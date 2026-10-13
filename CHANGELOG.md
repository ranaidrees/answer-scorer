# Changelog

## 2026-10-13: daytime start, spend limit

- **Three-phase instructions.** `instructions-for-claude-code.md` now runs the build: setup with the owner, an unattended build, then a finish with the owner. Where it differs from RUNBOOK section 4, it wins.
- **Schedule.** The build starts on Tuesday 13 October, in the day. Wave targets in `plan.md` are compressed to keep the Wednesday 14:30 and 18:00 deadlines, with a 09:00 Wednesday stop for the unattended build.
- **Spend limit of 10 GBP.** Free or pay-per-use resources only, a log ingestion cap, a running estimate of model spend, and owner approval before any run that would take the total past the limit. Prices come from the Azure Retail Prices API.
- **Model quota.** Checked on 13 October: UK South has quota, so the fallback region is not needed. Capacity 100.

## 2026-10-12 (v4): current practice from reputable sources

Each change is backed by an official source dated between 12 April and 12 October 2026.

### Risk reducers

- **Azure guardrail block handled as a routed outcome.** The default `Microsoft.DefaultV2` policy checks prompts for jailbreak attempts and returns HTTP 400 `content_filter`. A block now returns no score, sets `platform_guardrail` and goes to human review; it is never a 503. The guardrail is bound explicitly in Bicep. Source: Microsoft Learn, "Default Guardrail policies" (updated 9 Oct 2026). (`spec.md` FR-1, FR-4, FR-6, FR-8, section 9; `plan.md` S1, S2, S3)
- **claude-code-action pinned at version 1.0.74 or later**, with `show_full_output` off. Earlier versions let a `.mcp.json` in a PR run code in CI (CVE-2026-47751), and this repo has a `.mcp.json`. Source: GHSA-8q5r-mmjf-575q (20 May 2026). (`spec.md` section 9; RUNBOOK Prompt B)
- **Auto mode relies on deny rules, not broad allow rules.** Auto mode sets aside allow rules that permit arbitrary code. Source: Anthropic, "Auto mode default in Claude Code" (7 Aug 2026). (`spec.md` section 10)
- **Input sanitiser.** NFKC normalisation; zero-width, bidirectional and tag characters and HTML stripped before scoring; removal counts as an injection signal. Source: Microsoft, "Prompt Injection (Direct/Indirect)" (1 Aug 2026). (`spec.md` FR-4; `plan.md` S2)
- **Workflow hygiene.** Actions pinned to SHAs, Dependabot for `github-actions`, CodeQL default setup for Python and Actions, `cache-mode: read` on PR jobs, current majors (Node 20 removed). Sources: GitHub changelog, 3 Sep, 10 Sep and 23 Sep 2026. (`spec.md` section 9; `plan.md` S0, S5a; RUNBOOK Prompt A)
- **Repository ruleset** instead of classic branch protection, with an empty bypass list. Source: GitHub changelog (11 Aug 2026). (`spec.md` section 9; `plan.md` S0; RUNBOOK Prompt B)

### Story strengtheners

- **`disableLocalAuth: true` on the Foundry resource and `max_completion_tokens` capped**, so "no keys exist" is a fact. Source: Microsoft Learn, baseline Foundry chat architecture (17 Jun 2026). (`spec.md` FR-4, sections 5 and 9)
- **Two paraphrased variants of each injection** (24 injection answers; 92 eval inputs). Source: Anthropic, "How we contain Claude" (25 May 2026). (`spec.md` section 7; `plan.md` S4a)
- **Noise floor and fairness flip rate** reported, not gated. Sources: UK AISI (27 Aug 2026), with a university preprint as support. (`spec.md` section 7; `plan.md` S4b)
- **Reporting rules and a one-page eval card** (`docs/eval_card.md`): n beside every metric, no confidence intervals on 30 items, fixed settings, seeded item order, and a validity statement. Sources: NIST AI 200-2 draft (Aug 2026), UK AISI (23 Jul 2026). (`spec.md` section 7; `plan.md` S8)
- **Signed build provenance** with `actions/attest@v4`, verified with `gh attestation verify` before every deploy. (`spec.md` section 9; `plan.md` S5a)
- **Security review of every diff before its PR** (`/security-review`). Source: Anthropic, "How Anthropic secures its AI-native SDLC" (21 Jul 2026). (`spec.md` section 10; `plan.md`; RUNBOOK)
- **README "AI use" section** disclosing how the code was produced. Source: OpenSSF and CNCF, "Securing Open Source in the Age of AI" (May 2026). (`plan.md` S8)
- **Microsoft employment-use terms**: UI disclosure and a "Report a problem" link; governance cites the Transparency Note (21 Sep 2026) and AI Code of Conduct (1 May 2026). (`spec.md` FR-9, section 11)
- **Regulatory lines**: Commission high-risk guidelines still a draft (23 Jul 2026); EN 18286:2026 published; ICO final ADM guidance due winter 2026; AI literacy Q&A; CISA and UK NCSC agentic AI guidance (May 2026). (`spec.md` section 11)

