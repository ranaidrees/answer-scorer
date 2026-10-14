"""The delivery evidence snapshot script, with a fake `gh`, git and pytest.

`run_command` is the script's only subprocess call; every test here replaces it, so no
test calls the network. The fake GitHub data carries an author name, an email address and
a token-shaped string on purpose: none of them may reach the console or the file.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import sdlc_snapshot as snap

REPO_URL = "https://github.com/ranaidrees/answer-scorer"
API = "repos/ranaidrees/answer-scorer"
NOW = datetime(2026, 10, 14, 15, 30, tzinfo=UTC)
AUTHOR_NAME = "Jane Example"
# Fake addresses and hosts are assembled at run time, so the file itself holds none.
AT = chr(64)
AUTHOR_EMAIL = "jane.example" + AT + "example.invalid"
BOT_EMAIL = "noreply" + AT + "example.invalid"
FAKE_TOKEN = "ghp_" + "A1b2C3d4E5" * 4
RULESET_ID = 4242424
PINNED = "actions/checkout@" + "a" * 40
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
TOKEN = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_")
UTC_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def sha(n: int) -> str:
    """A made-up 40-character commit SHA that starts with n and holds no long digit run."""
    return (f"{n:03d}" + "abcdef" * 7)[:40]


def owner(state: str) -> dict:
    return {"state": state, "user": {"login": "ranaidrees", "email": AUTHOR_EMAIL}}


def ci_run(run_id: int, conclusion: str, status: str = "completed") -> dict:
    return {"id": run_id, "status": status, "conclusion": conclusion}


def ci_jobs(start: str, job_seconds: int, test_seconds: int) -> dict:
    begin = datetime.fromisoformat(start.replace("Z", "+00:00"))

    def at(seconds: int) -> str:
        return datetime.fromtimestamp(begin.timestamp() + seconds, UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    return {
        "jobs": [
            {
                "name": "ci",
                "started_at": start,
                "completed_at": at(job_seconds),
                "steps": [
                    {"name": "Check out", "started_at": start, "completed_at": at(1)},
                    {
                        "name": "Lint, format check and tests (including hook tests)",
                        "started_at": at(2),
                        "completed_at": at(2 + test_seconds),
                    },
                ],
            }
        ]
    }


def steps(**conclusions: str) -> list[dict]:
    names = {
        "route": "Choose the route",
        "provenance": "Verify build provenance",
        "revision": "Create a revision with the verified image",
        "warm": "Keep one replica warm",
        "checkout": "Check out (for the smoke test)",
        "smoke": "Smoke test the live app",
    }
    return [
        {"name": names[key], "conclusion": conclusion} for key, conclusion in conclusions.items()
    ]


def deploy_run(run_id, number, event, started, updated, head, conclusion, status="completed"):
    return {
        "id": run_id,
        "run_number": number,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "head_sha": head,
        "run_started_at": started,
        "updated_at": updated,
    }


def fake_github() -> dict[str, object]:
    """The GitHub API as the fake gh sees it: endpoint path (no query) to response body."""
    pr1 = {"number": 1, "merged_at": "2026-10-13T21:00:00Z", "merge_commit_sha": sha(101)}
    pr2 = {"number": 2, "merged_at": "2026-10-13T22:46:15Z", "merge_commit_sha": sha(103)}
    pulls = [
        {**pr2, "state": "closed", "head": {"sha": sha(12)}},
        {"number": 5, "state": "closed", "merged_at": None, "head": {"sha": sha(15)}},
        {"number": 3, "state": "open", "merged_at": None, "head": {"sha": sha(13)}},
        {"number": 4, "state": "open", "merged_at": None, "head": {"sha": sha(14)}},
        {**pr1, "state": "closed", "head": {"sha": sha(11)}},
    ]
    commit_by = {"name": AUTHOR_NAME, "email": AUTHOR_EMAIL}

    def commit(n: int, message: str) -> dict:
        return {
            "sha": sha(n),
            "commit": {"message": message, "author": commit_by, "committer": commit_by},
            "author": {"login": "jane-example"},
        }

    trailer = f"Co-Authored-By: Claude Opus <{BOT_EMAIL}>"
    deploy_runs = [
        # Listed newest first, as GitHub does.
        deploy_run(
            207,
            7,
            "push",
            "2026-10-14T13:12:13Z",
            "2026-10-14T13:12:59Z",
            sha(107),
            None,
            "waiting",
        ),
        deploy_run(
            206,
            6,
            "workflow_dispatch",
            "2026-10-14T11:20:00Z",
            "2026-10-14T11:24:00Z",
            sha(103),
            "failure",
        ),
        deploy_run(
            205,
            5,
            "workflow_dispatch",
            "2026-10-14T10:55:15Z",
            "2026-10-14T10:59:02Z",
            sha(103),
            "success",
        ),
        deploy_run(
            204,
            4,
            "workflow_dispatch",
            "2026-10-14T10:52:40Z",
            "2026-10-14T10:54:56Z",
            sha(103),
            "success",
        ),
        deploy_run(
            203, 3, "push", "2026-10-13T22:46:18Z", "2026-10-14T07:44:09Z", sha(103), "success"
        ),
        deploy_run(
            202, 2, "push", "2026-10-13T21:30:42Z", "2026-10-13T22:03:01Z", sha(102), "cancelled"
        ),
        deploy_run(
            201, 1, "push", "2026-10-13T21:28:22Z", "2026-10-14T07:39:27Z", sha(101), "failure"
        ),
    ]
    build_ok = {"name": "build", "conclusion": "success", "steps": []}
    build_skipped = {"name": "build", "conclusion": "skipped", "steps": []}
    return {
        f"{API}/actions/workflows/ci.yml/runs": {
            "total_count": 4,
            "workflow_runs": [
                ci_run(301, "success"),
                ci_run(302, "failure"),
                ci_run(303, "success"),
                ci_run(304, None, status="in_progress"),
            ],
        },
        # Out of order on purpose: the rows must come out sorted by start time.
        f"{API}/actions/runs/301/jobs": ci_jobs("2026-10-13T12:00:00Z", 80, 40),
        f"{API}/actions/runs/302/jobs": ci_jobs("2026-10-13T10:00:00Z", 60, 30),
        f"{API}/actions/runs/303/jobs": ci_jobs("2026-10-13T11:00:00Z", 100, 51),
        f"{API}/pulls": pulls,
        f"{API}/commits/{sha(13)}/check-runs": {
            "check_runs": [
                {"name": "ci", "conclusion": "success"},
                {"name": "evals", "conclusion": "failure"},
            ]
        },
        f"{API}/commits/{sha(14)}/check-runs": {
            "check_runs": [{"name": "evals", "conclusion": "success"}]
        },
        f"{API}/pulls/1/commits": [
            commit(1, f"Add the scorer\n\n{trailer}"),
            commit(2, f"Fix a typo by hand {FAKE_TOKEN}"),
        ],
        f"{API}/pulls/2/commits": [
            commit(2, f"Fix a typo by hand {FAKE_TOKEN}"),
            commit(3, f"Records\n\nco-authored-by: claude <{BOT_EMAIL}>"),
        ],
        f"{API}/rulesets": [{"id": RULESET_ID, "name": "main"}],
        f"{API}/rulesets/{RULESET_ID}": {
            "enforcement": "active",
            "bypass_actors": [],
            "rules": [
                {"type": "deletion", "parameters": None},
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [
                            {"context": "evals", "integration_id": 99999},
                            {"context": "ci", "integration_id": 99999},
                        ]
                    },
                },
            ],
        },
        f"{API}/code-scanning/default-setup": {
            "state": "configured",
            "languages": ["python", "actions"],
        },
        API: {
            "owner": {"login": "ranaidrees"},
            "security_and_analysis": {
                "secret_scanning": {"status": "enabled"},
                "secret_scanning_push_protection": {"status": "enabled"},
            },
        },
        f"{API}/actions/workflows/deploy.yml/runs": {"workflow_runs": deploy_runs},
        # Run 1: rejected by the owner, the deploy job never started its steps.
        f"{API}/actions/runs/201/jobs": {
            "jobs": [build_ok, {"name": "deploy", "conclusion": "failure", "steps": []}]
        },
        f"{API}/actions/runs/201/approvals": [owner("rejected")],
        f"{API}/commits/{sha(101)}/pulls": [pr1],
        # Run 2: cancelled while queued; no jobs, no approval, no pull request found.
        f"{API}/actions/runs/202/jobs": {"jobs": []},
        f"{API}/actions/runs/202/approvals": [],
        f"{API}/commits/{sha(102)}/pulls": [],
        # Run 3: the first deploy, a merge.
        f"{API}/actions/runs/203/jobs": {
            "jobs": [
                build_ok,
                {
                    "name": "deploy",
                    "conclusion": "success",
                    "steps": steps(
                        route="success",
                        provenance="success",
                        revision="success",
                        warm="skipped",
                        checkout="success",
                        smoke="success",
                    ),
                },
            ]
        },
        f"{API}/actions/runs/203/approvals": [owner("approved")],
        f"{API}/commits/{sha(103)}/pulls": [pr2],
        # Run 4: the warm route.
        f"{API}/actions/runs/204/jobs": {
            "jobs": [
                {
                    "name": "deploy",
                    "conclusion": "success",
                    "steps": steps(
                        route="success",
                        provenance="skipped",
                        revision="skipped",
                        warm="success",
                        checkout="skipped",
                        smoke="skipped",
                    ),
                },
                build_skipped,
            ]
        },
        f"{API}/actions/runs/204/approvals": [owner("approved")],
        # Run 5: the image_sha rollback route.
        f"{API}/actions/runs/205/jobs": {
            "jobs": [
                {
                    "name": "deploy",
                    "conclusion": "success",
                    "steps": steps(
                        route="success",
                        provenance="success",
                        revision="success",
                        warm="skipped",
                        checkout="success",
                        smoke="success",
                    ),
                },
                build_skipped,
            ]
        },
        f"{API}/actions/runs/205/approvals": [owner("approved")],
        # Run 6: the image_sha route again; the revision went live and the smoke test failed.
        f"{API}/actions/runs/206/jobs": {
            "jobs": [
                {
                    "name": "deploy",
                    "conclusion": "failure",
                    "steps": steps(
                        route="success",
                        provenance="success",
                        revision="success",
                        warm="skipped",
                        checkout="success",
                        smoke="failure",
                    ),
                },
                build_skipped,
            ]
        },
        f"{API}/actions/runs/206/approvals": [owner("approved")],
        # Run 7: waiting for the owner.
        f"{API}/actions/runs/207/jobs": {
            "jobs": [build_ok, {"name": "deploy", "conclusion": None, "steps": []}]
        },
        f"{API}/actions/runs/207/approvals": [],
        f"{API}/commits/{sha(107)}/pulls": [],
    }


DECISIONS = """# Decisions

