# Intent: delivery evidence dashboard (S9)

- **Author:** the owner asked for it on 14 October 2026, after the features stop, for the walkthrough.
- **Stage:** 1 of 3 for this slice. Next artifact: `spec.md` in this folder.

## Problem

The operational dashboard shows how the live scorer behaves. Nothing in Azure shows how the scorer was delivered: the gates it passed before production, what happened at and after each deploy, and where the agent worked and the owner decided. That story is spread across GitHub, the repository and Application Insights, and it takes several tabs to tell.

## Outcome

One Azure Workbook, **Answer scorer: delivery evidence**, with four tabs. The first was added at the owner's request after the first three were built, for the CEO and CTO (decision S9-4):

0. **Trust scorecard:** one trust score and a status, a score for each of five aspects (input guards, output guards, offline evaluation, online evaluation, golden dataset quality), the confidence of each live response as the agreement of its three runs, every check behind the score with its target and actual value, and a plain statement that validity against trained raters is not established.
1. **Before production:** the gates every change passed (tests, `ci`, the eval gate and its stability proof, supply-chain controls), with build and test time per `ci` run as a chart.
2. **In production:** every deploy and its approval, provenance check and smoke test, then the live service against its SLOs.
3. **AI-native SDLC:** the stages, the artifact each one committed and the gate that decided, with a few figures on who did the work and who decided.

Every figure links to the page or file it came from. Each tab says what its figures do not prove.

## Constraints

- Lean: a few figures per tab, chosen for the walkthrough. Detail stays in GitHub and the repository, one click away.
- Nothing that is not already public: no security alert details, no identifiers, no email addresses, no personal detail beyond the public GitHub handle in links.
- No new paid model runs, no resource with a fixed charge, no change to the running app.
- The owner applies the deployment once; everything else is done by the agent.
- Done before the freeze, 18:00 on 14 October 2026.

## How we will know it worked

The owner opens the workbook in the portal and walks the three tabs in under two minutes, and every figure on them can be traced with one click.
