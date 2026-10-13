"""What the workflows can print in a public job log, and what a deploy can skip.

GitHub prints the inputs (`with:`) and the environment (`env:`) of every step, and masks
only secrets. So anything that identifies the Azure account must come from `secrets.*`,
never from `vars.*`, and no script may print part of a resource ID. These tests fix that
for every workflow, and run the deploy workflow's quiet Azure CLI wrapper against a fake
tool that fails the way the real one does. No Azure, no GitHub.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW_FILES = sorted(WORKFLOWS.glob("*.yml"))

# Each of these names the tenant, the subscription, an identity or the model resource.
IDENTIFYING = (
    "AZURE_TENANT_ID",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_CLIENT_ID_EVAL",
    "AZURE_CLIENT_ID_DEPLOY",
    "FOUNDRY_ENDPOINT",
)
# Fixed names that identify nothing. Nothing else may be read from a variable.
PLAIN_VARIABLES = {
    "AZURE_RESOURCE_GROUP",
    "CONTAINER_APP_NAME",
    "MODEL_DEPLOYMENT",
    "MODEL_VERSION",
}
# Folders whose files ship in the image.
SHIPPED = ("prompts", "rubrics", "config", "src")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def all_steps(workflow: dict) -> list[dict]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def deploy_steps() -> list[dict]:
    return load(WORKFLOWS / "deploy.yml")["jobs"]["deploy"]["steps"]


def named(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step["name"].startswith(name))


# --------------------------------------------------------------------------- secrets, not variables
def test_both_azure_workflows_are_checked():
    assert {"evals.yml", "deploy.yml"} <= {path.name for path in WORKFLOW_FILES}


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda path: path.name)
def test_no_workflow_reads_an_identifying_value_from_a_variable(path):
    text = path.read_text(encoding="utf-8")
    read_from_variables = set(re.findall(r"\bvars\s*\.\s*(\w+)", text))
    read_from_variables |= set(re.findall(r"\bvars\s*\[\s*['\"](\w+)['\"]\s*\]", text))
    assert not read_from_variables & set(IDENTIFYING)
    assert read_from_variables <= PLAIN_VARIABLES
    # No way to read every variable at once either.
    assert not re.search(r"toJSON\s*\(\s*vars\s*\)", text, re.IGNORECASE)


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda path: path.name)
def test_azure_login_is_given_secrets_only(path):
    logins = [
        step for step in all_steps(load(path)) if step.get("uses", "").startswith("azure/login@")
    ]
    if path.name in ("evals.yml", "deploy.yml"):
        assert len(logins) == 1
    for login in logins:
        inputs = login["with"]
        assert set(inputs) == {"client-id", "tenant-id", "subscription-id"}
        for name, value in inputs.items():
            assert re.fullmatch(r"\$\{\{ secrets\.[A-Z_]+ \}\}", value), name
            assert "vars" not in value, name
        assert "env" not in login


def test_each_workflow_signs_in_with_its_own_identity():
    evals = named(all_steps(load(WORKFLOWS / "evals.yml")), "Sign in to Azure")
    deploy = named(deploy_steps(), "Sign in to Azure")
    assert evals["with"]["client-id"] == "${{ secrets.AZURE_CLIENT_ID_EVAL }}"
    assert deploy["with"] == {
        "client-id": "${{ secrets.AZURE_CLIENT_ID_DEPLOY }}",
        "tenant-id": "${{ secrets.AZURE_TENANT_ID }}",
        "subscription-id": "${{ secrets.AZURE_SUBSCRIPTION_ID }}",
    }


def test_deploy_scripts_take_values_from_the_environment_and_never_trace_them():
    for step in all_steps(load(WORKFLOWS / "deploy.yml")):
        script = step.get("run", "")
        assert "${{" not in script, step["name"]
        assert not re.search(r"\b(printenv|set -x|set -[a-z]*x)\b", script), step["name"]


def test_every_azure_cli_call_in_the_deploy_goes_through_the_quiet_wrapper():
    for step in deploy_steps():
        script = step.get("run", "")
        if step["name"].startswith("Prepare a quiet Azure CLI wrapper"):
            continue
        for line in script.splitlines():
            assert not re.match(r"\s*az\s", line), (step["name"], "a bare az call")
        # What jq reads from Azure holds settings, and jq quotes values in its errors.
        for line in script.splitlines():
            if re.search(r"\bjq\b.*\"\$(current|state)\"", line):
                assert "2>/dev/null" in line, step["name"]


# --------------------------------------------------------------------------- the quiet wrapper
FAKE_GUID = "11111111-2222-3333-4444-555555555555"
FAKE_SUBSCRIPTION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FAKE_ADDRESS = "someone@example.invalid"
TOOL_MESSAGE = (
    f"ERROR: (AuthorizationFailed) The client '{FAKE_ADDRESS}' with object id '{FAKE_GUID}' "
    "does not have authorization to perform action 'Microsoft.App/containerApps/write' over "
    f"scope '/subscriptions/{FAKE_SUBSCRIPTION}/resourceGroups/fakegroup/providers/"
    "Microsoft.App/containerApps/caprivatename' or the scope is invalid.\n"
    "Code: AuthorizationFailed\n"
    "Message: The Resource 'Microsoft.App/containerApps/hiddenappname' under resource group "
    "'fakegroup' was not found. Tenant (Fakecompany) access was denied.\n"
)
MUST_NOT_BE_PRINTED = [
    FAKE_GUID,
    FAKE_SUBSCRIPTION,
    FAKE_ADDRESS,
    "subscriptions",
    "fakegroup",
    "caprivatename",
    "hiddenappname",
    "Microsoft.App/containerApps/ca",
    "Microsoft.App/containerApps/hidden",
    "Fakecompany",
    "standard-output-line",
]
FAKE_AZ = """#!/usr/bin/env bash
cat "$FAKE_AZ_MESSAGE" >&2
echo "standard-output-line"
exit "$FAKE_AZ_EXIT"
"""


def wrapper_script() -> str:
    """The wrapper exactly as the workflow writes it to the runner."""
    script = named(deploy_steps(), "Prepare a quiet Azure CLI wrapper")["run"]
    match = re.search(r"<<'SCRIPT'\n(.*?)\nSCRIPT\n", script, re.DOTALL)
    assert match, "the wrapper is no longer written from a quoted here-document"
    return match.group(1) + "\n"


def usable_bash() -> str | None:
    """A bash that can run the wrapper here, or None (Windows without Git Bash on PATH)."""
    bash = shutil.which("bash")
    if bash is None:
        return None
    probe = "command -v mktemp grep sed sort tr cat >/dev/null && echo usable"
    try:
        version = subprocess.run([bash, "--version"], capture_output=True, text=True, timeout=30)
        tools = subprocess.run([bash, "-c", probe], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if "usable" not in tools.stdout:
        return None
    if sys.platform == "win32" and "msys" not in version.stdout.lower():
        return None  # a bash that cannot see Windows paths
    return bash


@pytest.fixture
def quiet(tmp_path):
    bash = usable_bash()
    if bash is None:
        pytest.skip("no bash that can run the wrapper on this machine; it runs in ci")
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "az").write_text(FAKE_AZ, encoding="utf-8", newline="\n")
    (tools / "az").chmod(0o755)
    wrapper = tmp_path / "az-quiet"
    wrapper.write_text(wrapper_script(), encoding="utf-8", newline="\n")
    message = tmp_path / "message.txt"
    message.write_text(TOOL_MESSAGE, encoding="utf-8", newline="\n")

    def run(exit_code: int, output: str) -> subprocess.CompletedProcess:
        environment = {
            **os.environ,
            "PATH": str(tools) + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_AZ_MESSAGE": message.as_posix(),
            "FAKE_AZ_EXIT": str(exit_code),
        }
        command = [bash, wrapper.as_posix(), output, "containerapp", "show", "--name", "x"]
        return subprocess.run(
            command, capture_output=True, text=True, env=environment, cwd=tmp_path, timeout=60
        )

    return run


def test_the_old_filter_would_have_printed_part_of_a_resource_name():
    # The finding this file guards: the first version matched inside a resource ID.
    leaked = re.findall(r"Microsoft\.[A-Za-z]+(?:/[A-Za-z]+)+", TOOL_MESSAGE)
    assert "Microsoft.App/containerApps/caprivatename" in leaked


def test_a_failed_azure_call_prints_codes_and_action_names_only(quiet):
    done = quiet(3, "-")
    printed = done.stdout + done.stderr
    assert done.returncode == 3
    for text in MUST_NOT_BE_PRINTED:
        assert text not in printed, text
    assert "exit code 3" in printed
    assert "AuthorizationFailed" in printed
    assert "Microsoft.App/containerApps/write" in printed
    assert "denied" in printed
    # Nothing but the fixed lines, the code, the action name and the known word.
    lines = [line for line in printed.splitlines() if line.strip()]
    assert sorted(lines[2:]) == [
        "AuthorizationFailed",
        "Microsoft.App/containerApps/write",
        "denied",
    ]


def test_a_successful_azure_call_prints_nothing_and_keeps_its_output_in_the_file(quiet, tmp_path):
    done = quiet(0, "captured.json")
    assert done.returncode == 0
    assert done.stdout == "" and done.stderr == ""
    assert (tmp_path / "captured.json").read_text(encoding="utf-8").strip() == (
        "standard-output-line"
    )


# --------------------------------------------------------------------------- what a deploy skips
def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """GitHub's path filter: `*` stops at a `/`, `**` does not, `**/` may match nothing."""
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts))


