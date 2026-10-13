"""scripts/setup_env_local.py: values are kept, generated and pushed, and never printed.

No Azure and no GitHub: every external command is replaced by a fake, or by a small
Python child process that fails the way a real tool does.
"""

from __future__ import annotations

import json
import sys

import pytest

from scripts import setup_env_local as setup

CONNECTION = "InstrumentationKey=fake-key;IngestionEndpoint=https://example.invalid/"
AZD_VALUES = {
    "FOUNDRY_ENDPOINT": "https://fake-foundry.example.invalid",
    "MODEL_DEPLOYMENT": "scorer-mini",
    "MODEL_VERSION": "2026-03-17",
    "APPLICATIONINSIGHTS_CONNECTION_STRING": CONNECTION,
    "CONTAINER_APP_NAME": "fake-app",
    "CONTAINER_APP_FQDN": "fake-app.example.invalid",
    "AZURE_RESOURCE_GROUP": "fake-group",
}
FAKE_ACCOUNT = {
    "tenantId": "fake-tenant",
    "id": "fake-subscription",
    "clientId": "fake-client",
    "user": {"name": "fake-user-name"},
}
FAKE_IDS = ["fake-tenant", "fake-subscription", "fake-client", "fake-user-name"]

# What an Azure authorisation error looks like: it names the caller, the caller's object
# ID and the subscription. All of these are made up.
FAKE_GUID = "11111111-2222-3333-4444-555555555555"
FAKE_SUBSCRIPTION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FAKE_ADDRESS = "someone@example.invalid"
FAKE_CONNECTION = (
    "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
    "IngestionEndpoint=https://fake-ingest.example.invalid/"
)
FAKE_TOKEN = "plain-demo-token-value"
TOOL_MESSAGE = (
    f"ERROR: (AuthorizationFailed) The client '{FAKE_ADDRESS}' with object id '{FAKE_GUID}' "
    f"does not have authorization over scope '/subscriptions/{FAKE_SUBSCRIPTION}/resourceGroups/"
    f"fake-group'. Connection {FAKE_CONNECTION} and token {FAKE_TOKEN}."
)
MUST_NOT_APPEAR = [
    FAKE_GUID,
    FAKE_SUBSCRIPTION,
    FAKE_ADDRESS,
    "InstrumentationKey",
    "00000000-0000-0000-0000-000000000000",
    "fake-ingest.example.invalid",
    FAKE_TOKEN,
]
# Quote-free, so it passes through any shell's argument rules unchanged.
CHILD_CODE = (
    "import sys,pathlib;sys.stderr.write(pathlib.Path(sys.argv[1]).read_text());sys.exit(3)"
)


class FakeCommands:
    """Stands in for `run`: records every call and answers the read commands.

    `fail_on` maps a piece of a command line to the tool message the failure carries.
    """

    def __init__(self, *, fail_on: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.fail_on = fail_on or {}

    def __call__(self, step, command, hidden, *, stdin=None):
        assert isinstance(hidden, list), f"{step} was not given the values to mask"
        self.calls.append((command, stdin))
        for piece, detail in self.fail_on.items():
            if piece in " ".join(command):
                raise setup.SetupError(f"{step} failed (exit 1)", detail)
        if command[:3] == ["azd", "env", "get-values"]:
            return setup.render_env({**AZD_VALUES, "AZURE_SUBSCRIPTION_ID": "fake-subscription"})
        if command[:3] == ["az", "account", "show"] or command[:3] == ["az", "identity", "show"]:
            return json.dumps(FAKE_ACCOUNT)
        return ""


@pytest.fixture
def commands(monkeypatch, tmp_path):
    fake = FakeCommands()
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "run", fake)
    return fake


@pytest.fixture
def failing_tool(monkeypatch, tmp_path):
    """A real child process that writes TOOL_MESSAGE to stderr and exits 3."""
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    message = tmp_path / "tool-message.txt"
    message.write_text(TOOL_MESSAGE, encoding="utf-8")
    return [sys.executable, "-c", CHILD_CODE, str(message)]