### Added after review of the guard layers

- **Rationale screen (output guard)**: a deterministic check that the rationale never mentions a protected attribute or a name from the answer; a hit is routed to review. (`spec.md` FR-4, FR-8; `plan.md` S2)
- **Defence-in-depth table** naming the four layers (input guards, output guards, offline evals, online evals), and a decision (C21) on why no LLM judge runs on live traffic. (`spec.md` sections 6 and 13; `intent.md`)

## 2026-10-12: revision after independent review

Applies the ten review fixes and the "cut now" list, and changes the operating model so Claude Code does the whole build autonomously, while the owner keeps sign-ins, production deploy approvals and final acceptance. Same file structure; this changelog is new.

### Ten fixes

1. **Scope vs time.** Cut list applied (below). Waves replace the day-by-day slice order; features stop Wednesday 14:30. (`plan.md`)
2. **Eval gate stability and J4.** Pair rules are now tolerances (mean difference at most 0.25, no pair more than 1 apart) instead of zero-difference rules on a model with no temperature setting. `v0-weak` is now a realistic "friendlier output" change that paraphrases evidence, so the deterministic grounding check catches it. A three-by-three stability proof is required before thresholds are confirmed. The weak branch is opened only after the gate is on `main`. (`spec.md` sections 3 and 7, `plan.md` S4c)
3. **Model.** gpt-5.4-mini 2026-03-17, Global Standard, UK South, `NoAutoUpgrade`, `reasoning_effort: "none"`, score as an integer enum. gpt-4.1-mini, gpt-4.1-nano and gpt-4o-mini are Deprecated and closed to new customers. Data residency trade-off recorded. `azure-ai-inference` (retired) banned in `CLAUDE.md`. (`spec.md` sections 4, 5, 9 and 13)
4. **Walkthrough-day traps.** Warm at freeze on Wednesday with no rebuild; no deploys on the day. J2 wording is "flagged, treated as data, routed to a human". Traces are shown in Application Insights, not the Foundry portal. (`spec.md` sections 3, 4 and 8, `plan.md`)
5. **Re-provisioning reset.** Placeholder on port 80 with no custom probes; the first deploy sets port 8000 and probes; `main.bicep` is never re-provisioned after the first deploy; S6 lives in `infra/observability.bicep`. Rollback is redeploying an earlier image (`image_sha`), because traffic shifting needs multiple revision mode. (`spec.md` section 9, `plan.md` S1, S5a, S5b, S6)
6. **Required checks.** `evals.yml` runs on every PR and always reports (path check inside the job), and becomes a required check when S4c merges. "Do not allow bypassing the above settings" ticked. (`spec.md` sections 7 and 9)
7. **OIDC.** Immutable subject format for repos created after 15 July 2026; identities created with the Azure CLI, not `azd pipeline config`. (`spec.md` section 9)
8. **Identity permissions.** `eval_run` events use the Application Insights connection string from a GitHub secret; deployment and rollback events cut; `id-deploy` has Container Apps Contributor on the app; app and `id-eval` have Cognitive Services OpenAI User; GHCR package made public before the first deploy approval. (`spec.md` sections 8, 9 and 13)
9. **Legal statements.** Annex III obligations from 2 December 2027 (Regulation (EU) 2026/1744); Article 6(3) profiling; Articles 9 to 15 as provider duties; Article 13 full title; Article 26 for deployers; UK GDPR Articles 22A to 22D (in force 5 February 2026); four-fifths rule labelled as a US heuristic. (`intent.md`, `spec.md` section 11)
10. **Harness claims.** Hooks described as guardrails, not a boundary; Bash-write parsing replaced by a verifier check on protected paths; review prompt points at `REVIEW.md`; `--bare` advice removed. (`spec.md` sections 9 and 10)

