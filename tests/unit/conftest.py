"""Fixtures for the scorer unit tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scorer.config import Settings
from tests.unit.samples import REPO_ROOT, make_settings


@pytest.fixture
def settings() -> Settings:
    """Settings pointing at the real rubrics and prompts in this repository."""
    return make_settings()


@pytest.fixture
def scorer_root(tmp_path: Path) -> Path:
    """A temporary SCORER_ROOT holding a copy of the real rubrics and prompts."""
    root = tmp_path / "root"
    shutil.copytree(REPO_ROOT / "rubrics", root / "rubrics")
    shutil.copytree(REPO_ROOT / "prompts", root / "prompts")
    return root
