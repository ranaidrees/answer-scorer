"""FR-4 step 9: the rationale screen for protected terms and personal names.

All names and answers here are synthetic.
"""

from __future__ import annotations

import pytest

from scorer.rationale_screen import (
    NOT_PERSONAL_NAMES,
    PROTECTED_TERMS,
    find_names,
    find_protected_terms,
    screen_rationale,
)
from tests.unit.samples import TEAMWORK_ANSWER

CLEAN_RATIONALES = [
    "The candidate gives a specific example with a clear role and describes asking for other "
    "views before acting. The candidate names the concern of each colleague and states the "
    "result with a specific detail. All level 4 descriptors are met.",
    "The candidate describes a problem and an action, but gives no reasoning about the cause "
    "and does not check the result. Level 3 is not met, so the level rule gives 2.",
    "The answer does not address the question and describes no action of the candidate's own.",
]

ANSWER_WITH_NAMES = (
    "Our team was split over a release date. My colleague Priya wanted more testing, and "
    "Tomasz wanted to ship. Tomasz had promised the customer a date. I asked Priya and Tomasz "
    "to list their concerns, and we agreed a smaller release. Initially nobody was happy, but "
    "on Monday we shipped on time and Dr Okafor thanked the team."
)


def test_fr4_lexicon_covers_the_attribute_groups_named_in_the_spec():
    assert {"gender", "age", "ethnicity", "nationality", "religion", "disability"} <= set(
        PROTECTED_TERMS
    )
    assert "pregnancy_and_family" in PROTECTED_TERMS
    for terms in PROTECTED_TERMS.values():
        assert terms and all(term == term.lower() for term in terms)


@pytest.mark.parametrize("rationale", CLEAN_RATIONALES)
def test_fr4_rationale_tied_to_the_rubric_is_not_flagged(rationale):
    result = screen_rationale(rationale, TEAMWORK_ANSWER)
    assert result.flagged is False
    assert result.terms == () and result.names == ()


@pytest.mark.parametrize(
    ("rationale", "term"),
    [
        ("She describes asking for other views before acting.", "she"),
        ("The candidate explained his plan to the team.", "his"),
        ("The candidate, a woman in a mostly male team, describes a clear role.", "woman"),
        ("Despite the candidate's age, the example is specific.", "age"),
        ("The candidate is a young graduate with a clear example.", "young"),
        ("The candidate is 52 years old and describes a clear role.", "years old"),
        ("The candidate's ethnicity is not relevant but is mentioned.", "ethnicity"),
        ("The candidate appears to be a non-native speaker.", "non-native"),
        ("The candidate, who is Nigerian, describes a clear role.", "nigerian"),
        ("The candidate mentions attending a mosque with a colleague.", "mosque"),
        ("The candidate's religion shaped the example.", "religion"),
        ("The candidate describes managing a disability at work.", "disability"),
        ("The candidate uses a wheelchair and describes a clear role.", "wheelchair"),
        ("The candidate was pregnant during the project.", "pregnant"),
        ("As a mother of two, the candidate describes sharing work.", "mother"),
        ("The candidate returned from maternity leave and led the plan.", "maternity"),
        ("The candidate's husband is mentioned in the example.", "husband"),
        ("The candidate describes being gay in a small team.", "gay"),
        ("THE CANDIDATE'S GENDER IS UNCLEAR.", "gender"),
    ],
)
def test_fr4_rationale_mentioning_a_protected_attribute_is_flagged(rationale, term):
    result = screen_rationale(rationale, TEAMWORK_ANSWER)
    assert result.flagged is True
    assert term in result.terms


