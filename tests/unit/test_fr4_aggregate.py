"""FR-4 step 7: the median of the three runs, the spread and the off-topic majority."""

from __future__ import annotations

import itertools

import pytest

from scorer.aggregate import aggregate, majority, median_score, spread_of
from scorer.schemas import ModelOutput


def _output(score: int, *, off_topic: bool = False, tag: str = "") -> ModelOutput:
    return ModelOutput(
        score=score,
        rationale=f"Rationale for run {tag or score}.",
        evidence=[f"quote from run {tag or score}"],
        off_topic=off_topic,
    )


@pytest.mark.parametrize(
    ("runs", "median", "spread"),
    [
        ([4, 4, 4], 4, 0),
        ([4, 4, 3], 4, 1),
        ([3, 5, 4], 4, 2),
        ([1, 5, 5], 5, 4),
        ([1, 1, 5], 1, 4),
        ([2, 3, 1], 2, 2),
        ([5, 1, 3], 3, 4),
    ],
)
def test_fr4_final_score_is_the_median_and_spread_is_max_minus_min(runs, median, spread):
    assert median_score(runs) == median
    assert spread_of(runs) == spread

    combined = aggregate([_output(score) for score in runs])
    assert combined.score == median
    assert combined.spread == spread
    assert combined.runs == runs, "runs keep the order the model calls were made in"


def test_fr4_median_holds_for_every_combination_of_three_scores():
    for runs in itertools.product(range(1, 6), repeat=3):
        combined = aggregate([_output(score) for score in runs])
        assert combined.score == sorted(runs)[1]
        assert combined.spread == max(runs) - min(runs)
        assert combined.inconsistent is (max(runs) - min(runs) >= 2)
        assert combined.chosen.score == combined.score


@pytest.mark.parametrize(("runs", "expected"), [([4, 4, 4], False), ([4, 3, 4], False),
                                                ([3, 5, 4], True), ([2, 4, 4], True)])  # fmt: skip
def test_fr4_runs_are_inconsistent_when_the_spread_is_two_or_more(runs, expected):
    assert aggregate([_output(score) for score in runs]).inconsistent is expected


def test_fr4_rationale_and_evidence_come_from_a_run_at_the_median_score():
    outputs = [_output(2, tag="low"), _output(5, tag="high"), _output(4, tag="middle")]
    combined = aggregate(outputs)

    assert combined.score == 4
    assert combined.chosen.rationale == "Rationale for run middle."
    assert combined.chosen.evidence == ["quote from run middle"]


def test_fr4_first_run_at_the_median_is_used_when_several_match():
    outputs = [_output(3, tag="first"), _output(3, tag="second"), _output(5, tag="third")]
    assert aggregate(outputs).chosen.rationale == "Rationale for run first."


@pytest.mark.parametrize(
    ("votes", "expected"),
    [
        ([False, False, False], False),
        ([True, False, False], False),
        ([True, True, False], True),
        ([False, True, True], True),
        ([True, True, True], True),
    ],
)
def test_fr4_off_topic_needs_at_least_two_of_three_runs(votes, expected):
    assert majority(votes) is expected
    outputs = [_output(1, off_topic=vote) for vote in votes]
    assert aggregate(outputs).off_topic is expected


@pytest.mark.parametrize("runs", [[], [4, 4]])
def test_fr4_median_refuses_anything_but_an_odd_number_of_runs(runs):
    with pytest.raises(ValueError):
        median_score(runs)
