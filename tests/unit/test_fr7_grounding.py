"""FR-7: the deterministic grounding check. A paraphrase is not evidence."""

from __future__ import annotations

import random
from difflib import SequenceMatcher

import pytest

from scorer.grounding import (
    FUZZY_THRESHOLD,
    _normalise_quote,
    check_evidence,
    is_grounded,
    normalise,
)
from tests.unit.samples import (
    EXACT_QUOTE,
    INVENTED_QUOTE,
    PARAPHRASED_QUOTE,
    SECOND_QUOTE,
    TEAMWORK_ANSWER,
)


def _brute_force(quote: str, answer: str) -> bool:
    """The definition in the spec, with every same-length window checked."""
    needle, haystack = _normalise_quote(quote), normalise(answer)
    if needle in haystack:
        return True
    return any(
        SequenceMatcher(None, haystack[start : start + len(needle)], needle, False).ratio()
        >= FUZZY_THRESHOLD
        for start in range(len(haystack) - len(needle) + 1)
    )


def test_fr7_exact_quote_is_grounded():
    assert is_grounded(EXACT_QUOTE, TEAMWORK_ANSWER)
    assert is_grounded(SECOND_QUOTE, TEAMWORK_ANSWER)
    assert is_grounded(TEAMWORK_ANSWER, TEAMWORK_ANSWER)


@pytest.mark.parametrize(
    "quote",
    [
        EXACT_QUOTE.upper(),
        EXACT_QUOTE.lower(),
        "  I asked each of them\n to explain   their concern before I suggested anything ",
        f'"{EXACT_QUOTE}"',
        f"\u201c{EXACT_QUOTE}\u201d",
        f"{EXACT_QUOTE}...",
        f"\u2026{EXACT_QUOTE}\u2026",
    ],
    ids=["upper", "lower", "whitespace", "straight-quotes", "curly-quotes", "dots", "ellipsis"],
)
def test_fr7_quote_differing_only_in_case_whitespace_or_quote_marks_is_grounded(quote):
    assert is_grounded(quote, TEAMWORK_ANSWER)


def test_fr7_quote_characters_are_normalised_on_both_sides():
    answer = "My manager said \u201cdon\u2019t wait for me\u201d, so I asked the team to decide."
    assert is_grounded('My manager said "don\'t wait for me"', answer)
    assert is_grounded("don\u2019t wait for me", answer.replace("\u2019", "'"))


@pytest.mark.parametrize(
    "quote",
    [
        # One slip each: a dropped letter, an added word ending, a changed word, a typo.
        "I asked each of them to explain their concern before I sugested anything",
        "I asked each of them to explain their concerns before I suggested anything",
        "I asked each of them to explain the concern before I suggested anything",
        "We agreed to train one small group first and migrate there tickets as a pilot",
        "We finished four days early, and the team kept the weekly note afterwards",
    ],
)
def test_fr7_near_exact_quote_is_grounded_at_ratio_0_9(quote):
    assert quote.lower() not in TEAMWORK_ANSWER.lower(), "the quote is not an exact substring"
    assert is_grounded(quote, TEAMWORK_ANSWER)


@pytest.mark.parametrize(
    "quote",
    [
        PARAPHRASED_QUOTE,
        "I listened to both colleagues and adjusted my plan afterwards",
        "They asked each colleague to describe the worry before proposing anything",
        "I asked them about their concerns and then changed the plan",
        # Two real fragments joined into a sentence the candidate never wrote.
        "I asked each of them to explain their concern and offered to cover a shift",
    ],
)
def test_fr7_paraphrased_quote_is_not_grounded(quote):
    assert not is_grounded(quote, TEAMWORK_ANSWER)


@pytest.mark.parametrize(
    "quote",
    [
        INVENTED_QUOTE,
        "I led the whole migration myself and trained every member of staff",
        "The customer satisfaction score rose by twenty per cent",
        "",
        "   ",
        '""',
        "...",
    ],
)
def test_fr7_invented_or_empty_quote_is_not_grounded(quote):
    assert not is_grounded(quote, TEAMWORK_ANSWER)


def test_fr7_quote_longer_than_the_answer_is_not_grounded():
    answer = "I asked the team what to change first."
    assert not is_grounded(answer + " Then I rebuilt the whole process alone.", answer)


def test_fr7_nothing_is_grounded_in_an_empty_answer():
    assert not is_grounded("I asked the team", "")


def test_fr7_ungrounded_quotes_are_removed_from_the_response_and_counted():
    result = check_evidence(
        [EXACT_QUOTE, PARAPHRASED_QUOTE, f" {SECOND_QUOTE} ", INVENTED_QUOTE], TEAMWORK_ANSWER
    )

    assert [item.quote for item in result.evidence] == [EXACT_QUOTE, SECOND_QUOTE]
    assert all(item.grounded for item in result.evidence)
    assert result.ungrounded == 2


def test_fr7_no_quotes_means_nothing_ungrounded():
    result = check_evidence([], TEAMWORK_ANSWER)
    assert result.evidence == [] and result.ungrounded == 0


def test_fr7_grounding_checks_against_the_redacted_answer():
    redacted = "I emailed [email] the plan and the team agreed to it."
    assert is_grounded("I emailed [email] the plan", redacted)
    assert not is_grounded("I emailed sam.taylor@example.com the plan", redacted)


def test_fr7_fuzzy_search_agrees_with_checking_every_window():
    """The fast search must give the same verdict as the plain definition."""
    rng = random.Random(20261013)
    words = normalise(TEAMWORK_ANSWER).split()
    letters = "abcdefghijklmnopqrstuvwxyz "
    verdicts = set()
    for _ in range(60):
        start = rng.randrange(0, len(words) - 12)
        quote = list(" ".join(words[start : start + rng.randrange(3, 12)]))
        for _ in range(rng.randrange(1, 7)):
            position = rng.randrange(len(quote))
            action = rng.choice(["swap", "drop", "add"])
            if action == "swap":
                quote[position] = rng.choice(letters)
            elif action == "drop" and len(quote) > 5:
                del quote[position]
            else:
                quote.insert(position, rng.choice(letters))
        text = "".join(quote).strip()
        if text and normalise(text) not in normalise(TEAMWORK_ANSWER):
            verdict = is_grounded(text, TEAMWORK_ANSWER)
            assert verdict == _brute_force(text, TEAMWORK_ANSWER), text
            verdicts.add(verdict)
    assert verdicts == {True, False}, "the sample covers both near-exact and too-different quotes"


def test_fr7_grounding_is_fast_on_a_long_answer_with_long_paraphrased_quotes():
    import time

    answer = (TEAMWORK_ANSWER + " ") * 7
    quotes = [
        PARAPHRASED_QUOTE * 4,
        INVENTED_QUOTE * 5,
        EXACT_QUOTE[:-20] + " while nobody else did so",
    ]
    started = time.perf_counter()
    result = check_evidence(quotes, answer[:4000])
    assert time.perf_counter() - started < 5.0
    assert result.ungrounded == 3
