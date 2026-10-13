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


@pytest.fixture(autouse=True)
def _no_waiting_between_eval_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The eval runner waits before trying a failed input again; tests do not wait."""
    try:
        import evals.run_evals as run_evals
    except ImportError:
        return
    monkeypatch.setattr(run_evals, "ITEM_RETRY_WAITS", (0.0, 0.0))
