# Governance note

**Demo level, not legal advice.** This page maps the demo's controls to the regulatory requirements named in [the spec](../intent/spec.md), section 11, and links each control to the file, test or dashboard tile that shows it. It repeats the spec's wording on the law and adds no legal claim of its own. Nothing here is a compliance assessment, and the repository records no review of this page by a person.

The demo runs on synthetic data and is not for use in real hiring decisions. Its evidence shows that the controls behave as designed. It does not show that the scores are right: reliability is not validity.

## 1. Why this domain is high-risk

- Recruitment and selection AI is high-risk under the EU AI Act: Annex III, point 4(a) covers systems "intended to be used for the recruitment or selection of natural persons, in particular ... to evaluate candidates".
- Under Article 6(3), an Annex III system that profiles natural persons is always high-risk.
- After the Digital Omnibus on AI (Regulation (EU) 2026/1744, in force 27 July 2026), the high-risk obligations for Annex III systems apply from **2 December 2027**.
- The Commission's guidelines on high-risk classification are still a draft (published 19 May 2026, updated 23 July 2026).
- Of the supporting standards, EN 18286:2026 (quality management system) is published, while the risk management and bias standards are still in development.
- The Commission's AI literacy Q&A (Article 4, updated 27 July 2026) expects deployers of high-risk systems to train the people who provide human oversight.

## 2. Provider requirements: Articles 9 to 15

Articles 9 to 15 are requirements on the system that the **provider** must meet (Article 16). The table gives the demo control for each and where to see it. "Tile" means a tile of the dashboard workbook, whose queries are in [dashboards/queries.kql](../dashboards/queries.kql) and whose layout is in [infra/workbook.json](../infra/workbook.json); the four tile queries return data when run with the read-only CLI against telemetry from the app run locally, but nobody has looked at the workbook in the portal yet, and the dashboard on traffic from the deployed application is pending live.

| Requirement area | Demo control | Where to see it |
|---|---|---|
| Risk management (Art. 9) | Failure mode table; eval gate; SLO bands | Failure modes: [spec](../intent/spec.md), section 6. Gate: [thresholds](../evals/thresholds.yaml), [runner](../evals/run_evals.py), [metrics](../evals/metrics.py), [metric tests](../tests/unit/test_metrics.py), [evals workflow](../.github/workflows/evals.yml). Bands: [SLOs](slo.md), tile 1 (`tile1_requests_latency`) and tile 2 (`tile2_review_rate_by_reason`) |
| Data and data governance (Art. 10) | Synthetic data; label provenance; fairness counterfactuals; holdout split | [Golden set](../evals/datasets/golden.jsonl), [fairness pairs](../evals/datasets/fairness_pairs.jsonl), [injection set](../evals/datasets/injection.jsonl), [edge cases](../evals/datasets/edge_cases.jsonl); [label audit](../evals/label_audit.md); [dataset schema test](../tests/unit/test_datasets.py); [eval card](eval_card.md). Holdout rows count in every metric but are not listed in the Markdown report or the pull request comment (decision S4b-11) |
| Technical documentation (Art. 11) | Intent, spec, plan, decisions log and eval reports in git | [Intent](../intent/intent.md), [spec](../intent/spec.md), [plan](../intent/plan.md), [decisions](../intent/decisions.md), [architecture](architecture.md), [eval card](eval_card.md). Eval reports: one Markdown and one JSON file per local run on the accepted prompt, and for the first CI run, under [evals/reports/](../evals/reports/), named by the run ids in the [eval card](eval_card.md); the reports of the later CI runs are artifacts of their workflow runs |
| Record-keeping (Art. 12) | A trace per decision with prompt version, model version and flags; no candidate text | [Telemetry](../src/scorer/telemetry.py) and [its tests](../tests/unit/test_telemetry.py); [content capture stays off](../tests/unit/test_genai_instrumentation.py); the 21 fixed `scorer.*` attribute names in [CLAUDE.md](../CLAUDE.md); a search of live telemetry that found no answer text (decision S3-13) |
| Transparency and provision of information to deployers (Art. 13) | Decision-support notice; rationale and evidence shown; model and prompt version returned | [Response schema](../src/scorer/schemas.py); [demo page](../src/scorer/ui/index.html) and [its test](../tests/unit/test_demo_page.py); [prompt registry](../prompts/scorer/registry.yaml) and [versioning tests](../tests/unit/test_fr3_prompt_versioning.py) |
| Human oversight (Art. 14) | Review routing rules; adverse outcomes always reviewed; no auto-reject | [Routing](../src/scorer/aggregate.py) and [routing tests](../tests/unit/test_fr8_review_routing.py); [fair-scoring policy](../.claude/skills/fair-scoring-policy/SKILL.md), rule 4; tile 2 (`tile2_review_rate_by_reason`) |
| Accuracy, robustness and cybersecurity (Art. 15) | Agreement metrics; consistency rule; injection guard; keyless auth | Agreement: [metrics](../evals/metrics.py) and the [eval card](eval_card.md). Consistency: [aggregation](../src/scorer/aggregate.py) and [its tests](../tests/unit/test_fr4_aggregate.py). Injection: [sanitiser](../src/scorer/sanitise.py), [screen](../src/scorer/injection.py), [tests](../tests/unit/test_fr6_injection.py), [dataset check](../tests/unit/test_fr6_datasets_offline.py). Keyless: [Foundry resource](../infra/modules/foundry.bicep) with key authentication disabled, [model client](../src/scorer/model_client.py) and [its test](../tests/unit/test_foundry_client.py), [identities](../infra/modules/identity.bicep) |

