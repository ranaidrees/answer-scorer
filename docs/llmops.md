# LLMOps: tracing, online evaluation, cost, latency, drift and the golden set

How the running scorer is watched and improved, answered as the five questions people ask about LLM operations. Each answer says what is built, where to see it, and what is not built. The data is synthetic and every output is decision support only. The figures below show that the controls behave consistently, not that the scores are right: reliability is not validity.

Dashboard tiles 5 and 6 were added on 14 October. They are in `infra/workbook.json` and `dashboards/queries.kql`, and they appear in the live workbook once the owner applies the observability deployment (decision P3-10).

## 1. What plays the part of an LLM observability tool such as Langfuse?

Application Insights, fed by OpenTelemetry, with one Azure Workbook as the dashboard (`infra/workbook.json`, queries in `dashboards/queries.kql`).

| What such a tool offers | What this project has | Where |
|---|---|---|
| A trace per request and per model call | One `score` span per request with the three model calls under it. The trace id is on the result card, and tile 6 lists the latest requests with theirs, including any the platform guardrail blocked | Application Insights, end-to-end transaction; `src/scorer/telemetry.py`; dashboard tile 6 |
| Prompt management and versions | Prompts in files with a SHA-256 registry; a unit test fails if a prompt changes without a new version; the version and hash are on every `score` span | `prompts/scorer/registry.yaml`; spec FR-3 |
| Scores attached to traces | 21 fixed `scorer.*` attributes on the `score` span: score, the three runs, spread, review reasons, and the injection, grounding, guardrail and protected-term flags | Spec section 8 |
| Cost and latency per call | Tokens in and out and an estimated cost on every `score` span; the duration of every request | Dashboard tiles 1, 3 and 6 |
| Datasets and experiments | Golden, fairness, injection and edge-case sets, run as a required CI gate and nightly; each full run in CI sends an `eval_run` event | `evals/`; dashboard tile 4; `docs/eval_card.md` |
| User feedback | A "Report a problem" issue form that asks for the trace id and never for answer text | `.github/ISSUE_TEMPLATE/report-a-problem.yml` |

**Why not Langfuse itself.** Tools of that kind are built to record prompts and completions. Here candidate text must never leave the scoring call (spec section 5, Privacy), so content capture is switched off and refused at start-up, and the telemetry holds metadata only. Application Insights sits in the same Azure tenant as the model, adds no new vendor or data processor, and has no fixed charge. It is not keyless in the way the model is: telemetry is sent with the resource's connection string, which holds an instrumentation key that Microsoft does not treat as a credential; the infrastructure sets it as an ordinary app setting, and GitHub holds a copy as a secret for CI, and Entra-only ingestion is not switched on. A self-hosted Langfuse with input and output masking would be the alternative if a team wanted its interface.

**Not built:** a trace viewer of our own, scores or comments added to a trace after the event, and any link from a reported problem or a reviewer's verdict back onto its trace. The trace id is the join, made by hand.

## 2. How is the service evaluated online?

Every live request is evaluated without a reference label, in the request itself:

- Is every evidence quote found in the answer (grounding)?
- Do the three runs agree (a spread of 2 or more is inconsistent)?
- Was there an injection attempt or hidden text, and did Azure's guardrail block the call?
- Does the rationale mention a protected attribute or a name? Is the answer off topic?

Any of these sends the answer to a person, and the reasons are counted on **dashboard tile 2** against a 25% band for live traffic (`docs/slo.md`). On 14 October the deployed app's control-triggered rate was 11 of 45 (24.4%), on traffic that held a deliberate burst of injected answers. Tile 6 lists the requests where a control tripped first, each with its trace id.

**Not built:** a measure of whether live scores were right. The ground truth for that would be the human reviewer's verdict on each routed answer (agree, or change the score), which needs a review queue; spec section 15 lists it as Later. No model judges live answers, because no answer text is kept to judge.

## 3. How are cost and latency kept in check on live traffic?

**Prevented by design:** output capped at 600 tokens and `reasoning_effort` set to none; answers limited to 4000 characters and questions to 500; a demo token and a limit of 10 requests a minute per address, counted in each replica (so up to 20 a minute across the two replicas); at most 2 replicas; the model deployment capped at 100 thousand tokens a minute.

**Watched:** dashboard tile 1 shows p50 and p95 latency against the 6 s SLO (2.25 s at p95 on 14 October); tile 3 shows tokens and estimated cost per score (about 0.0047 GBP); tile 6 shows both per request.

**Alerted:** p95 over 6 s for 15 minutes and availability under 99% in an hour, by email (a test alert was received, decision P3-7); a budget on the resource group with emails at 50%, 80% and 100% of 10 GBP. The availability alert rule running in Azure takes the query text corrected in decision S6-8 (an exact comparison at 99%, where the old text rounded first) only once the owner applies the observability deployment.

**Not built:** an alert on cost per score. The budget alert relies on Azure's cost data, which can lag by a day.

## 4. How is drift caught?

- **The model cannot drift silently.** The deployment is pinned to one model version with no automatic upgrade (spec section 9).
- **Quality against labels, every night.** The full eval suite runs nightly against the pinned deployment; kappa, agreement and the gate result per run are on tile 4, and a failed nightly run notifies the owner.
- **Prompt drift.** The prompt version and its hash are on every `score` span, and the registry test stops an unversioned change.
- **Live drift, without labels.** **Dashboard tile 5** (`tile5_drift_by_day`) gives one row per day: the share of scores at 1 or 2, at 3 and at 4 or 5, the mean score, the median answer length, and the injection and off-topic rates, with the change in mean score and median length against the first day in the chosen range. Tile 2's chart shows the review reasons over time. These show that inputs or outputs have moved, which is the prompt to look at the nightly eval; they cannot show that scores became wrong.

**Not built:** an alert on drift. A quiet day moves a lot, so the tile is read by a person.

## 5. How does the golden set grow?

**What is in place.** Every row carries where its label came from. A separate label-auditor agent re-labels each golden answer blind, and a fixed rule settles disagreements (spec section 7). Golden rows are split into `dev` and `holdout`, two and one in each competency and level, and prompt tuning looks at `dev` only. Datasets are a protected path, and any change goes through a pull request and the required `evals` gate. The build used the improvement loop once: an edge case the model handled inconsistently led to a deterministic control and a recorded decision (S4c-3).

**How a new case would get in today, by hand.** A problem is reported with its trace id. The maintainer finds the request's metadata, writes a synthetic answer that reproduces the problem (the candidate's own text is never stored, so it cannot be copied), labels it, has it audited blind, and opens a pull request that the gate runs on. Two things make this a deliberate change rather than a quick one: the dataset tests pin the exact size of each file and, for the golden set, two `dev` rows and one `holdout` row per competency and level, so a new golden case means a whole cell or a changed rule; and those tests are a protected path, so changing them needs the owner and a line in `intent/decisions.md`. The gate's own sizes are minimums, so it does not stop growth.

**Not built.** An automatic path from live traffic into the golden set. In production it would take reviewers' disagreements with the scorer as candidate cases, with consent and retention rules, labelled by trained raters; and the Maintain loop, which spec section 15 lists as Later, would write an incident file when a band is breached, from which new eval cases could be drawn.
