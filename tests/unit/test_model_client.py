"""The model client interface, the fake client and the strict output schema (FR-4 step 6)."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from scorer.model_client import FakeModelClient, ModelClient, ModelResult, ModelUnavailableError
from scorer.schemas import MODEL_OUTPUT_SCHEMA, ModelOutput

MESSAGES = [{"role": "system", "content": "prompt"}, {"role": "user", "content": "answer"}]


def _complete(client: FakeModelClient, messages=MESSAGES) -> ModelResult:
    return asyncio.run(client.complete(messages, schema=MODEL_OUTPUT_SCHEMA))


def test_model_output_schema_is_strict_with_an_integer_enum_score():
    assert MODEL_OUTPUT_SCHEMA["type"] == "object"
    assert MODEL_OUTPUT_SCHEMA["additionalProperties"] is False
    assert sorted(MODEL_OUTPUT_SCHEMA["required"]) == [
        "evidence",
        "off_topic",
        "rationale",
        "score",
    ]
    assert set(MODEL_OUTPUT_SCHEMA["properties"]) == set(MODEL_OUTPUT_SCHEMA["required"])
    score = MODEL_OUTPUT_SCHEMA["properties"]["score"]
    assert score == {"type": "integer", "enum": [1, 2, 3, 4, 5]}
    assert "minimum" not in score and "maximum" not in score
    assert MODEL_OUTPUT_SCHEMA["properties"]["evidence"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert MODEL_OUTPUT_SCHEMA["properties"]["rationale"] == {"type": "string"}
    assert MODEL_OUTPUT_SCHEMA["properties"]["off_topic"] == {"type": "boolean"}


def test_model_output_matches_the_schema_fields():
    assert set(ModelOutput.model_fields) == set(MODEL_OUTPUT_SCHEMA["properties"])
    parsed = ModelOutput.model_validate(FakeModelClient.output(3, evidence=["a quote"]).parsed)
    assert parsed.score == 3 and parsed.evidence == ["a quote"] and parsed.off_topic is False


@pytest.mark.parametrize("score", [0, 6, -1, "3", 3.5, 4.0, None, True])
def test_model_output_rejects_a_score_outside_the_enum(score):
    with pytest.raises(ValidationError):
        ModelOutput.model_validate(
            {"score": score, "rationale": "x", "evidence": [], "off_topic": False}
        )


def test_fake_client_implements_the_model_client_protocol():
    assert isinstance(FakeModelClient(FakeModelClient.output(4)), ModelClient)


def test_fake_client_returns_a_fixed_result_on_every_call_and_records_the_messages():
    client = FakeModelClient(FakeModelClient.output(4))

    first, second = _complete(client), _complete(client)

    assert first.parsed["score"] == second.parsed["score"] == 4
    assert first.blocked is False
    assert client.calls == [MESSAGES, MESSAGES]
    assert client.schemas == [MODEL_OUTPUT_SCHEMA, MODEL_OUTPUT_SCHEMA]


def test_fake_client_accepts_a_plain_dict_as_the_parsed_output():
    parsed = {"score": 2, "rationale": "x", "evidence": [], "off_topic": True}
    assert _complete(FakeModelClient(parsed)).parsed == parsed


def test_fake_client_plays_a_list_of_results_one_per_call():
    client = FakeModelClient([FakeModelClient.output(score) for score in (3, 4, 5)])
    assert [_complete(client).parsed["score"] for _ in range(3)] == [3, 4, 5]
    with pytest.raises(ModelUnavailableError):
        _complete(client)


def test_fake_client_calls_a_callable_with_the_messages():
    seen = []

    def script(messages):
        seen.append(messages)
        return FakeModelClient.output(5 if "answer" in messages[-1]["content"] else 1)

    client = FakeModelClient(script)
    assert _complete(client).parsed["score"] == 5
    assert seen == [MESSAGES]


def test_fake_client_simulates_a_content_filter_block():
    result = _complete(FakeModelClient(FakeModelClient.blocked()))
    assert result.blocked is True
    assert result.parsed is None


def test_fake_client_simulates_a_failure():
    client = FakeModelClient(ModelUnavailableError("synthetic outage"))
    with pytest.raises(ModelUnavailableError):
        _complete(client)
    assert client.calls == [MESSAGES], "the failed call is still recorded"


def test_fake_client_records_a_copy_of_the_messages():
    client = FakeModelClient(FakeModelClient.output(4))
    messages = [dict(message) for message in MESSAGES]
    _complete(client, messages)
    messages[0]["content"] = "changed afterwards"
    assert client.calls[0][0]["content"] == "prompt"


def test_model_result_defaults():
    result = ModelResult(parsed=None)
    assert (result.blocked, result.tokens_in, result.tokens_out, result.model_version) == (
        False,
        0,
        0,
        None,
    )
