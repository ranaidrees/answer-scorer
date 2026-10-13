"""The path check of the `evals` workflow (spec section 7 "Runs", plan S4b risk).

The risk is a check that skips a relevant change. These tests fix which paths count, and
that every doubtful case runs the evals or fails, and never passes without them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evals import changed_paths
from evals.changed_paths import changed_files, decide, relevant_area

SHA_A = "a" * 40
SHA_B = "b" * 40


@pytest.mark.parametrize(
    ("path", "area"),
    [
        ("prompts/scorer/v2.md", "prompts/"),
        ("prompts/scorer/registry.yaml", "prompts/"),
        ("rubrics/teamwork.yaml", "rubrics/"),
        ("src/scorer/pipeline.py", "src/scorer/"),
        ("src/scorer/ui/index.html", "src/scorer/"),
        ("evals/datasets/golden.jsonl", "evals/"),
        ("evals/thresholds.yaml", "evals/"),
        ("evals/run_evals.py", "evals/"),
        ("evals/changed_paths.py", "evals/"),
        ("config/prices.yaml", "config/"),
    ],
)
def test_paths_that_can_change_a_score_or_the_gate_are_relevant(path, area):
    assert relevant_area(path) == area


@pytest.mark.parametrize(
    "path",
    [
        "evals/reports/20261013T210000Z.md",
        "evals/reports/20261013T210000Z.json",
        "README.md",
        "docs/eval_card.md",
        "intent/plan.md",
        "infra/main.bicep",
        "tests/unit/test_metrics.py",
        ".github/workflows/evals.yml",
        "pyproject.toml",
        "src/other/module.py",
        "notprompts/x.md",
        "docs/prompts/notes.md",
        "evals_old/thing.py",
    ],
)
def test_other_paths_are_not_relevant(path):
    assert relevant_area(path) is None


def test_a_scheduled_or_manual_run_always_runs():
    for event in ("schedule", "workflow_dispatch"):
        decision = decide(event, None, can_sign_in=True)
        assert (decision.run, decision.ok) == (True, True)


def test_a_pull_request_with_no_relevant_change_succeeds_without_the_model():
    decision = decide("pull_request", ["README.md", "evals/reports/x.md"], can_sign_in=True)
    assert (decision.run, decision.ok) == (False, True)
    assert "No relevant changes" in decision.summary
    assert "The model was not called" in decision.summary


def test_a_pull_request_with_a_relevant_change_runs_the_evals():
    changed = ["README.md", "prompts/scorer/v2.md", "prompts/scorer/registry.yaml", "config/p.yaml"]
    decision = decide("pull_request", changed, can_sign_in=True)
    assert (decision.run, decision.ok) == (True, True)
    assert "`prompts/` (2)" in decision.summary and "`config/` (1)" in decision.summary


def test_one_relevant_file_among_many_is_enough():
    changed = [f"docs/page-{number}.md" for number in range(200)] + ["rubrics/teamwork.yaml"]
    assert decide("pull_request", changed, can_sign_in=True).run is True


def test_a_fork_with_a_relevant_change_fails_and_never_passes():
    decision = decide("pull_request", ["src/scorer/pipeline.py"], can_sign_in=False)
    assert (decision.run, decision.ok) == (False, False)
    assert "The gate cannot be proven" in decision.summary


def test_a_fork_with_no_relevant_change_succeeds():
    decision = decide("pull_request", ["README.md"], can_sign_in=False)
    assert (decision.run, decision.ok) == (False, True)


def test_files_that_cannot_be_listed_count_as_relevant():
    assert decide("pull_request", None, can_sign_in=True).run is True
    blocked = decide("pull_request", None, can_sign_in=False)
    assert (blocked.run, blocked.ok) == (False, False)


def test_an_empty_change_list_is_not_relevant():
    assert decide("pull_request", [], can_sign_in=True).run is False


def test_the_summary_never_repeats_a_file_name_from_the_pull_request():
    name = "prompts/scorer/<img src=x onerror=alert(1)>.md"
    for can_sign_in in (True, False):
        assert name not in decide("pull_request", [name], can_sign_in=can_sign_in).summary


def test_a_ref_that_is_not_a_commit_id_is_never_passed_to_git(monkeypatch):
    def no_git(*args, **kwargs):
        raise AssertionError("git must not be called")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert changed_files("main", SHA_B) is None
    assert changed_files(SHA_A, "--output=x") is None
    assert changed_files("", "") is None


def test_a_failed_git_command_gives_no_list(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 128, b"", b"bad object"),
    )
    assert changed_files(SHA_A, SHA_B) is None


def git(repo: Path, *arguments: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test.invalid", *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def test_changed_files_in_a_real_repository_including_a_file_moved_out(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "prompts" / "v1.md").write_text("prompt text\n" * 20, encoding="utf-8")
    (repo / "README.md").write_text("readme\n", encoding="utf-8")
    git(repo, "init", "--quiet")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")

    # The head moves the prompt out of `prompts/` unchanged, and edits the README.
    (repo / "prompts" / "v1.md").rename(repo / "docs" / "v1.md")
    (repo / "README.md").write_text("readme, edited\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "head")
    head = git(repo, "rev-parse", "HEAD")

    monkeypatch.chdir(repo)
    changed = changed_files(base, head)
    # The move is listed as a removal as well, so the prompt path still counts.
    assert sorted(changed) == ["README.md", "docs/v1.md", "prompts/v1.md"]
    assert decide("pull_request", changed, can_sign_in=True).run is True


def run_main(monkeypatch, tmp_path, **env: str) -> tuple[int, str, str]:
    summary, output = tmp_path / "summary.md", tmp_path / "output.txt"
    for name in ("EVENT_NAME", "BASE_SHA", "HEAD_SHA", "HEAD_REPO", "THIS_REPO", "ACTOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    code = changed_paths.main()
    return code, summary.read_text(encoding="utf-8"), output.read_text(encoding="utf-8")


PULL_REQUEST = {
    "EVENT_NAME": "pull_request",
    "BASE_SHA": SHA_A,
    "HEAD_SHA": SHA_B,
    "HEAD_REPO": "owner/answer-scorer",
    "THIS_REPO": "owner/answer-scorer",
    "ACTOR": "owner",
}


def test_main_always_reports_and_sets_the_run_output(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(changed_paths, "changed_files", lambda base, head: ["README.md"])
    code, summary, output = run_main(monkeypatch, tmp_path, **PULL_REQUEST)
    assert (code, output) == (0, "run=false\n")
    assert "No relevant changes" in summary

    monkeypatch.setattr(changed_paths, "changed_files", lambda base, head: ["rubrics/x.yaml"])
    code, summary, output = run_main(monkeypatch, tmp_path, **PULL_REQUEST)
    assert code == 0 and output.endswith("run=true\n")
    assert "Running the evals" in summary
    capsys.readouterr()


def test_main_fails_a_fork_or_dependabot_pull_request_that_changes_a_relevant_path(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(changed_paths, "changed_files", lambda base, head: ["src/scorer/a.py"])
    fork = {**PULL_REQUEST, "HEAD_REPO": "someone/answer-scorer"}
    code, summary, output = run_main(monkeypatch, tmp_path, **fork)
    assert (code, output) == (1, "run=false\n")
    assert "The gate cannot be proven" in summary

    code, _, output = run_main(monkeypatch, tmp_path, **{**PULL_REQUEST, "HEAD_REPO": ""})
    assert (code, output.splitlines()[-1]) == (1, "run=false")  # a deleted fork

    bot = {**PULL_REQUEST, "ACTOR": "dependabot[bot]"}
    code, _, _ = run_main(monkeypatch, tmp_path, **bot)
    assert code == 1
    capsys.readouterr()


def test_main_runs_on_the_schedule_without_looking_at_any_diff(monkeypatch, tmp_path, capsys):
    def no_diff(base, head):
        raise AssertionError("no diff on a scheduled run")

    monkeypatch.setattr(changed_paths, "changed_files", no_diff)
    code, summary, output = run_main(monkeypatch, tmp_path, EVENT_NAME="schedule")
    assert (code, output) == (0, "run=true\n")
    assert "always run" in summary
    capsys.readouterr()
