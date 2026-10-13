"""The eval runner tries an input again when the model was unavailable, and never invents.

Added in S4c after a full live run was thrown away at input 13 of 92 by one transient
model failure. A failure gives no score, so trying the same input again is not choosing
between scores; an input that still cannot be scored stops the run.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

import evals.run_evals as run_evals
from scorer.model_client import ModelUnavailableError
from tests.unit.samples import make_settings


@dataclass
class Item:
    item_id: str


def _run(items, fail_plan, monkeypatch, *, attempts_seen=None, waits=None, retried=None):
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
            concurrency=1,
            retried=retried,
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
