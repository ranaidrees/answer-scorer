# Plan: AI answer scorer with a trust harness

- **Status:** draft master plan (revised after independent review; see `CHANGELOG.md`). Each wave's slice sections are refined and accepted before code is written.
- **Reads:** `intent/intent.md`, `intent/spec.md`
- **Stage:** 3 of 6 (Build)
- **Features stop:** Wednesday 14 October 2026, 14:30. **Freeze:** Wednesday 14 October 2026, 18:00.

## Operating model

Claude Code builds, provisions, tests, merges and documents everything autonomously, with full access to this repo and the project's Azure resource group, in **auto mode** (a classifier reviews actions instead of the owner; deny rules still block in every mode).

A **lead session** orchestrates and does no slice work itself. Every slice runs as a **subagent**, briefed with its slice section below plus the spec sections it names:
- **Offline slices** (S2, S4a, S4b, S5a) run in the background, in parallel, each in its own git worktree (`isolation: worktree`).
- **Live slices** (V, S1, S3, S4c, S5b, S6, S8) touch Azure or GitHub settings and run one at a time, in the foreground, in the main checkout.
- At most three agents work at once. Agent teams are not used (experimental; no split panes in Windows Terminal).

The lead updates the **Status** section at the end of this file after every merge, so a new session can resume from it.

## Gates

**Automated gates (every PR).** The lead merges only when all of these pass, and the repository ruleset (empty bypass list) enforces the first two, so the agent cannot merge what fails:
- `ci` green (lint, tests, hook tests, gitleaks, Bicep build, image build).
- `evals` green (required from the S4c merge).
- `verifier` subagent returns PASS.
- Claude review findings marked Important are fixed.

**Decision rules the lead applies, each recorded in `intent/decisions.md`:**
- Wave plans: the `plan/wave-N` PR passes the Claude review against `intent/spec.md`.
- Golden labels: an independent auditor subagent re-labels every golden answer blind (spec section 7).
- Thresholds: confirmed only at the spec values or stricter, and only after the stability proof passes. **Loosening any threshold needs the owner.**
- Model region: the fallback in spec section 14 if UK South has no quota.

**Human touchpoints (the owner):**

| # | When | What | Time |
|---|---|---|---|
| H1 | Setup and W0 | Browser sign-ins (`gh`, `az`, `azd`, `claude`) and the Claude GitHub app consent (`/install-github-app`) | about 15 min |
| H2 | First image push (W3) | Make the `ghcr.io` package public (one settings toggle) | 1 min |
| H3 | Every production deploy | Approve the `demo` environment deployment in GitHub. The agent never approves a deployment | seconds each |
| H4 | Wednesday 15:00 to 18:00 | Final test, leak check (`git grep -i -f private/blocklist.txt`), rehearsals, acceptance (the `v1.0-demo` tag) | about 3 h |
| H5 | Optional, during H4 | Spot-check ten golden labels, recorded in `decisions.md` | 10 min |

## How every slice runs

1. The lead fetches and pulls `main`, then starts the slice subagent with its brief. Worktree subagents branch from the latest `main`.
2. The subagent implements, running `uv run poe check` until green. Fix the code, never the test. It commits, pushes its branch and returns; it does not open the PR.
3. The lead runs the `verifier` subagent on the branch; it must return PASS.
4. The lead rebases the branch on `main` (parallel slices all touch `pyproject.toml`, `uv.lock`, `decisions.md` and this file; resolve `uv.lock` conflicts by re-running `uv lock`), runs a security review of the diff (`/security-review` where available) and summarises it in the PR description, opens the PR, waits for the checks and the Claude review, and fixes Important findings.
5. The lead merges with `gh pr merge --squash --delete-branch` and updates **Status**.
6. Any departure from the plan is written under **Deviations** in the same PR.

## Waves

The build started on Tuesday 13 October, a day later than first planned, and follows the three phases in `instructions-for-claude-code.md`. Times are targets.

