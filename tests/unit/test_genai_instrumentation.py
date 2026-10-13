"""The real OpenAI instrumentation around the live client, with content capture off.

The instrumentation is started against in-memory exporters and the client talks to a
mocked transport, so nothing leaves the process. The test proves two things: the
instrumentation imports and works with this client, and neither its spans nor its log
events hold a word of the messages or the model's reply.
"""

from __future__ import annotations

import asyncio
import json

import httpx2
import pytest
from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from scorer.model_client import FoundryModelClient
from scorer.schemas import MODEL_OUTPUT_SCHEMA
from scorer.telemetry import assert_content_capture_off

MARKER = "heron-velvet-compass-3187"
REPLY = {"evidence": [MARKER], "rationale": f"Rationale {MARKER}", "off_topic": False, "score": 4}
MESSAGES = [
    {"role": "system", "content": f"prompt {MARKER}"},
    {"role": "user", "content": f"question and answer {MARKER}"},
]


def transport(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "chatcmpl-synthetic",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-5.4-mini-2026-03-17",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(REPLY)},
                }
            ],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 150, "total_tokens": 1350},
        },
    )


@pytest.fixture
def instrumented(monkeypatch):
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK", raising=False)
    monkeypatch.delenv("OTEL_SEMCONV_STABILITY_OPT_IN", raising=False)
    assert_content_capture_off()

    spans, logs = InMemorySpanExporter(), InMemoryLogRecordExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(spans))
    logger_provider = LoggerProvider()
    logger_provider.add_log_record_processor(SimpleLogRecordProcessor(logs))

    instrumentor = OpenAIInstrumentor()
    instrumentor.instrument(tracer_provider=tracer_provider, logger_provider=logger_provider)
    try:
        yield spans, logs
    finally:
        instrumentor.uninstrument()


def test_the_instrumented_model_call_records_usage_and_no_message_content(instrumented):
    spans, logs = instrumented

    async def token() -> str:
        return "synthetic-bearer-value"

    async def call():
        client = FoundryModelClient(
            endpoint="https://foundry.invalid",
            deployment="scorer-mini",
            token_provider=token,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
        )
        return await client.complete(MESSAGES, schema=MODEL_OUTPUT_SCHEMA)

    result = asyncio.run(call())
    assert result.parsed == REPLY

    (span,) = spans.get_finished_spans()
    assert span.attributes["gen_ai.request.model"] == "scorer-mini"
    assert span.attributes["gen_ai.usage.input_tokens"] == 1200
    assert span.attributes["gen_ai.usage.output_tokens"] == 150

    recorded = repr([(span.name, dict(span.attributes), span.events)])
    recorded += repr(
        [(item.log_record.body, item.log_record.attributes) for item in logs.get_finished_logs()]
    )
    assert MARKER not in recorded
    assert "synthetic-bearer-value" not in recorded
