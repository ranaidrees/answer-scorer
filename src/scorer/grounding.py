"""Deterministic grounding check for evidence quotes (spec FR-7). No model is involved.

A quote is grounded when, after normalising case, whitespace and quote characters, it is
a substring of the redacted answer, or it is near verbatim: the same words in the same
order, where a word may differ only by a small slip, and with a fuzzy match ratio of at
least 0.9 against a window of the answer of the same length. A paraphrase is not evidence.

Three rules keep the evidence honest and the cost bounded:

- The evidence returned is always the matching text of the answer itself, never the
  model's wording, so what a reviewer sees is the candidate's own words.
- The word rule is stricter than the ratio alone: a changed, added or dropped word, a
  changed number or a changed negation is never grounded. The 0.9 ratio stays the outer
  bound, so nothing it rejects is ever grounded.
- Every step has a fixed limit (quotes per run, quote length for near-verbatim matching,
  windows examined), so no answer or quote can make the check slow. A quote over a limit
  is grounded only as an exact substring.

Ungrounded quotes are removed from the response and counted.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from scorer.schemas import EvidenceItem

FUZZY_THRESHOLD = 0.9

# A grounded quote has at least this many words, or this many characters.
MIN_QUOTE_WORDS = 3
MIN_QUOTE_CHARS = 12
# Limits that bound the cost of the check.
MAX_QUOTES = 8
MAX_FUZZY_QUOTE_CHARS = 240
MAX_CANDIDATE_WINDOWS = 200
MAX_VERIFIED_WINDOWS = 3
# A slip inside one word: at most two characters and 40% of the word, with the same first
# letter and a length within one, never in a word of three characters or fewer.
MAX_WORD_EDITS = 2
MAX_WORD_EDIT_SHARE = 0.4
MIN_TYPO_WORD_CHARS = 4
MAX_TYPO_WORD_CHARS = 30

NEGATIONS = frozenset(
    """
    no not never none nobody nothing nowhere neither nor cannot without non
    cant dont wont didnt doesnt isnt arent wasnt werent hasnt havent hadnt couldnt wouldnt
    shouldnt
    """.split()
)
NEGATING_PREFIXES = ("un", "in", "im", "ir", "il", "non", "dis", "mis")

_SINGLE_QUOTES = (0x2018, 0x2019, 0x201A, 0x201B, 0x2032, 0x2035, 0x60, 0xB4)
_DOUBLE_QUOTES = (0x201C, 0x201D, 0x201E, 0x201F, 0x2033, 0x2036, 0xAB, 0xBB)
_QUOTE_TABLE = {
    **dict.fromkeys(_SINGLE_QUOTES, "'"),
    **dict.fromkeys(_DOUBLE_QUOTES, '"'),
}
_WHITESPACE = re.compile(r"\s+")
_WORD = re.compile(r"\S+")
_WORD_EDGES = re.compile(r"^[\W_]+|[\W_]+$")
# A model often wraps a quote in quotation marks or trims it with an ellipsis.
_WRAPPING = " \"'."


@dataclass(frozen=True)
class GroundingResult:
    evidence: list[EvidenceItem]
    ungrounded: int


@dataclass(frozen=True)
class _Word:
    core: str
    start: int
    end: int


@dataclass(frozen=True)
class _Answer:
    """An answer prepared once: normalised text that maps back to the answer's own text."""

    source: str
    text: str
    origin: list[int]
    words: list[_Word] = field(default_factory=list)
    positions: dict[str, list[int]] = field(default_factory=dict)

    def span(self, start: int, end: int) -> str:
        """The answer's own text behind normalised characters `start` to `end`."""
        return self.source[self.origin[start] : self.origin[end - 1] + 1]


def normalise(text: str) -> str:
    """Fold case, collapse whitespace and unify quote characters."""
    folded = unicodedata.normalize("NFKC", text).translate(_QUOTE_TABLE).casefold()
    return _WHITESPACE.sub(" ", folded).strip()


def _core(token: str) -> str:
    """A word without the punctuation around it."""
    return _WORD_EDGES.sub("", token) or token


def _prepare_answer(answer: str) -> _Answer:
    """Normalise the answer as `normalise` does, keeping where each character came from."""
    source = unicodedata.normalize("NFKC", answer)
    characters: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(source):
        for piece in char.translate(_QUOTE_TABLE).casefold():
            if piece.isspace():
                if not characters or characters[-1] == " ":
                    continue
                piece = " "
            characters.append(piece)
            origin.append(index)
    if characters and characters[-1] == " ":
        characters.pop()
        origin.pop()
    text = "".join(characters)

    words = []
    for match in _WORD.finditer(text):
        token = match.group(0)
        core = _core(token)
        # Where the word itself starts and ends, without the punctuation around it.
        begin = match.start() + token.find(core)
        words.append(_Word(core, begin, begin + len(core)))
    positions: dict[str, list[int]] = {}
    for number, word in enumerate(words):
        positions.setdefault(word.core, []).append(number)
    return _Answer(source=source, text=text, origin=origin, words=words, positions=positions)


def _normalise_quote(quote: str) -> str:
    return normalise(quote).strip(_WRAPPING).strip()