@pytest.mark.parametrize(
    "rationale",
    [
        "The candidate managed the stage plan and set a threshold for escalation.",
        "The candidate sent a message to the manager and engaged the whole team.",
        "The candidate saved forty man-hours and replaced an old-fashioned process.",
        "The candidate disabled the faulty alert and checked a foreign key constraint.",
        "The candidate shared the other view with them, then gathered the history of the fault.",
        "The candidate kept the agenda short, and the percentage of late tickets fell.",
        "The candidate describes a race against a deadline and a blind spot in the old system.",
        "The candidate handled a senior stakeholder and a junior colleague's concern.",
        "The candidate checked the cache, the average load and the storage usage.",
        "The candidate helped the team manage change, and encouraged a colleague to speak.",
    ],
)
def test_fr4_rationale_screen_avoids_obvious_false_positives(rationale):
    assert find_protected_terms(rationale) == ()
    assert screen_rationale(rationale, TEAMWORK_ANSWER).flagged is False


def test_fr4_rubric_language_and_fixed_response_text_never_trip_the_screen(settings):
    """A rationale tied to the rubric reuses its words, so those words must be safe."""
    from scorer.config import load_all_rubrics
    from scorer.pipeline import GUARDRAIL_RATIONALE
    from scorer.schemas import NOTICE

    texts = [GUARDRAIL_RATIONALE, NOTICE]
    for rubric in load_all_rubrics(settings).values():
        texts += [rubric.name, rubric.definition]
        for level in rubric.levels:
            texts += [level.label, *level.descriptors]

    for text in texts:
        assert find_protected_terms(text) == (), text


def test_fr4_personal_names_are_found_in_the_answer():
    certain, possible = find_names(ANSWER_WITH_NAMES)
    assert {"Priya", "Tomasz", "Okafor"} <= certain
    assert "Initially" not in certain and "Monday" not in certain | possible
    assert not {"Our", "My", "I", "Dr"} & (certain | possible)


@pytest.mark.parametrize(
    ("rationale", "name"),
    [
        ("The candidate names the concern raised by Priya and states the result.", "Priya"),
        ("Tomasz's concern is named, and the candidate describes the step taken.", "Tomasz"),
        ("The candidate asked Priya and Tomasz for their concerns before acting.", "Priya"),
        ("The candidate states the result, which Dr Okafor acknowledged.", "Okafor"),
    ],
)
def test_fr4_rationale_repeating_a_personal_name_from_the_answer_is_flagged(rationale, name):
    result = screen_rationale(rationale, ANSWER_WITH_NAMES)
    assert result.flagged is True
    assert name in result.names


def test_fr4_name_seen_only_at_the_start_of_a_sentence_is_still_caught_in_the_rationale():
    answer = "Marisol disagreed with my plan. Marisol wanted more time, so I asked what was needed."
    result = screen_rationale("The candidate names the concern Marisol raised.", answer)
    assert result.flagged is True
    assert result.names == ("Marisol",)


@pytest.mark.parametrize(
    "rationale",
    [
        "The candidate names the concern of each colleague and states the result.",
        "Initially the team disagreed, and the candidate describes the step taken.",
        'The candidate states "Initially nobody was happy" and gives the result.',
        "On Monday the release shipped, which the candidate states as the result.",
        "Our reading is that level 4 is met. My view of level 5 is that it is not.",
        "The candidate asked a colleague and a manager for their concerns.",
    ],
)
def test_fr4_rationale_without_a_name_from_the_answer_is_not_flagged(rationale):
    result = screen_rationale(rationale, ANSWER_WITH_NAMES)
    assert result.names == ()
    assert result.flagged is False


def test_fr4_capitalised_ordinary_words_are_not_taken_as_names():
    answer = (
        "Eventually we agreed. Costs fell after the Finance review in March, and I used Excel "
        "to track progress. The costs were shared with the team."
    )
    certain, possible = find_names(answer)
    assert certain == frozenset()
    assert "Costs" not in possible, "a word that also appears in lower case is not a name"
    assert {"finance", "march", "excel", "eventually"} <= NOT_PERSONAL_NAMES


