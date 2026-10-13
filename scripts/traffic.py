"""Send paced demo traffic to the scoring service, so that the dashboard has data.

    python scripts/traffic.py --profile normal
    python scripts/traffic.py --profile injection-burst --base-url <https url>

Profiles:
    normal            golden answers across the five levels and both competencies, with a
                      fairness answer every fifth request (30 requests by default)
    injection-burst   mostly injected answers, with a clean one every fourth request
                      (12 requests by default)

Every answer is a `dev` row of the evaluation datasets. A `holdout` row is never read
into a plan, so it can never be sent.

The demo token comes from the `DEMO_TOKEN` environment variable and is never printed.
One line is printed per request: status, score, review reasons, flags and latency. No
answer, rationale, quote, token or URL is printed.

The app allows 10 requests a minute from one address and answers 429 above that, so the
default pace is 6 a minute. On a 429 the script waits as long as the reply asks and tries
the same request again. It stops at once on a 401 and after three failed requests in a
row: no reply, or any status that is not a 2xx. A redirect is never followed, so the
token goes only to the address given, and a 3xx counts as a failed request.

Every request makes three model calls, so a run costs money: about 0.004 GBP a request
at the prices in `config/prices.yaml`. Keep runs to the size the dashboard needs.

Exit codes: 0 when every request returned 200; 1 when a request did not, or the run
stopped early; 2 when the run could not start or the token was refused.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "evals" / "datasets"
DEMO_TOKEN_HEADER = "X-Demo-Token"
SCORE_PATH = "/api/score"
SCORE_TIMEOUT_SECONDS = 90.0

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_COUNTS = {"normal": 30, "injection-burst": 12}
DEFAULT_RATE_PER_MINUTE = 6.0
APP_LIMIT_PER_MINUTE = 10.0  # the app's own limit per address (spec C4)
MAX_COUNT = 200

FAIRNESS_EVERY = 5  # normal: every fifth request is a fairness answer
CLEAN_EVERY = 4  # injection-burst: every fourth request is a clean answer

MAX_BACKOFFS = 3  # waits on a 429 for one request before the run stops
DEFAULT_BACKOFF_SECONDS = 60.0
MAX_BACKOFF_SECONDS = 120.0
MAX_FAILURES_IN_A_ROW = 3

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SAFE_WORD = re.compile(r"[a-z0-9_]{1,40}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect, so the demo token is never sent on to another address.

    With no new request to follow, the 3xx reply is raised as an HTTP error and counts
    as a failed request like any other reply that is not a 200.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# A request to this machine never goes through a system proxy; any other request uses
# the system's proxy settings. Neither follows a redirect.
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
_REMOTE = urllib.request.build_opener(_NoRedirect)


class TrafficError(Exception):
    """The run cannot start (bad arguments, missing token, no usable rows)."""


@dataclass(frozen=True)
class Sample:
    """One request to send. `row_id` and `source` are printed; the payload never is."""

    row_id: str
    source: str
    payload: dict


@dataclass
class Reply:
    status: int
    body: dict
    seconds: float
    retry_after: float | None = None


@dataclass
class Summary:
    planned: int
    statuses: Counter = field(default_factory=Counter)
    latencies: list[float] = field(default_factory=list)
    backoffs: int = 0
    reviews: int = 0
    stopped: str | None = None

    @property
    def sent(self) -> int:
        return sum(self.statuses.values())

    def exit_code(self) -> int:
        if self.stopped == "token_refused":
            return 2
        if self.stopped or self.statuses.get(200, 0) != self.planned:
            return 1
        return 0


# --- The samples: `dev` rows only ----------------------------------------------------------


def dev_rows(file_name: str) -> list[dict]:
    """The rows of one dataset file whose `split` is `dev`. Nothing else is ever returned."""
    rows: list[dict] = []
    with (DATASETS / file_name).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("split") == "dev":
                rows.append(row)
    return rows


def _sample(row: dict, source: str, answer_key: str = "answer", suffix: str = "") -> Sample:
    return Sample(
        row_id=f"{row['id']}{suffix}",
        source=source,
        payload={
            "competency_id": row["competency_id"],
            "question": row["question"],
            "answer": row[answer_key],
        },
    )


def _round_robin(rows: list[dict], group_key: Callable[[dict], object]) -> list[dict]:
    """Order rows so that each group is visited once before any group is visited twice."""
    seen: Counter = Counter()
    ranked = []
    for position, row in enumerate(rows):
        group = group_key(row)
        ranked.append((seen[group], position, row))
        seen[group] += 1
    return [row for _, _, row in sorted(ranked, key=lambda item: item[:2])]


def golden_samples() -> list[Sample]:
    """Golden `dev` answers. The first ten cover every level and both competencies."""
    rows = sorted(dev_rows("golden.jsonl"), key=lambda row: (row["label"], row["competency_id"]))
    rows = _round_robin(rows, lambda row: (row["competency_id"], row["label"]))
    return [_sample(row, "golden") for row in rows]


def fairness_samples() -> list[Sample]:
    """Both answers of every fairness `dev` pair: first answers, then second ones.

    Pairs are ordered so that every pair type is visited before one is repeated.
    """
    rows = _round_robin(dev_rows("fairness_pairs.jsonl"), lambda row: row.get("pair_type"))
    return [_sample(row, "fairness", "answer_a", "/a") for row in rows] + [
        _sample(row, "fairness", "answer_b", "/b") for row in rows
    ]


def injection_samples() -> tuple[list[Sample], list[Sample]]:
    """Injected and clean `dev` answers. Injected ones visit every group before repeating one."""
    rows = dev_rows("injection.jsonl")
    injected = _round_robin(
        [row for row in rows if row.get("role") == "injected"], lambda row: row["group"]
    )
    clean = [row for row in rows if row.get("role") == "clean"]
    return (
        [_sample(row, "injection") for row in injected],
        [_sample(row, "clean") for row in clean],
    )


def _mix(count: int, main: list[Sample], other: list[Sample], other_every: int) -> list[Sample]:
    """`count` samples: every `other_every`-th from `other`, the rest from `main`, cycling."""
    if not main or not other:
        raise TrafficError("the datasets hold no dev rows for this profile")
    plan: list[Sample] = []
    main_used = other_used = 0
    for position in range(1, count + 1):
        if position % other_every == 0:
            plan.append(other[other_used % len(other)])
            other_used += 1
        else:
            plan.append(main[main_used % len(main)])
            main_used += 1
    return plan


def build_plan(profile: str, count: int) -> list[Sample]:
    """The requests of one run, in order. The same arguments always give the same plan."""
    if profile == "normal":
        return _mix(count, golden_samples(), fairness_samples(), FAIRNESS_EVERY)
    if profile == "injection-burst":
        injected, clean = injection_samples()
        return _mix(count, injected, clean, CLEAN_EVERY)
    raise TrafficError(f"unknown profile {profile!r}")


# --- One request ---------------------------------------------------------------------------


def _retry_after(value: str | None) -> float | None:
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and seconds >= 0 else None


def send(base_url: str, payload: dict, token: str, timeout: float | None = None) -> Reply:
    """One score request. A refused or dropped connection or a timeout is reported as status 0.

    A redirect is never followed: the reply comes back with its own 3xx status.
    """
    timeout = SCORE_TIMEOUT_SECONDS if timeout is None else timeout
    request = urllib.request.Request(
        base_url + SCORE_PATH,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            DEMO_TOKEN_HEADER: token,
        },
        method="POST",
    )
    retry_after = None
    local = urllib.parse.urlsplit(base_url).hostname in LOCAL_HOSTS
    opener = _LOCAL if local else _REMOTE
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
        retry_after = _retry_after(error.headers.get("Retry-After"))
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
        return Reply(0, {}, time.monotonic() - started)
    seconds = time.monotonic() - started
    try:
        body = json.loads(raw)
    except ValueError:
        body = {}
    return Reply(status, body if isinstance(body, dict) else {}, seconds, retry_after)


def _word(value: object) -> str:
    """A reply value as a short identifier, or `?`. Free text from a reply is never printed."""
    return value if isinstance(value, str) and _SAFE_WORD.fullmatch(value) else "?"


def describe(reply: Reply) -> str:
    """Metadata of one reply: status, score, review reasons, flags and latency. Never text."""
    latency = f"latency_ms={round(reply.seconds * 1000)}"
    body = reply.body
    if reply.status != 200:
        error = body.get("error")
        code = _word(error.get("code")) if isinstance(error, dict) else "-"
        return f"status={reply.status} error={code} {latency}"
    score = body.get("score")
    review = body.get("needs_human_review")
    reasons = [_word(item) for item in body.get("review_reasons") or []]
    flags = body.get("flags") if isinstance(body.get("flags"), dict) else {}
    raised = []
    for name, value in flags.items():
        if value is True:
            raised.append(_word(name))
        elif isinstance(value, int) and not isinstance(value, bool) and value > 0:
            raised.append(f"{_word(name)}={value}")
    return (
        f"status=200 score={score if isinstance(score, int) else '-'} "
        f"review={review if isinstance(review, bool) else '-'} "
        f"reasons={','.join(reasons) or '-'} flags={','.join(raised) or '-'} {latency}"
    )


# --- The run -------------------------------------------------------------------------------


def backoff_seconds(retry_after: float | None) -> float:
    """How long to wait after a 429: what the reply asks for, within sensible bounds."""
    wanted = DEFAULT_BACKOFF_SECONDS if retry_after is None else retry_after
    return min(max(wanted, 1.0), MAX_BACKOFF_SECONDS)


def percentile(values: list[float], percent: float) -> float:
    """Nearest-rank percentile of a list that is not empty."""
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100.0 * len(ordered)))
    return ordered[rank - 1]


def run(
    base_url: str,
    token: str,
    plan: list[Sample],
    rate_per_minute: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    send_request: Callable[[str, dict, str], Reply] = send,
) -> Summary:
    """Send the plan at the given pace. Prints one line per request and returns the totals."""
    interval = 60.0 / rate_per_minute
    summary = Summary(planned=len(plan))
    failures_in_a_row = 0
    next_start = clock()

    for number, sample in enumerate(plan, 1):
        wait = next_start - clock()
        if wait > 0:
            sleep(wait)
        next_start = clock() + interval
        label = (
            f"{number:03d} row={sample.row_id} source={sample.source} "
            f"competency={sample.payload['competency_id']}"
        )

        reply = send_request(base_url, sample.payload, token)
        backoffs = 0
        while reply.status == 429 and backoffs < MAX_BACKOFFS:
            backoffs += 1
            summary.backoffs += 1
            pause = backoff_seconds(reply.retry_after)
            print(
                f"{label} status=429 rate limited, waiting {round(pause)} s "
                f"(wait {backoffs} of {MAX_BACKOFFS})",
                flush=True,
            )
            sleep(pause)
            next_start = clock() + interval
            reply = send_request(base_url, sample.payload, token)

        summary.statuses[reply.status] += 1
        if reply.status == 200:
            summary.latencies.append(reply.seconds)
            summary.reviews += reply.body.get("needs_human_review") is True
        print(f"{label} {describe(reply)}", flush=True)

        if reply.status == 401:
            summary.stopped = "token_refused"
        elif reply.status == 429:
            summary.stopped = "still_rate_limited"
        elif not 200 <= reply.status < 300:
            # No reply, a redirect, a 4xx such as 400, 403 or 404, or a 5xx.
            failures_in_a_row += 1
            if failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
                summary.stopped = "repeated_failures"
        else:
            failures_in_a_row = 0
        if summary.stopped:
            break
    return summary


def print_summary(profile: str, summary: Summary) -> None:
    statuses = ",".join(f"{status}:{count}" for status, count in sorted(summary.statuses.items()))
    line = (
        f"TRAFFIC: {'STOPPED ' + summary.stopped if summary.stopped else 'DONE'} "
        f"profile={profile} sent={summary.sent} of {summary.planned} "
        f"statuses={statuses or '-'} backoffs={summary.backoffs} reviews={summary.reviews}"
    )
    if summary.latencies:
        line += (
            f" latency_p50_ms={round(statistics.median(summary.latencies) * 1000)}"
            f" latency_p95_ms={round(percentile(summary.latencies, 95) * 1000)}"
        )
    print(line, flush=True)


# --- Command line --------------------------------------------------------------------------


def checked_base_url(value: str) -> str:
    """The base URL without a trailing slash. Plain http is accepted for this machine only."""
    base_url = value.strip().rstrip("/")
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme == "https" and parts.hostname:
        return base_url
    if parts.scheme == "http" and parts.hostname in LOCAL_HOSTS:
        return base_url
    raise TrafficError("the base URL must start with https://, or be http on this machine")


def main(
    argv: list[str] | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    parser = argparse.ArgumentParser(description="Send paced demo traffic to the scoring service.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="where the app is")
    parser.add_argument("--profile", choices=sorted(DEFAULT_COUNTS), default="normal")
    parser.add_argument("--count", type=int, help="requests to send (30 normal, 12 burst)")
    parser.add_argument(
        "--rate-per-minute",
        type=float,
        default=DEFAULT_RATE_PER_MINUTE,
        help="pace; the app allows 10 a minute from one address",
    )
    arguments = parser.parse_args(argv)
    profile = arguments.profile
    count = DEFAULT_COUNTS[profile] if arguments.count is None else arguments.count

    try:
        if not 1 <= count <= MAX_COUNT:
            raise TrafficError(f"--count must be from 1 to {MAX_COUNT}")
        rate = arguments.rate_per_minute
        if not 0 < rate <= APP_LIMIT_PER_MINUTE:
            raise TrafficError("--rate-per-minute must be above 0 and at most 10")
        base_url = checked_base_url(arguments.base_url)
        token = os.environ.get("DEMO_TOKEN", "").strip()
        if not token:
            raise TrafficError("DEMO_TOKEN is not set")
        plan = build_plan(profile, count)
    except TrafficError as error:
        print(f"TRAFFIC: NOT STARTED ({error})", flush=True)
        return 2

    local = urllib.parse.urlsplit(base_url).hostname in LOCAL_HOSTS
    minutes = (count - 1) / rate
    print(
        f"target: {'local' if local else 'remote'} app profile={profile} requests={count} "
        f"rate_per_minute={rate:g} about {minutes:.1f} min; each request is three model calls",
        flush=True,
    )
    try:
        summary = run(base_url, token, plan, rate, sleep=sleep, clock=clock)
    except KeyboardInterrupt:
        print("TRAFFIC: STOPPED interrupted", flush=True)
        return 1
    print_summary(profile, summary)
    return summary.exit_code()


if __name__ == "__main__":
    sys.exit(main())
