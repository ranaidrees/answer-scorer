"""`.github/workflows/evals.yml` against spec section 9 (workflow hygiene and `evals.yml`).

The workflow cannot be run offline, so these tests fix its shape: the triggers, the
permissions, the pinned actions, the order of the steps and the rule that nothing from a
pull request is written into a script.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "evals.yml"

# The pins looked up by the lead on 13 October 2026. No other action is allowed.
ALLOWED_ACTIONS = {
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1": "v7.0.1",
    "astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884": "v10.3.0",
    "azure/login@a641126d1b8aa4d1fa005f4f92df94a3a4c4c906": "v3.1.0",
    "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9": "v7.0.2",
}


@pytest.fixture(scope="module")
def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(text) -> dict:
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def steps(workflow) -> list[dict]:
    return workflow["jobs"]["evals"]["steps"]


def step(steps: list[dict], name: str) -> dict:
    return next(item for item in steps if item["name"].startswith(name))


def test_triggers_are_pull_request_nightly_and_manual(workflow):
    triggers = workflow[True]  # YAML reads the key `on` as a boolean
    assert set(triggers) == {"pull_request", "schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "0 2 * * *"}]
    assert triggers["pull_request"] is None  # every pull request, whatever its paths


def test_pull_request_target_is_never_used(text):
    assert "pull_request_target" not in text


def test_one_job_named_evals(workflow):
    assert list(workflow["jobs"]) == ["evals"]
    assert workflow["jobs"]["evals"]["name"] == "evals"
    assert workflow["name"] == "evals"


def test_permissions_are_empty_at_the_top_and_least_privilege_on_the_job(workflow):
    assert workflow["permissions"] == {}
    assert workflow["jobs"]["evals"]["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "pull-requests": "write",
    }


def test_caches_are_read_only(workflow):
    assert workflow["cache-mode"] == "read"


def test_a_superseded_pull_request_run_is_cancelled(workflow):
    concurrency = workflow["concurrency"]
    assert "github.event.pull_request.number" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_every_action_is_one_of_the_pinned_ones_with_its_version_in_a_comment(text, steps):
    used = [item["uses"] for item in steps if "uses" in item]
    assert set(used) == set(ALLOWED_ACTIONS)
    for action, version in ALLOWED_ACTIONS.items():
        assert re.search(rf"uses: {re.escape(action)} # {re.escape(version)}\n", text), action
    assert all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action) for action in used)


def test_checkout_keeps_no_credentials(steps):
    assert steps[0]["uses"].startswith("actions/checkout@")
    assert steps[0]["with"]["persist-credentials"] is False


def test_the_path_check_is_the_first_step_after_checkout_and_gates_the_rest(steps):
    check = steps[1]
    assert check["id"] == "paths"
    assert check["run"] == "python3 evals/changed_paths.py"
    assert "if" not in check  # it always runs and always reports
    for later in steps[2:]:
        assert "steps.paths.outputs.run == 'true'" in later["if"] or (
            "steps.run.outputs.report_md != ''" in later["if"]
        ), later["name"]


def test_step_order(steps):
    names = [item["name"] for item in steps]
    assert names == [
        "Check out",
        "Check changed paths",
        "Sign in to Azure as the eval identity (OIDC)",
        "Set up uv",
        "Install dependencies",
        "Run the evals",
        "Upload the report",
        "Comment on the pull request",
    ]


def test_sign_in_is_oidc_with_ids_from_repository_secrets(steps):
    # Secrets, not variables: the inputs of an action are printed in the public job log,
    # and only a secret is masked there.
    login = step(steps, "Sign in to Azure")
    assert login["with"] == {
        "client-id": "${{ secrets.AZURE_CLIENT_ID_EVAL }}",
        "tenant-id": "${{ secrets.AZURE_TENANT_ID }}",
        "subscription-id": "${{ secrets.AZURE_SUBSCRIPTION_ID }}",
    }


def test_the_evals_run_in_full_with_the_event_and_settings_from_the_repository(steps):
    assert step(steps, "Install dependencies")["run"] == "uv sync --locked"
    run = step(steps, "Run the evals")
    assert run["run"] == "uv run poe eval --emit-event"  # no --fake, --suite or --split
    assert "continue-on-error" not in run  # the gate fails the job
    env = run["env"]
    assert env["FOUNDRY_ENDPOINT"] == "${{ secrets.FOUNDRY_ENDPOINT }}"
    assert env["MODEL_DEPLOYMENT"] == "${{ vars.MODEL_DEPLOYMENT }}"
    assert env["MODEL_VERSION"] == "${{ vars.MODEL_VERSION }}"
    assert env["APPLICATIONINSIGHTS_CONNECTION_STRING"] == (
        "${{ secrets.APPLICATIONINSIGHTS_CONNECTION_STRING }}"
    )
    assert "${{" not in env["ANSWER_HASH_SALT"]  # fixed and not a secret


def test_everything_that_identifies_the_account_is_a_secret_and_nothing_is_hard_coded(text):
    assert set(re.findall(r"secrets\.(\w+)", text)) == {
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "AZURE_CLIENT_ID_EVAL",
        "AZURE_TENANT_ID",
        "AZURE_SUBSCRIPTION_ID",
        "FOUNDRY_ENDPOINT",
    }
    # Only fixed names that identify nothing are variables.
    assert set(re.findall(r"vars\.(\w+)", text)) == {"MODEL_DEPLOYMENT", "MODEL_VERSION"}
    # No id, endpoint or connection string written into the file.
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)
    assert "InstrumentationKey" not in text
    assert not re.search(r"https://[\w.-]+\.(azure|microsoft|windows)\.", text)


def test_no_expression_is_written_into_a_script(steps):
    for item in steps:
        assert "${{" not in item.get("run", ""), item["name"]


def test_scripts_never_echo_an_environment_value(steps):
    for item in steps:
        script = item.get("run", "")
        assert not re.search(r"\b(printenv|env\s*$|set -x)", script, re.MULTILINE), item["name"]
        for name in ("APPLICATIONINSIGHTS_CONNECTION_STRING", "FOUNDRY_ENDPOINT", "GH_TOKEN"):
            assert name not in script, item["name"]


def test_the_report_is_uploaded_even_when_the_gate_fails(steps):
    upload = step(steps, "Upload the report")
    assert "!cancelled()" in upload["if"]
    assert "steps.run.outputs.report_md" in upload["with"]["path"]
    assert "steps.run.outputs.report_json" in upload["with"]["path"]


def test_one_comment_is_posted_or_updated_and_cannot_change_the_gate(steps):
    comment = step(steps, "Comment on the pull request")
    assert "github.event_name == 'pull_request'" in comment["if"]
    assert "!cancelled()" in comment["if"]
    assert comment["continue-on-error"] is True
    script = comment["run"]
    assert "--method PATCH" in script and "--method POST" in script
    assert "<!-- answer-scorer-evals -->" in script
    # Only the summary section of the report goes into the comment.
    assert "/<!-- eval-summary:start -->/,/<!-- eval-summary:end -->/p" in script
    assert comment["env"]["PR_NUMBER"] == "${{ github.event.pull_request.number }}"
