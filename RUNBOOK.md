# Runbook: building the answer scorer with Claude Code

How Claude Code takes `intent/intent.md`, `intent/spec.md` and `intent/plan.md` through Build, Test and Deploy autonomously, using Anthropic's AI-native SDLC playbook. Commit this file too: the playbook treats the prompts that produced each artifact as part of the audit trail.

## 1. How this build runs

Claude Code builds, provisions, tests, merges and documents everything, with full access to this repo, your GitHub account and the project's Azure resource group. You do the one-off sign-ins, approve each production deploy, then test, rehearse and accept.

| Who | Does what |
|---|---|
| **Claude Code** (lead session on your Windows machine) | Creates the repo, writes and tests all code, provisions Azure, sets up GitHub, runs evals, merges PRs that pass the required checks, writes the demo pack, verifies the whole thing |
| **Subagents** (inside the lead session) | One per slice. Offline slices run in parallel in their own git worktrees; live slices run one at a time |
| **GitHub Actions** | CI, the eval gate, AI PR review and every application deploy |
| **You** | H1 to H5 in `intent/plan.md`: sign-ins and the GitHub app consent, one GHCR visibility toggle, deploy approvals, final test and rehearsal |
| **Claude chat** | After the freeze: learning the build, talking points and mock questions (notes stay in `private/`) |

**Permission mode: auto.** In auto mode a classifier reviews each action instead of you, so the build runs hands-off. It may occasionally ask about something unusual: approve it if it makes sense. Deny rules and the `cloud_gate.py` hook block destructive commands in every mode. Do not use `--dangerously-skip-permissions` on your own PC: Anthropic's docs reserve it for isolated containers or VMs, and your `az login` can change everything in your subscription.

**Why the deploy approval stays with you.** The demo's claim is "nothing reaches production without a human", and GitHub records you as the approver. If the agent pressed approve under your account, that record would be false, and it is exactly what a delivery leader may probe. It costs you a few seconds per deploy.

**Usage.** Parallel subagents multiply token use. A Max plan is much safer than Pro this week. At most three agents work at once.

**No Docker, no Make.** Local runs use `uv run poe <task>`. The image is built only on GitHub's runners.

## 2. Setup (you, about 15 minutes)

1. Install the tools in PowerShell (or use the official installers):
   ```powershell
   winget install --id Git.Git -e                # Git for Windows: gives Claude Code its Bash tool
   winget install --id OpenJS.NodeJS.LTS -e      # Node.js for the Azure MCP server (npx)
   winget install --id Microsoft.AzureCLI -e
   winget install --id Microsoft.Azd -e
   winget install --id GitHub.cli -e
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   uv python install 3.12
   irm https://claude.ai/install.ps1 | iex       # Claude Code
   ```
   Open a new terminal and check each one with `--version`.