def _long_enough(needle: str) -> bool:
    return len(needle) >= MIN_QUOTE_CHARS or len(needle.split(" ")) >= MIN_QUOTE_WORDS


def _is_negation(word: str) -> bool:
    return word in NEGATIONS or word.endswith("n't")


def _edit_distance(first: str, second: str) -> int:
    """Levenshtein distance. Both words are short, so the table is small."""
    previous = list(range(len(second) + 1))
    for row, char in enumerate(first, start=1):
        current = [row]
        for column, other in enumerate(second, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (char != other),
                )
            )
        previous = current
    return previous[-1]


def _same_word(quoted: str, written: str) -> bool:
    """True if the two words are the same word, allowing a small slip in copying."""
    if quoted == written:
        return True
    longer, shorter = sorted((quoted, written), key=len, reverse=True)
    if len(longer) < MIN_TYPO_WORD_CHARS or len(longer) > MAX_TYPO_WORD_CHARS:
        return False
    if any(char.isdigit() for char in longer + shorter):
        return False
    if _is_negation(quoted) or _is_negation(written):
        return False
    if any(longer == prefix + shorter for prefix in NEGATING_PREFIXES):
        return False
    # A slip keeps the first letter and nearly the same length; "their" for "her" or
    # "the" is another word, not a slip.
    if quoted[0] != written[0] or len(longer) - len(shorter) > 1:
        return False
    allowed = min(MAX_WORD_EDITS, int(MAX_WORD_EDIT_SHARE * len(longer)))
    return _edit_distance(quoted, written) <= allowed


def _ratio_reaches_threshold(needle: str, answer: _Answer, start: int, end: int) -> bool:
    """The spec's outer bound: a same-length window of the answer at ratio 0.9 or more."""
    length = len(needle)
    last = len(answer.text) - length
    if last < 0:
        windows = [answer.text]
    else:
        starts = {min(max(start, 0), last), min(max(end - length, 0), last)}
        windows = [answer.text[begin : begin + length] for begin in sorted(starts)]
    matcher = SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(needle)
    for window in windows:
        matcher.set_seq1(window)
        if matcher.quick_ratio() >= FUZZY_THRESHOLD and matcher.ratio() >= FUZZY_THRESHOLD:
            return True
    return False


def _near_verbatim(needle: str, answer: _Answer) -> str | None:
    """Find the answer's own text that the quote copies with small slips, if any."""
    quoted = [_core(token) for token in needle.split(" ")]
    count, total = len(quoted), len(answer.words)
    # Each differing word costs the ratio at least one character in ten.
    allowed = min(count - 1, len(needle) // 10)
    if count > total or allowed < 1:
        return None

    # At most `allowed` words differ, so of any `allowed + 1` words one is copied exactly.
    # The rarest ones in the answer give the fewest places to look.
    anchors = sorted(
        range(count), key=lambda place: (len(answer.positions.get(quoted[place], ())), place)
    )
    starts: set[int] = set()
    for place in anchors[: allowed + 1]:
        for found in answer.positions.get(quoted[place], ())[:MAX_CANDIDATE_WINDOWS]:
            if 0 <= found - place <= total - count:
                starts.add(found - place)

    verified = 0
    for start in sorted(starts)[:MAX_CANDIDATE_WINDOWS]:
        differing: list[int] = []
        for place in range(count):
            if answer.words[start + place].core != quoted[place]:
                differing.append(place)
                if len(differing) > allowed:
                    break
        else:
            if all(_same_word(quoted[p], answer.words[start + p].core) for p in differing):
                begin, end = answer.words[start].start, answer.words[start + count - 1].end
                if _ratio_reaches_threshold(needle, answer, begin, end):
                    return answer.span(begin, end)
                verified += 1
                if verified >= MAX_VERIFIED_WINDOWS:
                    return None
    return None


def _find(quote: str, answer: _Answer) -> str | None:
    needle = _normalise_quote(quote)
    if not needle or not answer.text or not _long_enough(needle):
        return None
    found = answer.text.find(needle)
    if found >= 0:
        return answer.span(found, found + len(needle))
    if len(needle) > MAX_FUZZY_QUOTE_CHARS:
        return None
    return _near_verbatim(needle, answer)


def ground_quote(quote: str, answer: str) -> str | None:
    """The answer's own text that the quote is grounded in, or None if it is not grounded."""
    return _find(quote, _prepare_answer(answer))


def is_grounded(quote: str, answer: str) -> bool:
    """True if the quote is verbatim, or near verbatim, text from the answer."""
    return ground_quote(quote, answer) is not None


def check_evidence(
    quotes: list[str], answer: str, *, max_quotes: int = MAX_QUOTES
) -> GroundingResult:
    """Keep the grounded quotes, as the answer's own words. Drop and count the rest.

    Only the first `max_quotes` quotes are checked; any beyond that count as ungrounded.
    """
    prepared = _prepare_answer(answer)
    evidence: list[EvidenceItem] = []
    ungrounded = 0
    for number, quote in enumerate(quotes):
        found = _find(quote, prepared) if number < max_quotes else None
        if found is None:
            ungrounded += 1
        else:
            evidence.append(EvidenceItem(quote=found, grounded=True))
    return GroundingResult(evidence=evidence, ungrounded=ungrounded)
