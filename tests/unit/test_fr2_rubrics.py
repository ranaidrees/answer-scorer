"""FR-2: the rubric format. The loader validates the schema and fails fast."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from scorer.config import (
    Rubric,
    RubricError,
    UnknownCompetencyError,
    load_all_rubrics,
    load_rubric,
)
from tests.unit.samples import make_settings

VALID = {
    "id": "sample",
    "name": "Sample",
    "definition": "A synthetic competency used only by this test.",
    "levels": [
        {"level": number, "label": f"Label {number}", "descriptors": [f"Behaviour {number}."]}
        for number in range(1, 6)
    ],
}


def _write(root: Path, data: object, name: str = "sample") -> None:
    folder = root / "rubrics"
    folder.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False)
    (folder / f"{name}.yaml").write_text(text, encoding="utf-8")


def _broken(change) -> dict:
    data = copy.deepcopy(VALID)
    change(data)
    return data


@pytest.mark.parametrize("competency_id", ["teamwork", "problem_solving"])
def test_fr2_both_real_rubrics_load_with_five_levels(settings, competency_id):
    rubric = load_rubric(competency_id, settings)

    assert isinstance(rubric, Rubric)
    assert rubric.id == competency_id
    assert rubric.name and rubric.definition
    assert len(rubric.levels) == 5
    assert [level.level for level in rubric.levels] == [1, 2, 3, 4, 5]
    assert [level.label for level in rubric.levels] == [
        "Limited",
        "Developing",
        "Competent",
        "Strong",
        "Exceptional",
    ]
    assert all(level.descriptors for level in rubric.levels)
    assert rubric.label_for(4) == "Strong"


def test_fr2_load_all_rubrics_returns_both_real_rubrics_for_startup_validation(settings):
    rubrics = load_all_rubrics(settings)
    assert set(rubrics) == {"teamwork", "problem_solving"}
    assert all(key == rubric.id for key, rubric in rubrics.items())


def test_fr2_valid_rubric_loads_from_a_temporary_root(tmp_path):
    _write(tmp_path, VALID)
    rubric = load_rubric("sample", make_settings(tmp_path))
    assert rubric.name == "Sample"


def test_fr2_level_key_is_optional(tmp_path):
    _write(tmp_path, _broken(lambda d: [level.pop("level") for level in d["levels"]]))
    rubric = load_rubric("sample", make_settings(tmp_path))
    assert [level.level for level in rubric.levels] == [None] * 5


BROKEN_RUBRICS = {
    "missing id": _broken(lambda d: d.pop("id")),
    "missing name": _broken(lambda d: d.pop("name")),
    "missing definition": _broken(lambda d: d.pop("definition")),
    "missing levels": _broken(lambda d: d.pop("levels")),
    "empty definition": _broken(lambda d: d.update(definition="   ")),
    "four levels": _broken(lambda d: d["levels"].pop()),
    "six levels": _broken(lambda d: d["levels"].append(copy.deepcopy(d["levels"][0]))),
    "level without label": _broken(lambda d: d["levels"][2].pop("label")),
    "level without descriptors": _broken(lambda d: d["levels"][2].pop("descriptors")),
    "empty descriptors": _broken(lambda d: d["levels"][2].update(descriptors=[])),
    "blank descriptor": _broken(lambda d: d["levels"][2].update(descriptors=["  "])),
    "descriptors not a list": _broken(lambda d: d["levels"][2].update(descriptors="One.")),
    "levels out of order": _broken(lambda d: d["levels"].reverse()),
    "level number repeated": _broken(lambda d: d["levels"][4].update(level=4)),
    "level number out of range": _broken(lambda d: d["levels"][4].update(level=6)),
    "level number not an integer": _broken(lambda d: d["levels"][0].update(level="1")),
    "unknown top-level key": _broken(lambda d: d.update(weight=2)),
    "unknown level key": _broken(lambda d: d["levels"][0].update(score=1)),
    "id does not match the file name": _broken(lambda d: d.update(id="other")),
    "not a mapping": ["id", "name"],
    "invalid yaml": "id: sample\nlevels: [unclosed\n",
    "empty file": "",
}


@pytest.mark.parametrize("case", sorted(BROKEN_RUBRICS))
def test_fr2_broken_rubric_fails_fast(tmp_path, case):
    _write(tmp_path, BROKEN_RUBRICS[case])
    settings = make_settings(tmp_path)

    with pytest.raises(RubricError):
        load_rubric("sample", settings)
    with pytest.raises(RubricError):
        load_all_rubrics(settings)


def test_fr2_one_broken_rubric_fails_startup_validation_even_if_others_are_valid(tmp_path):
    _write(tmp_path, VALID)
    _write(tmp_path, BROKEN_RUBRICS["four levels"], name="broken")
    with pytest.raises(RubricError):
        load_all_rubrics(make_settings(tmp_path))


def test_fr2_no_rubrics_at_all_fails_startup_validation(tmp_path):
    with pytest.raises(RubricError):
        load_all_rubrics(make_settings(tmp_path))


def test_fr2_missing_rubric_is_an_unknown_competency(tmp_path):
    _write(tmp_path, VALID)
    with pytest.raises(UnknownCompetencyError):
        load_rubric("teamwork", make_settings(tmp_path))
