# Screenshots

The fallback pictures for the [walkthrough](../walkthrough.md), one per step. The application is deployed (14 October). Pictures of GitHub pages were taken by the lead session as a visitor who is not signed in, in a browser with a fresh profile, so they show what the public sees: GitHub shows the merge box of a pull request only to signed-in users, so `07-weak-prompt-pr.png` shows the gate's own comment instead. Profile pictures are hidden in every picture. The live app pictures show the result card only, so neither the address bar nor the token field is in them. The four portal pictures were taken by the lead at the owner's request, in the owner's own browser signed in to the portal (decision P3-13). Each is cropped to the panel its step points at, so the address bar, the portal header and the account menu are out of it, and the endpoint, the account rows and the request id are painted over. `05` and `06` are each joined from captures of one page at different scroll positions, because the panel is taller than the screen. All twelve files are in this folder.

| File | Shows | Walkthrough step | Taken by | State |
|---|---|---|---|---|
| `01-readme-scoreboard.png` | The README's results scoreboard with its validity statement and the first table, from the heading down. The disclaimer sits just above the heading in the README; the status line between them is left out so that a later merge does not date the picture | 1 | Lead | 14 October 2026 |
| `02-app-strong.png` | The live app's result card after "Strong answer": 5 / 5, runs 4, 5, 5, four highlighted quotes, no review trigger, the notice | 2 (J1) | Lead, after the owner saved the demo token | 14 October 2026 |
| `03-app-injection.png` | The live app's result card after "Injection attempt": 2 / 5, runs 2, 2, 2, the two review reasons and "Injection detected: yes" | 2 (J2) | Lead, after the owner saved the demo token | 14 October 2026 |
| `04-app-weak.png` | The live app's result card after "Weak answer": 1 / 5, a low score sent to a person | 2 (J3) | Lead, after the owner saved the demo token | 14 October 2026 |
| `05-foundry-deployment.png` | The `scorer-mini` deployment in the Foundry portal: "API Key authentication is disabled", version upgrade policy NoAutoUpgrade, model gpt-5.4-mini version 2026-03-17, and the guardrail DefaultV2 | 3 | Lead, in the owner's signed-in browser (decision P3-13) | 14 October 2026 |
| `06-appinsights-trace.png` | One `score` span with all 21 of its `scorer.*` properties and no answer text: a live request scored 1, runs 1, 1, 1, sent for review for `adverse_score`, with its salted answer hash and prompt hash. It is not the J1 trace that the runbook's final test names | 3 | Lead, in the owner's signed-in browser (decision P3-13) | 14 October 2026 |
| `07-weak-prompt-pr.png` | The weak-prompt pull request: the comment the required `evals` check posted, "Eval gate: FAIL", with every metric and the three it breached | 4 | Lead | 14 October 2026 |
| `08-ci-run.png` | One `ci` run, the one on #16, green. GitHub shows a run's steps only to signed-in users, so the steps are on the run's page, not in the picture | 5 | Lead | 14 October 2026 |
| `09-deploy-approval.png` | The first deploy run (for #16): both jobs green, and "Deployment protection rules" naming the owner as approver of `demo`. The provenance step is inside the `deploy` job's log | 5 | Lead | 14 October 2026 |
| `10-dashboard.png` | Tile 1 of the operational workbook with live data: requests, failures, availability and p50 and p95 latency against the 6 s SLO, and the latency chart. The figures under the chart are the portal's sums of the plotted points, not figures to quote. All six tiles have been live since 14 October (decision S9-5) | 6 | Lead, in the owner's signed-in browser (decision P3-13) | 14 October 2026 |
| `11-pull-requests.png` | The pull request list with each one's check results (the verifier verdicts and review findings are comments inside each pull request) | 7 | Lead | 14 October 2026 |
| `12-delivery-evidence.png` | The delivery evidence workbook's trust scorecard: trust score 95, 21 of 22 checks met, amber; the score per aspect; the validity warning | 6 | Lead, in the owner's signed-in browser (decision P3-13) | 14 October 2026 |

The runbook's final test asks the owner for three of these at least: the Foundry model deployment, the J1 trace in Application Insights, and the approved deployment in GitHub. A recording of one rehearsal is the owner's second fallback; link it from the README when it exists.

## Before a picture is committed

This repository is public, and a screenshot is the easiest place to leak something a text search will not find. Check every picture for:

- the browser's address bar, which in the Azure portal holds the subscription and resource identifiers, and in the live app holds the app's URL: crop it out;
- the account menu, tenant name, directory name and any email address in a page header;
- subscription, tenant, client and object identifiers anywhere on a portal page;
- the demo token field (it should be empty or masked) and any open developer tools;
- answer text other than the three synthetic samples.

Use PNG, crop to the part the step points at, and keep the file names above so the walkthrough's fallbacks still match. When a file is added, change its state in the table from "Pending live" to the date it was taken.