Three supporting controls sit under more than one row:

- **Question echo.** An answer that only repeats the question is flagged off topic and routed by a deterministic check, whatever the model says: `src/scorer/echo.py` (decision S4c-3). It was added when the stability proof showed the model alone was inconsistent on that case.
- **Grounding.** Every evidence quote is checked against the answer without a model, and an ungrounded quote is removed, counted and routed: [grounding](../src/scorer/grounding.py) and [its tests](../tests/unit/test_fr7_grounding.py).
- **Identity-blind input.** The request schema has no identity field and turns away unknown fields, and the opaque reference never reaches the model: [identity-blind tests](../tests/unit/test_fr5_identity_blind.py). The rationale is screened for protected terms and names: [rationale screen](../src/scorer/rationale_screen.py) and [its tests](../tests/unit/test_fr4_rationale_screen.py).

### What this evidence does and does not show

- The agreement figures are measured against labels that Claude wrote and Claude audited. They show consistency with those labels, not accuracy against trained raters.
- The fairness evidence is 16 counterfactual pairs of synthetic text. It is a regression check on the scorer, not an adverse impact analysis.
- The gate's stability proof on the accepted prompt is three consecutive passing runs on one commit, reached at the third attempt (decision S4c-7). The first attempt ended in a failed run and the second in a stopped run; both were fixed in code, and no threshold, dataset, rubric or prompt changed. The [eval card](eval_card.md#stability-proof) tells it in full. The weak-prompt half is three consecutive failing runs on one commit (decision S4c-11), and a fourth failing run in CI on pull request #15, whose merge the required `evals` check blocks: each of the four breached the ungrounded quote rate (every quote, 332 to 334 of them) and the control-triggered review rate (30 of 30); two also breached an injection pair gate and one the edge cases. The weakened prompt still met the agreement gates each time, so it is the grounding and review-rate gates that catch it.
- The fairness gates can be breached by model noise alone. The identity-pair mean sat exactly on its limit in two of the first eight live runs (decision S4c-12), the dialect and verbosity mean did the same in the ninth, and the build's lead session estimates that roughly 1 full run in 20 would breach a pair gate with no change to the system. That is an estimate from eight runs, not a measured rate; a production gate would use more pairs.
- Record-keeping is proven on local runs against the live model (decision S3-13). The review rate has been measured on 41 requests from the app run locally against the live model: control-triggered 9 of 41 (22%), inside the 25% band, on a mix that deliberately included a burst of injected answers. On the deployed application both are pending live.
- The platform guardrail path (a blocked call becomes a routed outcome with no score) is proven by unit tests only; the guardrail did not block the injection sample in live testing (decision S3-12).

## 3. Deployer duties: Article 26

**Deployers** (the employers using such a system) have their own duties under Article 26, including 26(7): employers must inform workers' representatives and affected workers before use.

The demo has no deployer. What it offers a deployer is the information a person providing oversight would need: the decision-support notice, the rationale, the quoted evidence, the review reasons, and the prompt and model version on every response ([response schema](../src/scorer/schemas.py)). Informing people, training reviewers and running the review itself would be the deployer's process, and none of it is built here: there is no review queue.

## 4. The UK position: Articles 22A to 22D

