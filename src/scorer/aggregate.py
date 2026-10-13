"""Aggregation of the three runs and human review routing (spec FR-4 step 7, FR-8).

The final score is the median of the runs and the spread is the highest minus the lowest.
Routing only ever sends an answer to a person: the service never rejects a candidate.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from scorer.schemas import Flags, ModelOutput

INCONSISTENT_SPREAD = 2
ADVERSE_SCORES = frozenset({1, 2})

# The only values `review_reasons` can hold, in the order they are listed.
REVIEW_REASONS = (
    "injection_detected",
    "hidden_text_removed",
    "platform_guardrail",
    "inconsistent",
    "ungrounded_quote",
    "off_topic",
    "rationale_protected_term",
    "adverse_score",
)


@dataclass(frozen=True)
class Aggregate:
    score: int
    runs: list[int]
    spread: int
    inconsistent: bool
    off_topic: bool
    chosen: ModelOutput


def median_score(runs: list[int]) -> int:
    """The middle score of an odd number of runs."""
    if not runs or len(runs) % 2 == 0:
        raise ValueError("the median needs an odd number of runs")
    return int(statistics.median(runs))


def spread_of(runs: list[int]) -> int:
    return max(runs) - min(runs)


def majority(votes: list[bool]) -> bool:
    """True when more than half of the runs say so (two of three)."""
    return sum(votes) * 2 > len(votes)


def aggregate(outputs: list[ModelOutput]) -> Aggregate:
    """Combine the runs. The rationale and evidence come from a run at the median score."""
    runs = [output.score for output in outputs]
    score = median_score(runs)
    spread = spread_of(runs)
    chosen = next(output for output in outputs if output.score == score)
    return Aggregate(
        score=score,
        runs=runs,
        spread=spread,
        inconsistent=spread >= INCONSISTENT_SPREAD,
        off_topic=majority([output.off_topic for output in outputs]),
        chosen=chosen,
    )


def review_reasons(flags: Flags, score: int | None) -> list[str]:
    """Every trigger that sends this answer to a person (FR-8), in a fixed order."""
    triggered = {
        "injection_detected": flags.injection_detected,
        "hidden_text_removed": flags.hidden_text_removed,
        "platform_guardrail": flags.platform_guardrail,
        "inconsistent": flags.inconsistent,
        "ungrounded_quote": flags.ungrounded_quotes > 0,
        "off_topic": flags.off_topic,
        "rationale_protected_term": flags.rationale_protected_term,
        "adverse_score": score in ADVERSE_SCORES,
    }
    return [reason for reason in REVIEW_REASONS if triggered[reason]]
