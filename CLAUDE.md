# CLAUDE.md

AI answer scorer with a trust harness. Public repository. Read `intent/intent.md`, `intent/spec.md` and `intent/plan.md` (its Status section says where the build is) before working.

## Commands

Windows machine: no Docker, no Make. Everything runs through `uv run poe <task>`.

| Task | Healthy output |
|---|---|
| `uv run poe check` | ruff "All checks passed!", "files already formatted", pytest "N passed" |
| `uv run poe test` | pytest "N passed" |
| `uv run poe eval` | a report in `evals/reports/` and "GATE: PASS" |
| `uv run poe run` | the app on http://localhost:8000 |
| `uv run poe smoke` / `smoke-remote` | strong, weak and injection cases pass |

## Rules

- **Artifact chain.** Follow intent, spec and plan. Where they do not settle something, take the simplest option that meets the spec and record it in `intent/decisions.md` (date, decision, reason, who: agent, rule or owner). Never record a human review that did not happen.
- **Pull requests only.** Never push to `main`, never force push. One branch per slice; departures from the plan go under Deviations in the same PR.
- **Production is the owner's.** Never deploy the application, never approve or reject a deployment. GitHub Actions is the only deploy path. `main.bicep` is never re-provisioned after the first deploy.
- **Stay in the project.** Only this repository and resource group `rg-answer-scorer-demo`. Never switch the subscription, delete a resource group or repo, or grant Owner, Contributor or User Access Administrator. Never work round a hook or a deny rule: record the denial under "Needs owner" in plan Status and move on.
- **Spend.** Total Azure spend stays under 10 GBP. Nothing with a fixed hourly or monthly charge. Keep the running model spend estimate in plan Status.
- **Plain British English, no em dashes.**

## Protected paths

`tests/`, `evals/datasets/`, `evals/thresholds.yaml` and `rubrics/` are evidence. Fix the code, not the test. Never weaken a threshold or edit a dataset to pass; loosening a threshold needs the owner. While `.claude/fix-mode` exists these paths are locked. Prompt tuning looks at `dev` cases only, never `holdout`.

## Public repository

Nothing secret or confidential in files, commits, PR text or workflow logs: no keys, tokens, connection strings, subscription, tenant or client IDs, email addresses, local folder paths, company names or role details. IDs live in GitHub variables and secrets. Never read `private/` or any `.env` file. Workflows never echo environment values, tokens or raw telemetry rows. If a secret leaks: rotate first, then clean history.

## Azure conventions

- Keyless only: `DefaultAzureCredential`; key auth is disabled on the Foundry resource.
- Model calls use the `openai` package against `<endpoint>/openai/v1/` with `get_bearer_token_provider`. Never `azure-ai-inference` (retired 26 August 2026).
- Chat Completions, strict JSON schema, `reasoning_effort: "none"`, `max_completion_tokens` 600, no `temperature` or `top_p`.
- Check current Azure and SDK details on Microsoft Learn (the `microsoft-learn` MCP server) and cite the URL. Inspect Azure through the read-only `azure` MCP server; change it only through CLI commands.

## Observability conventions

No candidate text in logs, traces or events; GenAI content capture stays off. Answers are identified only by a salted hash. Span attribute names on the `score` span are fixed: `scorer.request_id`, `scorer.answer_hash`, `scorer.competency`, `scorer.prompt_version`, `scorer.prompt_sha`, `scorer.model_deployment`, `scorer.model_version`, `scorer.score`, `scorer.runs`, `scorer.spread`, `scorer.needs_human_review`, `scorer.review_reasons`, `scorer.injection_detected`, `scorer.hidden_text_removed`, `scorer.platform_guardrail`, `scorer.rationale_protected_term`, `scorer.ungrounded_quotes`, `scorer.input_chars`, `scorer.tokens_in`, `scorer.tokens_out`, `scorer.cost_estimate_gbp`.

## Workflows

Pin every action to a full commit SHA with the version in a comment. Current major versions only. Least-privilege `permissions:` per job. `cache-mode: read` on PR jobs. `claude-code-action` at 1.0.74 or later with `show_full_output` off. No `pull_request_target`.

## Verification

Before opening any PR:
1. `uv run poe check` is green. Read the output; do not assume.
2. Run a security review of the diff (`/security-review` where available, otherwise the same review as a subagent prompt) and summarise it in the PR description.
3. The `verifier` subagent returns PASS on the branch.
4. Report anything that failed or was skipped as it is.

## Known mistakes

- Git Bash rewrites arguments that look like paths (`origin/branch:path`, `/subscriptions/...`). Set `MSYS_NO_PATHCONV=1` for `git show`, `gh api` and `az` commands that take such arguments.
- Hooks, settings, agents and MCP servers load when a session starts. A change to them is proven by the hook tests, and live only in a new session.
