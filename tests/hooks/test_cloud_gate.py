"""Allow and deny cases for every rule in .claude/hooks/cloud_gate.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.hooks.conftest import run_hook

RG_SCOPE = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-answer-scorer-demo"
)
SUB_SCOPE = "/subscriptions/00000000-0000-0000-0000-000000000000"
REPO = "repos/example-owner/answer-scorer"

GOOD_RULESET = {
    "name": "main",
    "target": "branch",
    "enforcement": "active",
    "bypass_actors": [],
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "ci"}, {"context": "evals"}]},
        },
    ],
}


def gate(command: str, tool: str = "Bash", cwd: str | None = None):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": command},
    }
    if cwd:
        payload["cwd"] = cwd
    return run_hook("cloud_gate.py", payload)


def assert_denied(result, *words: str) -> None:
    assert result.returncode == 2, result.stderr
    assert result.stderr.startswith("cloud_gate: ")
    for word in words:
        assert word in result.stderr


def assert_allowed(result) -> None:
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


# --- azd and az -----------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize(
    ("command", "word"),
    [
        ("azd up", "azd up"),
        ("azd up --no-prompt", "azd up"),
        ("cd infra && azd deploy --all", "azd deploy"),
        ("azd down --purge --force", "azd down"),
        ("azd.exe up", "azd up"),
        ("az group delete --name rg-answer-scorer-demo --yes", "az group delete"),
        ("az.cmd group delete -n rg-answer-scorer-demo", "az group delete"),
        ("az account set --subscription 00000000-0000-0000-0000-000000000000", "az account set"),
        ("az  account   set -s other", "az account set"),
    ],
)
def test_destructive_azure_commands_are_denied(command: str, word: str, tool: str) -> None:
    assert_denied(gate(command, tool), word)


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize(
    "command",
    [
        "azd provision --no-prompt",
        "azd env get-values",
        "azd env new answer-scorer-demo --location uksouth",
        "az group show --name rg-answer-scorer-demo",
        "az group create --name rg-answer-scorer-demo --location uksouth",
        "az account show --query name",
        "az deployment group create -g rg-answer-scorer-demo -f infra/observability.bicep",
        "az bicep build --file infra/main.bicep",
        "echo 'the docs mention azdup and az groups'",
    ],
)
def test_ordinary_azure_commands_pass(command: str, tool: str) -> None:
    assert_allowed(gate(command, tool))


@pytest.mark.parametrize(
    "role",
    [
        "Owner",
        "Contributor",
        '"User Access Administrator"',
        "'user access administrator'",
        "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
        "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c",
    ],
)
def test_broad_roles_are_denied_even_inside_the_resource_group(role: str) -> None:
    command = f"az role assignment create --assignee abc --role {role} --scope {RG_SCOPE}"
    assert_denied(gate(command), "Owner, Contributor or User Access Administrator")


@pytest.mark.parametrize(
    ("command", "word"),
    [
        (
            f'az role assignment create --assignee abc --role "Reader" --scope {SUB_SCOPE}',
            "wider than the project resource group",
        ),
        ('az role assignment create --assignee abc --role "Reader"', "targets the subscription"),
        (
            'az role assignment create --assignee abc --role "Reader" '
            "--scope /subscriptions/0000/resourceGroups/some-other-group",
            "rg-answer-scorer-demo",
        ),
        ("az role assignment create --assignee abc --scope " + RG_SCOPE, "no --role"),
    ],
)
def test_role_assignments_outside_the_project_are_denied(command: str, word: str) -> None:
    assert_denied(gate(command), word)


@pytest.mark.parametrize(
    "command",
    [
        'az role assignment create --assignee-object-id abc --role "Cognitive Services OpenAI User" '
        f"--scope {RG_SCOPE}/providers/Microsoft.CognitiveServices/accounts/example",
        'az role assignment create --assignee abc --role "Container Apps Contributor" '
        f"--scope {RG_SCOPE}/providers/Microsoft.App/containerApps/example",
        "SCOPE=$(az containerapp show -g rg-answer-scorer-demo -n app --query id -o tsv) && "
        'az role assignment create --assignee abc --role "Container Apps Contributor" '
        '--scope "$SCOPE"',
        "az role assignment list --all",
    ],
)
def test_narrow_role_assignments_inside_the_project_pass(command: str) -> None:
    assert_allowed(gate(command))


# --- git --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin feature",
        "git push -f origin feature",
        "git push -fu origin feature",
        "git push --force-with-lease origin feature",
        "git push origin +feature",
        "git push --mirror",
        "git push origin --all",
    ],
)
def test_force_pushes_are_denied(command: str, repo_on_branch: Path) -> None:
    assert_denied(gate(command, cwd=str(repo_on_branch)), "blocked")


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push origin HEAD:main",
        "git push origin feature:refs/heads/main",
        "git push -u origin main",
        "git push origin :main",
        "git -C . push origin main",
        "git add . && git commit -m x && git push origin main",
    ],
)
def test_pushes_that_name_main_are_denied(command: str, repo_on_branch: Path) -> None:
    assert_denied(gate(command, cwd=str(repo_on_branch)), "pushes to main")


@pytest.mark.parametrize("command", ["git push", "git push origin", "git push -u origin HEAD"])
def test_bare_pushes_from_main_are_denied(command: str, repo_on_main: Path) -> None:
    assert_denied(gate(command, cwd=str(repo_on_main)), "pushes to main")


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push -u origin HEAD",
        "git push -u origin feature",
        "git push origin feature 2>&1",
        "git push origin --delete feature",
        "git status && git log --oneline -5",
        "git checkout main && git pull --ff-only",
    ],
)
def test_ordinary_pushes_from_a_branch_pass(command: str, repo_on_branch: Path) -> None:
    assert_allowed(gate(command, cwd=str(repo_on_branch)))


def test_bare_push_outside_a_repository_fails_closed(tmp_path: Path) -> None:
    assert_denied(gate("git push", cwd=str(tmp_path)), "current branch")


# --- gh repo ----------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize(
    "command",
    [
        "gh repo delete example-owner/answer-scorer --yes",
        "gh repo edit --visibility private --accept-visibility-change-consequences",
        "gh repo archive example-owner/answer-scorer",
        f"gh api -X DELETE {REPO}",
        f"gh api --method PATCH {REPO} -f private=true",
        f"gh api -X PATCH {REPO} -f visibility=private",
    ],
)
def test_repo_deletion_and_visibility_changes_are_denied(command: str, tool: str) -> None:
    assert_denied(gate(command, tool), "blocked")


@pytest.mark.parametrize(
    "command",
    [
        "gh repo view --json nameWithOwner",
        "gh repo edit --enable-auto-merge",
        f"gh api {REPO}",
        f"gh api -X PATCH {REPO} -f delete_branch_on_merge=true",
        f"gh api -X PUT {REPO}/vulnerability-alerts",
        "gh pr create --fill",
        "gh pr merge 3 --squash --delete-branch",
    ],
)
def test_ordinary_gh_commands_pass(command: str) -> None:
    assert_allowed(gate(command))


# --- deployments ------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize(
    "command",
    [
        f"gh api -X POST {REPO}/actions/runs/1/pending_deployments -f state=approved",
        f"gh api {REPO}/actions/runs/1/pending_deployments -f state=rejected -F 'environment_ids[]=1'",
        f"gh api --method POST {REPO}/actions/runs/1/pending_deployments --input body.json",
        f"gh api -X POST {REPO}/actions/runs/1/deployment_protection_rule -f state=approved",
    ],
)
def test_approving_or_rejecting_a_deployment_is_denied(command: str, tool: str) -> None:
    assert_denied(gate(command, tool), "blocked")


def test_reading_pending_deployments_passes() -> None:
    assert_allowed(gate(f"gh api {REPO}/actions/runs/1/pending_deployments"))


# --- rulesets ---------------------------------------------------------------------------


def _ruleset_file(tmp_path: Path, **changes) -> str:
    body = json.loads(json.dumps(GOOD_RULESET))
    body.update(changes)
    path = tmp_path / "ruleset.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return str(path)


def test_creating_the_ruleset_passes() -> None:
    assert_allowed(gate(f"gh api -X POST {REPO}/rulesets --input ruleset.json"))


def test_strengthening_the_ruleset_passes(tmp_path: Path) -> None:
    path = _ruleset_file(tmp_path)
    assert_allowed(gate(f'gh api -X PUT {REPO}/rulesets/42 --input "{path}"'))


def test_reading_the_ruleset_passes() -> None:
    assert_allowed(gate(f"gh api {REPO}/rulesets/42"))


def test_deleting_the_ruleset_is_denied() -> None:
    assert_denied(gate(f"gh api -X DELETE {REPO}/rulesets/42"), "deleting the main ruleset")


@pytest.mark.parametrize(
    ("changes", "word"),
    [
        ({"enforcement": "disabled"}, "enforcement"),
        ({"enforcement": "evaluate"}, "enforcement"),
        ({"bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole"}]}, "bypass"),
        ({"rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]}, "lose rules"),
        (
            {
                "rules": [
                    {"type": "deletion"},
                    {"type": "non_fast_forward"},
                    {"type": "pull_request"},
                    {
                        "type": "required_status_checks",
                        "parameters": {"required_status_checks": [{"context": "evals"}]},
                    },
                ]
            },
            "'ci'",
        ),
    ],
)
def test_weakening_the_ruleset_is_denied(tmp_path: Path, changes: dict, word: str) -> None:
    path = _ruleset_file(tmp_path, **changes)
    assert_denied(gate(f'gh api -X PUT {REPO}/rulesets/42 --input "{path}"'), word)


@pytest.mark.parametrize(
    "command",
    [
        f"gh api -X PUT {REPO}/rulesets/42 -f enforcement=disabled",
        f"gh api -X PUT {REPO}/rulesets/42 --input -",
        f"gh api -X PATCH {REPO}/rulesets/42 --input missing-file.json",
    ],
)
def test_ruleset_changes_the_gate_cannot_read_fail_closed(command: str, tmp_path: Path) -> None:
    assert_denied(gate(command, cwd=str(tmp_path)), "--input")


def test_deleting_branch_protection_is_denied() -> None:
    assert_denied(gate(f"gh api -X DELETE {REPO}/branches/main/protection"), "branch protection")


# --- environments -----------------------------------------------------------------------


def test_creating_demo_with_a_required_reviewer_passes(tmp_path: Path) -> None:
    body = tmp_path / "environment.json"
    body.write_text(json.dumps({"reviewers": [{"type": "User", "id": 1}]}), encoding="utf-8")
    assert_allowed(gate(f'gh api -X PUT {REPO}/environments/demo --input "{body}"'))


def test_removing_the_demo_reviewer_is_denied(tmp_path: Path) -> None:
    body = tmp_path / "environment.json"
    body.write_text(json.dumps({"reviewers": []}), encoding="utf-8")
    result = gate(f'gh api -X PUT {REPO}/environments/demo --input "{body}"')
    assert_denied(result, "required reviewer")


def test_environment_changes_the_gate_cannot_read_fail_closed() -> None:
    assert_denied(gate(f"gh api -X PUT {REPO}/environments/demo -F wait_timer=0"), "--input")


def test_deleting_an_environment_is_denied() -> None:
    assert_denied(gate(f"gh api -X DELETE {REPO}/environments/demo"), "deleting an environment")


def test_reading_an_environment_passes() -> None:
    assert_allowed(gate(f"gh api {REPO}/environments/demo"))


# --- payload handling -------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["Read", "Edit", "Write", "Grep", "WebFetch"])
def test_other_tools_pass(tool: str) -> None:
    payload = {"tool_name": tool, "tool_input": {"file_path": "azd up"}}
    assert_allowed(run_hook("cloud_gate.py", payload))


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", '"text"'])
def test_bad_payloads_fail_closed_with_exit_2(raw: str) -> None:
    result = run_hook("cloud_gate.py", None, raw=raw)
    assert_denied(result)


def test_a_missing_command_fails_closed() -> None:
    result = run_hook("cloud_gate.py", {"tool_name": "Bash", "tool_input": {}})
    assert_denied(result, "no command")


def test_the_gate_never_exits_1() -> None:
    result = run_hook("cloud_gate.py", {"tool_name": "Bash", "tool_input": {"command": 7}})
    assert result.returncode == 2
