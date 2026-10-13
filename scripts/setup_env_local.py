"""Write `.env.local` from the azd environment, and push its values to Azure and GitHub.

Claude Code is not allowed to read `.env.local`, so this script does everything that
touches it. It never prints a value or an ID: only the names of what it wrote or set.

    uv run python scripts/setup_env_local.py --write
    uv run python scripts/setup_env_local.py --push

`--write` reads `azd env get-values` and writes the git-ignored `.env.local` in the
repository root, adding a generated demo token and answer-hash salt. A token or salt
already in the file is kept, so running it twice is safe.

`--push` reads `.env.local` and sets the Container App secrets and their `secretref`
variables, the GitHub repository secret, the `demo` environment secret and the GitHub
repository variables. Values travel as subprocess arguments or on stdin, never to stdout.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE_NAME = ".env.local"
GITHUB_ENVIRONMENT = "demo"
DEPLOY_IDENTITY = "id-deploy"
EVAL_IDENTITY = "id-eval"

# Copied from the azd environment (the Bicep outputs) into .env.local.
AZD_KEYS = (
    "FOUNDRY_ENDPOINT",
    "MODEL_DEPLOYMENT",
    "MODEL_VERSION",
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "CONTAINER_APP_NAME",
    "CONTAINER_APP_FQDN",
    "AZURE_RESOURCE_GROUP",
)
# Generated here, once. The Container App holds them as secrets.
GENERATED_KEYS = ("DEMO_TOKEN", "ANSWER_HASH_SALT")
# Container App secret name for each generated key.
APP_SECRETS = {"DEMO_TOKEN": "demo-token", "ANSWER_HASH_SALT": "answer-hash-salt"}
# GitHub repository variables copied straight from .env.local.
VARIABLES_FROM_FILE = (
    "AZURE_RESOURCE_GROUP",
    "CONTAINER_APP_NAME",
    "FOUNDRY_ENDPOINT",
    "MODEL_DEPLOYMENT",
    "MODEL_VERSION",
)


class SetupError(Exception):
    """A step failed. The message never contains a value."""


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=value lines, with or without double quotes, as azd and this script write them."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def render_env(values: dict[str, str]) -> str:
    """Render KEY="value" lines. Double quotes keep the semicolons in a connection string intact."""
    lines = []
    for key, value in values.items():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}="{escaped}"')
    return "\n".join(lines) + "\n"


def merge(existing: dict[str, str], azd_values: dict[str, str]) -> dict[str, str]:
    """Build the new file: azd values win, a token or salt already present is kept."""
    missing = [key for key in AZD_KEYS if not azd_values.get(key)]
    if missing:
        raise SetupError(f"the azd environment has no value for: {', '.join(missing)}")
    merged = {key: azd_values[key] for key in AZD_KEYS}
    for key in GENERATED_KEYS:
        merged[key] = existing.get(key) or secrets.token_urlsafe(32)
    # Anything else a later slice added to the file is carried over untouched.
    for key, value in existing.items():
        merged.setdefault(key, value)
    return merged


def scrub(text: str, hidden: list[str]) -> str:
    """Remove known values from an error message before it is shown."""
    for value in sorted({item for item in hidden if item}, key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def run(
    step: str,
    command: list[str],
    *,
    stdin: str | None = None,
    hidden: list[str] | None = None,
) -> str:
    """Run a command quietly and return its stdout. Nothing it prints reaches the terminal."""
    executable = shutil.which(command[0])
    if executable is None:
        raise SetupError(f"{step}: '{command[0]}' is not installed or not on PATH")
    result = subprocess.run(
        [executable, *command[1:]],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        detail = scrub(result.stderr.strip(), [*(hidden or []), stdin or ""])
        raise SetupError(f"{step} failed (exit {result.returncode}): {detail}")
    return result.stdout


def env_file() -> Path:
    return ROOT / ENV_FILE_NAME


def require_ignored() -> None:
    """Refuse to write the file unless git ignores it."""
    try:
        run("git check-ignore", ["git", "check-ignore", "-q", ENV_FILE_NAME])
    except SetupError as error:
        raise SetupError(f"{ENV_FILE_NAME} is not git-ignored, so it is not written") from error


def write() -> list[str]:
    """Write .env.local and return the names of the keys in it."""
    require_ignored()
    azd_values = parse_env(run("azd env get-values", ["azd", "env", "get-values"]))
    path = env_file()
    existing = parse_env(path.read_text(encoding="utf-8")) if path.is_file() else {}
    merged = merge(existing, azd_values)
    path.write_text(render_env(merged), encoding="utf-8", newline="\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows keeps its own permissions.
    return list(merged)


def push(done: list[str], skipped: list[str]) -> None:
    """Push values to Azure and GitHub, recording by name what was set and what was skipped.

    The lists are filled as it goes, so a failure part-way still reports the steps before it.
    """
    path = env_file()
    if not path.is_file():
        raise SetupError(f"{ENV_FILE_NAME} does not exist: run this script with --write first")
    values = parse_env(path.read_text(encoding="utf-8"))
    needed = (*AZD_KEYS, *GENERATED_KEYS)
    missing = [key for key in needed if not values.get(key)]
    if missing:
        raise SetupError(f"{ENV_FILE_NAME} has no value for: {', '.join(missing)}")
    hidden = [values[key] for key in needed]
    group = values["AZURE_RESOURCE_GROUP"]
    app = values["CONTAINER_APP_NAME"]

    # Container App: the secrets first, then the variables that point at them.
    pairs = [f"{name}={values[key]}" for key, name in APP_SECRETS.items()]
    run(
        "Container App secrets",
        ["az", "containerapp", "secret", "set", "-g", group, "-n", app, "--secrets", *pairs]
        + ["--only-show-errors", "-o", "none"],
        hidden=hidden,
    )
    done += [f"Container App secret {name}" for name in APP_SECRETS.values()]
    references = [f"{key}=secretref:{name}" for key, name in APP_SECRETS.items()]
    run(
        "Container App environment variables",
        ["az", "containerapp", "update", "-g", group, "-n", app, "--set-env-vars", *references]
        + ["--only-show-errors", "-o", "none"],
        hidden=hidden,
    )
    done += [f"Container App variable {key} (secretref)" for key in APP_SECRETS]

    # GitHub secrets, passed on stdin.
    name = "APPLICATIONINSIGHTS_CONNECTION_STRING"
    run(f"GitHub secret {name}", ["gh", "secret", "set", name], stdin=values[name], hidden=hidden)
    done.append(f"GitHub repository secret {name}")
    try:
        run(
            "GitHub environment secret DEMO_TOKEN",
            ["gh", "secret", "set", "DEMO_TOKEN", "--env", GITHUB_ENVIRONMENT],
            stdin=values["DEMO_TOKEN"],
            hidden=hidden,
        )
        done.append(f"GitHub environment secret DEMO_TOKEN ({GITHUB_ENVIRONMENT})")
    except SetupError as error:
        # The lead creates the environment; until then this one step is skipped.
        skipped.append(f"GitHub environment secret DEMO_TOKEN ({GITHUB_ENVIRONMENT}): {error}")

    # GitHub variables. The IDs are read now and never stored in a file.
    account = json.loads(run("az account show", ["az", "account", "show", "-o", "json"]))
    variables = {
        "AZURE_TENANT_ID": account["tenantId"],
        "AZURE_SUBSCRIPTION_ID": account["id"],
        "AZURE_CLIENT_ID_DEPLOY": identity_client_id(group, DEPLOY_IDENTITY),
        "AZURE_CLIENT_ID_EVAL": identity_client_id(group, EVAL_IDENTITY),
    }
    variables.update({key: values[key] for key in VARIABLES_FROM_FILE})
    hidden += list(variables.values())
    for key, value in variables.items():
        run(f"GitHub variable {key}", ["gh", "variable", "set", key], stdin=value, hidden=hidden)
        done.append(f"GitHub repository variable {key}")


def identity_client_id(group: str, name: str) -> str:
    output = run(
        f"az identity show {name}",
        ["az", "identity", "show", "-g", group, "-n", name, "-o", "json"],
    )
    return json.loads(output)["clientId"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write .env.local from azd")
    mode.add_argument("--push", action="store_true", help="push .env.local to Azure and GitHub")
    args = parser.parse_args(argv)
    done: list[str] = []
    skipped: list[str] = []
    status = 0
    try:
        if args.write:
            names = write()
            print(f"Wrote {ENV_FILE_NAME} with keys: {', '.join(names)}")
        else:
            push(done, skipped)
    except SetupError as error:
        print(f"error: {error}", file=sys.stderr)
        status = 1
    for item in done:
        print(f"set: {item}")
    for item in skipped:
        print(f"skipped: {item}")
    return status


if __name__ == "__main__":
    sys.exit(main())
