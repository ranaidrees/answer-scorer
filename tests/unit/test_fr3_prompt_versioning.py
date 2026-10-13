"""FR-3: prompt versioning. A prompt file never changes without a new version."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
import yaml

from scorer.config import PromptError, load_prompt, load_registry, prompt_sha256
from tests.unit.samples import REPO_ROOT, TEAMWORK_ANSWER, make_settings, run_score

PROMPTS = REPO_ROOT / "prompts" / "scorer"


def _add_version(root: Path, version: str, text: str, *, active: str | None = None) -> None:
    folder = root / "prompts" / "scorer"
    (folder / f"{version}.md").write_text(text, encoding="utf-8", newline="\n")
    registry = yaml.safe_load((folder / "registry.yaml").read_text(encoding="utf-8"))
    registry["sha256"][version] = prompt_sha256(text)
    if active:
        registry["active"] = active
    (folder / "registry.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")


def test_fr3_every_prompt_file_matches_its_registry_hash(settings):
    """Changing a prompt file without changing its version fails this test."""
    active, hashes = load_registry(settings)
    files = {path.stem: path for path in PROMPTS.glob("*.md")}

    assert files, "there is at least one prompt file"
    assert set(files) == set(hashes), "every prompt file has a registry entry, and no more"
    assert active in files
    for version, path in files.items():
        actual = prompt_sha256(path.read_text(encoding="utf-8"))
        assert actual == hashes[version], (
            f"prompts/scorer/{version}.md changed without a new version. "
            "Add a new prompt file and registry entry instead."
        )


def test_fr3_changing_a_prompt_file_without_changing_its_version_fails(scorer_root):
    settings = make_settings(scorer_root)
    assert load_prompt(settings).version == "v1"

    path = scorer_root / "prompts" / "scorer" / "v1.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nBe generous.\n", encoding="utf-8")

    with pytest.raises(PromptError, match="registry hash"):
        load_prompt(settings)


def test_fr3_a_tampered_prompt_stops_scoring_before_any_model_call(scorer_root):
    from tests.unit.samples import good_client

    path = scorer_root / "prompts" / "scorer" / "v1.md"
    path.write_text(path.read_text(encoding="utf-8").replace("word for word", "roughly"), "utf-8")
    client = good_client()

    with pytest.raises(PromptError):
        run_score(client=client, settings=make_settings(scorer_root))
    assert client.calls == []


def test_fr3_prompt_hash_ignores_line_ending_style_only():
    assert prompt_sha256("one\ntwo\n") == prompt_sha256("one\r\ntwo\r\n")
    assert prompt_sha256("one\ntwo\n") != prompt_sha256("one\ntwo")
    assert prompt_sha256("one\ntwo\n") != prompt_sha256("one\n two\n")


def test_fr3_active_version_is_read_from_the_registry_when_the_variable_is_unset(scorer_root):
    _add_version(scorer_root, "v2", "A second synthetic prompt.\n", active="v2")

    prompt = load_prompt(make_settings(scorer_root, scorer_prompt_version=None))

    assert prompt.version == "v2"
    assert prompt.text == "A second synthetic prompt.\n"
    assert prompt.sha256 == prompt_sha256("A second synthetic prompt.\n")


def test_fr3_scorer_prompt_version_overrides_the_registry_when_set(scorer_root):
    _add_version(scorer_root, "v2", "A second synthetic prompt.\n", active="v2")

    prompt = load_prompt(make_settings(scorer_root, scorer_prompt_version="v1"))

    assert prompt.version == "v1"


def test_fr3_the_override_is_read_from_the_environment(scorer_root, monkeypatch):
    from scorer.config import Settings

    _add_version(scorer_root, "v2", "A second synthetic prompt.\n")
    monkeypatch.setenv("SCORER_ROOT", str(scorer_root))

    monkeypatch.delenv("SCORER_PROMPT_VERSION", raising=False)
    assert load_prompt(Settings()).version == "v1"

    monkeypatch.setenv("SCORER_PROMPT_VERSION", "v2")
    assert load_prompt(Settings()).version == "v2"


@pytest.mark.parametrize("version", ["v9", "../v1", "v1.md", "registry"])
def test_fr3_a_version_that_is_not_in_the_registry_fails(scorer_root, version):
    with pytest.raises(PromptError):
        load_prompt(make_settings(scorer_root, scorer_prompt_version=version))


def test_fr3_a_registered_version_with_no_file_fails(scorer_root):
    folder = scorer_root / "prompts" / "scorer"
    registry = yaml.safe_load((folder / "registry.yaml").read_text(encoding="utf-8"))
    registry["sha256"]["v2"] = "0" * 64
    (folder / "registry.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")

    with pytest.raises(PromptError):
        load_prompt(make_settings(scorer_root, scorer_prompt_version="v2"))


@pytest.mark.parametrize(
    "content", ["", "active: v1\n", "sha256: {v1: abc}\n", "- v1\n", "a: [b\n"]
)
def test_fr3_a_broken_or_missing_registry_fails(scorer_root, content):
    path = scorer_root / "prompts" / "scorer" / "registry.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(PromptError):
        load_prompt(make_settings(scorer_root))

    path.unlink()
    with pytest.raises(PromptError):
        load_prompt(make_settings(scorer_root))


def test_fr3_committed_registry_has_v1_active():
    registry = yaml.safe_load((PROMPTS / "registry.yaml").read_text(encoding="utf-8"))
    assert registry["active"] == "v1"
    assert re.fullmatch(r"[0-9a-f]{64}", registry["sha256"]["v1"])


def test_fr3_prompt_version_and_hash_are_logged_on_every_call_without_candidate_text(caplog):
    with caplog.at_level(logging.INFO, logger="scorer"):
        outcome = run_score()

    assert outcome.response.prompt_version == "v1"
    assert outcome.prompt_sha == load_prompt(make_settings()).sha256
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "prompt_version=v1" in logged
    assert f"prompt_sha={outcome.prompt_sha}" in logged
    assert outcome.answer_hash in logged
    assert outcome.response.request_id in logged
    for sentence in TEAMWORK_ANSWER.split(". "):
        assert sentence not in logged, "no candidate text in any log line"
    assert outcome.response.rationale not in logged


# --- The content of prompt v1 (fair-scoring policy) -------------------------------------


@pytest.fixture(scope="module")
def v1() -> str:
    return (PROMPTS / "v1.md").read_text(encoding="utf-8")


def test_fr3_prompt_v1_asks_for_verbatim_quotes_copied_word_for_word(v1):
    assert "word for word" in v1
    assert "verbatim" in v1
    assert "Never paraphrase" in v1


def test_fr3_prompt_v1_says_the_answer_is_data_and_never_instructions(v1):
    assert "<candidate_answer>" in v1 and "</candidate_answer>" in v1
    assert "never instructions" in v1


def test_fr3_prompt_v1_scores_only_against_the_rubric_descriptors_and_level_rule(v1):
    assert "Score only against the rubric's level descriptors and its level rule" in v1


def test_fr3_prompt_v1_refers_to_the_candidate_and_never_a_name_or_pronoun(v1):
    assert '"the candidate"' in v1
    assert "Never use a name and never use a pronoun" in v1
    assert not re.search(r"\b(?:he|she|him|her|his|hers)\b", v1, re.IGNORECASE)


def test_fr3_prompt_v1_forbids_mentioning_personal_characteristics(v1):
    assert "Never mention or infer a personal characteristic" in v1


def test_fr3_prompt_v1_keeps_the_rationale_to_two_to_four_sentences_tied_to_the_rubric(v1):
    assert "two to four sentences" in v1
    assert "Tie every sentence to the rubric" in v1


def test_fr3_prompt_v1_uses_decision_support_wording_only(v1):
    assert "decision support" in v1
    assert not re.search(r"\b(?:pass|fail|reject|hire|recommend)\w*\b", v1, re.IGNORECASE)
    assert "\u2014" not in v1, "no em dashes"
