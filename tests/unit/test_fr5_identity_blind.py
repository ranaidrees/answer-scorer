"""FR-5: identity-blind input. No identity field exists and `candidate_ref` stays here."""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError

from scorer.model_client import FakeModelClient
from scorer.schemas import ScoreRequest
from tests.unit.samples import (
    QUESTION,
    TEAMWORK_ANSWER,
    good_client,
    make_request,
    payload_text,
    run_score,
)

CANDIDATE_REF = "cand-7f3a91-opaque-ref"


def test_fr5_request_schema_has_only_the_four_documented_fields():
    assert set(ScoreRequest.model_fields) == {
        "competency_id",
        "question",
        "answer",
        "candidate_ref",
    }
    assert ScoreRequest.model_config["extra"] == "forbid"
    assert ScoreRequest.model_fields["candidate_ref"].is_required() is False


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "candidate_name",
        "gender",
        "age",
        "ethnicity",
        "nationality",
        "photo",
        "date_of_birth",
    ],
)
def test_fr5_schema_rejects_identity_fields(field):
    with pytest.raises(ValidationError) as caught:
        make_request(**{field: "synthetic value"})
    assert caught.value.errors()[0]["type"] == "extra_forbidden"


def test_fr5_schema_rejects_any_unknown_field():
    body = {
        "competency_id": "teamwork",
        "question": QUESTION,
        "answer": TEAMWORK_ANSWER,
        "anything_else": True,
    }
    with pytest.raises(ValidationError):
        ScoreRequest.model_validate(body)
    with pytest.raises(ValidationError):
        ScoreRequest.model_validate_json(json.dumps(body))


@pytest.mark.parametrize("missing", ["competency_id", "question", "answer"])
def test_fr5_schema_requires_the_three_scoring_fields(missing):
    body = {"competency_id": "teamwork", "question": QUESTION, "answer": TEAMWORK_ANSWER}
    body.pop(missing)
    with pytest.raises(ValidationError):
        ScoreRequest.model_validate(body)


def test_fr5_candidate_ref_is_optional_and_opaque():
    assert make_request().candidate_ref is None
    assert make_request(candidate_ref=CANDIDATE_REF).candidate_ref == CANDIDATE_REF


def test_fr5_candidate_ref_never_reaches_the_model_payload():
    client = good_client()
    run_score(make_request(candidate_ref=CANDIDATE_REF), client)

    assert len(client.calls) == 3
    payload = payload_text(client)
    assert CANDIDATE_REF not in payload
    assert "candidate_ref" not in payload
    for call in client.calls:
        for message in call:
            assert set(message) == {"role", "content"}
            assert CANDIDATE_REF not in message["content"]


def test_fr5_candidate_ref_never_reaches_the_model_on_the_guardrail_path_either():
    client = FakeModelClient(FakeModelClient.blocked())
    run_score(make_request(candidate_ref=CANDIDATE_REF), client)
    assert CANDIDATE_REF not in payload_text(client)


def test_fr5_payload_is_the_same_with_and_without_a_candidate_ref():
    with_ref, without_ref = good_client(), good_client()
    run_score(make_request(candidate_ref=CANDIDATE_REF), with_ref)
    run_score(make_request(), without_ref)
    assert with_ref.calls == without_ref.calls


def test_fr5_candidate_ref_is_not_in_the_response_or_the_logs(caplog):
    with caplog.at_level(logging.DEBUG):
        outcome = run_score(make_request(candidate_ref=CANDIDATE_REF))

    assert CANDIDATE_REF not in outcome.response.model_dump_json()
    assert CANDIDATE_REF not in "\n".join(record.getMessage() for record in caplog.records)