- **owner**: a bullet line, not a table row.

| Date | ID | Decision | Reason | Who |
|---|---|---|---|---|
| 2026-10-12 | C1 | Model | Reason | owner |
| 2026-10-12 | C2 | Later | Reason | owner |
| 2026-10-13 | D1 | Hooks in Python | Windows | agent |
| 2026-10-13 | D2 | A `a | b` pipe inside a cell | Reason | agent |
| 2026-10-13 | S4a-8 | Label audit | Rule | rule |
| 2026-10-14 | P3-10 | Dashboard | Request | owner (the request), agent (the build and record) |

| Not | a | decision table |
|---|---|---|
| x | y | agent |
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small repository with the files the script reads."""
    root = tmp_path / "repo"
    (root / "intent").mkdir(parents=True)
    (root / "intent" / "decisions.md").write_text(DECISIONS, encoding="utf-8")
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        f"jobs:\n  ci:\n    steps:\n      - uses: {PINNED} # v7\n"
        "      - name: Scan the full history for secrets (gitleaks)\n        run: gitleaks git .\n",
        encoding="utf-8",
    )
    (workflows / "deploy.yml").write_text(
        f"jobs:\n  deploy:\n    steps:\n      - uses: {PINNED} # v7\n"
        "      - uses: docker/login-action@v4\n"
        "      - name: Verify build provenance\n        run: gh attestation verify oci://x\n",
        encoding="utf-8",
    )
    (root / ".github" / "dependabot.yml").write_text(
        "version: 2\nupdates:\n  - package-ecosystem: github-actions\n"
        "  - package-ecosystem: docker\n  - package-ecosystem: github-actions\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def calls(monkeypatch) -> list[list[str]]:
    """Replace the script's subprocess call with fakes of gh, git and pytest."""
    github = fake_github()
    seen: list[list[str]] = []

    def fake_run(args: list[str], cwd: Path = snap.ROOT) -> str:
        seen.append(list(args))
        if args[0] == "gh":
            endpoint = args[-1].split("?")[0]
            if endpoint not in github:
                raise snap.SnapshotError(f"{snap.describe(args)} failed with exit code 1")
            return json.dumps(github[endpoint])
        if args[0] == "git":
            return "2026-10-13T09:47:14+01:00\n2026-10-13T09:59:34+01:00\n"
        if args[0] == sys.executable:
            return "tests/unit/test_a.py: 40\ntests/hooks/test_b.py: 2\n"
        raise AssertionError(f"unexpected command {args[0]}")

    monkeypatch.setattr(snap, "run_command", fake_run)
    return seen


