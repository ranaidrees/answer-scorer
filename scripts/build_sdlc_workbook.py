"""Build the delivery evidence workbook from the snapshot and four live tile queries.

    uv run python scripts/build_sdlc_workbook.py

Reads `dashboards/sdlc_snapshot.json`, which `scripts/sdlc_snapshot.py` makes, and four
named queries of `dashboards/queries.kql`, and writes `infra/sdlc_workbook.json`, which
`infra/sdlc_dashboard.bicep` deploys (spec section 2 in `intent/s9-delivery-evidence/`).
Standard library only. The same snapshot and queries give the same file, byte for byte.

The workbook has three tabs: before production, in production and the AI-native SDLC.
GitHub and repository figures become KQL `datatable` queries, so the workbook calls no
outside service when it is viewed and holds no token (decision S9-1). The live tiles are
tiles 1 to 4 of the operational dashboard, word for word, under one time-range parameter.

Every string from the snapshot is written as a KQL string literal with its backslashes and
double quotes escaped. A control character is refused, not escaped, and so is a string
that names one of the workbook's parameters in braces, which the workbook would replace.
Every `source` must be a page of this repository. The file holds no resource ID: Bicep
adds the Application Insights resource when the owner deploys it.
"""

from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_FILE = ROOT / "dashboards" / "sdlc_snapshot.json"
QUERIES_FILE = ROOT / "dashboards" / "queries.kql"
WORKBOOK_FILE = ROOT / "infra" / "sdlc_workbook.json"

REPOSITORY_URL = "https://github.com/ranaidrees/answer-scorer"
OPERATIONAL_WORKBOOK = "Answer scorer dashboard"
SCHEMA_URL = (
    "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json"
)
RESOURCE_TYPE = "microsoft.insights/components"

# Bicep's loadTextContent reads a file of at most this many characters:
# https://learn.microsoft.com/azure/azure-resource-manager/bicep/bicep-functions-files#loadtextcontent
MAX_WORKBOOK_CHARACTERS = 131_072

# A workbook parameter needs an id. These are made up and GUID-shaped, like the one in
# infra/workbook.json, and they are the only GUID-shaped values in the file.
TIME_RANGE_ID = "a0000000-0000-4000-8000-000000000001"
SELECTED_TAB_ID = "a0000000-0000-4000-8000-000000000002"
PARAMETER_IDS = (TIME_RANGE_ID, SELECTED_TAB_ID)
TIME_RANGE_CHOICES_MS = (
    1_800_000,
    3_600_000,
    14_400_000,
    43_200_000,
    86_400_000,
    172_800_000,
    604_800_000,
    2_592_000_000,
)
DEFAULT_TIME_RANGE_MS = 2_592_000_000  # 30 days

TAB_PARAMETER = "selectedTab"
TABS = (
    ("before", "Before production"),
    ("production", "In production"),
    ("sdlc", "AI-native SDLC"),
)

# Tiles 1 to 4 of the operational dashboard, with its titles and messages.
LIVE_TILES = (
    {
        "name": "production tile 1 table",
        "query": "tile1_requests_latency",
        "size": 4,
        "title": "Requests, failure rate, availability, p50 and p95 latency (SLO: p95 at or under 6 s, 99% of non-4xx requests succeed)",
        "noDataMessage": "No requests to POST /api/score in this time range.",
    },
    {
        "name": "production tile 2 table",
        "query": "tile2_review_rate_by_reason",
        "size": 3,
        "title": "Reviews by reason over the whole time range, with the control-triggered rate against the 25% band",
        "noDataMessage": "No scored requests in this time range.",
    },
    {
        "name": "production tile 3 table",
        "query": "tile3_tokens_cost",
        "size": 4,
        "title": "Tokens and estimated cost per score in GBP (an estimate from published prices, not the invoice)",
        "noDataMessage": "No scored requests in this time range.",
    },
    {
        "name": "production tile 4 table",
        "query": "tile4_eval_runs",
        "size": 3,
        "title": "Eval runs: quadratic weighted kappa, agreement and gate result, by pull request, nightly or manual run",
        "noDataMessage": "No eval run was recorded in this time range. Widen the time range: runs happen on pull requests and nightly.",
    },
)
LIVE_QUERIES = tuple(tile["query"] for tile in LIVE_TILES)

