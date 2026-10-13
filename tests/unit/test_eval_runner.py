"""The eval runner, offline (spec section 7). No test here calls a model.

The runner is driven through `main`, with the fake clients or with a client factory that
stands in for the live client. Reports go to a temporary folder.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from evals import run_evals
from evals.metrics import REQUIRED_SIZES
from evals.report import (
    DRY_RUN_NOTE,
    SUMMARY_END,
    SUMMARY_START,
    extract_summary,
    failure_text,
)
from evals.run_evals import (
    EXIT_ERROR,
    EXIT_FAIL,
    EXIT_PASS,
    FAKE_RATIONALE,
    SUITES,
    WEAK_PARAPHRASE,
    EvalItem,
    FakeEvalClient,
    build_items,
    estimate_cost,
    eval_event_attributes,
    load_datasets,
    main,
)
from scorer import model_client, pipeline
from scorer.injection import detect_injection
from scorer.model_client import ModelResult, ModelUnavailableError
from scorer.redact import redact
from scorer.sanitise import sanitise

# The real allow-list, bound here before any test swaps the module for a stand-in.
from scorer.telemetry import CUSTOM_EVENT_NAMES, safe_event_attributes

FULL = ["--seed", "11", "--per-minute", "0"]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Keep the developer's and the CI runner's environment out of the runs."""
    for name in (
        "GITHUB_STEP_SUMMARY",
        "GITHUB_OUTPUT",
        "GITHUB_EVENT_NAME",
        "GITHUB_SHA",
        "EVAL_GIT_SHA",
        "SCORER_ROOT",
        "SCORER_PROMPT_VERSION",
    ):
        monkeypatch.delenv(name, raising=False)


def run(tmp_path: Path, *arguments: str, client_factory=None) -> tuple[int, dict | None, str]:
    """Run the evals into a fresh folder. Returns the exit code, the JSON and the Markdown."""
    reports = tmp_path / "reports"
    code = main([*arguments, "--reports-dir", str(reports)], client_factory=client_factory)
    found = sorted(reports.glob("*.json")) if reports.exists() else []
    if not found:
        return code, None, ""
    report = json.loads(found[-1].read_text(encoding="utf-8"))
    return code, report, found[-1].with_suffix(".md").read_text(encoding="utf-8")


def caught_by_our_layers(item: EvalItem) -> bool:
    """Whether the deterministic layers flag this answer, worked out apart from the runner."""
    cleaned = sanitise(item.answer)
    return cleaned.hidden_text_removed or detect_injection(redact(cleaned.text).text).detected


def metric(report: dict, metric_id: str) -> dict:
    return next(item for item in report["metrics"] if item["id"] == metric_id)


class BlockedClient:
    """The platform guardrail stops every call."""

    async def complete(self, messages, *, schema):
        return ModelResult(parsed=None, blocked=True)


class UnavailableClient:
    async def complete(self, messages, *, schema):
        raise ModelUnavailableError("a model call failed")


# --------------------------------------------------------------------------- inputs
def test_a_full_run_has_92_inputs():
    items = build_items(load_datasets())
    counts = {suite: sum(item.suite == suite for item in items) for suite in SUITES}
    assert counts == {"golden": 30, "fairness": 32, "injection": 24, "edge": 6}
    assert len({item.item_id for item in items}) == 92


def test_fairness_pairs_become_two_inputs_with_sides():
    items = build_items(load_datasets(), ("fairness",))
    assert sorted(item.item_id for item in items if item.row_id == "f-id-01") == [
        "f-id-01:a",
        "f-id-01:b",
    ]
    assert {item.meta["side"] for item in items} == {"a", "b"}


def test_suite_and_split_narrow_the_inputs():
    datasets = load_datasets()
    assert len(build_items(datasets, ("golden",), "dev")) == 20
    assert len(build_items(datasets, ("golden",), "holdout")) == 10
    assert len(build_items(datasets, SUITES, "dev")) == 82
    assert build_items(datasets, ("fairness", "injection", "edge"), "holdout") == []


