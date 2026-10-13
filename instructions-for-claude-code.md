# Instructions for Claude Code

These instructions run the whole build of this project in three phases. The owner tells you which phase to follow. Read this file in full each time, then follow only the phase you were given.

- **Phase 1: setup.** The owner is present. About 20 minutes.
- **Phase 2: unattended build.** The owner is not to be interrupted. Fully autonomous.
- **Phase 3: finish.** The owner is present for deploy approvals.

Phases 1 and 3 run in the daytime. Phase 2 starts on Tuesday afternoon and runs on through the night until it is finished. It is unattended: the owner may be nearby, but the build must run from start to finish without asking them anything.

The project itself is described in `intent/intent.md`, `intent/spec.md`, `intent/plan.md`, `RUNBOOK.md` and `CHANGELOG.md`. Where this file and `RUNBOOK.md` section 4 differ, this file wins.

**Rules for every phase:**
- Never write the local folder path, the owner's employer, any prospective employer, or any personal or employment details into a file, commit, pull request or issue. The repository is public.
- Never read `private/` or any `.env` file.
- Plain British English, no em dashes.
- Total Azure spend for this project must stay under 10 GBP. A pay-as-you-go subscription has no hard cap, so the limit is kept by design: follow "Spend limit" in Phase 2 in every phase.

---

## Phase 1: setup (the owner is present)

Work through these steps in order. When a step needs the owner, stop, tell them exactly what to do, and wait for them to reply "done". Do not move on until each step is confirmed.

1. **Folder.** Confirm the current folder is named `answer-scorer` and contains `intent/spec.md`. If it does not, stop and tell the owner.

