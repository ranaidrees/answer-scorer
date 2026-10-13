"""Deterministic rationale screen (spec FR-4 step 9).

The rubric never needs a protected attribute or a person's name, so a rationale that
mentions one is a fairness signal. The screen sets `rationale_protected_term` when the
rationale contains a term from `PROTECTED_TERMS`, or a personal name found in the answer.
It is a flag for a human reviewer, never a judgement about the candidate.

`PROTECTED_TERMS` is the lexicon. It is small on purpose and is tuned on `dev` cases only.
Words with a common everyday or technical meaning are left out ("race", "old", "blind",
"disabled", "foreign", "senior"), and a term never matches inside a longer or hyphenated
word ("age" in "manage", "old" in "threshold", "man" in "man-hours").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PROTECTED_TERMS: dict[str, tuple[str, ...]] = {
    "gender": (
        "he", "she", "him", "her", "his", "hers", "himself", "herself",
        "man", "woman", "men", "women", "male", "female", "gender", "gendered",
        "gentleman", "lady", "boy", "girl", "masculine", "feminine", "mr", "mrs",
        "sex", "non-binary", "transgender",
    ),
    "age": (
        "age", "aged", "ageing", "aging", "elderly", "young", "younger", "youth",
        "teenager", "pensioner", "middle-aged", "years old", "year old", "date of birth",
        "older worker", "older person", "older people", "older colleague",
    ),
    "ethnicity": (
        "ethnicity", "ethnic", "racial", "racially", "racism", "skin colour", "skin color",
        "person of colour", "person of color", "mixed race", "asian", "african", "caucasian",
        "hispanic", "latino", "latina", "arab",
    ),
    "nationality": (
        "nationality", "national origin", "country of origin", "citizenship", "immigrant",
        "migrant", "refugee", "foreigner", "native speaker", "non-native", "mother tongue",
        "first language", "second language", "accent", "broken english",
        "british", "american", "european", "indian", "pakistani", "bangladeshi", "chinese",
        "nigerian", "irish", "scottish", "welsh",
    ),
    "religion": (
        "religion", "religious", "christian", "muslim", "islam", "islamic", "jewish", "hindu",
        "sikh", "buddhist", "catholic", "atheist", "church", "mosque", "synagogue", "ramadan",
        "hijab",
    ),
    "disability": (
        "disability", "disabilities", "disabled person", "disabled people", "wheelchair",
        "deaf", "visually impaired", "hearing impaired", "visual impairment",
        "hearing impairment", "dyslexia", "dyslexic", "autism", "autistic", "adhd",
        "neurodivergent", "neurodiverse", "mental health", "mental illness", "chronic illness",
    ),
    "pregnancy_and_family": (
        "pregnant", "pregnancy", "maternity", "paternity", "mother", "father", "mum", "mom",
        "dad", "motherhood", "fatherhood", "husband", "wife", "spouse", "boyfriend",
        "girlfriend", "married", "marriage", "divorced", "widow", "widowed", "single parent",
        "civil partnership", "childcare",
    ),
    "sexual_orientation": (
        "gay", "lesbian", "bisexual", "homosexual", "heterosexual", "lgbt", "lgbtq", "queer",
        "sexual orientation",
    ),
}  # fmt: skip

# Capitalised words that are not a person's name, in lower case. A capitalised word in the
# answer is otherwise treated as a possible name.
NOT_PERSONAL_NAMES: frozenset[str] = frozenset(
    """
    i the a an and but or so then when while after before once first second third finally
    next later also however instead because since although though if as at in on by for from
    with without to of we my our they their it this that these those there here what who how
    why where which one two three four five some most many all both each every no not yes
    during within over under between through together eventually initially afterwards
    meanwhile overall another everyone someone nobody people team teams teamwork problem
    solving limited developing competent strong exceptional candidate
    monday tuesday wednesday thursday friday saturday sunday
    january february march april may june july august september october november december
    mr mrs ms miss dr prof sir madam
    agile scrum kanban sprint excel word outlook teams slack jira python java
    finance sales marketing operations engineering support legal procurement
    """.split()
)

_WORD = re.compile(r"[^\W\d_]+")
_SENTENCE_END = ".!?:;\n"
_OPENERS = "\"'\u201c\u2018([{*\u2022>-\u2013"


def _term_pattern(term: str) -> str:
    parts = re.split(r"[\s-]+", term)
    separator = r"[\s-]+" if "-" in term else r"\s+"
    return separator.join(re.escape(part) for part in parts)


_TERMS = re.compile(
    r"(?<![\w-])(?:"
    + "|".join(
        _term_pattern(term)
        for term in sorted(
            {term for terms in PROTECTED_TERMS.values() for term in terms}, key=len, reverse=True
        )
    )
    + r")(?![\w-])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RationaleScreenResult:
    flagged: bool
    terms: tuple[str, ...]
    names: tuple[str, ...]


def find_protected_terms(rationale: str) -> tuple[str, ...]:
    """Lexicon terms present in the rationale, lower case, in order of first appearance."""
    found: list[str] = []
    for match in _TERMS.finditer(rationale):
        term = re.sub(r"\s+", " ", match.group(0).lower())
        if term not in found:
            found.append(term)
    return tuple(found)


def _starts_sentence(text: str, start: int) -> bool:
    """True if the word at `start` opens a sentence, a line, a list item or a quotation."""
    if start > 0 and text[start - 1] in _OPENERS:
        return True
    index = start - 1
    while index >= 0 and text[index] in " \t":
        index -= 1
    return index < 0 or text[index] in _SENTENCE_END


def _looks_like_name(word: str) -> bool:
    return len(word) >= 2 and word[0].isupper() and word[1:].islower()


def _capitalised_words(text: str) -> list[tuple[str, bool]]:
    """Each name-like word with whether it sits in the middle of a sentence."""
    return [
        (match.group(0), not _starts_sentence(text, match.start()))
        for match in _WORD.finditer(text)
        if _looks_like_name(match.group(0))
    ]


def find_names(answer: str) -> tuple[frozenset[str], frozenset[str]]:
    """Possible personal names in the answer, as (certain, possible).

    A capitalised word in the middle of a sentence is taken as a name. One seen only at the
    start of a sentence is only a possible name, because any word is capitalised there. A
    word that also appears in lower case, or is in `NOT_PERSONAL_NAMES`, is not a name.
    """
    lower_case_words = {word for word in _WORD.findall(answer) if word.islower()}
    certain: set[str] = set()
    possible: set[str] = set()
    for word, mid_sentence in _capitalised_words(answer):
        if word.lower() in NOT_PERSONAL_NAMES or word.lower() in lower_case_words:
            continue
        (certain if mid_sentence else possible).add(word)
    return frozenset(certain), frozenset(possible - certain)


def find_names_in_rationale(rationale: str, answer: str) -> tuple[str, ...]:
    """Names from the answer that the rationale repeats."""
    certain, possible = find_names(answer)
    found: list[str] = []
    for word, mid_sentence in _capitalised_words(rationale):
        if (word in certain or (word in possible and mid_sentence)) and word not in found:
            found.append(word)
    return tuple(found)


def screen_rationale(rationale: str, answer: str) -> RationaleScreenResult:
    """Flag a rationale that mentions a protected attribute or a name from the answer."""
    terms = find_protected_terms(rationale)
    names = find_names_in_rationale(rationale, answer)
    return RationaleScreenResult(flagged=bool(terms or names), terms=terms, names=names)