# The columns of each list in the snapshot (spec section 3) and their KQL types. A
# `figures` row has exactly these keys; a row of another list may carry more, all text.
TABLE_COLUMNS: dict[str, dict[str, str]] = {
    "figures": {"measure": "string", "value": "string", "detail": "string", "source": "string"},
    "gates": {"gate": "string", "status": "string", "source": "string"},
    "deploys": {
        "started": "string",
        "route": "string",
        "commit": "string",
        "approved_by_owner": "string",
        "provenance_verified": "string",
        "smoke_test": "string",
        "result": "string",
        "source": "string",
    },
    "stages": {"stage": "string", "artifact": "string", "gate": "string", "source": "string"},
    "decisions_by_who": {"who": "string", "decisions": "long"},
}
CI_RUN_COLUMNS = {"started": "datetime", "job_seconds": "real", "test_seconds": "real"}

SOURCE_LINK = {
    "formatters": [
        {
            "columnMatch": "source",
            "formatter": 7,
            "formatOptions": {"linkTarget": "Url", "linkLabel": "open"},
        }
    ]
}
NO_ROWS = "No rows in this snapshot."
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
UTC_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
# Any {Name...} would be read by the workbook as a parameter reference, so none is let in.
PARAMETER_REFERENCE = re.compile(r"\{\s*[A-Za-z_]\w*")


# --- KQL literals ---------------------------------------------------------------------------


def kql_string(value: object) -> str:
    """A KQL string literal holding exactly `value`."""
    if not isinstance(value, str):
        raise ValueError(f"expected text, got {type(value).__name__}")
    for character in value:
        if unicodedata.category(character) == "Cc":
            raise ValueError(f"control character U+{ord(character):04X} in a snapshot string")
    if PARAMETER_REFERENCE.search(value):
        raise ValueError("a snapshot string names a workbook parameter in braces")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def utc_time(value: object) -> datetime:
    """A time written as UTC ISO 8601 with a Z, to the second."""
    if not isinstance(value, str) or not UTC_TIME.fullmatch(value):
        raise ValueError("expected a UTC time written like 2026-10-14T15:30:00Z")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def kql_datetime(value: object) -> str:
    utc_time(value)
    return f"datetime({value})"


def kql_real(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"expected a number, got {type(value).__name__}")
    if not math.isfinite(value) or value < 0:
        raise ValueError("expected a finite number, zero or more")
    return repr(float(value))


def kql_long(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"expected a whole number, got {type(value).__name__}")
    if value < 0:
        raise ValueError("expected a whole number, zero or more")
    return str(value)


LITERALS: dict[str, Callable[[object], str]] = {
    "string": kql_string,
    "datetime": kql_datetime,
    "real": kql_real,
    "long": kql_long,
}


def datatable(columns: dict[str, str], rows: list[list[str]]) -> str:
    """A `datatable` query in the layout of the one in dashboards/queries.kql."""
    schema = ", ".join(f"{name}: {kind}" for name, kind in columns.items())
    if not rows:
        return f"datatable({schema}) []"
    body = ",\n".join("    " + ", ".join(row) for row in rows)
    return f"datatable({schema}) [\n{body}\n]"


# --- Reading the snapshot -------------------------------------------------------------------


def section(snapshot: dict, name: str) -> dict:
    value = snapshot.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"snapshot: section {name} is missing or is not an object")
    return value


def rows_of(part: dict, key: str, where: str) -> list[dict]:
    rows = part.get(key)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"snapshot: {where}.{key} is missing or is not a list of objects")
    return rows


