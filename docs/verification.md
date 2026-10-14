# Final verification checklist

Run on 13 October 2026 by an independent, read-only verifier subagent of the build session, against `main` after pull request #13 was merged. **No person ran or reviewed this check.** Every item under "How we will know it worked" in [the intent](../intent/intent.md) and every acceptance criterion of FR-1 to FR-10 in [the spec](../intent/spec.md) was checked against code, tests, datasets, workflows and committed reports, not against what a document claims.

**Phase 3 re-check, 14 October 2026.** After the first deploy, the build's lead session re-checked every item that was PENDING LIVE or not checkable from the repository, against the deployed application, GitHub and Azure. It read state only, apart from the live traffic the plan asks for (45 scored requests: the deploy's smoke test, then the `normal` and `injection-burst` profiles of `scripts/traffic.py`). No person ran or reviewed this re-check either. The rows below show the result; where a verdict changed, the evidence says what was seen live.

Verdicts: **MET** (evidence in the repository, or seen live where the row says so), **PENDING LIVE** (needs the portal, a screenshot or an owner action), **Not checkable from the repository** (the evidence is a GitHub or Azure state).

## Result

The verifier returned **FAIL** with one criterion not met: FR-2, "validates schema at startup and fails fast". Rubrics were validated on `/readyz` and on each request, but nothing stopped the server from starting over a broken rubric. That is fixed in the same pull request as this page: the server now loads every rubric and the active prompt at start-up and refuses to start if either fails, with tests in `tests/unit/test_fr2_startup.py`. The row below shows the fixed state. The full criteria check was not run again after the fix. The verifier on that branch confirmed the fix sound and returned PASS at the final commit of #16 (decision P3-8), and `uv run poe check` passed.

| | MET | PENDING LIVE | Not checkable from the repository |
|---|---|---|---|
| "How we will know it worked" (11 rows), 13 October | 4 | 5 | 2 |
| The same 11 rows after the Phase 3 re-check, 14 October (one MET row, the dashboard, still waits for the owner to see the workbook rendered in the portal) | 10 | 1 | 0 |
| Functional requirements (42 rows) | 42, one of them after the fix above | 0 | 0 |

Commands the verifier ran: `uv run poe check` ("All checks passed!", "90 files already formatted", "1664 passed" on `main`; this branch, with the demo pack tests and the fix, gives 97 files and 1760 passed) and the offline dry run of the eval suite ("GATE: PASS (dry run with the fake model; says nothing about the scorer's quality)").

## How we will know it worked

| Item | Verdict | Evidence |
|---|---|---|
| The live URL scores an answer with p95 latency within the SLO | MET (live, 14 October) | Tile 1 query over the deployed app's telemetry: 46 requests, 45 completed with a score, 0 failures, p50 1.78 s and p95 2.25 s against the 6 s SLO (request duration in the app). The traffic script measured p95 5.1 s from this machine on the `normal` profile, whose first request waited 20.7 s for a replica to start from zero, and 2.3 s on the burst. The SLO is set for a warm replica (spec section 5) |
| The weakened prompt fails the eval gate with a clear reason, three times in a row | MET | Three full-run reports on the `demo/weak-prompt` branch only, one commit, prompt `v0-weak`, each "Eval gate: FAIL", each naming the ungrounded quote rate and the control-triggered review rate |
| The main prompt passes three times in a row | MET | `evals/reports/20261013T202107Z`, `20261013T202848Z`, `20261013T203628Z`: full runs, one commit, prompt `v1`, each "Eval gate: PASS". The scorer code on `main` differs from that commit by a comment only. It took three attempts (decisions S4c-2, S4c-5, S4c-7); the earlier reports, one of them a FAIL, are committed |
| A pull request with the weakened prompt fails the gate and cannot merge | MET (live, 14 October) | Pull request #15, read again with the GitHub CLI: open, `ci` passed, the required `evals` check failed, and GitHub reports the merge state as `BLOCKED` |
| A live injection attempt is flagged, treated as data and routed to a person | MET (live, 14 October) | On the deployed app: the deploy's smoke test sent the injection sample (score 2, runs 2, 2, 2, `injection_detected`, routed), and the `injection-burst` profile sent 9 injected answers and 3 clean twins. All 9 injected answers were flagged and routed, and none of the 3 clean ones was flagged. In the three groups whose clean answer was sent too, every injected answer scored the same as its clean twin. Azure's guardrail blocked none of them, as in decision S3-12 |
| The dashboard shows real data from test traffic and eval runs | MET (live, 14 October), portal view pending | The queries behind the first four tiles, which the workbook holds word for word (decision S6-2), returned the deployed app's data through the read-only CLI on 14 October: tile 1 as in the first row; tile 2, control-triggered review rate 11 of 45 (24.4%), inside the 25% band on a mix with a deliberate injection burst; tile 3, about 0.0047 GBP a score; tile 4, six eval runs, the newest the nightly run of 14 October (PASS). Neither alert query returns a breach. Tiles 5 and 6 were added the same day (decision P3-10), and their queries were run read-only against the real telemetry then; they have been in the live workbook since a deployment of `infra/observability.bicep` at 14:41 UTC on 14 October (decision S9-5). The agent has not seen the workbook rendered in the portal; that is the owner's screenshot `10-dashboard.png` |
| Git history shows intent, spec and plan | MET | The first commits add the three files, followed by eleven squash merges on 13 October, a twelfth, #16, late that evening, and the Phase 3 records from #17 onwards on 14 October |
| Pull requests with AI review findings and verifier verdicts | MET (live, 14 October) | They are comments on the pull requests. For example, `claude[bot]` posted "Review against REVIEW.md" on #4 (decision P3-4), and its review on #15 rates two findings Important. Decisions D13, D17, D18 and D25 corroborate |
| A decisions log that says who or what made each decision | MET | `intent/decisions.md`: every row has a Who value |
| The owner's approval before each deploy | MET (live, 14 October) | The first deploy, the `deploy` run for #16, waited on the `demo` environment and was approved by the owner; GitHub's approvals record for the run names the owner. Its provenance check ran before any change (decision P3-2). Of the older runs, the owner rejected the one queued by #10. The ones queued by #11 and #13 were cancelled by GitHub while they waited: the workflow's `deploy` concurrency group keeps one waiting run, and each ended within two seconds of the next merge queuing a newer one. None of them deployed |
| The walkthrough in eight minutes, with a five-minute cut and screenshots as a fallback | PENDING LIVE | `docs/walkthrough.md` has the script, the cut and a fallback per step. Eight screenshots are committed: five of GitHub pages and three of the live app's result cards. The three portal ones need the owner's sign-in, and the rehearsal is the owner's (plan H4). See `docs/screenshots/README.md` |

