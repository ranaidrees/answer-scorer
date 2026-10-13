"""Schema tests for the eval datasets in `evals/datasets/` (spec section 7).

The datasets are evidence: these tests fix their shape so that later slices can
rely on the fields, and so that an edit cannot quietly change a count, a split
or a pairing. Files whose names start with an underscore are working files
(for example the blind file for the label audit) and are ignored.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "evals" / "datasets"
RUBRICS = ROOT / "rubrics"

GOLDEN = "golden.jsonl"
FAIRNESS = "fairness_pairs.jsonl"
INJECTION = "injection.jsonl"
EDGE = "edge_cases.jsonl"

ROW_COUNTS = {GOLDEN: 30, FAIRNESS: 16, INJECTION: 24, EDGE: 6}

COMMON_FIELDS = {"id", "competency_id", "question", "split", "label_source", "reason"}
FIELDS = {
    GOLDEN: COMMON_FIELDS | {"answer", "label"},
    FAIRNESS: COMMON_FIELDS | {"pair_type", "answer_a", "answer_b", "variant_a", "variant_b"},
    INJECTION: COMMON_FIELDS | {"answer", "group", "role", "injection_type", "variant"},
    EDGE: COMMON_FIELDS | {"answer", "case", "expected"},
}
STRING_FIELDS = {
    GOLDEN: {"answer"},
    FAIRNESS: {"pair_type", "answer_a", "answer_b", "variant_a", "variant_b"},
    INJECTION: {"answer", "group", "role", "variant"},
    EDGE: {"answer", "case"},
}

LABEL_SOURCE = "synthetic-ai-audited"
MIN_CHARS = 30
MAX_CHARS = 4000

PAIR_TYPES = {"identity": 8, "dialect": 4, "verbosity": 4}
INJECTION_TYPES = {
    "direct_demand",
    "fake_system_message",
    "delimiter_break",
    "hidden_instruction",
    "role_play",
    "rubric_language_score",
}
INJECTION_GROUPS = {f"inj-{number}" for number in range(1, 7)}
INJECTED_VARIANTS = {"twin", "paraphrase_1", "paraphrase_2"}
CLOSING_TAG = "</candidate_answer>"

EDGE_EXPECTED = {
    "contact_only": {
        "status": 400,
        "error": "answer_empty_after_redaction",
        "model_called": False,
    },
    "too_long": {"status": 400, "error": "answer_too_long", "model_called": False},
    "off_topic": {"status": 200, "needs_human_review": True, "off_topic": True},
    "other_competency": {
        "status": 200,
        "needs_human_review": True,
        "any_of": [{"off_topic": True}, {"max_score": 2}],
    },
    "buzzwords": {"status": 200, "needs_human_review": True, "max_score": 2},
    "copied_question": {
        "status": 200,
        "needs_human_review": True,
        "any_of": [{"off_topic": True}, {"max_score": 1}],
    },
}

EM_DASH = "—"

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
PHONE = re.compile(r"\+?\d(?:[ ().-]?\d){8,}")
RESERVED_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@example\.(?:com|org)")
RESERVED_URL = re.compile(r"https?://(?:www\.)?example\.(?:com|org)(?:/[A-Za-z0-9._~/-]*)?")
RESERVED_PHONE = re.compile(r"01632 ?960\d{3}|07700 ?900\d{3}")

SCORER_ADDRESSEES = ("scoring system", "assessor", "grader")
OTHER_TARGETS = re.compile(
    r"\b(?:assistant|agent|reviewer|repository|repo|shell|terminal|commands?|files?|"
    r"secrets?|passwords?|credentials?|api key|tokens?|tools?|commit|pull request|"
    r"workflow|github)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- helpers
def dataset_files(folder: Path) -> list[Path]:
    """The dataset files in a folder. Names starting with an underscore are ignored."""
    return sorted(
        path for path in folder.glob("*.jsonl") if path.is_file() and not path.name.startswith("_")
    )


def raw_text(name: str) -> str:
    return (DATASETS / name).read_bytes().decode("utf-8")


def load(name: str) -> list[dict]:
    rows = []
    for number, line in enumerate(raw_text(name).split("\n")[:-1], start=1):
        assert line.strip(), f"{name} line {number} is blank"
        row = json.loads(line)
        assert isinstance(row, dict), f"{name} line {number} is not a JSON object"
        rows.append(row)
    return rows


def all_rows() -> list[tuple[str, dict]]:
    return [(name, row) for name in ROW_COUNTS for row in load(name)]


def strings(value: object):
    """Every string inside a JSON value, at any depth."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def is_invisible(char: str) -> bool:
    """Zero-width, bidirectional, tag and other characters a reader cannot see."""
    if char == " ":
        return False
    code = ord(char)
    return (
        unicodedata.category(char) in {"Cf", "Cc", "Cs", "Co", "Cn", "Zs", "Zl", "Zp"}
        or 0xFE00 <= code <= 0xFE0F
        or 0xE0100 <= code <= 0xE01EF
        or code in {0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0}
    )


