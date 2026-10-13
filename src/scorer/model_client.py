"""The model client interface, a scripted fake and the live Foundry client.

`FakeModelClient` serves offline tests and dry runs. `FoundryModelClient` calls the pinned
deployment through Chat Completions with a strict JSON schema. It is keyless: a Microsoft
Entra token from `DefaultAzureCredential`, never a key. No message content, model output
or error text from the service is ever logged here.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import openai

if TYPE_CHECKING:
    from scorer.config import Settings

logger = logging.getLogger("scorer.model_client")

TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
API_PATH = "/openai/v1/"
SCHEMA_NAME = "score_output"
REASONING_EFFORT = "none"
MAX_COMPLETION_TOKENS = 600
REQUEST_TIMEOUT_SECONDS = 20.0
RETRY_DELAY_SECONDS = 0.5
ATTEMPTS = 2  # the first call plus one retry on a transient error
CONTENT_FILTER = "content_filter"

_VERSION_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})$")

# Timeouts and dropped connections, 429 and 5xx. `APITimeoutError` is a connection error.
_TRANSIENT_ERRORS = (
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)


@dataclass
class ModelResult:
    """One model call. `blocked` means the platform guardrail stopped it (no output)."""

    parsed: dict | None
    blocked: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    model_version: str | None = None


class ModelUnavailableError(Exception):
    """A model call failed or returned output that is not valid. There is no score."""


class ModelConfigError(RuntimeError):
    """The live client cannot be built because a required setting is missing."""


@runtime_checkable
class ModelClient(Protocol):
    async def complete(self, messages: list[dict[str, str]], *, schema: dict) -> ModelResult: ...


Messages = list[dict[str, str]]
Scripted = ModelResult | dict | BaseException
Script = Scripted | Sequence[Scripted] | Callable[[Messages], object]
TokenProvider = Callable[[], Awaitable[str]]


class FakeModelClient:
    """A scripted model client.

    The script is one of:
    - a fixed `ModelResult` (or a plain dict, used as its parsed output), returned every call;
    - a list of results, used one per call in order;
    - a callable taking the messages and returning a result.

    An exception in the script is raised instead of returned, so a failure is scripted
    with `ModelUnavailableError()` and a guardrail block with `FakeModelClient.blocked()`.
    Every call's messages are recorded in `calls`, and its schema in `schemas`.
    """

    def __init__(self, script: Script) -> None:
        self._script = script
        self._next = 0
        self.calls: list[Messages] = []
        self.schemas: list[dict] = []

    @staticmethod
    def blocked() -> ModelResult:
        """A call stopped by the platform guardrail (`content_filter`)."""
        return ModelResult(parsed=None, blocked=True)

    @staticmethod
    def output(
        score: int,
        *,
        rationale: str = "The candidate describes a specific example with a clear role.",
        evidence: Sequence[str] = (),
        off_topic: bool = False,
        tokens_in: int = 0,
        tokens_out: int = 0,
        model_version: str | None = None,
    ) -> ModelResult:
        """A well-formed result, for building scripts."""
        return ModelResult(
            parsed={
                "score": score,
                "rationale": rationale,
                "evidence": list(evidence),
                "off_topic": off_topic,
            },
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model_version=model_version,
        )

    async def complete(self, messages: Messages, *, schema: dict) -> ModelResult:
        self.calls.append([dict(message) for message in messages])
        self.schemas.append(schema)

        script = self._script
        if callable(script):
            item = script(messages)
            if inspect.isawaitable(item):
                item = await item
        elif isinstance(script, Sequence) and not isinstance(script, (str, bytes)):
            if self._next >= len(script):
                raise ModelUnavailableError("the scripted results have run out")
            item = script[self._next]
            self._next += 1
        else:
            item = script

        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ModelResult):
            return item
        if isinstance(item, dict):
            return ModelResult(parsed=dict(item))
        raise TypeError("a scripted result must be a ModelResult, a dict or an exception")


# --- The live client --------------------------------------------------------------------


def entra_token_provider() -> TokenProvider:
    """A keyless token provider for the Foundry resource.

    `DefaultAzureCredential` uses the app's managed identity in Azure and the developer's
    `az login` locally. The provider caches the token and refreshes it before it expires.
    It runs in a worker thread behind a lock, so three parallel calls fetch one token.
    """
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    provider = get_bearer_token_provider(DefaultAzureCredential(), TOKEN_SCOPE)
    lock = asyncio.Lock()

    async def token() -> str:
        async with lock:
            return await asyncio.to_thread(provider)

    return token


def response_format(schema: dict) -> dict[str, Any]:
    """The strict structured-output format for Chat Completions."""
    return {
        "type": "json_schema",
        "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": schema},
    }


def _is_content_filter(error: openai.BadRequestError) -> bool:
    """True for the platform guardrail's block: HTTP 400 with code `content_filter`."""
    if error.code == CONTENT_FILTER:
        return True
    body = error.body
    if isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        return inner.get("code") == CONTENT_FILTER
    return False


