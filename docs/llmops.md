# LLMOps: tracing, online evaluation, cost, latency, drift and the golden set

How the running scorer is watched and improved, answered as the five questions people ask about LLM operations. Each answer says what is built, where to see it, and what is not built. The data is synthetic and every output is decision support only.

## 1. What plays the part of an LLM observability tool such as Langfuse?

Application Insights, fed by OpenTelemetry, with one Azure Workbook as the dashboard (`infra/workbook.json`, queries in `dashboards/queries.kql`).

| What such a tool offers | What this project has | Where |
|---|---|---|
| A trace per request and per model call | One `score` span per request with the three model calls under it, opened from the trace id on the result card | Application Insights, end-to-end transaction; `src/scorer/telemetry.py` |
| Prompt management and versions | Prompts in files with a SHA-256 registry; a unit test fails if a prompt changes without a new version; the version and hash are on every trace | `prompts/scorer/registry.yaml`; spec FR-3 |
| Scores attached to traces | 21 fixed `scorer.*` attributes: score, the three runs, spread, review reasons, and the injection, grounding, guardrail and protected-term flags | `docs/slo.md`; spec section 8 |
| Cost and latency per call | Tokens in and out and an estimated cost on every span; latency of every request | Dashboard tiles 1 and 3 |
| Datasets and experiments | Golden, fairness, injection and edge-case sets, run as a required CI gate and nightly; each full run sends an `eval_run` event | `evals/`; dashboard tile 4; `docs/eval_card.md` |
| User feedback | A "Report a problem" issue form that asks for the trace id and never for answer text | `.github/ISSUE_TEMPLATE/report-a-problem.yml` |

**Why not Langfuse itself.** Such tools record prompts and completions by default. Here candidate text must never leave the scoring call (spec section 5, Privacy), so content capture is switched off and checked at start-up, and the telemetry holds metadata only. Application Insights sits in the same Azure tenant as the model, needs no key, adds no new data processor and has no fixed charge. A self-hosted Langfuse with input and output masking would be the alternative if a team wanted its interface.

## 2. How is the service evaluated online?

Every live request is evaluated without a reference label, in the request itself:

- Is every evidence quote found in the answer (grounding)?
- Do the three runs agree (spread of 2 or more is inconsistent)?
- Was there an injection attempt or hidden text, and did Azure's guardrail block the call?
- Does the rationale mention a protected attribute or a name? Is the answer off topic?

Any of these sends the answer to a person, and the reasons are counted on **dashboard tile 2** against a 25% band for live traffic (`docs/slo.md`). On 14 October the deployed app's control-triggered rate was 11 of 45 (24.4%), on traffic that held a deliberate burst of injected answers.

**Not built:** a measure of whether live scores were right. The ground truth for that would be the human reviewer's verdict on each routed answer (agree, or change the score), which needs a review queue; spec section 15 lists it as Later. No model judges live answers, because no answer text is kept to judge.

## 3. How are cost and latency kept in check on live traffic?

**Prevented by design:** output capped at 600 tokens and `reasoning_effort` set to none; answers limited to 4000 characters and questions to 500; a demo token and a limit of 10 requests a minute per address; at most 2 replicas; the model deployment capped at 100 thousand tokens a minute.

**Watched:** dashboard tile 1 shows p50 and p95 latency against the 6 s SLO (2.25 s at p95 on 14 October); tile 3 shows tokens and estimated cost per score (about 0.0047 GBP).

**Alerted:** p95 over 6 s for 15 minutes and availability under 99% in an hour, by email (a test alert was received, decision P3-7); a budget on the resource group with emails at 50%, 80% and 100% of 10 GBP.

**Not built:** an alert on cost per score. The budget alert relies on Azure's cost data, which can lag by a day.

## 4. How is drift caught?

- **The model cannot drift silently.** The deployment is pinned to one model version with no automatic upgrade (spec section 9).
- **Quality against labels, every night.** The full eval suite runs nightly against the pinned deployment; kappa, agreement and the gate result per run are on tile 4, and a failed nightly run notifies the owner.
- **Prompt drift.** The prompt version and its hash are on every trace, and the registry test stops an unversioned change.
- **Live drift, without labels.** **Dashboard tile 5** (`tile5_drift_by_day`) gives one row per day: the share of scores at 1 or 2, 3, and 4 or 5, the mean score, the median answer length, and the injection and off-topic rates, each set against the first day in the chosen range. Tile 2's chart shows the review reasons over time. These show that inputs or outputs have moved, which is the prompt to look at the nightly eval; they cannot show that scores became wrong.

**Not built:** an alert on drift. A quiet day moves a lot, so the tile is read by a person.

## 5. How does the golden set grow?

**What is in place.** Every row carries where its label came from. A separate label-auditor agent re-labels each golden answer blind, and a fixed rule settles disagreements (spec section 7). Rows are split into `dev` and `holdout`, and prompt tuning looks at `dev` only. Datasets are a protected path: a change goes through a pull request and the required `evals` gate, and the sizes in the gate are minimums, so the set can grow but not shrink. The build used this loop once: an edge case the model handled inconsistently led to a deterministic control and a recorded decision (S4c-3).

**How a new case gets in today, by hand.** A problem is reported with its trace id. The maintainer finds the request's metadata, writes a synthetic answer that reproduces the failure (the candidate's own text is never stored, so it cannot be copied), labels it, has it audited blind, places it in `dev` or `holdout` by the fixed pattern, and opens a pull request that the gate runs on.

**Not built.** An automatic path from live traffic into the golden set. In production it would take reviewers' disagreements with the scorer as candidate cases, with consent and retention rules, labelled by trained raters; and the Maintain loop (Later) would open an incident with new eval cases when a band is breached.