def shipped_paths() -> list[str]:
    real = [
        path.relative_to(ROOT).as_posix()
        for folder in SHIPPED
        for path in (ROOT / folder).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    invented = [
        f"{folder}/{name}"
        for folder in SHIPPED
        for name in ("notes.md", "README.md", "deep/er/v2.md", "x.yaml", "intent/x", "docs/x.md")
    ]
    return real + invented


def test_the_path_filter_reads_patterns_the_way_github_does():
    assert glob_to_regex("**/*.md").fullmatch("prompts/scorer/v1.md")  # the old pattern
    assert glob_to_regex("**/*.md").fullmatch("README.md")
    assert glob_to_regex("*.md").fullmatch("README.md")
    assert not glob_to_regex("*.md").fullmatch("prompts/scorer/v1.md")
    assert glob_to_regex("docs/**").fullmatch("docs/a/b.md")
    assert not glob_to_regex("docs/**").fullmatch("src/docs/b.md")


def test_no_deploy_ignore_pattern_can_match_a_file_that_ships_in_the_image():
    push = load(WORKFLOWS / "deploy.yml")[True]["push"]  # YAML reads the key `on` as a boolean
    patterns = push["paths-ignore"]
    assert patterns == ["intent/**", "docs/**", "*.md"]
    assert "paths" not in push
    paths = shipped_paths()
    assert "prompts/scorer/v1.md" in paths and "src/scorer/api.py" in paths
    for pattern in patterns:
        assert not pattern.startswith("!")
        matched = [path for path in paths if glob_to_regex(pattern).fullmatch(path)]
        assert matched == [], (pattern, matched[:3])


# --------------------------------------------------------------------------- the smoke step
def test_the_remote_smoke_test_needs_nothing_installed():
    source = (ROOT / "scripts" / "smoke.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.parse(source).body:  # module level only: local mode imports uvicorn later
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


def test_the_deploy_runs_the_smoke_test_with_plain_python_and_installs_nothing():
    steps = deploy_steps()
    smoke = named(steps, "Smoke test the live app")
    assert "python3 scripts/smoke.py --remote --base-url" in smoke["run"]
    assert "::add-mask::${host}" in smoke["run"]
    assert smoke["env"] == {"DEMO_TOKEN": "${{ secrets.DEMO_TOKEN }}"}
    for step in steps:
        assert "setup-uv" not in step.get("uses", ""), step["name"]
        assert not re.search(r"\buv\b", step.get("run", "")), step["name"]


# --------------------------------------------------------------------------- dependabot
def test_dependabot_watches_the_actions_and_the_image_tags_weekly():
    config = load(ROOT / ".github" / "dependabot.yml")
    updates = {item["package-ecosystem"]: item for item in config["updates"]}
    assert set(updates) == {"github-actions", "docker"}
    for item in updates.values():
        assert item["directory"] == "/"
        assert item["schedule"] == {"interval": "weekly"}
    # The two tags the docker entry is there for.
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert len(re.findall(r"^FROM \S+:\S+", dockerfile, re.MULTILINE)) == 2
