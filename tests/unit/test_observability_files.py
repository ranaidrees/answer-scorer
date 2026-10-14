"""The dashboard queries, the workbook file and the observability Bicep, read as text.

`dashboards/queries.kql` is the place a query is read and changed. The workbook file and
the alert rules hold copies, and these tests keep the copies equal. They also keep IDs,
addresses and candidate text out of all of them. Nothing here calls Azure.
"""

from __future__ import annotations

import inspect
import json
import re

import pytest
import yaml

from evals import run_evals
from scorer.telemetry import SCORE_SPAN_ATTRIBUTES
from tests.unit.samples import REPO_ROOT

QUERIES_FILE = REPO_ROOT / "dashboards" / "queries.kql"
WORKBOOK_FILE = REPO_ROOT / "infra" / "workbook.json"
BICEP_FILE = REPO_ROOT / "infra" / "observability.bicep"
SLO_FILE = REPO_ROOT / "docs" / "slo.md"
TRAFFIC_FILE = REPO_ROOT / "scripts" / "traffic.py"

TILE_QUERIES = (
    "tile1_requests_latency",
    "tile1_latency_over_time",
    "tile2_review_rate_by_reason",
    "tile2_review_rate_over_time",
    "tile3_tokens_cost",
    "tile4_eval_runs",
    "tile5_drift_by_day",
    "tile6_requests_to_look_at",
)
ALERT_QUERIES = ("alert_latency_p95", "alert_availability")
REVIEW_REASONS = (
    "injection_detected",
    "hidden_text_removed",
    "platform_guardrail",
    "ungrounded_quote",
    "inconsistent",
    "off_topic",
    "rationale_protected_term",
    "adverse_score",
)

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# The one GUID-shaped value allowed: the made-up id of the workbook's time-range parameter.
PARAMETER_ID = "a0000000-0000-4000-8000-000000000001"


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def load_queries() -> dict[str, dict[str, str]]:
    """Each named query of the file, as its comment and its text."""
    queries: dict[str, dict[str, list[str]]] = {}
    current = None
    for line in read(QUERIES_FILE).splitlines():
        header = re.fullmatch(r"// name: ([a-z0-9_]+)", line)
        if header:
            current = queries.setdefault(header.group(1), {"comment": [], "text": []})
        elif current is not None:
            current["comment" if line.startswith("//") else "text"].append(line)
    return {
        name: {"comment": "\n".join(parts["comment"]), "text": "\n".join(parts["text"]).strip()}
        for name, parts in queries.items()
    }


def workbook() -> dict:
    return json.loads(read(WORKBOOK_FILE))


def workbook_queries() -> list[dict]:
    return [item["content"] for item in workbook()["items"] if item["type"] == 3]


def bicep_resource(symbol: str) -> str:
    """The text of one resource block of the Bicep file."""
    match = re.search(rf"^resource {symbol} .*?^}}$", read(BICEP_FILE), re.DOTALL | re.MULTILINE)
    assert match, f"resource {symbol} not found"
    return match.group(0)


# --- dashboards/queries.kql ----------------------------------------------------------------


def test_there_is_one_named_and_commented_query_per_tile_and_per_alert():
    queries = load_queries()
    assert tuple(queries) == TILE_QUERIES + ALERT_QUERIES
    for name, query in queries.items():
        assert len(query["comment"]) > 80, f"{name} needs a comment that explains it"
        assert query["text"], name
    assert {name[:5] for name in TILE_QUERIES} == {
        "tile1",
        "tile2",
        "tile3",
        "tile4",
        "tile5",
        "tile6",
    }


def test_no_query_sets_its_own_time_range():
    for name, query in load_queries().items():
        assert "ago(" not in query["text"] and "now(" not in query["text"], name


def test_queries_read_only_the_three_metadata_tables_and_never_a_message():
    tables = re.compile(r"\b(traces|exceptions|pageViews|browserTimings|AppTraces)\b")
    for name, query in load_queries().items():
        text = query["text"]
        assert not tables.search(text), name
        assert not re.search(r"\b(message|details|outerMessage)\b", text), name
        first_table = re.search(r"\b(requests|dependencies|customEvents)\b", text)
        assert first_table, name