| Wave | Target | Slices | Ends when |
|---|---|---|---|
| Setup | Tuesday morning, owner present | Phase 1: sign-ins, repo, GitHub app (H1) | Tools signed in, repo created |
| W0 | Tuesday by 13:00, unattended | S0, GitHub app PR, ruleset, `demo` environment, V | Harness and rubrics merged |
| W1 | Tuesday by 16:00, unattended | S1 (live), with S2 and S4a (offline) in parallel | S1, S2, S4a merged |
| W2 | Tuesday by 20:00, unattended | S3 (live), with S4b and S5a (offline) in parallel | S3, S4b, S5a merged (S3 first) |
| W3 | Tuesday evening to Wednesday 07:00, unattended | S4c, then S6 with local traffic. The first deploy is queued for the owner | Gate proven, dashboard showing local data |
| W4 | Wednesday by 09:00, unattended | S8 with local screenshots and the final verification; items that need the live URL are marked "pending live" | Demo pack merged; lead stops and gives the build report |
| Finish | Wednesday 09:00 to 13:00, owner present | Phase 3: S5b (H2, H3), live traffic, live screenshots, re-verify "pending live" items | App live; all green or named |
| Test | Wednesday 15:00 to 18:00 | Owner H4 (and H5); lead fixes defects only | Freeze: warm (H3), smoke, tag |

**Keeping to the clock.** The unattended build runs without a break until it is finished, into Tuesday night if it has to. At the end of each wave the lead checks the clock (`date`) against the target. If it is more than two hours behind, it applies "Cut if behind" in order and records the cut under Deviations.

**Checkpoint, Wednesday 09:00.** The unattended build stops and reports whatever the state, so the owner can start Phase 3.

**Checkpoint, Wednesday 14:30.** Features stop whatever the state. The lead reports what is not green; it is shown from screenshots and named honestly in the walkthrough.

## Slices

### S0. Delivery harness (W0, lead session 1, then proof in session 2)

**Files:** `CLAUDE.md`, `REVIEW.md`, `LICENSE`, `README.md` (stub with disclaimer), `pyproject.toml` (with poe tasks), `.gitignore`, `.gitattributes`, `.claude/settings.json`, `.claude/hooks/cloud_gate.py`, `.claude/hooks/protect_evidence.py`, `.claude/hooks/format_py.py`, `.claude/agents/verifier.md`, `.claude/agents/label-auditor.md`, `.claude/skills/fair-scoring-policy/SKILL.md`, `.mcp.json`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `.github/CODEOWNERS`, `tests/hooks/*`, `intent/decisions.md`.

**Order:** pyproject and poe tasks; hooks with allow and deny tests; settings (narrow allow rules; deny rules carry the safety); `CLAUDE.md` and `REVIEW.md`; verifier, label auditor and skill; MCP servers; `ci.yml` following the workflow hygiene in spec section 9 (actions pinned to SHAs, least-privilege permissions, `cache-mode`); `dependabot.yml` for the `github-actions` ecosystem; decisions seeded from spec section 13. Then stop: hooks, settings and agents load when a session starts.

**Risks:** a gate hook that fails open (exit 1) or blocks everything (fails closed on a missing tool); PowerShell commands slipping past a Bash-only matcher; the Azure MCP server not starting on Windows.

**Proof** (in session 2):
- `uv run poe check` passes, including allow and deny cases for every hook rule.
- `azd up` and `az group delete` are denied with a reason.
- The verifier returns a verdict on the S0 branch.
- `claude mcp list` (or `/mcp`) shows both MCP servers connected.

After the S0 merge: the owner runs `/install-github-app` (H1); the lead pins `claude-code-action` to a SHA at version 1.0.74 or later with `show_full_output` off, creates a repository ruleset on `main` (PR required, required check `ci`, block force pushes and deletion, empty bypass list) and creates environment `demo` with the owner as required reviewer.

### V. Design validation (W0, live)

**Files:** `rubrics/teamwork.yaml`, `rubrics/problem_solving.yaml`, `intent/spec.md` (status), `intent/decisions.md`, `.github/workflows/claude-code-review.yml` (prompt points at `REVIEW.md`).

**Order:** record the quota check; check any **[confirm]** item that needs no resources; write both rubrics (generic, observable behaviours per level); have an independent subagent check them against FR-2 and the fair-scoring policy; record the spec section 13 decisions as accepted; set spec status to "accepted".

**Proof:** quota recorded; rubric check recorded; the V PR shows a Claude review comment that cites `REVIEW.md`.

### S1. Azure bootstrap (W1, live)

**Files:** `azure.yaml`, `infra/main.bicep`, `infra/modules/*`, a Bicep build step in `.github/workflows/ci.yml`, `scripts/setup_env_local.py`, `docs/architecture.md`, decision entries for model, region, roles and identities.

