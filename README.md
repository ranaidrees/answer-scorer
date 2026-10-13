# AI answer scorer with a trust harness

A small reference implementation of governed AI output for a high-stakes decision: it scores a written interview answer against a competency rubric, and wraps that score in input guards, output guards, offline evals and online evals.

**Status:** being built. This page is a stub until the demo pack is written.

## Disclaimer

- **Synthetic data only.** Every answer, label and name in this repository is invented.
- **A reference implementation.** It shows how the controls work. It does not show that the scoring is valid; validity needs trained raters and occupational psychologists.
- **Not for use in real hiring decisions.**

## Where to look

- `intent/intent.md`: what this is for.
- `intent/spec.md`: what it does and how it is checked.
- `intent/plan.md`: how it is being built, and the current status.
- `intent/decisions.md`: every decision, with who or what made it.
- `RUNBOOK.md` and `instructions-for-claude-code.md`: the prompts that drove the build.

## Licence

MIT. See `LICENSE`.