@pytest.fixture
def snapshot(repo, calls, capsys) -> dict:
    return snap.build_snapshot(repo, now=NOW)


def by_measure(rows: list[dict]) -> dict[str, dict]:
    return {row["measure"]: row for row in rows}


# --- schema ----------------------------------------------------------------------------


def test_the_snapshot_has_the_schema_of_spec_section_3(snapshot):
    assert list(snapshot) == [
        "generated_at",
        "repository",
        "before_production",
        "in_production",
        "ai_native_sdlc",
    ]
    assert snapshot["generated_at"] == "2026-10-14T15:30:00Z"
    assert snapshot["repository"] == "ranaidrees/answer-scorer"
    assert list(snapshot["before_production"]) == ["figures", "ci_runs", "gates"]
    assert list(snapshot["in_production"]) == ["figures", "deploys"]
    assert list(snapshot["ai_native_sdlc"]) == ["figures", "stages", "decisions_by_who"]

    for tab in ("before_production", "in_production", "ai_native_sdlc"):
        assert snapshot[tab]["figures"], tab
        for row in snapshot[tab]["figures"]:
            assert list(row) == ["measure", "value", "detail", "source"], row
            assert all(isinstance(value, str) and value for value in row.values()), row

    for row in snapshot["before_production"]["ci_runs"]:
        assert list(row) == ["started", "job_seconds", "test_seconds"]
        assert UTC_TIME.fullmatch(row["started"])
        assert isinstance(row["job_seconds"], int) and isinstance(row["test_seconds"], int)
    for row in snapshot["before_production"]["gates"]:
        assert list(row) == ["gate", "status", "source"]
        assert all(isinstance(value, str) and value for value in row.values())
    for row in snapshot["in_production"]["deploys"]:
        assert list(row) == [
            "started",
            "route",
            "commit",
            "approved_by_owner",
            "provenance_verified",
            "smoke_test",
            "result",
            "source",
        ]
        assert UTC_TIME.fullmatch(row["started"])
        assert re.fullmatch(r"[0-9a-f]{7}", row["commit"])
        assert re.fullmatch(rf"{REPO_URL}/actions/runs/\d+", row["source"])
    assert [row["stage"] for row in snapshot["ai_native_sdlc"]["stages"]] == [
        "Plan",
        "Design",
        "Build",
        "Test",
        "Deploy",
        "Maintain",
    ]
    for row in snapshot["ai_native_sdlc"]["stages"]:
        assert list(row) == ["stage", "artifact", "gate", "source"]
        assert "who decides" in row["gate"]
    for row in snapshot["ai_native_sdlc"]["decisions_by_who"]:
        assert list(row) == ["who", "decisions"]
        assert isinstance(row["decisions"], int)


