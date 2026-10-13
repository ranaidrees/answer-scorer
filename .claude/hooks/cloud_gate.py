"""PreToolUse gate for the Bash and PowerShell tools. Deny only.

Reads the hook payload from stdin. Exit 0 lets the call continue to the normal
permission flow. Exit 2 blocks it, with the reason on stderr. Any error also
exits 2 (fail closed), because exit 1 would not block.

The command is split into segments at shell separators outside quotes, and every
rule runs on every segment, so a blocked command cannot hide behind an allowed one.

Known limits: the gate matches text, so it also fires on blocked commands quoted in
prose (pass long text with a file instead), and it does not see what a script does
once it runs. It is a guardrail, not a security boundary: see intent/spec.md section 10.
"""

from __future__ import annotations

import json
import os
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
UNREADABLE = "UNREADABLE"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE", UNREADABLE}
REPO_KEYS = ("private", "visibility", "archived")
GRAPHQL_BLOCKED = (
    "approveDeployments",
    "rejectDeployments",
    "deleteRepositoryRuleset",
    "updateRepositoryRuleset",
    "deleteEnvironment",
    "updateEnvironment",
    "deleteBranchProtectionRule",
    "updateBranchProtectionRule",
    "deleteRepository",
    "updateRepository",
    "archiveRepository",
)

# A tool name (optionally quoted, as in PowerShell's & "az.cmd"), then any global flags
# or the PowerShell stop-parsing token before the subcommand.
_VALUE = r"(?:\"[^\"]*\"|'[^']*'|\S+)"
_FLAGS = r"(?:(?:--%|-{1,2}[\w-]+(?:(?:=|\s+)" + _VALUE + r")?)\s+)*?"
_AZ = r"(?<![\w.-])az(?:\.cmd|\.exe)?[\"']?\s+" + _FLAGS
_AZD = r"(?<![\w.-])azd(?:\.exe)?[\"']?\s+" + _FLAGS
_GH = r"(?<![\w.-])gh(?:\.exe)?[\"']?\s+"
_GIT = r"(?<![\w.-])git(?:\.exe)?[\"']?\s+"
_MOVES = re.compile(
    r"(?<![\w.-])(?:cd|pushd|popd|chdir|Set-Location|Push-Location|sl)(?![\w-])"
    r"|(?<![\w.-])git(?:\.exe)?[\"']?\s+(?:\S+\s+)*?(?:checkout|switch|-C|--git-dir|--work-tree)(?![\w-])",
    re.IGNORECASE,
)


class Deny(Exception):
    """Raised with the reason a command is blocked."""


def _split(command: str, *, respect_quotes: bool) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote = ""
    for char in command:
        if quote:
            if char == quote:
                quote = ""
            current.append(char)
        elif respect_quotes and char in "\"'":
            quote = char
            current.append(char)
        elif char in ";&|\n":
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
    segments.append("".join(current))
    return [segment.strip() for segment in segments if segment.strip()]


def _segments(command: str) -> tuple[list[str], bool]:
    """Split a command line at ; & | and newlines, and say whether it is one command.

    Quote tracking can be thrown by a stray apostrophe or an escaped quote, which would
    glue later commands onto the first. So the rules run over both the quote-aware split
    and a quote-blind one, and a command counts as standing alone only if both agree.
    """
    aware = _split(command, respect_quotes=True)
    blind = _split(command, respect_quotes=False)
    merged = list(dict.fromkeys(aware + blind))
    return merged, len(aware) == 1 and len(blind) == 1


def _option(command: str, *names: str) -> str | None:
    """Return the value of the first matching option, without quotes."""
    for name in names:
        pattern = rf"(?<![\w-]){re.escape(name)}(?:\s+|=)(\"[^\"]*\"|'[^']*'|\S+)"
        match = re.search(pattern, command)
        if match:
            return match.group(1).strip("\"'")
    return None


