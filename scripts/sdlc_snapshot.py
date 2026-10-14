"""Delivery evidence snapshot for the S9 workbook.

    uv run python scripts/sdlc_snapshot.py

Reads GitHub through the signed-in `gh` CLI, with read-only `gh api --method GET` calls
only, and reads this repository: git, `intent/decisions.md`, the workflow files, the
Dependabot file and pytest's test collection. Writes `dashboards/sdlc_snapshot.json` in
the schema of `intent/s9-delivery-evidence/spec.md` section 3, with the figures of its
section 4.

Prints short progress lines and the output path only: never a token, an email address,
a commit author, an error body from GitHub, or an ID other than run numbers in URLs.
Every link written to the file points at this repository, and the file is checked for
that before it is written. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("dashboards") / "sdlc_snapshot.json"
REPOSITORY = "ranaidrees/answer-scorer"
OWNER = REPOSITORY.split("/")[0]
REPO_URL = f"https://github.com/{REPOSITORY}"
API = f"repos/{REPOSITORY}"
PER_PAGE = 100
MAX_PAGES = 10

CI_JOB = "ci"
TEST_STEP_PREFIX = "Lint, format check and tests"
EVALS_CHECK = "evals"
# Step names of the deploy job in .github/workflows/deploy.yml. The warm route runs the
# first; the image_sha route skips the build job and runs the provenance check; a step
# that starts with one of CHANGE_STEPS and succeeds has changed the running app.
WARM_STEP = "Keep one replica warm"
PROVENANCE_WORD = "provenance"
SMOKE_WORD = "smoke"
CHANGE_STEPS = ("Create a revision", WARM_STEP)
STEP_RESULTS = {"success": "passed", "failure": "failed", "skipped": "skipped"}
CO_AUTHOR = re.compile(r"co-authored-by:\s*claude", re.IGNORECASE)
WHO_VALUES = ("agent", "owner", "rule", "shared")

EMAIL = re.compile(r"[\w.+-]+(?:@|%40)[\w-]+\.[\w.-]+", re.IGNORECASE)
TOKEN = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|eyJ[\w-]{10,}\.[\w-]{10,})")
AZURE_HOST = re.compile(
    r"azurecontainerapps\.io|applicationinsights\.azure\.com|instrumentationkey|/subscriptions/",
    re.IGNORECASE,
)
URL = re.compile(r"https?://[^\s\"]+", re.IGNORECASE)
SHA40 = re.compile(r"[0-9a-f]{40}")


def blob(path: str) -> str:
    return f"{REPO_URL}/blob/main/{path}"


# Figures that come from the records, not from an API. Each names the file it was taken
# from; change one only when that file changes.
RECORDED_FIGURES: tuple[dict[str, str], ...] = (
    {
        "key": "stability_proof",
        "measure": "Eval gate stability proof",
        "value": "3 PASS, 3 FAIL",
        "detail": "accepted prompt v1: 3 PASS in a row; weakened prompt v0-weak: 3 FAIL in a row (decision S4c-11)",
        "source": blob("intent/decisions.md"),
    },
    {
        "key": "kappa",
        "measure": "Kappa of the three proof runs",
        "value": "0.926, 0.947, 0.926",
        "detail": "quadratic weighted kappa against the labels, n=30, gate at least 0.70, accepted prompt v1",
        "source": blob("docs/eval_card.md"),
    },
    {
        "key": "injection",
        "measure": "Injection cases flagged and routed",
        "value": "18 of 18",
        "detail": "in every run of the stability proof; gate 100%",
        "source": blob("docs/eval_card.md"),
    },
    {
        "key": "label_audit",
        "measure": "Label audit agreement",
        "value": "30 of 30",
        "detail": "between two Claude agents, one of them blind; no person labelled or reviewed the answers",
        "source": blob("evals/label_audit.md"),
    },
    {
        "key": "spend",
        "measure": "Azure spend estimate",
        "value": "about 7.0 GBP of 10 GBP",
        "detail": "estimate from token counts on 14 October 2026, because Azure's own figures lag",
        "source": blob("intent/plan.md"),
    },
    {
        "key": "verifier",
        "measure": "Verifier FAIL verdicts before merge",
        "value": "12",
        "detail": "6 up to #16, 4 on the Phase 3 records and 2 on the dashboard and LLMOps branch, each corrected before merge",
        "source": blob("README.md#results-scoreboard"),
    },
    {
        "key": "review_findings",
        "measure": "Important review findings, all fixed",
        "value": "15",
        "detail": "found by the in-session reviews before merge; the fixes for the S4b and S5a ones were merged with #13",
        "source": blob("README.md#results-scoreboard"),
    },
)

# The stages of intent/spec.md section 10, with the artifact each one commits, the gate
# that decides and who decides.
STAGES: tuple[dict[str, str], ...] = (
    {
        "stage": "Plan",
        "artifact": "intent/intent.md",
        "gate": "the owner wrote it and committed it first (who decides: owner)",
        "source": blob("intent/intent.md"),
    },
    {
        "stage": "Design",
        "artifact": "intent/spec.md and rubrics/*.yaml",
        "gate": "validation session under the owner's delegation, independent rubric check (D23) and the CI Claude review; the owner's final acceptance is still to come (who decides: agent and rule, under the owner's delegation)",
        "source": blob("intent/spec.md"),
    },
    {
        "stage": "Build",
        "artifact": "intent/plan.md slice sections, code and tests",
        "gate": "slice sections built as written, with no separate plan pull request (D12); verifier PASS and ci green (who decides: agent and rule)",
        "source": blob("intent/plan.md"),
    },
    {
        "stage": "Test",
        "artifact": "eval reports, label audit and stability proof",
        "gate": "eval gate at the spec's thresholds or stricter; loosening needs the owner (who decides: rule)",
        "source": blob("docs/eval_card.md"),
    },
    {
        "stage": "Deploy",
        "artifact": "pull request with AI review findings, and the GitHub deployment record",
        "gate": "required checks before merge; the owner approves every production deploy (who decides: owner)",
        "source": blob(".github/workflows/deploy.yml"),
    },
    {
        "stage": "Maintain",
        "artifact": "nightly eval run; the Maintain loop is Later",
        "gate": "a GitHub notification to the owner (who decides: owner)",
        "source": blob(".github/workflows/evals.yml"),
    },
)


class SnapshotError(RuntimeError):
    """A read failed. The message names the call, never what it returned."""


# --- reading ---------------------------------------------------------------------------


def describe(args: list[str]) -> str:
    """A command for an error message: no interpreter path, no ID, no commit SHA."""
    words = ["python" if arg == sys.executable else arg for arg in args]
    text = " ".join(words)
    text = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", text)
    return re.sub(r"\b\d{3,}\b", "<n>", text)


def run_command(args: list[str], cwd: Path = ROOT) -> str:
    """Run one command and return its standard output. The script's only subprocess call.

    Standard error is captured and dropped, so an error body from GitHub never reaches
    the console; a non-zero exit raises SnapshotError naming the command only.
    """
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        raise SnapshotError(f"{describe(args)} could not be started") from None
    if completed.returncode != 0:
        raise SnapshotError(f"{describe(args)} failed with exit code {completed.returncode}")
    return completed.stdout


def gh_api(endpoint: str) -> Any:
    """One read-only GET on the GitHub API through the signed-in gh CLI."""
    output = run_command(["gh", "api", "--method", "GET", endpoint])
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        raise SnapshotError(f"{describe(['gh', 'api', endpoint])} returned no JSON") from None


def gh_pages(endpoint: str, key: str | None = None) -> list[dict]:
    """Every item of a paged list endpoint (at most MAX_PAGES pages of PER_PAGE)."""
    items: list[dict] = []
    joiner = "&" if "?" in endpoint else "?"
    for page in range(1, MAX_PAGES + 1):
        body = gh_api(f"{endpoint}{joiner}per_page={PER_PAGE}&page={page}")
        batch = body.get(key, []) if key else body
        items.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return items


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def seconds_between(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    return int((parse_time(end) - parse_time(start)).total_seconds())


def hours_minutes(start: datetime, end: datetime) -> str:
    minutes = round((end - start).total_seconds() / 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def median_text(values: list[int]) -> str:
    if not values:
        return "no runs"
    return f"{statistics.median(values):g} s"


def figure(measure: str, value: Any, detail: str, source: str) -> dict[str, str]:
    return {"measure": measure, "value": str(value), "detail": detail, "source": source}


def recorded(key: str) -> dict[str, str]:
    row = next(row for row in RECORDED_FIGURES if row["key"] == key)
    return figure(row["measure"], row["value"], row["detail"], row["source"])


def find_job(jobs: list[dict], name: str) -> dict | None:
    return next((job for job in jobs if job.get("name") == name), None)


# --- before production -----------------------------------------------------------------


def read_ci_runs() -> tuple[list[dict], int, int]:
    """One row per completed ci run with a ci job and a test step; completed and passed counts."""
    runs = gh_pages(f"{API}/actions/workflows/ci.yml/runs", key="workflow_runs")
    completed = [run for run in runs if run.get("status") == "completed"]
    passed = sum(1 for run in completed if run.get("conclusion") == "success")
    rows = []
    for run in completed:
        jobs = gh_api(f"{API}/actions/runs/{int(run['id'])}/jobs").get("jobs", [])
        job = find_job(jobs, CI_JOB)
        if job is None:
            continue
        step = next(
            (s for s in job.get("steps") or [] if s.get("name", "").startswith(TEST_STEP_PREFIX)),
            None,
        )
        job_seconds = seconds_between(job.get("started_at"), job.get("completed_at"))
        test_seconds = step and seconds_between(step.get("started_at"), step.get("completed_at"))
        if job_seconds is None or test_seconds is None:
            continue
        rows.append(
            {
                "started": utc_text(parse_time(job["started_at"])),
                "job_seconds": job_seconds,
                "test_seconds": test_seconds,
            }
        )
    rows.sort(key=lambda row: row["started"])
    return rows, len(completed), passed


def blocked_by_eval_gate(pulls: list[dict]) -> list[int]:
    """Open pull requests whose head commit has a failed evals check run."""
    blocked = []
    for pull in sorted(pulls, key=lambda p: int(p["number"])):
        if pull.get("state") != "open":
            continue
        sha = (pull.get("head") or {}).get("sha", "")
        if not SHA40.fullmatch(sha):
            raise SnapshotError("a pull request head is not a commit SHA; nothing written")
        checks = gh_api(f"{API}/commits/{sha}/check-runs?per_page={PER_PAGE}")
        if any(
            check.get("name") == EVALS_CHECK and check.get("conclusion") == "failure"
            for check in checks.get("check_runs", [])
        ):
            blocked.append(int(pull["number"]))
    return blocked


def count_tests(root: Path) -> int:
    output = run_command([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=root)
    summary = re.search(r"(\d+) tests? collected", output)
    if summary:
        return int(summary.group(1))
    per_file = re.findall(r"^\S+\.py: (\d+)\s*$", output, re.MULTILINE)
    if not per_file:
        raise SnapshotError("pytest --collect-only reported no tests")
    return sum(int(count) for count in per_file)


USES = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^\s'\"#]+)", re.MULTILINE)


def pinned_actions(root: Path) -> tuple[int, int]:
    folder = root / ".github" / "workflows"
    refs: list[str] = []
    for path in sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")]):
        refs.extend(USES.findall(read_text(path)))
    pinned = sum(1 for ref in refs if re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", ref))
    return pinned, len(refs)


def ruleset_status() -> str:
    try:
        rulesets = gh_api(f"{API}/rulesets")
        main = next((r for r in rulesets if r.get("name") == "main"), None)
        if main is None:
            return "no ruleset named main"
        detail = gh_api(f"{API}/rulesets/{int(main['id'])}")
    except SnapshotError:
        return "not readable"
    contexts = sorted(
        {
            check.get("context", "")
            for rule in detail.get("rules") or []
            if rule.get("type") == "required_status_checks"
            for check in (rule.get("parameters") or {}).get("required_status_checks") or []
        }
    )
    bypass = detail.get("bypass_actors")
    if bypass is None:
        bypass_text = "bypass list not readable"
    elif not bypass:
        bypass_text = "bypass list empty"
    else:
        bypass_text = f"{len(bypass)} on the bypass list"
    required = ", ".join(contexts) or "none"
    return f"{detail.get('enforcement', 'unknown')}; required checks {required}; {bypass_text}"


def codeql_status() -> str:
    try:
        setup = gh_api(f"{API}/code-scanning/default-setup")
    except SnapshotError:
        return "not readable"
    languages = ", ".join(sorted(setup.get("languages") or []))
    state = setup.get("state") or "unknown"
    return f"{state}; {languages}" if languages else state


def secret_scanning_status() -> str:
    try:
        repo = gh_api(API)
    except SnapshotError:
        return "not readable"
    security = repo.get("security_and_analysis") or {}
    scanning = (security.get("secret_scanning") or {}).get("status")
    push = (security.get("secret_scanning_push_protection") or {}).get("status")
    if not scanning or not push:
        return "not readable"
    return f"secret scanning {scanning}; push protection {push}"


def dependabot_ecosystems(root: Path) -> list[str]:
    found = re.findall(
        r"package-ecosystem:\s*['\"]?([\w-]+)", read_text(root / ".github" / "dependabot.yml")
    )
    return list(dict.fromkeys(found))


def gate_rows(root: Path) -> list[dict[str, str]]:
    pinned, uses = pinned_actions(root)
    workflows = root / ".github" / "workflows"
    gitleaks = "gitleaks" in read_text(workflows / "ci.yml").lower()
    verified = "gh attestation verify" in read_text(workflows / "deploy.yml")
    ecosystems = dependabot_ecosystems(root)
    return [
        {
            "gate": "Actions pinned to a full commit SHA",
            "status": f"{pinned} of {uses}",
            "source": f"{REPO_URL}/tree/main/.github/workflows",
        },
        {
            "gate": "Ruleset on main: required checks, empty bypass list",
            "status": ruleset_status(),
            "source": f"{REPO_URL}/rules",
        },
        {
            "gate": "CodeQL default setup",
            "status": codeql_status(),
            "source": f"{REPO_URL}/actions/workflows/github-code-scanning/codeql",
        },
        {
            "gate": "Secret scan of the full history in ci (gitleaks)",
            "status": "present" if gitleaks else "missing",
            "source": blob(".github/workflows/ci.yml"),
        },
        {
            "gate": "Secret scanning with push protection",
            "status": secret_scanning_status(),
            "source": f"{REPO_URL}/security",
        },
        {
            "gate": "Dependabot version updates",
            "status": ", ".join(ecosystems) or "none",
            "source": blob(".github/dependabot.yml"),
        },
        {
            "gate": "Signed build provenance verified before every deploy",
            "status": "yes" if verified else "no",
            "source": blob(".github/workflows/deploy.yml"),
        },
    ]


# --- in production ---------------------------------------------------------------------


@dataclass
class Deploy:
    run: dict
    jobs: list[dict]
    approvals: list[dict]
    pull: dict | None
    row: dict[str, str]


def is_owner(approval: dict) -> bool:
    return str((approval.get("user") or {}).get("login", "")).lower() == OWNER.lower()


def approval_value(approvals: list[dict]) -> str:
    states = {approval.get("state") for approval in approvals if is_owner(approval)}
    if "approved" in states:
        return "yes"
    if "rejected" in states:
        return "rejected by owner"
    if approvals:
        return "decided by another reviewer"
    return "not reached"


def step_conclusion(job: dict | None, word: str) -> str | None:
    """The conclusion of the job's step whose name holds the word, leaving out check-outs."""
    for step in (job or {}).get("steps") or []:
        name = step.get("name", "").lower()
        if word.lower() in name and not name.startswith(("check out", "post ")):
            return step.get("conclusion")
    return None


