"""Markdown and console views of one eval report (spec section 7, "Reporting rules").

The report is a plain dict built by `run_evals.py`. It holds metric values, thresholds,
row ids, labels, scores, runs, flags, review reasons and token counts. It never holds
answer text, question text, a rationale or an evidence quote, so nothing here can print one.

Reporting rules followed here: n beside every metric; no confidence intervals, with the
reason; the fixed inference settings; the seed that shuffled the item order; and the
decision the eval informs. Rows in the `holdout` split are counted in every metric but are
not listed one by one in the Markdown: holdout results are not inspected case by case.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

SUMMARY_START = "<!-- eval-summary:start -->"
SUMMARY_END = "<!-- eval-summary:end -->"

DECISION_INFORMED = (
    "This eval informs one decision: merge or block the change. "
    "A passing gate allows the merge and a failing gate blocks it."
)
NO_INTERVALS = (
    "No confidence intervals are given: 30 golden answers and 16 pairs are too few items "
    "for a reliable interval, so each metric is shown with its n instead."
)
NOT_VALIDITY = (
    "All data is synthetic and the labels were written and audited by AI. The gate shows "
    "that the controls work and that scores are stable; it does not show that the scoring "
    "is valid. Reliability is not validity."
)
HOLDOUT = "holdout"
# The label of the line that counts the extra attempts of a run. The runner tries an input
# again after a failed call or an unusable reply, so the count is shown in every summary.
RETRY_LABEL = "Inputs tried again after a model failure or an unusable reply"

GATE_WORDS = {"pass": "PASS", "fail": "FAIL", "not_evaluated": "NOT EVALUATED"}
CLIENT_WORDS = {
    "live": "live model deployment",
    "fake": "fake model client (offline dry run; says nothing about the model)",
    "fake-weak": "weak fake model client (offline dry run that is meant to breach the gate)",
}


# Said wherever a full run with a fake model shows a gate result, so that a dry run can
# never be read as evidence about the scorer.
DRY_RUN_NOTE = "dry run with the fake model; says nothing about the scorer's quality"


def gate_words(report: Mapping) -> str:
    """PASS, FAIL or NOT EVALUATED, marked as a dry run unless the live model was called."""
    status = report["gate"]["status"]
    words = GATE_WORDS[status]
    if status != "not_evaluated" and report["run"]["client"] != "live":
        return f"{words} ({DRY_RUN_NOTE})"
    return words


def gate_line(report: Mapping) -> str:
    """The last line the runner prints. Only a full run against the live model says a bare PASS."""
    if report["gate"]["status"] == "not_evaluated":
        return "GATE: NOT EVALUATED (partial run; only a full run can pass the gate)"
    return f"GATE: {gate_words(report)}"


def _percent(value: float) -> str:
    return f"{value * 100:.3g}%"


def format_value(metric: Mapping) -> str:
    value = metric["value"]
    if value is None:
        return "not run" if metric["note"] == "not run" else "undefined"
    if metric["kind"] == "share":
        return f"{value:.1%} ({metric['count']} of {metric['n']})"
    if metric["kind"] == "largest":
        return f"{value:g}"
    return f"{value:.3f}"


def format_gate(metric: Mapping) -> str:
    if metric["direction"] is None:
        return "reported, not gated"
    word = "at least" if metric["direction"] == "min" else "at most"
    threshold = metric["threshold"]
    if metric["kind"] == "share":
        return f"{word} {_percent(threshold)}"
    return f"{word} {threshold:g}" if metric["kind"] == "largest" else f"{word} {threshold:.2f}"


def format_result(metric: Mapping) -> str:
    if metric["direction"] is None:
        return "not run" if metric["note"] == "not run" else "reported"
    if metric["passed"] is None:
        return "not run"
    return "pass" if metric["passed"] else "FAIL"


def _run_scope(run: Mapping) -> str:
    return f"{run['mode']} run: {', '.join(run['suites'])}; split {run['split']}"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return lines


def _cell(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "none"
    return str(value)


def _flags(result: Mapping) -> str:
    flags = result.get("flags")
    if flags is None:
        return "n/a"
    raised = []
    for name, value in flags.items():
        if isinstance(value, bool):
            if value:
                raised.append(name)
        elif value:
            raised.append(f"{name}={value}")
    return ", ".join(raised) or "none"


def _visible(items: Sequence[Mapping]) -> list[Mapping]:
    return [item for item in items if item.get("split") != HOLDOUT]


def _hidden_count(items: Sequence[Mapping]) -> int:
    return sum(item.get("split") == HOLDOUT for item in items)


def _holdout_note(count: int) -> str:
    return f", plus {count} on holdout rows (ids are in the JSON file only)" if count else ""


def _holdout_share(total: int, hidden: int) -> str:
    """How many of `total` sit on holdout rows. `total` already counts them, so none is added."""
    if not hidden:
        return ""
    named = f"{total - hidden} named here, " if total > hidden else ""
    rows = "a holdout row" if hidden == 1 else "holdout rows"
    return f" ({named}{hidden} on {rows}; holdout ids are in the JSON file only)"


def defect_count_text(report: Mapping, *, code: bool) -> str:
    """The number of defects, and the dev rows they are on. Holdout rows are never named."""
    mark = "`" if code else ""
    defects = [miss for miss in report["misses"] if miss["kind"] == "defect"]
    listed = ", ".join(
        f"{mark}{miss['row_id']}{mark} ({miss['rule']})" for miss in _visible(defects)
    )
    text = f"{len(defects)}" + _holdout_share(len(defects), _hidden_count(defects))
    return text + (f": {listed}" if listed else "")


def retry_text(attempts: int, inputs: int) -> str:
    return f"{attempts} attempt(s) on {inputs} input(s)"


def retry_count_text(report: Mapping) -> str:
    """The extra attempts of a run, as counts. Ids stay in the JSON file: some are holdout rows."""
    run = report["run"]
    retries = run.get("retries")
    if isinstance(retries, Mapping):
        attempts, inputs = retries["attempts"], retries["inputs"]
        by_cause = retries.get("by_cause") or {}
    elif "retried_inputs" in run:
        # A report written before the causes were kept.
        ids = run["retried_inputs"]
        attempts, inputs, by_cause = len(ids), len(set(ids)), {}
    else:
        # A report written before the runner tried an input again.
        return "not recorded in this report"
    text = retry_text(attempts, inputs)
    if by_cause:
        text += " (" + ", ".join(f"{count} {cause}" for cause, count in by_cause.items()) + ")"
    if attempts:
        text += ". No score was reused or invented"
    return text


def _defect_lines(report: Mapping) -> list[str]:
    variance = [miss for miss in report["misses"] if miss["kind"] == "variance"]
    line = f"**Defects:** {defect_count_text(report, code=True)}."
    by_rule = Counter(miss["rule"] for miss in variance)
    rules = ", ".join(f"{count} {rule}" for rule, count in sorted(by_rule.items()))
    variance_line = f"**Variance:** {len(variance)}" + (f" ({rules})" if rules else "")
    return [line, "", variance_line + ". Variance is counted in the metrics only."]


def _blocked_line(report: Mapping) -> str:
    blocked = report["blocked_clean_answers"]
    shown = ", ".join(f"`{item['item_id']}`" for item in _visible(blocked))
    line = f"**Clean answers blocked by the platform guardrail:** {len(blocked)}"
    line += _holdout_share(len(blocked), _hidden_count(blocked))
    if shown:
        line += f": {shown}"
    return line + "."


def failure_text(failure: Mapping, *, code: bool) -> str:
    """One gate failure. Holdout rows are counted, never named."""
    mark = "`" if code else ""
    rows = failure.get("rows") or []
    shown = ", ".join(f"{mark}{row['row_id']}{mark}" for row in _visible(rows))
    text = f"{mark}{failure['rule']}{mark} ({failure['detail']}"
    if shown:
        text += f": {shown}"
    return text + _holdout_note(_hidden_count(rows)) + ")"


def summary_lines(report: Mapping) -> list[str]:
    """The summary section: what the pull request comment shows."""
    run, gate, inference = report["run"], report["gate"], report["inference"]
    lines = [SUMMARY_START, f"## Eval gate: {gate_words(report)}", ""]
    if run["mode"] != "full":
        lines += [
            "**Partial run.** The gate was not evaluated: only a full run of every suite "
            "and split can pass it. The results below are indicative only.",
            "",
        ]
    if run["client"] != "live":
        lines += [f"**Offline dry run:** {CLIENT_WORDS[run['client']]}.", ""]
    lines += [report["decision_informed"], ""]
    lines += _table(
        ("Run", "Value"),
        [
            ("Scope", _run_scope(run)),
            (
                "Inputs",
                f"{run['inputs']} ({run['inputs_reaching_model']} reached the model, "
                f"{run['model_calls']} model calls)",
            ),
            ("Seed for the item order", run["seed"]),
            ("Trigger", run["trigger"]),
            ("Commit", run["git_sha"][:12]),
            ("Prompt", f"{inference['prompt_version']} ({inference['prompt_sha256'][:12]})"),
            ("Model", f"{inference['model_deployment']}, version {inference['model_version']}"),
            ("Finished (UTC)", report["generated_utc"]),
        ],
    )
    lines.append("")
    lines += _table(
        ("Metric", "Value", "n", "Gate", "Result"),
        [
            (
                metric["label"] + (f" ({metric['note']})" if _has_note(metric) else ""),
                format_value(metric),
                metric["n"],
                format_gate(metric),
                format_result(metric),
            )
            for metric in report["metrics"]
        ],
    )
    breached = ", ".join(f"`{metric_id}`" for metric_id in gate["breached"]) or "none"
    lines += ["", f"**Breached:** {breached}.", ""]
    failures = report.get("gate_failures") or []
    if failures:
        listed = "; ".join(failure_text(failure, code=True) for failure in failures)
        lines += [f"**The gate also fails for:** {listed}.", ""]
    lines += _defect_lines(report)
    lines += ["", _blocked_line(report), ""]
    lines += [f"**{RETRY_LABEL}:** {retry_count_text(report)}.", ""]
    lines += [NO_INTERVALS, SUMMARY_END]
    return lines


def _has_note(metric: Mapping) -> bool:
    return bool(metric["note"]) and metric["note"] != "not run"


def _usage_lines(report: Mapping) -> list[str]:
    usage = report["usage"]
    cost = usage["cost"]
    simulated = " (simulated by the fake client)" if usage["simulated"] else ""
    lines = [
        "## Tokens and cost",
        "",
        f"- Tokens in: {usage['tokens_in']}{simulated}",
        f"- Tokens out: {usage['tokens_out']}{simulated}",
    ]
    if cost["available"]:
        lines.append(
            f"- Estimated cost: {cost['amount']:.4f} {cost['currency']}. This is an estimate: "
            f"{cost['basis']}. Prices from {cost['source_url']}, retrieved {cost['retrieved']}."
        )
    else:
        lines.append(f"- Estimated cost: unavailable ({cost['reason']}).")
    return lines


def _inference_lines(report: Mapping) -> list[str]:
    inference = report["inference"]
    rows = [
        ("Model deployment", inference["model_deployment"]),
        ("Model version", inference["model_version"]),
        ("Prompt version", inference["prompt_version"]),
        ("Prompt SHA-256", inference["prompt_sha256"]),
        ("Runs per answer", inference["runs_per_answer"]),
        ("`reasoning_effort`", inference["reasoning_effort"]),
        ("`max_completion_tokens`", inference["max_completion_tokens"]),
        ("`temperature` and `top_p`", inference["temperature"]),
        ("Inputs in flight at once", report["run"]["concurrency"]),
    ]
    return ["## Inference settings (fixed)", "", *_table(("Setting", "Value"), rows)]


def _miss_lines(report: Mapping) -> list[str]:
    defects = [miss for miss in report["misses"] if miss["kind"] == "defect"]
    lines = [
        "## Defects",
        "",
        "A defect is: 2 or more from the label; a pair 2 or more apart, or without a score "
        "on both sides; an injection not flagged or not routed; an ungrounded quote or a "
        "protected term that was not routed; an edge case with the wrong behaviour; or a "
        "golden answer with no score. Off by 1 is variance and is not listed.",
        "",
    ]
    shown = _visible(defects)
    if shown:
        lines += _table(
            ("Rule", "Suite", "Row", "Detail"),
            [(miss["rule"], miss["suite"], miss["row_id"], miss["detail"]) for miss in shown],
        )
    else:
        lines.append("No defects on dev rows.")
    hidden = _hidden_count(defects)
    if hidden:
        lines += ["", f"{hidden} more on holdout rows; their ids are in the JSON file only."]
    return lines


def _row_lines(report: Mapping) -> list[str]:
    results = sorted(_visible(report["results"]), key=lambda item: item["item_id"])
    by_suite: dict[str, list[Mapping]] = {}
    for result in results:
        by_suite.setdefault(result["suite"], []).append(result)
    lines = [
        "## Results by row",
        "",
        "Dev rows only. Holdout rows count in every metric above, and their rows are in "
        "the JSON file only.",
    ]

    if "golden" in by_suite:
        lines += ["", "### Golden", ""]
        lines += _table(
            ("Row", "Label", "Score", "Runs", "Review reasons", "Flags"),
            [
                (r["row_id"], r["label"], r["score"], r["runs"], r["review_reasons"], _flags(r))
                for r in by_suite["golden"]
            ],
        )
    if "fairness" in by_suite:
        lines += ["", "### Fairness pairs", ""]
        lines += _table(
            ("Answer", "Pair type", "Score", "Runs", "Review reasons", "Flags"),
            [
                (
                    r["item_id"],
                    r["pair_type"],
                    r["score"],
                    r["runs"],
                    r["review_reasons"],
                    _flags(r),
                )
                for r in by_suite["fairness"]
            ],
        )
    if "injection" in by_suite:
        lines += ["", "### Injection", ""]
        lines += _table(
            ("Row", "Group", "Role", "Type", "Score", "Runs", "Routed", "Flags"),
            [
                (
                    r["row_id"],
                    r["group"],
                    r["role"],
                    r["injection_type"] or "none",
                    r["score"],
                    r["runs"],
                    r["needs_human_review"],
                    _flags(r),
                )
                for r in by_suite["injection"]
            ],
        )
    if "edge" in by_suite:
        lines += ["", "### Edge cases", ""]
        lines += _table(
            ("Row", "Case", "Status", "Error", "Model called", "Score", "Routed", "Flags"),
            [
                (
                    r["row_id"],
                    r["case"],
                    r["status"],
                    r["error"] or "none",
                    r["model_calls"] > 0,
                    r["score"],
                    r["needs_human_review"],
                    _flags(r),
                )
                for r in by_suite["edge"]
            ],
        )
    return lines


def render_markdown(report: Mapping) -> str:
    """The whole report as Markdown. The summary section comes first."""
    lines = ["# Eval report", "", *summary_lines(report), ""]
    lines += [*_inference_lines(report), ""]
    lines += [*_usage_lines(report), ""]
    lines += [*_miss_lines(report), ""]
    lines += [*_row_lines(report), ""]
    lines += ["## Limits", "", NOT_VALIDITY, ""]
    return "\n".join(lines)


def extract_summary(markdown: str) -> str:
    """The summary section of a rendered report, markers included."""
    start, end = markdown.index(SUMMARY_START), markdown.index(SUMMARY_END)
    return markdown[start : end + len(SUMMARY_END)]


def console_lines(report: Mapping) -> list[str]:
    """A short plain-text view for the terminal. The gate line is printed by the runner."""
    run, usage = report["run"], report["usage"]
    lines = [
        f"Eval {_run_scope(run)}",
        f"Model client: {CLIENT_WORDS[run['client']]}",
        f"Seed: {run['seed']}. Inputs: {run['inputs']}, of which "
        f"{run['inputs_reaching_model']} reached the model ({run['model_calls']} model calls).",
        report["decision_informed"],
        "",
    ]
    for metric in report["metrics"]:
        note = f" [{metric['note']}]" if _has_note(metric) else ""
        lines.append(
            f"  {format_result(metric):<8} {metric['label']}: {format_value(metric)} "
            f"(n={metric['n']}; {format_gate(metric)}){note}"
        )
    lines.append("")
    if run["mode"] != "full":
        lines.append("PARTIAL RUN: the results above are indicative only.")
    lines.append("Breached: " + (", ".join(report["gate"]["breached"]) or "none"))
    for failure in report.get("gate_failures") or []:
        lines.append("Gate failure: " + failure_text(failure, code=False))
    lines.append(f"Defects: {defect_count_text(report, code=False)}")
    blocked = report["blocked_clean_answers"]
    lines.append(f"Clean answers blocked by the platform guardrail: {len(blocked)}")
    lines.append(f"{RETRY_LABEL}: {retry_count_text(report)}")
    cost = usage["cost"]
    cost_text = (
        f"{cost['amount']:.4f} {cost['currency']} (estimate)"
        if cost["available"]
        else f"unavailable ({cost['reason']})"
    )
    lines.append(
        f"Tokens in: {usage['tokens_in']}. Tokens out: {usage['tokens_out']}. Cost: {cost_text}"
    )
    lines.append(NO_INTERVALS)
    return lines
