# Label audit: golden set

Every golden answer was labelled twice, by two separate Claude agents:

- **Generator:** the S4a slice agent, which wrote the answers and their target labels.
- **Auditor:** a separate agent running the `label-auditor` instructions. It was given only the two rubrics and a shuffled copy of the 30 answers under neutral ids (`a01` to `a30`, shuffle seed 20261013), in a checkout that held no labelled dataset. It never saw the generator's label, reason, split or id.

Both labellers are the same model family as each other, and a different family from the scorer. No human labelled or reviewed these answers. The audit shows that the labels follow the rubric's level rule consistently; it does not show that the labels are valid. Validity needs trained raters and occupational psychologists.

## Result

- Exact agreement before resolution: **30 of 30 (100%)**.
- Off by 1: 0. Off by 2 or more: 0.
- Audit rule (spec section 7): same label, kept; off by 1, the lead decides with a one-line reason; off by 2 or more, the answer is rewritten and audited again.
- No disagreement, so no label was changed, no answer was rewritten and the lead made no off-by-1 decision.

Full agreement on 30 answers is weaker evidence than it looks: each rubric carries an explicit level rule, the generator wrote each answer to meet that rule, and the auditor applied the same rule. It says the rule is clear enough to be applied the same way twice. It is also a sign that the golden set may be easier than real answers, which the eval card states as a limitation.

## Every answer

