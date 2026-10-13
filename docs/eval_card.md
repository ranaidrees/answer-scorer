# Eval card

One page on what the offline evaluation of the answer scorer measures, what it found, and what that does and does not prove. Design: [the spec](../intent/spec.md), section 7. As of 13 October 2026, late evening.

## Purpose and the decision it informs

The eval informs one decision: **merge or block a change** to a prompt, a rubric, the scoring code or a dataset. A passing gate allows the merge and a failing gate blocks it. It is wired to run on every pull request that touches those paths, nightly against the pinned deployment, and on demand ([evals workflow](../.github/workflows/evals.yml)); the workflow on `main` has read its sign-in identifiers from secrets since pull request #13 merged, and `evals` is a required check on `main`, so the merge of a failing change is blocked. It informs no decision about any person: all data is synthetic and every output of the service is decision support.

## Datasets and label provenance

| File | Size | Content |
|---|---|---|
| [golden.jsonl](../evals/datasets/golden.jsonl) | 30 answers | 2 competencies x 5 levels x 3 answers, each with a target label. 20 `dev`, 10 `holdout` |
| [fairness_pairs.jsonl](../evals/datasets/fairness_pairs.jsonl) | 16 pairs | 8 identity pairs, 4 dialect pairs, 4 verbosity pairs. Only the cue under test differs inside a pair |
| [injection.jsonl](../evals/datasets/injection.jsonl) | 6 clean, 18 injected | Six attack types, each as a twin of a clean answer plus two paraphrases |
| [edge_cases.jsonl](../evals/datasets/edge_cases.jsonl) | 6 | Each row carries its expected behaviour |

- **Who wrote them.** Claude wrote every answer and every target label. Claude is a different model family from the scorer.
- **Audit.** A separate Claude agent then labelled all 30 golden answers blind, from the rubric and the answer only. Exact agreement before resolution was **30 of 30**, and a second independent reviewer agent also agreed on 30 of 30 ([label audit](../evals/label_audit.md)).
- **The caveat.** Both labellers are one model family applying an explicit level rule. Full agreement shows the labels are consistent. It does not show they are right, and it is a sign the golden set may be easier than real answers. **No person labelled or reviewed the answers.**
- **Holdout.** Holdout rows count in every metric and are not listed case by case in the Markdown report or the pull request comment (decision S4b-11).

## Inference settings and repetitions

- Model: gpt-5.4-mini, version 2026-03-17, deployment `scorer-mini`, Global Standard, no automatic upgrade ([Bicep](../infra/modules/foundry.bicep)).
- Call: Chat Completions with a strict JSON schema and an enum score, `reasoning_effort: "none"`, `max_completion_tokens` 600, no `temperature` or `top_p` because this model family does not accept them ([client](../src/scorer/model_client.py), [test](../tests/unit/test_foundry_client.py)).
- Prompt: `v1`, by hash in the [registry](../prompts/scorer/registry.yaml). It was **not tuned and never changed**: every figure on this page is the same prompt, except the four runs on the weakened prompt under "Stability proof".
- Repetitions: every answer is scored **3 times** in parallel; the score is the median and the spread is the largest minus the smallest. One full run is 92 inputs, of which 90 reach the model: about 270 model calls, 400,338 tokens in and about 58,500 out, about 0.43 GBP (priced as uncached, so an upper estimate).
- Order: items are shuffled with a seed that is printed in the report. Sampling variance cannot be switched off, so the gates use tolerances and the proof is repeated runs.
- Retries: when an input comes back with no score at all, the runner tries it again up to three times with waits and lists the retried ids in the report (decision S4c-6). One run makes at most three such extra attempts in all; needing a fourth stops the run with no report, because a rate of unusable replies is itself a finding (decision S4c-9). A score is never retried for a better one.

## Metrics, with n

Thresholds are in [thresholds.yaml](../evals/thresholds.yaml) at the spec's values; none was changed. "Baseline" is the first live run, in CI on pull request [#9](https://github.com/ranaidrees/answer-scorer/pull/9), at an earlier commit. "Proof 1 to 3" are the three consecutive local runs on one commit that make up the stability proof: `20261013T202107Z`, `20261013T202848Z` and `20261013T203628Z`. There are no confidence intervals: 30 answers and 16 pairs are too few for a reliable interval.

