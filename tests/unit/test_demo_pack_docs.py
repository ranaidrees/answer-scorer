"""The demo pack (plan S8): its links resolve and it keeps the public-repository rules.

Covers the README and the documents under `docs/` that the demo pack adds:

- every relative Markdown link, and every file path written as inline code, points at a
  file that exists in this checkout, and every `#anchor` matches a heading;
- links that leave the repository go to this repository's own pages on GitHub only;
- no long dashes, no email addresses, identifiers, endpoints or local folder paths;
- no decision word ("pass", "fail", "reject", "hire", "recommend") in the same sentence
  as "candidate" (fair-scoring rule 5; a proximity check, so it errs on the strict side);
- a figure that is not known yet is written as a `[[PENDING: what is missing]]` marker;
- the disclaimer and the "reliability is not validity" statement stay where results are.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

README = "README.md"
GOVERNANCE = "docs/governance.md"
EVAL_CARD = "docs/eval_card.md"
WALKTHROUGH = "docs/walkthrough.md"
SCREENSHOTS = "docs/screenshots/README.md"
DOCUMENTS = (README, GOVERNANCE, EVAL_CARD, WALKTHROUGH, SCREENSHOTS)

# The only place a link may leave the repository for: its own pages on GitHub.
REPOSITORY_URL = "https://github.com/ranaidrees/answer-scorer/"

# Paths the documents name on purpose although this checkout does not hold them.
NOT_IN_THIS_CHECKOUT = {
    "prompts/scorer/v0-weak.md",  # exists only on the weak-prompt branch (spec section 7)
    "src/scorer/echo.py",  # added by S4c (decision S4c-3), which is stacked under this slice later
}

LINK = re.compile(r"!?\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)\)")
CODE_SPAN = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.MULTILINE | re.DOTALL)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
PATH_IN_CODE = re.compile(r"^[\w.\-]+(/[\w.\-]+)+\.(md|py|ya?ml|json|jsonl|kql|bicep|html|toml)$")
PENDING = re.compile(r"\[\[PENDING: [^\[\]\n]{3,}\]\]")

LONG_DASHES = ("–", "—", "―")
DECISION_WORDS = re.compile(
    r"\b(pass(es|ed|ing)?|fail(s|ed|ing|ure|ures)?|reject(s|ed|ing|ion|ions)?"
    r"|hire[sd]?|recommend(s|ed|ing|ation|ations)?)\b",
    re.IGNORECASE,
)
CANDIDATE = re.compile(r"\bcandidates?\b", re.IGNORECASE)
SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+|\n|\|")

FORBIDDEN = {
    "an email address": re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"),
    "a GUID": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
    ),
    "a long hexadecimal value": re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE),
    "a connection string": re.compile(
        r"InstrumentationKey=|IngestionEndpoint=|AccountKey=|SharedAccessSignature=",
        re.IGNORECASE,
    ),
    "an Azure host name": re.compile(
        r"[\w-]+\.(azurecontainerapps\.io|openai\.azure\.com|cognitiveservices\.azure\.com"
        r"|services\.ai\.azure\.com|applicationinsights\.azure\.com|azurewebsites\.net)",
        re.IGNORECASE,
    ),
    "an Azure resource ID": re.compile(r"/subscriptions/[^<{\s]", re.IGNORECASE),
    "a local folder path": re.compile(r"\b[A-Za-z]:[\\/][\w.]|/(Users|home)/\w", re.IGNORECASE),
    "a token": re.compile(r"\b(gh[pousr]_\w{20,}|sk-[\w-]{20,}|eyJ[\w-]{20,})"),
}


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _prose(text: str) -> str:
    """The text without fenced code blocks, where a bracket is not a link."""
    return FENCE.sub("", text)


def _slug(heading: str) -> str:
    """The anchor GitHub gives a heading: lower case, punctuation dropped, spaces to hyphens."""
    heading = re.sub(r"[`*_]", "", heading).strip().lower()
    heading = re.sub(r"[^\w\- ]", "", heading)
    return heading.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    return {_slug(match) for match in HEADING.findall(_prose(path.read_text(encoding="utf-8")))}


def _links(name: str) -> list[str]:
    prose = CODE_SPAN.sub("", _prose(_read(name)))
    return [match.group("target") for match in LINK.finditer(prose)]


def _resolve(name: str, target: str) -> Path:
    return ((ROOT / name).parent / target).resolve()


@pytest.mark.parametrize("name", DOCUMENTS)
def test_the_document_exists_and_is_not_a_stub(name):
    assert (ROOT / name).is_file()
    assert len(_read(name).splitlines()) >= 10


@pytest.mark.parametrize("name", DOCUMENTS)
def test_every_relative_link_resolves_to_a_file_in_the_repository(name):
    broken = []
    for target in _links(name):
        if target.startswith(("http://", "https://")):
            continue
        path_part, _, anchor = target.partition("#")
        path = _resolve(name, path_part) if path_part else ROOT / name
        if ROOT.resolve() not in (path, *path.parents) or not path.exists():
            broken.append(target)
        elif anchor and path.suffix == ".md" and anchor not in _anchors(path):
            broken.append(target)
    assert not broken, f"{name}: links that do not resolve: {broken}"


@pytest.mark.parametrize("name", DOCUMENTS)
def test_links_that_leave_the_repository_go_to_its_own_github_pages_only(name):
    outside = [
        target
        for target in _links(name)
        if ":" in target.split("#")[0] and not target.startswith(REPOSITORY_URL)
    ]
    assert not outside, f"{name}: unexpected external links: {outside}"


@pytest.mark.parametrize("name", DOCUMENTS)
def test_every_file_path_written_as_code_exists(name):
    missing = []
    for span in CODE_SPAN.findall(_prose(_read(name))):
        if not PATH_IN_CODE.match(span) or span in NOT_IN_THIS_CHECKOUT:
            continue
        if not (ROOT / span).exists():
            missing.append(span)
    assert not missing, f"{name}: paths that do not exist: {missing}"


def test_the_link_check_can_fail():
    """Guards the checks above against a pattern that silently matches nothing."""
    assert LINK.search("see [the spec](../intent/spec.md#11-governance)").group("target") == (
        "../intent/spec.md#11-governance"
    )
    assert not _resolve(README, "docs/no-such-file.md").exists()
    assert PATH_IN_CODE.match("docs/no-such-file.md")
    assert _slug("AI use") == "ai-use"
    assert _slug("7. Repository history (7:00 to 8:00)") == "7-repository-history-700-to-800"


@pytest.mark.parametrize("name", DOCUMENTS)
def test_no_long_dashes(name):
    text = _read(name)
    found = [
        f"line {number}"
        for number, line in enumerate(text.splitlines(), start=1)
        if any(dash in line for dash in LONG_DASHES)
    ]
    assert not found, f"{name}: long dash on {found}"


@pytest.mark.parametrize("name", DOCUMENTS)
def test_no_decision_word_is_used_about_a_candidate(name):
    found = [
        sentence.strip()
        for sentence in SENTENCE_END.split(_read(name))
        if sentence and CANDIDATE.search(sentence) and DECISION_WORDS.search(sentence)
    ]
    assert not found, f"{name}: decision word beside 'candidate': {found}"


def test_the_decision_word_check_can_fail():
    assert DECISION_WORDS.search("The candidate failed.") and CANDIDATE.search("The candidate")
    assert DECISION_WORDS.search("never auto-reject")
    assert not DECISION_WORDS.search("not for use in real hiring decisions")
    assert not DECISION_WORDS.search("a passage about surpassing")


@pytest.mark.parametrize("name", DOCUMENTS)
@pytest.mark.parametrize("kind", sorted(FORBIDDEN))
def test_no_identifier_contact_detail_or_local_path(name, kind):
    match = FORBIDDEN[kind].search(_read(name))
    assert match is None, f"{name}: looks like {kind}"


def test_the_identifier_check_can_fail():
    samples = {
        "an email address": "someone@example.org",
        "a GUID": "00000000-0000-4000-8000-000000000000",
        "a long hexadecimal value": "0" * 40,
        "a connection string": "InstrumentationKey=x",
        "an Azure host name": "name.azurecontainerapps.io",
        "an Azure resource ID": "/subscriptions/abc",
        "a local folder path": "D:" + "\\" + "work",
        "a token": "ghp_" + "a" * 24,
    }
    assert set(samples) == set(FORBIDDEN)
    for kind, sample in samples.items():
        assert FORBIDDEN[kind].search(sample), kind
    assert not FORBIDDEN["an Azure resource ID"].search("/subscriptions/<id>")
    assert not FORBIDDEN["a local folder path"].search("http://localhost:8000 at 10:30")


@pytest.mark.parametrize("name", DOCUMENTS)
def test_every_double_bracket_is_a_well_formed_pending_marker(name):
    text = _read(name)
    assert text.count("[[") == len(PENDING.findall(text)), f"{name}: malformed pending marker"
    assert text.count("]]") == text.count("[[")


def test_the_readme_keeps_the_disclaimer_near_the_top():
    top = "\n".join(_read(README).splitlines()[:12])
    assert "Synthetic data only" in top
    assert "Not for use in real hiring decisions" in top
    assert "decision support" in top.lower()


@pytest.mark.parametrize("name", [README, EVAL_CARD, GOVERNANCE, WALKTHROUGH])
def test_results_are_never_shown_without_the_validity_statement(name):
    assert "reliability is not validity" in _read(name).lower()


@pytest.mark.parametrize("name", DOCUMENTS)
def test_no_document_claims_the_scoring_is_valid_or_accurate(name):
    claims = re.compile(
        r"\b(validated|proven accurate|is accurate|are accurate|is valid\b(?! JSON))",
        re.IGNORECASE,
    )
    negations = re.compile(r"\b(not|never|no|nor|neither|cannot|does not|do not)\b", re.IGNORECASE)
    found = [
        sentence.strip()
        for sentence in SENTENCE_END.split(_read(name))
        if claims.search(sentence) and not negations.search(sentence)
    ]
    assert not found, f"{name}: a validity claim without a negation: {found}"


def test_the_walkthrough_names_the_three_sample_buttons_of_the_demo_page():
    page = _read("src/scorer/ui/index.html")
    labels = re.findall(r'data-sample="\w+">([^<]+)</button>', page)
    assert len(labels) == 3
    walkthrough = _read(WALKTHROUGH)
    for label in labels:
        assert f'"{label}"' in walkthrough, label
    assert '"Score this answer"' in walkthrough


def test_the_readme_shows_the_four_defence_layers_of_the_spec():
    readme = _read(README)
    spec = _read("intent/spec.md")
    for layer in ("Input guards", "Output guards", "Offline evals", "Online evals"):
        row = next(line for line in spec.splitlines() if line.startswith(f"| {layer} |"))
        assert row in readme, layer


def test_the_readme_diagram_is_the_one_in_the_architecture_page():
    block = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
    assert block.search(_read(README)).group(1) == (
        block.search(_read("docs/architecture.md")).group(1)
    )


def test_the_readme_links_every_slice_pull_request_and_the_decisions_log():
    readme = _read(README)
    for number in range(2, 12):
        assert f"{REPOSITORY_URL}pull/{number})" in readme, number
    assert "(intent/decisions.md)" in readme


def test_the_screenshot_list_marks_a_missing_file_as_pending_live():
    rows = [
        line
        for line in _read(SCREENSHOTS).splitlines()
        if line.startswith("| `") and ".png`" in line
    ]
    assert len(rows) >= 7
    for row in rows:
        file_name = row.split("`")[1]
        if not (ROOT / "docs" / "screenshots" / file_name).exists():
            assert "pending live" in row.lower(), file_name