def step_result(job: dict | None, word: str) -> str:
    return STEP_RESULTS.get(step_conclusion(job, word) or "", "not run")


def ran(conclusion: str | None) -> bool:
    return conclusion in ("success", "failure")


def deploy_route(run: dict, jobs: list[dict], pull: dict | None) -> str:
    event = run.get("event")
    if event == "push":
        return f"merge of #{int(pull['number'])}" if pull else "push to main"
    if event != "workflow_dispatch":
        return str(event)
    deploy, build = find_job(jobs, "deploy"), find_job(jobs, "build")
    build_ran = build is not None and ran(build.get("conclusion"))
    if ran(step_conclusion(deploy, WARM_STEP)):
        return "warm (min replicas 1)"
    if not build_ran and ran(step_conclusion(deploy, PROVENANCE_WORD)):
        return "rollback route (image_sha)"
    if build_ran:
        return "manual build"
    return "manual run"


def run_result(run: dict) -> str:
    if run.get("status") == "completed":
        return run.get("conclusion") or "unknown"
    return run.get("status") or "unknown"


def merged_pull(sha: str) -> dict | None:
    pulls = gh_api(f"{API}/commits/{sha}/pulls")
    for pull in pulls:
        if pull.get("merge_commit_sha") == sha and pull.get("merged_at"):
            return pull
    return next((pull for pull in pulls if pull.get("merged_at")), None)


