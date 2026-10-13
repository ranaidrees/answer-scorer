"""FR-6 against the eval datasets, offline: the pipeline with a fake model client.

The dataset rows are test data. The injected rows hold text aimed at the scorer; here it
is only ever passed to the screen as data. Golden rows are read from the `dev` split only.
"""

from __future__ import annotations

import json

import pytest

from scorer.model_client import FakeModelClient
from scorer.pipeline import ScoringError
from tests.unit.samples import REPO_ROOT, good_client, make_request, run_score

DATASETS = REPO_ROOT / "evals" / "datasets"


def _rows(name: str) -> list[dict]:
    text = (DATASETS / f"{name}.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _flags(row: dict, answer: str | None = None):
    client = good_client(3, evidence=[])
    request = make_request(
        answer if answer is not None else row["answer"],
        competency_id=row["competency_id"],
        question=row["question"],
    )
    response = run_score(request, client).response
    assert len(client.calls) == 3, "the answer is still scored, as data"
    return response


INJECTION = _rows("injection")
INJECTED = [row for row in INJECTION if row["role"] == "injected"]
CLEAN = [row for row in INJECTION if row["role"] == "clean"]
GOLDEN_DEV = [row for row in _rows("golden") if row["split"] == "dev"]
FAIRNESS = [
    (f"{row['id']}-{side}", row, row[f"answer_{side}"])
    for row in _rows("fairness_pairs")
    for side in ("a", "b")
]
EDGE_REJECTED = [row for row in _rows("edge_cases") if row["expected"]["status"] == 400]


def test_fr6_datasets_have_the_expected_shape():
    assert len(INJECTED) == 18 and len(CLEAN) == 6
    assert len(GOLDEN_DEV) == 20
    assert len(FAIRNESS) == 32
    assert {row["case"] for row in EDGE_REJECTED} == {"contact_only", "too_long"}


@pytest.mark.parametrize("row", INJECTED, ids=[row["id"] for row in INJECTED])
def test_fr6_every_injected_dataset_row_is_flagged_and_routed(row):
    response = _flags(row)
    assert response.flags.injection_detected is True, row["injection_type"]
    assert response.needs_human_review is True
    assert "injection_detected" in response.review_reasons


@pytest.mark.parametrize("row", CLEAN, ids=[row["id"] for row in CLEAN])
def test_fr6_no_clean_twin_in_the_injection_dataset_is_flagged(row):
    response = _flags(row)
    assert response.flags.injection_detected is False
    assert response.flags.hidden_text_removed is False
    assert response.review_reasons == []


@pytest.mark.parametrize("row", GOLDEN_DEV, ids=[row["id"] for row in GOLDEN_DEV])
def test_fr6_no_golden_dev_answer_is_flagged(row):
    response = _flags(row)
    assert response.flags.injection_detected is False
    assert response.flags.hidden_text_removed is False
    assert response.review_reasons == []


@pytest.mark.parametrize(("row", "answer"), [item[1:] for item in FAIRNESS],
                         ids=[item[0] for item in FAIRNESS])  # fmt: skip
def test_fr6_no_fairness_pair_answer_is_flagged(row, answer):
    response = _flags(row, answer)
    assert response.flags.injection_detected is False
    assert response.flags.hidden_text_removed is False
    assert response.review_reasons == []


@pytest.mark.parametrize("row", EDGE_REJECTED, ids=[row["id"] for row in EDGE_REJECTED])
def test_fr1_edge_cases_that_expect_a_400_are_rejected_with_no_model_call(row):
    client = FakeModelClient(FakeModelClient.output(3))
    request = make_request(
        row["answer"], competency_id=row["competency_id"], question=row["question"]
    )
    with pytest.raises(ScoringError) as caught:
        run_score(request, client)

    assert caught.value.status == row["expected"]["status"] == 400
    assert caught.value.code == row["expected"]["error"]
    assert client.calls == []
    assert row["expected"]["model_called"] is False
