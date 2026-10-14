# Screenshots

The fallback pictures for the [walkthrough](../walkthrough.md), one per step. The application is deployed (14 October). Pictures of GitHub pages were taken by the lead session as a visitor who is not signed in, in a browser with a fresh profile, so they show what the public sees: GitHub shows the merge box of a pull request only to signed-in users, so `07-weak-prompt-pr.png` shows the gate's own comment instead. Every file not yet in this folder is pending live.

| File | Shows | Walkthrough step | Taken by | State |
|---|---|---|---|---|
| `01-readme-scoreboard.png` | The README's results scoreboard with the disclaimer above it | 1 | Lead or owner | Pending live |
| `02-app-strong.png` | The live app after "Strong answer": score, highlighted evidence, runs, spread, notice | 2 (J1) | Lead or owner | Pending live |
| `03-app-injection.png` | The live app after "Injection attempt": the review reasons and "Injection detected: yes" | 2 (J2) | Lead or owner | Pending live |
| `04-app-weak.png` | The live app after "Weak answer": a low score sent to a person | 2 (J3) | Lead or owner | Pending live |
| `05-foundry-deployment.png` | The `scorer-mini` deployment: pinned version, no automatic upgrade, guardrail | 3 | Owner (portal) | Pending live |
| `06-appinsights-trace.png` | One `score` span with its `scorer.*` properties and no answer text | 3 | Owner (portal) | Pending live |
| `07-weak-prompt-pr.png` | The weak-prompt pull request: the comment the required `evals` check posted, "Eval gate: FAIL", with every metric and the three it breached | 4 | Lead | 14 October 2026 |
| `08-ci-run.png` | One `ci` run with its steps | 5 | Lead or owner | Pending live |
| `09-deploy-approval.png` | The deploy run: provenance verified, and the owner named as approver | 5 | Owner | Pending live |
| `10-dashboard.png` | The workbook's four tiles with data | 6 | Owner (portal) | Pending live |
| `11-pull-requests.png` | The pull request list with each one's check results (the verifier verdicts and review findings are comments inside each pull request) | 7 | Lead | 14 October 2026 |

The runbook's final test asks the owner for three of these at least: the Foundry model deployment, the J1 trace in Application Insights, and the approved deployment in GitHub. A recording of one rehearsal is the owner's second fallback; link it from the README when it exists.

## Before a picture is committed

This repository is public, and a screenshot is the easiest place to leak something a text search will not find. Check every picture for:

- the browser's address bar, which in the Azure portal holds the subscription and resource identifiers, and in the live app holds the app's URL: crop it out;
- the account menu, tenant name, directory name and any email address in a page header;
- subscription, tenant, client and object identifiers anywhere on a portal page;
- the demo token field (it should be empty or masked) and any open developer tools;
- answer text other than the three synthetic samples.

Use PNG, crop to the part the step points at, and keep the file names above so the walkthrough's fallbacks still match. When a file is added, change its state in the table from "Pending live" to the date it was taken.
