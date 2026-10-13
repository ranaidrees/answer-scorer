"""Allow and deny cases for .claude/hooks/protect_evidence.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.hooks.conftest import run_hook

PROTECTED = [
    "tests/unit/test_grounding.py",
    "tests/hooks/test_cloud_gate.py",
    "evals/datasets/golden.jsonl",
    "evals/thresholds.yaml",
    "rubrics/teamwork.yaml",
    "Rubrics/Teamwork.yaml",
]
UNPROTECTED = [
    "src/scorer/grounding.py",
    "prompts/scorer/v2.md",
    "evals/run_evals.py",
    "evals/reports/latest.md",
    "intent/decisions.md",
]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    return tmp_path


def edit(project: Path, path: str, tool: str = "Edit", *, absolute: bool = False):
    file_path = str(project / path) if absolute else path
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "cwd": str(project),
        "tool_input": {"file_path": file_path},
    }
    return run_hook("protect_evidence.py", payload, env={"CLAUDE_PROJECT_DIR": str(project)})


@pytest.mark.parametrize("tool", ["Edit", "Write"])
@pytest.mark.parametrize("absolute", [True, False])
@pytest.mark.parametrize("path", PROTECTED)
def test_protected_paths_are_locked_in_fix_mode(
    project: Path, path: str, tool: str, absolute: bool
) -> None:
    (project / ".claude" / "fix-mode").touch()
    result = edit(project, path, tool, absolute=absolute)
    assert result.returncode == 2, result.stderr
    assert "fix mode is on" in result.stderr


@pytest.mark.parametrize("path", UNPROTECTED)
def test_other_paths_stay_editable_in_fix_mode(project: Path, path: str) -> None:
    (project / ".claude" / "fix-mode").touch()
    result = edit(project, path, absolute=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", PROTECTED + UNPROTECTED)
def test_everything_is_editable_when_fix_mode_is_off(project: Path, path: str) -> None:
    result = edit(project, path, absolute=True)
    assert result.returncode == 0, result.stderr


def test_windows_style_separators_are_normalised(project: Path) -> None:
    (project / ".claude" / "fix-mode").touch()
    result = edit(project, "evals\\datasets\\golden.jsonl")
    # On Windows the backslash is a separator; on Linux it is part of a file name.
    import os

    assert result.returncode == (2 if os.name == "nt" else 0), result.stderr


def test_files_outside_the_project_pass(project: Path, tmp_path_factory) -> None:
    (project / ".claude" / "fix-mode").touch()
    outside = tmp_path_factory.mktemp("elsewhere") / "tests" / "note.txt"
    payload = {"tool_name": "Write", "cwd": str(project), "tool_input": {"file_path": str(outside)}}
    result = run_hook("protect_evidence.py", payload, env={"CLAUDE_PROJECT_DIR": str(project)})
    assert result.returncode == 0, result.stderr


def test_the_project_folder_falls_back_to_cwd(project: Path) -> None:
    (project / ".claude" / "fix-mode").touch()
    payload = {
        "tool_name": "Edit",
        "cwd": str(project),
        "tool_input": {"file_path": "rubrics/teamwork.yaml"},
    }
    assert run_hook("protect_evidence.py", payload).returncode == 2


def test_other_tools_pass(project: Path) -> None:
    (project / ".claude" / "fix-mode").touch()
    payload = {"tool_name": "Bash", "cwd": str(project), "tool_input": {"command": "ls tests"}}
    assert run_hook("protect_evidence.py", payload).returncode == 0


@pytest.mark.parametrize("raw", ["", "not json", "[]"])
def test_bad_payloads_fail_closed_with_exit_2(raw: str) -> None:
    result = run_hook("protect_evidence.py", None, raw=raw)
    assert result.returncode == 2
    assert result.stderr.startswith("protect_evidence: ")


def test_a_missing_file_path_fails_closed_in_fix_mode(project: Path) -> None:
    (project / ".claude" / "fix-mode").touch()
    payload = {"tool_name": "Edit", "cwd": str(project), "tool_input": {}}
    assert run_hook("protect_evidence.py", payload).returncode == 2


def test_no_project_folder_fails_closed() -> None:
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "tests/x.py"}}
    assert run_hook("protect_evidence.py", payload).returncode == 2