def test_an_input_never_shows_its_text_when_printed():
    item = build_items(load_datasets(), ("golden",))[0]
    assert item.answer not in repr(item)
    assert item.question not in repr(item)


# --------------------------------------------------------------------------- full runs
def test_full_fake_run_writes_a_complete_report_and_gates_on_the_real_controls(tmp_path, capsys):
    code, report, markdown = run(tmp_path, "--fake", *FULL)
    out = capsys.readouterr().out

    run_info = report["run"]
    assert (run_info["mode"], run_info["client"], run_info["seed"]) == ("full", "fake", 11)
    assert (run_info["inputs"], run_info["inputs_reaching_model"]) == (92, 90)
    assert run_info["model_calls"] == 270
    assert len(report["results"]) == 92

    # The fake model returns the label, a mid score and verbatim quotes, so every metric
    # that depends on the model passes.
    for metric_id in (
        "golden_qwk",
        "golden_within_1",
        "golden_exact",
        "identity_mean_abs_diff",
        "identity_max_pair_diff",
        "dialect_verbosity_mean_abs_diff",
        "dialect_verbosity_max_pair_diff",
        "injection_mean_diff",
        "injection_max_pair_diff",
        "edge_expected_behaviour",
        "ungrounded_quote_rate",
        "golden_control_review_rate",
    ):
        assert metric(report, metric_id)["passed"] is True, metric_id
    assert metric(report, "golden_qwk")["value"] == 1.0
    assert metric(report, "ungrounded_quote_rate")["n"] == 180

    # Flagging an injection is the job of the real, deterministic layers, which the fake
    # does not replace. Those layers catch all 18 injected answers, so the dry run passes.
    injected = [
        item
        for item in build_items(load_datasets(), ("injection",))
        if item.meta["role"] == "injected"
    ]
    assert [item.item_id for item in injected if not caught_by_our_layers(item)] == []
    caught = metric(report, "injection_flagged_and_routed")
    assert (caught["count"], caught["n"], caught["passed"]) == (18, 18, True)
    assert [miss for miss in report["misses"] if miss["kind"] == "defect"] == []
    assert report["gate"] == {"status": "pass", "breached": []}
    assert report["gate_failures"] == []
    assert code == EXIT_PASS
    # A dry run can never be mistaken for a result about the scorer.
    assert out.rstrip().splitlines()[-1] == (
        "GATE: PASS (dry run with the fake model; says nothing about the scorer's quality)"
    )
    assert (
        "## Eval gate: PASS (dry run with the fake model; says nothing about the scorer's quality)"
        in markdown
    )
    assert "GATE: PASS" not in [line.strip() for line in out.splitlines()]
    assert "**Offline dry run:**" in markdown


def test_a_full_run_passes_the_gate_when_every_control_holds(tmp_path, capsys):
    # The stand-in for the live client: the fake model, except that the platform guardrail
    # blocks any injected answer our own layers did not flag. A block counts as flagged and
    # routed, and has no score to compare.
    def client_for(item: EvalItem):
        if item.meta.get("role") == "injected" and not caught_by_our_layers(item):
            return BlockedClient()
        return FakeEvalClient(item)

    code, report, markdown = run(tmp_path, *FULL, client_factory=client_for)
    out = capsys.readouterr().out
    assert report["gate"] == {"status": "pass", "breached": []}
    assert code == EXIT_PASS
    assert out.rstrip().splitlines()[-1] == "GATE: PASS"
    assert "## Eval gate: PASS" in markdown
    assert report["run"]["client"] == "live"
    assert metric(report, "injection_flagged_and_routed")["count"] == 18
    assert report["blocked_clean_answers"] == []


