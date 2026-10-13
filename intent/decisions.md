# Decisions

One line per decision: date, decision, reason, and who made it.

- **owner**: the repository owner decided it. C1 to C21 were settled in `intent/spec.md` section 13, which the owner committed.
- **agent**: Claude Code decided it during the build, where intent, spec and plan did not settle the point.
- **rule**: a rule in the spec or plan decided it mechanically (for example the label audit rule or the threshold rule).

No line here records a human review that did not happen.

## Design decisions from the spec (C1 to C21)

| Date | ID | Decision | Reason | Who |
|---|---|---|---|---|
| 2026-10-12 | C1 | Model gpt-5.4-mini, version 2026-03-17, Global Standard, UK South, deployment `scorer-mini`, `NoAutoUpgrade`, `reasoning_effort: "none"` | Current small model open to new customers; older mini models are deprecated | owner |
| 2026-10-12 | C2 | Eval results go to Application Insights and GitHub only; the Foundry evaluation view is Later | Protects the deadline | owner |
| 2026-10-12 | C3 | Maintain loop is Later | Protects the deadline | owner |
| 2026-10-12 | C4 | Demo URL protected by a demo token header plus a per-IP rate limit (10 requests per minute) | Simple abuse control for a public demo | owner |
| 2026-10-12 | C5 | Claude in CI through `/install-github-app` with a subscription token; `--bare` never used with it | Acceptable for ordinary individual use | owner |
| 2026-10-12 | C6 | Prompt Shields document-attack detection is Later; heuristic detector plus delimiters this week | Protects the deadline | owner |
| 2026-10-12 | C7 | `config/prices.yaml` filled from published Azure prices, with URL and date; cost labelled as an estimate | Never guess a price | owner |
| 2026-10-12 | C8 | Telemetry sampling at 100% | Low volume | owner |
| 2026-10-12 | C9 | Public image on `ghcr.io`; no Azure Container Registry | No fixed cost, no registry credentials | owner |
| 2026-10-12 | C10 | MIT licence | Reusable reference | owner |
| 2026-10-12 | C11 | Personal notes live in `private/`, git-ignored, never committed | Public repository | owner |
| 2026-10-12 | C12 | Inference role is Cognitive Services OpenAI User for the app and `id-eval`; Foundry User noted as Microsoft's broader preferred role | Narrowest role for the `/openai/v1` endpoint | owner |
| 2026-10-12 | C13 | GitHub OIDC through two managed identities created with the Azure CLI, immutable subject format; not `azd pipeline config` | `azd pipeline config` grants broad subscription roles | owner |
| 2026-10-12 | C14 | Global Standard in UK South accepted for synthetic data; production would assess a regional or data-zone option | Data at rest stays in region; prompts may be processed elsewhere | owner |
| 2026-10-12 | C15 | Developer machine is Windows: Git Bash, Python hooks, poethepoet tasks, `.gitattributes`, no Docker, no Make | Matches the owner's machine | owner |
| 2026-10-12 | C16 | Microsoft Learn MCP and Azure MCP Server (read-only); Azure writes only through CLI commands that pass the hook and deny rules | Inspect freely, change narrowly | owner |
| 2026-10-12 | C17 | Lead session plus subagents in worktrees; no agent teams | Agent teams are experimental | owner |
| 2026-10-12 | C18 | Claude Code works autonomously in auto mode and merges PRs that pass the required checks. The owner keeps sign-ins, the GHCR visibility toggle, every production deploy approval, any threshold loosening and final acceptance | The human sits where the risk is | owner |
| 2026-10-12 | C19 | `Microsoft.DefaultV2` guardrail bound explicitly on the deployment; a guardrail block is a routed outcome with no score, never an error | Visible as code; no fabricated score | owner |
| 2026-10-12 | C20 | Actions pinned to SHAs with Dependabot; CodeQL default setup; signed build provenance verified before deploy; ruleset with an empty bypass list | Verifiable supply chain | owner |
| 2026-10-12 | C21 | Reference-free online checks on every live request; no LLM judge on live traffic | Candidate text is never stored | owner |

## Build decisions