def read_deploys() -> list[Deploy]:
    runs = gh_pages(f"{API}/actions/workflows/deploy.yml/runs", key="workflow_runs")
    runs.sort(key=lambda run: (run.get("run_started_at") or "", int(run.get("run_number", 0))))
    deploys = []
    for run in runs:
        run_id = int(run["id"])
        jobs = gh_api(f"{API}/actions/runs/{run_id}/jobs").get("jobs", [])
        approvals = gh_api(f"{API}/actions/runs/{run_id}/approvals")
        sha = str(run.get("head_sha", ""))
        pull = merged_pull(sha) if run.get("event") == "push" and SHA40.fullmatch(sha) else None
        deploy_job = find_job(jobs, "deploy")
        row = {
            "started": utc_text(parse_time(run["run_started_at"])),
            "route": deploy_route(run, jobs, pull),
            "commit": sha[:7],
            "approved_by_owner": approval_value(approvals),
            "provenance_verified": step_result(deploy_job, PROVENANCE_WORD),
            "smoke_test": step_result(deploy_job, SMOKE_WORD),
            "result": run_result(run),
            "source": f"{REPO_URL}/actions/runs/{run_id}",
        }
        deploys.append(Deploy(run, jobs, approvals, pull, row))
    return deploys


def changed_the_app(deploy: Deploy) -> bool:
    job = find_job(deploy.jobs, "deploy")
    return any(
        step.get("name", "").startswith(CHANGE_STEPS) and step.get("conclusion") == "success"
        for step in (job or {}).get("steps") or []
    )


