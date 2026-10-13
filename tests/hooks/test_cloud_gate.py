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


def gate(command: str, tool: str = "Bash", cwd: str | None = None, env: dict | None = None):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": command},
    }
    if cwd:
        payload["cwd"] = cwd
    return run_hook("cloud_gate.py", payload, env=env)


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
            "must be scoped inside rg-answer-scorer-demo",
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
    assert_denied(gate(f"gh api -X DELETE {REPO}/rulesets/42"), "ruleset")


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
    assert_denied(gate(f"gh api -X DELETE {REPO}/environments/demo"), "environment")


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


# --- spellings the first verifier run found passing ---------------------------------------


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize(
    ("command", "word"),
    [
        ("azd --no-prompt up", "azd up"),
        ("azd -C infra deploy", "azd deploy"),
        ("azd --debug down --purge", "azd down"),
        ("azd --cwd=infra --no-prompt deploy --all", "azd deploy"),
        ("az --verbose group delete -n rg-answer-scorer-demo", "az group delete"),
        ("az --only-show-errors account set -s other", "az account set"),
    ],
)
def test_global_flags_before_a_blocked_subcommand_are_denied(
    command: str, word: str, tool: str
) -> None:
    assert_denied(gate(command, tool), word)


@pytest.mark.parametrize(
    "command",
    [
        "azd --no-prompt provision",
        "azd -C infra env get-values",
        "azd env set NOTE up",
        "az --only-show-errors group show -n rg-answer-scorer-demo",
    ],
)
def test_global_flags_before_an_ordinary_subcommand_pass(command: str) -> None:
    assert_allowed(gate(command))


@pytest.mark.parametrize(
    "command",
    [
        f"gh api -XDELETE {REPO}/rulesets/42",
        f"gh api -XDELETE {REPO}/environments/demo",
        f"gh api -XDELETE {REPO}",
        f"gh api -X=DELETE {REPO}/rulesets/42",
        f"gh api --method=DELETE {REPO}/environments/demo",
        f"gh api -X 'DELETE' {REPO}/rulesets/42",
        f"gh api {REPO}/actions/runs/1/pending_deployments -fstate=approved",
        f"gh api {REPO}/actions/runs/1/pending_deployments -Fstate=rejected",
        f"gh api -XPOST {REPO}/actions/runs/1/pending_deployments --input body.json",
    ],
)
def test_attached_short_flags_are_read(command: str) -> None:
    assert_denied(gate(command), "blocked")


@pytest.mark.parametrize(
    ("changes", "word"),
    [
        ({"target": "tag"}, "target"),
        ({"conditions": {"ref_name": {"include": ["refs/heads/other"], "exclude": []}}}, "default"),
        ({"conditions": {"ref_name": {"include": [], "exclude": []}}}, "default"),
        ({"conditions": {}}, "default"),
        (
            {"conditions": {"ref_name": {"include": ["~ALL"], "exclude": ["refs/heads/main"]}}},
            "exclude",
        ),
    ],
)
def test_pointing_the_ruleset_away_from_main_is_denied(
    tmp_path: Path, changes: dict, word: str
) -> None:
    path = _ruleset_file(tmp_path, **changes)
    assert_denied(gate(f'gh api -X PUT {REPO}/rulesets/42 --input "{path}"'), word)


# --- shapes the security review found passing ---------------------------------------------


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize(
    "command",
    [
        "az --% group delete -n rg-answer-scorer-demo",
        "azd --% up",
        '& "az.cmd" group delete -n rg-answer-scorer-demo',
        '& "azd.exe" deploy',
    ],
)
def test_stop_parsing_tokens_and_quoted_tool_names_are_denied(command: str, tool: str) -> None:
    assert_denied(gate(command, tool), "blocked")


GOOD_ROLE = (
    'az role assignment create --assignee abc --role "Cognitive Services OpenAI User" '
    f"--scope {RG_SCOPE}/providers/Microsoft.CognitiveServices/accounts/example"
)


@pytest.mark.parametrize("separator", [" && ", "; ", " || ", "\n", " | "])
def test_every_command_in_a_compound_line_is_checked(separator: str) -> None:
    broad = f"az role assignment create --assignee b --role Contributor --scope {SUB_SCOPE}"
    assert_denied(gate(GOOD_ROLE + separator + broad), "Owner, Contributor")
    assert_denied(
        gate(f"gh api -X GET {REPO}/rulesets{separator}gh api -X DELETE {REPO}/rulesets/42")
    )
    assert_denied(gate(f"echo ok{separator}azd up"), "azd up")


