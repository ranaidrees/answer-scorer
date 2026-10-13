"""Telemetry: tracing set-up, the `score` span, custom events and the cost estimate (spec 8).

Telemetry carries metadata only. No answer, question, rationale or evidence quote is ever
set on a span, written to a log line or put in an event, and GenAI content capture stays
off: `configure_telemetry` refuses to start while it is switched on.

Without an Application Insights connection string everything here is a no-op, so tests
and offline runs need no Azure resource.
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

if TYPE_CHECKING:
    from scorer.config import Settings
    from scorer.pipeline import ScoreOutcome

SERVICE_NAME = "answer-scorer"
TRACER_NAME = "scorer"
LOGGER_NAME = "scorer"
SCORE_SPAN_NAME = "score"

# The only attribute names the `score` span may carry (CLAUDE.md, observability conventions).
SCORE_SPAN_ATTRIBUTES = (
    "scorer.request_id",
    "scorer.answer_hash",
    "scorer.competency",
    "scorer.prompt_version",
    "scorer.prompt_sha",
    "scorer.model_deployment",
    "scorer.model_version",
    "scorer.score",
    "scorer.runs",
    "scorer.spread",
    "scorer.needs_human_review",
    "scorer.review_reasons",
    "scorer.injection_detected",
    "scorer.hidden_text_removed",
    "scorer.platform_guardrail",
    "scorer.rationale_protected_term",
    "scorer.ungrounded_quotes",
    "scorer.input_chars",
    "scorer.tokens_in",
    "scorer.tokens_out",
    "scorer.cost_estimate_gbp",
)
# A request stopped by the platform guardrail has no score, so these two are left out
# rather than filled with a number that is not a score.
ATTRIBUTES_ABSENT_WITHOUT_A_SCORE = ("scorer.score", "scorer.spread")

CONTENT_CAPTURE_ENV = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
COMPLETION_HOOK_ENV = "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK"
_CAPTURE_OFF_VALUES = frozenset({"", "false", "no_content"})

# Only the model's HTTP calls are traced by the distro (`httpx2`, which the openai package
# uses). The API instruments its own app, so that health probes can be left out, and the
# libraries this service does not use for its own work are switched off: the token calls
# made by the Azure credential would otherwise add rows, and failed local probes.
INSTRUMENTATION_OPTIONS = {
    "httpx2": {"enabled": True},
    **{
        name: {"enabled": False}
        for name in (
            "azure_sdk",
            "django",
            "fastapi",
            "flask",
            "httpx",
            "psycopg2",
            "requests",
            "urllib",
            "urllib3",
        )
    },
}

CUSTOM_EVENT_NAME_ATTRIBUTE = "microsoft.custom_event.name"
SAMPLING_RATIO = 1.0  # spec C8: every trace is kept

# The allow-list for custom events. Only these event names are sent, and an attribute is
# sent only when its name is a plain identifier and its value is a number, a boolean or
# short text made of tokens: ids, hashes, versions, dates and metric names, alone or in a
# comma-separated list. A token has no space, so a sentence can never be sent.
CUSTOM_EVENT_NAMES = frozenset({"eval_run"})
MAX_EVENT_TEXT_CHARS = 400
_EVENT_ATTRIBUTE_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_EVENT_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

_logger = logging.getLogger(f"{LOGGER_NAME}.telemetry")
_event_logger = logging.getLogger(f"{LOGGER_NAME}.events")
_LOG_RECORD_FIELDS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
_configured = False
_offline_provider: TracerProvider | None = None


class ContentCaptureError(RuntimeError):
    """GenAI content capture is switched on, so telemetry refuses to start."""


class PricesError(ValueError):
    """`config/prices.yaml` is missing, unreadable or does not have the expected keys."""


# --- Set-up -----------------------------------------------------------------------------


def assert_content_capture_off() -> None:
    """Raise unless prompt and completion capture is off in the environment.

    The OpenAI instrumentation records message content when the capture variable is
    `true` (or one of its newer modes), and also when a completion hook is configured.
    Either would put candidate text into telemetry.
    """
    capture = os.environ.get(CONTENT_CAPTURE_ENV, "").strip().lower()
    if capture not in _CAPTURE_OFF_VALUES:
        raise ContentCaptureError(
            f"{CONTENT_CAPTURE_ENV} is set, so telemetry will not start: "
            "candidate text must never be recorded. Unset it or set it to false."
        )
    if os.environ.get(COMPLETION_HOOK_ENV, "").strip():
        raise ContentCaptureError(
            f"{COMPLETION_HOOK_ENV} is set, so telemetry will not start: "
            "candidate text must never be recorded. Unset it."
        )


def configure_telemetry(settings: Settings) -> bool:
    """Send traces and events to Application Insights. True when it was configured.

    A no-op returning False when the connection string is unset. Raises
    `ContentCaptureError` if GenAI content capture is switched on, whether or not a
    connection string is present, so a process never runs with capture on.
    """
    global _configured
    assert_content_capture_off()
    if _configured:
        return True
    connection_string = settings.applicationinsights_connection_string
    if not connection_string:
        return False

    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

    configure_azure_monitor(
        connection_string=connection_string,
        resource=Resource.create({"service.name": SERVICE_NAME}),
        sampling_ratio=SAMPLING_RATIO,
        # Only this package's own log lines are exported: they hold metadata only.
        logger_name=LOGGER_NAME,
        enable_live_metrics=False,
        enable_performance_counters=False,
        instrumentation_options=INSTRUMENTATION_OPTIONS,
    )
    OpenAIInstrumentor().instrument()
    logging.getLogger(LOGGER_NAME).setLevel(logging.INFO)
    _configured = True
    return True


def telemetry_configured() -> bool:
    return _configured


def flush_telemetry(timeout_millis: int = 10_000) -> None:
    """Send anything still buffered. Called when the app or a batch job stops."""
    if not _configured:
        return
    from opentelemetry._logs import get_logger_provider

    for provider in (trace.get_tracer_provider(), get_logger_provider()):
        force_flush = getattr(provider, "force_flush", None)
        if callable(force_flush):
            force_flush(timeout_millis)


def get_tracer(tracer_provider: trace.TracerProvider | None = None) -> trace.Tracer:
    """The tracer for the `score` span.

    Uses the given provider (tests), else the configured global one, else a local provider
    with no exporter, so that a response always carries a real trace id.
    """
    global _offline_provider
    if tracer_provider is not None:
        return tracer_provider.get_tracer(TRACER_NAME)
    if _configured:
        return trace.get_tracer(TRACER_NAME)
    if _offline_provider is None:
        _offline_provider = TracerProvider()
    return _offline_provider.get_tracer(TRACER_NAME)


def trace_id_of(span: trace.Span) -> str:
    """The W3C trace id of a span: 32 lower-case hex characters."""
    return format(span.get_span_context().trace_id, "032x")


# --- Custom events ----------------------------------------------------------------------


def is_safe_event_value(value: object) -> bool:
    """True for a boolean, a finite number, or short text made only of tokens."""
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, str):
        if len(value) > MAX_EVENT_TEXT_CHARS:
            return False
        return value == "" or all(_EVENT_TOKEN.fullmatch(part) for part in value.split(","))
    return False


def safe_event_attributes(attributes: Mapping[str, Any]) -> dict[str, str | bool | int | float]:
    """The attributes the allow-list lets through. A None value is simply left out."""
    return {
        key: value
        for key, value in attributes.items()
        if value is not None
        and isinstance(key, str)
        and _EVENT_ATTRIBUTE_NAME.fullmatch(key)
        and is_safe_event_value(value)
    }


def emit_custom_event(name: str, attributes: Mapping[str, Any]) -> None:
    """Record an Application Insights custom event. A no-op when telemetry is not configured.

    Only an event name on the allow-list is sent, with only the attributes the allow-list
    lets through. Anything else is dropped, never converted to text: an event with an
    unknown name is not sent at all, and a value that is not a number, a boolean or token
    text is left out. What was dropped is logged as a count, never as content.
    """
    if not _configured:
        return
    if name not in CUSTOM_EVENT_NAMES:
        _logger.warning("custom event not sent: its name is not on the allow-list")
        return
    safe = safe_event_attributes(attributes)
    dropped = sum(value is not None for value in attributes.values()) - len(safe)
    if dropped:
        _logger.warning("custom event %s: %d attributes dropped by the allow-list", name, dropped)
    extra: dict[str, str | bool | int | float] = {
        # A key that is also a field of a log record (such as `name`) gets a trailing
        # underscore, because the logging module refuses to overwrite its own fields.
        (f"{key}_" if key in _LOG_RECORD_FIELDS else key): value
        for key, value in safe.items()
    }
    extra[CUSTOM_EVENT_NAME_ATTRIBUTE] = name
    _event_logger.info(name, extra=extra)


# --- Cost estimate ----------------------------------------------------------------------


@dataclass(frozen=True)
class Prices:
    """Prices per one million tokens, from `config/prices.yaml`."""

    currency: str
    unit: str
    input: float
    cached_input: float
    output: float
    source_url: str
    retrieved: date
    model: str
    region: str


PRICE_KEYS = tuple(Prices.__dataclass_fields__)


@lru_cache(maxsize=8)
def _read_prices(path: Path) -> Prices:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise PricesError(f"prices file cannot be read: {type(error).__name__}") from error
    if not isinstance(data, dict) or set(data) != set(PRICE_KEYS):
        raise PricesError(f"prices file must hold exactly: {', '.join(PRICE_KEYS)}")
    if data["currency"] != "GBP" or data["unit"] != "per_1m_tokens":
        raise PricesError("prices must be in GBP per_1m_tokens")
    for key in ("input", "cached_input", "output"):
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise PricesError(f"price {key!r} must be a number that is not negative")
    if not isinstance(data["retrieved"], date):
        raise PricesError("`retrieved` must be a date")
    for key in ("source_url", "model", "region"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise PricesError(f"{key!r} must be text")
    return Prices(**data)


def load_prices(settings: Settings) -> Prices:
    return _read_prices(settings.config_dir / "prices.yaml")


def estimate_cost_gbp(tokens_in: int, tokens_out: int, settings: Settings) -> float:
    """Estimated cost of the model calls in GBP, from the token counts and the price file.

    Every input token is priced at the full input rate (no cached-input discount), so the
    figure is an upper estimate, never the invoice.
    """
    prices = load_prices(settings)
    cost = (tokens_in * prices.input + tokens_out * prices.output) / 1_000_000
    return round(cost, 6)


# --- The score span ---------------------------------------------------------------------


def score_span_attributes(outcome: ScoreOutcome, settings: Settings) -> dict[str, Any]:
    """The attributes of the `score` span. Metadata only: ids, hashes, counts and flags.

    `scorer.runs` and `scorer.review_reasons` are comma-separated text (for example
    `4,4,3` and `adverse_score,off_topic`), which reads the same in every backend.
    """
    response = outcome.response
    flags = response.flags
    attributes: dict[str, Any] = {
        "scorer.request_id": response.request_id,
        "scorer.answer_hash": outcome.answer_hash,
        "scorer.competency": response.competency_id,
        "scorer.prompt_version": response.prompt_version,
        "scorer.prompt_sha": outcome.prompt_sha,
        "scorer.model_deployment": response.model_deployment,
        "scorer.model_version": outcome.model_version or settings.model_version,
        "scorer.score": response.score,
        "scorer.runs": ",".join(str(run) for run in response.runs),
        "scorer.spread": response.spread,
        "scorer.needs_human_review": response.needs_human_review,
        "scorer.review_reasons": ",".join(response.review_reasons),
        "scorer.injection_detected": flags.injection_detected,
        "scorer.hidden_text_removed": flags.hidden_text_removed,
        "scorer.platform_guardrail": flags.platform_guardrail,
        "scorer.rationale_protected_term": flags.rationale_protected_term,
        "scorer.ungrounded_quotes": flags.ungrounded_quotes,
        "scorer.input_chars": outcome.input_chars,
        "scorer.tokens_in": outcome.tokens_in,
        "scorer.tokens_out": outcome.tokens_out,
        "scorer.cost_estimate_gbp": estimate_cost_gbp(
            outcome.tokens_in, outcome.tokens_out, settings
        ),
    }
    return {name: value for name, value in attributes.items() if value is not None}