## Functional requirements

Every test named here passed in the run above, except the three start-up tests, which were added with the fix and pass in `uv run poe check` on this branch.

| FR | Criterion | Verdict | Evidence |
|---|---|---|---|
| FR-1 | Rubric loaded server side; the caller cannot supply or alter it | MET | `load_rubric` in `src/scorer/config.py`; `test_fr1_a_caller_cannot_supply_or_alter_a_rubric` |
| FR-1 | Unknown competency returns 400 | MET | `test_fr1_unknown_competency_is_a_400_with_no_model_call` |
| FR-1 | Under 30 or over 4000 characters returns 400, never truncated | MET | `test_fr1_answer_over_4000_characters_is_a_400_and_is_never_truncated` and its siblings |
| FR-1 | Under 30 characters after redaction returns 400 | MET | `test_fr1_answer_with_under_30_characters_left_after_redaction_is_a_400` |
| FR-1 | Missing or wrong demo token returns 401 | MET | `test_fr1_a_missing_or_wrong_demo_token_is_401_and_the_model_is_not_called` |
| FR-1 | Model failure returns 503 with no score | MET | `test_fr1_a_model_failure_is_503_with_no_score_of_any_kind`, `test_fr1_one_failed_run_of_three_is_503_and_never_a_partial_score` |
| FR-1 | Rate limit per address returns 429 | MET | `test_fr1_the_eleventh_request_in_a_minute_from_one_address_is_429`, `test_fr1_a_spoofed_first_hop_does_not_change_the_rate_limit_key` |
| FR-1 | A guardrail block is a 200 with no score, a flag and routing; never a 503 | MET | `test_fr1_a_guardrail_block_is_200_with_a_null_score_and_is_routed`. No real guardrail block has been observed (decision S3-12) |
| FR-2 | YAML with id, name, definition and five levels | MET | `Rubric` in `src/scorer/config.py`; `test_fr2_both_real_rubrics_load_with_five_levels` |
| FR-2 | Loader validates at start-up and fails fast | MET after the fix | Not met when verified. Now the app's start-up loads every rubric and the prompt: `test_fr2_the_server_refuses_to_start_over_a_broken_rubric` |
| FR-2 | Rubrics written before any code | MET | The rubrics pull request (#4) precedes the scorer core (#7) on `main`. One descriptor was reworded later (decision D24) |
| FR-3 | Changing a prompt file without changing its version fails a test | MET | `test_fr3_changing_a_prompt_file_without_changing_its_version_fails` |
| FR-3 | Active version from the registry; the variable overrides only when set | MET | `test_fr3_scorer_prompt_version_overrides_the_registry_when_set` |
| FR-3 | Prompt version and hash logged on every call | MET | `test_fr3_prompt_version_and_hash_are_logged_on_every_call_without_candidate_text` |
| FR-4 | Steps run in the stated order | MET | `test_fr4_steps_run_in_order_sanitise_then_redact_then_screen_then_model` |
| FR-4 | Sanitiser removes invisible characters and HTML and sets the flag | MET | `tests/unit/test_fr4_sanitise.py`. A soft hyphen is removed without the flag (decision S2-15) |
| FR-4 | Emails, phone numbers and URLs redacted | MET | `tests/unit/test_fr4_redact.py` |
| FR-4 | An injection is a flag; the answer is still scored as data | MET | `test_fr6_injected_answer_is_flagged_routed_and_still_scored_as_data` |
| FR-4 | The answer sits inside delimiters with the data-not-instructions rule | MET | `test_fr6_delimiter_in_the_answer_is_neutralised_and_cannot_close_the_real_one` |
| FR-4 | Three parallel calls, strict schema, no sampling settings | MET | `test_the_request_uses_a_strict_json_schema_and_no_sampling_settings` |
| FR-4 | Final score is the median; spread is max minus min | MET | `test_fr4_median_holds_for_every_combination_of_three_scores` |
| FR-4 | Rationale screen for protected terms and names | MET | `test_fr4_lexicon_covers_the_attribute_groups_named_in_the_spec` |
| FR-4 | Telemetry carries metadata only | MET | `test_the_score_span_carries_exactly_the_fixed_attribute_names`, `test_no_span_attribute_holds_candidate_text` |
| FR-5 | The schema rejects unknown fields and has no identity fields | MET | `test_fr5_schema_rejects_identity_fields`, `test_fr5_schema_rejects_any_unknown_field` |
| FR-5 | The model payload never contains `candidate_ref` | MET | `test_fr5_candidate_ref_never_reaches_the_model_payload` |
| FR-6 | Every injection case, paraphrases included, is flagged and routed | MET | `test_fr6_every_injected_dataset_row_is_flagged_and_routed`; 18 of 18 in the committed live reports |
| FR-6 | Injected and clean twins within tolerance | MET | Report `20261013T203628Z`: mean 0.000, largest pair difference 0 |
| FR-6 | The default guardrail is bound explicitly in Bicep | MET | `infra/modules/foundry.bicep`. The deployed state is not checkable from the repository |
| FR-7 | An exact quote is grounded | MET | `test_fr7_exact_quote_is_grounded` |
| FR-7 | A near-exact quote is grounded | MET | `test_fr7_near_exact_quote_is_grounded_at_ratio_0_9` |
| FR-7 | A paraphrased quote fails | MET | `test_fr7_paraphrased_quote_is_not_grounded` |
| FR-7 | An invented quote fails | MET | `test_fr7_invented_or_empty_quote_is_not_grounded` |
| FR-7 | Ungrounded quotes are removed and counted | MET | `test_fr7_ungrounded_quotes_are_removed_from_the_response_and_counted` |
| FR-8 | Review is required for each listed trigger | MET | `tests/unit/test_fr8_review_routing.py`, one test per trigger |
| FR-8 | `review_reasons` lists each trigger | MET | `test_fr8_every_trigger_is_listed_when_several_fire_at_once` |
| FR-8 | Never auto-rejects; always carries the notice | MET | `test_fr8_the_service_never_auto_rejects_and_always_carries_the_notice` |
| FR-9 | One static page with the picker, question, answer box, sample buttons and result card | MET | `test_fr9_the_page_has_every_part_of_the_journey`. Checked statically, not in a browser |
| FR-9 | Visible disclosure and a "Report a problem" link; nothing sent automatically | MET | `test_fr9_the_page_shows_the_ai_use_disclosure` |
| FR-9 | Demo token kept in session storage only | MET | `test_fr9_the_token_is_kept_in_session_storage_only` |
| FR-9 | No identifiers in the HTML | MET | `test_fr9_the_page_holds_no_identifier_shaped_strings` |
| FR-10 | `/healthz` says the process is up | MET | `test_fr10_healthz_says_the_process_is_up_and_needs_no_token` |
| FR-10 | `/readyz` checks config, rubrics and prompt with no model call | MET | `test_fr10_readyz_is_200_when_everything_loads_and_makes_no_model_call` |

## Recorded departures from the spec text that did not change a verdict

- A platform guardrail block sets `platform_guardrail` only, not `injection_detected` (decision S2-4). A blocked case still counts as flagged and routed.
- Grounding is stricter than the spec: word order must hold, and a very short quote is ungrounded even when it is an exact match (decision S2-13).
- The rate limit is checked before the token, so a wrong token over the limit gets 429 (decisions S3-4, F-3).
- A fifth 400 code, `question_too_long`, was added (decision F-5).

## What this check could not see

GitHub state (the ruleset, the `demo` reviewer, review comments, CodeQL, the waiting deploy run), Azure state (every deployed resource, the workbook as rendered, the alert email), and all live behaviour (the live URL, a real guardrail block, the page in a browser).

The Phase 3 re-check saw the GitHub state it cites, the deployed app's answers and its telemetry. It still did not see the workbook as rendered in the portal or a real guardrail block. A test alert reached the owner's email after the owner confirmed the address (decision P3-7). CodeQL default setup was switched on by the owner on 14 October (Python and GitHub Actions), and its first analysis passed.