def test_separators_inside_quotes_do_not_split_a_command() -> None:
    assert_allowed(gate(f"gh api {REPO}/rulesets --jq '.[] | select(.name == \"main\") | .id'"))
    assert_denied(gate(f"gh api -X DELETE --jq '.a | .b' {REPO}/rulesets/42"), "ruleset")


@pytest.mark.parametrize(
    ("command", "word"),
    [
        (
            'az role assignment create --assignee abc --role "$ROLE" --scope ' + RG_SCOPE,
            "role name",
        ),
        (
            "SCOPE=$(az containerapp show -g rg-answer-scorer-demo -n app --query id -o tsv) && "
            'az role assignment create --assignee abc --role "Reader" --scope "$SCOPE"',
            "--scope out in full",
        ),
        (
            'az role assignment create --assignee abc --role "Reader" '
            "--scope /subscriptions/0000/resourceGroups/rg-answer-scorer-demo-other",
            "rg-answer-scorer-demo",
        ),
    ],
)
def test_role_assignments_the_gate_cannot_read_fail_closed(command: str, word: str) -> None:
    assert_denied(gate(command), word)


@pytest.mark.parametrize(
    "command",
    [
        "git checkout main && git merge --ff-only feature && git push",
        "git switch main; git push origin HEAD",
        "cd ../elsewhere && git push",
        "git -C ../elsewhere push",
    ],
)
def test_bare_pushes_after_a_move_are_denied(command: str, repo_on_branch: Path) -> None:
    assert_denied(gate(command, cwd=str(repo_on_branch)), "name the branch")


@pytest.mark.parametrize(
    "command",
    [
        "OUT=$(git push origin main)",
        "echo `git push origin main`",
        'git push origin "main"',
    ],
)
def test_wrapped_pushes_to_main_are_denied(command: str, repo_on_branch: Path) -> None:
    assert_denied(gate(command, cwd=str(repo_on_branch)), "pushes to main")


def test_a_named_push_after_a_move_passes(repo_on_branch: Path) -> None:
    result = gate("cd . && git push -u origin feature", cwd=str(repo_on_branch))
    assert_allowed(result)


@pytest.mark.parametrize(
    "command",
    [
        f"gh api -X DELETE {REPO}/rulesets/$ID",
        f"gh api -X PUT {REPO}/rulesets/$ID --input anything.json",
        f"gh api -X DELETE {REPO}/environments/$NAME",
        "gh api -X DELETE repos/{owner}/{repo}",
        "gh api -X PATCH repos/{owner}/{repo} -f visibility=private",
        "gh api -X PATCH repos/:owner/:repo -f private=true",
    ],
)
def test_variables_and_placeholders_in_paths_are_denied(command: str, tmp_path: Path) -> None:
    assert_denied(gate(command, cwd=str(tmp_path)))


def test_a_ruleset_change_must_be_the_only_command(tmp_path: Path) -> None:
    path = _ruleset_file(tmp_path)
    command = f'echo rewrite && gh api -X PUT {REPO}/rulesets/42 --input "{path}"'
    assert_denied(gate(command), "only command")


def test_an_environment_change_must_be_the_only_command(tmp_path: Path) -> None:
    body = tmp_path / "environment.json"
    body.write_text(json.dumps({"reviewers": [{"type": "User", "id": 1}]}), encoding="utf-8")
    command = f'echo rewrite; gh api -X PUT {REPO}/environments/demo --input "{body}"'
    assert_denied(gate(command), "only command")


@pytest.mark.parametrize("key", ["private", "visibility", "archived"])
def test_repo_changes_sent_as_a_file_are_read(tmp_path: Path, key: str) -> None:
    body = tmp_path / "repo.json"
    body.write_text(json.dumps({key: True}), encoding="utf-8")
    assert_denied(gate(f'gh api -X PATCH {REPO} --input "{body}"'), "visibility")


def test_harmless_repo_changes_sent_as_a_file_pass(tmp_path: Path) -> None:
    body = tmp_path / "repo.json"
    body.write_text(json.dumps({"delete_branch_on_merge": True}), encoding="utf-8")
    assert_allowed(gate(f'gh api -X PATCH {REPO} --input "{body}"'))