def test_every_span_attribute_a_query_reads_is_one_the_score_span_carries():
    read_attributes = set(re.findall(r'"(scorer\.[a-z_]+)"', read(QUERIES_FILE)))
    assert read_attributes, "the tile queries are expected to read scorer.* attributes"
    assert read_attributes <= set(SCORE_SPAN_ATTRIBUTES)
    for kept_out in ("scorer.answer_hash",):
        assert kept_out not in read_attributes, "a dashboard has no use for a per-answer id"


def test_the_review_tile_lists_every_review_reason_the_service_can_give():
    from scorer.aggregate import REVIEW_REASONS as service_reasons

    assert set(REVIEW_REASONS) == set(service_reasons)
    text = load_queries()["tile2_review_rate_by_reason"]["text"]
    for reason in service_reasons:
        assert f'"{reason}"' in text, reason


def test_the_control_triggered_rate_leaves_out_the_adverse_score_rule_alone():
    queries = load_queries()
    for name in ("tile2_review_rate_by_reason", "tile2_review_rate_over_time"):
        text = queries[name]["text"]
        assert 'set_difference(reason_list, dynamic(["adverse_score"]))' in text, name
        assert "25" in text, f"{name} shows the 25% band"


def test_the_eval_tile_reads_fields_that_the_eval_run_event_really_has():
    text = load_queries()["tile4_eval_runs"]["text"]
    fields = set(re.findall(r'customDimensions\["([a-z0-9_]+)"\]', text))
    metric_ids = set(yaml.safe_load(read(REPO_ROOT / "evals" / "thresholds.yaml")))
    event_source = inspect.getsource(run_evals.eval_event_attributes)

    metrics = {field for field in fields if field.startswith("golden_")}
    assert metrics == {
        "golden_qwk",
        "golden_exact",
        "golden_within_1",
        "golden_control_review_rate",
    }
    assert metrics <= metric_ids
    for field in fields - metrics:
        assert f'"{field}"' in event_source, field
    for trigger in ("pull_request", "schedule", "workflow_dispatch"):
        assert f'"{trigger}"' in text, trigger


def test_latency_is_measured_on_completed_requests_and_failures_leave_out_4xx():
    queries = load_queries()
    for name in ("tile1_requests_latency", "tile1_latency_over_time", "alert_latency_p95"):
        assert 'name == "POST /api/score"' in queries[name]["text"], name
        assert "== 200" in queries[name]["text"], name
    for name in ("tile1_requests_latency", "alert_availability"):
        assert "status < 400 or status >= 500" in queries[name]["text"], name


def test_an_alert_query_returns_no_row_when_there_is_no_data():
    queries = load_queries()
    latency = queries["alert_latency_p95"]["text"]
    assert latency.splitlines()[-1] == "| where completed_requests >= 5 and p95_ms > 6000"
    availability = queries["alert_availability"]["text"]
    assert "| where counted_requests > 0" in availability
    assert "| where availability < 99.0" in availability


def test_slo_comparisons_use_the_exact_figure_and_round_only_for_display():
    queries = load_queries()
    # 3 failures in 299 is 98.997%: rounded first, it would read 99.0 and pass unnoticed.
    availability = queries["alert_availability"]["text"]
    compared, shown = availability.split("| where availability < 99.0")
    assert "round(" not in compared and "round(availability, 2)" in shown

    tile1 = queries["tile1_requests_latency"]["text"]
    assert "availability >= 99.0" in tile1 and "p95_ms <= 6000" in tile1
    assert "availability_pct >= 99.0" not in tile1 and "p95_s <= 6.0" not in tile1

    tile2 = queries["tile2_review_rate_by_reason"]["text"]
    assert "rate <= 25.0" in tile2 and "rate_pct <= 25.0" not in tile2


def test_cost_per_score_is_averaged_over_requests_that_have_a_score():
    text = load_queries()["tile3_tokens_cost"]["text"]
    assert 'has_score = isnotempty(tostring(customDimensions["scorer.score"]))' in text
    assert "scores = countif(has_score)" in text
    assert "blocked_no_score = countif(not(has_score))" in text
    for column in ("tokens_in", "tokens_out", "cost_gbp"):
        assert f"avgif({column}, has_score)" in text, column
    assert "avg(" not in text.replace("avgif(", "")


