# Service level objectives

What the scoring service promises, how each promise is measured, and what happens when one is missed. The design is in `intent/spec.md` section 8. Every query named here is in `dashboards/queries.kql`; the dashboard and the alert rules are in `infra/observability.bicep` and `infra/workbook.json`.

Everything on this page is measured from metadata: status codes, timings, flags and counts. No candidate text is recorded, so no query, tile or alert can show any.

## The four objectives

| SLO | Target | Measured by | Alert |
|---|---|---|---|
| Latency | p95 at or under 6 s | `tile1_requests_latency`, `tile1_latency_over_time` | Log alert `alert-answer-scorer-latency-p95` (query `alert_latency_p95`): p95 over 6 s for 15 minutes |
| Availability | 99% of non-4xx requests succeed | `tile1_requests_latency` | Log alert `alert-answer-scorer-availability` (query `alert_availability`): under 99% over 1 hour |
| Review rate band | Control-triggered review rate at or under 25% of live traffic | `tile2_review_rate_by_reason`, `tile2_review_rate_over_time` | Dashboard tile only |
| Model quality | The nightly eval gate passes | `tile4_eval_runs` | GitHub notification when the nightly run fails |

The dashboard has three more views that carry no objective: tokens and estimated cost per score (`tile3_tokens_cost`), the eval history per run (`tile4_eval_runs`), and live drift by day (`tile5_drift_by_day`).

## How each one is measured

**Latency.** The duration of each request to `POST /api/score`, as Application Insights records it for the whole HTTP call: the three model calls and everything around them. Only completed requests (status 200) are measured. A refused request (wrong token, rate limit, input that cannot be scored) returns in a few milliseconds and would pull the percentiles down. The target is for a warm replica. The app scales to zero, so the first request after an idle period is slower by design, and it shows on the chart.

**Availability.** Of the requests to `POST /api/score` that are not a 4xx, the share that did not end in a 5xx. A 4xx is the caller's side. A 503 (the model was unavailable, so no score was given) and a 500 both count against the target. A platform guardrail block is a 200 with no score and a review flag: the service did its job, so it does not count as a failure.

**Review rate band.** A scored request is a `score` span that carries `scorer.request_id`. Its `scorer.review_reasons` attribute lists why the answer was sent to a person: `injection_detected`, `hidden_text_removed`, `platform_guardrail`, `ungrounded_quote`, `inconsistent`, `off_topic`, `rationale_protected_term` and `adverse_score`. The control-triggered rate counts a request once when it has any reason other than `adverse_score` alone. A low score always goes to a person by rule, so it says nothing about how the controls behave, and it is left out. The rate is read against 25% over the time range chosen on the dashboard. There is no alert: a burst of injection attempts is meant to push it up, and that is a thing to look at, not a fault to page for.

**Model quality.** Each full eval run against the live model sends one `eval_run` event from CI with the trigger, every metric and the gate result. The tile lists the runs, newest first, with quadratic weighted kappa, exact and within-1 agreement and PASS or FAIL, and labels each run as pull request, nightly or manual. The alert is GitHub's own: a nightly run that fails the gate fails the workflow, and GitHub notifies the owner.

**Live drift.** `tile5_drift_by_day` gives one row per day of scored requests: the share of scores at 1 or 2, at 3 and at 4 or 5, the mean score, the median answer length (`scorer.input_chars`), and the injection and off-topic rates, with the change in mean score and median length against the first day in the time range. A live answer has no label, so this view cannot show that scores became wrong. It shows that what comes in, or what the model gives back, has moved, and that is the prompt to look at the nightly eval on tile 4, which is the check against labels. There is no alert on it: a day with a handful of requests moves a lot, and a burst of injection attempts is meant to move the injection rate.

**Tokens and cost.** `scorer.tokens_in` and `scorer.tokens_out` are the sums over the three model calls of one score. `scorer.cost_estimate_gbp` multiplies them by the published prices in `config/prices.yaml`, with every input token at the full input price. It is an estimate and is labelled as one wherever it appears. It is never the invoice. The per-score figures are averaged over requests that were given a score. A request the platform guardrail blocked has no score, so it is counted in its own column, and its tokens and estimated cost appear in the totals only.

## The two review rates: a 15% gate and a 25% band

They share a definition and nothing else.

| | 15% gate | 25% band |
|---|---|---|
| Measured on | The golden set: 30 labelled answers written to be clean | Live traffic: whatever people send |
| Where | CI, on every eval run (`golden_control_review_rate` in `evals/thresholds.yaml`) | The dashboard (`tile2_review_rate_by_reason`) |
| What a breach means | The scorer or the prompt changed so that clean answers are being flagged: a regression | Live answers are tripping the controls more than expected: look at which reason is driving it |
| What happens | The eval gate fails and the pull request cannot merge | Nothing automatic. A person reads the tile |

The golden set holds no injected answers and no edge cases, so its rate should sit near zero and 15% is a tight limit on false alarms. Live traffic includes real injection attempts, off-topic answers and pasted text with hidden characters, where a flag is the control working. The band is wider for that reason, and it is a level to notice, not a pass mark. The two numbers must never be compared with each other. Tile 4 shows the golden-set rate of each eval run next to its gate result, so both can be seen on one page without being mixed up.

## The alert rules

Both are scheduled log alert rules on the Application Insights resource, and both send email through the action group `ag-answer-scorer-email`. The address is a deployment parameter and is in no file.

| Rule | Fires when | Window | Runs every | Severity |
|---|---|---|---|---|
| `alert-answer-scorer-latency-p95` | p95 of completed requests is over 6 s, with at least five completed requests in the window | 15 minutes | 15 minutes | 2 |
| `alert-answer-scorer-availability` | Fewer than 99% of non-4xx requests succeeded | 1 hour | 1 hour | 1 |

- **No data, no alert.** Each rule fires when its query returns a row, and each query returns a row only on a breach. A window with no requests returns nothing. This matters here because the app scales to zero and is idle most of the time.
- **At least five requests for latency.** One request is not a percentile, and the first request after a scale to zero is slow by design. Without the floor, every cold start would send an email.
- **They resolve themselves.** A fired alert closes when a later window is healthy again.
- **Cost.** A log alert rule is charged per month by how often it runs. Both rules run at the cheapest tier (every 15 minutes or less often). The figure and its source are in `intent/decisions.md` (S6-4). They are the only resources in this project with a monthly charge; delete them with the rest of the resource group when the demo ends.

Alert email only reaches an address that its owner has confirmed. Azure sends a confirmation message with a one-time passcode when the action group is first saved, and an unconfirmed address gets neither alerts nor test notifications.

## Deploying and checking

The dashboard and the alerts are deployed on their own, never through `main.bicep` and never with `azd`:

```
az deployment group create --resource-group rg-answer-scorer-demo --template-file infra/observability.bicep --parameters applicationInsightsName=<name> alertEmail=<address>
```

Pass both values from commands at run time so that neither is typed or stored. To put data on the dashboard, run the app and send paced demo traffic (every request makes three model calls, so keep runs small):

```
python scripts/traffic.py --profile normal
python scripts/traffic.py --profile injection-burst
```

The traffic script sends `dev` rows of the evaluation datasets only, never a `holdout` row. Telemetry takes a few minutes to become queryable. After an injection burst the control-triggered rate goes well over the band. That is the tile doing its job.
