"""The question-echo check: an answer that only repeats the question is off topic.

Added in S4c after the stability proof showed the model alone was not reliable on this
case: across three full runs it scored a restated question 1, 1 and then 2, without
setting `off_topic`. The check is deterministic, so the control no longer depends on
the model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scorer.echo import ECHO_MAX_NOVEL_SHARE, echoes_question, novel_share
from scorer.model_client import FakeModelClient
from tests.unit.samples import QUESTION, REPO_ROOT, TEAMWORK_ANSWER, make_request, run_score

DATASETS = REPO_ROOT / "evals" / "datasets"
output = FakeModelClient.output

RESTATED = (
    "Tell me about a time you resolved a conflict in a team. Well, about a time I resolved "
    "a conflict in a team: there was a conflict in a team and I resolved it at the time."
)


def _rows(name: str) -> list[dict]:
    lines = Path(DATASETS, name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_a_restated_question_is_an_echo() -> None:
    assert echoes_question(QUESTION, RESTATED)
    assert novel_share(QUESTION, RESTATED) < ECHO_MAX_NOVEL_SHARE


def test_an_ordinary_answer_is_not_an_echo() -> None:
    assert not echoes_question(QUESTION, TEAMWORK_ANSWER)
    assert novel_share(QUESTION, TEAMWORK_ANSWER) > 0.6


def test_hand_computed_share() -> None:
    # Answer words: "we fixed the problem" (4). Question words: {"describe", "a", "problem"}.
    # New words: "we", "fixed", "the" = 3 of 4.
    assert novel_share("Describe a problem", "We fixed the problem") == pytest.approx(0.75)


@pytest.mark.parametrize("answer", ["", "   ", "?!...", "​"])
def test_an_answer_with_no_words_is_not_called_an_echo(answer: str) -> None:
    # Length and redaction rules reject such answers elsewhere; this check stays quiet.
    assert novel_share(QUESTION, answer) == 1.0
    assert not echoes_question(QUESTION, answer)


def test_case_and_full_width_letters_do_not_hide_an_echo() -> None:
    shouted = RESTATED.upper()
    full_width = "".join(chr(ord(c) + 0xFEE0) if "a" <= c <= "z" else c for c in RESTATED)
    assert echoes_question(QUESTION, shouted)
    assert echoes_question(QUESTION, full_width)


def test_the_copied_question_edge_case_is_an_echo() -> None:
    row = next(row for row in _rows("edge_cases.jsonl") if row["case"] == "copied_question")
    assert echoes_question(row["question"], row["answer"])


def test_no_other_dev_answer_is_an_echo() -> None:
    flagged = []
    for name, fields in (
        ("golden.jsonl", ("answer",)),
        ("fairness_pairs.jsonl", ("answer_a", "answer_b")),
        ("injection.jsonl", ("answer",)),
        ("edge_cases.jsonl", ("answer",)),
    ):
        for row in _rows(name):
            if row["split"] != "dev" or row.get("case") == "copied_question":
                continue
            for field in fields:
                if echoes_question(row["question"], row[field]):
                    flagged.append(row["id"])
    assert flagged == []


def test_dev_answers_sit_well_clear_of_the_limit() -> None:
    # The limit is 0.35. Real dev answers that reach the model are above 0.6, so the
    # check has a wide margin on both sides (the restated question is near 0.2).
    shares = [
        novel_share(row["question"], row["answer"])
        for row in _rows("golden.jsonl")
        if row["split"] == "dev"
    ]
    assert min(shares) > 0.6


def test_an_echo_is_off_topic_and_routed_even_when_the_model_disagrees() -> None:
    # All three runs say "not off topic" and give a 3. The check still flags and routes.
    client = FakeModelClient(output(3, off_topic=False, evidence=[]))
    response = run_score(request=make_request(answer=RESTATED), client=client).response
    assert response.flags.off_topic is True
    assert response.needs_human_review is True
    assert "off_topic" in response.review_reasons
    # The check is a flag only: the answer was still scored, and the score is the model's.
    assert response.score == 3
    assert len(client.calls) == 3


def test_an_ordinary_answer_is_not_made_off_topic_by_the_check() -> None:
    response = run_score().response
    assert response.flags.off_topic is False
    assert "off_topic" not in response.review_reasons