def test_every_source_is_a_link_into_this_repository(snapshot):
    text = snap.render(snapshot)
    sources = re.findall(r'"source": "([^"]*)"', text)
    assert len(sources) > 30
    for source in sources:
        assert source.startswith(REPO_URL), source
    for url in re.findall(r"https?://[^\s\"]+", text):
        assert url.startswith(REPO_URL), url


def test_the_file_is_deterministic_indented_and_ends_with_a_newline(repo, calls):
    first = snap.render(snap.build_snapshot(repo, now=NOW))
    second = snap.render(snap.build_snapshot(repo, now=NOW))
    assert first == second
    assert first.endswith("}\n")
    assert first == json.dumps(json.loads(first), indent=2, ensure_ascii=False) + "\n"
    assert chr(0x2014) not in first and chr(0x2013) not in first


# --- before production -----------------------------------------------------------------


def test_ci_rows_are_sorted_and_the_medians_and_passed_count_are_right(snapshot):
    rows = snapshot["before_production"]["ci_runs"]
    assert rows == [
        {"started": "2026-10-13T10:00:00Z", "job_seconds": 60, "test_seconds": 30},
        {"started": "2026-10-13T11:00:00Z", "job_seconds": 100, "test_seconds": 51},
        {"started": "2026-10-13T12:00:00Z", "job_seconds": 80, "test_seconds": 40},
    ]
    figures = by_measure(snapshot["before_production"]["figures"])
    assert figures["ci runs passed"]["value"] == "2 of 3"  # the run in progress is left out
    assert figures["Median ci job time"]["value"] == "80 s"
    assert figures["Median test step time"]["value"] == "40 s"
    assert figures["Tests passing"]["value"] == "42"