2. Sign in (each opens a browser): `gh auth login`, `az login` (choose the subscription for this demo; the agent is not allowed to switch it), `azd auth login`, then `claude` (your Max or Pro account).
3. Create a folder `answer-scorer` and unzip the pack into it, so it holds `intent\`, `RUNBOOK.md` and `CHANGELOG.md`. Create `private\blocklist.txt` with one name per line that must never appear in the repo. The agent never reads `private\`.
4. Open Windows Terminal in that folder and run `claude`. Accept the folder trust prompt. Check the status bar says auto mode; if not, press Shift+Tab until it does, or start with `claude --permission-mode auto`.
5. Paste Prompt A from section 4.

## 3. Public repo rules (Claude follows these from CLAUDE.md)

- Everything in git, PR comments and Actions logs is public.
- No secrets, keys, connection strings, subscription or tenant IDs in files. Use GitHub secrets and variables.
- Workflows never print tokens, the app URL with a token, environment values or raw telemetry rows.
- No company names, role details or third-party documents.
- Only you trigger `@claude`: the action only answers users with write access by default. Never set `allowed_non_write_users`.
- If a secret ever leaks: rotate it first, then clean history.

## 4. Prompts

### Prompt A: bootstrap and harness (session 1, Monday evening)

```
We are building the project described in intent/intent.md, intent/spec.md and
intent/plan.md, using Anthropic's AI-native SDLC playbook
(https://claude.com/blog/the-ai-native-sdlc-playbook): each stage commits one artifact
the next stage reads, and git history is the audit trail.

You have full access to this folder, my GitHub account (gh) and my Azure subscription
(az, azd). Work autonomously. Stop only for my touchpoints H1 to H5 in intent/plan.md.

Read first, in full: intent/intent.md, intent/spec.md, intent/plan.md, RUNBOOK.md.

Environment: Windows with Git Bash and PowerShell, no Docker, no Make. Tasks run with
uv run poe. Hooks are Python scripts registered in exec form.

Rules for this and every later session (put them in CLAUDE.md):
- Follow intent, spec and plan. Where they do not settle something, choose the simplest
  option that meets the spec, record it in intent/decisions.md with "agent" as who, and
  carry on. Ask me only if a choice would change scope, cost real money or touch
  anything outside this repo and the project's resource group.
- Never deploy the application yourself and never approve or reject a deployment.
  GitHub Actions is the only deploy path and I approve every deploy.
- Never switch the Azure subscription, delete a resource group or repo, or grant broad
  roles. Never try to get round a hook or a deny rule.
- Fix the code, not the test. Never weaken a threshold or edit a dataset to pass.
  Loosening any threshold needs my decision.
- For Azure and SDK details, check current docs with the Microsoft Learn MCP and cite URLs.
- This is a PUBLIC repo. Nothing secret or confidential in files, commits, PR comments or
  workflow logs: no keys, tokens, connection strings, subscription or tenant IDs, company
  names or role details. Never read private/ or any .env file.
- Every decision goes in intent/decisions.md with date, decision, reason and who
  (agent, rule or owner). Never record a human review that did not happen.
- Before opening any PR, run a security review of the diff (/security-review where
  available) and summarise it in the PR description.
- Workflows: pin every action to a full commit SHA with the version in a comment, use
  current major versions, least-privilege permissions per job, cache-mode read on PR
  jobs. claude-code-action must be 1.0.74 or later with show_full_output off.
- Plain British English, no em dashes.

Step 1. Bootstrap. Write .gitignore (.env*, .azure/, private/, .claude/worktrees/,
.claude/fix-mode, __pycache__/, .venv/) and .gitattributes (* text=auto eol=lf) first.
git init -b main, stage everything, confirm nothing from private/ and no .env file is
staged, commit "intent: draft intent, spec, plan and runbook", then
gh repo create answer-scorer --public --source . --push. With gh api: turn on secret
scanning push protection and Dependabot alerts, turn on CodeQL default setup for Python
and GitHub Actions, and require approval for fork PR workflows from outside
contributors.

Step 2. With read-only az commands, confirm quota for gpt-5.4-mini 2026-03-17 Global
Standard in UK South. If there is none, apply the fallback in spec section 14.

Step 3. Wave 0, first part: refine the S0 and V sections of plan.md, commit them on
branch plan/wave-0, open the PR, and merge it once the checks that exist pass. Then build
S0 on branch s0-harness exactly as spec section 10 and plan S0 describe:
 a. pyproject.toml (Python 3.12; dev dependencies ruff, pytest, poethepoet, pyyaml) with
    poe tasks check (ruff check, ruff format --check, pytest including tests/hooks),
    test, eval, run, smoke and smoke-remote; all but check and test print "not yet
    implemented" for now. MIT LICENSE. README stub: synthetic data only, a reference
    implementation, not for use in real hiring decisions.
 b. CLAUDE.md (under one page) and REVIEW.md.
 c. Hooks cloud_gate.py, protect_evidence.py and format_py.py. Read
    https://code.claude.com/docs/en/hooks first and use the current input and output
    format. Register them in exec form through uv, with matchers covering both Bash and
    PowerShell. Gate hooks catch every exception and exit 2 with a reason on stderr.
    tests/hooks/ pipes JSON payloads into each script and asserts allow and deny for
    every rule.
 d. .claude/settings.json exactly as spec section 10 lists.
 e. .claude/agents/verifier.md, .claude/agents/label-auditor.md and
    .claude/skills/fair-scoring-policy/SKILL.md.
 f. .mcp.json with the Microsoft Learn MCP (https://learn.microsoft.com/api/mcp) and the
    Azure MCP Server in read-only mode (npx -y @azure/mcp@latest server start
    --read-only). If the npx server does not start on Windows, check the Claude Code MCP
    docs for Windows guidance and record what worked.
 g. .github/workflows/ci.yml with a job named ci (ruff, pytest, hook tests, gitleaks),
    .github/dependabot.yml (github-actions ecosystem), .github/CODEOWNERS, and
    intent/decisions.md seeded with C1 to C21 from spec section 13.
 h. Commit and push s0-harness. Then stop and tell me to restart Claude Code and paste
    Prompt B, because hooks, settings and agents load when a session starts.
```

### Prompt B: the rest of the build (session 2, after the restart)

```
Continue the build in intent/plan.md. Read CLAUDE.md, everything in intent/, RUNBOOK.md,
and the Status section of plan.md first, and pick up from where Status says. Work
autonomously under the rules in CLAUDE.md. Stop only for my touchpoints H1 to H5.

You are the lead. Orchestrate; do not do slice work yourself. Follow "How every slice
runs" in plan.md for every slice:
- Brief each subagent with its slice section of plan.md plus the spec sections it names.
- Offline slices (S2, S4a, S4b, S5a): background subagents, in parallel, each with
  isolation: worktree. Fetch and pull main before starting them.
- Live slices (V, S1, S3, S4c, S5b, S6, S8): one at a time, in the foreground, in the
  main checkout.
- At most three agents at once.
- For each branch: verifier PASS, rebase on main, security review of the diff, open the
  PR, wait for the required checks and the Claude review, fix Important findings, then
  gh pr merge --squash --delete-branch. The ruleset is the gate; never bypass it.
- Update Status in plan.md after every merge.

Order:
1. Finish Wave 0. Prove S0 in this fresh session (plan S0 proof), open its PR and merge
   it. Then tell me to run /install-github-app (H1), with the review workflow and a
   subscription token, and wait. In the PR it creates, pin claude-code-action to a SHA
   at 1.0.74 or later, keep show_full_output off and point the review prompt at
   REVIEW.md; merge it. Then create a repository ruleset on main (PR required, required
   check ci, block force pushes and deletion, empty bypass list) and the GitHub
   environment demo with me as required reviewer. Show me both with read-only gh api
   calls. Then V.
2. Waves 1 to 4 as plan.md describes. Start each wave by refining its slice sections on
   a plan/wave-N branch, opening the PR and merging it after the Claude review.
3. Merge S3 before S5a: the S5a merge queues the first deploy.
4. When the first image is pushed, tell me to make the ghcr.io package public (H2) and
   wait. Whenever a deployment waits for approval, tell me (H3) and wait. Never approve
   or reject a deployment yourself.
5. Stop at the end of W4, or at Wednesday 14:30 at the latest (check the clock with
   date). Give me: the final verification report, the live URL, anything not green, and
   the final-test checklist from RUNBOOK.md section 5.
```

### Prompt C: resume

Use this if the session ends, the machine restarts or the context gets muddled. Start a new session in the repo folder first.

```
Resume the build. Read CLAUDE.md, everything in intent/, RUNBOOK.md and the Status
section of plan.md. Check open PRs (gh pr list), branches and worktrees (git worktree
list) to confirm where things really are, reconcile Status with that, then continue
Prompt B from that point. Do not redo merged slices.
```

### Prompt D: fix a defect found during your final test

```
During final testing I found: <describe what you saw, where, and what you expected>.
Create .claude/fix-mode so tests and datasets are locked. Reproduce it, find the root
cause, fix the code or the prompt, run uv run poe check (and uv run poe eval if
relevant), delete .claude/fix-mode, and take it through the normal PR steps. Give me the
root cause in two sentences. If the fix needs a deploy, tell me when to approve it.
```

### Utility prompts

**Status:** `Summarise Status in plan.md in five lines: merged, in progress, blocked, next, and anything I need to do.`

**Independent check:** `@agent-verifier check the current branch against slice <Sx> in intent/plan.md.`

**Learn from a repeated mistake:** `You made the same kind of mistake twice: <describe it>. Add one line to Known mistakes in CLAUDE.md that would have prevented it. Keep CLAUDE.md under one page.`

## 5. Final test and rehearsal (you, Wednesday 15:00 to 18:00)

1. Live app: run the strong, weak and injection samples. Check the evidence highlighting, the flags, the review reasons, the AI-use disclosure and the "Report a problem" link. For the injection sample, check what `decisions.md` says Azure's guardrail does with it, so you describe it correctly on the day.
2. Weak-prompt PR: the `evals` check has failed, the comment explains why, and merge is blocked.
3. Deploy run: the provenance check passed before the update, and you are shown as the approver.
4. Dashboard: all four tiles show data.
5. README and eval card: the scoreboard numbers match the latest eval report and `evals/label_audit.md`; read `docs/eval_card.md` end to end.
6. `intent/decisions.md`: every decision says who made it (agent, rule or owner).
7. Leak check: run `git grep -i -f private/blocklist.txt` yourself on `main`. It must print nothing.
8. Optional H5: spot-check ten golden labels in `evals/datasets/golden.jsonl` and ask Claude to record what you checked.
9. Take three screenshots for the fallback: the Foundry model deployment, the J1 trace in Application Insights, and the approved deployment in GitHub. Ask Claude to add them to `docs/screenshots/`.
10. Rehearse the walkthrough in `plan.md` twice with a timer: once at eight minutes, once as the five-minute cut. Record one run as a fallback.
11. Freeze at 18:00: ask Claude to dispatch `warm=true`, approve it, ask Claude to run `uv run poe smoke-remote`, then tag `v1.0-demo` (or ask Claude to).
12. Then bring the repo link to Claude chat to learn how to present and defend it.

## 6. Walkthrough day

At 11:00: `uv run poe smoke-remote`, `scripts/traffic.py --profile normal`, open the tabs in the order in `plan.md`, keep the screenshots and recording ready. No deploys on the day.

## 7. Teardown

When the live demo is no longer needed: disable the nightly run (`gh workflow disable evals.yml`, or remove its schedule in a PR), then run `azd down --purge` yourself (the deny rules stop Claude from running it). The repo stays public as a portfolio piece; add the screenshots and the recording link to the README so it still makes sense without a live URL.
