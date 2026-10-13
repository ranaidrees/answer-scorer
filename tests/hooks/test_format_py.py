"""Tests for .claude/hooks/format_py.py: it formats one Python file and never blocks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.hooks.conftest import HOOKS_DIR, run_hook

spec = importlib.util.spec_from_file_location("format_py", HOOKS_DIR / "format_py.py")
format_py = importlib.util.module_from_spec(spec)
spec.loader.exec_module(format_py)


def test_a_python_file_is_selected(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("x=1\n", encoding="utf-8")
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}
    assert format_py.changed_python_file(payload) == target


def test_a_relative_path_is_resolved_against_cwd(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("x=1\n", encoding="utf-8")
    payload = {"tool_name": "Edit", "cwd": str(tmp_path), "tool_input": {"file_path": "module.py"}}
    assert format_py.changed_python_file(payload) == tmp_path / "module.py"


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "Write", "tool_input": {"file_path": "notes.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "missing.py"}},
        {"tool_name": "Bash", "tool_input": {"command": "python x.py"}},
        {"tool_name": "Write", "tool_input": {}},
    ],
)
def test_other_edits_are_skipped(payload: dict) -> None:
    assert format_py.changed_python_file(payload) is None


def test_only_the_changed_file_is_passed_to_ruff(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    for command in format_py.commands(target):
        assert "ruff" in command
        assert command[-1] == str(target)
        assert "." not in command


def test_the_hook_formats_the_file(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("x   =   1\n", encoding="utf-8")
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}
    project = str(HOOKS_DIR.parents[1])
    result = run_hook("format_py.py", payload, env={"CLAUDE_PROJECT_DIR": project})
    assert result.returncode == 0
    assert target.read_text(encoding="utf-8") == "x = 1\n"


@pytest.mark.parametrize("raw", ["", "not json", "[]"])
def test_bad_payloads_never_block(raw: str) -> None:
    assert run_hook("format_py.py", None, raw=raw).returncode == 0