def _gh_api_method(command: str) -> str:
    """Work out the HTTP method the way gh does, including attached forms like -XDELETE."""
    values = re.findall(r"(?<![\w-])(?:--method(?:\s+|=)|-X\s*=?\s*)[\"']?([^\s\"']*)", command)
    methods = {value.upper() for value in values}
    if any(not re.fullmatch(r"[A-Z]+", method) for method in methods):
        return UNREADABLE
    # gh uses the last method given; the gate takes the most dangerous one.
    for method in ("DELETE", "PUT", "PATCH", "POST"):
        if method in methods:
            return method
    if methods:
        return "GET"
    if re.search(r"(?<![\w-])(?:-[fF]|--field|--raw-field|--input)(?![\w-])", command):
        return "POST"
    if re.search(r"(?<![\w-])-[fF]\S", command):
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


def _check_azure(segment: str) -> None:
    match = re.search(_AZD + r"(up|deploy|down)\b", segment, re.IGNORECASE)
    if match:
        raise Deny(
            f"'azd {match.group(1).lower()}' is blocked: the application deploys only "
            "through GitHub Actions, and teardown is the owner's job"
        )
    if re.search(_AZ + r"group\s+delete\b", segment, re.IGNORECASE):
        raise Deny("'az group delete' is blocked: the agent never deletes a resource group")
    if re.search(_AZ + r"account\s+set\b", segment, re.IGNORECASE):
        raise Deny("'az account set' is blocked: the agent never switches the subscription")
    if re.search(_AZ + r"role\s+assignment\s+create\b", segment, re.IGNORECASE):
        _check_role_assignment(segment)


def _check_role_assignment(segment: str) -> None:
    role = (_option(segment, "--role") or "").strip().lower()
    if not role:
        raise Deny("role assignment has no --role the gate can read")
    if "$" in role or "`" in role:
        raise Deny("write the role name out in full so the gate can read it")
    if role.rsplit("/", 1)[-1] in BROAD_ROLES:
        raise Deny(
            "role assignments granting Owner, Contributor or User Access Administrator are blocked"
        )
    scope = _option(segment, "--scope")
    if scope is None:
        raise Deny("role assignment without --scope targets the subscription: blocked")
    if "$" in scope or "`" in scope:
        raise Deny("write the --scope out in full so the gate can read it")
    inside = f"/resourcegroups/{PROJECT_RESOURCE_GROUP}"
    lowered = scope.lower()
    if not (lowered.endswith(inside) or inside + "/" in lowered):
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


def _implicit_push_target(cwd: str | None, moved: bool) -> str:
    """The branch a bare or HEAD push would send, if the gate can know it."""
    if moved:
        raise Deny(
            "name the branch in the push: this command changes folder or branch first, "
            "so the gate cannot tell what a bare push would send"
        )
    return _current_branch(cwd)


def _check_git(segment: str, cwd: str | None, moved: bool) -> None:
    match = re.search(_GIT + r"(?:-\S+\s+(?:\S+\s+)?)*?push\b(.*)", segment, re.DOTALL)
    if not match:
        return
    to_main = "pushes to main are blocked: every change goes through a pull request"
    args = [arg.strip("\"'`()") for arg in match.group(1).split()]
    args = [arg for arg in args if arg and "<" not in arg and ">" not in arg]
    flags = [arg for arg in args if arg.startswith("-")]
    refs = [arg for arg in args if not arg.startswith("-")]
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
        if _implicit_push_target(cwd, moved) == PROTECTED_BRANCH:
            raise Deny(to_main)
        return
    for ref in refspecs:
        target = ref.rsplit(":", 1)[-1]
        if target in (PROTECTED_BRANCH, f"refs/heads/{PROTECTED_BRANCH}"):
            raise Deny(to_main)
        if target in ("HEAD", "@") and _implicit_push_target(cwd, moved) == PROTECTED_BRANCH:
            raise Deny(to_main)


def _check_gh_repo(segment: str) -> None:
    if re.search(_GH + r"repo\s+delete\b", segment):
        raise Deny("'gh repo delete' is blocked")
    if re.search(_GH + r"repo\s+edit\b.*--visibility", segment, re.DOTALL):
        raise Deny("changing repository visibility is blocked")
    if re.search(_GH + r"repo\s+(archive|rename)\b", segment):
        raise Deny("archiving or renaming the repository is blocked")


def _evals_gate_exists(cwd: str | None) -> bool:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    return bool(root) and (Path(root) / ".github" / "workflows" / "evals.yml").is_file()


