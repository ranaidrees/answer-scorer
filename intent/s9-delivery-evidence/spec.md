# Spec: delivery evidence dashboard (S9)

- **Reads:** `intent.md` in this folder. **Read next:** `plan.md` in this folder.
- **Stage:** 2 of 3 for this slice.

## 1. Data route (decision S9-1)

Three routes were compared on 14 October:

| Route | Effort | Freshness | Risk |
|---|---|---|---|
| Workbook Custom Endpoint calling the public GitHub API | medium | live | every viewer must mark `api.github.com` as a trusted host in their own browser, or the tiles stay blank; 60 calls an hour per viewer; approvals and security data need a token |
| GitHub Actions sending delivery events to Application Insights | high | live | changes `src/scorer/telemetry.py`, which runs the paid eval gate and a deploy |
| **A snapshot made by a script and embedded in the workbook** | low | as of the commit | none at view time; refreshed by a pull request |

Chosen: the snapshot for GitHub and repository figures, embedded as KQL `datatable` queries, and the existing KQL queries for live figures. Sources: https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-data-sources#custom-endpoint and https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-data-sources#json (both note that everything in a workbook query is visible to every viewer, so no token can go in one).

## 2. Files

| File | What it is |
|---|---|
| `scripts/sdlc_snapshot.py` | Reads GitHub with the signed-in `gh` CLI (read-only calls) and the repository; writes `dashboards/sdlc_snapshot.json`. Never prints a token or an email address |
| `dashboards/sdlc_snapshot.json` | The snapshot, committed. Schema in section 3 |
| `scripts/build_sdlc_workbook.py` | Turns the snapshot, plus four tile queries from `dashboards/queries.kql`, into `infra/sdlc_workbook.json`. Deterministic: the same snapshot gives the same file |
| `infra/sdlc_workbook.json` | The workbook layout and queries. No resource ID |
| `infra/sdlc_dashboard.bicep` | One workbook, bound to Application Insights by name at deploy time, as `observability.bicep` does |
| `tests/unit/test_sdlc_snapshot.py`, `tests/unit/test_sdlc_dashboard.py` | New tests (section 5) |

`ci.yml` also builds the new Bicep file. `README.md` gains a row for S9 in its build table, and `docs/walkthrough.md` gains the second workbook in its dashboard step (decision S9-3). Nothing under `src/`, `prompts/`, `rubrics/`, `evals/` or `config/` changes, so the eval gate has nothing to run.

## 3. Snapshot schema

```json
{
  "generated_at": "2026-10-14T15:30:00Z",
  "repository": "ranaidrees/answer-scorer",
  "before_production": {
    "figures": [{"measure": "Tests passing", "value": "1762", "detail": "unit and hook tests, every pull request", "source": "https://github.com/ranaidrees/answer-scorer/actions/workflows/ci.yml"}],
    "ci_runs": [{"started": "2026-10-13T15:27:07Z", "job_seconds": 15, "test_seconds": 7}],
    "gates": [{"gate": "Actions pinned to a full commit SHA", "status": "14 of 14", "source": "https://github.com/ranaidrees/answer-scorer/tree/main/.github/workflows"}]
  },
  "in_production": {
    "figures": [],
    "deploys": [{"started": "2026-10-14T07:40:12Z", "route": "merge of #16", "commit": "cc949e0", "approved_by_owner": "yes", "provenance_verified": "passed", "smoke_test": "passed", "result": "success", "source": "https://github.com/ranaidrees/answer-scorer/actions/runs/0"}]
  },
  "ai_native_sdlc": {
    "figures": [],
    "stages": [{"stage": "Plan", "artifact": "intent/intent.md", "gate": "the owner commits it", "source": "https://github.com/ranaidrees/answer-scorer/blob/main/intent/intent.md"}],
    "decisions_by_who": [{"who": "agent", "decisions": 143}]
  }
}
```

Every `figures` row has the four keys shown, all strings. Every `source` starts with `https://github.com/ranaidrees/answer-scorer`. Times are UTC ISO 8601 with a `Z`.

## 4. Figures (lean: what the walkthrough needs)

**Before production.** Figures: tests passing (from `pytest --collect-only`); `ci` runs passed of all runs; median `ci` job and test-step time; merged pull requests and the weak-prompt one blocked; eval gate stability proof (accepted prompt 3 PASS, weakened prompt 3 FAIL, decision S4c-11); kappa of the three proof runs; injection cases flagged (18 of 18); label audit (30 of 30, two Claude agents). Chart: job and test-step seconds per `ci` run. Gates table: actions pinned, `ci` and `evals` required with an empty bypass list, CodeQL default setup on, gitleaks in `ci`, secret scanning with push protection, Dependabot, signed provenance verified before every deploy. No alert counts or alert details (they are not public).

**In production.** Deploys table: one row per run of the deploy workflow, oldest first, so the runs the owner rejected and the ones GitHub cancelled while they waited are shown beside the three that deployed (the first deploy, the `warm` route, the `image_sha` rollback route). Columns: route, approval (yes, rejected by owner, not reached), provenance check and smoke test (passed, failed, skipped, not run), and result, read from the run's jobs, steps and approvals. Change failure rate counts deploys whose app-changing step succeeded and whose smoke test then failed. Figures: deploys approved by the owner, change failure rate, time from merge to production for the first deploy, rollback route proven, spend estimate against the budget (from plan Status). Live: the existing `tile1_requests_latency`, `tile2_review_rate_by_reason`, `tile3_tokens_cost` and `tile4_eval_runs`, text equal to `dashboards/queries.kql`, under one time-range parameter (default 30 days).

**AI-native SDLC.** Stages table from spec section 10 of the main spec: stage, artifact, gate, who decides. Figures: commits on merged pull request branches that carry the agent's co-author line, of all of them; decisions by who (agent, owner, rule, shared), from `intent/decisions.md`, also as a bar chart; owner deploy approvals; verifier FAIL verdicts and Important review findings fixed before merge (from the README scoreboard); first intent commit to first approved deploy.

Every tab ends with a caption: the data is synthetic; reliability is not validity; every review counted here was made by an AI agent, not a person.

## 5. Tests

- The workbook file equals what the builder makes from the committed snapshot.
- The four live queries equal their text in `dashboards/queries.kql`.
- No resource ID, GUID other than the parameter ids, email address, host name of the app, `/subscriptions/`, instrumentation key or long dash in any new file; every link points at this repository.
- The Bicep file creates exactly one workbook and references Application Insights by name, as `observability.bicep` does.
- The snapshot script, with a fake `gh`, builds every section, computes medians and the approval column correctly, and prints no token or email address.

## 6. Deployment

The owner runs, once, both pending observability deployments:

```
az deployment group create --resource-group rg-answer-scorer-demo --template-file infra/observability.bicep --parameters applicationInsightsName=<name> alertEmail=<address>
az deployment group create --resource-group rg-answer-scorer-demo --template-file infra/sdlc_dashboard.bicep --parameters applicationInsightsName=<name>
```

The first one also makes tiles 5 and 6 of the operational dashboard live (decision P3-10).