def production_figures(deploys: list[Deploy]) -> list[dict[str, str]]:
    deploy_runs = f"{REPO_URL}/actions/workflows/deploy.yml"
    decided = [d for d in deploys if d.approvals]
    approved = [d for d in deploys if d.row["approved_by_owner"] == "yes"]
    rejected = [d for d in deploys if d.row["approved_by_owner"] == "rejected by owner"]
    waiting = [d for d in deploys if d.row["result"] == "waiting"]
    changed = [d for d in deploys if changed_the_app(d)]
    failed_after = [d for d in changed if d.row["smoke_test"] == "failed"]

    first = next((d for d in deploys if d.row["result"] == "success" and d.pull is not None), None)
    if first is not None:
        lead_time = hours_minutes(
            parse_time(first.pull["merged_at"]), parse_time(first.run["updated_at"])
        )
        lead_detail = (
            f"#{int(first.pull['number'])} merged to its deploy run finishing, for the first "
            "successful deploy; includes the wait for the owner's approval"
        )
        lead_source = first.row["source"]
    else:
        lead_time, lead_detail, lead_source = "no deploy yet", "no successful deploy", deploy_runs

    rollback = next(
        (
            d
            for d in deploys
            if d.row["route"] == "rollback route (image_sha)" and d.row["result"] == "success"
        ),
        None,
    )
    return [
        figure(
            "Deploy runs approved by the owner",
            f"{len(approved)} of {len(decided)}",
            f"of the runs that reached the owner's decision; rejected by the owner: "
            f"{len(rejected)}; waiting for approval: {len(waiting)}",
            deploy_runs,
        ),
        figure(
            "Change failure rate",
            f"{len(failed_after)} of {len(changed)}",
            "deploys that changed the app and whose smoke test then failed, of all deploys "
            "that changed the app",
            deploy_runs,
        ),
        figure("Time from merge to production", lead_time, lead_detail, lead_source),
        figure(
            "Rollback route proven",
            "yes" if rollback else "no",
            "a successful image_sha run: an earlier image redeployed by its commit SHA"
            if rollback
            else "no successful image_sha run yet",
            rollback.row["source"] if rollback else deploy_runs,
        ),
        recorded("spend"),
    ]