def table_columns(table: str, rows: list[dict], where: str) -> dict[str, str]:
    """The columns of one list: the row's own key order, with `source` last."""
    declared = TABLE_COLUMNS[table]
    if not rows:
        return dict(declared)
    keys = list(rows[0])
    if table == "figures" and set(keys) != set(declared):
        raise ValueError(f"snapshot: every {where} row has exactly the keys {sorted(declared)}")
    missing = [name for name in declared if name not in keys]
    if missing:
        raise ValueError(f"snapshot: {where} rows lack {missing}")
    for name in keys:
        if not IDENTIFIER.fullmatch(name):
            raise ValueError(f"snapshot: {where} has a key that is not a plain column name")
    ordered = [name for name in keys if name != "source"]
    if "source" in keys:
        ordered.append("source")
    return {name: declared.get(name, "string") for name in ordered}


def check_source(value: str) -> None:
    if not (value == REPOSITORY_URL or value.startswith(REPOSITORY_URL + "/")):
        raise ValueError(f"every source must be a page of {REPOSITORY_URL}")


def literal_rows(columns: dict[str, str], rows: list[dict], where: str) -> list[list[str]]:
    expected = set(columns)
    result = []
    for number, row in enumerate(rows, start=1):
        if set(row) != expected:
            raise ValueError(f"snapshot: {where} row {number} has different keys from row 1")
        literals = []
        for name, kind in columns.items():
            try:
                literals.append(LITERALS[kind](row[name]))
                if name == "source":
                    check_source(row[name])
            except ValueError as error:
                raise ValueError(f"snapshot: {where} row {number}, {name}: {error}") from error
        result.append(literals)
    return result


def table_query(table: str, rows: list[dict], where: str) -> tuple[str, bool]:
    """The `datatable` query of one list, and whether it has a `source` column."""
    columns = table_columns(table, rows, where)
    return datatable(columns, literal_rows(columns, rows, where)), "source" in columns


def display_time(moment: datetime) -> str:
    """14 October 2026, 15:30 UTC: month names fixed here, not taken from the locale."""
    return f"{moment.day} {MONTHS[moment.month - 1]} {moment.year}, {moment:%H:%M} UTC"


# --- Workbook items -------------------------------------------------------------------------


def item(item_type: int, content: dict, name: str, tab: str | None = None) -> dict:
    result: dict = {"type": item_type, "content": content}
    if tab is not None:
        result["conditionalVisibility"] = {
            "parameterName": TAB_PARAMETER,
            "comparison": "isEqualTo",
            "value": tab,
        }
    result["name"] = name
    return result


def text_item(name: str, markdown: str, tab: str | None = None, style: str | None = None) -> dict:
    content = {"json": markdown}
    if style is not None:
        content["style"] = style
    return item(1, content, name, tab)


def query_content(query: str, size: int, title: str, no_data: str) -> dict:
    return {
        "version": "KqlItem/1.0",
        "query": query,
        "size": size,
        "title": title,
        "noDataMessage": no_data,
    }


def snapshot_table(name: str, tab: str, table: str, rows: list[dict], where: str, title: str):
    query, has_source = table_query(table, rows, where)
    content = query_content(query, 3, title, NO_ROWS)
    content.update(queryType=0, resourceType=RESOURCE_TYPE, visualization="table")
    if has_source:
        content["gridSettings"] = SOURCE_LINK
    return item(3, content, name, tab)


def ci_runs_chart(rows: list[dict], tab: str) -> dict:
    where = "before_production.ci_runs"
    for number, row in enumerate(rows, start=1):
        if set(row) != set(CI_RUN_COLUMNS):
            raise ValueError(f"snapshot: {where} row {number} needs exactly {list(CI_RUN_COLUMNS)}")
    query = datatable(CI_RUN_COLUMNS, literal_rows(CI_RUN_COLUMNS, rows, where))
    content = query_content(
        query + "\n| order by started asc",
        0,
        "Seconds per ci run: the whole job and the test step (snapshot)",
        NO_ROWS,
    )
    content.update(
        queryType=0,
        resourceType=RESOURCE_TYPE,
        visualization="timechart",
        chartSettings={"showLegend": True, "showDataPoints": True, "ySettings": {"min": 0}},
    )
    return item(3, content, "before ci run times", tab)


