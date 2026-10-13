"""Shared helpers for the hook tests: run a hook script with a piped JSON payload."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "hooks"


def run_hook(script: str, payload: object, *, env: dict | None = None, raw: str | None = None):
    """Run a hook the way Claude Code does: JSON on stdin, verdict in the exit code."""
    hook_env = {key: value for key, value in os.environ.items() if key != "CLAUDE_PROJECT_DIR"}
    hook_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / script)],
        input=raw if raw is not None else json.dumps(payload),
        capture_output=True,
        text=True,
        env=hook_env,
        timeout=60,
        check=False,
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _make_repo(path: Path, branch: str) -> Path:
    path.mkdir()
    _git(path, "init", "-b", branch)
    _git(
        path,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "init",
    )
    return path


@pytest.fixture
def repo_on_main(tmp_path: Path) -> Path:
    return _make_repo(tmp_path / "on-main", "main")


@pytest.fixture
def repo_on_branch(tmp_path: Path) -> Path:
    return _make_repo(tmp_path / "on-branch", "feature")