def test_the_drift_tile_compares_each_scored_day_with_the_first_day_of_the_range():
    text = load_queries()["tile5_drift_by_day"]["text"]
    # Scored requests only, one row per day, against the first day the caller's range holds.
    assert 'isnotempty(tostring(customDimensions["scorer.score"]))' in text
    assert "bin(timestamp, 1d)" in text
    assert "min(day)" in text and "mean_score - base_mean" in text
    # The distribution, the input length and the two flags it follows, as shares of scores.
    for column in ("low_1_2_pct", "mid_3_pct", "high_4_5_pct", "median_input_chars"):
        assert column in text, column
    for reason in ("injection_detected", "off_topic"):
        assert f'"{reason}"' in text, reason
    assert "/ scores" in text, "rates are shares of the day's scored requests"


def test_the_requests_tile_lists_metadata_with_the_trace_id_and_puts_tripped_controls_first():
    text = load_queries()["tile6_requests_to_look_at"]["text"]
    assert "trace_id = operation_Id" in text
    assert 'set_difference(reason_list, dynamic(["adverse_score"]))' in text
    assert "order by look_first desc, timestamp desc" in text and "take 50" in text
    assert "pipeline_s > 6.0" in text


# --- infra/workbook.json -------------------------------------------------------------------


def test_the_workbook_shows_exactly_the_tile_queries_of_the_queries_file():
    queries = load_queries()
    shown = [content["query"] for content in workbook_queries()]
    assert shown == [queries[name]["text"] for name in TILE_QUERIES]


def test_the_workbook_has_a_time_range_parameter_that_every_tile_uses():
    book = workbook()
    assert book["version"] == "Notebook/1.0"
    parameters = [
        parameter
        for item in book["items"]
        if item["type"] == 9
        for parameter in item["content"]["parameters"]
    ]
    assert [(parameter["name"], parameter["type"]) for parameter in parameters] == [
        ("TimeRange", 4)
    ]
    assert parameters[0]["isRequired"] is True and parameters[0]["value"]["durationMs"] > 0
    for content in workbook_queries():
        assert content["timeContextFromParameter"] == "TimeRange", content["title"]
        assert content["resourceType"] == "microsoft.insights/components"
        assert content["queryType"] == 0


def test_every_tile_has_a_title_that_says_what_it_is_and_cost_is_called_an_estimate():
    titles = [content["title"] for content in workbook_queries()]
    assert all(len(title) > 30 for title in titles)
    assert "6 s" in titles[0] and "6 s" in titles[1]
    assert "25% band" in titles[2] and "25% band" in titles[3]
    assert "estimate" in titles[4].lower() and "not the invoice" in titles[4]
    assert "kappa" in titles[5] and "nightly" in titles[5]
    headings = " ".join(
        item["content"]["json"] for item in workbook()["items"] if item["type"] == 1
    )
    for number in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6."):
        assert number in headings
    assert "drift" in titles[6].lower() and "no labels" in titles[6]
    assert "trace id" in titles[7]
    assert "15% CI gate" in headings and "25% band for live traffic" in headings
    assert "No candidate text" in headings


def test_the_workbook_file_holds_no_resource_id():
    text = read(WORKBOOK_FILE)
    book = workbook()
    assert "fallbackResourceIds" not in book, "the resource is bound in Bicep at deploy time"
    assert "/subscriptions/" not in text and "resourceGroups" not in text
    assert "crossComponentResources" not in text
    assert "InstrumentationKey" not in text and "IngestionEndpoint" not in text
    assert GUID.findall(text) == [PARAMETER_ID]


# --- infra/observability.bicep -------------------------------------------------------------


def test_the_alert_rules_run_exactly_the_alert_queries_of_the_queries_file():
    queries = load_queries()
    blocks = dict(re.findall(r"var (\w+) = '''\n(.*?)'''", read(BICEP_FILE), re.DOTALL))
    assert blocks["latencyQuery"].strip() == queries["alert_latency_p95"]["text"]
    assert blocks["availabilityQuery"].strip() == queries["alert_availability"]["text"]
    assert "query: latencyQuery" in bicep_resource("latencyAlert")
    assert "query: availabilityQuery" in bicep_resource("availabilityAlert")