### Cut now

S7 Maintain loop and its prompt; Prompt Shields; Foundry evaluation view and the Foundry trace link; council subagents, `/council` and the eval-analyst subagent; automatic rollback, `simulate_smoke_failure`, deployment and rollback events and the change-failure tile; workbook and alerts in `main.bicep`; the guard-secrets hook; Bash-write parsing; two of the three skills (azure and observability conventions moved into `CLAUDE.md`). All listed under Later in `spec.md` section 15.

### Autonomous build (new)

- Claude Code creates the repo, provisions Azure, sets up GitHub, builds, evaluates, merges and documents, in **auto mode**, with full access to this repo and the project's resource group. `bypassPermissions` is not used on the developer machine.
- A lead session orchestrates; every slice is a subagent. Offline slices run in parallel in git worktrees; live slices run one at a time. Agent teams are not used.
- **Automated gates:** required checks (`ci`, `evals`) with branch protection and no bypass, so the agent can only merge what passes; verifier PASS; Claude review Important findings fixed.
- **Decision rules:** golden labels audited blind by a new `label-auditor` subagent (`evals/label_audit.md`); thresholds confirmed only at spec values or stricter after the stability proof; the verifier fails any loosened threshold without an owner decision.
- **Human touchpoints H1 to H5:** sign-ins and the GitHub app consent, one GHCR visibility toggle, every production deploy approval, final test with leak check and rehearsal, and an optional label spot-check. The agent never approves a deployment, so GitHub's approval record stays true.
- **Safety:** `cloud_gate.py` is deny-only (no prompts) and blocks `azd up`, `azd deploy`, `azd down`, `az group delete`, subscription switching, broad role assignments, repo deletion or visibility changes, force pushes and pushes to `main`, deployment approvals, and changes to branch protection or the `demo` reviewers. The same destructive commands are also deny rules in `settings.json`, which block in every permission mode.
- `decisions.md` records who made each decision (agent, rule or owner). The README never claims a human review that did not happen.
- RUNBOOK rewritten: about 15 minutes of setup, then Prompt A (bootstrap and harness), a restart, Prompt B (everything else, stopping at 14:30 on Wednesday at the latest), Prompt C (resume) and Prompt D (fix a defect found in final testing). `plan.md` gains a Status section so any new session can resume.

### Windows

Python hooks registered in exec form with `Bash|PowerShell` matchers; poethepoet tasks (`uv run poe ...`) instead of Make; `.gitattributes` for LF line endings; setup commands in PowerShell.

### Independent consistency check (applied)

- Verifier flags only changes to existing protected files outside the slice's Files list, so slices that create tests, datasets or rubrics are not failed.
- Subagents commit, push and return; the lead runs the verifier, rebases on `main`, opens and merges every PR.
- The owner's account gets Cognitive Services OpenAI User for local runs and live evals (an Owner role has no data actions).
- Container App environment variables set in Bicep; the demo token added as a secret with `secretref`.
- `scripts/setup_env_local.py` writes `.env.local` in one go, because Claude cannot read or edit it.
- `smoke` (local) and `smoke-remote` (live URL) are separate tasks; S3 owns `scripts/smoke.py`.
- Stability runs are local on `s4-evals`; the weak branch moves with `git rebase --onto`; `evals` job named and required from the S4c merge.
- Hook tests run in a fresh session; the REVIEW.md proof moved to V; FR-1's 401, 429 and 503 tests moved to S3; Bicep build step assigned to S1.

### Consistency

Eval volume corrected (now 92 inputs and about 270 calls per run, after the paraphrased injection variants below); edge-case expected behaviour defined; active prompt version committed in `registry.yaml`; J4 reasons aligned across files; slice names aligned (waves W0 to W4, slices S0 to S8, S7 cut); CODEOWNERS described as a signal; workflow names match what `/install-github-app` creates; references to the selection process removed from committed files.

### Walkthrough

Ten minutes at most: an eight-minute script covering the GitHub repo, build, test, Azure Foundry and the live app, with a five-minute cut. (`plan.md`)