# --- AI-native SDLC --------------------------------------------------------------------


def count_decisions(text: str) -> dict[str, int]:
    """Rows of the decision tables by their Who cell: agent, owner, rule, or shared."""
    counts = dict.fromkeys(WHO_VALUES, 0)
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            in_table = False
            continue
        who = line.strip("|").split("|")[-1].strip()
        if who.lower() == "who":
            in_table = True
            continue
        if not in_table or set(who) <= set("-: "):
            continue
        counts[who if who in ("agent", "owner", "rule") else "shared"] += 1
    return counts


def co_authored_commits(merged: list[dict]) -> tuple[int, int]:
    """Commits on merged pull request branches, counted once each: co-authored, all."""
    seen: dict[str, bool] = {}
    for pull in merged:
        for commit in gh_pages(f"{API}/pulls/{int(pull['number'])}/commits"):
            sha = commit.get("sha")
            if sha and sha not in seen:
                message = (commit.get("commit") or {}).get("message") or ""
                seen[sha] = bool(CO_AUTHOR.search(message))
    return sum(seen.values()), len(seen)


def first_commit_time(root: Path) -> datetime:
    output = run_command(["git", "log", "--reverse", "--format=%cI", "main"], cwd=root)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise SnapshotError("git log found no commit on main")
    return datetime.fromisoformat(lines[0]).astimezone(UTC)