def test_fake_weak_run_fails_the_gate_and_names_the_breached_metrics(tmp_path, capsys):
    code, report, markdown = run(tmp_path, "--fake-weak", *FULL)
    out = capsys.readouterr().out
    assert code == EXIT_FAIL
    assert out.rstrip().splitlines()[-1] == f"GATE: FAIL ({DRY_RUN_NOTE})"
    assert f"## Eval gate: FAIL ({DRY_RUN_NOTE})" in markdown
    breached = report["gate"]["breached"]
    for metric_id in (
        "golden_exact",
        "injection_mean_diff",
        "injection_max_pair_diff",
        "edge_expected_behaviour",
        "ungrounded_quote_rate",
        "golden_control_review_rate",
    ):
        assert metric_id in breached
        assert metric_id in out
        assert f"`{metric_id}`" in markdown
    # Every quote was a paraphrase: 90 answers, one quote each, none grounded.
    rate = metric(report, "ungrounded_quote_rate")
    assert (rate["count"], rate["n"]) == (90, 90)
    # Golden scores are the label plus one, capped at 5: only the six level 5 answers match.
    assert metric(report, "golden_exact")["count"] == 6
    assert "i-1-twin" in [miss["row_id"] for miss in report["misses"] if miss["kind"] == "defect"]


def test_a_clean_answer_blocked_by_the_guardrail_is_listed_and_fails_the_gate(tmp_path, capsys):
    def client_for(item: EvalItem):
        if item.item_id in ("g-tw-3-a", "f-id-01:b"):
            return BlockedClient()
        return FakeEvalClient(item)

    code, report, markdown = run(tmp_path, *FULL, client_factory=client_for)
    capsys.readouterr()
    assert code == EXIT_FAIL
    assert [item["item_id"] for item in report["blocked_clean_answers"]] == [
        "f-id-01:b",
        "g-tw-3-a",
    ]
    blocked = next(item for item in report["results"] if item["item_id"] == "g-tw-3-a")
    assert (blocked["score"], blocked["runs"], blocked["status"]) == (None, [], 200)
    assert "identity_max_pair_diff" in report["gate"]["breached"]
    assert "`f-id-01:b`, `g-tw-3-a`" in markdown


# --------------------------------------------------------------------------- partial runs
def test_a_partial_run_says_so_and_never_passes_the_gate(tmp_path, capsys):
    code, report, markdown = run(tmp_path, "--fake", "--suite", "golden", "--split", "dev")
    out = capsys.readouterr().out
    assert code == EXIT_PASS  # nothing it computed was breached, but it is not a gate result
    assert "GATE: PASS" not in out
    assert out.rstrip().splitlines()[-1].startswith("GATE: NOT EVALUATED (partial run")
    assert "PARTIAL" in out
    assert report["gate"]["status"] == "not_evaluated"
    assert (report["run"]["mode"], report["run"]["inputs"]) == ("partial", 20)
    assert "## Eval gate: NOT EVALUATED" in markdown
    assert "**Partial run.**" in markdown
    assert metric(report, "edge_expected_behaviour")["note"] == "not run"
    assert metric(report, "golden_within_1")["n"] == 20


def test_every_suite_on_one_split_is_still_partial(tmp_path, capsys):
    code, report, _ = run(tmp_path, "--fake", "--split", "dev")
    assert report["gate"]["status"] == "not_evaluated"
    assert "GATE: PASS" not in capsys.readouterr().out


def test_a_partial_run_with_a_breach_exits_non_zero(tmp_path, capsys):
    code, report, _ = run(tmp_path, "--fake-weak", "--suite", "golden")
    out = capsys.readouterr().out
    assert code == EXIT_FAIL
    assert report["gate"]["status"] == "not_evaluated"
    assert "golden_exact" in report["gate"]["breached"]
    assert "GATE: PASS" not in out and "GATE: FAIL" not in out


def test_a_split_with_no_inputs_is_an_error(tmp_path, capsys):
    code, report, _ = run(tmp_path, "--fake", "--suite", "edge", "--split", "holdout")
    assert (code, report) == (EXIT_ERROR, None)