| Metric | n | Gate | Baseline | Proof 1 | Proof 2 | Proof 3 |
|---|---|---|---|---|---|---|
| **Gate result** | | every row below | **PASS** | **PASS** | **PASS** | **PASS** |
| Quadratic weighted kappa against labels | 30 | at least 0.70 | 0.926 | 0.926 | 0.947 | 0.926 |
| Within-1 agreement | 30 | at least 90% (27 of 30) | 29 of 30 | 29 of 30 | 29 of 30 | 29 of 30 |
| Exact agreement | 30 | at least 55% | 25 of 30 | 25 of 30 | 27 of 30 | 25 of 30 |
| Identity pairs: mean absolute difference | 8 | at most 0.25 | 0.000 | **0.250** | 0.000 | 0.125 |
| Identity pairs: largest pair difference | 8 | at most 1 | 0 | 1 | 0 | 1 |
| Dialect and verbosity pairs: mean absolute difference | 8 | at most 0.25 | 0.000 | 0.000 | 0.000 | 0.125 |
| Dialect and verbosity pairs: largest pair difference | 8 | at most 1 | 0 | 0 | 0 | 1 |
| Noise floor: answers whose three runs disagree | 90 | reported, not gated | 14 of 90 (15.6%) | 16 of 90 (17.8%) | 18 of 90 (20.0%) | 18 of 90 (20.0%) |
| Fairness flip rate: pairs whose medians differ | 16 | reported, not gated | 0 of 16 | 2 of 16 (12.5%) | 0 of 16 | 2 of 16 (12.5%) |
| Injection cases flagged and routed | 18 | 100% | 18 of 18 | 18 of 18 | 18 of 18 | 18 of 18 |
| Injection pairs: mean (injected minus clean), and largest difference | 18 | at most 0.25, at most 1 | 0.000 mean | within the gate | within the gate | within the gate |
| Edge cases with the expected behaviour | 6 | 100% | 6 of 6 | 6 of 6 | 6 of 6 | 6 of 6 |
| Ungrounded quote rate | quotes checked | at most 2% | 0 of 338 | 0 of 341 | 0 of 332 | 1 of 327 (0.3%) |
| Control-triggered review rate, golden set | 30 | at most 15% | 1 of 30 | 0 of 30 | 1 of 30 | 2 of 30 |

"Within the gate" means the run passed, so the value met its threshold, but the exact figure is not recorded on this page. Each of these four runs has a report, a Markdown and a JSON file named by its run id, under [evals/reports/](../evals/reports/).

One golden `dev` answer is scored two levels under its label in most runs, and every report counts it as a defect; that is the one answer missing from within-1 agreement. The reports also count one defect on a `holdout` row, which is not inspected case by case.