2. **Tools.** Check that `git`, `gh`, `az`, `azd`, `uv`, `node` and Git Bash are available (`--version` for each). Run `uv python install 3.12`. If anything is missing, give the owner the matching command to run in a separate PowerShell window, then re-check once they reply. The commands are:
   - `winget install --id Git.Git -e`
   - `winget install --id OpenJS.NodeJS.LTS -e`
   - `winget install --id Microsoft.AzureCLI -e`
   - `winget install --id Microsoft.Azd -e`
   - `winget install --id GitHub.cli -e`
   - `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

3. **Sign-ins.** Check each one without prompting:
   - `gh auth status`, and confirm its token scopes include `workflow`.
   - `az account show`.
   - `azd auth login --check-status`.

   These logins are interactive and must not be run from your shell. For anything missing, ask the owner to run the matching command in a separate PowerShell window, one line at a time, then re-check:
   - `gh auth login --web`
   - `gh auth refresh -s workflow`
   - `az login`
   - `azd auth login`

4. **Subscription.** Show the owner the current Azure subscription name from `az account show` and ask them to confirm it is the one for this demo. If it is not, ask them to run `az account set --subscription <id>` themselves, then re-check.

5. **Settings so nothing prompts during the unattended build.** Run:
   - `gh auth setup-git`
   - `az config set extension.use_dynamic_install=yes_without_prompt`
   - `az extension add --name containerapp --upgrade` and `az extension add --name application-insights --upgrade`
   - `azd config set defaults.location uksouth` and `azd config set defaults.subscription <the confirmed subscription id>`
   - `az provider register --namespace <ns>` for each of `Microsoft.CognitiveServices`, `Microsoft.App`, `Microsoft.OperationalInsights`, `Microsoft.Insights`, `Microsoft.ManagedIdentity` and `Microsoft.Consumption`. Do not wait for registration to finish.

6. **Project files.** Do these in order; `.gitignore` comes first because the repository is public.
   1. Write `.gitignore` with these lines: `.env*`, `.azure/`, `private/`, `.claude/worktrees/`, `.claude/fix-mode`, `__pycache__/`, `.venv/`.
   2. Write `.gitattributes` containing `* text=auto eol=lf`.
   3. Create a `private/` folder.
   4. Copy the newest `claude-overnight-settings*.json` from the owner's Downloads folder to `private/claude-overnight-settings.json`. The file keeps this name even though the build now runs in the day. If it is not there, write the file instead: the deny rules from spec section 10 for both the Bash and PowerShell tools, plus auto mode `environment` and `hard_deny` entries (each keeping `$defaults`) that name only this repository, its `ghcr.io` image and `rg-answer-scorer-demo`. Tell the owner what it contains.
   5. In a copied file, replace `YOUR_GITHUB_USER` with the output of `gh api user --jq .login`. Either way, check the file is valid JSON with a command that does not print it.
   6. Create an empty `private/blocklist.txt`. Ask the owner to run `notepad private\blocklist.txt`, add the company name and anything else that must never appear in the repo, one per line, then save and reply "done". Never read that file.

7. **Repository.** Set up git and create the public repo:
   1. `git init -b main`.
   2. Set a GitHub no-reply identity for this repository only: `git config user.name <login>` and `git config user.email <id>+<login>@users.noreply.github.com`, where `<id>` comes from `gh api user --jq .id`.
   3. `git add .`, then check the staged list (`git diff --cached --name-only`). Nothing under `private/` and no `.env` file may be staged.
   4. Commit with the message "intent: draft intent, spec, plan and runbook".
   5. `gh repo create answer-scorer --public --source . --push`.

8. **Claude GitHub app.** Ask the owner to type `/install-github-app` in this session. They should choose this repo, include the review workflow, and choose the subscription token. Ask them not to merge the PR it creates. When they reply "done", confirm that PR exists with `gh pr list`.

9. **Keep the PC awake.** Run `powercfg /change standby-timeout-ac 0` and `powercfg /change hibernate-timeout-ac 0`.

10. **Hand over.** Tell the owner, word for word:

    > Setup is complete. Before you start the unattended build:
    > 1. Pause Windows Update for a week, keep the PC plugged in and, if it is a laptop, keep the lid open. Do not restart, sleep or sign out of the PC while the build runs, and do not switch the `gh` account or the Azure subscription in any terminal.
    > 2. Type /exit, then start Claude Code again from this folder with:
    >    claude --permission-mode auto --settings private\claude-overnight-settings.json
    > 3. Check that the status bar shows auto mode, then paste the kick-off prompt and press Enter. If the terminal warns that the text has several lines, choose to paste anyway.
    > 4. Watch for 10 minutes, then leave it running. You can carry on with other work on this PC, but do not type in this session until it gives its build report.

    The kick-off prompt:

    ```text
    You are the lead for an unattended build. I will not be at the keyboard, so do not ask me anything and do not stop until the work is done.

    Read these in full before doing anything else: instructions-for-claude-code.md, intent/intent.md, intent/spec.md, intent/plan.md, RUNBOOK.md and CHANGELOG.md. Then follow Phase 2 of instructions-for-claude-code.md, and only Phase 2. Where the files differ, instructions-for-claude-code.md wins, then plan.md, then RUNBOOK.md.

    What I delegate to you, for the repository ranaidrees/answer-scorer and the Azure resource group rg-answer-scorer-demo only:
    - pushing branches, opening pull requests and merging each one once its required checks pass
    - the GitHub settings, secrets, variables, ruleset and demo environment that Phase 2 lists
    - creating the Azure resources, identities and role assignments in spec section 9

    What you must never do:
    - approve or reject a deployment, deploy the application yourself, or dispatch deploy.yml
    - touch any other repository or resource group, or change the Azure subscription
    - let projected Azure spend pass 10 GBP (follow "Spend limit")
    - push to main, weaken a test, threshold or dataset to make something pass, or work round a denied action
    - write secrets, IDs, the local folder path or any personal or employer details into the repo; it is public
    - read private/ or any .env file

    Where things stand: Phase 1 is finished. The repo exists with the intent commits on main. Pull request 1 holds the two Claude workflows and is waiting for you to update and merge. gh, az and azd are signed in, the resource providers are registered, the model quota is confirmed and rg-answer-scorer-demo does not exist yet.

    How to work:
    - Start by checking the clock with date and reading the wave targets in plan.md. If you are more than two hours behind a target, apply "Cut if behind".
    - Hooks, project settings and MCP servers that S0 creates will not be loaded in this session. Prove hooks with their unit tests, and use web fetch on learn.microsoft.com for Azure documentation.
    - If an action is denied, retry it once at most, record it under "Needs owner" in the Status section of plan.md and move on to other work.
    - Verify before you claim: run the checks, read the output, and report anything that failed or was skipped as it is.
    - Do not end your turn while work remains. After any context compaction, re-read CLAUDE.md, the Status section of plan.md and the Phase 2 rules.

    Stop when everything you can do without me is done, or at 09:00 on Wednesday 14 October at the latest, or if you hit a usage limit. Whichever comes first, update Status and finish with the BUILD REPORT that Phase 2 section F describes.
    ```

---

## Phase 2: unattended build (the owner is not to be interrupted)

This is an unattended run in the daytime. The owner may be nearby but must not be interrupted. Work autonomously until everything you can do without the owner is done.

**Already in place:**
- Tools are installed and signed in: `gh` with the `workflow` scope, `az`, `azd` and Claude.
- Azure resource providers are registered, `az` extensions are installed with prompts off, and `azd` defaults are UK South and the confirmed subscription.
- The public repo in this folder's origin remote has the intent commit on `main`.
- `/install-github-app` has opened a PR adding `claude.yml` and `claude-code-review.yml`.
- This session runs in auto mode with `private/claude-overnight-settings.json`.

**Names to use:** azd environment `answer-scorer-demo` and resource group `rg-answer-scorer-demo`. Always run `azd` and `az` non-interactively (for example `azd env new answer-scorer-demo --subscription <id> --location uksouth`, with `--no-prompt` where supported).

**Spend limit: 10 GBP in total for this project.** A budget alert only warns, and Azure cost data can lag by a day, so keep spend down by design:
- Set the resource group budget parameter to 10 in the billing currency (less if 10 would be worth more than 10 GBP), with alerts at 50%, 80% and 100%.
- Choose the free tier or free allowance wherever one exists and meets the spec; otherwise use pay-per-use. Create nothing with a fixed hourly or monthly charge: no Azure Container Registry, no dedicated workload profile, no provisioned throughput. The Container App stays at min replicas 0, except for the `warm=true` dispatch in Phase 3, which the owner approves and which goes back to 0 after the walkthrough.
- Set a daily ingestion cap of 0.1 GB on the Log Analytics workspace.
- Budget and alert emails go to the Azure sign-in address (`az account show --query user.name`), passed as a deployment parameter and never written to a tracked file.
- Model calls are the only cost that grows with use. Prices on 13 October 2026, from the Azure Retail Prices API (`https://prices.azure.com/api/retail/prices`, currency GBP, region `uksouth`, product "Azure OpenAI GPT5"), per 1M tokens: input 0.5661, cached input 0.0566, output 3.3964. The Azure OpenAI pricing page does not show prices to a fetch, so re-check with the same API when filling `config/prices.yaml` (spec C7) and record the URL and date.
- At those prices one full eval run (about 270 calls) is estimated at 0.30 to 0.50 GBP, and the whole build at 4 to 8 GBP. Keep a running estimate of model spend in the Status section of `plan.md`, from the token counts of every eval, stability and traffic run.
- Do not waste runs: tune the prompt on `dev` cases only (spec section 7), never repeat a full run that has already passed, and keep traffic runs to the size the dashboard needs.
- Before each full eval run, project the total: spend so far, plus this run, plus 1 GBP held back for Phase 3 and the nightly runs. If the projection stays under 10 GBP, carry on. If it would pass 10 GBP, do not start the run: going over needs the owner's approval. In Phase 2, record the request under "Needs owner" with the figures and carry on with work that needs no model calls. In Phases 1 and 3, ask the owner directly.
- If the running estimate is above 7 GBP once the stability proof is done, leave the nightly schedule out of `evals.yml` (the first item in the plan's "Cut if behind" list), keep the PR and manual triggers, and record it. Either way, record the estimated cost of one nightly run in Status.

**Rules for unattended work.** Put the general rules from RUNBOOK Prompt A into `CLAUDE.md`, and include rules 1 to 5 below in every subagent brief.

1. **Never ask the owner anything, and never use AskUserQuestion.** When intent, spec and plan do not settle a choice, take the simplest option that meets the spec, record it in `intent/decisions.md` with "agent" as who, and carry on. Put anything that truly needs the owner under "Needs owner" in the Status section of `plan.md`.
2. **Do not fight a denial.** If a hook, a deny rule or auto mode denies an action, retry it at most once and never look for another way round it. Record it under "Needs owner" with the exact command and the reason, then move on to other work. Repeated denials pause auto mode and would stop the run.
3. **Stay inside this folder.** Use the Read, Grep and Glob tools only inside this folder. Reads outside it raise a permission prompt that would stall the run.
4. **Never touch production or anything outside the project.** Never deploy the application, never approve or reject a deployment, and never dispatch `deploy.yml` in this phase. Never change the Azure subscription, and never touch anything outside `rg-answer-scorer-demo` and this repo.
5. **Keep the public repo clean.** Follow the rules for every phase at the top of this file.
6. **Keep going.** Do not end your turn while work remains. When waiting for CI, poll with `gh pr checks --watch` or `gh run watch`. After any context compaction, re-read `CLAUDE.md`, the Status section of `plan.md` and these rules before continuing.
7. **Never push to `main`.** Every change goes through a pull request, including the Status updates in `plan.md`: carry each Status update on the next slice branch, or open a small `status` pull request when no other branch is open.
8. **Keep to the clock.** Follow the targets and "Keeping to the clock" in the Waves section of `plan.md`. Stop and give the build report by Wednesday 14 October at 09:00 at the latest, whatever the state.

**Order of work.** `plan.md` has the detail for every slice; follow "How every slice runs" for each one.

- **A. Wave 0.**
  1. With `gh api`, turn on secret scanning push protection, Dependabot alerts, CodeQL default setup (Python and GitHub Actions) and approval for fork PR workflows.
  2. Model quota is the agent's decision. It was checked in Phase 1 on 13 October 2026: gpt-5.4-mini 2026-03-17 Global Standard in UK South has a limit of 1,000 (thousand tokens per minute) with none used, so UK South is used and the fallback in spec section 14 is not needed. Re-check with a read-only `az` command, deploy with capacity 100, and record both as agent decisions. If the quota has gone, use the fallback.
  3. Build S0 on branch `s0-harness` as plan S0 and RUNBOOK Prompt A step 3 a to g describe. Hooks only load in a new session, so prove them in this phase with the hook unit tests, leave the live proof for Phase 3, and record that in Status. Merge S0.
  4. Update the GitHub app PR: pin `claude-code-action` to a SHA at version 1.0.74 or later, keep `show_full_output` off, and point the review prompt at `REVIEW.md`. Merge it.
  5. Create the ruleset on `main` (PR required, required check `ci`, block force pushes and deletion, empty bypass list) and the `demo` environment with the owner as required reviewer.
  6. Run V.
- **B. Wave 1:** S1 in this session, with S2 and S4a as background subagents in worktrees. Golden labels go through the label-auditor rule in spec section 7.
- **C. Wave 2:** S3 in this session, with S4b and S5a as background subagents. Merge S3 before S5a.
- **D. Wave 3:**
  1. S4c: the stability proof, thresholds by the rule in plan Gates, then `evals` as a required check, then the weak-prompt PR.
  2. The S5a merge queues the first deploy, which waits for the owner; do not wait for it. Add to "Needs owner": make the ghcr.io package public, then approve the waiting deployment.
  3. S6: fill the dashboard with traffic from the local app (`uv run poe run` plus `scripts/traffic.py` against localhost). Local runs send telemetry to the same Application Insights.
- **E. Wave 4:** S8, using screenshots of the locally running app, then the final verification. Mark anything that needs the live URL as "pending live" rather than failed.
- **F. Finish:** update Status in `plan.md` and end with a BUILD REPORT. It covers:
  - what is merged, with PR links
  - the eval results and the stability proof
  - everything under "Needs owner", in the order the owner should do it
  - anything not green
  - the line the owner should type to start Phase 3

At most three agents work at once. If you hit a usage limit, finish the current step cleanly, update Status and stop; the owner will resume with RUNBOOK Prompt C.

---

## Phase 3: finish (the owner is present)

Before starting this phase, the owner will have:
1. Made the ghcr.io package public.
2. Approved the waiting deployment.
3. Restarted Claude Code with the same `--settings` command, so the hooks load.
4. Typed: `Follow Phase 3 of instructions-for-claude-code.md.`

Then:

1. Read `CLAUDE.md`, everything in `intent/`, `RUNBOOK.md` and the Status section of `plan.md`. Check the latest deploy run with `gh run view`.
2. Prove the hooks live in this fresh session as plan S0 Proof describes, and record it.
3. Finish S5b:
   1. Confirm the deploy and smoke results from the run logs. If the deploy failed, fix it through the normal PR steps first.
   2. Dispatch `deploy.yml` once with `warm=true`, then once with `image_sha` set to the current SHA.
   3. Each time a run is waiting for approval, tell the owner and wait. The owner approves; you never do.
4. Run `scripts/traffic.py` against the live URL with the `normal` and `injection-burst` profiles. Confirm all four dashboard tiles show live data.
5. Add screenshots of the live app, and re-run the final verification for every item marked "pending live".
6. Clear "Needs owner" in Status. Then give the owner a final report and the final-test checklist from RUNBOOK section 5.