# --------------------------------------------------------------------------- failures
def test_model_unavailable_stops_the_run_with_no_report_and_no_score(tmp_path, capsys, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    scored: list[str] = []

    def client_for(item: EvalItem):
        if item.item_id == "g-ps-3-b":
            return UnavailableClient()
        scored.append(item.item_id)
        return FakeEvalClient(item)

    code, report, _ = run(tmp_path, *FULL, "--concurrency", "2", client_factory=client_for)
    captured = capsys.readouterr()
    assert code == EXIT_ERROR
    assert report is None
    assert not (tmp_path / "reports").exists() or not list((tmp_path / "reports").iterdir())
    assert "the model was unavailable on input g-ps-3-b" in captured.err
    assert "no score was invented" in captured.err
    assert "GATE: PASS" not in captured.out
    assert captured.out.rstrip().splitlines()[-1].startswith("GATE: NOT EVALUATED")
    assert len(scored) < 92  # the run stopped: later inputs were never started
    assert "NOT EVALUATED" in summary.read_text(encoding="utf-8")


def test_without_a_live_client_in_the_checkout_the_run_fails_cleanly(tmp_path, capsys, monkeypatch):
    # Whenever the live client cannot be built (no endpoint, no sign-in), a run without
    # --fake must stop: it never falls back to a fake.
    def unbuildable(settings):
        raise RuntimeError("no endpoint")

    monkeypatch.setattr("scorer.model_client.build_model_client", unbuildable, raising=False)
    code, report, _ = run(tmp_path, *FULL)
    assert (code, report) == (EXIT_ERROR, None)
    assert "could not be built" in capsys.readouterr().err


# --------------------------------------------------------------------------- report content
def test_reports_hold_no_answer_question_rationale_or_quote_text(tmp_path, capsys):
    _, _, weak_markdown = run(tmp_path / "weak", "--fake-weak", *FULL)
    _, report, markdown = run(tmp_path / "fake", "--fake", *FULL)
    capsys.readouterr()
    written = json.dumps(report) + markdown + weak_markdown
    for rows in load_datasets().values():
        for row in rows:
            for key in ("answer", "answer_a", "answer_b", "question", "reason"):
                if key in row:
                    assert row[key] not in written, (row["id"], key)
                    assert row[key][:40] not in written, (row["id"], key)
    assert FAKE_RATIONALE not in written
    assert WEAK_PARAPHRASE not in written
    allowed = {
        "item_id", "suite", "row_id", "split", "competency_id", "order", "status", "error",
        "model_calls", "score", "runs", "spread", "needs_human_review", "review_reasons",
        "flags", "quotes_grounded", "quotes_ungrounded", "tokens_in", "tokens_out",
        "model_version", "label", "pair_type", "side", "group", "role", "injection_type",
        "variant", "case", "expected",
    }  # fmt: skip
    assert {key for result in report["results"] for key in result} <= allowed


def test_report_follows_the_reporting_rules(tmp_path, capsys):
    _, report, markdown = run(tmp_path, "--fake", *FULL)
    capsys.readouterr()
    # n beside every metric, and every threshold in the JSON.
    assert all("n" in item and "threshold" in item for item in report["metrics"])
    assert set(report["thresholds"]) == {
        item["id"] for item in report["metrics"] if item["direction"]
    }
    assert "| Metric | Value | n | Gate | Result |" in markdown
    # No confidence intervals, with the reason.
    assert "No confidence intervals are given" in markdown and "too few items" in markdown
    # The fixed inference settings.
    inference = report["inference"]
    assert inference["runs_per_answer"] == 3
    assert inference["reasoning_effort"] == "none"
    assert inference["max_completion_tokens"] == 600
    assert (inference["model_deployment"], inference["prompt_version"]) == ("scorer-mini", "v1")
    assert len(inference["prompt_sha256"]) == 64
    for text in (
        "`reasoning_effort`",
        "`max_completion_tokens`",
        "Prompt SHA-256",
        "Runs per answer",
    ):
        assert text in markdown
    # The seed, and the decision the eval informs.
    assert "| Seed for the item order | 11 |" in markdown
    assert "merge or block" in markdown
    # The noise floor and the flip rate, next to each other and not gated.
    rows = [line for line in markdown.splitlines() if line.startswith("| ")]
    noise = next(i for i, line in enumerate(rows) if line.startswith("| Noise floor"))
    assert rows[noise + 1].startswith("| Fairness flip rate")
    assert "reported, not gated" in rows[noise] and "reported, not gated" in rows[noise + 1]
    # Offline dry runs say so, and cost nothing.
    assert "**Offline dry run:**" in markdown
    assert report["usage"]["simulated"] is True
    assert report["usage"]["cost"]["available"] is False
    assert report["usage"]["tokens_in"] > 0
    assert chr(0x2014) not in markdown  # no em dash


def test_holdout_rows_are_in_the_json_but_not_listed_in_the_markdown(tmp_path, capsys):
    _, report, markdown = run(tmp_path, "--fake-weak", *FULL)
    capsys.readouterr()
    holdout = [item["item_id"] for item in report["results"] if item["split"] == "holdout"]
    assert len(holdout) == 10
    for item_id in holdout:
        assert item_id not in markdown
    assert "| g-tw-1-a |" in markdown  # a dev row is listed
    # Misses on holdout rows are counted but not named.
    hidden = [miss for miss in report["misses"] if miss["split"] == "holdout"]
    assert hidden and all(miss["kind"] == "variance" for miss in hidden)


def test_the_summary_section_is_what_a_pull_request_comment_shows(tmp_path, capsys):
    _, _, markdown = run(tmp_path, "--fake", *FULL)
    capsys.readouterr()
    summary = extract_summary(markdown)
    assert summary.startswith(SUMMARY_START) and summary.endswith(SUMMARY_END)
    assert "## Eval gate:" in summary and "| Metric |" in summary
    assert "## Results by row" not in summary


def test_the_item_order_follows_the_seed(tmp_path, capsys):
    def order(folder: str, seed: str) -> list[str]:
        _, report, _ = run(tmp_path / folder, "--fake", "--suite", "golden", "--seed", seed)
        return [item["item_id"] for item in report["results"]]

    first, again, other = order("a", "5"), order("b", "5"), order("c", "6")
    capsys.readouterr()
    assert first == again
    assert first != other
    assert sorted(first) == sorted(other) != first  # shuffled, not file order


def test_a_seed_is_chosen_and_logged_when_none_is_given(tmp_path, capsys):
    _, report, _ = run(tmp_path, "--fake", "--suite", "edge")
    assert f"Seed: {report['run']['seed']} " in capsys.readouterr().out


def test_the_separator_passed_on_by_the_task_runner_is_accepted(tmp_path, capsys):
    reports = tmp_path / "reports"
    code = main(["--", "--fake", "--suite", "edge", "--reports-dir", str(reports)])
    capsys.readouterr()
    assert code == EXIT_PASS and len(list(reports.glob("*.md"))) == 1


def test_github_summary_and_outputs_are_written_when_the_variables_are_set(
    tmp_path, capsys, monkeypatch
):
    summary, output = tmp_path / "summary.md", tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("EVAL_GIT_SHA", "a" * 40)
    _, report, markdown = run(tmp_path, "--fake", "--suite", "edge")
    capsys.readouterr()
    assert summary.read_text(encoding="utf-8").strip() == markdown.strip()
    outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert outputs["gate"] == "not_evaluated"
    assert outputs["report_md"].endswith(".md") and outputs["report_json"].endswith(".json")
    assert (report["run"]["trigger"], report["run"]["git_sha"]) == ("pull_request", "a" * 40)


# --------------------------------------------------------------------------- cost
def test_cost_is_estimated_from_the_price_file(tmp_path):
    prices = tmp_path / "prices.yaml"
    prices.write_text(
        "currency: GBP\nunit: per_1m_tokens\ninput: 0.5\ncached_input: 0.05\noutput: 3.0\n"
        "source_url: https://example.org/prices\nretrieved: 2026-10-13\n",
        encoding="utf-8",
    )
    # 400,000 tokens in at 0.5 per million = 0.20. 40,000 out at 3.0 per million = 0.12.
    cost = estimate_cost(400_000, 40_000, prices)
    assert (cost["available"], cost["amount"], cost["currency"]) == (True, 0.32, "GBP")
    assert cost["retrieved"] == "2026-10-13"


def test_cost_is_unavailable_without_a_usable_price_file(tmp_path):
    assert estimate_cost(1000, 100, tmp_path / "missing.yaml")["available"] is False
    wrong_unit = tmp_path / "prices.yaml"
    wrong_unit.write_text("currency: GBP\nunit: per_1k_tokens\ninput: 1\noutput: 1\n", "utf-8")
    cost = estimate_cost(1000, 100, wrong_unit)
    assert cost["available"] is False and "amount" not in cost


# --------------------------------------------------------------------------- eval_run event
@pytest.fixture
def telemetry(monkeypatch):
    """A stand-in for `scorer.telemetry`: it records what is sent and when it is flushed."""
    module = types.ModuleType("scorer.telemetry")
    module.configured = True
    module.events = []
    module.calls = []
    module.configure_telemetry = lambda settings: module.configured

    def emit_custom_event(name, attributes):
        module.calls.append("emit")
        module.events.append((name, attributes))

    module.emit_custom_event = emit_custom_event
    module.flush_telemetry = lambda: module.calls.append("flush")
    monkeypatch.setitem(sys.modules, "scorer.telemetry", module)
    return module


def passing_client(item: EvalItem):
    if item.meta.get("role") == "injected" and not caught_by_our_layers(item):
        return BlockedClient()
    return FakeEvalClient(item)


def test_one_eval_run_event_is_sent_after_a_full_live_run(tmp_path, capsys, telemetry, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    _, report, _ = run(tmp_path, *FULL, "--emit-event", client_factory=passing_client)
    assert "eval_run event: sent" in capsys.readouterr().out
    assert len(telemetry.events) == 1
    name, attributes = telemetry.events[0]
    assert name == "eval_run"
    assert attributes == eval_event_attributes(report)
    assert (attributes["git_sha"], attributes["trigger"]) == ("b" * 40, "schedule")
    assert (attributes["prompt_version"], attributes["gate"], attributes["passed"]) == (
        "v1",
        "pass",
        True,
    )
    for item in report["metrics"]:  # every metric, with its n
        assert attributes[item["id"]] == item["value"]
        assert attributes[f"{item['id']}_n"] == item["n"]
    # Numbers, ids and flags only: nothing an answer could be carried in.
    assert all(isinstance(value, (str, int, float, bool)) for value in attributes.values())
    assert all(len(value) < 400 for value in attributes.values() if isinstance(value, str))


def test_the_event_is_not_sent_for_a_dry_run_or_a_partial_run(tmp_path, capsys, telemetry):
    run(tmp_path / "fake", "--fake", *FULL, "--emit-event")
    run(
        tmp_path / "partial",
        "--suite",
        "golden",
        "--per-minute",
        "0",
        "--emit-event",
        client_factory=FakeEvalClient,
    )
    assert capsys.readouterr().out.count("eval_run event: not sent") == 2
    assert telemetry.events == []


def test_the_event_is_a_no_op_when_telemetry_is_not_configured(tmp_path, capsys, telemetry):
    telemetry.configured = False
    code, _, _ = run(tmp_path, *FULL, "--emit-event", client_factory=passing_client)
    assert "not sent (telemetry is not configured)" in capsys.readouterr().out
    assert telemetry.events == []
    assert code == EXIT_PASS


def test_a_telemetry_fault_never_changes_the_gate_result(tmp_path, capsys, telemetry):
    def broken(name, attributes):
        raise RuntimeError("exporter down")

    telemetry.emit_custom_event = broken
    code, report, _ = run(tmp_path, *FULL, "--emit-event", client_factory=passing_client)
    assert "eval_run event: not sent (RuntimeError)" in capsys.readouterr().out
    assert (code, report["gate"]["status"]) == (EXIT_PASS, "pass")


def test_the_default_pace_keeps_a_full_run_inside_the_deployment_limit():
    # 100 thousand tokens a minute; an input is about three calls of 1,650 tokens in plus
    # up to 600 out: 3 * 2,250 = 6,750. 12 inputs a minute is 81,000, inside the limit.
    assert run_evals.DEFAULT_PER_MINUTE * 3 * (1650 + 600) <= 100_000
    assert run_evals.DEFAULT_CONCURRENCY == 4


# --------------------------------------------------------------------------- the event, checked
def test_the_event_is_flushed_straight_after_it_is_sent(tmp_path, capsys, telemetry):
    run(tmp_path, *FULL, "--emit-event", client_factory=passing_client)
    assert "eval_run event: sent" in capsys.readouterr().out
    assert telemetry.calls == ["emit", "flush"], "the process ends next, so nothing may wait"


def test_nothing_is_flushed_when_no_event_was_sent(tmp_path, capsys, telemetry):
    telemetry.configured = False
    run(tmp_path, *FULL, "--emit-event", client_factory=passing_client)
    capsys.readouterr()
    assert telemetry.calls == []


def test_every_eval_run_attribute_passes_the_telemetry_allow_list(tmp_path, capsys):
    # The real allow-list, not the stand-in: nothing the runner sends may be dropped by it.
    _, passing, _ = run(tmp_path / "pass", "--fake", *FULL)
    _, failing, _ = run(tmp_path / "fail", "--fake-weak", *FULL)
    capsys.readouterr()
    for report in (passing, failing):
        attributes = eval_event_attributes(report)
        assert safe_event_attributes(attributes) == attributes
        assert "eval_run" in CUSTOM_EVENT_NAMES
    assert eval_event_attributes(failing)["breached"].count(",") >= 5
    assert eval_event_attributes(passing)["failures"] == ""


# --------------------------------------------------------------------------- required sizes
def test_the_datasets_hold_exactly_the_required_sizes():
    datasets = load_datasets()
    injection = [row["role"] for row in datasets["injection"]]
    pair_types = [row["pair_type"] for row in datasets["fairness"]]
    assert REQUIRED_SIZES == {
        "golden_answers": len(datasets["golden"]),
        "identity_pairs": pair_types.count("identity"),
        "dialect_verbosity_pairs": pair_types.count("dialect") + pair_types.count("verbosity"),
        "injection_clean_answers": injection.count("clean"),
        "injection_injected_answers": injection.count("injected"),
        "edge_cases": len(datasets["edge"]),
    }


def small_datasets() -> dict[str, list[dict]]:
    """Two golden rows, one identity pair, one dialect pair, one injected row, one edge case."""
    full = load_datasets()
    by_label = {row["label"]: row for row in full["golden"]}
    by_type = {row["pair_type"]: row for row in full["fairness"]}
    group = full["injection"][0]["group"]
    return {
        "golden": [by_label[1], by_label[5]],
        "fairness": [by_type["identity"], by_type["dialect"]],
        "injection": [
            row for row in full["injection"] if row["group"] == group and row["variant"] != "twin"
        ][:2],
        "edge": full["edge"][:1],
    }


def test_a_full_run_over_too_few_rows_fails_the_gate_with_named_reasons(
    tmp_path, capsys, monkeypatch
):
    # Every metric passes on these few rows. Before the sizes were required, so did the gate.
    monkeypatch.setattr(run_evals, "load_datasets", small_datasets)
    code, report, markdown = run(tmp_path, *FULL, client_factory=FakeEvalClient)
    out = capsys.readouterr().out

    assert report["run"]["mode"] == "full" and report["run"]["inputs"] == 9
    assert report["gate"] == {"status": "fail", "breached": []}
    assert all(item["passed"] is True for item in report["metrics"] if item["direction"])
    assert [failure["rule"] for failure in report["gate_failures"]] == ["required_size_not_met"] * 6
    assert code == EXIT_FAIL
    assert out.rstrip().splitlines()[-1] == "GATE: FAIL"
    assert (
        "Gate failure: required_size_not_met (golden answers: 2 present, at least 30 required)"
        in out
    )
    assert "## Eval gate: FAIL" in markdown
    assert "**The gate also fails for:**" in markdown
    for text in (
        "golden answers: 2 present, at least 30 required",
        "identity pairs: 1 present, at least 8 required",
        "dialect verbosity pairs: 1 present, at least 8 required",
        "injection clean answers: 1 present, at least 6 required",
        "injection injected answers: 1 present, at least 18 required",
        "edge cases: 1 present, at least 6 required",
    ):
        assert text in markdown
    assert "**The gate also fails for:**" in extract_summary(markdown)
    assert eval_event_attributes(report)["failures"] == "required_size_not_met"


def test_a_partial_run_over_few_rows_is_not_a_size_failure(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(run_evals, "load_datasets", small_datasets)
    code, report, markdown = run(tmp_path, "--fake", "--suite", "golden")
    capsys.readouterr()
    assert (code, report["gate"]["status"], report["gate_failures"]) == (
        EXIT_PASS,
        "not_evaluated",
        [],
    )
    assert "The gate also fails for" not in markdown


def test_a_gate_failure_never_names_a_holdout_row():
    failure = {
        "rule": "tripped_control_not_routed",
        "detail": "2 answers were not routed",
        "rows": [
            {"row_id": "g-tw-3-a", "split": "dev"},
            {"row_id": "g-tw-5-a", "split": "holdout"},
        ],
    }
    text = failure_text(failure, code=True)
    assert "`g-tw-3-a`" in text and "g-tw-5-a" not in text
    assert "plus 1 on holdout rows" in text


# --------------------------------------------------------------------------- inference settings
def test_the_printed_inference_settings_are_the_live_clients_own_constants(tmp_path, capsys):
    assert run_evals.FIXED_INFERENCE["reasoning_effort"] is model_client.REASONING_EFFORT
    assert run_evals.FIXED_INFERENCE["max_completion_tokens"] is model_client.MAX_COMPLETION_TOKENS
    assert run_evals.FIXED_INFERENCE["runs_per_answer"] is pipeline.RUNS

    _, report, markdown = run(tmp_path, "--fake", "--suite", "edge")
    capsys.readouterr()
    inference = report["inference"]
    assert inference["reasoning_effort"] == model_client.REASONING_EFFORT
    assert inference["max_completion_tokens"] == model_client.MAX_COMPLETION_TOKENS
    assert inference["runs_per_answer"] == pipeline.RUNS
    assert f"| `reasoning_effort` | {model_client.REASONING_EFFORT} |" in markdown
    assert f"| `max_completion_tokens` | {model_client.MAX_COMPLETION_TOKENS} |" in markdown
    assert f"| Runs per answer | {pipeline.RUNS} |" in markdown


def test_the_runner_keeps_no_copy_of_the_client_settings():
    # The report reads the constants: it has no copy of its own to drift from them.
    source = Path(run_evals.__file__).read_text(encoding="utf-8")
    assert '"reasoning_effort": REASONING_EFFORT' in source
    assert '"max_completion_tokens": MAX_COMPLETION_TOKENS' in source
    assert '"reasoning_effort": "' not in source and '"max_completion_tokens": 6' not in source