def decisions_chart(rows: list[dict], tab: str) -> dict:
    query, _ = table_query("decisions_by_who", rows, "ai_native_sdlc.decisions_by_who")
    content = query_content(
        query,
        0,
        "Decisions by who made them, as a bar chart (snapshot)",
        NO_ROWS,
    )
    content.update(queryType=0, resourceType=RESOURCE_TYPE, visualization="barchart")
    return item(3, content, "sdlc decisions chart", tab)


def live_tile(tile: dict, queries: dict[str, str], tab: str) -> dict:
    query = queries.get(tile["query"])
    if not isinstance(query, str) or not query:
        raise ValueError(f"dashboards/queries.kql has no query named {tile['query']}")
    content = query_content(query, tile["size"], tile["title"], tile["noDataMessage"])
    content.update(
        timeContextFromParameter="TimeRange",
        queryType=0,
        resourceType=RESOURCE_TYPE,
        visualization="table",
    )
    return item(3, content, tile["name"], tab)


def introduction(as_of: str) -> dict:
    return text_item(
        "introduction",
        "# Answer scorer: delivery evidence\n\n"
        "How the answer scorer was delivered: the gates every change passed before production, "
        "every deploy and the live service against its SLOs, and the stages of the AI-native "
        "SDLC with who did the work and who decided. Every row links to the page or file it "
        "came from, in the public repository.\n\n"
        f"**Snapshot of {as_of}.** The GitHub and repository figures are a snapshot made by "
        f"[`scripts/sdlc_snapshot.py`]({REPOSITORY_URL}/blob/main/scripts/sdlc_snapshot.py) and "
        f"kept in [`dashboards/sdlc_snapshot.json`]({REPOSITORY_URL}/blob/main/dashboards/sdlc_snapshot.json). "
        "It is refreshed by a pull request, never when the page is viewed, so this page calls "
        "no outside service and holds no token (decision S9-1 in "
        f"[`intent/decisions.md`]({REPOSITORY_URL}/blob/main/intent/decisions.md)). Only the "
        "tiles under a **Live** heading read Application Insights.\n\n"
        f"The live operational view is the workbook **{OPERATIONAL_WORKBOOK}**, in the same "
        "resource group.",
    )


def parameters() -> dict:
    return item(
        9,
        {
            "version": "KqlParameterItem/1.0",
            "parameters": [
                {
                    "id": TIME_RANGE_ID,
                    "version": "KqlParameterItem/1.0",
                    "name": "TimeRange",
                    "label": "Time range of the live tiles",
                    "type": 4,
                    "isRequired": True,
                    "typeSettings": {
                        "selectableValues": [
                            {"durationMs": duration} for duration in TIME_RANGE_CHOICES_MS
                        ],
                        "allowCustom": True,
                    },
                    "timeContext": {"durationMs": DEFAULT_TIME_RANGE_MS},
                    "value": {"durationMs": DEFAULT_TIME_RANGE_MS},
                },
                {
                    "id": SELECTED_TAB_ID,
                    "version": "KqlParameterItem/1.0",
                    "name": TAB_PARAMETER,
                    "type": 1,
                    "isHiddenWhenLocked": True,
                    "value": TABS[0][0],
                },
            ],
            "style": "pills",
            "queryType": 0,
            "resourceType": RESOURCE_TYPE,
        },
        "parameters",
    )


def tabs() -> dict:
    return item(
        11,
        {
            "version": "LinkItem/1.0",
            "style": "tabs",
            "links": [
                {
                    "cellValue": TAB_PARAMETER,
                    "linkTarget": "parameter",
                    "linkLabel": label,
                    "subTarget": value,
                    "style": "link",
                }
                for value, label in TABS
            ],
        },
        "tabs",
    )


