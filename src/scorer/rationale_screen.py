"""Deterministic rationale screen (spec FR-4 step 9).

The rubric never needs a protected attribute or a person's name, so a rationale that
mentions one is a fairness signal. The screen sets `rationale_protected_term` when the
rationale contains a term from `PROTECTED_TERMS`, or a personal name found in the answer.
It is a flag for a human reviewer, never a judgement about the candidate.

`PROTECTED_TERMS` is the lexicon. It is small on purpose and is tuned on `dev` cases only.
Words with a common everyday or technical meaning are left out ("race", "old", "blind",
"disabled", "foreign", "senior"), and a term never matches inside a longer or hyphenated
word ("age" in "manage", "old" in "threshold", "man" in "man-hours").

A personal name is any capitalised word in the answer that is not in `NOT_PERSONAL_NAMES`,
including names with inner capitals, apostrophes and hyphens ("McKenzie", "O'Brien",
"Anne-Marie"). Finding a candidate costs nothing by itself: the flag is set only when the
rationale repeats one. Known limits: a name that is also a month ("May", "June"), and a
name seen only at the start of a sentence whose lower-case form is also in the answer.
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
    i me my mine myself we us our ours ourselves you your yours he him his she her hers
    they them their theirs it its this that these those there here who whom whose which
    what whatever whoever whenever wherever how why where
    the a an all any anyone anybody anything both each either every everyone everybody
    everything few many most much neither nobody none nothing some someone somebody
    something several another other others such same
    and but or nor so yet for because since although though unless until while when if as
    at in on by from with without to of off out up down over under between through during
    within across after before above below against among around into onto upon about along
    despite except towards per via
    then now later soon today yesterday tomorrow still also again already just only even
    maybe perhaps once twice first second third firstly secondly thirdly finally lastly
    last next initially eventually afterwards meanwhile overall instead however therefore
    moreover furthermore otherwise nevertheless additionally consequently sometimes often
    always never usually normally generally originally recently previously suddenly
    quickly slowly obviously personally honestly actually basically clearly fortunately
    unfortunately luckily sadly thankfully rather quite partway halfway together too very
    well afterward anyway anyhow besides indeed thus hence likewise similarly apparently
    essentially ultimately naturally surprisingly importantly hopefully admittedly frankly
    typically occasionally immediately altogether alternatively accordingly nonetheless
    regardless whereas whether whilst like
    is are was were be been being am do does did done has have had can could would should
    must might shall let make made take took get got give gave go went see saw say said
    tell told ask asked know knew think thought want wanted need needed try tried use used
    work worked start started keep kept put set found felt help helped look looked given
    based
    people person team teams teamwork member members colleague colleagues manager managers
    management staff customer customers client clients supplier suppliers problem problems
    solving solution conflict issue issues situation task tasks action actions result
    results example time times day days week weeks month months year years part thing
    things way job role company business project projects plan meeting meetings
    communication feedback
    limited developing competent strong exceptional candidate level levels descriptor
    descriptors competency
    one two three four five six seven eight nine ten
    yes no not ok okay please thanks thank sorry hello hi dear
    monday tuesday wednesday thursday friday saturday sunday
    mondays tuesdays wednesdays thursdays fridays saturdays sundays
    january february march april may june july august september october november december
    christmas easter
    mr mrs ms miss dr prof sir madam
    agile scrum kanban sprint excel word outlook slack jira python java
    finance sales marketing operations engineering support legal procurement
    """.split()
)

_APOSTROPHES = "'" + chr(0x2019)
_WORD = re.compile(r"[^\W\d_]+")
# A word that may hold an apostrophe, such as a surname or a possessive. Hyphens split
# words, so each part of a double-barrelled name is looked at on its own.
_NAME_WORD = re.compile(rf"[^\W\d_]+(?:[{_APOSTROPHES}][^\W\d_]+)*")
_CONTRACTION = re.compile(rf"[{_APOSTROPHES}](?:s|m|d|ll|ve|re)$", re.IGNORECASE)
_NEGATIVE_CONTRACTION = re.compile(rf"n[{_APOSTROPHES}]t$", re.IGNORECASE)
_SENTENCE_END = ".!?:;\n"
_OPENERS = "\"'([{" + chr(0x201C) + chr(0x2018)
_BULLETS = "*>-" + chr(0x2022) + chr(0x2013)


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
    if index >= 0 and text[index] in _BULLETS and index + 1 < start:
        # A list marker, with a space after it, at the start of a line.
        index -= 1
        while index >= 0 and text[index] in " \t":
            index -= 1
    return index < 0 or text[index] in _SENTENCE_END


def _looks_like_name(word: str) -> bool:
    """Capitalised, with at least one small letter: "Priya", "McKenzie", "O'Brien"."""
    return len(word) >= 2 and word[0].isupper() and not word.isupper()


def _capitalised_words(text: str) -> list[tuple[str, bool]]:
    """Each name-like word with whether it sits in the middle of a sentence.

    A possessive or contraction ending is dropped ("Priya's" gives "Priya"), and a word
    such as "Don't" is never a name.
    """
    found: list[tuple[str, bool]] = []
    for match in _NAME_WORD.finditer(text):
        word = match.group(0)
        if _NEGATIVE_CONTRACTION.search(word):
            continue
        word = _CONTRACTION.sub("", word)
        if _looks_like_name(word) and word.lower() not in NOT_PERSONAL_NAMES:
            found.append((word, not _starts_sentence(text, match.start())))
    return found


def find_names(answer: str) -> tuple[frozenset[str], frozenset[str]]:
    """Possible personal names in the answer, as (certain, possible).

    A capitalised word in the middle of a sentence is taken as a name, whether or not the
    same word also appears in lower case ("Will", "Mark"). One seen only at the start of a
    sentence is a possible name, because any word is capitalised there: it counts unless
    the answer also uses it in lower case. A word in `NOT_PERSONAL_NAMES` is never a name.
    """
    lower_case_words = {word for word in _WORD.findall(answer) if word.islower()}
    certain: set[str] = set()
    possible: set[str] = set()
    for word, mid_sentence in _capitalised_words(answer):
        if mid_sentence:
            certain.add(word)
        elif word.lower() not in lower_case_words and not word.endswith("ing"):
            # "Turning to the cause, ..." opens a sentence with a verb, not a name.
            possible.add(word)
    return frozenset(certain), frozenset(possible - certain)


def find_names_in_rationale(rationale: str, answer: str) -> tuple[str, ...]:
    """Names from the answer that the rationale repeats, wherever they sit in a sentence."""
    certain, possible = find_names(answer)
    names = certain | possible
    found: list[str] = []
    for word, _ in _capitalised_words(rationale):
        if word in names and word not in found:
            found.append(word)
    return tuple(found)


def screen_rationale(rationale: str, answer: str) -> RationaleScreenResult:
    """Flag a rationale that mentions a protected attribute or a name from the answer."""
    terms = find_protected_terms(rationale)
    names = find_names_in_rationale(rationale, answer)
    return RationaleScreenResult(flagged=bool(terms or names), terms=terms, names=names)
