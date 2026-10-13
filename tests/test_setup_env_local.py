"""scripts/setup_env_local.py: values are kept, generated and pushed, and never printed.

No Azure and no GitHub: every external command is replaced by a fake.
"""

from __future__ import annotations

import json

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
FAKE_IDS = {"tenantId": "fake-tenant", "id": "fake-subscription", "clientId": "fake-client"}


class FakeCommands:
    """Stands in for `run`: records every call and answers the read commands."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.fail_on = fail_on

    def __call__(self, step, command, *, stdin=None, hidden=None):
        self.calls.append((command, stdin))
        if self.fail_on and self.fail_on in " ".join(command):
            raise setup.SetupError(f"{step} failed (exit 1): not found")
        if command[:3] == ["azd", "env", "get-values"]:
            return setup.render_env({**AZD_VALUES, "AZURE_SUBSCRIPTION_ID": "fake-subscription"})
        if command[:3] == ["az", "account", "show"] or command[:3] == ["az", "identity", "show"]:
            return json.dumps(FAKE_IDS)
        return ""


@pytest.fixture
def commands(monkeypatch, tmp_path):
    fake = FakeCommands()
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "run", fake)
    return fake


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


def test_scrub_removes_known_values():
    assert setup.scrub("bad value s3cret here", ["s3cret", ""]) == "bad value *** here"


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
    monkeypatch.setattr(setup, "run", FakeCommands(fail_on="check-ignore"))
    assert setup.main(["--write"]) == 1
    assert not (tmp_path / ".env.local").exists()
    assert "not git-ignored" in capsys.readouterr().err


def test_push_prints_names_only_and_sends_github_values_on_stdin(commands, tmp_path, capsys):
    setup.main(["--write"])
    values = setup.parse_env((tmp_path / ".env.local").read_text(encoding="utf-8"))
    capsys.readouterr()
    commands.calls.clear()

    assert setup.main(["--push"]) == 0

    captured = capsys.readouterr()
    for value in [*values.values(), *FAKE_IDS.values()]:
        assert value not in captured.out
        assert value not in captured.err
    for name in ("demo-token", "answer-hash-salt", "AZURE_CLIENT_ID_EVAL", "MODEL_VERSION"):
        assert name in captured.out

    github = [(command, stdin) for command, stdin in commands.calls if command[0] == "gh"]
    assert github, "no GitHub command was run"
    for command, stdin in github:
        assert stdin, f"{command[:4]} was given no value on stdin"
        assert stdin not in command
    sent = {command[3]: stdin for command, stdin in github if command[1] == "variable"}
    assert sent["AZURE_TENANT_ID"] == "fake-tenant"
    assert sent["AZURE_SUBSCRIPTION_ID"] == "fake-subscription"
    assert sent["AZURE_CLIENT_ID_DEPLOY"] == "fake-client"
    environment = [command for command, _ in github if "--env" in command]
    assert environment == [["gh", "secret", "set", "DEMO_TOKEN", "--env", "demo"]]

    update = next(command for command, _ in commands.calls if "update" in command)
    assert "DEMO_TOKEN=secretref:demo-token" in update
    assert "ANSWER_HASH_SALT=secretref:answer-hash-salt" in update


def test_push_carries_on_when_the_demo_environment_is_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "run", FakeCommands())
    setup.main(["--write"])
    monkeypatch.setattr(setup, "run", FakeCommands(fail_on="--env demo"))
    capsys.readouterr()

    assert setup.main(["--push"]) == 0

    output = capsys.readouterr().out
    assert "skipped: GitHub environment secret DEMO_TOKEN" in output
    assert "set: GitHub repository variable MODEL_VERSION" in output


def test_push_needs_the_file_first(commands, capsys):
    assert setup.main(["--push"]) == 1
    assert "--write first" in capsys.readouterr().err
