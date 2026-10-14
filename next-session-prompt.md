# Prompt for the next session: the AI-native SDLC evidence dashboard

Start Claude Code in this folder with the same settings as Phase 3:

```
claude --permission-mode auto --settings private\claude-overnight-settings.json
```

Then paste everything in the block below.

```text
You are the lead for one more piece of work on this repository, with the owner present. Read these in full before doing anything else: CLAUDE.md, intent/intent.md, intent/spec.md, intent/plan.md (all of Status, Deviations and the Walkthrough), intent/decisions.md (at least C1 to C21 and P3-1 onwards), RUNBOOK.md, docs/llmops.md, docs/slo.md, dashboards/queries.kql, infra/workbook.json, infra/observability.bicep and tests/unit/test_observability_files.py. Work under the rules in CLAUDE.md in full: pull requests only, verifier PASS and a security review before each pull request, protected paths, public-repository hygiene, plain British English with no long dashes, spend under 10 GBP in total, nothing with a fixed charge, the owner approves every deploy.

## Where things stand (14 October 2026, about 14:40)

- The application is deployed and live (one warm replica). Both manual deploy routes are proven with the owner's approval. Hooks are proven live. CodeQL is on. The test alert reached the owner's email. Model spend is about 7.1 GBP of 10.
- Merged: the twelve slice pull requests, then #17, #18, #19 and the records pull request that holds this file (decision P3-11). Open by design: #15, the weak-prompt demonstration. #1 and #14 were closed at the owner's request on 14 October.
- #19 added dashboard tiles 5 (live drift by day) and 6 (requests to look at, with trace ids), a links header and docs/llmops.md. They are on main but NOT in the live workbook yet: auto mode denied the lead's `az deployment group create` for infra/observability.bicep twice as a "blind apply", the second time with the owner's go-ahead. The owner runs that deployment; never try a third time or another route. Check first whether it has been applied: the workbook's `timeModified` and the deployment list in the resource group (read-only).
- Records still to write, in one small pull request: whether the owner has applied the observability deployment (add to decision P3-11's story in a new decision), and the deferred wording notes listed in the #19 pull request description ("no keys anywhere" in README, docs/architecture.md and walkthrough step 3 needs "for the model and Azure access", since Application Insights takes a connection string; CI review coverage lists stop at #16; tile 6's no-data message; walkthrough fallback still says four tiles).
- The owner still has: the three portal screenshots (05, 06, 10), judging the three actions taken after denials (plan Status, "Denied actions"), and after the interview switching the nightly eval off and setting minimum replicas back to 0.
- The plan's features stop (14:30) has passed. This work is the owner's explicit request; agree a time box with the owner before building, and keep the freeze (18:00) in view.

## The goal

One dashboard in Azure that tells the whole story of this project as evidence: that the delivery was AI-native, following Anthropic's AI-native SDLC playbook (each stage commits an artifact the next stage reads; gates decide; the human sits where the risk is), and that its quality is top notch. It should run in stage order:

1. Plan and design: the artifact chain (intent, spec, plan), design decisions and who made them, the independent rubric check, the blind label audit.
2. Build: pull requests per slice, lead time from first commit to merge, size, agent authorship, parallel worktrees, verifier verdicts and catches, in-session and CI review findings found and fixed, hooks and deny rules that held.
3. Test: unit and hook tests (count and trend), build time and test time per `ci` run with a graph, `ci` pass rate, the eval gate (kappa and agreement per run, the stability proof three passes and three failures, the weak prompt blocked), injection and fairness results, label audit agreement.
4. Supply chain and security: actions pinned, CodeQL, gitleaks, secret scanning, signed provenance verified before every deploy, Dependabot.
5. Deploy: deploy runs, every one approved by the owner, provenance verified, smoke results, lead time from merge to production, the rollback route proven, change failure rate; DORA-style figures where the data supports them.
6. Operate, live: the six existing tiles (latency and availability against SLOs, review rate by reason, cost per score, eval runs, drift, requests to look at), alerts, and spend against the budget.
7. AI-nativeness, as a summary strip: share of commits written by the agent, decisions by agent, rule and owner, human touchpoints and the time they took, gates passed, issues caught by gates before merge, time from intent to production.

Every figure must be one that a reader can trace to GitHub, the repository or Azure. Say what each one does not prove (reliability is not validity; the reviews are by AI agents, not people; the data is synthetic).

## How to work

Phase A, research and brainstorm (no code). Use the Microsoft Learn MCP and cite URLs.
- How a workbook can show GitHub data. Known so far: workbooks have a Custom Endpoint data source (needs CORS, the host must be marked trusted, JSONPath transforms results), and a JSON data source for static content (https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-data-sources#custom-endpoint, https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-jsonpath, https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-manage). The GitHub REST API allows CORS and unauthenticated reads of a public repository (rate limited per caller address). Headers and URLs in a workbook are visible to every viewer, so no token may go in one.
- Compare at least three ways to get the data in, with effort, freshness, privacy and risk: (a) Custom Endpoint calls to the public GitHub API from the workbook; (b) a GitHub Actions job that sends SDLC events to Application Insights (the telemetry allow-list in src/scorer/telemetry.py admits only `eval_run` today, and a change under src/ runs the paid eval gate); (c) a snapshot of the figures, generated by a script from the GitHub API and the repository, embedded as a JSON data source in the workbook and refreshed by a pull request. Recommend one, or a mix (for example, live GitHub where it is unauthenticated and cheap, snapshot for figures that need the repository or authenticated endpoints, Application Insights for post-deploy and live).
- Work out which metrics each GitHub endpoint can give without a token (workflow runs and jobs with timings, pull requests, reviews and comments, deployments and environment approvals, check runs, releases) and which need one (for example code scanning alerts). Test the calls read-only with `gh api` and plain `curl` first.
- Use the dataviz and artifact-design skills to design the layout: a KPI strip first, then one section per stage, one hero figure per section, honest captions. Show the owner a mock-up (inline visual) and the metric list before building.
- Write the design as a short plan section (a new slice, for example S9) and decisions; get the owner's agreement on the approach and the time box.

Phase B, build, as one slice on its own branch:
- A new workbook (keep the operational dashboard as it is, or add the SDLC view as a second workbook in infra/observability.bicep), queries kept in dashboards/ like the existing ones, and tests in the style of tests/unit/test_observability_files.py (copies equal, no resource IDs, no secrets, links only to this repository). Any snapshot script goes in scripts/ with tests, and never prints a token.
- Run every query read-only against real data before committing. Keep `poe check` green.
- Verifier PASS, security review, pull request, checks, merge. Then the owner applies the deployment (give the exact command with placeholders; auto mode will deny it to you). Then confirm in the portal with the owner signed in to the built-in browser, and take the screenshot.
- Update README (link the new dashboard), docs/llmops.md and the walkthrough (where it fits in the eight minutes; it is the highlight of the interview demo), plan Status and decisions.

Constraints to keep in mind:
- Public repository: no subscription, tenant or resource IDs, no email addresses, no app host name, no tokens, no local paths in any file, workbook or pull request text. The workbook file must hold no resource ID (bind the resource in Bicep at deploy time, as the existing workbook does).
- No new Azure resource with a fixed charge; no new paid model runs unless the owner agrees, and keep the spend estimate in plan Status.
- Rules for denials: retry at most once, never work round one, record it under "Needs owner".
- Never claim a human review that did not happen, and never present a figure you cannot trace.

Start by checking the clock and the state above against reality (gh pr list, the deployment list, the workbook's timeModified), then give the owner a one-screen summary of Phase A's plan and the time box you propose, and begin.
```