- Article 22 of the UK GDPR was replaced by Articles 22A to 22D by section 80 of the Data (Use and Access) Act 2025, in force since 5 February 2026.
- Solely automated significant decisions are now restricted mainly where special category data is involved, and safeguards are required: information about the decision, the chance to make representations, human intervention, and the right to contest.
- The ICO's guidance on the new provisions is still in draft, with the final version due in winter 2026, so the demo is described as aligned to the draft.
- The demo's design (no solely automated decisions; every adverse outcome reviewed; rationale and evidence shown) is built to support these safeguards; information to candidates and a contest route would be the deployer's process.

| Safeguard | What the demo's design offers | Where to see it |
|---|---|---|
| Information about the decision | Rationale, verbatim evidence, review reasons and the notice on every response | [Response schema](../src/scorer/schemas.py), [demo page](../src/scorer/ui/index.html) |
| Human intervention | A score of 1 or 2, or any tripped control, is routed to a person; the service decides nothing by itself | [Routing](../src/scorer/aggregate.py), [routing tests](../tests/unit/test_fr8_review_routing.py) |
| Representations and the right to contest | Not built. The deployer's process | None |

## 5. Platform terms and agentic practice

- Microsoft's Transparency Note for Azure OpenAI advises against uses with consequential impact on employment unless there is meaningful human review, and Microsoft's AI Code of Conduct asks for appropriate human oversight, disclosure of AI use and a feedback channel.
- The demo provides all three: review routing ([routing](../src/scorer/aggregate.py)), the UI disclosure ([demo page](../src/scorer/ui/index.html)) and the "Report a problem" link ([issue form](../.github/ISSUE_TEMPLATE/report-a-problem.yml); nothing is sent automatically).
- For the agent-built delivery, the joint CISA and UK NCSC guidance "Careful Adoption of Agentic AI Services" (May 2026) recommends limited autonomy, least privilege and layered defences, which the harness applies: deny rules, scoped identities, required checks, and an owner-only production gate.
- The README's "AI use" section discloses how the code was produced, as the OpenSSF and CNCF guidance "Securing Open Source in the Age of AI" (May 2026) recommends: [AI use](../README.md#ai-use).

| Harness control | Where to see it |
|---|---|
| Deny rules, in every permission mode | [Settings](../.claude/settings.json) |
| Command gate, fail closed | [cloud_gate.py](../.claude/hooks/cloud_gate.py) and [its tests](../tests/hooks/test_cloud_gate.py); [evidence lock](../.claude/hooks/protect_evidence.py) and [its tests](../tests/hooks/test_protect_evidence.py) |
| Scoped identities | [Architecture](architecture.md#identities), [identity module](../infra/modules/identity.bicep) |
| Required checks | [ci](../.github/workflows/ci.yml) and [evals](../.github/workflows/evals.yml) are both required on `main`; `evals` was added after the stability proof (pull request #13) merged, and the ruleset was read back after the change, with an empty bypass list. The weak-prompt pull request, #15, shows it: `ci` passes, `evals` fails and the merge is blocked. The ruleset lives in GitHub settings, not in a file (decision D22) |
| Independent verification | [Verifier](../.claude/agents/verifier.md), [label auditor](../.claude/agents/label-auditor.md), [review standard](../REVIEW.md) |
| Owner-only production gate | The `demo` environment in the [deploy workflow](../.github/workflows/deploy.yml), with signed build provenance verified before any change. No deploy has run yet: the run queued by the merge of #13 waits for the owner's approval, so this is pending live |

The limits of the harness are recorded as they are. Hooks and permission rules are guardrails, not a security boundary (decision D14); the hard boundaries are the ruleset with an empty bypass list, the owner-only approval and the scope of each identity. Azure identifiers, not credentials, were printed in one workflow log and are now held as secrets (decision F-1).

## 6. What production would add

Production would add real rater calibration, adverse impact analysis on consented demographic data, a DPIA and a model card.

The US "four-fifths rule" (29 CFR 1607.4(D)) is a useful monitoring heuristic but not a UK or EU legal test; in the UK the test for indirect discrimination is "particular disadvantage" under section 19 of the Equality Act 2010.

Also outside this demo, from the spec's "Later" list: a review queue, sampled online evaluation of live outputs with consent and retention rules, Prompt Shields document-attack detection, and a regional or data-zone deployment in place of Global Standard (decision C14).