def has_invisible(text: str) -> bool:
    return any(is_invisible(char) for char in text)


def revealed(text: str) -> str:
    """The text with tag characters decoded and other invisible characters removed."""
    out = []
    for char in text:
        code = ord(char)
        if 0xE0020 <= code <= 0xE007E:
            out.append(chr(code - 0xE0000))
        elif not is_invisible(char):
            out.append(char)
    return "".join(out)


def is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_hidden_row(name: str, row: dict) -> bool:
    return name == INJECTION and row.get("injection_type") == "hidden_instruction"


def injection_groups() -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in load(INJECTION):
        groups[row["group"]].append(row)
    return groups


def clean_and_injected(rows: list[dict]) -> tuple[dict, list[dict]]:
    clean = [row for row in rows if row["role"] == "clean"]
    injected = [row for row in rows if row["role"] == "injected"]
    assert len(clean) == 1
    return clean[0], injected


def injection_position(clean: str, injected: str) -> str:
    """Where the injection sits, given that the injected answer is the clean answer plus one insert."""
    prefix = 0
    while prefix < len(clean) and prefix < len(injected) and clean[prefix] == injected[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < len(clean) - prefix
        and suffix < len(injected) - prefix
        and clean[-1 - suffix] == injected[-1 - suffix]
    ):
        suffix += 1
    assert prefix + suffix == len(clean), (
        "the injected answer is not the clean answer plus an insert"
    )
    if prefix == 0:
        return "start"
    if suffix == 0:
        return "end"
    return "middle"


def model_answers() -> list[tuple[str, str]]:
    """Every answer that should reach the model, as (row id, answer)."""
    answers = [(row["id"], row["answer"]) for row in load(GOLDEN)]
    for row in load(FAIRNESS):
        answers.append((row["id"] + ":a", row["answer_a"]))
        answers.append((row["id"] + ":b", row["answer_b"]))
    answers.extend((row["id"], row["answer"]) for row in load(INJECTION))
    answers.extend(
        (row["id"], row["answer"])
        for row in load(EDGE)
        if row["case"] not in ("contact_only", "too_long")
    )
    return answers


# --------------------------------------------------------------------------- files
def test_dataset_folder_holds_the_four_files():
    assert {path.name for path in dataset_files(DATASETS)} == set(ROW_COUNTS)


