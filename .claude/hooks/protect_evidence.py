"""PreToolUse gate for the Edit and Write tools.

While `.claude/fix-mode` exists, edits to tests, eval datasets, thresholds and
rubrics are blocked, so a defect is fixed in the code or the prompt and never
by changing the evidence. Exit 2 blocks with a reason on stderr; any error also
exits 2 (fail closed).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path, PurePosixPath

PROTECTED_DIRS = ("tests", "evals/datasets", "rubrics")
PROTECTED_FILES = ("evals/thresholds.yaml",)


class Deny(Exception):
    """Raised with the reason an edit is blocked."""


def _project_dir(payload: dict) -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
    if not root:
        raise Deny("could not work out the project folder")
    return Path(root).resolve()


def _relative(path: str, root: Path) -> PurePosixPath | None:
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    try:
        relative = target.resolve().relative_to(root)
    except ValueError:
        return None
    return PurePosixPath(relative.as_posix().lower())


def check(payload: dict) -> None:
    if payload.get("tool_name") not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return
    root = _project_dir(payload)
    if not (root / ".claude" / "fix-mode").exists():
        return
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str) or not path:
        raise Deny("no file path found in the hook payload")
    relative = _relative(path, root)
    if relative is None:
        return
    text = relative.as_posix()
    protected = text in PROTECTED_FILES or any(
        text == folder or text.startswith(folder + "/") for folder in PROTECTED_DIRS
    )
    if protected:
        raise Deny(
            f"fix mode is on, so {text} is locked. Fix the code or the prompt, "
            "never the tests, datasets, thresholds or rubrics"
        )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise Deny("hook payload is not a JSON object")
        check(payload)
    except Deny as reason:
        print(f"protect_evidence: {reason}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - fail closed on anything unexpected
        print(
            f"protect_evidence: blocked because the gate itself failed: {error!r}", file=sys.stderr
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