# --- the snapshot ----------------------------------------------------------------------


def build_snapshot(root: Path, now: datetime | None = None) -> dict:
    generated = now or datetime.now(UTC)

    print("Reading ci runs")
    ci_rows, ci_completed, ci_passed = read_ci_runs()
    print("Reading pull requests")
    pulls = gh_pages(f"{API}/pulls?state=all")
    merged = sorted((p for p in pulls if p.get("merged_at")), key=lambda p: int(p["number"]))
    blocked = blocked_by_eval_gate(pulls)
    print("Reading the gates")
    gates = gate_rows(root)
    print("Reading deploy runs")
    deploys = read_deploys()
    print("Reading commits of merged pull requests")
    co_authored, commits = co_authored_commits(merged)
    print("Counting tests")
    tests = count_tests(root)
    decisions = count_decisions(read_text(root / "intent" / "decisions.md"))
    started = first_commit_time(root)

    ci_page = f"{REPO_URL}/actions/workflows/ci.yml"
    merged_page = f"{REPO_URL}/pulls?q=is%3Apr+is%3Amerged"
    if len(blocked) == 1:
        blocked_source = f"{REPO_URL}/pull/{blocked[0]}"
    else:
        blocked_source = f"{REPO_URL}/pulls?q=is%3Apr+is%3Aopen"
    before_figures = [
        figure(
            "Tests passing",
            tests,
            "unit and hook tests collected by pytest; every pull request must pass them all in ci",
            ci_page,
        ),
        figure(
            "ci runs passed",
            f"{ci_passed} of {ci_completed}",
            "completed runs of the ci workflow",
            ci_page,
        ),
        figure(
            "Median ci job time",
            median_text([row["job_seconds"] for row in ci_rows]),
            f"the ci job, median of {len(ci_rows)} runs",
            ci_page,
        ),
        figure(
            "Median test step time",
            median_text([row["test_seconds"] for row in ci_rows]),
            f"the lint, format check and tests step, median of {len(ci_rows)} runs",
            ci_page,
        ),
        figure(
            "Pull requests merged",
            len(merged),
            "pull requests merged into main",
            merged_page,
        ),
        figure(
            "Blocked by the eval gate",
            ", ".join(f"#{number}" for number in blocked) or "none",
            "open pull requests whose required evals check failed, so the merge is blocked",
            blocked_source,
        ),
        recorded("stability_proof"),
        recorded("kappa"),
        recorded("injection"),
        recorded("label_audit"),
    ]

    owner_approvals = sum(
        1 for d in deploys for a in d.approvals if is_owner(a) and a.get("state") == "approved"
    )
    all_approvals = sum(1 for d in deploys for a in d.approvals if a.get("state") == "approved")
    owner_rejections = sum(
        1 for d in deploys for a in d.approvals if is_owner(a) and a.get("state") == "rejected"
    )
    first_success = next((d for d in deploys if d.row["result"] == "success"), None)
    total_decisions = sum(decisions.values())
    sdlc_figures = [
        figure(
            "Commits with the agent's co-author line",
            f"{co_authored} of {commits}",
            "commits on the branches of merged pull requests, counted once each, whose "
            "message carries Co-Authored-By: Claude",
            merged_page,
        ),
        figure(
            "Decisions made by the owner",
            f"{decisions['owner']} of {total_decisions}",
            f"rows of the decision record whose Who is the owner alone; {decisions['shared']} "
            "more name two of owner, agent and rule",
            blob("intent/decisions.md"),
        ),
        figure(
            "Deploy approvals by the owner",
            owner_approvals,
            f"approvals of the demo environment by the owner, of {all_approvals} in all; "
            f"rejected by the owner: {owner_rejections}",
            f"{REPO_URL}/actions/workflows/deploy.yml",
        ),
        recorded("verifier"),
        recorded("review_findings"),
        figure(
            "First commit to first deploy",
            hours_minutes(started, parse_time(first_success.run["updated_at"]))
            if first_success
            else "no deploy yet",
            "first commit on main to the first successful deploy run finishing",
            first_success.row["source"] if first_success else f"{REPO_URL}/commits/main",
        ),
    ]

    return {
        "generated_at": utc_text(generated),
        "repository": REPOSITORY,
        "before_production": {
            "figures": before_figures,
            "ci_runs": ci_rows,
            "gates": gates,
        },
        "in_production": {
            "figures": production_figures(deploys),
            "deploys": [deploy.row for deploy in deploys],
        },
        "ai_native_sdlc": {
            "figures": sdlc_figures,
            "stages": [dict(stage) for stage in STAGES],
            "decisions_by_who": [{"who": who, "decisions": decisions[who]} for who in WHO_VALUES],
        },
    }


