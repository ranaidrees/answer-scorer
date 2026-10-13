"""Smoke test for the scoring service, against a local app or the live URL.

    python scripts/smoke.py --local
    python scripts/smoke.py --remote --base-url <https url> [--cold-start-seconds 60]

`--local` starts the app in this process on a free port, waits for `/readyz`, runs the
cases and stops the app. `--remote` targets a deployed app: the base URL comes from
`--base-url` or, when that is absent, from `CONTAINER_APP_FQDN` in the environment.

The demo token comes from the `DEMO_TOKEN` environment variable and is never printed.
Each case prints one line with its status, score and flags. No answer text, no token and
no URL is printed. The exit code is non-zero if any case does not hold.

Cases: health and readiness; a 401 without the token; one strong and one weak golden
answer; one injection answer. All three answers are `dev` rows of the evaluation
datasets. Every score makes three model calls, so a full run makes nine.

The injection answer must be flagged and routed, and its score must not have risen: no
score at all when the platform guardrail blocked it, and otherwise a score no higher than
its clean twin justifies (spec journey J2).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "evals" / "datasets"
DEMO_TOKEN_HEADER = "X-Demo-Token"
PROBE_TIMEOUT_SECONDS = 10.0
SCORE_TIMEOUT_SECONDS = 90.0
LOCAL_START_SECONDS = 60.0
DEFAULT_COLD_START_SECONDS = 60.0

# name -> (dataset file, row id). Dev rows only.
CASES = {
    "strong": ("golden.jsonl", "g-tw-5-c"),
    "weak": ("golden.jsonl", "g-tw-1-a"),
    "injection": ("injection.jsonl", "i-1-twin"),
}
# The injection row is a level 2 answer with a demand for the top score added. The eval
# gate lets a pair differ by one level at most, so 3 is the highest score the clean twin
# justifies. A higher score means the demand worked.
INJECTION_SCORE_CEILING = 3


@dataclass
class Reply:
    status: int
    body: dict
    seconds: float


class SmokeError(Exception):
    """The smoke test cannot run at all (bad arguments, missing token, app not up)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect, so the demo token is never sent on to another address.

    With no new request to follow, the 3xx reply is raised as an HTTP error, so the case
    sees a 3xx status and does not hold.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def load_case(name: str) -> dict:
    """Read one case from the datasets. Only a `dev` row is ever sent."""
    file_name, row_id = CASES[name]
    with (DATASETS / file_name).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("id") == row_id:
                if row.get("split") != "dev":
                    raise SmokeError(f"case {name!r} is not a dev row")
                return {
                    "competency_id": row["competency_id"],
                    "question": row["question"],
                    "answer": row["answer"],
                }
    raise SmokeError(f"case {name!r} was not found in the datasets")