| Golden id | Audit id | Split | Generator | Auditor | Outcome | Auditor's reason |
|---|---|---|---|---|---|---|
| `g-ps-1-a` | `a24` | dev | 1 | 1 | kept | List of qualities and general statements; no specific situation |
| `g-ps-1-b` | `a08` | holdout | 1 | 1 | kept | Describes only what managers and the engineer did; no action of their own |
| `g-ps-1-c` | `a02` | dev | 1 | 1 | kept | No action of their own; says nothing could be done at their end and the problem was never solved |
| `g-ps-2-a` | `a27` | dev | 2 | 2 | kept | Own action (switching off and on) was the first idea, cause unknown, no alternative considered, result vague |
| `g-ps-2-b` | `a30` | dev | 2 | 2 | kept | Own action (rebuilt the workbook) without gathering information on or stating a cause; no alternative weighed; result only assumed, so L3 not met |
| `g-ps-2-c` | `a20` | holdout | 2 | 2 | kept | Own action (swapped batteries) was the first idea with no reasoning about cause, alternative not explored, result unchecked and vague |
| `g-ps-3-a` | `a13` | holdout | 3 | 3 | kept | Gathered incident forms, night logs and carers' accounts, stated cause (getting up in the dark) linked to the motion light and bed move, result stated; no causes tested in turn or options compared, so L4 missed |
| `g-ps-3-b` | `a26` | dev | 3 | 3 | kept | Gathered till rolls and staff walk-throughs, stated cause (moved refund button) linked to the retraining, result stated; no causes tested in turn or options compared, so L4 missed |
| `g-ps-3-c` | `a03` | dev | 3 | 3 | kept | Gathered reports and server logs, stated cause (clock six minutes fast) linked to the fix, result stated; no causes tested one at a time and no options compared, so L4 missed |
| `g-ps-4-a` | `a06` | dev | 4 | 4 | kept | Broke the job into three stages and checked each, compared two options with trade-off, checked via continued sampling and returns figure; no risk/effect-on-others criterion and no recurrence step, so L5 missed |
| `g-ps-4-b` | `a15` | holdout | 4 | 4 | kept | Tested likely causes one at a time, compared paper vs lunchtime computer room with trade-off, checked by comparing hand-in numbers; no evidence-based ruling out, no risk/others criterion, no recurrence step, so L5 missed |
| `g-ps-4-c` | `a10` | dev | 4 | 4 | kept | Listed three possible causes and went through them one at a time, compared sealant vs repointing with trade-off, checked by hose test and moisture readings; no evidence stated for ruling out causes, no risk/others criterion, no recurrence step, so L5 missed |
| `g-ps-5-a` | `a04` | dev | 5 | 5 | kept | Ruled out door seal with evidence (paper test, logger times); criteria named incl. customer food-safety risk; confirmed on logger for seven nights; recurrence step (settings taped up, opening-list check) |
| `g-ps-5-b` | `a09` | dev | 5 | 5 | kept | Ruled out network and disk with stated evidence; criteria named incl. risk of holding up finance team; confirmed by re-running largest files and two month ends; recurrence step (size alert, test sample) |
| `g-ps-5-c` | `a21` | holdout | 5 | 5 | kept | Ruled out battery with evidence (12.6 volts, stuck with engine running); criteria named incl. risk to a passenger and effect on users; confirmed by ten runs each frosty morning for a week; recurrence step (fluid check on service sheet) |
| `g-tw-1-a` | `a16` | dev | 1 | 1 | kept | General statements and a list of qualities with no specific situation |
| `g-tw-1-b` | `a19` | dev | 1 | 1 | kept | Describes only what the two leads and the depot manager did; no action of their own |
| `g-tw-1-c` | `a17` | holdout | 1 | 1 | kept | General views on teamwork and hypotheticals; no specific situation or action of their own |
| `g-tw-2-a` | `a23` | holdout | 2 | 2 | kept | Describes own module work only; mentions team tension but takes no step on it and no action directed at another person; team result vague |
| `g-tw-2-b` | `a01` | dev | 2 | 2 | kept | Own actions in a relevant example (kept to own rounds and notes) but no cooperative action and no step to resolve the conflict, so L3 not met |
| `g-tw-2-c` | `a05` | dev | 2 | 2 | kept | Describes own part (tinned goods table) only; no action directed at another person, no step on the difficulty, team result vague |
| `g-tw-3-a` | `a28` | dev | 3 | 3 | kept | Specific example with own role, cooperative action (shared queue information, proposed turns and took the first), step on the disagreement with result stated; did not ask for views before acting and no lasting practice, so L4 and L5 missed |
| `g-tw-3-b` | `a18` | holdout | 3 | 3 | kept | Specific example with own role clear, cooperative actions (shared planning sheet, asked colleague to check room plan), step on the double booking with result stated; no change of approach after others' views, no named concern, no support/credit, so L4 missed |
| `g-tw-3-c` | `a11` | dev | 3 | 3 | kept | Specific example with own role, cooperative action (shared booked lift times, chalked them up), step on the disagreement with result stated; did not ask others' views or name a concern, so L4 missed |
| `g-tw-4-a` | `a12` | dev | 4 | 4 | kept | Asked views before acting and changed plan, named the waiter's concern, supported the commis and gave credit, stated what changed for the team; no each-side wants/agreement and no lasting practice, so L5 missed |
| `g-tw-4-b` | `a25` | dev | 4 | 4 | kept | Asked others before acting and changed the split, named colleague's concern, took half her old cases and gave her credit, stated what changed for the team; no each-side wants/agreement and no lasting practice, so L5 missed |
| `g-tw-4-c` | `a14` | holdout | 4 | 4 | kept | Asked tester and support lead before acting and dropped own plan, named tester's concern, supported newer developer and shared credit, stated what changed; no explicit agreement by those involved and no practice kept afterwards, so L5 missed |
| `g-tw-5-a` | `a07` | holdout | 5 | 5 | kept | States what each shift wanted, a step for each, both agreed at team meeting; sheet still in use a year on; specific result (queries from about five a week to one) |
| `g-tw-5-b` | `a22` | dev | 5 | 5 | kept | States what pickers and loaders each wanted, a step for each, both groups signed up at the briefing; lanes still in use; specific result (all fourteen lorries on time every day) |
| `g-tw-5-c` | `a29` | dev | 5 | 5 | kept | States what cooks and drivers each wanted, a step for each, everyone agreed at the briefing; two waves written into the rota and used every Friday since; specific result (all hundred and twenty meals out by six) |