def render(snapshot: dict) -> str:
    return json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"


def check_public(text: str) -> None:
    """Refuse to write an email address, a token-shaped string or a link elsewhere."""
    if EMAIL.search(text):
        raise SnapshotError("the snapshot would hold an email address; nothing written")
    if TOKEN.search(text):
        raise SnapshotError("the snapshot would hold a token-shaped string; nothing written")
    if AZURE_HOST.search(text):
        raise SnapshotError("the snapshot would hold an Azure host or identifier; nothing written")
    for url in URL.findall(text):
        if (url != REPO_URL and not url.startswith(f"{REPO_URL}/")) or ".." in url:
            raise SnapshotError("the snapshot would link outside this repository; nothing written")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description="Write dashboards/sdlc_snapshot.json from GitHub (read-only) and this repository."
    ).parse_args(argv)
    try:
        text = render(build_snapshot(ROOT))
        check_public(text)
    except SnapshotError as error:
        print(f"sdlc_snapshot: {error}", file=sys.stderr)
        return 1
    except (KeyError, ValueError, TypeError) as error:
        # A reply in an unexpected shape: name the error type only, never a path or a body.
        print(
            f"sdlc_snapshot: unexpected data from GitHub ({type(error).__name__})", file=sys.stderr
        )
        return 1
    path = ROOT / OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