def _check_ruleset_body(body: dict, cwd: str | None) -> None:
    if body.get("target") != "branch":
        raise Deny("the main ruleset must keep target 'branch'")
    ref_name = (body.get("conditions") or {}).get("ref_name") or {}
    included = set(ref_name.get("include") or [])
    if not included & {"~DEFAULT_BRANCH", "~ALL", f"refs/heads/{PROTECTED_BRANCH}"}:
        raise Deny("the main ruleset must keep covering the default branch")
    if ref_name.get("exclude"):
        raise Deny("the main ruleset must not exclude any branch")
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
    if "evals" not in contexts and _evals_gate_exists(cwd):
        raise Deny("the main ruleset must keep 'evals' as a required check")


def _names_repo_root(segment: str) -> bool:
    """True if a token is the repository itself: repos/<owner>/<repo>, in any spelling.

    Covers a leading slash, a full URL, gh placeholders and shell variables (where one
    variable may stand for owner/repo), but not deeper paths such as .../pulls.
    """
    for token in segment.split():
        path = re.sub(r"^https?://[^/]+", "", token.strip("\"'`()")).lstrip("/")
        parts = path.split("/")
        if parts[0] != "repos" or len(parts) < 2 or not all(parts[1:]):
            continue
        if len(parts) == 3 or (len(parts) == 2 and "$" in parts[1]):
            return True
    return False


def _check_gh_api(segment: str, cwd: str | None, alone: bool) -> None:
    if not re.search(_GH + r"api\b", segment):
        return
    method = _gh_api_method(segment)
    lowered = segment.lower()
    if re.search(r"\bgraphql\b", lowered):
        for name in GRAPHQL_BLOCKED:
            if name.lower() in lowered:
                raise Deny(f"the GraphQL mutation {name} is blocked")
    if "pending_deployments" in lowered and method != "GET":
        raise Deny("approving or rejecting a deployment is the owner's decision: blocked")
    if "deployment_protection_rule" in lowered and method != "GET":
        raise Deny("reviewing a deployment protection rule is blocked")
    if method not in WRITE_METHODS:
        return
    if re.search(r"/branches/[^/\s\"']+/protection", segment) and method == "DELETE":
        raise Deny("deleting branch protection is blocked")
    ruleset = re.search(r"/rulesets/[^\s\"']+", segment)
    environment = re.search(r"/environments/[^\s\"'/]+(?=[\s\"']|$)", segment)
    repo_root = _names_repo_root(segment)
    if not (ruleset or environment or repo_root):
        return
    if method == UNREADABLE:
        raise Deny("write the HTTP method out in full so the gate can read it: blocked")
    if method == "DELETE":
        raise Deny("deleting a repository, a ruleset or an environment is blocked")
    if repo_root:
        if re.search(rf"({'|'.join(REPO_KEYS)})\s*[=\"]", segment):
            raise Deny("changing repository visibility is blocked")
        if _option(segment, "--input") and not alone:
            raise Deny("send a repository change as the only command in the call: blocked")
        if _option(segment, "--input") and any(
            key in _load_input_file(segment, cwd) for key in REPO_KEYS
        ):
            raise Deny("changing repository visibility is blocked")
        return
    if not alone:
        raise Deny(
            "a ruleset or environment change must be the only command in the call, "
            "so the gate checks exactly the body that is sent: blocked"
        )
    if ruleset:
        _check_ruleset_body(_load_input_file(segment, cwd), cwd)
    elif method == "PUT" and not _load_input_file(segment, cwd).get("reviewers"):
        raise Deny("an environment must keep its required reviewer: blocked")


def check(payload: dict) -> None:
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return
    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        raise Deny("no command found in the hook payload")
    command = command.replace("`\r\n", " ").replace("`\n", " ").replace("\\\n", " ")
    cwd = payload.get("cwd")
    segments, alone = _segments(command)
    moved = bool(_MOVES.search(command))
    for segment in segments:
        _check_azure(segment)
        _check_git(segment, cwd, moved)
        _check_gh_repo(segment)
        _check_gh_api(segment, cwd, alone=alone)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
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