def test_the_median_of_an_even_count_keeps_its_half_second():
    assert snap.median_text([30, 41]) == "35.5 s"
    assert snap.median_text([]) == "no runs"


def test_pull_requests_merged_and_the_one_the_eval_gate_blocks(snapshot):
    figures = by_measure(snapshot["before_production"]["figures"])
    assert figures["Pull requests merged"]["value"] == "2"
    blocked = figures["Blocked by the eval gate"]
    assert blocked["value"] == "#3"  # #4 is open but its evals check passed
    assert blocked["source"] == f"{REPO_URL}/pull/3"


def test_recorded_figures_carry_their_source_files(snapshot):
    figures = by_measure(snapshot["before_production"]["figures"])
    assert figures["Eval gate stability proof"]["value"] == "3 PASS, 3 FAIL"
    assert "S4c-11" in figures["Eval gate stability proof"]["detail"]
    assert figures["Kappa of the three proof runs"]["value"] == "0.926, 0.947, 0.926"
    assert figures["Injection cases flagged and routed"]["value"] == "18 of 18"
    assert figures["Label audit agreement"]["value"] == "30 of 30"
    assert figures["Label audit agreement"]["source"].endswith("evals/label_audit.md")
    for row in snap.RECORDED_FIGURES:
        assert row["source"].startswith(f"{REPO_URL}/blob/main/"), row["key"]


def test_the_gates_table(snapshot):
    gates = {row["gate"]: row["status"] for row in snapshot["before_production"]["gates"]}
    assert gates["Actions pinned to a full commit SHA"] == "2 of 3"
    assert (
        gates["Ruleset on main: required checks, empty bypass list"]
        == "active; required checks ci, evals; bypass list empty"
    )
    assert gates["CodeQL default setup"] == "configured; actions, python"
    assert gates["Secret scan of the full history in ci (gitleaks)"] == "present"
    assert gates["Secret scanning with push protection"] == (
        "secret scanning enabled; push protection enabled"
    )
    assert gates["Dependabot version updates"] == "github-actions, docker"
    assert gates["Signed build provenance verified before every image deploy"] == "yes"


def test_a_setting_that_cannot_be_read_says_so(repo, calls, monkeypatch):
    github_run = snap.run_command

    def refuse_security_reads(args, cwd=snap.ROOT):
        if args[0] == "gh" and ("code-scanning" in args[-1] or "rulesets" in args[-1]):
            raise snap.SnapshotError(f"{snap.describe(args)} failed with exit code 1")
        return github_run(args, cwd)

    monkeypatch.setattr(snap, "run_command", refuse_security_reads)
    gates = {
        row["gate"]: row["status"]
        for row in snap.build_snapshot(repo, now=NOW)["before_production"]["gates"]
    }
    assert gates["CodeQL default setup"] == "not readable"
    assert gates["Ruleset on main: required checks, empty bypass list"] == "not readable"


# --- in production ---------------------------------------------------------------------


