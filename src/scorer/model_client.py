"""The model client interface and a scripted fake for offline tests and dry runs.

This slice makes no model calls. The live client (keyless, against the Foundry
deployment) is added in a later slice and implements the same `ModelClient` protocol.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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


@runtime_checkable
class ModelClient(Protocol):
    async def complete(self, messages: list[dict[str, str]], *, schema: dict) -> ModelResult: ...


Messages = list[dict[str, str]]
Scripted = ModelResult | dict | BaseException
Script = Scripted | Sequence[Scripted] | Callable[[Messages], object]


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