**Order:** Bicep for spec section 9 resources (Foundry with `disableLocalAuth: true`; the deployment with `raiPolicyName: Microsoft.DefaultV2`; `owner` tags; placeholder image on port 80, no custom probes, single revision mode, non-secret Container App environment variables); `az bicep build` clean; `azd provision`; the app identity role and the owner's own Cognitive Services OpenAI User role; `id-deploy` and `id-eval` with immutable-format federated credentials and roles; `scripts/setup_env_local.py` writes the whole git-ignored `.env.local` (values from `azd env get-values` plus a generated demo token) and never prints it, because Claude cannot read or edit that file; the demo token set as a Container App secret with its `secretref` variable, and as a `demo` environment secret, from that file; GitHub variables (client, tenant, subscription IDs) and the Application Insights connection string secret.

**Risks:** quota; role assignment propagation delay (retry after a minute); OIDC subject format.

**Proof:** a one-line inference call with the owner's `az login` succeeds; Application Insights is connected to the Foundry project; `azd env get-values` lists endpoints; both identities exist with the expected federated subjects and roles (read-only checks).

### S2. Scorer core, offline (W1, worktree)

**Files:** `src/scorer/{schemas,config,sanitise,redact,injection,grounding,rationale_screen,aggregate,pipeline,model_client}.py` (fake client only), `prompts/scorer/v1.md`, `prompts/scorer/registry.yaml` (with `active: v1`), `tests/unit/*`.

**Order:** schemas and config; rubric loader; sanitiser (tests first: zero-width, bidirectional and tag characters, HTML); redaction (with the empty-after-redaction rule); grounding (tests first); injection heuristics; rationale screen (tests first); aggregation and routing (tests first); pipeline with a fake model client that can also simulate a `content_filter` block (tests first: routed with no score, never 503); identity-blind payload test (tests first); prompt v1 (refers to "the candidate", never a name or pronoun) and hash registry.

**Risks:** grounding too strict or too loose; heuristic false positives on normal answers.

**Proof:** `uv run poe test` green; one named test per acceptance criterion FR-1 (validation and 400 cases) to FR-8; a test asserts `candidate_ref` never reaches the model payload. FR-1's 401, 429 and 503 cases need the API and are proved in S3.

### S4a. Datasets and label audit (W1, worktree)

**Files:** `evals/datasets/{golden,fairness_pairs,injection,edge_cases}.jsonl`, `evals/label_audit.md`, `tests/unit/test_datasets.py`.

**Order:** generate exactly as spec section 7 describes (sizes, splits, pair types, injection types with 2 paraphrased variants each, edge cases with `expected`); every row has `label_source` and a one-line reason; the `label-auditor` subagent re-labels every golden answer blind (rubric and answer only); apply the audit rule in spec section 7; write `evals/label_audit.md` (agreement, every disagreement and how it was resolved).

**Risks:** labels too easy; injection text written to attack agents in general rather than the scorer.

**Proof:** a schema test over every dataset file; audit agreement recorded in `decisions.md`.

### S3. Live model, API, UI, telemetry (W2, live)

**Files:** `src/scorer/model_client.py` (Foundry client, keyless), `src/scorer/api.py`, `src/scorer/telemetry.py`, `src/scorer/ui/index.html`, `config/prices.yaml`, `scripts/smoke.py` (both modes: `--local` and `--remote`, behind the poe tasks `smoke` and `smoke-remote`).

**Order:** confirm the client pattern on Microsoft Learn (the `openai` package against `<endpoint>/openai/v1/` with `get_bearer_token_provider`; strict JSON schema with an integer enum; `reasoning_effort: "none"`; `max_completion_tokens` 600; no temperature); three parallel calls with timeouts, one retry on transient errors, 503 on failure, and `content_filter` blocks handled as routed outcomes; FastAPI routes, demo token check, per-IP rate limit; telemetry with the fixed attribute names and content capture off; one-page UI with three sample buttons, the trace id, the AI-use disclosure and a "Report a problem" link; `prices.yaml` from the pricing page with URL and date. Send the injection sample live once and record in `decisions.md` whether Azure's guardrail blocked it, so the walkthrough says what will actually happen.

**Risks:** structured-output schema rejected; tracing setup differs from the docs.

**Proof:** API tests for FR-1's 401, 429 and 503 cases; `uv run poe run` locally; `uv run poe smoke` passes (strong, weak, injection); the trace is visible in Application Insights within 5 minutes; a read-only KQL query shows no answer text in telemetry.

### S4b. Eval runner and workflow (W2, worktree)