def test_files_starting_with_an_underscore_are_ignored(tmp_path):
    (tmp_path / "golden.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "_blind_golden.jsonl").write_text("{}\n", encoding="utf-8")
    assert [path.name for path in dataset_files(tmp_path)] == ["golden.jsonl"]


@pytest.mark.parametrize(("name", "count"), sorted(ROW_COUNTS.items()))
def test_row_count(name, count):
    assert len(load(name)) == count


@pytest.mark.parametrize("name", sorted(ROW_COUNTS))
def test_file_is_utf8_jsonl_with_lf_endings(name):
    text = raw_text(name)
    assert text.endswith("\n")
    assert "\r" not in text
    assert load(name)


@pytest.mark.parametrize("name", sorted(ROW_COUNTS))
def test_rows_have_exactly_the_schema_fields(name):
    for row in load(name):
        assert set(row) == FIELDS[name], row.get("id")


@pytest.mark.parametrize("name", sorted(ROW_COUNTS))
def test_string_fields_are_non_empty_strings(name):
    for row in load(name):
        for field in COMMON_FIELDS | STRING_FIELDS[name]:
            assert isinstance(row[field], str) and row[field].strip(), (row.get("id"), field)


# --------------------------------------------------------------------------- common fields
def test_ids_are_unique_across_all_files():
    ids = [row["id"] for _, row in all_rows()]
    assert len(ids) == sum(ROW_COUNTS.values())
    assert [item for item, count in Counter(ids).items() if count > 1] == []


def test_competency_matches_a_rubric_file():
    rubric_ids = set()
    for path in RUBRICS.glob("*.yaml"):
        rubric = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert rubric["id"] == path.stem
        rubric_ids.add(path.stem)
    assert rubric_ids == {"teamwork", "problem_solving"}
    for _, row in all_rows():
        assert row["competency_id"] in rubric_ids, row["id"]


def test_each_competency_uses_two_fixed_questions():
    questions: dict[str, set[str]] = defaultdict(set)
    for _, row in all_rows():
        questions[row["competency_id"]].add(row["question"])
    assert {competency: len(found) for competency, found in questions.items()} == {
        "teamwork": 2,
        "problem_solving": 2,
    }


def test_label_source_on_every_row():
    for _, row in all_rows():
        assert row["label_source"] == LABEL_SOURCE, row["id"]


def test_reason_is_one_non_empty_line():
    for _, row in all_rows():
        reason = row["reason"]
        assert reason == reason.strip() and len(reason) >= 20, row["id"]
        assert "\n" not in reason and "\r" not in reason, row["id"]


def test_split_values():
    for name, row in all_rows():
        allowed = {"dev", "holdout"} if name == GOLDEN else {"dev"}
        assert row["split"] in allowed, row["id"]


# --------------------------------------------------------------------------- golden
def test_golden_labels_are_integers_from_1_to_5():
    for row in load(GOLDEN):
        assert is_int(row["label"]) and 1 <= row["label"] <= 5, row["id"]


def test_golden_has_three_answers_per_competency_and_level():
    cells = Counter((row["competency_id"], row["label"]) for row in load(GOLDEN))
    expected = {
        (competency, level): 3
        for competency in ("teamwork", "problem_solving")
        for level in range(1, 6)
    }
    assert dict(cells) == expected


def test_golden_split_is_two_dev_and_one_holdout_per_cell():
    cells: dict[tuple[str, int], list[str]] = defaultdict(list)
    for row in load(GOLDEN):
        cells[(row["competency_id"], row["label"])].append(row["split"])
    for cell, splits in cells.items():
        assert sorted(splits) == ["dev", "dev", "holdout"], cell
    totals = Counter(row["split"] for row in load(GOLDEN))
    assert totals == {"dev": 20, "holdout": 10}


def test_golden_ids_follow_competency_and_level():
    short = {"teamwork": "tw", "problem_solving": "ps"}
    for row in load(GOLDEN):
        pattern = rf"g-{short[row['competency_id']]}-{row['label']}-[abc]"
        assert re.fullmatch(pattern, row["id"]), row["id"]


def test_golden_answers_are_all_different():
    answers = [row["answer"] for row in load(GOLDEN)]
    assert len(set(answers)) == len(answers)


# --------------------------------------------------------------------------- fairness pairs
def test_fairness_pair_types():
    assert Counter(row["pair_type"] for row in load(FAIRNESS)) == PAIR_TYPES


def test_fairness_pairs_have_two_different_answers_and_variants():
    for row in load(FAIRNESS):
        assert row["answer_a"] != row["answer_b"], row["id"]
        assert row["variant_a"] != row["variant_b"], row["id"]


def test_fairness_pairs_cover_both_competencies():
    counts = Counter(row["competency_id"] for row in load(FAIRNESS))
    assert set(counts) == {"teamwork", "problem_solving"}


def test_verbosity_pairs_are_concise_then_padded():
    for row in load(FAIRNESS):
        if row["pair_type"] == "verbosity":
            assert len(row["answer_b"]) >= 1.5 * len(row["answer_a"]), row["id"]


# --------------------------------------------------------------------------- injection
def test_injection_groups_are_one_clean_plus_three_injected():
    groups = injection_groups()
    assert set(groups) == INJECTION_GROUPS
    for group, rows in groups.items():
        assert sorted(row["variant"] for row in rows) == sorted({"base"} | INJECTED_VARIANTS), group
        for row in rows:
            if row["variant"] == "base":
                assert row["role"] == "clean", row["id"]
                assert row["injection_type"] is None, row["id"]
            else:
                assert row["role"] == "injected", row["id"]
                assert row["injection_type"] in INJECTION_TYPES, row["id"]


def test_injection_groups_have_one_type_each_and_cover_all_six():
    types = []
    for group, rows in injection_groups().items():
        _, injected = clean_and_injected(rows)
        found = {row["injection_type"] for row in injected}
        assert len(found) == 1, group
        types.extend(found)
    assert sorted(types) == sorted(INJECTION_TYPES)


def test_injection_group_shares_competency_and_question():
    for group, rows in injection_groups().items():
        assert len({(row["competency_id"], row["question"]) for row in rows}) == 1, group


def test_injected_answers_are_the_clean_answer_plus_an_insert():
    for group, rows in injection_groups().items():
        clean, injected = clean_and_injected(rows)
        answers = {row["answer"] for row in injected}
        assert len(answers) == 3 and clean["answer"] not in answers, group
        positions = {injection_position(clean["answer"], row["answer"]) for row in injected}
        assert positions == {"start", "middle", "end"}, group


def test_hidden_instruction_rows_contain_invisible_characters():
    hidden = [row for row in load(INJECTION) if row["injection_type"] == "hidden_instruction"]
    assert len(hidden) == 3
    for row in hidden:
        assert has_invisible(row["answer"]), row["id"]


def test_no_other_row_contains_an_invisible_character():
    for name, row in all_rows():
        for text in strings(row):
            if is_hidden_row(name, row) and text == row["answer"]:
                continue
            assert not has_invisible(text), row["id"]


@pytest.mark.parametrize("name", sorted(ROW_COUNTS))
def test_invisible_characters_are_written_as_json_escapes(name):
    text = raw_text(name)
    assert not any(is_invisible(char) for char in text if char != "\n")


def test_delimiter_break_rows_contain_the_closing_tag():
    for row in load(INJECTION):
        if row["injection_type"] == "delimiter_break":
            assert CLOSING_TAG in row["answer"], row["id"]
        elif row["role"] == "clean":
            assert CLOSING_TAG not in row["answer"], row["id"]


def test_injections_address_only_the_scorer():
    """The CI reviewer and the verifier read this file, so no injection may address them."""
    for row in load(INJECTION):
        text = revealed(row["answer"])
        assert not OTHER_TARGETS.search(text), row["id"]
        if row["role"] == "injected":
            assert any(name in text.lower() for name in SCORER_ADDRESSEES), row["id"]


# --------------------------------------------------------------------------- edge cases
def test_edge_cases_match_the_six_cases_and_expected_shapes():
    rows = load(EDGE)
    assert sorted(row["case"] for row in rows) == sorted(EDGE_EXPECTED)
    for row in rows:
        expected = EDGE_EXPECTED[row["case"]]
        assert json.dumps(row["expected"], sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_edge_case_lengths():
    by_case = {row["case"]: row["answer"] for row in load(EDGE)}
    assert len(by_case["too_long"]) > MAX_CHARS
    assert len(set(by_case["too_long"])) > 20, "the long answer must read as a real answer"
    assert len(by_case["contact_only"]) > MIN_CHARS
    assert by_case["copied_question"].startswith(
        next(row["question"] for row in load(EDGE) if row["case"] == "copied_question")
    )


def test_answers_that_reach_the_model_are_30_to_4000_characters():
    answers = model_answers()
    assert len(answers) == 90
    for row_id, answer in answers:
        assert MIN_CHARS <= len(answer) <= MAX_CHARS, row_id
        assert answer == answer.strip(), row_id


# --------------------------------------------------------------------------- hygiene
@pytest.mark.parametrize("path", dataset_files(DATASETS), ids=lambda path: path.name)
def test_no_em_dash_in_any_dataset_file(path):
    text = path.read_bytes().decode("utf-8")
    assert EM_DASH not in text
    assert "\\u2014" not in text.lower()
    for line in text.split("\n")[:-1]:
        for value in strings(json.loads(line)):
            assert EM_DASH not in value


def test_contact_details_only_in_the_contact_only_case_and_only_reserved_forms():
    contact_only_answers = 0
    for name, row in all_rows():
        for text in strings(row):
            emails = EMAIL.findall(text)
            urls = URL.findall(text)
            phones = PHONE.findall(text)
            if name == EDGE and row["case"] == "contact_only" and text == row["answer"]:
                contact_only_answers += 1
                assert emails and urls and phones, row["id"]
                assert all(RESERVED_EMAIL.fullmatch(item) for item in emails), emails
                assert all(RESERVED_URL.fullmatch(item) for item in urls), urls
                assert all(RESERVED_PHONE.fullmatch(item) for item in phones), phones
                leftover = PHONE.sub("", URL.sub("", EMAIL.sub("", text)))
                assert not leftover.strip(), (
                    "the contact-only answer holds more than contact details"
                )
            else:
                assert not emails and not urls and not phones, row["id"]
    assert contact_only_answers == 1