def write_env_file(tmp_path) -> None:
    values = {**AZD_VALUES, "DEMO_TOKEN": FAKE_TOKEN, "ANSWER_HASH_SALT": "plain-salt-value"}
    (tmp_path / ".env.local").write_text(setup.render_env(values), encoding="utf-8")


def test_round_trip_keeps_a_connection_string_intact():
    values = {"A": CONNECTION, "B": 'quote " and \\ backslash', "C": ""}
    assert setup.parse_env(setup.render_env(values)) == values


def test_parse_reads_unquoted_values_and_skips_comments():
    text = '# comment\n\nPLAIN=value=with=equals\nQUOTED="two words"\nnot a pair\n'
    assert setup.parse_env(text) == {"PLAIN": "value=with=equals", "QUOTED": "two words"}


def test_merge_generates_a_token_and_a_salt():
    merged = setup.merge({}, AZD_VALUES)
    assert set(merged) == {*setup.AZD_KEYS, *setup.GENERATED_KEYS}
    assert len(merged["DEMO_TOKEN"]) >= 32
    assert merged["DEMO_TOKEN"] != merged["ANSWER_HASH_SALT"]


def test_merge_keeps_an_existing_token_salt_and_extra_keys():
    existing = {"DEMO_TOKEN": "kept-token", "ANSWER_HASH_SALT": "kept-salt", "EXTRA": "kept"}
    merged = setup.merge({**existing, "MODEL_VERSION": "stale"}, AZD_VALUES)
    assert merged["DEMO_TOKEN"] == "kept-token"
    assert merged["ANSWER_HASH_SALT"] == "kept-salt"
    assert merged["EXTRA"] == "kept"
    assert merged["MODEL_VERSION"] == "2026-03-17"


def test_merge_names_a_missing_key_without_values():
    incomplete = {key: value for key, value in AZD_VALUES.items() if key != "FOUNDRY_ENDPOINT"}
    with pytest.raises(setup.SetupError, match="FOUNDRY_ENDPOINT"):
        setup.merge({}, incomplete)


def test_mask_removes_known_values():
    assert setup.mask("bad value s3cret here", ["s3cret", ""]) == "bad value *** here"


def test_mask_removes_ids_addresses_and_connection_strings_it_was_not_told_about():
    masked = setup.mask(TOOL_MESSAGE, [])
    for text in [item for item in MUST_NOT_APPEAR if item != FAKE_TOKEN]:
        assert text not in masked
    assert "AuthorizationFailed" in masked
    assert "fake-group" in masked


def test_mask_handles_a_sign_in_name_with_a_provider_prefix():
    assert "example.invalid" not in setup.mask("user live.com#someone@example.invalid", [])


def test_a_failing_tool_leaves_only_the_step_and_the_exit_code(failing_tool):
    with pytest.raises(setup.SetupError) as raised:
        setup.run("fake step", failing_tool, [FAKE_TOKEN])
    assert str(raised.value) == "fake step failed (exit 3)"
    for text in MUST_NOT_APPEAR:
        assert text not in raised.value.detail
    assert "AuthorizationFailed" in raised.value.detail


@pytest.mark.parametrize("debug", [False, True])
def test_write_failure_prints_no_identifier(monkeypatch, failing_tool, capsys, debug):
    monkeypatch.setattr(setup, "require_ignored", lambda: None)
    monkeypatch.setattr(setup, "AZD_GET_VALUES", failing_tool)

    assert setup.main(["--write", *(["--debug"] if debug else [])]) == 1

    captured = capsys.readouterr()
    for text in [item for item in MUST_NOT_APPEAR if item != FAKE_TOKEN]:
        assert text not in captured.out
        assert text not in captured.err
    assert "azd env get-values failed (exit 3)" in captured.err
    assert ("AuthorizationFailed" in captured.err) is debug


@pytest.mark.parametrize("debug", [False, True])
def test_push_failure_prints_no_identifier_or_value(
    monkeypatch, tmp_path, failing_tool, capsys, debug
):
    # The account read is the first call, before any ID is known to the script.
    write_env_file(tmp_path)
    monkeypatch.setattr(setup, "AZ_ACCOUNT_SHOW", failing_tool)

    assert setup.main(["--push", *(["--debug"] if debug else [])]) == 1

    captured = capsys.readouterr()
    for text in MUST_NOT_APPEAR:
        assert text not in captured.out
        assert text not in captured.err
    assert "az account show failed (exit 3)" in captured.err
    assert ("AuthorizationFailed" in captured.err) is debug
    assert "set:" not in captured.out


