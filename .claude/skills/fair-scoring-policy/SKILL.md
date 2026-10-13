---
name: fair-scoring-policy
description: The fair-scoring policy for this project. Use when writing or reviewing scorer prompts, rubrics, scoring code, eval datasets, UI wording or docs about how answers are scored.
---

# Fair-scoring policy

Five rules. Each one is enforced by code or a test; this file is the plain statement of them.

1. **Identity-blind.** The scorer never receives a name, gender, age, ethnicity, nationality, photo or any other protected attribute. The request schema rejects unknown fields. `candidate_ref` is an opaque id and never reaches the model. Prompts and rationales refer to "the candidate", never a name or pronoun.
2. **Rubric-only scoring.** A score reflects only the observable behaviours in the rubric's level descriptors. Writing style, length, dialect, spelling variety and life details are not evidence. Rubrics are loaded server side; a caller can never supply or alter one. Rubrics are generic: no proprietary frameworks, product names or branding.
3. **Verbatim evidence.** Every evidence quote is copied word for word from the answer and checked deterministically. A paraphrase is not evidence. An ungrounded quote is removed, counted and routed to a human.
4. **Review routing.** A human reviews the answer whenever a control trips: injection or hidden text detected, a platform guardrail block, a spread of 2 or more across the three runs, any ungrounded quote, an off-topic answer, a protected term in the rationale, or a score of 1 or 2. The service never rejects a candidate by itself, and never invents or defaults a score when the model fails.
5. **Decision-support wording.** Outputs are described as decision support. Every response carries the notice "Decision support only. A trained person makes the decision." Never write "pass", "fail", "reject", "hire" or "recommend" about a candidate in prompts, UI text or docs.

## When reviewing a change

- A new input field, log line or span attribute: could it carry identity or candidate text? If so, it breaks rule 1 or the privacy rules in `CLAUDE.md`.
- A prompt change: does it still ask for verbatim quotes, keep the answer inside its delimiters as data, and say "the candidate"?
- A dataset change: synthetic only, with `label_source` and a one-line reason on every row.
- Wording: reliability is not validity. Never claim the scoring is valid; that needs trained raters and occupational psychologists.