def test_one_deploy_row_per_run_oldest_first_with_routes_and_results(snapshot):
    rows = snapshot["in_production"]["deploys"]
    assert [row["source"].rsplit("/", 1)[1] for row in rows] == [
        "201",
        "202",
        "203",
        "204",
        "205",
        "206",
        "207",
    ]
    assert [row["route"] for row in rows] == [
        "merge of #1",
        "push to main",
        "merge of #2",
        "warm (min replicas 1)",
        "rollback route (image_sha)",
        "rollback route (image_sha)",
        "push to main",
    ]
    assert [row["result"] for row in rows] == [
        "failure",
        "cancelled",
        "success",
        "success",
        "success",
        "failure",
        "waiting",
    ]
    assert rows[2]["commit"] == sha(103)[:7]


def test_the_approval_column_reads_approved_rejected_and_not_reached(snapshot):
    rows = snapshot["in_production"]["deploys"]
    assert [row["approved_by_owner"] for row in rows] == [
        "rejected by owner",
        "not reached",
        "yes",
        "yes",
        "yes",
        "yes",
        "not reached",
    ]


def test_provenance_and_smoke_columns_come_from_the_deploy_job_steps(snapshot):
    rows = snapshot["in_production"]["deploys"]
    assert [row["provenance_verified"] for row in rows] == [
        "not run",
        "not run",
        "passed",
        "skipped",
        "passed",
        "passed",
        "not run",
    ]
    # "Check out (for the smoke test)" succeeded in run 6; the smoke test itself failed.
    assert [row["smoke_test"] for row in rows] == [
        "not run",
        "not run",
        "passed",
        "skipped",
        "passed",
        "failed",
        "not run",
    ]


def test_production_figures(snapshot):
    figures = by_measure(snapshot["in_production"]["figures"])
    approved = figures["Deploy runs approved by the owner"]
    assert approved["value"] == "4 of 5"
    assert "rejected by the owner: 1" in approved["detail"]
    assert "waiting for approval: 1" in approved["detail"]
    # Runs 3 to 6 changed the app; run 6's smoke test then failed.
    assert figures["Change failure rate"]["value"] == "1 of 4"
    # #2 merged at 22:46:15, its deploy run finished at 07:44:09 the next day.
    assert figures["Time from merge to production"]["value"] == "8 h 58 min"
    assert figures["Time from merge to production"]["source"] == f"{REPO_URL}/actions/runs/203"
    assert figures["Rollback route proven"]["value"] == "yes"
    assert figures["Rollback route proven"]["source"] == f"{REPO_URL}/actions/runs/205"
    assert figures["Azure spend estimate"]["value"] == "about 7.0 GBP of 10 GBP"


# --- AI-native SDLC --------------------------------------------------------------------


def test_decisions_are_counted_by_who_with_a_shared_row():
    assert snap.count_decisions(DECISIONS) == {"agent": 2, "owner": 2, "rule": 1, "shared": 1}


def test_commits_are_counted_once_and_by_the_co_author_line(snapshot):
    figures = by_measure(snapshot["ai_native_sdlc"]["figures"])
    # Commit 2 is on both branches and is counted once; 1 and 3 carry the line.
    assert figures["Commits with the agent's co-author line"]["value"] == "2 of 3"


def test_sdlc_figures_and_decisions_table(snapshot):
    sdlc = snapshot["ai_native_sdlc"]
    assert sdlc["decisions_by_who"] == [
        {"who": "agent", "decisions": 2},
        {"who": "owner", "decisions": 2},
        {"who": "rule", "decisions": 1},
        {"who": "shared", "decisions": 1},
    ]
    figures = by_measure(sdlc["figures"])
    assert figures["Decisions made by the owner"]["value"] == "2 of 6"
    assert figures["Deploy approvals by the owner"]["value"] == "4"
    assert figures["Verifier FAIL verdicts before merge"]["value"] == "12"
    assert figures["Important review findings, all fixed"]["value"] == "15"
    # First commit 08:47:14 UTC on the 13th; first successful deploy finished 07:44:09 next day.
    assert figures["First commit to first deploy"]["value"] == "22 h 57 min"


# --- what the script reads and what it lets out ----------------------------------------


