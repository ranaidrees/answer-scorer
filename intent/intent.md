# Intent: AI answer scorer with a trust harness

- **Author:** Rana Naveed Idrees
- **Status:** draft (owner accepts by merging this file)
- **Source:** idea (portfolio reference implementation)
- **Date:** 2026-10-12 (revised after independent review; see `CHANGELOG.md`)
- **Stage:** 1 of 6 (Plan). Next artifact: `intent/spec.md`

## Problem

AI that scores what candidates say is only useful in hiring if people can trust it. It has to be consistent, fair, grounded in the candidate's own words, resistant to manipulation, observable in production and compliant. Recruitment AI is listed as high-risk under the EU AI Act (Annex III, point 4(a)), with the high-risk obligations applying from 2 December 2027 after the Digital Omnibus on AI. The bar is evidence, not a good demo.

Most AI demos show the model producing a score. Very few show the engineering that makes that score safe to ship. That engineering is what a lead AI engineer owns.

I want a small, real, working system that shows how I build and govern AI output for high-stakes decisions, and that was itself delivered with an AI-native SDLC. It is a public reference I can walk technical leaders and clients through in under ten minutes.

## Proposed outcome

A deployed service on Microsoft Foundry and Azure that:

1. Scores a written interview answer against a competency rubric (1 to 5), with a short rationale and verbatim evidence quotes from the answer.
2. Wraps scoring in a trust harness. **Input guards:** identity-blind input, sanitising, redaction, an injection screen and Azure's guardrail. **Output guards:** strict structured output, repeated scoring with a consistency rule, a deterministic grounding check on every quote, and a rationale screen for protected attributes. When any control trips, the answer goes to human review.
3. Has **offline evals** (agreement with labelled answers, fairness counterfactuals against a noise floor, injection cases with paraphrased variants, edge cases) that run as a CI quality gate and nightly. The gate blocks a deliberately weakened prompt and is proven stable: the accepted prompt passes three full runs in a row, and the weak prompt fails three in a row. A one-page eval card states what the results do and do not prove.
4. Has **online evals** and observability: reference-free checks on every live request, traces in Application Insights (connected to the Foundry project), SLOs, alerts, and one dashboard covering review rate by reason, latency, cost per score and eval results.
5. Has a **verifiable supply chain:** actions pinned to SHAs, CodeQL, and signed build provenance checked before every deploy.
6. Was built autonomously by Claude Code through the artifact chain `intent.md` > `spec.md` > `plan.md` > PR > production, with `CLAUDE.md`, `REVIEW.md`, hooks, a verifier subagent, an independent label auditor and parallel work in isolated worktrees. The agent merges only what the required checks pass; the human sits where the risk is: I approve every production deploy, any loosening of a quality threshold, and the final acceptance. The public repository is evidence of how I lead AI-native delivery.

## Who it is for

- **Primary:** technical leaders judging AI delivery capability (hiring panels, clients). They want concise, concrete evidence and results.
- **Secondary:** engineers looking for a worked example of governed AI output.

## Why this shape

Each capability area a lead AI engineer is accountable for maps onto a visible feature:

| Capability area | Where the demo proves it |
|---|---|
| Delivery platform and engineering practice | AI-native SDLC harness: artifact chain, hooks, verifier, CI gates, AI PR review, human gates |
| Architecture | Keyless Foundry and Container Apps design, documented decisions, SLOs |
| Quality, security and governance | Input and output guards, Azure guardrail bound as code, signed build provenance, EU AI Act and UK GDPR mapping |
| Evaluation and continuous improvement | Eval suite, defect vs stylistic variance rule, gate stability proof, failed cases feed the eval set, nightly drift run |
| Team standards and leadership | `REVIEW.md` and `CLAUDE.md` as team standards, human oversight design, a walkthrough for non-specialists |

## Constraints

- Time-boxed: deployed, tested and rehearsed by **Wednesday 14 October 2026, 18:00**. Feature freeze then. Features stop at 14:30 that day.
- Simple: one service, one model deployment, one-page UI. No agent framework, no RAG, no database.
- Microsoft Foundry for model access; Azure Container Apps for hosting; Application Insights for traces. GitHub Actions is the only route that deploys the application.
- Claude Code does the build autonomously, in auto mode, with full access to this repo and the project's Azure resource group. It never deploys the application itself, never approves a deployment, and never runs destructive commands outside the project (deny rules block them).
- Development machine: Windows, no Docker, no Make. Container images are built only on GitHub Actions runners. Tasks run through `uv run poe <task>`.
- Personal Azure subscription. UK South. Scale to zero. Tear down when no longer needed. Keep spend minimal.
- **Public repository.** No secrets, keys, subscription details or personal data in git or in workflow logs. No confidential material from any employer, client or selection process: no company names, role details or third-party documents. Personal notes stay in a git-ignored `private/` folder.
- Synthetic data only. No real candidate data. Not for use in real hiring decisions (stated in the README).
- Generic competencies (for example Teamwork, Problem Solving). No proprietary frameworks, product names or branding.
- The scorer never receives name, gender, age or other protected attributes as inputs.
- Preview Azure features are allowed only if isolated behind one module and listed in `intent/decisions.md`.
- Writing style for all artifacts: plain British English, no em dashes.

## Out of scope

Voice or video, languages other than English, RAG, multi-tenancy, user accounts, a real rater calibration study, formal compliance sign-off, and my AgentOps factory.

Moved to Later after review, to protect the deadline: the Maintain loop (breached band writes a new intent), Prompt Shields, the Foundry evaluation view, custom deployment events and change-failure tracking, automatic rollback, and council subagents.

## How we will know it worked

- The live URL scores an answer with p95 latency within the SLO set in the spec.
- A PR containing the deliberately weakened prompt fails the eval gate with a clear reason; the main prompt passes. Both results repeat three times in a row.
- A live injection attempt is flagged, treated as data and routed to a human.
- The dashboard shows real data from test traffic and eval runs.
- Git history shows intent, spec, plan, PRs with AI review findings and verifier verdicts, a decisions log that says who or what made each decision, and my approval before each deploy.
- I can give the walkthrough in eight minutes (ten at most), with a five-minute cut and screenshots as a fallback.

## Resolved questions

The original open questions (model and region, Foundry evaluation view, Maintain loop, URL protection, Claude in CI) are answered in `intent/spec.md` section 13 and recorded in `intent/decisions.md`.