def test_write_prints_key_names_only(commands, tmp_path, capsys):
    assert setup.main(["--write"]) == 0
    written = setup.parse_env((tmp_path / ".env.local").read_text(encoding="utf-8"))
    assert set(written) == {*setup.AZD_KEYS, *setup.GENERATED_KEYS}
    assert "AZURE_SUBSCRIPTION_ID" not in written
    output = capsys.readouterr().out
    assert "DEMO_TOKEN" in output
    for value in written.values():
        assert value not in output


def test_write_twice_keeps_the_token(commands, tmp_path):
    setup.main(["--write"])
    first = setup.parse_env((tmp_path / ".env.local").read_text(encoding="utf-8"))
    setup.main(["--write"])
    second = setup.parse_env((tmp_path / ".env.local").read_text(encoding="utf-8"))
    assert second == first


def test_write_refuses_when_the_file_is_not_ignored(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "run", FakeCommands(fail_on={"check-ignore": ""}))
    assert setup.main(["--write"]) == 1
    assert not (tmp_path / ".env.local").exists()
    assert "not git-ignored" in capsys.readouterr().err


def test_push_prints_names_only_and_sends_github_values_on_stdin(commands, tmp_path, capsys):
    write_env_file(tmp_path)
    values = setup.parse_env((tmp_path / ".env.local").read_text(encoding="utf-8"))

    assert setup.main(["--push"]) == 0

    captured = capsys.readouterr()
    for value in [*values.values(), *FAKE_IDS]:
        assert value not in captured.out
        assert value not in captured.err
    for name in ("demo-token", "answer-hash-salt", "AZURE_CLIENT_ID_EVAL", "MODEL_VERSION"):
        assert name in captured.out

    # The IDs are read before anything is changed.
    assert commands.calls[0][0][:3] == ["az", "account", "show"]

    setters = [
        (command, stdin) for command, stdin in commands.calls if command[:2] == ["gh", "secret"]
    ]
    setters += [(c, stdin) for c, stdin in commands.calls if c[:3] == ["gh", "variable", "set"]]
    assert setters, "no GitHub value was set"
    for command, stdin in setters:
        assert stdin, f"{command[:4]} was given no value on stdin"
        assert stdin not in command
    # The IDs and the endpoint are secrets: a variable is printed in public workflow logs.
    secrets = {
        command[3]: stdin
        for command, stdin in setters
        if command[:3] == ["gh", "secret", "set"] and "--env" not in command
    }
    assert secrets == {
        "APPLICATIONINSIGHTS_CONNECTION_STRING": CONNECTION,
        "FOUNDRY_ENDPOINT": AZD_VALUES["FOUNDRY_ENDPOINT"],
        "AZURE_TENANT_ID": "fake-tenant",
        "AZURE_SUBSCRIPTION_ID": "fake-subscription",
        "AZURE_CLIENT_ID_DEPLOY": "fake-client",
        "AZURE_CLIENT_ID_EVAL": "fake-client",
    }
    variables = {command[3]: stdin for command, stdin in setters if command[1] == "variable"}
    assert variables == {
        key: AZD_VALUES[key]
        for key in (
            "AZURE_RESOURCE_GROUP",
            "CONTAINER_APP_NAME",
            "MODEL_DEPLOYMENT",
            "MODEL_VERSION",
        )
    }
    assert not set(variables) & set(setup.IDENTIFYING_SECRETS)
    for name in setup.IDENTIFYING_SECRETS:
        assert f"set: GitHub repository secret {name}" in captured.out
        assert f"set: GitHub repository variable {name}" not in captured.out
    environment = [command for command, _ in setters if "--env" in command]
    assert environment == [["gh", "secret", "set", "DEMO_TOKEN", "--env", "demo"]]

    update = next(command for command, _ in commands.calls if "update" in command)
    assert "DEMO_TOKEN=secretref:demo-token" in update
    assert "ANSWER_HASH_SALT=secretref:answer-hash-salt" in update