| Date | ID | Decision | Reason | Who |
|---|---|---|---|---|
| 2026-10-13 | D1 | Model quota re-checked with a read-only `az cognitiveservices usage list` for UK South: gpt-5.4-mini Global Standard limit 1,000 (thousand tokens per minute), 0 used; version 2026-03-17 is generally available there. UK South is used and the Sweden Central fallback is not needed | Spec C1 **[confirm]** item | agent |
| 2026-10-13 | D2 | Deployment capacity is 100 (thousand tokens per minute) | A full eval run makes about 270 short calls; 100 leaves headroom without holding the whole quota | agent |
| 2026-10-13 | D3 | The LICENSE copyright line uses the repository owner's GitHub handle | It is already public on the repository; no further personal detail is added | agent |
| 2026-10-13 | D4 | CodeQL default setup is switched on after S0 merges, not before | GitHub rejects the setting (HTTP 422) while the repository has no Python or workflow files | agent |
| 2026-10-13 | D5 | `ci.yml` runs on pull requests with a fixed workflow-level `cache-mode: read`; workflows that run on pushes to `main` set `write` | GitHub's `cache-mode` key (changelog 10 September 2026) is set per workflow or job; a fixed value is simpler than an expression | agent |
| 2026-10-13 | D6 | gitleaks runs in CI as the release binary, pinned by version and SHA-256, over the full history | No extra action, no extra token permission, and the pin is as strong as an action SHA | agent |
| 2026-10-13 | D7 | The deny rules from spec section 10 are repeated for the PowerShell tool, with `Read(**/.env*)` added | Claude Code on Windows offers both shells; a Bash-only rule would leave a gap | agent |
| 2026-10-13 | D8 | The Azure MCP server is registered as `cmd /c npx ...` | Claude Code on native Windows cannot spawn the `npx` shim directly | agent |
| 2026-10-13 | D9 | Slice branches are brought up to date by rebasing before their first push, or by merging `main` after it; never by force push | The cloud gate denies every force push, and squash merges make branch history irrelevant | agent |
| 2026-10-13 | D10 | `cloud_gate.py` lets a ruleset or environment update through only when its JSON body is sent with `--input <file>` and the file keeps the gate intact (active enforcement, empty bypass list, PR, `ci`, no force push, no deletion; a required reviewer on the environment). Anything it cannot read is denied | Adding `evals` as a required check must stay possible, while weakening the ruleset must not | agent |
| 2026-10-13 | D13 | After the first verifier run returned FAIL and the security review found fail-open shapes, `cloud_gate.py` was tightened: every command in a compound line is checked; attached flags (`-XDELETE`, `-fkey=value`), global flags before a subcommand, the PowerShell stop-parsing token and quoted tool names are read; a role assignment needs a literal role and a literal scope inside the project resource group; a bare push is denied when the same command changes folder or branch; ruleset, environment and repository paths match variables and placeholders; a ruleset or environment change must be the only command in the call; the ruleset must keep covering `main`, and keep `evals` once `evals.yml` exists; named GraphQL mutations are denied | "A gate hook that fails open" is the slice's own named risk | agent |
| 2026-10-13 | D17 | The second verifier run also returned FAIL, for four shapes still open in `cloud_gate.py`. Fixed with tests: the repository path is read in every spelling (leading slash, full URL, placeholders, shell variables); visibility keys are read when attached to `-f` or `-F`; the rules run over a quote-blind split as well as the quote-aware one, so a stray quote cannot hide later commands; a repeated or unreadable HTTP method fails closed; quoted and widely spaced flag values and the `@` alias for `HEAD` are read | The verifier gate applies to the harness itself; a PASS is needed before S0 merges | agent |
| 2026-10-13 | D18 | The third verifier run returned FAIL for one shape: a push whose branch is a shell variable or a command substitution. Fixed with tests, along with its notes: such a push is denied as unreadable; the flag patterns were made unambiguous so a long run of flags cannot stall the gate; `gh` and `git` are read in any letter case; a write to an endpoint held entirely in a variable, a trailing slash and a query string on the repository path are read | Same reason as D17 | agent |
| 2026-10-13 | D14 | Known limits of the hooks, accepted: the gate matches text, so it also fires on a blocked command quoted in prose (long text is passed as a file); `protect_evidence.py` and the `Read` deny rules cover the file tools only, not shell commands; the gate cannot see what a script does once it runs | Spec section 10: hooks are guardrails, not a boundary. The verifier, the ruleset with an empty bypass list and the owner-only deploy approval are the next lines | agent |
| 2026-10-13 | D15 | The Azure MCP server is pinned to an exact version (3.0.0) instead of `@latest`, and bumped by hand. The allow rules for `git diff *` and `git log *` were dropped | An unpinned package would run whatever is published at session start, against C20; those two git commands can write files with `--output` | agent |
| 2026-10-13 | D16 | Every squash merge passes the owner's GitHub no-reply address as the commit author and an explicit commit body | GitHub would otherwise use the account's web commit email, and add co-author lines taken from the branch commits | agent |
| 2026-10-13 | D11 | Hooks are proven in the unattended build by their unit tests (allow and deny cases for every rule, run by `uv run poe check`). The live proof in a fresh session is left for Phase 3 | Hooks, settings and agents load only when a session starts | agent |
| 2026-10-13 | D12 | Separate `plan/wave-N` pull requests are not opened in the unattended build; each slice is built from its plan section as written, and departures are listed under Deviations | The compressed schedule in `instructions-for-claude-code.md` lists no wave-plan step, and that file wins | agent |