**Files:** `evals/thresholds.yaml`, `evals/run_evals.py`, `evals/report.py`, `.github/workflows/evals.yml`, `tests/unit/test_metrics.py`.

**Order:** metrics (QWK, agreement, pair tolerances, injection rules with guardrail blocks counted as flagged and routed, edge cases, ungrounded, protected-term and review rates, noise floor and fairness flip rate) with unit tests against hand-computed examples; defect vs variance classification; reports following the reporting rules in spec section 7 (n beside every metric, no confidence intervals on 30 items, fixed settings printed, item order randomised with a logged seed) as `.md`, `.json` and a job summary; `eval_run` event; `evals.yml` with one job named `evals` (OIDC as `id-eval`, path check step that always reports, nightly 02:00 UTC, manual, PR comment). Runs offline against the fake client; live runs happen in S4c.

**Risks:** QWK computed wrongly; workflow path check skipping a relevant change.

**Proof:** metric unit tests green; a dry run with the fake client produces a complete report.

### S5a. Deploy pipeline files (W2, worktree)

**Files:** `Dockerfile`, image build step in `ci.yml`, `.github/workflows/deploy.yml` (calls `scripts/smoke.py --remote`, which S3 owns).

**Order:** Dockerfile (slim Python 3.12 base, non-root user, uv, port 8000, no HEALTHCHECK); build-only step in `ci.yml`; `deploy.yml` as spec section 9 describes, following the workflow hygiene there (build and push to `ghcr.io`; signed provenance with `actions/attest@v4`; `demo` environment; `gh attestation verify` by digest before any change; OIDC as `id-deploy`; first deploy sets port 8000 and probes; smoke with a 60 s cold-start allowance; inputs `warm` and `image_sha`; `paths-ignore` for `intent/**`, `docs/**` and `*.md` so documentation merges do not queue deploys; nothing secret echoed). Merged after S3, because its merge queues the first deploy.

**Risks:** image builds in CI only, so each Dockerfile fix costs a CI round trip.

**Proof:** the PR's `ci` run builds the image; `deploy.yml` passes `actionlint` if available.

### S4c. Baseline, stability proof, gate, weak PR (W3, live)

**Order:** on branch `s4-evals`, create `.claude/fix-mode`; live baseline; if a threshold fails, diagnose on `dev` cases only and iterate the prompt as a new version with the registry updated, never thresholds or datasets; remove `.claude/fix-mode`; create a local branch `demo/weak-prompt` from `s4-evals` with `prompts/scorer/v0-weak.md` and `active: v0-weak`; stability proof (three full runs on `s4-evals`, all pass; three on `demo/weak-prompt`, all fail); confirm thresholds by the rule in **Gates**; merge `s4-evals`; add `evals` to the required checks; move the weak branch onto `main` with `git rebase --onto main s4-evals demo/weak-prompt` (this works after a squash merge), push it and open its PR so the required gate fails. Do not merge it.

**Risks:** baseline below threshold; weak prompt not failing (redesign it to break grounding harder, record the change).

**Proof:** baseline report committed; six stability results in `decisions.md`; `main` passes the gate; the weak-prompt PR shows the failed required check and a blocked merge.

### S5b. First deploy (W3, live)

**Order:** after the first build job pushes, ask the owner to make the `ghcr.io` package public (H2) and wait; tell the owner a deployment is waiting (H3) and wait; read the logs (`gh run view`) and confirm smoke results; dispatch `warm=true` once and `image_sha` with the same SHA once to prove both routes (each waits for H3); reject nothing on the owner's behalf.

**Risks:** OIDC subject mismatch (fix the credential from the subject named in the error); GHCR still private; cold start.

**Proof:** a green deploy with the owner as approver; smoke passed; the live URL scores J1, J2 and J3.

### S6. Observability (W3, live)

**Files:** `infra/observability.bicep`, `infra/workbook.json`, `dashboards/queries.kql`, `docs/slo.md`, `scripts/traffic.py`.

**Order:** KQL per tile, each tested with a read-only query against real data; workbook, action group (email as a parameter) and two log alerts in `observability.bicep`, deployed with `az deployment group create` (never `azd provision`); `traffic.py` with `normal` and `injection-burst` profiles using `dev` samples only, rate limited; a test alert.

**Risks:** workbook JSON fiddly (time box one hour; fallback: four saved Log Analytics queries).

**Proof:** after `traffic.py`, all four tiles show data; a test alert reaches email.

### S7. Maintain loop

Cut. See spec section 15.

### S8. Demo pack and final verification (W4, live)