def test_the_five_identifiers_are_secrets_and_never_variables():
    assert set(setup.IDENTIFYING_SECRETS) == {
        "AZURE_TENANT_ID",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_CLIENT_ID_DEPLOY",
        "AZURE_CLIENT_ID_EVAL",
        "FOUNDRY_ENDPOINT",
    }
    assert not set(setup.VARIABLES_FROM_FILE) & set(setup.IDENTIFYING_SECRETS)


def test_push_deletes_an_old_variable_for_each_identifier(commands, tmp_path, capsys):
    write_env_file(tmp_path)

    assert setup.main(["--push"]) == 0

    deleted = [
        command for command, _ in commands.calls if command[:3] == ["gh", "variable", "delete"]
    ]
    assert [command[3] for command in deleted] == list(setup.IDENTIFYING_SECRETS)
    assert all(len(command) == 4 for command in deleted), "a name only, never a value"
    # Each secret is set before the variable of the same name is deleted.
    order = [command[1:4] for command, _ in commands.calls if command[0] == "gh"]
    for name in setup.IDENTIFYING_SECRETS:
        assert order.index(["secret", "set", name]) < order.index(["variable", "delete", name])
    output = capsys.readouterr().out
    for name in setup.IDENTIFYING_SECRETS:
        assert f"removed: GitHub repository variable {name}" in output


def test_push_ignores_an_old_variable_that_is_not_there(monkeypatch, tmp_path, capsys):
    message = "failed to delete variable: HTTP 404: Not Found"
    fake = FakeCommands(fail_on={"variable delete": message})
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "run", fake)
    write_env_file(tmp_path)

    assert setup.main(["--push"]) == 0

    captured = capsys.readouterr()
    assert "removed:" not in captured.out and "HTTP" not in captured.err
    assert "set: GitHub repository variable MODEL_VERSION" in captured.out
    assert len([c for c, _ in fake.calls if c[:3] == ["gh", "variable", "delete"]]) == 5


def test_push_fails_when_an_old_variable_cannot_be_deleted(monkeypatch, tmp_path, capsys):
    fake = FakeCommands(fail_on={"variable delete": "gh: Forbidden (HTTP 403)"})
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "run", fake)
    write_env_file(tmp_path)

    assert setup.main(["--push"]) == 1

    captured = capsys.readouterr()
    assert "GitHub variable AZURE_TENANT_ID removal failed" in captured.err
    assert "HTTP" not in captured.err and "removed:" not in captured.out


def test_push_carries_on_when_the_demo_environment_does_not_exist(monkeypatch, tmp_path, capsys):
    fake = FakeCommands(fail_on={"environments/demo": "gh: Not Found (HTTP 404)"})
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "run", fake)
    write_env_file(tmp_path)

    assert setup.main(["--push"]) == 0

    output = capsys.readouterr().out
    assert "skipped: GitHub environment secret DEMO_TOKEN" in output
    assert "set: GitHub repository variable MODEL_VERSION" in output
    assert not [command for command, _ in fake.calls if "--env" in command]


@pytest.mark.parametrize(
    "fail_on",
    [
        {"environments/demo": "gh: Forbidden (HTTP 403)"},
        {"--env demo": "failed to fetch public key: HTTP 404"},
    ],
    ids=["lookup fails for another reason", "the secret itself cannot be set"],
)
def test_push_fails_when_the_environment_secret_fails_for_any_other_reason(
    monkeypatch, tmp_path, capsys, fail_on
):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "run", FakeCommands(fail_on=fail_on))
    write_env_file(tmp_path)

    assert setup.main(["--push"]) == 1

    captured = capsys.readouterr()
    assert "skipped:" not in captured.out
    assert "set: GitHub repository secret APPLICATIONINSIGHTS_CONNECTION_STRING" in captured.out
    assert "set: GitHub environment secret DEMO_TOKEN" not in captured.out
    assert "HTTP" not in captured.err


def test_push_needs_the_file_first(commands, capsys):
    assert setup.main(["--push"]) == 1
    assert "--write first" in capsys.readouterr().err
