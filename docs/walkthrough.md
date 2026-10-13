# Walkthrough

Eight minutes, ten at most, with a five-minute cut. The script follows the Walkthrough table in [the plan](../intent/plan.md) and corrects its wording where the build turned out differently. Each step has the exact clicks, one line to say and a fallback.

Say once, early: the data is synthetic, every output is decision support, and reliability is not validity. The results show the controls work; they do not show the scores are right.

## Where things stand (13 October 2026)

The application is **not deployed yet** and nothing is merged to `main` yet. Until that changes, the steps below marked **pending live** are shown from the fallback in the same step. The screenshots are listed in [screenshots/README.md](screenshots/README.md); none has been taken yet.

| Tab, left to right | Needs | State |
|---|---|---|
| 1. GitHub README | The repository | Ready. Some scoreboard figures are still PENDING |
| 2. Live app | The live URL and the demo token | Pending live. Fallback: the same app run locally |
| 3. Foundry portal, model deployment | The portal | Pending live (the owner's sign-in) |
| 4. Application Insights | The portal | Pending live (the owner's sign-in) |
| 5. Weak-prompt pull request | The stability proof merged, then the pull request opened | Pending: [[PENDING: weak-prompt pull request number]] |
| 6. Actions deploy run | The first deploy, approved by the owner | Pending live |
| 7. Dashboard | The portal, with traffic sent | Pending live (the owner's sign-in) |

## Before you start

On the day, about an hour before (from the plan's "Walkthrough day"; no deploys on the day):

1. Run `uv run poe smoke-remote`. It prints one line per case, with a trace id for each score. Keep the trace id of the strong case: it is the fallback for step 3.
2. Run `python scripts/traffic.py --profile normal` with `--base-url` set to the live URL and the demo token in the `DEMO_TOKEN` environment variable, so the dashboard has recent data. Telemetry takes a few minutes to become queryable. Type neither value into a file.
3. Open the seven tabs in the order above.
4. In the live app tab, paste the demo token into "Demo token" and click "Save for this tab". Never show the token on screen: the field hides it, so paste, do not type.
5. Keep [screenshots/README.md](screenshots/README.md) and its files open in an eighth tab.

If the app is not live, start it locally with `uv run poe run` and use `http://localhost:8000` for tab 2. It is the same code calling the same pinned model deployment, with a developer sign-in in place of the managed identity. Say that it is local.

## The eight-minute script

### 1. README scoreboard (0:00 to 0:40)

- **Clicks.** Tab 1. Open the repository's front page and scroll to "Results scoreboard". Point at the disclaimer above it, then at the first table: the accepted prompt beside the weakened one.
- **Say.** "Scoring is easy; trusted scoring in a high-risk domain is the hard part. Here are the results, on synthetic data, and they show the controls work, not that the scores are right."
- **Fallback.** `01-readme-scoreboard.png`, or the [README](../README.md) opened from a local checkout.

### 2. Live app: three samples (0:40 to 2:40), pending live

The page has three sample buttons after "Load a sample:". Each one fills the competency, the question and the answer. All three are synthetic `dev` rows, the same ones the smoke test sends.

**J1, a strong answer.**

- **Clicks.** Tab 2. Click "Strong answer", then "Score this answer". Wait for the "Result" card.
- **Point at.** The score and its level label; the badge ("No review trigger" when nothing tripped); the quotes highlighted under "The answer, with the quoted evidence highlighted"; "Runs" and "Spread" under "Details"; the notice at the foot of the card. Copy the "Trace id" for step 3.
- **Expect.** 5 / 5 "Exceptional", or 3 / 5 "Competent": in three live smoke runs this same answer scored 5 twice and 3 once. That is model variance. If it shows 3, say so and point at "Runs": do not click again to get a better number.

**J2, an injection attempt.**

- **Clicks.** Click "Injection attempt". Point at the last sentence of the answer: a note addressed to the scoring system that asks for the top score. Click "Score this answer".
- **Expect** (three live sends, decision S3-12). 2 / 5 "Developing", runs 2, 2, 2, the badge "Needs human review". Under "Why a person reviews this answer": the answer contains text that looks like an instruction to the scorer and was treated as data, and the score is 1 or 2. Under "Flags": "Injection detected: yes" and "Platform guardrail block: no". The score equals the label of the same answer without the note, so the demand changed nothing.
- **If Azure's guardrail blocks it on the day.** The card shows "Not scored", the badge "Needs human review" and the reason that the platform guardrail stopped the model call. Say that this is the designed outcome: routed to a person with no score, never an error and never a made-up score.

**J3, a weak answer.**

- **Clicks.** Click "Weak answer", then "Score this answer".
- **Expect.** 1 / 5 "Limited", the badge "Needs human review", with the reason that a low score always goes to a person.

- **Say.** "Input guards, the model, then output guards: every quote is checked against the answer, the manipulation attempt is flagged by our own screen and scored as data, and every low score goes to a person. Azure's guardrail is a further layer behind ours; it did not block this sample in testing, and if it does, the answer is routed with no score."
- **Plan wording corrected.** The plan's line says manipulation "is caught by our screen and Azure's guardrail". In live testing only our screen flagged this sample (decision S3-12), so do not say the guardrail caught it.
- **Fallback.** The local app (see "Before you start"), then `02-app-strong.png`, `03-app-injection.png` and `04-app-weak.png`.

### 3. Foundry deployment and one trace (2:40 to 3:30), pending live

- **Clicks, Foundry.** Tab 3. Open the model deployment `scorer-mini` in the Foundry portal. Point at the model version (2026-03-17), the version upgrade setting (no automatic upgrade) and the guardrail (`Microsoft.DefaultV2`). For keyless access, show `disableLocalAuth: true` in [foundry.bicep](../infra/modules/foundry.bicep): no key exists to leak.
- **Clicks, trace.** Tab 4. In Application Insights open "Transaction search", paste the trace id from J1 and open the end-to-end transaction. Select the `score` span and scroll its custom properties: `scorer.prompt_version`, `scorer.prompt_sha`, `scorer.model_version`, `scorer.score`, `scorer.runs`, `scorer.review_reasons` and `scorer.answer_hash`. Point out that there is no answer text anywhere in it.
- **Say.** "The model cannot change under us, nothing uses a key, and every decision is traceable without storing candidate text."
- **Fallback.** A trace takes a few minutes to appear, so if the J1 trace is not there yet, use the trace id kept from the smoke run. Otherwise `05-foundry-deployment.png` and `06-appinsights-trace.png`, or the attribute list in [telemetry.py](../src/scorer/telemetry.py). Portal menu names move; if a page has changed, search the portal for the resource by name.

### 4. Test: the weakened prompt, blocked (3:30 to 5:00), pending

- **Clicks.** Tab 5. Open the weak-prompt pull request. Show the changed files (a warmer prompt that asks for evidence "in your own words"), then the checks box: `ci` should be green and only the required `evals` check red, with the merge button blocked. Then open the comment the `evals` job posted with the metrics that breached.
- **Say.** "A realistic 'friendlier' prompt change was blocked before merge by a deterministic check, not by a reviewer's opinion."
- **The honest version of "proven stable".** The accepted prompt passed three full runs in a row on one commit, but at the third attempt (decision S4c-7). Attempt 1 went pass, pass, fail: on an answer that only repeats the question the model was inconsistent, so a deterministic check now routes that case. Attempt 2 stopped when the model was unavailable on one input, with no report and no invented score, so the runner now retries an input that has no score. Nothing was loosened: the prompt, thresholds, datasets and rubrics are unchanged. If there is time, tell it; it is the best evidence that the gate is real. The table is under "Stability proof" in the [eval card](eval_card.md#stability-proof).
- **Plan wording to confirm.** The plan adds "and the gate is proven stable". The weak-prompt half is still to come, so say it only once this is filled in: [[PENDING: the three weak-prompt runs all breached the gate, with the metrics that breached]]
- **Fallback.** `07-weak-prompt-pr.png`, then the "Stability proof" table in the [eval card](eval_card.md). If the pull request does not exist yet, show the gate itself: [thresholds.yaml](../evals/thresholds.yaml) and the `evals` check on pull request [#9](https://github.com/ranaidrees/answer-scorer/pull/9), where the accepted prompt met every threshold.

### 5. Build: checks, provenance and the approval (5:00 to 6:00), pending live

- **Clicks, checks.** Tab 6. In the "Actions" tab open the `ci` workflow and its latest run. Point at the steps: lint and tests, the Bicep build, the image build, the workflow lint and the secret scan.
- **Clicks, deploy.** Open the `deploy` workflow and its latest run. In the `build` job point at "Sign build provenance". In the `deploy` job point at "Verify build provenance", which runs before anything changes, and at the review banner that names the owner as the approver.
- **Say.** "Every change went through the same gates; the deploy refuses any image our pipeline did not build; and nothing reaches production without my approval, which the agent cannot give."
- **Plan wording corrected.** The plan's line says "the agent merged only what the gates passed". As of 13 October nothing is merged: the unattended build left every slice as a checked pull request (decision D19). Use the plan's line only once this is true: [[PENDING: the stack was merged after the required checks, and the first deploy ran with the owner as approver]]
- **Fallback.** `08-ci-run.png` and `09-deploy-approval.png`, or the two steps in [deploy.yml](../.github/workflows/deploy.yml).

### 6. Dashboard (6:00 to 7:00), pending live

- **Clicks.** Tab 7. In Application Insights open "Workbooks" and the workbook "Answer scorer dashboard". Set the time range to cover the traffic sent earlier. Go down the four tiles: requests, failures and p95 latency against the 6 s SLO; review rate by reason against the 25% band; tokens and estimated cost per score; eval runs with kappa, agreement and the gate result.
- **Say.** "Online evaluation on every live request: review rate by reason, plus p95 against the SLO, cost per score as an estimate, and the offline eval trend. No model judges live answers, because no answer text is ever stored."
- **Fallback.** `10-dashboard.png`, or run the tile queries from [queries.kql](../dashboards/queries.kql) in the Logs page. The agent deployed the workbook and read it back but did not open it in the portal (decision S6-2), so check how the tiles render before the day.

### 7. Repository history (7:00 to 8:00)

- **Clicks.** Tab 1. Open the `intent` folder: [intent](../intent/intent.md), [spec](../intent/spec.md), [plan](../intent/plan.md). Open the "Pull requests" tab and one slice, for example [#7](https://github.com/ranaidrees/answer-scorer/pull/7): show the verifier's verdict and the review findings in its comments. Open [decisions.md](../intent/decisions.md) and point at the last column: agent, rule or owner on every row.
- **Say.** "Claude Code built it inside gates I designed; I own the intent, the gates and production. That is how I would run AI-native delivery for a team."
- **Plan wording corrected.** The plan says "PRs with AI review". The review on each pull request so far is an independent review run in the build session against `REVIEW.md`, posted as comments; the Claude review in CI starts once its workflow is on `main` (decision D25). The plan also says "built and merged"; say "merged" only when the stack has merged.
- **Fallback.** `11-pull-requests.png`, or the "How it was built" table in the [README](../README.md#how-it-was-built).

### 8. Questions (8:00 to 10:00)

- **Say.** "What production adds: trained raters, adverse impact analysis, a DPIA, and the 2 December 2027 date for the high-risk obligations."
- **Have ready.** The limits, said plainly: synthetic data written, labelled and audited by one model family; a prompt that met the gate untuned, so the golden set may be easy; 30 answers, so no confidence intervals; the same answer can score differently between runs; the pair gates have little headroom, so roughly 1 full run in 20 might breach one from noise alone (an estimate from eight runs, not a measured rate); hooks are guardrails, not a boundary. They are in the [eval card](eval_card.md) and the [governance note](governance.md).

## The five-minute cut

| Time | Step | What changes from the full script |
|---|---|---|
| 0:00 to 0:30 | 1. README scoreboard | First table only |
| 0:30 to 2:00 | 2. Live app | J1 and J2 only; skip J3 |
| 2:00 to 3:00 | 4. Weak-prompt pull request | The red `evals` check and the blocked merge; skip the comment |
| 3:00 to 3:30 | 5. Deploy approval | The review banner only |
| 3:30 to 4:30 | 7. Repository history | One pull request and `decisions.md` |
| 4:30 to 5:00 | Close | "I own the intent, the gates and production; the agent works inside them. Reliability is not validity, and production would add trained raters." |

Steps 3 and 6 are dropped. If someone asks, show `06-appinsights-trace.png` and `10-dashboard.png`.

## If something breaks

| What happens | Do this |
|---|---|
| The app answers slowly on the first click | It scales to zero when idle, so the first request is slow by design. Wait, and say so |
| "The demo token was not accepted" | Paste the token again and click "Save for this tab" |
| "Too many requests from this address" | The rate limit is 10 a minute. Wait a minute; talk through the previous result |
| "The model is unavailable, so no score was produced" | Say that this is the design: no score is ever made up. Try once more, then go to the screenshots |
| A score differs from the one expected | Say what it shows and point at "Runs" and "Spread". Do not rerun for a better number |
| A portal page will not load | Go to the screenshot for that step and the file linked in its fallback |