**A ninth and a tenth run, after the proof.** The first CI gate run on pull request [#13](https://github.com/ranaidrees/answer-scorer/pull/13), at commit `01cb892`, also returned PASS, with no input tried again. Kappa 0.865; exact agreement 25 of 30; within-1 agreement 27 of 30, **exactly on its 90% limit**; identity pairs mean absolute difference 0.125; dialect and verbosity pairs mean absolute difference 0.250, **exactly on its limit**; injection 18 of 18; edge cases 6 of 6; ungrounded quotes 0 of 344; control-triggered review rate 3 of 30. Two gated metrics sat on their limits in that run, so it passed with nothing to spare on either. Its noise floor and flip rate are not recorded on this page. In that run three answers, not one, were more than one level from their labels. The second CI gate run on the same pull request, at commit `814fc6d`, is the tenth: PASS, kappa 0.874, within-1 agreement 28 of 30, nothing breached and no input tried again. Its other figures are not recorded on this page. The reports of these two runs are artifacts of their workflow runs, not files under `evals/reports/`.

## Noise floor and flip rate

The same answer, scored three times with the same prompt, did not always get the same score: the three runs disagreed on 14 to 18 of 90 answers in these four runs. That is the noise floor. A fairness pair "flips" when the two medians differ; that happened on 0, 2, 0 and 2 of 16 pairs, under the noise floor each time, and no pair differed by more than 1. Across the first eight completed live runs on this prompt there were 11 flips in 128 pair-runs (8.6%); the flip counts of the ninth and the tenth are not recorded on this page. So these runs give no sign that an identity, dialect or length cue moves scores more than chance does. With 16 pairs they cannot show that no such effect exists.

**The pair gates have little headroom.** In two of the first eight runs the identity mean sat exactly on its 0.25 limit: 2 of 8 pairs one level apart (decision S4c-12). One more flipped pair would have breached the gate. In the ninth run the dialect and verbosity mean sat exactly on the same limit. The build's lead session estimates that roughly 1 full run in 20 would breach a pair gate from model noise alone, with no change to the system. That is an estimate from eight runs, not a measured rate. A nightly failure on a pair gate alone should therefore be run once more before it is read as a regression, and a production gate would use more pairs.

## Stability proof

A gate that flakes gets ignored, so the gate must give the same answer three times running: three passes on the accepted prompt and three failures on the deliberately weakened prompt (`prompts/scorer/v0-weak.md`, a warm coaching tone that paraphrases evidence and drops the delimiter rule).

**On the accepted prompt it took three attempts.** The prompt, the thresholds, the datasets and the rubrics did not change between them; two faults were fixed in the code.

| Attempt | Run | Gate | Kappa | Within-1 | Exact | What happened |
|---|---|---|---|---|---|---|
| Baseline | CI, pull request #9 | PASS | 0.926 | 29 of 30 | 25 of 30 | First live run, earlier commit |
| 1 | `20261013T194024Z` | PASS | 0.914 | 29 of 30 | 24 of 30 | |
| 1 | `20261013T194814Z` | PASS | 0.926 | 29 of 30 | 25 of 30 | |
| 1 | `20261013T195557Z` | **FAIL** | 0.943 | 30 of 30 | 24 of 30 | Edge cases 5 of 6 |
| 2 | `20261013T200813Z` | PASS | 0.914 | 29 of 30 | 24 of 30 | |
| 2 | no report | stopped | | | | Stopped at input 13 of 92: the model was unavailable on one input |
| 3 | `20261013T202107Z` | PASS | 0.926 | 29 of 30 | 25 of 30 | Proof 1 |
| 3 | `20261013T202848Z` | PASS | 0.947 | 29 of 30 | 27 of 30 | Proof 2 |
| 3 | `20261013T203628Z` | PASS | 0.926 | 29 of 30 | 25 of 30 | Proof 3 |
| After the proof | CI, pull request #13, commit `01cb892` | PASS | 0.865 | 27 of 30 | 25 of 30 | Ninth run. Within-1 agreement and the dialect and verbosity mean both exactly on their limits |
| After the proof | CI, pull request #13, commit `814fc6d` | PASS | 0.874 | 28 of 30 | not recorded here | Tenth run. Nothing breached |

- **Attempt 1: pass, pass, fail.** The failing case was the `dev` edge case whose answer only repeats the question. The model gave runs of 2, 1, 2 and did not mark it off topic, where the expected behaviour is off topic or a score of 1. In the two earlier runs the same case scored 1. The gate was right to fail: the behaviour depended on model noise.
- **The fix was a control, not a looser check** (decision S4c-3). A deterministic question-echo check, `src/scorer/echo.py`: when fewer than 35% of an answer's words are words the question does not contain, the answer is flagged off topic and routed, whatever the model says. On `dev` data the restated question sits at 19% and every real answer is above 60%.
- **Attempt 2: one pass, then a stopped run.** The model was unavailable on one input, so the runner stopped with no report and no invented score. That is not a gate result, but in CI it would have failed the check. The fix is the bounded retry described under "Inference settings" (decision S4c-6).
- **Attempt 3: three consecutive passes on one commit, after the last code change.** Only these three count as the proof (decision S4c-7). The baseline in CI is a fourth passing run on the same prompt at an earlier commit, and the two CI gate runs on pull request #13 are later ones. Overall the accepted prompt passed nine of its ten completed live runs; the one failure is the third run of attempt 1.

**On the weakened prompt: three full local runs in a row on one commit, and the gate failed all three** (decision S4c-11).

A fourth full run on the weakened prompt, in CI on pull request [#15](https://github.com/ranaidrees/answer-scorer/pull/15), failed too; it is not one of the three that make up the proof.

| Run | Prompt | Where | Gate | Kappa | Ungrounded quotes | Control-triggered review rate | Gated metrics breached |
|---|---|---|---|---|---|---|---|
| Weak 1, `20261013T204457Z` | `v0-weak` | local | **FAIL** | 0.903 | 333 of 333 | 30 of 30 | Ungrounded quote rate; control-triggered review rate |
| Weak 2, `20261013T205241Z` | `v0-weak` | local | **FAIL** | 0.855 | 332 of 332 | 30 of 30 | Those two, and the injection pairs mean (injected minus clean): 0.278 against a limit of 0.25 |
| Weak 3, `20261013T210024Z` | `v0-weak` | local | **FAIL** | 0.867 | 333 of 333 | 30 of 30 | Those two, the injection pairs mean (0.278), and the largest injection pair difference: 2 against a limit of 1 |
| Weak 4, commit `15176ab` | `v0-weak` | CI, pull request #15 | **FAIL** | 0.875 | 334 of 334 | 30 of 30 | Those two, and edge cases with the expected behaviour: 5 of 6 |

The weakened prompt still met the agreement gates in all four runs, with kappa above 0.70 each time. Agreement with the labels alone would have let it through; it is the grounding and review-rate gates that catch it, every time. The injection gates caught it in two runs of the four and the edge cases in one, not in all. The reports of the three local runs are on the `demo/weak-prompt` branch only, which is never merged, so they are not under `evals/reports/` on `main`; the report of the CI run is an artifact of its workflow run. On pull request #15 the `ci` check passes, the required `evals` check fails and GitHub reports the merge as blocked.

## Limitations

- **Synthetic, and one family.** The same model family wrote the answers, labelled them and audited the labels. Real answers are messier and real raters disagree.
- **Small.** 30 answers, 16 pairs, 18 injected answers, 6 edge cases. One answer moves agreement by more than three points. No intervals are given.
- **An easy pass on agreement.** The prompt met the agreement gates without tuning and the audit agreed on every label. Both point to a golden set that may be too easy to separate a good prompt from an adequate one: the weakened prompt met the agreement gates too. The margin is not always wide, though: in the ninth run within-1 agreement sat exactly on its limit.
- **The gate is not flake-free.** It took three attempts to get three consecutive passes, one edge case needed a deterministic check because the model alone was inconsistent on it, and the pair gates can be breached by noise (see above). Three passes show the gate is stable enough to use, not that it will never need a second run.
- **Variance remains.** About 15% to 20% of answers had runs that disagreed. In three live smoke runs the same strong sample scored 5 twice and 3 once.
- **One known miss.** One golden `dev` answer is scored two levels under its label in most runs. It is reported as it is; the prompt was not tuned to remove it.
- **Injection coverage.** 18 attacks in English, written by the same agent family that wrote the screen. Our own screen flags all 18, which an offline run shows without the model; Azure's guardrail did not block the one sample sent live three times (decision S3-12). The guardrail-block path is proven by unit tests only.
- **Fairness coverage.** Counterfactual text pairs test whether a cue in the text moves the score. They are not an adverse impact analysis, which needs consented demographic data from real use.
- **Settings in reports.** A report prints the client's and the pipeline's own constants for the inference settings, and a test checks that the printed values equal them (decision F-13). They are constants in the code, not values read back from the service.

## Validity statement

**Reliability is not validity.** These results show that the scorer agrees with a fixed set of AI-written labels, gives stable scores within a stated tolerance, resists the listed manipulation attempts and sends what it should to a person. They do not show that a score measures the competency, predicts anything about a person, or is fair in use. Showing that needs trained raters, occupational psychologists and real, consented data. Nothing here supports using the scorer for real hiring decisions.
