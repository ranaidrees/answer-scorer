"""Path check for the `evals` workflow (spec section 7 "Runs" and section 9).

The `evals` job always runs and always reports. On a pull request this step decides
whether the model has to be called:

- no file that affects scoring changed: write a "no relevant changes" summary and let the
  job finish with success, with no sign-in and no model call;
- a relevant file changed and the run can sign in: carry on to the evals;
- a relevant file changed but the run cannot sign in (a pull request from a fork gets no
  OIDC token and no secrets): fail, because the gate cannot be proven.

On the nightly schedule and on a manual run the evals always run. If the changed files
cannot be listed, the change is treated as relevant, so a fault here never skips the gate.

Standard library only: this runs before any dependency is installed. It prints no file
name from the pull request, only counts per area.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass

# A change under any of these can change a score, a metric or the gate itself.
RELEVANT_PREFIXES = ("prompts/", "rubrics/", "src/scorer/", "evals/", "config/")
# Reports are output, not input.
IGNORED_PREFIXES = ("evals/reports/",)

_SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")


def relevant_area(path: str) -> str | None:
    """The relevant area a changed path falls under, or None if it cannot affect scoring."""
    if path.startswith(IGNORED_PREFIXES):
        return None
    return next((prefix for prefix in RELEVANT_PREFIXES if path.startswith(prefix)), None)


def changed_files(base: str, head: str) -> list[str] | None:
    """Files changed on the head since it left the base. None if they cannot be listed.

    Renames are listed as a removal and an addition, so a file moved out of a relevant
    folder still counts.
    """
    if not _SHA.fullmatch(base) or not _SHA.fullmatch(head):
        return None
    try:
        done = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}"],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return [name for name in done.stdout.decode("utf-8", "replace").split("\0") if name]


@dataclass(frozen=True)
class Decision:
    run: bool  # carry on to the sign-in and the evals
    ok: bool  # False fails the job at this step
    summary: str


def decide(event_name: str, changed: list[str] | None, *, can_sign_in: bool) -> Decision:
    if event_name != "pull_request":
        return Decision(True, True, "Scheduled or manual run: the evals always run.")

    if changed is None:
        found = "The changed files could not be listed, so the change is treated as relevant."
    else:
        areas = Counter(area for area in map(relevant_area, changed) if area)
        if not areas:
            return Decision(
                False,
                True,
                f"**No relevant changes.** None of the {len(changed)} changed files is under "
                "`prompts/`, `rubrics/`, `src/scorer/`, `evals/` (other than `evals/reports/`) "
                "or `config/`, so no score can have changed. The model was not called and the "
                "gate result on the base branch stands.",
            )
        listed = ", ".join(f"`{area}` ({count})" for area, count in sorted(areas.items()))
        found = f"Relevant changes: {listed}."

    if not can_sign_in:
        return Decision(
            False,
            False,
            f"**The gate cannot be proven.** {found} A pull request from a fork (or from "
            "Dependabot) gets no sign-in token and no secrets, so the evals cannot call the "
            "model. The job fails rather than pass a change it could not check. A maintainer "
            "can run the evals from a branch in this repository.",
        )
    return Decision(True, True, f"{found} Running the evals.")


def main() -> int:
    env = os.environ
    event_name = env.get("EVENT_NAME", "")
    changed = None
    can_sign_in = True
    if event_name == "pull_request":
        changed = changed_files(env.get("BASE_SHA", ""), env.get("HEAD_SHA", ""))
        # A fork, and a Dependabot pull request, get a read-only token and no secrets.
        from_fork = env.get("HEAD_REPO", "") != env.get("THIS_REPO", "")
        can_sign_in = not from_fork and env.get("ACTOR", "") != "dependabot[bot]"
    decision = decide(event_name, changed, can_sign_in=can_sign_in)

    text = f"## Evals: path check\n\n{decision.summary}\n"
    print(decision.summary)
    for variable, line in (
        ("GITHUB_STEP_SUMMARY", text + "\n"),
        ("GITHUB_OUTPUT", f"run={'true' if decision.run else 'false'}\n"),
    ):
        target = env.get(variable)
        if target:
            with open(target, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
    return 0 if decision.ok else 1


if __name__ == "__main__":
    sys.exit(main())
