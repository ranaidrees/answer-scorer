"""The live Foundry client against a mocked transport. No network, no credential.

Covers the request it sends (strict JSON schema, no sampling settings, a bearer token and
never a key), a content-filter 400, a `content_filter` finish reason, a timeout with one
retry and replies that do not follow the schema.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx2
import pytest

from scorer.model_client import (
    FoundryModelClient,
    ModelClient,
    ModelConfigError,
    ModelUnavailableError,
    build_model_client,
)
from scorer.schemas import MODEL_OUTPUT_SCHEMA, ModelOutput
from tests.unit.samples import make_settings

ENDPOINT = "https://foundry.invalid"
BEARER = "synthetic-bearer-value"
MESSAGES = [
    {"role": "system", "content": "prompt and rubric"},
    {"role": "user", "content": "question and delimited answer"},
]
GOOD_OUTPUT = {
    "evidence": ["I asked each of them to explain their concern"],
    "rationale": "The candidate describes a specific action towards colleagues.",
    "off_topic": False,
    "score": 4,
}
# A phrase placed in service replies, to prove that nothing from them is logged or raised.
MARKER = "walrus-copper-meadow-9920"


def completion(
    content: str | None, *, finish_reason: str = "stop", model: str = "gpt-5.4-mini-2026-03-17"
) -> dict:
    return {
        "id": "chatcmpl-synthetic",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 150, "total_tokens": 1350},
    }


def ok(content: str | None = None, **kwargs) -> httpx2.Response:
    text = json.dumps(GOOD_OUTPUT) if content is None else content
    return httpx2.Response(200, json=completion(text, **kwargs))


def error(status: int, code: str, message: str = MARKER) -> httpx2.Response:
    return httpx2.Response(status, json={"error": {"code": code, "message": message}})


CONTENT_FILTER_400 = httpx2.Response(
    400,
    json={
        "error": {
            "message": f"The response was filtered. {MARKER}",
            "type": None,
            "param": "prompt",
            "code": "content_filter",
            "status": 400,
            "innererror": {
                "code": "ResponsibleAIPolicyViolation",
                "content_filter_result": {"jailbreak": {"filtered": True, "detected": True}},
            },
        }
    },
)


class Transport:
    """Plays a list of replies in order and records every request."""

    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        reply = self.replies[min(len(self.requests), len(self.replies)) - 1]
        if isinstance(reply, type) and issubclass(reply, Exception):
            raise reply("synthetic transport error", request=request)
        # A fresh response each time, so one scripted reply can be played twice.
        return httpx2.Response(reply.status_code, json=json.loads(reply.content))

    def body(self, index: int = 0) -> dict:
        return json.loads(self.requests[index].content)


def run(transport: Transport, *, token_calls: list | None = None):
    async def token() -> str:
        if token_calls is not None:
            token_calls.append(1)
        return BEARER

    async def go():
        http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(transport))
        client = FoundryModelClient(
            endpoint=ENDPOINT,
            deployment="scorer-mini",
            token_provider=token,
            http_client=http_client,
            retry_delay=0,
        )
        try:
            return await client.complete(MESSAGES, schema=MODEL_OUTPUT_SCHEMA)
        finally:
            await client.aclose()

    return asyncio.run(go())


# --- The request ------------------------------------------------------------------------


def test_the_client_implements_the_model_client_protocol():
    async def token() -> str:
        return BEARER

    assert isinstance(
        FoundryModelClient(endpoint=ENDPOINT, deployment="scorer-mini", token_provider=token),
        ModelClient,
    )


def test_the_request_goes_to_the_v1_chat_completions_path_with_a_bearer_token_and_no_key():
    transport = Transport(ok())
    run(transport)

    (request,) = transport.requests
    assert request.method == "POST"
    assert str(request.url) == f"{ENDPOINT}/openai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {BEARER}"
    assert "api-key" not in request.headers
    assert "api-version" not in str(request.url)


def test_a_trailing_slash_on_the_endpoint_does_not_double_the_path():
    transport = Transport(ok())

    async def token() -> str:
        return BEARER

    async def go():
        client = FoundryModelClient(
            endpoint=ENDPOINT + "/",
            deployment="scorer-mini",
            token_provider=token,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
        )
        await client.complete(MESSAGES, schema=MODEL_OUTPUT_SCHEMA)

    asyncio.run(go())
    assert str(transport.requests[0].url) == f"{ENDPOINT}/openai/v1/chat/completions"


def test_the_request_uses_a_strict_json_schema_and_no_sampling_settings():
    transport = Transport(ok())
    run(transport)

    sent = transport.body()
    assert sent["model"] == "scorer-mini", "the model is the deployment name"
    assert sent["messages"] == MESSAGES
    assert sent["reasoning_effort"] == "none"
    assert sent["max_completion_tokens"] == 600
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["response_format"]["json_schema"]["schema"] == MODEL_OUTPUT_SCHEMA
    assert sent["response_format"]["json_schema"]["name"]
    for absent in ("temperature", "top_p", "max_tokens", "stream", "user", "store"):
        assert absent not in sent


def test_a_good_reply_returns_the_parsed_output_the_tokens_and_the_model_version():
    result = run(Transport(ok()))

    assert result.blocked is False
    assert result.parsed == GOOD_OUTPUT
    assert ModelOutput.model_validate(result.parsed).score == 4
    assert (result.tokens_in, result.tokens_out) == (1200, 150)
    assert result.model_version == "2026-03-17"


def test_a_model_name_without_a_date_is_reported_as_it_is():
    assert run(Transport(ok(model="scorer-mini"))).model_version == "scorer-mini"


# --- Guardrail blocks -------------------------------------------------------------------


def test_a_content_filter_400_is_a_blocked_result_not_an_error():
    transport = Transport(CONTENT_FILTER_400)
    result = run(transport)

    assert result.blocked is True and result.parsed is None
    assert (result.tokens_in, result.tokens_out) == (0, 0)
    assert len(transport.requests) == 1, "a block is never retried"


def test_a_content_filter_finish_reason_is_a_blocked_result_with_its_tokens():
    transport = Transport(ok("", finish_reason="content_filter"))
    result = run(transport)

    assert result.blocked is True and result.parsed is None
    assert (result.tokens_in, result.tokens_out) == (1200, 150)
    assert result.model_version == "2026-03-17"
    assert len(transport.requests) == 1


def test_a_partial_reply_cut_by_the_content_filter_is_blocked_not_parsed():
    result = run(Transport(ok(json.dumps(GOOD_OUTPUT), finish_reason="content_filter")))
    assert result.blocked is True and result.parsed is None


# --- Transient errors: one retry --------------------------------------------------------


@pytest.mark.parametrize(
    "first",
    [
        httpx2.ReadTimeout,
        httpx2.ConnectTimeout,
        httpx2.ConnectError,
        error(429, "rate_limit_exceeded"),
        error(500, "internal_error"),
        error(503, "service_unavailable"),
    ],
)
def test_a_transient_error_is_retried_once_and_then_succeeds(first):
    transport = Transport(first, ok())
    result = run(transport)

    assert result.parsed == GOOD_OUTPUT
    assert len(transport.requests) == 2


@pytest.mark.parametrize(
    "always",
    [httpx2.ReadTimeout, error(429, "rate_limit_exceeded"), error(502, "bad_gateway")],
)
def test_a_transient_error_twice_is_model_unavailable_after_exactly_one_retry(always):
    transport = Transport(always)
    with pytest.raises(ModelUnavailableError):
        run(transport)
    assert len(transport.requests) == 2


def test_a_block_on_the_retry_is_still_a_blocked_result():
    transport = Transport(httpx2.ReadTimeout, CONTENT_FILTER_400)
    assert run(transport).blocked is True
    assert len(transport.requests) == 2


def test_each_attempt_asks_the_token_provider_so_a_refreshed_token_is_used():
    token_calls: list = []
    run(Transport(error(500, "internal_error"), ok()), token_calls=token_calls)
    assert len(token_calls) >= 2


# --- Errors that are not retried --------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        error(400, "invalid_request_error"),
        error(401, "unauthorized"),
        error(403, "forbidden"),
        error(404, "DeploymentNotFound"),
    ],
)
def test_a_client_error_is_model_unavailable_with_no_retry(reply):
    transport = Transport(reply)
    with pytest.raises(ModelUnavailableError):
        run(transport)
    assert len(transport.requests) == 1


def test_a_token_provider_failure_is_model_unavailable():
    async def broken() -> str:
        raise RuntimeError(MARKER)

    transport = Transport(ok())

    async def go():
        client = FoundryModelClient(
            endpoint=ENDPOINT,
            deployment="scorer-mini",
            token_provider=broken,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
            retry_delay=0,
        )
        await client.complete(MESSAGES, schema=MODEL_OUTPUT_SCHEMA)

    with pytest.raises(ModelUnavailableError) as raised:
        asyncio.run(go())
    assert MARKER not in str(raised.value)
    assert transport.requests == []


# --- Replies that do not follow the schema ----------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "this is not json",
        '{"score": 4, "rationale": "cut off',
        "[1, 2, 3]",
        '"just a string"',
        json.dumps({"score": 4, "rationale": "no evidence or off_topic field"}),
        json.dumps({key: value for key, value in GOOD_OUTPUT.items() if key != "score"}),
    ],
)
def test_a_schema_invalid_reply_is_model_unavailable_and_is_not_retried(content):
    transport = Transport(ok(content))
    with pytest.raises(ModelUnavailableError):
        run(transport)
    assert len(transport.requests) == 1


@pytest.mark.parametrize("finish_reason", ["length", "tool_calls"])
def test_a_reply_that_did_not_finish_normally_is_model_unavailable(finish_reason):
    with pytest.raises(ModelUnavailableError):
        run(Transport(ok(finish_reason=finish_reason)))


def test_an_empty_reply_is_model_unavailable():
    with pytest.raises(ModelUnavailableError):
        run(Transport(ok("")))
    with pytest.raises(ModelUnavailableError):
        run(Transport(httpx2.Response(200, json=completion(None))))


def test_a_reply_with_no_choices_is_model_unavailable():
    reply = completion("x")
    reply["choices"] = []
    with pytest.raises(ModelUnavailableError):
        run(Transport(httpx2.Response(200, json=reply)))


def test_a_wrong_score_value_passes_the_client_and_is_rejected_by_the_output_model():
    # The client checks the shape; the pipeline's ModelOutput check rejects the value.
    result = run(Transport(ok(json.dumps({**GOOD_OUTPUT, "score": 9}))))
    with pytest.raises(ValueError):
        ModelOutput.model_validate(result.parsed)


# --- Nothing from the service is logged or raised ---------------------------------------


def test_service_error_text_is_never_logged_or_carried_by_the_exception(caplog):
    caplog.set_level(logging.DEBUG, logger="scorer")
    with pytest.raises(ModelUnavailableError) as raised:
        run(Transport(error(400, "invalid_request_error", message=MARKER)))

    assert MARKER not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__ is True
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert MARKER not in logged
    assert "BadRequestError" in logged and "status=400" in logged


def test_reply_content_is_never_logged(caplog):
    caplog.set_level(logging.DEBUG, logger="scorer")
    with pytest.raises(ModelUnavailableError):
        run(Transport(ok(f"not json {MARKER}")))
    run(Transport(ok()))

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert MARKER not in logged
    assert GOOD_OUTPUT["rationale"] not in logged and MESSAGES[1]["content"] not in logged


# --- build_model_client -----------------------------------------------------------------


def test_build_model_client_needs_the_endpoint():
    with pytest.raises(ModelConfigError, match="FOUNDRY_ENDPOINT"):
        build_model_client(make_settings(foundry_endpoint=None))


def test_build_model_client_returns_the_live_client_without_any_network_call():
    client = build_model_client(make_settings(foundry_endpoint=ENDPOINT))
    assert isinstance(client, FoundryModelClient)
    assert isinstance(client, ModelClient)