**Files:** `docs/governance.md`, `docs/eval_card.md`, `docs/walkthrough.md`, `README.md`, `docs/screenshots/*`.

**Order:** governance mapping from spec section 11 (including the platform terms and agentic practice paragraph), linking each control to the file, test or tile that proves it; the eval card as spec section 7 describes; the walkthrough below with exact clicks, sample inputs and a fallback per step; README with a results scoreboard at the top (main vs weak-prompt metrics, noise floor and fairness flip rate, p95, cost per score, review rate, label audit agreement, PR count, AI review findings fixed, verifier catches), the four-layer defence table from spec section 6, the architecture diagram, an "AI use" section (an agent wrote the code; the gates it had to pass; the decisions only the owner made), how it was built (artifact chain with links to each PR, and who decided what: agent, rule or owner) and the disclaimer; screenshots of the live app and GitHub pages with Playwright (the owner adds Azure portal screenshots in H4); then a **fresh-context verifier run** against every item in intent's "How we will know it worked" and every FR acceptance criterion, producing a pass or fail checklist. Then stop and report to the owner.

**Proof:** verification checklist clean or each gap listed in the walkthrough; demo pack merged.

## Walkthrough (eight minutes, ten at most)

Tabs, left to right: GitHub README, live app, Foundry portal (model deployment), Application Insights, weak-prompt PR, Actions deploy run, dashboard.

| Time | Show | Say (one line) |
|---|---|---|
| 0:00 to 0:40 | **GitHub README** scoreboard | Scoring is easy; trusted scoring in a high-risk domain is the hard part. Here are the results. |
| 0:40 to 2:40 | **Live app**: J1 strong, J2 injection, J3 weak | Input guards, the model, then output guards: evidence is quoted and checked, manipulation is caught by our screen and Azure's guardrail and goes to a human, and every adverse outcome goes to a human. |
| 2:40 to 3:30 | **Foundry** model deployment (pinned version, no auto-upgrade, keyless access), then the J1 trace in **Application Insights** | The model cannot change under us, nothing uses a key, and every decision is traceable without storing candidate text. |
| 3:30 to 5:00 | **Test**: weak-prompt PR with the failed required `evals` check and its comment | A realistic "friendlier" prompt change was blocked before merge, and the gate is proven stable. |
| 5:00 to 6:00 | **Build**: Actions `ci` run, then the deploy run verifying the image's signed provenance and waiting for my approval | The agent merged only what the gates passed; the deploy refuses any image our pipeline did not build; nothing reached production without me. |
| 6:00 to 7:00 | **Dashboard** | Online evaluation on every live request: review rate by reason, plus p95 against the SLO, cost per score and the offline eval trend. |
| 7:00 to 8:00 | **Repo history**: intent, spec, plan, PRs with AI review and verifier verdicts, `decisions.md` | Claude Code built and merged it inside gates I designed; I own intent, the gates and production. That is how I would run AI-native delivery for a team. |
| 8:00 to 10:00 | Buffer for questions | What production adds: trained raters, adverse impact analysis, DPIA, and the 2 December 2027 date. |

**Five-minute cut:** README (0:30), live app J1 and J2 (1:30), weak-prompt PR (1:00), deploy approval (0:30), repo history (1:00), close (0:30).

## Walkthrough day

At freeze (Wednesday 18:00): the lead dispatches `deploy.yml` with `warm=true` (min replicas 1, no rebuild) and the owner approves it (H3); `uv run poe smoke-remote`; the owner tags `v1.0-demo`.

On the day at 11:00: `uv run poe smoke-remote`, `scripts/traffic.py --profile normal`, open the tabs, keep the screenshots and recording ready. No deploys on the day. Afterwards: disable the nightly schedule, then tear down (RUNBOOK section 7).

## Cut if behind (in this order)

1. Nightly eval schedule (keep PR and manual triggers)
2. Workbook (use four saved Log Analytics queries)
3. Per-IP rate limit (the demo token stays)
4. Smoke test inside the deploy job (the approval gate stays)

Already cut by review: Maintain loop, Prompt Shields, Foundry evaluation view, council subagents and the eval-analyst subagent, automatic rollback and deployment events, workbook and alerts in `main.bicep`, the guard-secrets hook, Bash-write parsing, two of three skills.

**Never cut:** grounding check, injection eval, identity-blind schema, eval gate with its stability proof, deploy approval by the owner.

## Status

Not started.

## Deviations

None yet.
