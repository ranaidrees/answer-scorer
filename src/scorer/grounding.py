"""Deterministic grounding check for evidence quotes (spec FR-7). No model is involved.

A quote is grounded when, after normalising case, whitespace and quote characters, it is
a substring of the redacted answer, or it has a fuzzy match ratio of at least 0.9 against
a window of the answer of the same length. A paraphrase is not evidence. Ungrounded quotes
are removed from the response and counted.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from scorer.schemas import EvidenceItem

FUZZY_THRESHOLD = 0.9

_QUOTE_CHARACTERS = {
    **dict.fromkeys("\u2018\u2019\u201a\u201b\u2032\u2035`\u00b4", "'"),
    **dict.fromkeys("\u201c\u201d\u201e\u201f\u2033\u2036\u00ab\u00bb", '"'),
}
_QUOTE_TABLE = str.maketrans(_QUOTE_CHARACTERS)
_WHITESPACE = re.compile(r"\s+")
# A model often wraps a quote in quotation marks or trims it with an ellipsis.
_WRAPPING = " \"'."


@dataclass(frozen=True)
class GroundingResult:
    evidence: list[EvidenceItem]
    ungrounded: int


def normalise(text: str) -> str:
    """Fold case, collapse whitespace and unify quote characters."""
    folded = unicodedata.normalize("NFKC", text).translate(_QUOTE_TABLE).casefold()
    return _WHITESPACE.sub(" ", folded).strip()


def _normalise_quote(quote: str) -> str:
    return normalise(quote).strip(_WRAPPING).strip()


def _ratio(matcher: SequenceMatcher, window: str) -> float:
    matcher.set_seq1(window)
    if matcher.real_quick_ratio() < FUZZY_THRESHOLD or matcher.quick_ratio() < FUZZY_THRESHOLD:
        return 0.0
    return matcher.ratio()


def _fuzzy_window_match(quote: str, answer: str) -> bool:
    """True if some window of `answer` as long as `quote` has a ratio of at least 0.9.

    Checking every window would be slow, so candidate windows are found first. A window
    that reaches the ratio shares at least `matched` characters with the quote in at most
    `unmatched + 1` runs, so it shares a run of at least `seed` characters, and that run
    sits within `unmatched` places of the same position in both. Every window near every
    shared seed is therefore checked, which finds the same windows as checking them all.
    """
    length = len(quote)
    matcher = SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(quote)
    if length >= len(answer):
        return _ratio(matcher, answer) >= FUZZY_THRESHOLD

    matched = math.ceil(round(FUZZY_THRESHOLD * 100) * length / 100)
    unmatched = length - matched
    seed = max(1, math.ceil(matched / (unmatched + 1)))

    positions: dict[str, list[int]] = {}
    for start in range(len(answer) - seed + 1):
        positions.setdefault(answer[start : start + seed], []).append(start)

    last_start = len(answer) - length
    candidates: set[int] = set()
    for offset in range(length - seed + 1):
        for found in positions.get(quote[offset : offset + seed], ()):
            diagonal = found - offset
            low, high = max(0, diagonal - unmatched), min(last_start, diagonal + unmatched)
            candidates.update(range(low, high + 1))

    return any(
        _ratio(matcher, answer[start : start + length]) >= FUZZY_THRESHOLD
        for start in sorted(candidates)
    )


def is_grounded(quote: str, answer: str) -> bool:
    """True if the quote is verbatim, or near verbatim, text from the answer."""
    needle, haystack = _normalise_quote(quote), normalise(answer)
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    return _fuzzy_window_match(needle, haystack)


def check_evidence(quotes: list[str], answer: str) -> GroundingResult:
    """Keep the grounded quotes, drop and count the rest."""
    evidence: list[EvidenceItem] = []
    ungrounded = 0
    for quote in quotes:
        if is_grounded(quote, answer):
            evidence.append(EvidenceItem(quote=quote.strip(), grounded=True))
        else:
            ungrounded += 1
    return GroundingResult(evidence=evidence, ungrounded=ungrounded)
