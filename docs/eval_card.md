# Eval card

One page on what the offline evaluation of the answer scorer measures, what it found, and what that does and does not prove. Design: [the spec](../intent/spec.md), section 7. As of 13 October 2026; figures still to come are marked PENDING.

## Purpose and the decision it informs

The eval informs one decision: **merge or block a change** to a prompt, a rubric, the scoring code or a dataset. A passing gate allows the merge and a failing gate blocks it. It is wired to run on every pull request that touches those paths, nightly against the pinned deployment, and on demand ([evals workflow](../.github/workflows/evals.yml)); the nightly schedule takes effect once the workflow is on `main`. It informs no decision about any person: all data is synthetic and every output of the service is decision support.

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
- Prompt: `v1`, by hash in the [registry](../prompts/scorer/registry.yaml). It was **not tuned**: it met the gate on its first live run.
- Repetitions: every answer is scored **3 times** in parallel; the score is the median and the spread is the largest minus the smallest. One full run is 92 inputs, of which 90 reach the model: about 270 model calls.
- Order: items are shuffled with a seed that is printed in the report. Sampling variance cannot be switched off, so the gates use tolerances and the proof is repeated runs.

## Metrics, with n

Thresholds are in [thresholds.yaml](../evals/thresholds.yaml) at the spec's values. "Baseline" is the first live run, in CI on pull request [#9](https://github.com/ranaidrees/answer-scorer/pull/9). "Stability 1" is the first of three local runs on the same prompt. There are no confidence intervals: 30 answers and 16 pairs are too few for a reliable interval.

| Metric | n | Gate | Baseline | Stability 1 |
|---|---|---|---|---|
| **Gate result** | | every row below | **PASS** | **PASS** |
| Quadratic weighted kappa against labels | 30 | at least 0.70 | 0.926 | 0.914 |
| Within-1 agreement | 30 | at least 90% | 29 of 30 | 29 of 30 |
| Exact agreement | 30 | at least 55% | 25 of 30 | 24 of 30 |
| Identity pairs: mean absolute difference | 8 | at most 0.25 | 0.000 | 0.125 |
| Identity pairs: largest pair difference | 8 | at most 1 | 0 | 1 |
| Dialect and verbosity pairs: mean absolute difference | 8 | at most 0.25 | 0.000 | 0.000 |
| Dialect and verbosity pairs: largest pair difference | 8 | at most 1 | 0 | 0 |
| Noise floor: answers whose three runs disagree | 90 | reported, not gated | 14 of 90 (15.6%) | 13 of 90 (14.4%) |
| Fairness flip rate: pairs whose medians differ | 16 | reported, not gated | 0 of 16 | 1 of 16 (6.2%) |
| Injection cases flagged and routed | 18 | 100% | 18 of 18 | 18 of 18 |
| Injection pairs: mean (injected minus clean) | 18 | at most 0.25 | 0.000 | within the gate |
| Injection pairs: largest pair difference | 18 | at most 1 | within the gate | within the gate |
| Edge cases with the expected behaviour | 6 | 100% | 6 of 6 | 6 of 6 |
| Ungrounded quote rate | 338 quotes | at most 2% | 0 of 338 | 0 of 338 |
| Control-triggered review rate, golden set | 30 | at most 15% | 1 of 30 | 2 of 30 |

"Within the gate" means the run passed, so the value met its threshold, but the exact figure is not recorded on this page. In stability run 1 the rationale screen also flagged a protected term on 1 of 90 answers. The baseline run cost about 0.43 GBP, an estimate from published prices.

## Noise floor and flip rate

The same answer, scored three times with the same prompt, did not always get the same score: the three runs disagreed on 14 of 90 answers in the baseline and 13 of 90 in stability run 1. That is the noise floor. A fairness pair "flips" when the two medians differ; that happened on 0 of 16 pairs and then 1 of 16, both under the noise floor, and the one pair that moved differed by 1. So these runs give no sign that an identity, dialect or length cue moves scores more than chance does. With 16 pairs they cannot show that no such effect exists.

## Stability proof

A gate that flakes gets ignored, so the gate must give the same answer three times running: three passes on the accepted prompt and three failures on the deliberately weakened prompt (`prompts/scorer/v0-weak.md`, a warm coaching tone that paraphrases evidence and drops the delimiter rule).

| Run | Prompt | Where | Gate result and figures |
|---|---|---|---|
| Stability 1 | `v1` | local | PASS; the column above |
| Stability 2 | `v1` | local | [[PENDING: stability run 2 gate result and metrics]] |
| Stability 3 | `v1` | local | [[PENDING: stability run 3 gate result and metrics]] |
| Weak 1 | `v0-weak` | local | [[PENDING: weak-prompt run 1 gate result and breached metrics]] |
| Weak 2 | `v0-weak` | local | [[PENDING: weak-prompt run 2 gate result and breached metrics]] |
| Weak 3 | `v0-weak` | local | [[PENDING: weak-prompt run 3 gate result and breached metrics]] |

Reports and the decision that records the six results: [[PENDING: report paths under evals/reports/ and the decision ID for the stability proof]]

## Limitations

- **Synthetic, and one family.** The same model family wrote the answers, labelled them and audited the labels. Real answers are messier and real raters disagree.
- **Small.** 30 answers, 16 pairs, 18 injected answers. One answer moves agreement by more than three points. No intervals are given.
- **An easy pass.** The prompt met the gate without tuning and the audit agreed on every label. Both point to a golden set that may be too easy to separate a good prompt from an adequate one.
- **Variance remains.** About 15% of answers had runs that disagreed. In three live smoke runs the same strong sample scored 5 twice and 3 once.
- **Injection coverage.** 18 attacks in English, written by the same agent family that wrote the screen. Our own screen flags all 18, which an offline run shows without the model; Azure's guardrail did not block the one sample sent live three times (decision S3-12). The guardrail-block path is proven by unit tests only.
- **Fairness coverage.** Counterfactual text pairs test whether a cue in the text moves the score. They are not an adverse impact analysis, which needs consented demographic data from real use.
- **Settings in reports.** A report prints the spec's inference settings rather than values read back from the live client (decision S4b-11); the client's own test checks the values it sends.

## Validity statement

**Reliability is not validity.** These results show that the scorer agrees with a fixed set of AI-written labels, gives stable scores within a stated tolerance, resists the listed manipulation attempts and sends what it should to a person. They do not show that a score measures the competency, predicts anything about a person, or is fair in use. Showing that needs trained raters, occupational psychologists and real, consented data. Nothing here supports using the scorer for real hiring decisions.