def test_dropping_evals_is_denied_once_the_eval_gate_exists(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".github" / "workflows").mkdir(parents=True)
    (project / ".github" / "workflows" / "evals.yml").write_text("name: evals\n", encoding="utf-8")
    only_ci = json.loads(json.dumps(GOOD_RULESET["rules"]))
    only_ci[-1]["parameters"]["required_status_checks"] = [{"context": "ci"}]
    path = _ruleset_file(tmp_path, rules=only_ci)
    command = f'gh api -X PUT {REPO}/rulesets/42 --input "{path}"'
    assert_denied(gate(command, env={"CLAUDE_PROJECT_DIR": str(project)}), "evals")
    assert_allowed(gate(command, env={"CLAUDE_PROJECT_DIR": str(tmp_path)}))


@pytest.mark.parametrize(
    "mutation",
    ["approveDeployments", "rejectDeployments", "deleteRepositoryRuleset", "deleteEnvironment"],
)
def test_blocked_graphql_mutations_are_denied(mutation: str) -> None:
    command = (
        f"gh api graphql -f query='mutation {{ {mutation}(input: {{}}) {{ clientMutationId }} }}'"
    )
    assert_denied(gate(command), mutation)


def test_ordinary_graphql_queries_pass() -> None:
    assert_allowed(gate("gh api graphql -f query='query { viewer { login } }'"))


def test_non_ascii_text_in_a_command_is_read_as_utf8() -> None:
    assert_allowed(gate("echo “curly quotes” and café"))


# --- shapes the second verifier run found passing -----------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        f"gh api -X PATCH {REPO} -fvisibility=private",
        f"gh api -X PATCH {REPO} -Fprivate=true",
        f"gh api -X PATCH {REPO} -Farchived=true",
        f"gh api -X DELETE /{REPO}",
        f"gh api -X PATCH /{REPO} -f visibility=private",
        f"gh api -X PATCH /{REPO} -f archived=true",
        f"gh api -X DELETE https://api.github.com/{REPO}",
        f"gh api -X PATCH https://api.github.com/{REPO} -f private=true",
        "gh api -X DELETE repos/$OWNER/$REPO",
        "gh api -X DELETE repos/$REPO",
        'gh api -X DELETE "repos/${OWNER}/${REPO}"',
        'gh api -X PATCH "repos/$env:OWNER/answer-scorer" -f private=true',
        "gh api -X PATCH repos/$REPO -f visibility=private",
    ],
)
@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
def test_every_spelling_of_the_repository_path_is_read(command: str, tool: str) -> None:
    assert_denied(gate(command, tool), "blocked")


@pytest.mark.parametrize("prefix", ["/", "https://api.github.com/", ""])
@pytest.mark.parametrize("key", ["private", "visibility", "archived"])
def test_repo_bodies_are_read_for_every_path_spelling(
    tmp_path: Path, prefix: str, key: str
) -> None:
    body = tmp_path / "repo.json"
    body.write_text(json.dumps({key: True}), encoding="utf-8")
    assert_denied(gate(f'gh api -X PATCH {prefix}{REPO} --input "{body}"'), "visibility")


@pytest.mark.parametrize(
    "command",
    [
        f"gh api /{REPO}",
        f"gh api -X GET https://api.github.com/{REPO}",
        f"gh api -X PATCH /{REPO} -f delete_branch_on_merge=true",
        f"gh api -X PUT /{REPO}/vulnerability-alerts",
        f"gh api /{REPO}/pulls/3/comments",
        "gh api repos/$REPO/pulls",
    ],
)
def test_harmless_calls_in_those_spellings_pass(command: str) -> None:
    assert_allowed(gate(command))


@pytest.mark.parametrize(
    "command",
    [
        f"gh api -X GET -X DELETE {REPO}/rulesets/42",
        f"gh api -X DELETE -X GET {REPO}/environments/demo",
        f"gh api -X $METHOD {REPO}/rulesets/42",
        f"gh api --method $METHOD {REPO}",
        f"gh api -X $METHOD {REPO}/actions/runs/1/pending_deployments",
    ],
)
def test_repeated_or_unreadable_methods_fail_closed(command: str) -> None:
    assert_denied(gate(command), "blocked")


