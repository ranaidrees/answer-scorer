"""PreToolUse gate for the Bash and PowerShell tools. Deny only.

Reads the hook payload from stdin. Exit 0 lets the call continue to the normal
permission flow. Exit 2 blocks it, with the reason on stderr. Any error also
exits 2 (fail closed), because exit 1 would not block.

This is a guardrail, not a security boundary: see intent/spec.md section 10.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_RESOURCE_GROUP = "rg-answer-scorer-demo"
PROTECTED_BRANCH = "main"

BROAD_ROLES = {
    "owner",
    "contributor",
    "user access administrator",
    # Built-in role definition IDs for the same three roles.
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
    "b24988ac-6180-42a0-ab88-20f7382dd24c",
    "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9",
}

REQUIRED_RULE_TYPES = {"pull_request", "required_status_checks", "non_fast_forward", "deletion"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class Deny(Exception):
    """Raised with the reason a command is blocked."""


def _option(command: str, *names: str) -> str | None:
    """Return the value of the first matching option, without quotes."""
    for name in names:
        pattern = rf"(?<![\w-]){re.escape(name)}(?:\s+|=)(\"[^\"]*\"|'[^']*'|\S+)"
        match = re.search(pattern, command)
        if match:
            return match.group(1).strip("\"'")
    return None


def _gh_api_method(command: str) -> str:
    method = _option(command, "--method", "-X")
    if method:
        return method.upper()
    if re.search(r"(?<![\w-])(-f|-F|--field|--raw-field|--input)(\s|=)", command):
        return "POST"
    return "GET"


def _load_input_file(command: str, cwd: str | None) -> dict:
    """Load the JSON body a gh api call sends with --input <file>."""
    name = _option(command, "--input")
    if not name or name == "-":
        raise Deny("send the JSON body with --input <file> so the gate can check it")
    path = Path(name)
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Deny(f"could not read the --input file to check it: {error}") from error
    if not isinstance(body, dict):
        raise Deny("the --input file must hold a JSON object")
    return body


def _check_azure(command: str) -> None:
    az = r"\baz(?:\.cmd|\.exe)?\s+"
    azd = r"\bazd(?:\.exe)?\s+"
    match = re.search(azd + r"(up|deploy|down)\b", command, re.IGNORECASE)
    if match:
        raise Deny(
            f"'azd {match.group(1).lower()}' is blocked: the application deploys only "
            "through GitHub Actions, and teardown is the owner's job"
        )
    if re.search(az + r"group\s+delete\b", command, re.IGNORECASE):
        raise Deny("'az group delete' is blocked: the agent never deletes a resource group")
    if re.search(az + r"account\s+set\b", command, re.IGNORECASE):
        raise Deny("'az account set' is blocked: the agent never switches the subscription")
    if re.search(az + r"role\s+assignment\s+create\b", command, re.IGNORECASE):
        _check_role_assignment(command)


def _check_role_assignment(command: str) -> None:
    role = (_option(command, "--role") or "").strip().lower()
    if not role:
        raise Deny("role assignment has no --role the gate can read")
    if role.rsplit("/", 1)[-1] in BROAD_ROLES:
        raise Deny(
            "role assignments granting Owner, Contributor or User Access Administrator are blocked"
        )
    scope = _option(command, "--scope")
    group = _option(command, "--resource-group", "-g")
    if scope is None and group is None:
        raise Deny("role assignment without --scope targets the subscription: blocked")
    if scope and scope.startswith("/") and "/resourcegroups/" not in scope.lower():
        raise Deny("role assignment scope is wider than the project resource group: blocked")
    if PROJECT_RESOURCE_GROUP not in command.lower():
        raise Deny(f"role assignment must be scoped inside {PROJECT_RESOURCE_GROUP}: blocked")


def _current_branch(cwd: str | None) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=cwd or None,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise Deny("could not work out the current branch, so the push is blocked")
    return result.stdout.strip()


def _check_git(command: str, cwd: str | None) -> None:
    for match in re.finditer(
        r"\bgit(?:\.exe)?\s+(?:-\S+\s+(?:\S+\s+)?)*?push\b([^;&|\n]*)", command
    ):
        args = match.group(1).split()
        flags = [arg for arg in args if arg.startswith("-")]
        refs = [arg.strip("\"'") for arg in args if not arg.startswith("-")]
        if any(
            flag == "--force"
            or flag.startswith("--force-")
            or re.fullmatch(r"-[A-Za-z]*f[A-Za-z]*", flag)
            for flag in flags
        ):
            raise Deny("force pushes are blocked")
        if any(flag in ("--mirror", "--all") for flag in flags):
            raise Deny("'git push --mirror' and '--all' are blocked: they can push to main")
        refspecs = refs[1:]
        if any(ref.startswith("+") for ref in refspecs):
            raise Deny("force pushes are blocked")
        if not refspecs:
            if _current_branch(cwd) == PROTECTED_BRANCH:
                raise Deny("pushes to main are blocked: every change goes through a pull request")
            continue
        for ref in refspecs:
            target = ref.rsplit(":", 1)[-1]
            if target in (PROTECTED_BRANCH, f"refs/heads/{PROTECTED_BRANCH}"):
                raise Deny("pushes to main are blocked: every change goes through a pull request")
            if target == "HEAD" and _current_branch(cwd) == PROTECTED_BRANCH:
                raise Deny("pushes to main are blocked: every change goes through a pull request")


def _check_gh_repo(command: str) -> None:
    if re.search(r"\bgh(?:\.exe)?\s+repo\s+delete\b", command):
        raise Deny("'gh repo delete' is blocked")
    if re.search(r"\bgh(?:\.exe)?\s+repo\s+edit\b[^;&|\n]*--visibility", command):
        raise Deny("changing repository visibility is blocked")
    if re.search(r"\bgh(?:\.exe)?\s+repo\s+(archive|rename)\b", command):
        raise Deny("archiving or renaming the repository is blocked")


def _check_ruleset_body(body: dict) -> None:
    if body.get("enforcement") != "active":
        raise Deny("the main ruleset must keep enforcement 'active'")
    if body.get("bypass_actors"):
        raise Deny("the main ruleset must keep an empty bypass list")
    rules = body.get("rules") or []
    types = {rule.get("type") for rule in rules if isinstance(rule, dict)}
    missing = REQUIRED_RULE_TYPES - types
    if missing:
        raise Deny(f"the main ruleset would lose rules: {', '.join(sorted(missing))}")
    contexts: set[str] = set()
    for rule in rules:
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks":
            checks = (rule.get("parameters") or {}).get("required_status_checks") or []
            contexts = {check.get("context") for check in checks if isinstance(check, dict)}
    if "ci" not in contexts:
        raise Deny("the main ruleset must keep 'ci' as a required check")


def _check_gh_api(command: str, cwd: str | None) -> None:
    if not re.search(r"\bgh(?:\.exe)?\s+api\b", command):
        return
    method = _gh_api_method(command)
    lowered = command.lower()
    if "pending_deployments" in lowered and method != "GET":
        raise Deny("approving or rejecting a deployment is the owner's decision: blocked")
    if "deployment_protection_rule" in lowered and method != "GET":
        raise Deny("reviewing a deployment protection rule is blocked")
    if method not in WRITE_METHODS:
        return
    if re.search(r"/rulesets/\d+", command):
        if method == "DELETE":
            raise Deny("deleting the main ruleset is blocked")
        _check_ruleset_body(_load_input_file(command, cwd))
    if re.search(r"/branches/[^/\s\"']+/protection", command) and method == "DELETE":
        raise Deny("deleting branch protection is blocked")
    environment = re.search(r"/environments/([\w.-]+)(?![\w./-])", command)
    if environment:
        if method == "DELETE":
            raise Deny("deleting an environment is blocked")
        if method == "PUT" and not _load_input_file(command, cwd).get("reviewers"):
            raise Deny("an environment must keep its required reviewer: blocked")
    repo_root = re.search(r"\brepos/[\w.-]+/[\w.-]+(?=[\s\"']|$)", command)
    if repo_root:
        if method == "DELETE":
            raise Deny("deleting a repository is blocked")
        if re.search(r"\b(private|visibility|archived)\b\s*[=\"]", command):
            raise Deny("changing repository visibility is blocked")


def check(payload: dict) -> None:
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return
    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        raise Deny("no command found in the hook payload")
    command = command.replace("`\n", " ").replace("\\\n", " ")
    cwd = payload.get("cwd")
    _check_azure(command)
    _check_git(command, cwd)
    _check_gh_repo(command)
    _check_gh_api(command, cwd)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise Deny("hook payload is not a JSON object")
        check(payload)
    except Deny as reason:
        print(f"cloud_gate: {reason}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - fail closed on anything unexpected
        print(f"cloud_gate: blocked because the gate itself failed: {error!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
