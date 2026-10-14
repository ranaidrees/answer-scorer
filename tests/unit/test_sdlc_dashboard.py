"""The delivery evidence workbook: its builder, the committed workbook file and its Bicep.

`scripts/build_sdlc_workbook.py` turns the snapshot and four tile queries of
`dashboards/queries.kql` into `infra/sdlc_workbook.json`. These tests build from a small
snapshot written here, so they do not depend on the committed one, except the test that
the committed workbook is what the builder makes from the committed snapshot. They also
keep IDs, addresses and links to anywhere else out of the new files. Nothing here calls
Azure or GitHub.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts import build_sdlc_workbook as builder
from tests.unit.samples import REPO_ROOT
from tests.unit.test_observability_files import EMAIL, GUID, load_queries

QUERIES_FILE = REPO_ROOT / "dashboards" / "queries.kql"
SNAPSHOT_FILE = REPO_ROOT / "dashboards" / "sdlc_snapshot.json"
OPERATIONAL_WORKBOOK_FILE = REPO_ROOT / "infra" / "workbook.json"
WORKBOOK_FILE = REPO_ROOT / "infra" / "sdlc_workbook.json"
BICEP_FILE = REPO_ROOT / "infra" / "sdlc_dashboard.bicep"
BUILDER_FILE = REPO_ROOT / "scripts" / "build_sdlc_workbook.py"
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
THIS_FILE = Path(__file__).resolve()

REPO = "https://github.com/ranaidrees/answer-scorer"
TABS = {
    "scorecard": "Trust scorecard",
    "before": "Before production",
    "production": "In production",
    "sdlc": "AI-native SDLC",
}
SCORECARD_FILE = REPO_ROOT / "dashboards" / "scorecard.kql"
THRESHOLDS_FILE = REPO_ROOT / "evals" / "thresholds.yaml"
LIVE_QUERIES = (
    "tile1_requests_latency",
    "tile2_review_rate_by_reason",
    "tile3_tokens_cost",
    "tile4_eval_runs",
)
PARAMETER_IDS = ("a0000000-0000-4000-8000-000000000001", "a0000000-0000-4000-8000-000000000002")
LINK = re.compile(r"https?://[^\s\"'`()<>\[\]]+")
ALLOWED_LINK = re.compile(
    r"https://(github\.com/ranaidrees/answer-scorer|learn\.microsoft\.com)(/|$)"
)


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def queries() -> dict[str, str]:
    return builder.parse_queries(read(QUERIES_FILE))


def fixture_snapshot() -> dict:
    """A small snapshot in the shape of spec section 3, with text that needs escaping."""
    return {
        "generated_at": "2026-10-14T15:30:00Z",
        "repository": "ranaidrees/answer-scorer",
        "before_production": {
            "figures": [
                {
                    "measure": "Tests passing",
                    "value": "12",
                    "detail": "unit and hook tests, every pull request",
                    "source": f"{REPO}/actions/workflows/ci.yml",
                },
                {
                    "measure": 'A "quoted" measure',
                    "value": "a\\b",
                    "detail": 'a backslash before a quote: \\"',
                    "source": f"{REPO}/blob/main/README.md",
                },
            ],
            "ci_runs": [
                {"started": "2026-10-13T15:27:07Z", "job_seconds": 15, "test_seconds": 7},
                {"started": "2026-10-13T16:02:41Z", "job_seconds": 14.5, "test_seconds": 6.25},
            ],
            "gates": [
                {
                    "gate": "Actions pinned to a full commit SHA",
                    "status": "5 of 5",
                    "source": f"{REPO}/tree/main/.github/workflows",
                }
            ],
        },
        "in_production": {
            "figures": [],
            "deploys": [
                {
                    "started": "2026-10-14T07:40:12Z",
                    "route": "merge of #16",
                    "commit": "cc949e0",
                    "approved_by_owner": "yes",
                    "provenance_verified": "yes",
                    "smoke_test": "passed",
                    "result": "success",
                    "source": f"{REPO}/actions/runs/1",
                }
            ],
        },
        "ai_native_sdlc": {
            "figures": [
                {
                    "measure": "Owner deploy approvals",
                    "value": "3",
                    "detail": "every production deploy",
                    "source": f"{REPO}/deployments",
                }
            ],
            "stages": [
                {
                    "stage": "Plan",
                    "artifact": "intent/intent.md",
                    "gate": "the owner commits it",
                    "source": f"{REPO}/blob/main/intent/intent.md",
                }
            ],
            "decisions_by_who": [
                {"who": "agent", "decisions": 3},
                {"who": "owner", "decisions": 1},
            ],
        },
        "trust_scorecard": {
            "checks": [
                {
                    "aorder": 5,
                    "aspect": "Golden dataset quality",
                    "corder": 1,
                    "check": 'Sizes as "specified"',
                    "target": "30, 16, 24, 6",
                    "critical": False,
                    "basis": "evals/datasets",
                    "actual": "30, 16, 24, 6",
                    "state": "met",
                },
                {
                    "aorder": 5,
                    "aspect": "Golden dataset quality",
                    "corder": 2,
                    "check": "Labels from trained human raters",
                    "target": "not set",
                    "critical": False,
                    "basis": "not done",
                    "actual": "0 of 30",
                    "state": "not measured",
                },
            ]
        },
    }


def built(snapshot: dict | None = None) -> dict:
    return builder.build(snapshot if snapshot is not None else fixture_snapshot(), queries())


def named(book: dict, name: str) -> dict:
    [found] = [entry for entry in book["items"] if entry["name"] == name]
    return found


def tab_items(book: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for entry in book["items"]:
        if "conditionalVisibility" in entry:
            grouped.setdefault(entry["conditionalVisibility"]["value"], []).append(entry)
    return grouped


def kql_literals(query: str) -> list[str]:
    """Every double-quoted string literal in a KQL query, read back as KQL reads it."""
    values, position = [], 0
    while (start := query.find('"', position)) != -1:
        characters, index = [], start + 1
        while query[index] != '"':
            if query[index] == "\\":
                index += 1
            characters.append(query[index])
            index += 1
        values.append("".join(characters))
        position = index + 1
    return values


def strings(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [text for value in node.values() for text in strings(value)]
    if isinstance(node, list):
        return [text for value in node for text in strings(value)]
    return []


# --- The builder ----------------------------------------------------------------------------


def test_the_workbook_has_four_tabs_and_every_item_after_them_shows_on_one_tab():
    book = built()
    assert book["version"] == "Notebook/1.0" and "fallbackResourceIds" not in book
    assert [entry["name"] for entry in book["items"][:3]] == ["introduction", "parameters", "tabs"]
    for entry in book["items"][:3]:
        assert "conditionalVisibility" not in entry, entry["name"]

    links = named(book, "tabs")
    assert links["type"] == 11
    assert links["content"]["version"] == "LinkItem/1.0" and links["content"]["style"] == "tabs"
    assert [
        (link["cellValue"], link["linkTarget"], link["subTarget"], link["linkLabel"])
        for link in links["content"]["links"]
    ] == [("selectedTab", "parameter", value, label) for value, label in TABS.items()]

    for entry in book["items"][3:]:
        assert entry["conditionalVisibility"] == {
            "parameterName": "selectedTab",
            "comparison": "isEqualTo",
            "value": entry["conditionalVisibility"]["value"],
        }, entry["name"]
    grouped = tab_items(book)
    assert list(grouped) == list(TABS)
    assert sum(len(entries) for entries in grouped.values()) == len(book["items"]) - 3


def test_every_tab_starts_with_a_heading_and_ends_with_the_caption_on_what_it_does_not_prove():
    for tab, entries in tab_items(built()).items():
        heading, last = entries[0], entries[-1]
        assert heading["type"] == 1 and heading["content"]["json"].startswith("## "), tab
        assert TABS[tab] in heading["content"]["json"]
        assert "14 October 2026, 15:30 UTC" in heading["content"]["json"], tab
        assert last["type"] == 1 and last["name"] == f"{tab} caption"
        text = last["content"]["json"]
        for phrase in (
            "does not prove",
            "synthetic",
            "Reliability is not validity",
            "made by an AI agent, not a person",
            "snapshot dated 14 October 2026, 15:30 UTC",
            "says live",
        ):
            assert phrase in text, (tab, phrase)


def test_the_introduction_dates_the_snapshot_and_names_the_operational_workbook():
    text = named(built(), "introduction")["content"]["json"]
    assert text.startswith("# Answer scorer: delivery evidence\n")
    assert "Snapshot of 14 October 2026, 15:30 UTC" in text
    assert "refreshed by a pull request" in text
    assert "**Answer scorer dashboard**" in text


def test_the_parameters_are_a_30_day_time_range_and_a_hidden_tab_parameter():
    content = named(built(), "parameters")["content"]
    assert named(built(), "parameters")["type"] == 9
    assert content["version"] == "KqlParameterItem/1.0"
    time_range, tab = content["parameters"]
    assert (time_range["id"], tab["id"]) == PARAMETER_IDS == builder.PARAMETER_IDS
    assert (time_range["name"], time_range["type"], time_range["isRequired"]) == (
        "TimeRange",
        4,
        True,
    )
    assert time_range["value"] == time_range["timeContext"] == {"durationMs": 2_592_000_000}
    operational = json.loads(read(OPERATIONAL_WORKBOOK_FILE))
    [existing] = [entry for entry in operational["items"] if entry["type"] == 9]
    assert time_range["typeSettings"] == existing["content"]["parameters"][0]["typeSettings"], (
        "the same choices as the operational dashboard"
    )
    assert (tab["name"], tab["type"], tab["value"], tab["isHiddenWhenLocked"]) == (
        "selectedTab",
        1,
        "scorecard",
        True,
    )


def test_every_item_has_a_unique_name():
    names = [entry["name"] for entry in built()["items"]]
    assert all(names) and len(names) == len(set(names))


def test_the_two_query_parsers_agree():
    ours = queries()
    theirs = load_queries()
    assert set(ours) == set(theirs)
    for name in ours:
        assert ours[name] == theirs[name]["text"], name


def test_the_live_tiles_are_tiles_1_to_4_of_the_queries_file_word_for_word():
    book = built()
    live = [
        entry
        for entry in book["items"]
        if "timeContextFromParameter" in entry["content"]
        and not entry["name"].startswith("scorecard")
    ]
    expected = load_queries()
    assert [entry["content"]["query"] for entry in live] == [
        expected[name]["text"] for name in LIVE_QUERIES
    ]
    assert builder.LIVE_QUERIES == LIVE_QUERIES

    operational = {
        entry["content"]["query"]: entry["content"]
        for entry in json.loads(read(OPERATIONAL_WORKBOOK_FILE))["items"]
        if entry["type"] == 3
    }
    for entry in live:
        content = entry["content"]
        assert entry["conditionalVisibility"]["value"] == "production", entry["name"]
        assert content["timeContextFromParameter"] == "TimeRange"
        existing = operational[content["query"]]
        for key in ("title", "noDataMessage", "size", "visualization", "queryType"):
            assert content[key] == existing[key], (entry["name"], key)
        assert content["resourceType"] == "microsoft.insights/components"


def test_the_scorecard_tab_shows_score_aspects_validity_confidence_and_checks():
    names = [entry["name"] for entry in tab_items(built())["scorecard"]]
    assert names == [
        "scorecard heading",
        "scorecard overall",
        "scorecard aspects",
        "scorecard validity",
        "scorecard confidence",
        "scorecard confidence note",
        "scorecard checks",
        "scorecard caption",
    ]
    book = built()
    validity = named(book, "scorecard validity")["content"]
    assert validity["style"] == "warning" and "not established" in validity["json"]
    assert (
        "not a calibrated probability"
        in named(book, "scorecard confidence note")["content"]["json"]
    )
    for name in (
        "scorecard overall",
        "scorecard aspects",
        "scorecard checks",
        "scorecard confidence",
    ):
        content = named(book, name)["content"]
        assert content["timeContextFromParameter"] == "TimeRange", name
        assert (content["queryType"], content["visualization"]) == (0, "table"), name


def test_the_scorecard_queries_are_the_parts_of_its_file_with_every_token_filled():
    parts = builder.parse_parts(read(SCORECARD_FILE))
    assert tuple(parts) == ("checks", "overall", "aspects", "detail", "confidence")
    book = built()
    filled = builder.fill_scorecard(
        parts["checks"],
        builder.parse_thresholds(read(THRESHOLDS_FILE)),
        builder.static_rows(fixture_snapshot()["trust_scorecard"]),
    )
    for name, part in (
        ("scorecard overall", "overall"),
        ("scorecard aspects", "aspects"),
        ("scorecard checks", "detail"),
    ):
        assert named(book, name)["content"]["query"] == filled + "\n" + parts[part], name
    assert named(book, "scorecard confidence")["content"]["query"] == parts["confidence"]
    for entry in book["items"]:
        if entry["name"].startswith("scorecard") and entry["type"] == 3:
            query = entry["content"]["query"]
            assert not re.search(r"__[A-Z]+_", query), entry["name"]
            assert "{" not in query and "}" not in query, entry["name"]


def test_the_scorecard_gate_values_are_those_of_the_thresholds_file():
    thresholds = builder.parse_thresholds(read(THRESHOLDS_FILE))
    filled = named(built(), "scorecard checks")["content"]["query"]
    assert f'"at least {thresholds["golden_qwk"]:g}"' in filled
    assert f'"at most {thresholds["ungrounded_quote_rate"] * 100:g}%"' in filled
    # The state of an offline check is the gate's own verdict, never a re-comparison.
    assert 'tolower(tostring(ev["golden_qwk_passed"])) == "true"' in filled
    assert 'todouble(ev["golden_qwk"]) >=' not in filled
    assert f'"at most {thresholds["golden_control_review_rate"] * 100:g}%"' in filled
    assert f'"at least {thresholds["golden_within_1"] * 100:g}%"' in filled
    used = set(re.findall(r"__[TP]_([a-z0-9_]+)__", read(SCORECARD_FILE)))
    assert used <= set(thresholds), "every gate the scorecard names is in thresholds.yaml"


def test_scorecard_static_rows_are_typed_and_their_states_are_limited():
    rows = builder.static_rows(fixture_snapshot()["trust_scorecard"])
    assert rows.startswith(
        "datatable(aorder: long, aspect: string, corder: long, check: string, target: string, "
        "critical: bool, basis: string, actual: string, state: string) [\n"
    )
    assert '"Sizes as \\"specified\\""' in rows and ", false, " in rows
    bad = fixture_snapshot()["trust_scorecard"]
    bad["checks"][0]["state"] = "great"
    with pytest.raises(ValueError):
        builder.static_rows(bad)
    bad = fixture_snapshot()["trust_scorecard"]
    bad["checks"][0]["critical"] = "no"
    with pytest.raises(ValueError):
        builder.static_rows(bad)
    with pytest.raises(ValueError):
        builder.fill_scorecard("x __T_no_such_metric__", {}, "datatable(a: long) []")
    with pytest.raises(ValueError):
        builder.fill_scorecard("x | where a == 1 { }", {}, "")


def test_the_production_tab_shows_deploys_then_figures_then_the_live_tiles():
    names = [entry["name"] for entry in tab_items(built())["production"]]
    assert names == [
        "production heading",
        "production deploys",
        "production figures",
        "production live heading",
        "production tile 1 table",
        "production tile 2 table",
        "production tile 3 table",
        "production tile 4 table",
        "production caption",
    ]


def test_snapshot_figures_are_datatables_with_no_time_range_and_a_link_to_their_source():
    book = built()
    snapshot_items = [
        entry
        for entry in book["items"]
        if entry["type"] == 3 and "timeContextFromParameter" not in entry["content"]
    ]
    assert len(snapshot_items) == 9  # 3 before, 2 in production, 4 in the SDLC tab
    for entry in snapshot_items:
        content = entry["content"]
        assert content["query"].startswith("datatable("), entry["name"]
        assert (content["version"], content["queryType"], content["resourceType"]) == (
            "KqlItem/1.0",
            0,
            "microsoft.insights/components",
        )
        assert content["visualization"] in {"table", "timechart", "barchart"}
        assert content["noDataMessage"] and len(content["title"]) > 30
        if "source: string" in content["query"]:
            assert content["gridSettings"]["formatters"] == [
                {
                    "columnMatch": "source",
                    "formatter": 7,
                    "formatOptions": {"linkTarget": "Url", "linkLabel": "open"},
                }
            ], entry["name"]

    chart = named(book, "before ci run times")["content"]
    assert chart["visualization"] == "timechart"
    assert chart["query"].startswith(
        "datatable(started: datetime, job_seconds: real, test_seconds: real) [\n"
        "    datetime(2026-10-13T15:27:07Z), 15.0, 7.0,\n"
        "    datetime(2026-10-13T16:02:41Z), 14.5, 6.25\n]"
    )
    assert "seconds per ci run" in chart["title"].lower()
    assert "job" in chart["title"] and "test step" in chart["title"]

    decisions = named(book, "sdlc decisions chart")["content"]
    assert decisions["visualization"] == "barchart"
    assert decisions["query"] == named(book, "sdlc decisions table")["content"]["query"]
    assert decisions["query"] == (
        'datatable(who: string, decisions: long) [\n    "agent", 3,\n    "owner", 1\n]'
    )


def test_an_empty_list_gives_an_empty_datatable_with_the_schema_columns():
    query = named(built(), "production figures")["content"]["query"]
    assert query == "datatable(measure: string, value: string, detail: string, source: string) []"


@pytest.mark.parametrize(
    "value",
    ['say "yes"', "back\\slash", 'both \\" at once', "\\\\", '""', "a pound sign: £", ""],
)
def test_a_kql_string_literal_reads_back_as_the_same_text(value):
    assert kql_literals(builder.kql_string(value)) == [value]


def test_snapshot_text_reads_back_unchanged_from_its_datatable():
    snapshot = fixture_snapshot()
    query = named(built(snapshot), "before figures")["content"]["query"]
    rows = snapshot["before_production"]["figures"]
    assert kql_literals(query) == [
        row[column] for row in rows for column in ("measure", "value", "detail", "source")
    ]


@pytest.mark.parametrize("character", ["\n", "\r", "\t", "\x00", "\x1b", "\x7f", "\x85"])
def test_a_control_character_in_the_snapshot_is_refused(character):
    snapshot = fixture_snapshot()
    snapshot["ai_native_sdlc"]["stages"][0]["gate"] = f"the owner{character}commits it"
    with pytest.raises(ValueError, match="control character"):
        built(snapshot)
    with pytest.raises(ValueError, match="control character"):
        builder.kql_string(character)


def _set(path: tuple, value):
    def change(snapshot: dict) -> None:
        target = snapshot
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return change


def _drop(path: tuple):
    def change(snapshot: dict) -> None:
        target = snapshot
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return change


FIGURE = ("before_production", "figures", 0)
RUN = ("before_production", "ci_runs", 0)


@pytest.mark.parametrize(
    "change",
    [
        _set((*FIGURE, "source"), "https://example.com/answer-scorer"),
        _set((*FIGURE, "source"), f"{REPO}-fork/blob/main/README.md"),
        _set((*FIGURE, "source"), "http://github.com/ranaidrees/answer-scorer"),
        _set(("ai_native_sdlc", "stages", 0, "source"), "https://learn.microsoft.com/azure"),
        _drop((*FIGURE, "detail")),
        _set((*FIGURE, "owner"), "an extra key"),
        _set((*FIGURE, "value"), 12),
        _set((*FIGURE, "detail"), "see {TimeRange} here"),
        _set((*RUN, "started"), "2026-10-13 15:27:07"),
        _set((*RUN, "started"), "2026-10-13T15:27:07+01:00"),
        _set((*RUN, "job_seconds"), True),
        _set((*RUN, "job_seconds"), "15"),
        _set((*RUN, "job_seconds"), float("nan")),
        _set((*RUN, "test_seconds"), -1),
        _set(("ai_native_sdlc", "decisions_by_who", 0, "decisions"), "3"),
        _set(("ai_native_sdlc", "decisions_by_who", 0, "decisions"), 2.5),
        _set(("in_production", "deploys", 0, "route"), None),
        _drop(("in_production", "deploys")),
        _drop(("ai_native_sdlc",)),
        _set(("generated_at",), "14 October 2026"),
    ],
)
def test_a_snapshot_outside_the_schema_is_refused(change):
    snapshot = fixture_snapshot()
    change(snapshot)
    with pytest.raises(ValueError):
        built(snapshot)


def test_a_list_row_may_carry_an_extra_text_column_and_source_stays_last():
    snapshot = fixture_snapshot()
    stage = snapshot["ai_native_sdlc"]["stages"][0]
    snapshot["ai_native_sdlc"]["stages"][0] = {
        "stage": stage["stage"],
        "artifact": stage["artifact"],
        "source": stage["source"],
        "gate": stage["gate"],
        "who_decides": "owner",
    }
    query = named(built(snapshot), "sdlc stages")["content"]["query"]
    assert query.startswith(
        "datatable(stage: string, artifact: string, gate: string, who_decides: string, "
        "source: string) [\n"
    )


def test_the_build_is_deterministic_and_the_file_text_has_a_fixed_layout():
    first, second = builder.render(built()), builder.render(built())
    assert first == second
    assert first.endswith("}\n") and not first.endswith("\n\n")
    assert first.startswith('{\n  "version": "Notebook/1.0",\n  "items": [\n')
    assert json.loads(first) == built()


def test_a_workbook_over_the_bicep_file_limit_is_refused():
    snapshot = fixture_snapshot()
    snapshot["before_production"]["ci_runs"] = [
        {"started": "2026-10-13T15:27:07Z", "job_seconds": 15, "test_seconds": 7}
    ] * 4000
    with pytest.raises(ValueError, match="loadTextContent"):
        builder.render(built(snapshot))


def test_write_workbook_writes_the_rendered_build_with_unix_line_endings(tmp_path):
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(json.dumps(fixture_snapshot()), encoding="utf-8")
    out = tmp_path / "workbook.json"
    text = builder.write_workbook(snapshot_file, QUERIES_FILE, out)
    assert out.read_bytes() == text.encode("utf-8")
    assert b"\r\n" not in out.read_bytes()
    assert text == builder.render(built())


# --- The committed files --------------------------------------------------------------------


def test_the_committed_workbook_is_the_build_of_the_committed_snapshot():
    if not SNAPSHOT_FILE.exists():
        pytest.skip("dashboards/sdlc_snapshot.json is not committed yet")
    snapshot = json.loads(read(SNAPSHOT_FILE))
    assert read(WORKBOOK_FILE) == builder.render(builder.build(snapshot, queries())), (
        "run: uv run python scripts/build_sdlc_workbook.py"
    )


def test_the_committed_workbook_holds_no_resource_id_and_links_only_here():
    text = read(WORKBOOK_FILE)
    book = json.loads(text)
    assert "fallbackResourceIds" not in book, "the resource is bound in Bicep at deploy time"
    assert "/subscriptions/" not in text and "resourceGroups" not in text
    assert "crossComponentResources" not in text
    assert "InstrumentationKey" not in text and "IngestionEndpoint" not in text
    assert sorted(set(GUID.findall(text))) == list(PARAMETER_IDS)
    assert len(text) <= builder.MAX_WORKBOOK_CHARACTERS

    del book["$schema"]  # the workbook format's own schema address, not a link on the page
    links = [link for value in strings(book) for link in LINK.findall(value)]
    assert links, "the workbook links to its sources"
    for link in links:
        assert ALLOWED_LINK.match(link), link


@pytest.mark.parametrize(
    "path", [BUILDER_FILE, WORKBOOK_FILE, BICEP_FILE, THIS_FILE], ids=lambda p: p.name
)
def test_no_new_file_holds_an_id_an_address_a_host_or_a_long_dash(path):
    text = read(path)
    assert not EMAIL.search(text), "no email address"
    assert [found for found in GUID.findall(text) if found not in PARAMETER_IDS] == []
    assert chr(0x2014) not in text and chr(0x2013) not in text, "no em or en dash"
    if path != THIS_FILE:  # this file names what it looks for
        assert "/subscriptions/" not in text
        assert "InstrumentationKey" not in text
        assert ".azurecontainerapps.io" not in text
        assert ".applicationinsights.azure.com" not in text


def bicep_resource(text: str, symbol: str) -> str:
    match = re.search(rf"^resource {symbol} .*?^}}$", text, re.DOTALL | re.MULTILINE)
    assert match, f"resource {symbol} not found"
    return match.group(0)


def test_the_bicep_file_creates_one_workbook_bound_to_application_insights_by_name():
    text = read(BICEP_FILE)
    assert "targetScope = 'resourceGroup'" in text
    created = re.findall(r"^resource (\w+) '([\w./]+)@[\w-]+' = \{$", text, re.MULTILINE)
    assert created == [("workbook", "Microsoft.Insights/workbooks")]
    referenced = re.findall(
        r"^resource (\w+) '([\w./]+)@[\w-]+' existing = \{$", text, re.MULTILINE
    )
    assert referenced == [("applicationInsights", "Microsoft.Insights/components")]
    assert re.search(r"^param applicationInsightsName string$", text, re.MULTILINE)
    assert "name: applicationInsightsName" in bicep_resource(text, "applicationInsights")
    assert "module " not in text and "main.bicep'" not in text
    assert "roleAssignments" not in text

    assert "union(json(loadTextContent('sdlc_workbook.json'))" in text
    assert "fallbackResourceIds" in text
    book = bicep_resource(text, "workbook")
    for line in (
        "name: guid(resourceGroup().id, 'answer-scorer-delivery-evidence')",
        "kind: 'shared'",
        "category: 'workbook'",
        "sourceId: applicationInsights.id",
        "serializedData: string(workbookContent)",
        "tags: tags",
    ):
        assert line in book, line
    assert "param workbookDisplayName string = 'Answer scorer: delivery evidence'" in text
    for tag in ("project: 'answer-scorer'", "env: 'demo'", "owner: ownerTag"):
        assert tag in text
    assert re.findall(r"^output (\w+) (\w+) = (.+)$", text, re.MULTILINE) == [
        ("workbookDisplayName", "string", "workbook.properties.displayName")
    ], "the display name only: no resource ID leaves the file"


def test_ci_builds_the_new_bicep_file():
    assert "az bicep build --file infra/sdlc_dashboard.bicep --stdout > /dev/null" in read(CI_FILE)


def test_the_no_pair_text_follows_the_gate_verdict_not_the_missing_value():
    # The gate leaves the value out both when there was nothing to compare (it passes) and
    # when an injected answer had no clean twin (it fails); the text must follow the verdict.
    query = named(built(), "scorecard checks")["content"]["query"]
    assert (
        'iff(tolower(tostring(ev["injection_mean_diff_passed"])) == "true", '
        '"no pair to compare (the gate passes it)", "no pair to compare (the gate fails it)")'
    ) in query