def caption(tab: str, limit: str, as_of: str) -> dict:
    return text_item(
        f"{tab} caption",
        f"**What this tab does not prove.** {limit} The data is synthetic: the golden set, the "
        "eval cases and the demo traffic are all made up. Reliability is not validity: a gate "
        "that gives the same result every time does not show that the scores are right. Every "
        "code, eval and label review counted here was made by an AI agent, not a person; the "
        "deploy approvals are the owner's. Figures are a snapshot "
        f"dated {as_of} unless the tile or its heading says live.",
        tab,
        style="info",
    )


def before_production(part: dict, as_of: str) -> list[dict]:
    tab, where = "before", "before_production"
    return [
        text_item(
            "before heading",
            "## Before production\n\n"
            "The gates every change passed before it could reach production: the tests and the "
            "`ci` checks, the eval gate and its stability proof, and the supply-chain controls. "
            f"The chart shows how long each `ci` run took, the whole job and the test step. "
            f"Snapshot of {as_of}.",
            tab,
        ),
        snapshot_table(
            "before figures",
            tab,
            "figures",
            rows_of(part, "figures", where),
            f"{where}.figures",
            "Before production: figures from the snapshot, each with the page it came from",
        ),
        ci_runs_chart(rows_of(part, "ci_runs", where), tab),
        snapshot_table(
            "before gates",
            tab,
            "gates",
            rows_of(part, "gates", where),
            f"{where}.gates",
            "Gates and supply-chain controls, each with the page that shows it (snapshot)",
        ),
        caption(
            tab,
            "A passed gate shows that a change met its thresholds on the golden set, not that "
            "the scorer is fit for real use.",
            as_of,
        ),
    ]


def in_production(part: dict, queries: dict[str, str], as_of: str) -> list[dict]:
    tab, where = "production", "in_production"
    return [
        text_item(
            "production heading",
            "## In production\n\n"
            "Every run of the deploy workflow, oldest first: the ones that changed the app, "
            "with the owner's approval, the build provenance check and the smoke test, and the "
            "ones the owner rejected or that GitHub cancelled while they waited. Then a few "
            "figures on how the deploys went. "
            f"Snapshot of {as_of}. Below them, the live service against its SLOs.",
            tab,
        ),
        snapshot_table(
            "production deploys",
            tab,
            "deploys",
            rows_of(part, "deploys", where),
            f"{where}.deploys",
            "Every deploy run: owner approval, provenance check, smoke test and result (snapshot)",
        ),
        snapshot_table(
            "production figures",
            tab,
            "figures",
            rows_of(part, "figures", where),
            f"{where}.figures",
            "In production: figures from the snapshot, each with the page it came from",
        ),
        text_item(
            "production live heading",
            "### Live: the service against its SLOs\n\n"
            "These four tiles read Application Insights over the time range at the top of the "
            "page (30 days unless you change it). They are tiles 1 to 4 of the workbook "
            f"**{OPERATIONAL_WORKBOOK}**, with the same queries, kept in "
            f"[`dashboards/queries.kql`]({REPOSITORY_URL}/blob/main/dashboards/queries.kql); the "
            f"SLOs are described in [`docs/slo.md`]({REPOSITORY_URL}/blob/main/docs/slo.md). "
            "Metadata only: no candidate text is recorded, so none can be shown.",
            tab,
        ),
        *(live_tile(tile, queries, tab) for tile in LIVE_TILES),
        caption(
            tab,
            "A passed smoke test shows that the app answered its sample requests as expected, "
            "not that its scores are right, and the live tiles show demo traffic, not real use.",
            as_of,
        ),
    ]


