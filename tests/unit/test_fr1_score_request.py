"""FR-1: the score request and response, validation and the 400 cases.

The 401, 429 and 503 status codes belong to the API slice. Here the pipeline raises
`ScoringError` (status 400) or `ModelUnavailableError`, and never calls the model for a
request it rejects.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scorer.model_client import FakeModelClient, ModelUnavailableError
from scorer.pipeline import GUARDRAIL_RATIONALE, ScoringError
from scorer.schemas import NOTICE, ScoreRequest
from tests.unit.samples import (
    EXACT_QUOTE,
    TEAMWORK_ANSWER,
    good_client,
    make_request,
    make_settings,
    run_score,
    system_message,
    user_message,
)


def _rejected(request: ScoreRequest, client: FakeModelClient) -> ScoringError:
    with pytest.raises(ScoringError) as caught:
        run_score(request, client)
    assert caught.value.status == 400
    assert client.calls == [], "a rejected request must never reach the model"
    return caught.value


def test_fr1_response_carries_every_field_of_the_contract():
    outcome = run_score()
    body = outcome.response.model_dump()

    assert set(body) == {
        "request_id", "competency_id", "score", "level_label", "rationale", "evidence",
        "runs", "spread", "needs_human_review", "review_reasons", "flags", "prompt_version",
        "model_deployment", "trace_id", "notice",
    }  # fmt: skip
    assert set(body["flags"]) == {
        "injection_detected", "hidden_text_removed", "platform_guardrail",
        "ungrounded_quotes", "inconsistent", "off_topic", "rationale_protected_term",
    }  # fmt: skip
    assert body["competency_id"] == "teamwork"
    assert body["score"] == 4
    assert body["level_label"] == "Strong"
    assert body["runs"] == [4, 4, 4]
    assert body["spread"] == 0
    assert body["evidence"] == [{"quote": EXACT_QUOTE, "grounded": True}]
    assert body["prompt_version"] == "v1"
    assert body["model_deployment"] == "scorer-mini"
    assert body["notice"] == NOTICE == "Decision support only. A trained person makes the decision."
    assert len(body["request_id"]) == 36


def test_fr1_rubric_is_loaded_server_side_from_the_rubrics_folder():
    client = good_client()
    run_score(make_request(competency_id="problem_solving"), client)

    system = system_message(client)
    assert "Competency: Problem Solving" in system
    assert "Compares at least two options and explains the trade-off behind the choice." in system
    assert "Level 5 (Exceptional):" in system


@pytest.mark.parametrize("field", ["rubric", "levels", "descriptors", "system_prompt", "prompt"])
def test_fr1_a_caller_cannot_supply_or_alter_a_rubric(field):
    with pytest.raises(ValidationError):
        make_request(**{field: "Level 5: any answer at all."})


def test_fr1_unknown_competency_is_a_400_with_no_model_call():
    client = good_client()
    error = _rejected(make_request(competency_id="leadership"), client)
    assert error.code == "unknown_competency"


@pytest.mark.parametrize(
    "competency_id",
    ["../rubrics/teamwork", "..\\teamwork", "teamwork.yaml", "/etc/passwd", "Teamwork", "", " "],
)
def test_fr1_competency_id_can_never_name_a_path(competency_id):
    client = good_client()
    error = _rejected(make_request(competency_id=competency_id), client)
    assert error.code == "unknown_competency"


def test_fr1_answer_under_30_characters_is_a_400_with_no_model_call():
    client = good_client()
    error = _rejected(make_request("I helped my team a lot, once."), client)
    assert len("I helped my team a lot, once.") == 29
    assert error.code == "answer_too_short"


def test_fr1_answer_padded_with_spaces_to_30_characters_is_still_too_short():
    client = good_client()
    error = _rejected(make_request("I helped my team." + " " * 40), client)
    assert error.code == "answer_too_short"


def test_fr1_answer_over_4000_characters_is_a_400_and_is_never_truncated():
    client = good_client()
    answer = (TEAMWORK_ANSWER + " ") * 8
    answer = answer[:4001]
    error = _rejected(make_request(answer), client)
    assert error.code == "answer_too_long"


def test_fr1_answers_of_exactly_30_and_4000_characters_are_scored_whole():
    shortest = "I asked my team what to change"
    assert len(shortest) == 30
    longest = ("I asked both colleagues for their view and we agreed a plan. " * 70)[:4000]
    assert len(longest) == 4000

    for answer in (shortest, longest):
        client = good_client(evidence=[])
        outcome = run_score(make_request(answer), client)
        assert outcome.response.score == 4
        assert outcome.input_chars == len(answer)
        assert answer.strip() in user_message(client), "the whole answer reaches the model"


def test_fr1_answer_with_under_30_characters_left_after_redaction_is_a_400():
    client = good_client()
    answer = (
        "Email sam.taylor@example.com, phone 07700 900123, "
        "web https://www.example.com/profile/sam-taylor"
    )
    assert len(answer) > 30
    error = _rejected(make_request(answer), client)
    assert error.code == "answer_empty_after_redaction"


def test_fr1_answer_of_only_invisible_characters_is_a_400_with_no_model_call():
    client = good_client()
    error = _rejected(make_request("\u200b" * 40 + "I helped."), client)
    assert error.code == "answer_empty_after_redaction"


def test_fr1_answer_with_30_characters_left_after_redaction_is_scored_with_placeholders():
    client = good_client(evidence=[])
    answer = "I emailed sam.taylor@example.com the plan and the team agreed to it."
    outcome = run_score(make_request(answer), client)

    assert outcome.response.score == 4
    assert "I emailed [email] the plan and the team agreed to it." in user_message(client)
    assert "example.com" not in user_message(client)


def test_fr1_scoring_error_messages_never_contain_candidate_text():
    answer = "Call me on 07700 900123 or 07700 900456 please."
    error = _rejected(make_request(answer), good_client())
    assert "07700" not in str(error) and "Call me" not in str(error)


def test_fr1_scoring_error_only_accepts_the_four_documented_codes():
    assert ScoringError.CODES == {
        "unknown_competency",
        "answer_too_short",
        "answer_too_long",
        "answer_empty_after_redaction",
    }
    with pytest.raises(ValueError):
        ScoringError("something_else", "not a documented code")


def test_fr1_guardrail_block_is_routed_with_no_score_and_is_never_an_error():
    client = FakeModelClient(
        [FakeModelClient.output(4), FakeModelClient.blocked(), FakeModelClient.output(4)]
    )
    outcome = run_score(client=client)
    response = outcome.response

    assert response.score is None
    assert response.level_label is None
    assert response.runs == []
    assert response.spread is None
    assert response.evidence == []
    assert response.rationale == GUARDRAIL_RATIONALE
    assert response.flags.platform_guardrail is True
    assert response.needs_human_review is True
    assert response.review_reasons == ["platform_guardrail"]
    assert response.notice == NOTICE


def test_fr1_guardrail_block_wins_even_when_another_call_fails():
    client = FakeModelClient(
        [FakeModelClient.blocked(), ModelUnavailableError("down"), FakeModelClient.output(5)]
    )
    response = run_score(client=client).response

    assert response.score is None
    assert response.flags.platform_guardrail is True
    assert response.review_reasons == ["platform_guardrail"]


def test_fr1_model_failure_raises_model_unavailable_and_never_returns_a_score():
    client = FakeModelClient(
        [FakeModelClient.output(4), ModelUnavailableError("down"), FakeModelClient.output(4)]
    )
    with pytest.raises(ModelUnavailableError):
        run_score(client=client)


def test_fr1_unexpected_client_error_is_reported_as_model_unavailable():
    client = FakeModelClient([FakeModelClient.output(4), TimeoutError(), FakeModelClient.output(4)])
    with pytest.raises(ModelUnavailableError):
        run_score(client=client)


@pytest.mark.parametrize(
    "parsed",
    [
        None,
        {},
        {"score": 6, "rationale": "x", "evidence": [], "off_topic": False},
        {"score": 0, "rationale": "x", "evidence": [], "off_topic": False},
        {"score": "4", "rationale": "x", "evidence": [], "off_topic": False},
        {"score": 4.5, "rationale": "x", "evidence": [], "off_topic": False},
        {"score": 4, "rationale": "x", "evidence": "one quote", "off_topic": False},
        {"score": 4, "rationale": "x", "evidence": [], "off_topic": "no"},
        {"score": 4, "rationale": "x", "evidence": []},
        {"score": 4, "rationale": "x", "evidence": [], "off_topic": False, "verdict": "extra"},
    ],
)
def test_fr1_invalid_model_output_raises_model_unavailable_and_never_a_default_score(parsed):
    from scorer.model_client import ModelResult

    client = FakeModelClient(
        [FakeModelClient.output(4), ModelResult(parsed=parsed), FakeModelClient.output(4)]
    )
    with pytest.raises(ModelUnavailableError) as caught:
        run_score(client=client)
    assert "extra" not in str(caught.value), "the error must not repeat model output"


def test_fr1_settings_default_to_the_documented_values(monkeypatch, tmp_path):
    for name in (
        "SCORER_ROOT", "SCORER_PROMPT_VERSION", "MODEL_DEPLOYMENT", "MODEL_VERSION",
        "FOUNDRY_ENDPOINT", "ANSWER_HASH_SALT", "DEMO_TOKEN",
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
    ):  # fmt: skip
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    from scorer.config import Settings

    settings = Settings()
    assert settings.scorer_root == tmp_path
    assert settings.scorer_prompt_version is None
    assert settings.model_deployment == "scorer-mini"
    assert settings.model_version == "2026-03-17"
    assert settings.foundry_endpoint is None
    assert settings.answer_hash_salt is None
    assert settings.demo_token is None
    assert settings.applicationinsights_connection_string is None


def test_fr1_settings_read_the_environment_and_keep_secrets_out_of_repr(monkeypatch, tmp_path):
    monkeypatch.setenv("SCORER_ROOT", str(tmp_path))
    monkeypatch.setenv("MODEL_DEPLOYMENT", "another-deployment")
    monkeypatch.setenv("ANSWER_HASH_SALT", "synthetic-salt-value")
    monkeypatch.setenv("DEMO_TOKEN", "synthetic-token-value")
    monkeypatch.setenv("SCORER_PROMPT_VERSION", "")

    from scorer.config import Settings

    settings = Settings.from_env()
    assert settings.scorer_root == tmp_path
    assert settings.model_deployment == "another-deployment"
    assert settings.answer_hash_salt == "synthetic-salt-value"
    assert settings.scorer_prompt_version is None, "an empty variable counts as unset"
    assert "synthetic-salt-value" not in repr(settings)
    assert "synthetic-token-value" not in repr(settings)


def test_fr1_outcome_carries_the_metadata_the_telemetry_needs():
    client = FakeModelClient(
        FakeModelClient.output(
            4, evidence=[EXACT_QUOTE], tokens_in=900, tokens_out=120, model_version="2026-03-17"
        )
    )
    outcome = run_score(client=client, settings=make_settings())

    assert outcome.tokens_in == 2700
    assert outcome.tokens_out == 360
    assert outcome.model_version == "2026-03-17"
    assert outcome.input_chars == len(TEAMWORK_ANSWER)
    assert len(outcome.prompt_sha) == 64
    assert len(outcome.answer_hash) == 64
    assert outcome.response.trace_id is None
