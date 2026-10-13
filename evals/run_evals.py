"""The eval runner (spec section 7): `python -m evals.run_evals`, behind `uv run poe eval`.

It loads the four datasets, builds one input per golden row, two per fairness pair, one
per injection row and one per edge case, shuffles them with a logged seed, scores each
through the real pipeline (`scorer.pipeline.score_answer`), computes the metrics and the
gate, and writes a Markdown and a JSON report.

    uv run poe eval                         full run against the live deployment
    uv run poe eval --fake                  full run, offline, with a fake model client
    uv run poe eval --fake-weak             the same with a fake that should breach the gate
    uv run poe eval --suite golden --split dev    a partial run, while tuning

Only a full run (every suite, every split) can pass the gate, and only when it holds
every dataset in full. A partial run says that it is partial and never prints
"GATE: PASS". A run with a fake model says in its last line that it is a dry run.

An input the model could not score, because a call failed or a reply was unusable, is
tried again, and every extra attempt is counted and shown in the report. If an input
keeps failing, or the run needs more than `MAX_RETRY_ATTEMPTS_PER_RUN` extra attempts in
all, the run stops: it writes no report, exits with code 2 and never invents a score.
The dataset files are data. Their text is sent to the scorer and nowhere else: no answer,
question, rationale or quote is printed, logged or written to a report.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import inspect
import json
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evals.metrics import REQUIRED_SIZES, Evaluation, evaluate, validate_thresholds
from evals.report import (
    DECISION_INFORMED,
    RETRY_LABEL,
    console_lines,
    gate_line,
    render_markdown,
    retry_text,
)
from scorer.config import Settings, load_prompt
from scorer.model_client import (
    MAX_COMPLETION_TOKENS,
    REASONING_EFFORT,
    ModelClient,
    ModelResult,
    ModelUnavailableError,
)
from scorer.pipeline import ANSWER_CLOSE, ANSWER_OPEN, RUNS, ScoringError, score_answer
from scorer.schemas import ScoreRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = REPO_ROOT / "evals" / "datasets"
THRESHOLDS_PATH = REPO_ROOT / "evals" / "thresholds.yaml"
REPORTS_DIR = REPO_ROOT / "evals" / "reports"

SUITES = ("golden", "fairness", "injection", "edge")
DATASET_FILES = {
    "golden": "golden.jsonl",
    "fairness": "fairness_pairs.jsonl",
    "injection": "injection.jsonl",
    "edge": "edge_cases.jsonl",
}
SPLITS = ("dev", "holdout", "all")

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

DEFAULT_CONCURRENCY = 4
# The deployment has 100 thousand tokens per minute. One input is three calls of roughly
# 1,650 input tokens each (measured offline at four characters per token) plus up to 600
# output tokens, so about 14 inputs fit in a minute. Starting at most 12 a minute keeps a
# full run clear of throttling (decision S4b-6). The fake clients are not paced.
DEFAULT_PER_MINUTE = 12.0

# Fixed by the spec (FR-4 step 6) and printed in every report. The values are the live
# client's and the pipeline's own constants, so a report cannot say one thing while the
# client sends another. The live client passes no `temperature` and no `top_p`.
FIXED_INFERENCE = {
    "runs_per_answer": RUNS,
    "reasoning_effort": REASONING_EFFORT,
    "max_completion_tokens": MAX_COMPLETION_TOKENS,
    "temperature": "not set (the model family does not accept them)",
}

LIVE = "live"
FAKE = "fake"
FAKE_WEAK = "fake-weak"

FAKE_MID_SCORE = 3
FAKE_TOKENS_OUT = 60
FAKE_QUOTE_CHARS = 70
FAKE_RATIONALE = (
    "The candidate describes specific actions and their result, which match the "
    "descriptors for this level."
)
WEAK_PARAPHRASE = (
    "The candidate worked well with other people and reached a good result in the end."
)


class EvalRunError(Exception):
    """The run could not finish. There is no report and no gate result."""


# --- Datasets and inputs -------------------------------------------------------------------


@dataclass(frozen=True)
class EvalItem:
    """One input to the scorer. `meta` holds labels and categories, never text."""

    item_id: str
    suite: str
    row_id: str
    split: str
    competency_id: str
    question: str = field(repr=False)
    answer: str = field(repr=False)
    meta: Mapping[str, object] = field(default_factory=dict)


def load_rows(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvalRunError(f"dataset {path.name} cannot be read: {type(error).__name__}") from None


def load_datasets(folder: Path = DATASETS_DIR) -> dict[str, list[dict]]:
    return {suite: load_rows(folder / name) for suite, name in DATASET_FILES.items()}


def _item(suite: str, row: Mapping, item_id: str, answer: str, **meta: object) -> EvalItem:
    return EvalItem(
        item_id=item_id,
        suite=suite,
        row_id=row["id"],
        split=row["split"],
        competency_id=row["competency_id"],
        question=row["question"],
        answer=answer,
        meta=meta,
    )


def build_items(
    datasets: Mapping[str, Sequence[Mapping]], suites: Sequence[str] = SUITES, split: str = "all"
) -> list[EvalItem]:
    """One input per golden row, two per fairness pair, one per injection row and edge case."""
    items: list[EvalItem] = []
    for suite in SUITES:
        if suite not in suites:
            continue
        for row in datasets[suite]:
            if split != "all" and row["split"] != split:
                continue
            if suite == "golden":
                items.append(_item(suite, row, row["id"], row["answer"], label=row["label"]))
            elif suite == "fairness":
                for side in ("a", "b"):
                    items.append(
                        _item(
                            suite,
                            row,
                            f"{row['id']}:{side}",
                            row[f"answer_{side}"],
                            pair_type=row["pair_type"],
                            side=side,
                        )
                    )
            elif suite == "injection":
                items.append(
                    _item(
                        suite,
                        row,
                        row["id"],
                        row["answer"],
                        group=row["group"],
                        role=row["role"],
                        injection_type=row["injection_type"],
                        variant=row["variant"],
                    )
                )
            else:
                items.append(
                    _item(
                        suite,
                        row,
                        row["id"],
                        row["answer"],
                        case=row["case"],
                        expected=row["expected"],
                    )
                )
    return items


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, dict[str, float]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return validate_thresholds(raw)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError) as error:
        raise EvalRunError(f"thresholds cannot be used: {error}") from None


# --- Fake model clients, for offline dry runs ----------------------------------------------


def _answer_in(messages: Sequence[Mapping[str, str]]) -> str:
    """The prepared answer, as the model would see it between its delimiters."""
    user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    # The pipeline neutralises delimiter text inside the answer, so the first closing tag
    # after the opening tag is the real one. The rule that follows names the tags again.
    start = user.index(ANSWER_OPEN) + len(ANSWER_OPEN)
    return user[start : user.index(ANSWER_CLOSE, start)].strip()


def _verbatim_quotes(answer: str) -> list[str]:
    """Two quotes copied word for word from the answer, so that grounding passes."""
    if len(answer) <= FAKE_QUOTE_CHARS:
        return [answer]
    first = answer[:FAKE_QUOTE_CHARS].rsplit(" ", 1)[0]
    last = answer[-FAKE_QUOTE_CHARS:].split(" ", 1)[-1]
    return [quote for quote in (first, last) if quote.strip()]


def fake_output(item: EvalItem, answer: str, *, weak: bool = False) -> dict:
    """What the fake model returns for one input. Deterministic.

    Normal mode: a golden answer gets its label; pair and injection answers get a fixed mid
    score; an edge case gets `off_topic` or a low score where its `expected` object asks
    for one; quotes are verbatim. Weak mode imitates a prompt that paraphrases and
    flatters: quotes are reworded, golden scores go up by one, an injected answer gets the
    top score and an edge case gets a high one.
    """
    off_topic = False
    if item.suite == "golden":
        score = int(item.meta["label"])
    elif item.suite == "edge":
        expected = item.meta["expected"]
        options = [expected, *expected.get("any_of", [])]
        off_topic = any(option.get("off_topic") for option in options)
        ceilings = [option["max_score"] for option in options if "max_score" in option]
        score = min(ceilings) if ceilings else 1
    else:
        score = FAKE_MID_SCORE
    evidence = _verbatim_quotes(answer)

    if weak:
        evidence = [WEAK_PARAPHRASE]
        if item.suite == "golden":
            score = min(5, score + 1)
        elif item.suite == "edge":
            score, off_topic = 4, False
        elif item.meta.get("role") == "injected":
            score = 5

    return {
        "evidence": evidence,
        "rationale": FAKE_RATIONALE,
        "off_topic": off_topic,
        "score": score,
    }


class FakeEvalClient:
    """A deterministic stand-in for the model. It makes no network call and costs nothing.

    Token counts are simulated (about four characters per token) so that the totals and
    the report can be exercised offline.
    """

    def __init__(self, item: EvalItem, *, weak: bool = False) -> None:
        self._item = item
        self._weak = weak

    async def complete(self, messages: list[dict[str, str]], *, schema: dict) -> ModelResult:
        characters = sum(len(message["content"]) for message in messages)
        return ModelResult(
            parsed=fake_output(self._item, _answer_in(messages), weak=self._weak),
            tokens_in=characters // 4,
            tokens_out=FAKE_TOKENS_OUT,
        )


class _CountingClient:
    """Counts the model calls made for one input, to check `model_called` on edge cases."""

    def __init__(self, inner: ModelClient) -> None:
        self._inner = inner
        self.calls = 0

    async def complete(self, messages: list[dict[str, str]], *, schema: dict) -> ModelResult:
        self.calls += 1
        return await self._inner.complete(messages, schema=schema)


ClientFactory = Callable[[EvalItem], ModelClient]


def _live_client_factory(settings: Settings) -> tuple[ClientFactory, ModelClient]:
    """One shared live client. Imported here so that offline runs never need it."""
    try:
        from scorer.model_client import build_model_client
    except ImportError:
        raise EvalRunError(
            "the live model client is not in this checkout; use --fake for an offline dry run"
        ) from None
    try:
        client = build_model_client(settings)
    except Exception as error:
        raise EvalRunError(
            f"the live model client could not be built: {type(error).__name__}"
        ) from None
    return (lambda item: client), client


async def _close(client: object) -> None:
    closer = getattr(client, "aclose", None) or getattr(client, "close", None)
    if callable(closer):
        result = closer()
        if inspect.isawaitable(result):
            await result


# --- Scoring -------------------------------------------------------------------------------


async def score_item(item: EvalItem, client: ModelClient, settings: Settings) -> dict:
    """Score one input through the pipeline. The result holds no text.

    A `ScoringError` is the pipeline's 400: it is recorded with its status and code. A
    model failure is not caught here, so it stops the run.
    """
    counting = _CountingClient(client)
    result: dict = {
        "item_id": item.item_id,
        "suite": item.suite,
        "row_id": item.row_id,
        "split": item.split,
        "competency_id": item.competency_id,
        **item.meta,
    }
    request = ScoreRequest(
        competency_id=item.competency_id, question=item.question, answer=item.answer
    )
    try:
        outcome = await score_answer(request, client=counting, settings=settings)
    except ScoringError as error:
        result.update(
            status=error.status,
            error=error.code,
            score=None,
            runs=[],
            spread=None,
            needs_human_review=None,
            review_reasons=[],
            flags=None,
            quotes_grounded=0,
            quotes_ungrounded=0,
            tokens_in=0,
            tokens_out=0,
            model_version=None,
        )
    else:
        response = outcome.response
        result.update(
            status=200,
            error=None,
            score=response.score,
            runs=list(response.runs),
            spread=response.spread,
            needs_human_review=response.needs_human_review,
            review_reasons=list(response.review_reasons),
            flags=response.flags.model_dump(),
            quotes_grounded=len(response.evidence),
            quotes_ungrounded=response.flags.ungrounded_quotes,
            tokens_in=outcome.tokens_in,
            tokens_out=outcome.tokens_out,
            model_version=outcome.model_version,
        )
    result["model_calls"] = counting.calls
    return result


# A full run is about 270 calls over eight minutes; one transient model failure should not
# throw it all away. An input is tried at most this many times, waiting between attempts.
ITEM_ATTEMPTS = 3
ITEM_RETRY_WAITS: tuple[float, ...] = (10.0, 30.0)
# `ModelUnavailableError` is also what a cut-off reply, a reply that is not valid JSON and
# a reply that misses the schema raise. The live app answers each of those with an error,
# so a prompt that makes replies unusable must not be able to retry its way to a finished
# run. One run makes at most this many extra attempts in all, across every input; needing
# one more stops it (decision S4c-9).
MAX_RETRY_ATTEMPTS_PER_RUN = 3

RETRY_FAILED_CALL = "failed call"
RETRY_UNUSABLE_REPLY = "unusable reply"
RETRY_CAUSE_NOT_KNOWN = "model failure or unusable reply"
RETRY_CAUSES = (RETRY_FAILED_CALL, RETRY_UNUSABLE_REPLY, RETRY_CAUSE_NOT_KNOWN)

# The fixed texts that `scorer.model_client` and `scorer.pipeline` raise. They are matched
# here, and nothing is changed there, so the scorer the stability proof ran on stays as it
# was. A text that is not listed is never guessed at: its cause is reported as not known.
_UNUSABLE_REPLY_PREFIX = "the reply"
_UNUSABLE_REPLY_TEXTS = frozenset({"a model call returned output that is not valid"})
_FAILED_CALL_TEXTS = frozenset(
    {
        "a model call failed",
        "the call failed",
        "the call failed after one retry",
        "the call was not made",
        "the request was rejected",
    }
)


def retry_cause(error: BaseException) -> str:
    """Why an input has to be tried again: a failed call, an unusable reply, or not known.

    Read from the fixed text of the error and of the errors it was raised from. An
    unusable reply anywhere in that chain wins, because the pipeline may wrap it as a
    failed call. Only the category is kept: the text of an error is never stored.
    """
    cause = RETRY_CAUSE_NOT_KNOWN
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ModelUnavailableError):
            text = str(current)
            if text.startswith(_UNUSABLE_REPLY_PREFIX) or text in _UNUSABLE_REPLY_TEXTS:
                return RETRY_UNUSABLE_REPLY
            if text in _FAILED_CALL_TEXTS:
                cause = RETRY_FAILED_CALL
        current = current.__cause__
    return cause


def retries_by_cause(retries: Sequence[Mapping]) -> dict[str, int]:
    """Extra attempts counted by cause, in a fixed order, leaving out a cause with none."""
    counts = Counter(entry["cause"] for entry in retries)
    return {cause: counts[cause] for cause in RETRY_CAUSES if counts[cause]}


class _RetryCapExceeded(Exception):
    """The run needed one more extra attempt than `MAX_RETRY_ATTEMPTS_PER_RUN` allows."""

    def __init__(self, cause: str) -> None:
        super().__init__(cause)
        self.cause = cause


class _Pacer:
    """Starts at most `per_minute` inputs a minute. Zero means no limit."""

    def __init__(self, per_minute: float) -> None:
        self._interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if not self._interval:
            return
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self._interval


async def run_items(
    items: Sequence[EvalItem],
    client_for: ClientFactory,
    settings: Settings,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    per_minute: float = 0.0,
    progress: Callable[[int, int], None] | None = None,
    retried: list[str] | None = None,
    retry_log: list[dict] | None = None,
    retry_waits: Sequence[float] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[dict]:
    """Score every input, at most `concurrency` at a time, in the order given.

    An input the model could not score is tried again, up to `ITEM_ATTEMPTS` times with a
    wait in between. Each extra attempt appends the input's id to `retried` and its id and
    cause to `retry_log`. If the input still cannot be scored the run stops: no new input
    is started, and `EvalRunError` names the input that failed. The run also stops, without
    making the attempt, as soon as it needs more than `MAX_RETRY_ATTEMPTS_PER_RUN` extra
    attempts in all. No result is ever filled in for an input the model did not score.
    """
    retried = retried if retried is not None else []
    retry_log = retry_log if retry_log is not None else []
    retry_waits = ITEM_RETRY_WAITS if retry_waits is None else retry_waits
    results: list[dict | None] = [None] * len(items)
    pending = iter(enumerate(items))
    failures: list[tuple[EvalItem, BaseException]] = []
    pacer = _Pacer(per_minute)
    done = 0

    async def worker() -> None:
        nonlocal done
        for index, item in pending:
            if failures:
                return
            await pacer.wait()
            for attempt in range(1, ITEM_ATTEMPTS + 1):
                try:
                    result = await score_item(item, client_for(item), settings)
                except ModelUnavailableError as error:
                    # A model failure gives no score, so trying the same input again is not
                    # choosing between scores. Every attempt is counted in the report.
                    if attempt == ITEM_ATTEMPTS:
                        failures.append((item, error))
                        return
                    cause = retry_cause(error)
                    if len(retry_log) >= MAX_RETRY_ATTEMPTS_PER_RUN:
                        # Counted as it happens: the attempt over the cap is never made.
                        failures.append((item, _RetryCapExceeded(cause)))
                        return
                    retry_log.append({"item_id": item.item_id, "cause": cause})
                    retried.append(item.item_id)
                    await sleep(retry_waits[min(attempt, len(retry_waits)) - 1])
                    if failures:
                        return
                    continue
                except Exception as error:
                    failures.append((item, error))
                    return
                results[index] = result
                break
            done += 1
            if progress:
                progress(done, len(items))

    await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))

    if failures:
        item, error = failures[0]
        if isinstance(error, _RetryCapExceeded):
            made = ", ".join(
                f"{count} {cause}" for cause, count in retries_by_cause(retry_log).items()
            )
            # The input is not named: the finding is about the run, not about one row.
            raise EvalRunError(
                "the model failed or returned unusable replies too often: a run may make "
                f"at most {MAX_RETRY_ATTEMPTS_PER_RUN} extra attempts, {len(retry_log)} were "
                f"made ({made}) and one more was needed ({error.cause}), after {done} of "
                f"{len(items)} inputs were scored. That rate is itself a finding about the "
                "prompt or the model deployment: the live service answers each such request "
                "with an error"
            )
        cause = type(error.__cause__).__name__ if error.__cause__ else None
        if isinstance(error, ModelUnavailableError):
            reason = "the model was unavailable" + (f" ({cause})" if cause else "")
        else:
            reason = f"an unexpected error ({type(error).__name__})"
        raise EvalRunError(
            f"{reason} on input {item.item_id}, after {done} of {len(items)} inputs were scored"
        )
    return [result for result in results if result is not None]


# --- Report --------------------------------------------------------------------------------


def estimate_cost(tokens_in: int, tokens_out: int, prices_path: Path) -> dict:
    """Estimate the cost of a run from `config/prices.yaml`. Never guesses a price."""
    if not prices_path.is_file():
        return {"available": False, "reason": "config/prices.yaml is missing; tokens only"}
    try:
        prices = yaml.safe_load(prices_path.read_text(encoding="utf-8"))
        if prices["unit"] != "per_1m_tokens":
            raise ValueError("unit")
        amount = (tokens_in * float(prices["input"]) + tokens_out * float(prices["output"])) / 1e6
        return {
            "available": True,
            "amount": round(amount, 4),
            "currency": str(prices["currency"]),
            "basis": "every input token is priced as uncached, so this is an upper estimate",
            "source_url": str(prices["source_url"]),
            "retrieved": str(prices["retrieved"]),
        }
    except (OSError, UnicodeDecodeError, yaml.YAMLError, KeyError, TypeError, ValueError):
        return {"available": False, "reason": "config/prices.yaml cannot be read; tokens only"}


def _git_sha() -> str:
    candidate = os.environ.get("EVAL_GIT_SHA") or os.environ.get("GITHUB_SHA") or ""
    if not candidate:
        try:
            candidate = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            candidate = ""
    return candidate if re.fullmatch(r"[0-9a-f]{7,64}", candidate) else "unknown"


def _trigger() -> str:
    name = os.environ.get("GITHUB_EVENT_NAME", "")
    return name if re.fullmatch(r"[a-z_]{1,40}", name) else "local"


def build_report(
    *,
    results: Sequence[Mapping],
    evaluation: Evaluation,
    thresholds: Mapping,
    settings: Settings,
    suites: Sequence[str],
    split: str,
    seed: int,
    client: str,
    concurrency: int,
    duration_seconds: float,
    retries: Sequence[Mapping] = (),
) -> dict:
    """The report as a plain dict: every metric, threshold and per-row result, and no text.

    `retries` holds one entry per extra attempt, in the order they were made: the input's
    id and the cause, as `run_items` logged them.
    """
    prompt = load_prompt(settings)
    retried_ids = [entry["item_id"] for entry in retries]
    full = tuple(suites) == SUITES and split == "all"
    if not full:
        status = "not_evaluated"
    else:
        status = "pass" if evaluation.gate_passed else "fail"
    tokens_in = sum(result["tokens_in"] for result in results)
    tokens_out = sum(result["tokens_out"] for result in results)
    if client == LIVE:
        cost = estimate_cost(tokens_in, tokens_out, settings.config_dir / "prices.yaml")
    else:
        cost = {"available": False, "reason": "fake client: no model call was made, nothing spent"}
    versions = sorted({r["model_version"] for r in results if r.get("model_version")})
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "decision_informed": DECISION_INFORMED,
        "run": {
            "mode": "full" if full else "partial",
            "suites": list(suites),
            "split": split,
            "seed": seed,
            "trigger": _trigger(),
            "git_sha": _git_sha(),
            "client": client,
            "concurrency": concurrency,
            "inputs": len(results),
            "inputs_reaching_model": sum(result["model_calls"] > 0 for result in results),
            "model_calls": sum(result["model_calls"] for result in results),
            "duration_seconds": round(duration_seconds, 1),
            # Inputs the model could not score at first and that were tried again: ids
            # only, one per extra attempt. The same count is in the summary of the report.
            "retried_inputs": sorted(retried_ids),
            "retries": {
                "summary": f"{RETRY_LABEL}: {retry_text(len(retried_ids), len(set(retried_ids)))}",
                "attempts": len(retried_ids),
                "inputs": len(set(retried_ids)),
                "max_attempts_per_run": MAX_RETRY_ATTEMPTS_PER_RUN,
                "by_cause": retries_by_cause(retries),
                "attempts_in_order": [
                    {"item_id": entry["item_id"], "cause": entry["cause"]} for entry in retries
                ],
            },
        },
        "inference": {
            "model_deployment": settings.model_deployment,
            "model_version": ", ".join(versions) or settings.model_version,
            "prompt_version": prompt.version,
            "prompt_sha256": prompt.sha256,
            **FIXED_INFERENCE,
        },
        "gate": {"status": status, "breached": evaluation.breached},
        # Reasons the gate failed that are not a metric: a run short of a required size,
        # or a control that tripped without routing the answer.
        "gate_failures": [failure.as_dict() for failure in evaluation.failures],
        "metrics": [metric.as_dict() for metric in evaluation.metrics],
        "thresholds": {key: dict(value) for key, value in thresholds.items()},
        "misses": [miss.as_dict() for miss in evaluation.misses],
        "blocked_clean_answers": evaluation.blocked_clean,
        "usage": {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "simulated": client != LIVE,
            "cost": cost,
        },
        "results": [dict(result, order=order) for order, result in enumerate(results, start=1)],
    }


def write_report(report: Mapping, reports_dir: Path) -> tuple[Path, Path]:
    """Write `<UTC timestamp>.md` and `.json`, and append the Markdown to the job summary."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem, attempt = stamp, 1
    while (reports_dir / f"{stem}.md").exists() or (reports_dir / f"{stem}.json").exists():
        attempt += 1
        stem = f"{stamp}-{attempt}"
    markdown = render_markdown(report)
    markdown_path, json_path = reports_dir / f"{stem}.md", reports_dir / f"{stem}.json"
    markdown_path.write_text(markdown, encoding="utf-8", newline="\n")
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(markdown + "\n")
    return markdown_path, json_path


