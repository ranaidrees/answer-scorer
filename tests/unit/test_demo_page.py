"""The demo page (FR-9) and the issue form its "Report a problem" link opens."""

from __future__ import annotations

import base64
import hashlib
import json
import re

import yaml
from starlette.testclient import TestClient

from scorer.api import UI_PAGE, create_app
from tests.unit.samples import REPO_ROOT, good_client, make_settings

HTML = UI_PAGE.read_text(encoding="utf-8")
ISSUE_FORM = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "report-a-problem.yml"
REPORT_LINK = "https://github.com/ranaidrees/answer-scorer/issues/new?template=report-a-problem.yml"
# The three samples are these dev rows of the evaluation datasets.
SAMPLE_ROWS = {
    "strong": ("golden.jsonl", "g-tw-5-c"),
    "weak": ("golden.jsonl", "g-tw-1-a"),
    "injection": ("injection.jsonl", "i-1-twin"),
}


def dataset_row(file_name: str, row_id: str) -> dict:
    path = REPO_ROOT / "evals" / "datasets" / file_name
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return next(row for row in rows if row["id"] == row_id)


def get_page():
    app = create_app(make_settings(demo_token="unit-test-demo-token"), good_client())
    return TestClient(app).get("/")


def test_fr9_the_page_is_served_at_the_root_without_a_token():
    response = get_page()
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == HTML.replace("\r\n", "\n")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_fr9_the_page_shows_the_ai_use_disclosure():
    assert "AI-assisted, decision support only" in HTML
    assert "A trained person makes the decision" in HTML
    assert "synthetic data" in HTML


def test_fr9_the_page_links_to_the_report_a_problem_issue_form():
    assert f'href="{REPORT_LINK}"' in HTML
    assert "Report a problem" in HTML
    assert 'rel="noopener noreferrer"' in HTML
    assert "do not paste any answer text" in HTML


def test_fr9_the_issue_form_exists_and_tells_people_not_to_paste_candidate_text():
    form = yaml.safe_load(ISSUE_FORM.read_text(encoding="utf-8"))
    assert form["name"] == "Report a problem"
    text = ISSUE_FORM.read_text(encoding="utf-8")
    assert "Do not paste any answer text" in text
    assert "public" in text
    ids = [item.get("id") for item in form["body"] if "id" in item]
    assert "trace-id" in ids
    confirm = next(item for item in form["body"] if item["type"] == "checkboxes")
    assert confirm["attributes"]["options"][0]["required"] is True
    answer_fields = [item for item in form["body"] if item["type"] in ("input", "textarea")]
    assert all("answer" not in item["id"] for item in answer_fields), "no field asks for the answer"


def test_fr9_the_page_has_every_part_of_the_journey():
    for element_id in (
        "competency",
        "question",
        "answer",
        "token",
        "score",
        "result-score",
        "result-level",
        "result-rationale",
        "result-answer",
        "result-flags",
        "result-reasons",
        "result-trace",
        "result-notice",
        "report-link",
        "disclosure",
    ):
        assert f'id="{element_id}"' in HTML, element_id
    for sample in ("strong", "weak", "injection"):
        assert f'data-sample="{sample}"' in HTML
    assert "<mark" in HTML or 'createElement("mark")' in HTML


def test_fr9_the_competency_picker_lists_exactly_the_rubrics():
    options = re.findall(r'<option value="([^"]+)">', HTML)
    rubric_ids = sorted(path.stem for path in (REPO_ROOT / "rubrics").glob("*.yaml"))
    assert sorted(options) == rubric_ids


def test_fr9_the_samples_are_dev_rows_never_holdout_rows():
    for name, (file_name, row_id) in SAMPLE_ROWS.items():
        row = dataset_row(file_name, row_id)
        assert row["split"] == "dev", name
        assert json.dumps(row["answer"]) in HTML, f"the {name} sample is the dataset row, unchanged"
        assert json.dumps(row["question"]) in HTML
    holdout = [
        json.loads(line)
        for line in (REPO_ROOT / "evals" / "datasets" / "golden.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    for row in holdout:
        if row["split"] == "holdout":
            assert row["answer"][:60] not in HTML, row["id"]


def test_fr9_the_token_is_kept_in_session_storage_only():
    assert "sessionStorage.setItem" in HTML and "sessionStorage.getItem" in HTML
    assert "localStorage" not in HTML and "document.cookie" not in HTML
    assert '"X-Demo-Token"' in HTML
    assert 'type="password"' in HTML and 'autocomplete="off"' in HTML


def test_fr9_model_and_user_text_is_rendered_with_text_content_never_as_html():
    for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert unsafe not in HTML, unsafe
    assert "textContent" in HTML and "createTextNode" in HTML


def test_fr9_the_page_loads_nothing_from_anywhere_else():
    assert re.search(r"<script[^>]+src=", HTML) is None
    assert "<link" not in HTML and "@import" not in HTML and "url(" not in HTML
    assert "<img" not in HTML and "<iframe" not in HTML and "@font-face" not in HTML
    assert re.findall(r"https?://[^\s\"'<>]+", HTML) == [REPORT_LINK]
    assert 'fetch("/api/score"' in HTML, "the only request goes to this service"


def test_fr9_the_page_holds_no_identifier_shaped_strings():
    guid = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    assert re.search(guid, HTML) is None
    assert re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", HTML) is None
    assert re.search(r"\b[A-Za-z0-9+/_-]{40,}\b", HTML) is None, "nothing shaped like a key"
    lowered = HTML.lower()
    for word in (
        "instrumentationkey",
        "ingestionendpoint",
        "subscription",
        "tenant",
        "azure.com",
        "azurecontainerapps",
        "windows.net",
        "applicationinsights",
        "client_id",
        "resourcegroups",
    ):
        assert word not in lowered, word


def test_fr9_the_page_uses_decision_support_wording():
    text = re.sub(r"<script>.*?</script>|<style>.*?</style>", " ", HTML, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    script = re.search(r"<script>(.*?)</script>", HTML, flags=re.DOTALL).group(1)
    shown = text + " " + " ".join(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', script))
    banned = r"\b(pass|passed|passes|fail|failed|fails|reject|rejected|hire|hired|recommend|recommended)\b"
    assert re.findall(banned, shown, flags=re.IGNORECASE) == []


def test_the_content_security_policy_allows_only_the_page_s_own_inline_blocks():
    policy = get_page().headers["content-security-policy"]
    directives = dict(part.strip().split(" ", 1) for part in policy.split(";"))

    assert directives["default-src"] == "'none'"
    assert directives["connect-src"] == "'self'"
    assert directives["frame-ancestors"] == "'none'" and directives["base-uri"] == "'none'"
    assert "unsafe" not in policy

    served = HTML.replace("\r\n", "\n")
    for kind in ("script", "style"):
        blocks = re.findall(rf"<{kind}>(.*?)</{kind}>", served, flags=re.DOTALL)
        assert len(blocks) == 1
        digest = base64.b64encode(hashlib.sha256(blocks[0].encode("utf-8")).digest()).decode()
        assert directives[f"{kind}-src"] == f"'sha256-{digest}'"
    assert len(re.findall(r"<script\b", served)) == 1, "no script tag the policy does not cover"
    assert re.search(r"\son[a-z]+\s*=", served) is None, "no inline event handlers"
    assert 'style="' not in served, "no inline style attributes"
