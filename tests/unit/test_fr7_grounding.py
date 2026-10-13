"""FR-7: the deterministic grounding check. A paraphrase is not evidence."""

from __future__ import annotations

import random
from difflib import SequenceMatcher

import pytest

from scorer.grounding import (
    FUZZY_THRESHOLD,
    _normalise_quote,
    check_evidence,
    ground_quote,
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
        # One slip each: a dropped letter, an added word ending, swapped letters, a typo.
        # ("explain the concern" for "explain their concern" was here. It is a changed
        # word, which the review of this slice ruled out, so it moved to the test of
        # changed words below.)
        "I asked each of them to explain their concern before I sugested anything",
        "I asked each of them to explain their concerns before I suggested anything",
        "We agreed to train one small group first and migrate their tikcets as a pilot",
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


def test_fr7_nothing_is_grounded_that_the_0_9_ratio_rule_would_reject():
    """The spec's rule is the outer bound: the word rule and the limits only ever make the
    check stricter. (This test first asserted equal verdicts. The review of this slice
    asked for a stricter word rule and for limits, so equality no longer holds.)"""
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
            if verdict:
                assert _brute_force(text, TEAMWORK_ANSWER), text
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
    assert time.perf_counter() - started < 0.5
    assert result.ungrounded == 3


# --- Review findings: verbatim evidence, the word rule and the limits -------------------

COMPROMISE = (
    "Two colleagues wanted different release dates. I asked each of them what mattered most "
    "and proposed a compromise that both accepted. I can help them again if it happens."
)


def test_fr7_near_verbatim_match_returns_the_answers_own_words_not_the_models():
    quote = "I asked each of them to explain their concerns before I sugested anything"
    result = check_evidence([quote], TEAMWORK_ANSWER)

    assert [item.quote for item in result.evidence] == [EXACT_QUOTE]
    assert result.evidence[0].quote in TEAMWORK_ANSWER
    assert ground_quote(quote, TEAMWORK_ANSWER) == EXACT_QUOTE


def test_fr7_exact_match_returns_the_answers_own_case_and_spacing():
    assert ground_quote(EXACT_QUOTE.upper(), TEAMWORK_ANSWER) == EXACT_QUOTE
    assert ground_quote("i asked  each of\nthem to explain", TEAMWORK_ANSWER) == (
        "I asked each of them to explain"
    )
    answer = "My manager said \u201cdon\u2019t wait for me\u201d, so I asked the team to decide."
    assert ground_quote('My manager said "don\'t wait for me"', answer) == (
        "My manager said \u201cdon\u2019t wait for me"
    )


def test_fr7_every_grounded_quote_is_text_from_the_answer():
    quotes = [
        EXACT_QUOTE.lower(),
        "We agreed to train one small group first and migrate there tickets as a pilot",
        "We finished four days early, and the team kept the weekly note afterwards",
    ]
    result = check_evidence(quotes, TEAMWORK_ANSWER)
    assert len(result.evidence) == 3
    for item in result.evidence:
        assert item.quote in TEAMWORK_ANSWER


def test_fr7_quote_with_a_changed_word_is_not_grounded():
    quote = "proposed a compromise that nobody accepted"
    assert _brute_force(quote, COMPROMISE), "the ratio alone would accept it"
    assert not is_grounded(quote, COMPROMISE)
    assert check_evidence([quote], COMPROMISE).evidence == []


def test_fr7_quote_with_an_added_or_dropped_negation_is_not_grounded():
    assert not is_grounded("I can't help them again if it happens", COMPROMISE)
    assert not is_grounded("I cannot help them again if it happens", COMPROMISE)
    assert not is_grounded("I can not help them again if it happens", COMPROMISE)
    negative = "I told the customer I can't promise a date and wasn't able to confirm it."
    assert not is_grounded("I told the customer I can promise a date", negative)
    assert not is_grounded("and was able to confirm it", negative)
    assert is_grounded("I can\u2019t promise a date", negative)


@pytest.mark.parametrize("quote", ["a", "I", "we", "of them", "We agreed", "plan after"])
def test_fr7_quote_shorter_than_three_words_or_twelve_characters_is_not_grounded(quote):
    assert quote.lower() in TEAMWORK_ANSWER.lower(), "it is an exact substring"
    assert not is_grounded(quote, TEAMWORK_ANSWER)


@pytest.mark.parametrize("quote", ["We agreed to", "I changed my", "training. We finished"])
def test_fr7_quote_of_three_words_or_twelve_characters_can_be_grounded(quote):
    assert is_grounded(quote, TEAMWORK_ANSWER)


@pytest.mark.parametrize(
    "quote",
    [
        # A dropped word, an added word, a changed number, an opposite, a swapped pronoun.
        "I asked each of them to explain concern before I suggested anything",
        "I asked each of them to carefully explain their concern before I suggested anything",
        "We finished five days early and the team kept the weekly note afterwards",
        "I asked each of them to explain their concern after I suggested anything",
        "We agreed to train one small group first and migrate her tickets as a pilot",
        "I asked each of them to explain the concern before I suggested anything",
    ],
)
def test_fr7_quote_that_changes_adds_or_drops_a_whole_word_is_not_grounded(quote):
    assert not is_grounded(quote, TEAMWORK_ANSWER)


def test_fr7_a_small_slip_is_allowed_only_inside_a_longer_word():
    from scorer.grounding import _same_word

    assert _same_word("suggested", "sugested")
    assert _same_word("concerns", "concern")
    assert _same_word("their", "there")
    assert not _same_word("he", "she")
    assert not _same_word("was", "has")
    assert not _same_word("able", "unable")
    assert not _same_word("can", "can't")
    assert not _same_word("didnt", "did")
    assert not _same_word("2019", "2018")
    assert not _same_word("both", "nobody")
    assert not _same_word("accepted", "rejected")


def test_fr7_only_the_first_eight_quotes_are_checked_and_the_rest_count_as_ungrounded():
    from scorer.grounding import MAX_QUOTES

    assert MAX_QUOTES == 8
    result = check_evidence([EXACT_QUOTE] * 11, TEAMWORK_ANSWER)
    assert len(result.evidence) == 8
    assert result.ungrounded == 3


def test_fr7_a_quote_over_the_length_limit_is_grounded_only_as_an_exact_substring():
    from scorer.grounding import MAX_FUZZY_QUOTE_CHARS

    long_quote = TEAMWORK_ANSWER[:400]
    assert len(long_quote) > MAX_FUZZY_QUOTE_CHARS
    assert is_grounded(long_quote, TEAMWORK_ANSWER)
    assert not is_grounded(long_quote.replace("ticketing", "tiketing"), TEAMWORK_ANSWER)
    short_quote = TEAMWORK_ANSWER[: TEAMWORK_ANSWER.index(" first,")]
    assert 100 < len(short_quote) <= MAX_FUZZY_QUOTE_CHARS
    assert is_grounded(short_quote.replace("ticketing", "tiketing"), TEAMWORK_ANSWER)


def test_fr7_prepared_answer_matches_the_plain_normalisation():
    from scorer.grounding import _prepare_answer

    for text in (
        TEAMWORK_ANSWER,
        COMPROMISE,
        "  A \u201cquoted\u201d\n\n line\tSTRASSE \u00df  ",
        "",
    ):
        prepared = _prepare_answer(text)
        assert prepared.text == normalise(text)
        assert len(prepared.origin) == len(prepared.text)


HOSTILE_GROUNDING = {
    "repeated letters, 120-character quote": (
        "abc" * 1334,
        ["abcabcabcabc" + "cba" * 36],
    ),
    "repeated letters, 240-character quote": (
        "abc" * 1334,
        ["abcabcabcabc" + "cba" * 76],
    ),
    "repeated sentence, altered long quote": (
        "I asked the team what to change and we agreed a plan for the week. " * 60,
        [("I asked the team what to change and we agreed a plan for the week. " * 3)[:156]
         .replace("agreed", "argued")],
    ),
    "repeated word, ten near-miss quotes": (
        "ab " * 1333,
        ["ab " * 70 + "xy zz"] * 10,
    ),
    "repeated words, ten quotes one slip from many windows": (
        "alpha beta gamma delta " * 170,
        ["alpha beta gamma delta " * 9 + "alpha betta gamma dellta epsilon"] * 10,
    ),
    "one long word": ("x" * 4000, ["x" * 239 + "y"] * 10),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(HOSTILE_GROUNDING))
def test_fr7_grounding_stays_fast_on_hostile_answers_and_quotes(case):
    import time

    answer, quotes = HOSTILE_GROUNDING[case]
    started = time.perf_counter()
    result = check_evidence(quotes, answer[:4000])
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"{case} took {elapsed:.3f}s"
    assert len(result.evidence) + result.ungrounded == len(quotes)
    for item in result.evidence:
        assert item.quote in answer
