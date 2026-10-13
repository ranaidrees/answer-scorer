"""The eval runner tries an input again when the model was unavailable, and never invents.

Added in S4c after a full live run was thrown away at input 13 of 92 by one transient
model failure. A failure gives no score, so trying the same input again is not choosing
between scores; an input that still cannot be scored stops the run.

The same error also covers an unusable reply (cut off, not valid JSON, off the schema),
so the extra attempts of a run are capped and their causes are kept: a prompt that makes
replies unusable cannot retry its way to a finished run.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import evals.run_evals as run_evals
from scorer import model_client, pipeline
from scorer.model_client import FoundryModelClient, ModelResult, ModelUnavailableError
from scorer.schemas import MODEL_OUTPUT_SCHEMA
from tests.unit.samples import make_settings


@dataclass
class Item:
    item_id: str


def _run(
    items,
    fail_plan,
    monkeypatch,
    *,
    attempts_seen=None,
    waits=None,
    retried=None,
    retry_log=None,
    concurrency=1,
):
    """Run `run_items` with a stand-in scorer that fails as `fail_plan` says."""
    remaining = dict(fail_plan)
    attempts_seen = attempts_seen if attempts_seen is not None else []

    async def fake_score_item(item, client, settings):
        attempts_seen.append(item.item_id)
        error = remaining.get(item.item_id)
        if isinstance(error, list) and error:
            raise error.pop(0)
        return {"id": item.item_id, "score": 3}

    async def fake_sleep(seconds: float) -> None:
        if waits is not None:
            waits.append(seconds)

    monkeypatch.setattr(run_evals, "score_item", fake_score_item)
    return asyncio.run(
        run_evals.run_items(
            items,
            lambda item: object(),
            make_settings(),
            concurrency=concurrency,
            retried=retried,
            retry_log=retry_log,
            retry_waits=(10.0, 30.0),
            sleep=fake_sleep,
        )
    )


def test_an_input_that_fails_once_is_tried_again_and_scored(monkeypatch) -> None:
    items = [Item("a"), Item("b"), Item("c")]
    attempts, waits, retried = [], [], []
    results = _run(
        items,
        {"b": [ModelUnavailableError("blip")]},
        monkeypatch,
        attempts_seen=attempts,
        waits=waits,
        retried=retried,
    )
    assert [result["id"] for result in results] == ["a", "b", "c"]
    assert attempts == ["a", "b", "b", "c"]
    assert retried == ["b"]
    assert waits == [10.0]


def test_two_failures_then_success_waits_longer_the_second_time(monkeypatch) -> None:
    waits, retried = [], []
    plan = {"a": [ModelUnavailableError("one"), ModelUnavailableError("two")]}
    results = _run([Item("a")], plan, monkeypatch, waits=waits, retried=retried)
    assert [result["id"] for result in results] == ["a"]
    assert retried == ["a", "a"]
    assert waits == [10.0, 30.0]


def test_an_input_that_keeps_failing_stops_the_run_with_no_result_for_it(monkeypatch) -> None:
    attempts = []
    always = [ModelUnavailableError(str(n)) for n in range(10)]
    with pytest.raises(run_evals.EvalRunError) as raised:
        _run([Item("a"), Item("b"), Item("c")], {"b": always}, monkeypatch, attempts_seen=attempts)
    assert "the model was unavailable" in str(raised.value)
    assert "input b" in str(raised.value)
    # Exactly ITEM_ATTEMPTS tries for the failing input, and nothing after it was started.
    assert attempts == ["a"] + ["b"] * run_evals.ITEM_ATTEMPTS
    assert run_evals.ITEM_ATTEMPTS == 3


def test_an_unexpected_error_is_never_retried(monkeypatch) -> None:
    attempts = []
    with pytest.raises(run_evals.EvalRunError) as raised:
        _run(
            [Item("a"), Item("b")], {"a": [ValueError("bug")]}, monkeypatch, attempts_seen=attempts
        )
    assert "an unexpected error (ValueError)" in str(raised.value)
    assert attempts == ["a"]


def test_a_clean_run_reports_no_retries(monkeypatch) -> None:
    retried: list[str] = []
    results = _run([Item("a"), Item("b")], {}, monkeypatch, retried=retried)
    assert len(results) == 2
    assert retried == []


# --------------------------------------------------------------------------- the cap
def _once(*ids: str) -> dict:
    """Each named input fails on its first attempt, with a reply that was cut off."""
    return {item_id: [ModelUnavailableError("the reply is not complete")] for item_id in ids}


def test_three_extra_attempts_across_different_inputs_still_finish(monkeypatch) -> None:
    assert run_evals.MAX_RETRY_ATTEMPTS_PER_RUN == 3
    attempts, retried, log = [], [], []
    results = _run(
        [Item("a"), Item("b"), Item("c"), Item("d")],
        _once("a", "b", "c"),
        monkeypatch,
        attempts_seen=attempts,
        retried=retried,
        retry_log=log,
    )
    assert [result["id"] for result in results] == ["a", "b", "c", "d"]
    assert attempts == ["a", "a", "b", "b", "c", "c", "d"]
    assert retried == ["a", "b", "c"]
    assert log == [
        {"item_id": item_id, "cause": run_evals.RETRY_UNUSABLE_REPLY} for item_id in "abc"
    ]


def test_the_cap_stops_the_run_on_the_attempt_that_exceeds_it(monkeypatch) -> None:
    attempts, retried, waits = [], [], []
    with pytest.raises(run_evals.EvalRunError) as raised:
        _run(
            [Item("a"), Item("b"), Item("c"), Item("d"), Item("e")],
            _once("a", "b", "c", "d", "e"),
            monkeypatch,
            attempts_seen=attempts,
            retried=retried,
            waits=waits,
        )
    # The fourth extra attempt is never made, and no input after it is started.
    assert attempts == ["a", "a", "b", "b", "c", "c", "d"]
    assert retried == ["a", "b", "c"]
    assert len(waits) == 3
    message = str(raised.value)
    assert "the model failed or returned unusable replies too often" in message
    assert "at most 3 extra attempts" in message
    assert "3 were made (3 unusable reply) and one more was needed (unusable reply)" in message
    assert "after 3 of 5 inputs were scored" in message
    assert "itself a finding" in message
    # The finding is about the run, so no input is named.
    assert "input d" not in message


def test_the_cap_counts_attempts_across_the_whole_run_not_per_input(monkeypatch) -> None:
    attempts = []
    plan = {
        "a": [ModelUnavailableError("the call failed after one retry") for _ in range(2)],
        "b": [ModelUnavailableError("the reply is not valid JSON") for _ in range(2)],
    }
    with pytest.raises(run_evals.EvalRunError) as raised:
        _run([Item("a"), Item("b"), Item("c")], plan, monkeypatch, attempts_seen=attempts)
    # Two extra attempts for a, one for b, and b's second failure needs a fourth.
    assert attempts == ["a", "a", "a", "b", "b"]
    message = str(raised.value)
    assert "too often" in message
    assert "3 were made (2 failed call, 1 unusable reply)" in message
    assert "after 1 of 3 inputs were scored" in message


def test_an_input_that_keeps_failing_is_still_reported_as_such_under_the_cap(monkeypatch) -> None:
    # Two extra attempts on one input are inside the cap: the older message stands.
    always = [ModelUnavailableError("the reply is not complete") for _ in range(10)]
    with pytest.raises(run_evals.EvalRunError) as raised:
        _run([Item("a"), Item("b")], {"a": always}, monkeypatch)
    assert "the model was unavailable" in str(raised.value)
    assert "too often" not in str(raised.value)


def test_the_cap_holds_with_several_inputs_in_flight(monkeypatch) -> None:
    ids = [f"i{number}" for number in range(12)]
    attempts, retried = [], []
    with pytest.raises(run_evals.EvalRunError) as raised:
        _run(
            [Item(item_id) for item_id in ids],
            _once(*ids),
            monkeypatch,
            attempts_seen=attempts,
            retried=retried,
            concurrency=4,
        )
    assert "too often" in str(raised.value)
    assert len(retried) == run_evals.MAX_RETRY_ATTEMPTS_PER_RUN
    # Three inputs were tried again; each of the four workers can add one first attempt.
    assert len(attempts) <= 2 * run_evals.MAX_RETRY_ATTEMPTS_PER_RUN + 4


# --------------------------------------------------------------------------- the cause
def _completion(content, finish_reason="stop", *, choices=True):
    choice = SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))
    return SimpleNamespace(usage=None, model=None, choices=[choice] if choices else [])


@pytest.mark.parametrize(
    "completion",
    [
        _completion("{}", choices=False),
        _completion('{"score": 3', finish_reason="length"),
        _completion(""),
        _completion("not json"),
        _completion("{}"),
    ],
    ids=["no choices", "cut off", "empty", "not JSON", "off the schema"],
)
def test_every_unusable_reply_the_live_client_raises_is_told_apart(completion) -> None:
    # The live client's own code makes the error, so a reworded text there fails here.
    with pytest.raises(ModelUnavailableError) as raised:
        FoundryModelClient._to_result(completion, MODEL_OUTPUT_SCHEMA)
    assert run_evals.retry_cause(raised.value) == run_evals.RETRY_UNUSABLE_REPLY


def test_the_matched_texts_are_the_ones_the_scorer_raises() -> None:
    client_source = Path(model_client.__file__).read_text(encoding="utf-8")
    pipeline_source = Path(pipeline.__file__).read_text(encoding="utf-8")
    for text in run_evals._FAILED_CALL_TEXTS | run_evals._UNUSABLE_REPLY_TEXTS:
        assert f'"{text}"' in client_source + pipeline_source, text
    assert f'ModelUnavailableError("{run_evals._UNUSABLE_REPLY_PREFIX} ' in client_source


class _Raises:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def complete(self, messages, *, schema):
        raise self._error


class _Returns:
    def __init__(self, parsed: object) -> None:
        self._parsed = parsed

    async def complete(self, messages, *, schema):
        return ModelResult(parsed=self._parsed, tokens_in=10, tokens_out=5)


@pytest.mark.parametrize(
    ("client", "expected"),
    [
        (_Raises(TimeoutError("synthetic")), run_evals.RETRY_FAILED_CALL),
        (
            _Raises(ModelUnavailableError("the call failed after one retry")),
            run_evals.RETRY_FAILED_CALL,
        ),
        (_Raises(ModelUnavailableError("the request was rejected")), run_evals.RETRY_FAILED_CALL),
        (
            _Raises(ModelUnavailableError("the reply is not complete")),
            run_evals.RETRY_UNUSABLE_REPLY,
        ),
        (_Returns({"score": "high"}), run_evals.RETRY_UNUSABLE_REPLY),
        (_Raises(ModelUnavailableError("a text nobody listed")), run_evals.RETRY_CAUSE_NOT_KNOWN),
    ],
    ids=["raised", "failed after a retry", "rejected", "cut off", "not valid", "not known"],
)
def test_the_cause_is_read_from_the_error_the_real_pipeline_raises(client, expected) -> None:
    item = run_evals.build_items(run_evals.load_datasets(), ("golden",), "dev")[0]
    with pytest.raises(ModelUnavailableError) as raised:
        asyncio.run(run_evals.score_item(item, client, make_settings()))
    assert run_evals.retry_cause(raised.value) == expected


def test_an_unusable_reply_wrapped_as_a_failed_call_is_still_an_unusable_reply() -> None:
    wrapped = ModelUnavailableError("a model call failed")
    wrapped.__cause__ = ModelUnavailableError("the reply does not follow the schema")
    assert run_evals.retry_cause(wrapped) == run_evals.RETRY_UNUSABLE_REPLY


def test_a_cause_that_cannot_be_told_is_not_guessed() -> None:
    assert run_evals.retry_cause(ModelUnavailableError("blip")) == "model failure or unusable reply"
    # A text from outside the scorer is never matched, whatever it says.
    wrapped = ModelUnavailableError("something else")
    wrapped.__cause__ = ValueError("the reply is not complete")
    assert run_evals.retry_cause(wrapped) == run_evals.RETRY_CAUSE_NOT_KNOWN


def test_the_log_keeps_the_cause_of_each_extra_attempt_in_order(monkeypatch) -> None:
    log: list[dict] = []
    plan = {
        "a": [ModelUnavailableError("the call failed after one retry")],
        "b": [ModelUnavailableError("the reply is not valid JSON"), ModelUnavailableError("blip")],
    }
    _run([Item("a"), Item("b")], plan, monkeypatch, retry_log=log)
    assert log == [
        {"item_id": "a", "cause": "failed call"},
        {"item_id": "b", "cause": "unusable reply"},
        {"item_id": "b", "cause": "model failure or unusable reply"},
    ]
    assert run_evals.retries_by_cause(log) == {
        "failed call": 1,
        "unusable reply": 1,
        "model failure or unusable reply": 1,
    }