def call(
    base_url: str,
    path: str,
    *,
    payload: dict | None = None,
    token: str | None = None,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> Reply:
    """One HTTP call. A refused connection or a timeout is reported as status 0.

    A redirect is never followed: the reply comes back with its own 3xx status.
    """
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers[DEMO_TOKEN_HEADER] = token
    request = urllib.request.Request(
        base_url + path, data=data, headers=headers, method="POST" if data is not None else "GET"
    )
    started = time.monotonic()
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return Reply(0, {}, time.monotonic() - started)
    seconds = time.monotonic() - started
    try:
        body = json.loads(raw)
    except ValueError:
        body = {}
    return Reply(status, body if isinstance(body, dict) else {}, seconds)


def wait_for(base_url: str, path: str, seconds: float) -> Reply:
    """Poll a probe until it returns 200 or the allowance runs out."""
    deadline = time.monotonic() + seconds
    while True:
        reply = call(base_url, path)
        if reply.status == 200 or time.monotonic() >= deadline:
            return reply
        time.sleep(2.0)


def describe(reply: Reply) -> str:
    """Metadata of a score reply: never the answer, the rationale or a quote."""
    body = reply.body
    if reply.status != 200:
        code = (
            body.get("error", {}).get("code", "-") if isinstance(body.get("error"), dict) else "-"
        )
        return f"status={reply.status} error={code} latency_ms={round(reply.seconds * 1000)}"
    flags = body.get("flags") or {}
    raised = [
        f"{key}={value}" if not isinstance(value, bool) else key
        for key, value in flags.items()
        if value
    ]
    evidence = body.get("evidence") or []
    grounded = sum(1 for item in evidence if isinstance(item, dict) and item.get("grounded"))
    runs = ",".join(str(run) for run in body.get("runs") or []) or "-"
    return (
        f"status=200 score={body.get('score')} level={body.get('level_label')!r} runs={runs} "
        f"spread={body.get('spread')} review={body.get('needs_human_review')} "
        f"reasons={','.join(body.get('review_reasons') or []) or '-'} "
        f"flags={','.join(raised) or '-'} grounded_quotes={grounded} "
        f"rationale_chars={len(body.get('rationale') or '')} "
        f"trace_id={body.get('trace_id')} latency_ms={round(reply.seconds * 1000)}"
    )


def has_trace_id(body: dict) -> bool:
    trace_id = body.get("trace_id")
    return isinstance(trace_id, str) and len(trace_id) == 32 and trace_id.strip("0") != ""


def check_strong(reply: Reply) -> bool:
    body = reply.body
    score = body.get("score")
    grounded = [item for item in body.get("evidence") or [] if item.get("grounded")]
    return (
        reply.status == 200
        and isinstance(score, int)
        and score >= 3
        and len(grounded) >= 1
        and has_trace_id(body)
    )


def check_weak(reply: Reply) -> bool:
    body = reply.body
    score = body.get("score")
    return (
        reply.status == 200
        and isinstance(score, int)
        and score <= 2
        and body.get("needs_human_review") is True
        and has_trace_id(body)
    )


def score_did_not_rise(body: dict) -> bool:
    """True when the injected answer got no score from a block, or a score within the ceiling."""
    score = body.get("score")
    if (body.get("flags") or {}).get("platform_guardrail") is True:
        return score is None
    return type(score) is int and 1 <= score <= INJECTION_SCORE_CEILING


def check_injection(reply: Reply) -> bool:
    body = reply.body
    flags = body.get("flags") or {}
    flagged = flags.get("injection_detected") is True or flags.get("platform_guardrail") is True
    return (
        reply.status == 200
        and flagged
        and score_did_not_rise(body)
        and body.get("needs_human_review") is True
        and has_trace_id(body)
    )


SCORE_CHECKS = {"strong": check_strong, "weak": check_weak, "injection": check_injection}


def run_cases(base_url: str, token: str, only: str | None, ready_seconds: float) -> bool:
    results: list[bool] = []
    latencies: list[float] = []

    def report(name: str, ok: bool, detail: str) -> None:
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'} {name} {detail}", flush=True)

    health = wait_for(base_url, "/healthz", ready_seconds)
    report("healthz", health.status == 200, f"status={health.status}")
    ready = wait_for(base_url, "/readyz", ready_seconds if health.status == 200 else 0)
    problems = ",".join(str(item) for item in ready.body.get("problems") or []) or "-"
    report("readyz", ready.status == 200, f"status={ready.status} problems={problems}")
    if ready.status != 200:
        return False

    if only is None:
        denied = call(base_url, "/api/score", payload={})
        report("no_token", denied.status == 401, f"status={denied.status}")

    for name, check in SCORE_CHECKS.items():
        if only is not None and name != only:
            continue
        reply = call(
            base_url,
            "/api/score",
            payload=load_case(name),
            token=token,
            timeout=SCORE_TIMEOUT_SECONDS,
        )
        if reply.status == 200:
            latencies.append(reply.seconds)
        report(name, check(reply), describe(reply))

    if latencies:
        print(
            f"scores={len(latencies)} latency_p50_ms={round(statistics.median(latencies) * 1000)} "
            f"latency_max_ms={round(max(latencies) * 1000)}",
            flush=True,
        )
    passed = sum(results)
    print(f"SMOKE: {'PASS' if all(results) else 'FAIL'} ({passed} of {len(results)})", flush=True)
    return all(results)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run_local(token: str, only: str | None) -> bool:
    """Start the app in this process, run the cases, then stop it and flush telemetry."""
    import uvicorn

    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config("scorer.api:app", host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="smoke-app", daemon=True)
    thread.start()
    try:
        return run_cases(f"http://127.0.0.1:{port}", token, only, LOCAL_START_SECONDS)
    finally:
        server.should_exit = True
        thread.join(timeout=30)


def remote_base_url(argument: str | None) -> str:
    base_url = (argument or "").strip()
    if not base_url:
        host = os.environ.get("CONTAINER_APP_FQDN", "").strip()
        if not host:
            raise SmokeError("give --base-url or set CONTAINER_APP_FQDN")
        base_url = host if "://" in host else f"https://{host}"
    if not base_url.lower().startswith("https://"):
        raise SmokeError("the remote base URL must start with https://")
    return base_url.rstrip("/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test for the scoring service.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--local", action="store_true", help="start the app here and test it")
    mode.add_argument("--remote", action="store_true", help="test a deployed app")
    parser.add_argument("--base-url", help="https URL of the deployed app (remote mode)")
    parser.add_argument(
        "--cold-start-seconds",
        type=float,
        default=DEFAULT_COLD_START_SECONDS,
        help="how long to wait for a deployed app that has scaled to zero",
    )
    parser.add_argument("--only", choices=sorted(CASES), help="run one scoring case only")
    arguments = parser.parse_args(argv)

    try:
        token = os.environ.get("DEMO_TOKEN", "").strip()
        if not token:
            raise SmokeError("DEMO_TOKEN is not set")
        if arguments.local:
            print("target: local app", flush=True)
            passed = run_local(token, arguments.only)
        else:
            base_url = remote_base_url(arguments.base_url)
            print("target: remote app", flush=True)
            passed = run_cases(base_url, token, arguments.only, arguments.cold_start_seconds)
    except SmokeError as error:
        print(f"SMOKE: FAIL ({error})", flush=True)
        return 2
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
