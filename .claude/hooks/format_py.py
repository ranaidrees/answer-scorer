"""PostToolUse formatter for the Edit and Write tools.

Runs `ruff format` and `ruff check --fix` on the one Python file that changed.
It never blocks: the edit has already happened, and `uv run poe check` is the
gate. Always exits 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def changed_python_file(payload: dict) -> Path | None:
    if payload.get("tool_name") not in ("Edit", "Write", "MultiEdit"):
        return None
    path = (payload.get("tool_input") or {}).get("file_path")
    if not isinstance(path, str) or not path.endswith(".py"):
        return None
    target = Path(path)
    if not target.is_absolute():
        target = Path(payload.get("cwd") or ".") / target
    return target if target.is_file() else None


def commands(target: Path) -> list[list[str]]:
    return [
        ["uv", "run", "ruff", "format", str(target)],
        ["uv", "run", "ruff", "check", "--fix", "--quiet", str(target)],
    ]


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        target = changed_python_file(payload) if isinstance(payload, dict) else None
        if target is None:
            return 0
        root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or None
        for command in commands(target):
            subprocess.run(command, cwd=root, capture_output=True, timeout=60, check=False)
    except Exception as error:  # noqa: BLE001 - formatting must never block an edit
        print(f"format_py: skipped ({error!r})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