def test_every_github_call_is_a_read_only_get_through_gh(snapshot, calls):
    gh_calls = [args for args in calls if args[0] == "gh"]
    assert gh_calls
    for args in gh_calls:
        assert args[:4] == ["gh", "api", "--method", "GET"], args
        assert len(args) == 5 and args[4].startswith(API)
    assert ["git", "log", "--reverse", "--format=%cI", "main"] in calls
    assert [sys.executable, "-m", "pytest", "--collect-only", "-q"] in calls


def leaks(text: str) -> list[str]:
    found = []
    if EMAIL.search(text):
        found.append("email address")
    if TOKEN.search(text):
        found.append("token")
    if AUTHOR_NAME in text or "jane-example" in text:
        found.append("author")
    if str(RULESET_ID) in text:
        found.append("ruleset id")
    if "ranaidrees" in text.replace(REPO_URL, "").replace("ranaidrees/answer-scorer", ""):
        found.append("login")
    return found


def test_the_console_and_the_file_hold_no_token_email_author_or_login(
    repo, calls, monkeypatch, capsys
):
    monkeypatch.setattr(snap, "ROOT", repo)
    assert snap.main([]) == 0
    printed = capsys.readouterr()
    written = (repo / "dashboards" / "sdlc_snapshot.json").read_text(encoding="utf-8")

    assert leaks(printed.out + printed.err) == []
    assert leaks(written) == []
    assert printed.out.strip().splitlines()[-1] == "Wrote dashboards/sdlc_snapshot.json"
    assert str(repo) not in printed.out
    # The only long numbers in the file are run numbers inside run links.
    without_run_links = re.sub(rf"{REPO_URL}/actions/runs/\d+", "", written)
    assert not re.search(r"\d{6,}", without_run_links)
    assert b"\r\n" not in (repo / "dashboards" / "sdlc_snapshot.json").read_bytes()


def test_a_failed_command_names_the_call_but_never_its_output(tmp_path):
    # A stand-in for gh answering with an error body: the secrets are in its output only.
    (tmp_path / "fail.py").write_text(
        "import sys\n"
        f"sys.stdout.write('body {AUTHOR_EMAIL}')\n"
        f"sys.stderr.write('Bad credentials {FAKE_TOKEN}')\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )
    with pytest.raises(snap.SnapshotError) as caught:
        snap.run_command([sys.executable, "fail.py"], cwd=tmp_path)
    assert str(caught.value) == "python fail.py failed with exit code 3"
    assert leaks(str(caught.value)) == []


def test_an_error_stops_the_run_without_writing_or_leaking(repo, calls, monkeypatch, capsys):
    def failing(args, cwd=snap.ROOT):
        raise snap.SnapshotError(
            snap.describe(["gh", "api", f"{API}/actions/runs/38552626830/jobs"])
        )

    monkeypatch.setattr(snap, "ROOT", repo)
    monkeypatch.setattr(snap, "run_command", failing)
    assert snap.main([]) == 1
    printed = capsys.readouterr()
    assert "38552626830" not in printed.out + printed.err
    assert not (repo / "dashboards" / "sdlc_snapshot.json").exists()


def test_the_public_check_refuses_an_email_a_token_or_a_foreign_link():
    snap.check_public(f'{{"source": "{REPO_URL}/pull/1"}}')
    for bad in (
        AUTHOR_EMAIL,
        FAKE_TOKEN,
        "https://example.com/x",
        "https://github.com/ranaidrees/other-repo",
        "HTTPS://example.com/x",
        f"{REPO_URL}/../../other/repo",
        "app.example." + "azurecontainerapps" + ".io",
        "someone" + "%" + "40example.invalid",
        "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0",
    ):
        with pytest.raises(snap.SnapshotError):
            snap.check_public(f'{{"detail": "{bad}"}}')


def test_the_committed_snapshot_and_workbook_pass_the_public_check():
    # The workbook is public in the repository; the same guard covers both committed files.
    schema = "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json"
    for relative in ("dashboards/sdlc_snapshot.json", "infra/sdlc_workbook.json"):
        path = snap.ROOT / relative
        if not path.exists():
            pytest.skip(f"{relative} not generated yet")
        text = path.read_text(encoding="utf-8")
        if relative.startswith("infra/"):
            # The schema address and Learn links are the only other links the workbook may hold.
            text = text.replace(schema, "")
            text = re.sub(r"https://learn\.microsoft\.com/[^\s\")]+", "", text)
        snap.check_public(text)