def _shown(path: Path) -> str:
    """A path relative to the repository where possible, so no local folder is printed."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _github_output(values: Mapping[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8", newline="\n") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in values.items())


# --- The `eval_run` custom event -----------------------------------------------------------


def eval_event_attributes(report: Mapping) -> dict:
    """Attributes of the `eval_run` event (spec section 8). Numbers and ids only."""
    run, inference, gate = report["run"], report["inference"], report["gate"]
    attributes: dict = {
        "git_sha": run["git_sha"],
        "prompt_version": inference["prompt_version"],
        "prompt_sha": inference["prompt_sha256"],
        "trigger": run["trigger"],
        "gate": gate["status"],
        "passed": gate["status"] == "pass",
        "breached": ",".join(gate["breached"]),
        "failures": ",".join(sorted({item["rule"] for item in report["gate_failures"]})),
        "seed": run["seed"],
        "model_deployment": inference["model_deployment"],
        "model_version": inference["model_version"],
        "inputs": run["inputs"],
        "model_calls": run["model_calls"],
        "tokens_in": report["usage"]["tokens_in"],
        "tokens_out": report["usage"]["tokens_out"],
    }
    for metric in report["metrics"]:
        if metric["value"] is not None:
            attributes[metric["id"]] = metric["value"]
        attributes[f"{metric['id']}_n"] = metric["n"]
        if metric["passed"] is not None:
            attributes[f"{metric['id']}_passed"] = metric["passed"]
    return attributes


def emit_eval_event(report: Mapping, settings: Settings) -> str:
    """Send one `eval_run` event. Returns what happened, for the console.

    Only a full run against the live model is recorded, so a dry run or a partial run can
    never put numbers on the dashboard. A problem here never changes the gate result.
    """
    if report["run"]["client"] != LIVE or report["run"]["mode"] != "full":
        return "not sent (only a full run against the live model is recorded)"
    try:
        from scorer.telemetry import configure_telemetry, emit_custom_event, flush_telemetry
    except ImportError:
        return "not sent (the telemetry module is not in this checkout)"
    try:
        if not configure_telemetry(settings):
            return "not sent (telemetry is not configured)"
        emit_custom_event("eval_run", eval_event_attributes(report))
        # The process ends straight after this, so the event is sent now and not left to
        # the exporter's exit hook.
        flush_telemetry()
    except Exception as error:
        return f"not sent ({type(error).__name__})"
    return "sent"


# --- Command line --------------------------------------------------------------------------


def _suites(value: str) -> tuple[str, ...]:
    chosen = [part.strip() for part in value.split(",") if part.strip()]
    unknown = [part for part in chosen if part not in SUITES]
    if not chosen or unknown:
        raise argparse.ArgumentTypeError(f"choose from: {', '.join(SUITES)}")
    return tuple(suite for suite in SUITES if suite in chosen)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run_evals",
        description="Run the eval suite and the gate. Only a full run can pass the gate.",
    )
    fakes = parser.add_mutually_exclusive_group()
    fakes.add_argument(
        "--fake", action="store_true", help="offline dry run with a fake model client"
    )
    fakes.add_argument(
        "--fake-weak",
        action="store_true",
        help="offline dry run with a fake that paraphrases quotes and inflates scores",
    )
    parser.add_argument(
        "--suite",
        type=_suites,
        default=SUITES,
        metavar="LIST",
        help="comma-separated suites to run: golden,fairness,injection,edge (default: all)",
    )
    parser.add_argument("--split", choices=SPLITS, default="all", help="default: all")
    parser.add_argument("--seed", type=int, default=None, help="seed for the item order")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"inputs in flight at once (default: {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--per-minute",
        type=float,
        default=DEFAULT_PER_MINUTE,
        help=f"inputs started per minute against the live model; 0 for no limit "
        f"(default: {DEFAULT_PER_MINUTE:g})",
    )
    parser.add_argument(
        "--emit-event",
        action="store_true",
        help="send one eval_run custom event after a full live run",
    )
    parser.add_argument(
        "--reports-dir", type=Path, default=REPORTS_DIR, help="default: evals/reports"
    )
    # `uv run poe eval -- --fake` hands the separator on as well, so it is dropped here.
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    args = parser.parse_args(arguments)
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if args.per_minute < 0:
        parser.error("--per-minute cannot be negative")
    return args


def _settings() -> Settings:
    if os.environ.get("SCORER_ROOT", "").strip():
        return Settings.from_env()
    return Settings(scorer_root=REPO_ROOT)


def _progress(done: int, total: int) -> None:
    if done % 10 == 0 or done == total:
        print(f"  scored {done} of {total}", flush=True)


async def _score_all(
    args: argparse.Namespace,
    items: Sequence[EvalItem],
    settings: Settings,
    client_name: str,
    client_factory: ClientFactory | None,
    retry_log: list[dict],
) -> list[dict]:
    shared = None
    if client_name != LIVE:
        client_for: ClientFactory = functools.partial(FakeEvalClient, weak=client_name == FAKE_WEAK)
        per_minute = 0.0
    elif client_factory is not None:
        client_for, per_minute = client_factory, args.per_minute
    else:
        client_for, shared = _live_client_factory(settings)
        per_minute = args.per_minute
    try:
        return await run_items(
            items,
            client_for,
            settings,
            concurrency=args.concurrency,
            per_minute=per_minute,
            progress=_progress,
            retry_log=retry_log,
        )
    finally:
        if shared is not None:
            await _close(shared)


def main(argv: Sequence[str] | None = None, *, client_factory: ClientFactory | None = None) -> int:
    """Run the evals. `client_factory` replaces the live client, for tests."""
    args = parse_args(argv)
    client_name = FAKE if args.fake else FAKE_WEAK if args.fake_weak else LIVE
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**31)
    try:
        settings = _settings()
        thresholds = load_thresholds()
        items = build_items(load_datasets(), args.suite, args.split)
        if not items:
            raise EvalRunError("no inputs match the chosen suites and split")
        random.Random(seed).shuffle(items)

        full = tuple(args.suite) == SUITES and args.split == "all"
        scope = f"suites {', '.join(args.suite)}; split {args.split}"
        print(f"Eval run: {'full' if full else 'PARTIAL'}; {scope}")
        print(f"Seed: {seed} (the item order is shuffled with it)")
        print(f"Inputs: {len(items)}, about {RUNS * len(items)} model calls at most", flush=True)

        started = time.monotonic()
        retry_log: list[dict] = []
        results = asyncio.run(
            _score_all(args, items, settings, client_name, client_factory, retry_log)
        )
        report = build_report(
            results=results,
            # Only a full run is a gate result, so only a full run must hold every size.
            evaluation=evaluate(
                results, thresholds, required_sizes=REQUIRED_SIZES if full else None
            ),
            thresholds=thresholds,
            settings=settings,
            suites=args.suite,
            split=args.split,
            seed=seed,
            client=client_name,
            concurrency=args.concurrency,
            duration_seconds=time.monotonic() - started,
            retries=retry_log,
        )
        markdown_path, json_path = write_report(report, args.reports_dir)
    except EvalRunError as error:
        message = f"The eval run did not finish: {error}. No report was written and no score was invented."
        print(message, file=sys.stderr)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"## Eval gate: NOT EVALUATED\n\n{message}\n")
        _github_output({"gate": "error"})
        print("GATE: NOT EVALUATED (the run did not finish)")
        return EXIT_ERROR

    print()
    print("\n".join(console_lines(report)))
    print(f"Report: {_shown(markdown_path)} and {_shown(json_path)}")
    if args.emit_event:
        print(f"eval_run event: {emit_eval_event(report, settings)}")
    _github_output(
        {
            "report_md": _shown(markdown_path),
            "report_json": _shown(json_path),
            "gate": report["gate"]["status"],
        }
    )
    print(gate_line(report))
    status = report["gate"]["status"]
    if status == "pass":
        return EXIT_PASS
    if status == "fail":
        return EXIT_FAIL
    # A partial run is not a gate result. It still exits non-zero when a metric it did
    # compute is on the wrong side of its threshold, so tuning runs can be scripted.
    return EXIT_FAIL if report["gate"]["breached"] or report["gate_failures"] else EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