def ai_native_sdlc(part: dict, as_of: str) -> list[dict]:
    tab, where = "sdlc", "ai_native_sdlc"
    decisions = rows_of(part, "decisions_by_who", where)
    return [
        text_item(
            "sdlc heading",
            "## AI-native SDLC\n\n"
            "Each stage commits an artifact that the next stage reads, and a gate decides "
            "whether the work moves on. The figures show where the agent did the work and where "
            "the owner decided, and the chart counts the decisions in "
            f"[`intent/decisions.md`]({REPOSITORY_URL}/blob/main/intent/decisions.md) by who made "
            f"them. Snapshot of {as_of}.",
            tab,
        ),
        snapshot_table(
            "sdlc stages",
            tab,
            "stages",
            rows_of(part, "stages", where),
            f"{where}.stages",
            "Stages: the artifact each one committed and the gate that decided (snapshot)",
        ),
        snapshot_table(
            "sdlc figures",
            tab,
            "figures",
            rows_of(part, "figures", where),
            f"{where}.figures",
            "AI-native SDLC: figures from the snapshot, each with the page it came from",
        ),
        snapshot_table(
            "sdlc decisions table",
            tab,
            "decisions_by_who",
            decisions,
            f"{where}.decisions_by_who",
            "Decisions recorded in intent/decisions.md, by who made them (snapshot)",
        ),
        decisions_chart(decisions, tab),
        caption(
            tab,
            "Counts of commits and decisions show who did the work and who decided, not how "
            "good the work was.",
            as_of,
        ),
    ]


# --- The workbook ---------------------------------------------------------------------------


def build(snapshot: dict, queries: dict) -> dict:
    """The workbook for one snapshot. `queries` maps a query name to its text."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot: expected a JSON object")
    try:
        generated = utc_time(snapshot.get("generated_at"))
    except ValueError as error:
        raise ValueError(f"snapshot: generated_at: {error}") from error
    as_of = display_time(generated)

    items = [
        introduction(as_of),
        parameters(),
        tabs(),
        *before_production(section(snapshot, "before_production"), as_of),
        *in_production(section(snapshot, "in_production"), queries, as_of),
        *ai_native_sdlc(section(snapshot, "ai_native_sdlc"), as_of),
    ]
    names = [entry["name"] for entry in items]
    if len(names) != len(set(names)):
        raise ValueError("two workbook items have the same name")
    return {
        "version": "Notebook/1.0",
        "items": items,
        "styleSettings": {},
        "$schema": SCHEMA_URL,
    }


def render(workbook: dict) -> str:
    """The file text: two-space indent, a newline at the end, within Bicep's limit."""
    text = json.dumps(workbook, indent=2, ensure_ascii=False) + "\n"
    if len(text) > MAX_WORKBOOK_CHARACTERS:
        raise ValueError(
            f"the workbook is {len(text)} characters, over the {MAX_WORKBOOK_CHARACTERS} "
            "that Bicep's loadTextContent reads"
        )
    return text


def parse_queries(text: str) -> dict[str, str]:
    """Each named query of dashboards/queries.kql: the lines after its `// name:` line
    that are not comments, as the unit tests read them."""
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        header = re.fullmatch(r"// name: ([a-z0-9_]+)", line)
        if header:
            current = blocks.setdefault(header.group(1), [])
        elif current is not None and not line.startswith("//"):
            current.append(line)
    return {name: "\n".join(lines).strip() for name, lines in blocks.items()}


def write_workbook(
    snapshot_file: Path = SNAPSHOT_FILE,
    queries_file: Path = QUERIES_FILE,
    workbook_file: Path = WORKBOOK_FILE,
) -> str:
    snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
    queries = parse_queries(queries_file.read_text(encoding="utf-8"))
    text = render(build(snapshot, queries))
    workbook_file.write_text(text, encoding="utf-8", newline="\n")
    return text


def main() -> int:
    if not SNAPSHOT_FILE.exists():
        print(
            "dashboards/sdlc_snapshot.json is missing: run scripts/sdlc_snapshot.py first",
            file=sys.stderr,
        )
        return 2
    try:
        text = write_workbook()
    except ValueError as error:
        print(f"not written: {error}", file=sys.stderr)
        return 1
    print(f"wrote infra/sdlc_workbook.json ({len(text)} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
