"""Telemetry set-up, the content-capture guard, custom events and the cost estimate.

No test here reaches Azure: the Azure Monitor set-up call is replaced by a recorder.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest
import yaml

from scorer import telemetry
from scorer.api import create_app
from scorer.telemetry import (
    PRICE_KEYS,
    SCORE_SPAN_ATTRIBUTES,
    ContentCaptureError,
    PricesError,
    configure_telemetry,
    emit_custom_event,
    estimate_cost_gbp,
    get_tracer,
    load_prices,
    score_span_attributes,
    trace_id_of,
)
from tests.unit.samples import REPO_ROOT, make_settings, run_score

CAPTURE = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
HOOK = "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK"
CONNECTION = "synthetic-connection-value"  # never parsed: the set-up call is replaced


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv(CAPTURE, raising=False)
    monkeypatch.delenv(HOOK, raising=False)
    monkeypatch.setattr(telemetry, "_configured", False)


@pytest.fixture
def azure_monitor(monkeypatch):
    """Replace the Azure Monitor and OpenAI instrumentation set-up with recorders."""
    import azure.monitor.opentelemetry as distro
    import opentelemetry.instrumentation.openai_v2 as openai_v2

    calls: dict[str, list] = {"configure": [], "instrument": []}

    class Instrumentor:
        def instrument(self, **kwargs):
            calls["instrument"].append(kwargs)

    monkeypatch.setattr(
        distro, "configure_azure_monitor", lambda **kw: calls["configure"].append(kw)
    )
    monkeypatch.setattr(openai_v2, "OpenAIInstrumentor", Instrumentor)
    level = logging.getLogger("scorer").level
    yield calls
    logging.getLogger("scorer").setLevel(level)


# --- configure_telemetry ----------------------------------------------------------------


def test_without_a_connection_string_telemetry_is_a_no_op(azure_monitor):
    assert configure_telemetry(make_settings()) is False
    assert azure_monitor == {"configure": [], "instrument": []}
    assert telemetry.telemetry_configured() is False


def test_with_a_connection_string_azure_monitor_is_configured_at_full_sampling(azure_monitor):
    settings = make_settings(applicationinsights_connection_string=CONNECTION)

    assert configure_telemetry(settings) is True

    (kwargs,) = azure_monitor["configure"]
    assert kwargs["connection_string"] == CONNECTION
    assert kwargs["sampling_ratio"] == 1.0, "spec C8: sampling at 100%"
    assert kwargs["logger_name"] == "scorer", "only this package's metadata log lines are sent"
    assert kwargs["enable_live_metrics"] is False
    options = kwargs["instrumentation_options"]
    assert options["httpx2"] == {"enabled": True}, "the model's HTTP calls are traced"
    assert options["fastapi"] == {"enabled": False}, "the API instruments its own app"
    assert [name for name, option in options.items() if option["enabled"]] == ["httpx2"]
    assert azure_monitor["instrument"] == [{}], "the OpenAI instrumentation is started once"
    assert telemetry.telemetry_configured() is True


def test_configuring_twice_sets_up_once(azure_monitor):
    settings = make_settings(applicationinsights_connection_string=CONNECTION)
    assert configure_telemetry(settings) is True
    assert configure_telemetry(settings) is True
    assert len(azure_monitor["configure"]) == 1 and len(azure_monitor["instrument"]) == 1


# --- The content-capture guard ----------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "True", "TRUE", " true ", "1", "yes", "span_only"])
@pytest.mark.parametrize("connection", [None, CONNECTION])
def test_telemetry_refuses_to_start_when_content_capture_is_on(
    monkeypatch, azure_monitor, value, connection
):
    monkeypatch.setenv(CAPTURE, value)
    settings = make_settings(applicationinsights_connection_string=connection)

    with pytest.raises(ContentCaptureError, match=CAPTURE):
        configure_telemetry(settings)

    assert azure_monitor == {"configure": [], "instrument": []}
    assert telemetry.telemetry_configured() is False


@pytest.mark.parametrize("value", ["event_only", "span_and_event", "SPAN_AND_EVENT"])
def test_the_newer_capture_modes_are_refused_too(monkeypatch, azure_monitor, value):
    monkeypatch.setenv(CAPTURE, value)
    with pytest.raises(ContentCaptureError):
        configure_telemetry(make_settings(applicationinsights_connection_string=CONNECTION))
    assert azure_monitor["configure"] == []


def test_a_completion_hook_is_refused_because_it_also_records_content(monkeypatch, azure_monitor):
    monkeypatch.setenv(HOOK, "upload")
    with pytest.raises(ContentCaptureError, match=HOOK):
        configure_telemetry(make_settings(applicationinsights_connection_string=CONNECTION))
    assert azure_monitor["configure"] == []


@pytest.mark.parametrize("value", ["", "false", "False", "FALSE", " false ", "no_content"])
def test_content_capture_unset_or_false_lets_telemetry_start(monkeypatch, azure_monitor, value):
    monkeypatch.setenv(CAPTURE, value)
    settings = make_settings(applicationinsights_connection_string=CONNECTION)
    assert configure_telemetry(settings) is True


def test_the_app_refuses_to_start_when_content_capture_is_on(monkeypatch):
    monkeypatch.setenv(CAPTURE, "true")
    with pytest.raises(ContentCaptureError):
        create_app(make_settings(demo_token="x"), None)


def test_the_guard_still_holds_after_telemetry_was_configured(monkeypatch, azure_monitor):
    settings = make_settings(applicationinsights_connection_string=CONNECTION)
    assert configure_telemetry(settings) is True
    monkeypatch.setenv(CAPTURE, "true")
    with pytest.raises(ContentCaptureError):
        configure_telemetry(settings)


# --- Custom events ----------------------------------------------------------------------


def test_emit_custom_event_is_a_no_op_when_telemetry_is_not_configured(caplog):
    caplog.set_level(logging.DEBUG)
    emit_custom_event("eval_run", {"gate": "pass"})
    assert caplog.records == []


def test_emit_custom_event_sends_one_record_marked_as_an_application_insights_event(
    azure_monitor, caplog
):
    configure_telemetry(make_settings(applicationinsights_connection_string=CONNECTION))
    caplog.set_level(logging.INFO, logger="scorer.events")

    emit_custom_event(
        "eval_run",
        {"git_sha": "abc1234", "qwk": 0.81, "passed": True, "n": 30, "skipped": None, "by": ["a"]},
    )

    (record,) = [item for item in caplog.records if item.name == "scorer.events"]
    assert getattr(record, "microsoft.custom_event.name") == "eval_run"
    assert record.git_sha == "abc1234" and record.qwk == 0.81
    assert record.passed is True and record.n == 30
    assert record.by == '["a"]', "a value that is not a scalar is sent as JSON text"
    assert not hasattr(record, "skipped"), "a None value is left out"


def test_an_event_attribute_named_like_a_log_record_field_is_renamed_not_refused(
    azure_monitor, caplog
):
    configure_telemetry(make_settings(applicationinsights_connection_string=CONNECTION))
    caplog.set_level(logging.INFO, logger="scorer.events")

    emit_custom_event("eval_run", {"name": "nightly", "module": "evals", "message": "done"})

    (record,) = [item for item in caplog.records if item.name == "scorer.events"]
    assert (record.name_, record.module_, record.message_) == ("nightly", "evals", "done")


# --- The tracer -------------------------------------------------------------------------


def test_the_offline_tracer_still_gives_a_real_trace_id():
    with get_tracer().start_as_current_span("score") as span:
        trace_id = trace_id_of(span)
    assert len(trace_id) == 32 and int(trace_id, 16) != 0
    assert trace_id == trace_id.lower()


# --- Prices and the cost estimate -------------------------------------------------------


def test_prices_yaml_has_every_key_and_its_source():
    data = yaml.safe_load((REPO_ROOT / "config" / "prices.yaml").read_text(encoding="utf-8"))

    assert set(data) == {
        "currency",
        "unit",
        "input",
        "cached_input",
        "output",
        "source_url",
        "retrieved",
        "model",
        "region",
    }
    assert set(data) == set(PRICE_KEYS)
    assert data["currency"] == "GBP" and data["unit"] == "per_1m_tokens"
    for key in ("input", "cached_input", "output"):
        assert isinstance(data[key], float) and data[key] > 0
    assert data["cached_input"] < data["input"] < data["output"]
    assert data["source_url"].startswith("https://prices.azure.com/")
    assert isinstance(data["retrieved"], date) and data["retrieved"] >= date(2026, 10, 13)
    assert data["model"] == "gpt-5.4-mini" and data["region"] == "uksouth"


def test_load_prices_reads_the_committed_file(settings):
    prices = load_prices(settings)
    assert prices.currency == "GBP" and prices.model == "gpt-5.4-mini"


def write_prices(root, **changes) -> None:
    data = {
        "currency": "GBP",
        "unit": "per_1m_tokens",
        "input": 2.0,
        "cached_input": 0.2,
        "output": 10.0,
        "source_url": "https://prices.example/api",
        "retrieved": date(2026, 10, 13),
        "model": "synthetic-model",
        "region": "nowhere",
    }
    data.update(changes)
    data = {key: value for key, value in data.items() if value is not ...}
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "prices.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_estimate_cost_gbp_matches_hand_computed_numbers(tmp_path):
    write_prices(tmp_path)
    settings = make_settings(root=tmp_path)

    # 2.00 per 1M input tokens and 10.00 per 1M output tokens.
    assert estimate_cost_gbp(0, 0, settings) == 0.0
    assert estimate_cost_gbp(1_000_000, 0, settings) == 2.0
    assert estimate_cost_gbp(0, 1_000_000, settings) == 10.0
    assert estimate_cost_gbp(1000, 100, settings) == pytest.approx(0.003)  # 0.002 + 0.001
    assert estimate_cost_gbp(3600, 450, settings) == pytest.approx(0.0117)  # 0.0072 + 0.0045


def test_estimate_cost_gbp_with_the_committed_prices(settings):
    # 3600 x 0.5661 / 1e6 = 0.00203796 and 450 x 3.3964 / 1e6 = 0.00152838; sum 0.00356634.
    assert estimate_cost_gbp(3600, 450, settings) == pytest.approx(0.003566, abs=1e-9)
    assert estimate_cost_gbp(1_000_000, 0, settings) == pytest.approx(0.5661)
    assert estimate_cost_gbp(0, 1_000_000, settings) == pytest.approx(3.3964)


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "USD"},
        {"unit": "per_1k_tokens"},
        {"input": -1.0},
        {"output": "3.39"},
        {"output": True},
        {"retrieved": "yesterday"},
        {"source_url": ""},
        {"cached_input": ...},
        {"extra": 1},
    ],
)
def test_a_price_file_that_is_not_valid_is_an_error_never_a_guess(tmp_path, changes):
    write_prices(tmp_path, **changes)
    with pytest.raises(PricesError):
        estimate_cost_gbp(1000, 100, make_settings(root=tmp_path))


def test_a_missing_price_file_is_an_error_never_a_guess(tmp_path):
    with pytest.raises(PricesError):
        estimate_cost_gbp(1000, 100, make_settings(root=tmp_path))


# --- The score span attributes ----------------------------------------------------------


def test_score_span_attributes_uses_only_the_fixed_names(settings):
    attributes = score_span_attributes(run_score(), settings)
    assert set(attributes) == set(SCORE_SPAN_ATTRIBUTES)
    assert len(SCORE_SPAN_ATTRIBUTES) == 21
    for value in attributes.values():
        assert isinstance(value, (str, bool, int, float)), "a span attribute is a scalar"