def _version_of(model: object) -> str | None:
    """The version date from the model name the service reports, or the name itself."""
    if not isinstance(model, str) or not model:
        return None
    match = _VERSION_DATE.search(model)
    return match.group(1) if match else model


class FoundryModelClient:
    """Chat Completions against `<FOUNDRY_ENDPOINT>/openai/v1/` with a strict JSON schema.

    One call has a timeout and one retry on a transient error (a timeout, a dropped
    connection, 429 or 5xx). Anything else that goes wrong raises `ModelUnavailableError`.
    A platform guardrail block is not an error: it returns a blocked result with no output.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        token_provider: TokenProvider | None = None,
        http_client: Any | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        retry_delay: float = RETRY_DELAY_SECONDS,
    ) -> None:
        self._deployment = deployment
        self._retry_delay = retry_delay
        self._token_provider = token_provider or entra_token_provider()
        self._client = openai.AsyncOpenAI(
            base_url=endpoint.rstrip("/") + API_PATH,
            api_key=self._token_provider,
            timeout=timeout,
            max_retries=0,  # the one retry is made here, so it can be counted and tested
            http_client=http_client,
        )

    async def warm(self) -> None:
        """Fetch the first token ahead of the first request. Makes no model call."""
        await self._token_provider()

    async def aclose(self) -> None:
        await self._client.close()

    async def complete(self, messages: Messages, *, schema: dict) -> ModelResult:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                completion = await self._client.chat.completions.create(
                    model=self._deployment,
                    messages=messages,
                    response_format=response_format(schema),
                    reasoning_effort=REASONING_EFFORT,
                    max_completion_tokens=MAX_COMPLETION_TOKENS,
                )
            except openai.BadRequestError as error:
                if _is_content_filter(error):
                    return ModelResult(parsed=None, blocked=True)
                raise self._unavailable("the request was rejected", error) from None
            except _TRANSIENT_ERRORS as error:
                if attempt < ATTEMPTS:
                    await asyncio.sleep(self._retry_delay)
                    continue
                raise self._unavailable("the call failed after one retry", error) from None
            except Exception as error:
                raise self._unavailable("the call failed", error) from None
            return self._to_result(completion, schema)
        raise ModelUnavailableError("the call was not made")  # pragma: no cover

    @staticmethod
    def _unavailable(reason: str, error: Exception) -> ModelUnavailableError:
        # The error type and status only. The service's message is never logged or chained.
        status = getattr(error, "status_code", None)
        logger.warning("model call: %s (%s, status=%s)", reason, type(error).__name__, status)
        return ModelUnavailableError(reason)

    @staticmethod
    def _to_result(completion: Any, schema: dict) -> ModelResult:
        usage = getattr(completion, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        model_version = _version_of(getattr(completion, "model", None))

        choices = getattr(completion, "choices", None) or []
        if not choices:
            raise ModelUnavailableError("the reply has no choices")
        choice = choices[0]
        if choice.finish_reason == CONTENT_FILTER:
            return ModelResult(
                parsed=None,
                blocked=True,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model_version=model_version,
            )
        content = getattr(choice.message, "content", None)
        if choice.finish_reason != "stop" or not content:
            # Cut off at the token cap, a refusal, or an empty reply: no usable output.
            raise ModelUnavailableError("the reply is not complete")
        try:
            parsed = json.loads(content)
        except ValueError:
            raise ModelUnavailableError("the reply is not valid JSON") from None
        required = schema.get("required", [])
        if not isinstance(parsed, dict) or any(key not in parsed for key in required):
            raise ModelUnavailableError("the reply does not follow the schema")
        return ModelResult(
            parsed=parsed,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model_version=model_version,
        )


def build_model_client(settings: Settings) -> ModelClient:
    """The live client for the configured deployment. Needs `FOUNDRY_ENDPOINT`."""
    if not settings.foundry_endpoint:
        raise ModelConfigError("FOUNDRY_ENDPOINT is not set, so the live model client is not built")
    return FoundryModelClient(
        endpoint=settings.foundry_endpoint,
        deployment=settings.model_deployment,
    )