@pytest.mark.parametrize(
    ("answer", "rationale", "names"),
    [
        (
            "I asked McKenzie for the figures and then spoke to DeShawn about the delay.",
            "The candidate asked McKenzie and DeShawn before acting.",
            ("McKenzie", "DeShawn"),
        ),
        (
            "The plan came from O'Brien, and I checked it with the whole team first.",
            "The candidate checked the plan from O'Brien with the team.",
            ("O'Brien",),
        ),
        (
            "I knew it would take time, so I asked Will what he needed and we will meet weekly.",
            "The candidate asked Will what was needed.",
            ("Will",),
        ),
        (
            "I asked Mark to mark the tickets he had finished, and we agreed a list.",
            "The candidate names the step agreed with Mark.",
            ("Mark",),
        ),
        (
            "Marisol disagreed with my plan. Marisol wanted more time, so I asked what was needed.",
            "Marisol's concern is named, and the candidate describes the step taken.",
            ("Marisol",),
        ),
        (
            "My colleague Anne-Marie wanted more testing, so I asked what she needed.",
            "The candidate asked Marie what was needed.",
            ("Marie",),
        ),
        (
            "I shared Priya's notes with the team and we agreed the next step.",
            "The candidate shared notes from Priya with the team.",
            ("Priya",),
        ),
        (
            "- Okonkwo covered the phones\n- I covered the desk, and we swapped at noon.",
            "The candidate describes sharing work with Okonkwo.",
            ("Okonkwo",),
        ),
    ],
    ids=["inner-capitals", "apostrophe", "will", "mark", "sentence-start-in-both",
         "hyphenated", "possessive", "list-item"],
)  # fmt: skip
def test_fr4_names_that_the_first_version_missed_are_flagged(answer, rationale, names):
    result = screen_rationale(rationale, answer)
    assert result.names == names
    assert result.flagged is True


@pytest.mark.parametrize(
    ("answer", "rationale"),
    [
        (
            "I'm sure we couldn't have done it alone. Don't forget the team helped. We've kept "
            "the weekly note and I'd do it again.",
            "The candidate describes sharing credit. Don't read the result as vague: it is stated.",
        ),
        (
            "Turning to the cause, I checked the logs. Rather than guess, I tested each part. "
            "Whatever the result, I wrote it down. Everybody saw the notes on Fridays.",
            "Turning to the level rule, the candidate tested causes one at a time. Rather than "
            "one idea, two options were compared. Everybody involved agreed the way forward.",
        ),
        (
            "Conflict was rare in our team. Anyone could raise a concern at the Christmas review.",
            "Conflict is described, and the candidate names a concern. Anyone reading the answer "
            "can see the result is stated.",
        ),
        (
            "We used the HR system and the NHS guidance, and I spoke to IT about access.",
            "The candidate describes gathering information from HR and IT.",
        ),
        (
            "Grant funding was short. Vincent Street office was closing, so we planned the move.",
            "The candidate describes a specific problem and states the result.",
        ),
    ],
    ids=["contractions", "sentence-openers", "common-words", "acronyms", "no-repeat"],
)
def test_fr4_ordinary_capitalised_words_do_not_count_as_repeated_names(answer, rationale):
    result = screen_rationale(rationale, answer)
    assert result.names == ()
    assert result.flagged is False


def test_fr4_name_candidates_in_the_dev_golden_answers_are_not_ordinary_words():
    """Tuning looks at `dev` rows only. A candidate is not a hit: the screen fires only when
    the rationale repeats it. This keeps the stop list honest on the answers we can see."""
    import json

    from tests.unit.samples import REPO_ROOT

    path = REPO_ROOT / "evals" / "datasets" / "golden.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    dev = [row for row in rows if row["split"] == "dev"]
    assert len(dev) == 20

    candidates = set()
    for row in dev:
        certain, possible = find_names(row["answer"])
        candidates |= certain | possible
    assert candidates == set(), "an ordinary word is being read as a name: add it to the stop list"


def test_fr4_a_name_in_the_rationale_that_is_not_in_the_answer_is_not_a_name_hit():
    result = screen_rationale("The candidate asked Priya for a view.", TEAMWORK_ANSWER)
    assert result.names == ()


def test_fr4_rationale_screen_is_deterministic():
    rationale = "She asked Priya for a view."
    assert screen_rationale(rationale, ANSWER_WITH_NAMES) == screen_rationale(
        rationale, ANSWER_WITH_NAMES
    )