@pytest.mark.parametrize(
    ("symbol", "frequency", "window"),
    [("latencyAlert", "PT15M", "PT15M"), ("availabilityAlert", "PT1H", "PT1H")],
)
def test_each_alert_rule_has_the_window_of_its_slo_and_fires_only_on_a_row(
    symbol, frequency, window
):
    rule = bicep_resource(symbol)
    assert "'Microsoft.Insights/scheduledQueryRules@" in rule
    assert f"evaluationFrequency: '{frequency}'" in rule
    assert f"windowSize: '{window}'" in rule
    assert "enabled: true" in rule
    assert "timeAggregation: 'Count'" in rule
    assert "operator: 'GreaterThan'" in rule and "threshold: 0" in rule
    assert "applicationInsights.id" in rule and "actionGroup.id" in rule


def test_no_rule_runs_more_often_than_every_15_minutes():
    frequencies = re.findall(r"evaluationFrequency: '(\w+)'", read(BICEP_FILE))
    assert sorted(frequencies) == ["PT15M", "PT1H"], "a faster rule costs more each month"


def test_the_email_address_is_a_secure_parameter_with_no_default():
    text = read(BICEP_FILE)
    assert re.search(r"@secure\(\)\n@description\([^\n]*\)\nparam alertEmail string\n", text)
    assert "emailAddress: alertEmail" in bicep_resource("actionGroup")
    assert len(re.findall(r"emailAddress:", text)) == 1, "one email receiver"
    for other in ("smsReceivers", "webhookReceivers", "armRoleReceivers"):
        assert other not in text


def test_the_workbook_is_loaded_from_its_file_and_bound_by_a_parameter():
    text = read(BICEP_FILE)
    assert re.search(r"^param applicationInsightsName string$", text, re.MULTILINE)
    assert "loadTextContent('workbook.json')" in text
    assert "fallbackResourceIds" in text
    book = bicep_resource("workbook")
    assert "sourceId: applicationInsights.id" in book
    assert "serializedData: string(workbookContent)" in book


def test_the_file_deploys_only_the_four_observability_resources():
    text = read(BICEP_FILE)
    assert "targetScope = 'resourceGroup'" in text
    created = re.findall(r"^resource (\w+) '([\w./]+)@[\w-]+' = \{$", text, re.MULTILINE)
    assert sorted(kind for _, kind in created) == [
        "Microsoft.Insights/actionGroups",
        "Microsoft.Insights/scheduledQueryRules",
        "Microsoft.Insights/scheduledQueryRules",
        "Microsoft.Insights/workbooks",
    ]
    referenced = re.findall(
        r"^resource (\w+) '([\w./]+)@[\w-]+' existing = \{$", text, re.MULTILINE
    )
    assert [kind for _, kind in referenced] == ["Microsoft.Insights/components"]
    assert "module " not in text and "main.bicep'" not in text
    assert "roleAssignments" not in text
    for symbol, _ in created:
        assert "tags: tags" in bicep_resource(symbol), symbol
    for tag in ("project: 'answer-scorer'", "env: 'demo'", "owner: ownerTag"):
        assert tag in text


# --- All of the slice's files --------------------------------------------------------------


@pytest.mark.parametrize(
    "path", [QUERIES_FILE, WORKBOOK_FILE, BICEP_FILE, SLO_FILE, TRAFFIC_FILE], ids=lambda p: p.name
)
def test_no_file_of_the_slice_holds_an_id_an_address_or_an_em_dash(path):
    text = read(path)
    assert not EMAIL.search(text), "no email address"
    assert [found for found in GUID.findall(text) if found != PARAMETER_ID] == []
    assert "/subscriptions/" not in text
    assert "InstrumentationKey=" not in text
    assert ".azurecontainerapps.io" not in text and ".applicationinsights.azure.com" not in text
    assert chr(0x2014) not in text and chr(0x2013) not in text, "no em or en dash"


def test_the_slo_page_names_a_query_for_every_measure_and_keeps_the_two_rates_apart():
    text = read(SLO_FILE)
    for name in TILE_QUERIES + ALERT_QUERIES:
        assert f"`{name}`" in text, name
    for rule in ("alert-answer-scorer-latency-p95", "alert-answer-scorer-availability"):
        assert rule in text, rule
    assert "15%" in text and "25%" in text
    assert "golden set" in text and "live traffic" in text
