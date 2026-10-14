# Plan: delivery evidence dashboard (S9)

- **Reads:** `intent.md` and `spec.md` in this folder.
- **Stage:** 3 of 3 for this slice. Time box: 15:10 to 17:30 on 14 October 2026; freeze at 18:00.

## Who does what

| Step | Who | When |
|---|---|---|
| Agree this plan | owner | once, now |
| Snapshot script and its tests | build agent 1, in the S9 worktree | in parallel with step 3 |
| Workbook builder, Bicep, tests, `ci.yml` line | build agent 2, in the same worktree, other files | in parallel with step 2 |
| Wording notes from #19 (decision P3-12) | records agent, own branch | in parallel |
| Run the snapshot; run every new query read-only against Application Insights; `what-if` the Bicep | lead | after steps 2 and 3 |
| Verifier, security review, pull request, checks, merge | lead | after that |
| Apply the two deployments (spec section 6) | owner | once, after the merge: the only other owner action |
| Read the workbook back, give the owner its portal link, record the apply | lead | after the apply |

## Order

1. Write these three files and decision S9-1. Start the agents.
2. When both build agents return: generate the snapshot, build the workbook, run `uv run poe check`, run each `datatable` and live query with `az monitor app-insights query` (read-only).
3. `az deployment group what-if` on `infra/sdlc_dashboard.bicep` (read-only).
4. Verifier against this plan; security review of the diff; pull request; `ci` and `evals` checks; squash merge.
5. Ask the owner once to run the two commands in spec section 6.
6. Read the workbook back (read-only), check that its items equal the file, and give the owner the portal link. The README row and the walkthrough step went into the S9 pull request itself (decision S9-3).

## Cut if behind

1. The live tiles on the In production tab (keep the deploys table and a link to the operational dashboard).
2. The decisions bar chart (keep the table).
3. The `ci` timing chart (keep the median figures).

## Risks

- The merge queues a `deploy` run, because `infra/` is not in the deploy workflow's ignore list. It changes no application code; the owner may approve or reject it.
- The workbook has not been seen rendered until the owner applies it; a layout fix would need a second apply.
- The snapshot goes stale; the tab headers show its date, and a pull request refreshes it.