def test_a_stray_quote_cannot_hide_later_commands(repo_on_main: Path) -> None:
    broad = f"az role assignment create --assignee b --role Owner --scope {SUB_SCOPE}"
    assert_denied(gate("# don't stop here\n" + GOOD_ROLE + "\n" + broad), "Owner, Contributor")
    hidden_delete = f"gh api -X GET {REPO}/rulesets; gh api -X DELETE {REPO}/rulesets/42"
    assert_denied(gate('echo "a \\" b"; ' + hidden_delete), "blocked")
    push = "# it's fine\ngit push\necho done"
    assert_denied(gate(push, cwd=str(repo_on_main)), "pushes to main")


def test_a_stray_quote_cannot_make_a_compound_call_look_alone(tmp_path: Path) -> None:
    path = _ruleset_file(tmp_path)
    put = f'gh api -X PUT {REPO}/rulesets/42 --input "{path}"'
    assert_denied(gate("# don't\n" + put + "\necho done"), "only command")


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize(
    ("command", "word"),
    [
        ('azd --cwd "my infra" deploy', "azd deploy"),
        ("azd --cwd  infra  up", "azd up"),
        ("azd -C 'my infra'   down --purge", "azd down"),
    ],
)
def test_quoted_and_widely_spaced_flag_values_are_read(command: str, word: str, tool: str) -> None:
    assert_denied(gate(command, tool), word)


def test_the_at_alias_for_head_is_read(repo_on_main: Path, repo_on_branch: Path) -> None:
    assert_denied(gate("git push origin @", cwd=str(repo_on_main)), "pushes to main")
    assert_allowed(gate("git push origin @", cwd=str(repo_on_branch)))


# --- shapes the third verifier run found passing ------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'git push origin "$(git branch --show-current)"',
        "git push -u origin $(git branch --show-current)",
        "git push origin $BRANCH",
        'git push origin "${BRANCH}"',
        "git push origin HEAD:$BRANCH",
        "git push origin HEAD:$(git branch --show-current)",
        "git push origin `git branch --show-current`",
        "git push origin (git branch --show-current)",
    ],
)
@pytest.mark.parametrize("where", ["main", "branch"])
def test_a_branch_the_gate_cannot_read_is_denied(
    command: str, where: str, repo_on_main: Path, repo_on_branch: Path
) -> None:
    cwd = repo_on_main if where == "main" else repo_on_branch
    assert_denied(gate(command, cwd=str(cwd)), "blocked")


@pytest.mark.parametrize(
    "command",
    [
        "GIT push origin main",
        "Git.exe push --force origin feature",
        f"GH api -X DELETE {REPO}/rulesets/42",
        "GH repo delete example-owner/answer-scorer --yes",
    ],
)
def test_tool_names_are_read_in_any_case(command: str, repo_on_branch: Path) -> None:
    assert_denied(gate(command, "PowerShell", cwd=str(repo_on_branch)), "blocked")


@pytest.mark.parametrize(
    "command",
    [
        'gh api -X DELETE "$URL"',
        "gh api -X DELETE $RULESET_URL",
        "gh api -X PUT $URL --input body.json",
        "gh api -X PATCH ${REPO_URL} -f name=other",
        f"gh api -X DELETE /{REPO}/",
        f"gh api -X PATCH /{REPO}/ -f visibility=private",
        f"gh api -X DELETE {REPO}/environments/demo/",
        f"gh api -X PATCH '{REPO}?x=1' -f private=true",
    ],
)
def test_endpoints_the_gate_cannot_read_and_trailing_slashes_are_denied(command: str) -> None:
    assert_denied(gate(command), "blocked")


@pytest.mark.parametrize(
    "command",
    [
        f'gh api {REPO}/pulls --jq "$FILTER"',
        "gh api $URL",
        f"gh api -X POST {REPO}/issues --input $FILE",
    ],
)
def test_variables_in_harmless_places_pass(command: str) -> None:
    assert_allowed(gate(command))


@pytest.mark.parametrize("tool_name", ["az", "azd", "git"])
def test_a_long_run_of_flags_is_judged_quickly(tool_name: str) -> None:
    import time

    flags = " ".join(f"--flag-{number}" for number in range(40))
    started = time.monotonic()
    harmless = gate(f"{tool_name} {flags} version")
    blocked = gate(f"az {flags} account set -s other")
    assert time.monotonic() - started < 20
    assert_allowed(harmless)
    assert_denied(blocked, "az account set")


def test_the_gate_never_exits_1() -> None:
    result = run_hook("cloud_gate.py", {"tool_name": "Bash", "tool_input": {"command": 7}})
    assert result.returncode == 2
