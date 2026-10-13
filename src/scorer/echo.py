"""Deterministic check for an answer that only repeats the question.

An answer built almost entirely from the question's own words has nothing to
evaluate, so it is off topic by definition. The model usually says so, but not
every time, and a control that depends on the model's mood is not a control.
This check needs no model: it counts how many of the answer's words are new.
"""

from __future__ import annotations

import re
import unicodedata

# An answer is an echo when fewer than this share of its words are words the question
# does not contain. Ordinary answers sit above 0.8; a restated question sits near 0.2.
ECHO_MAX_NOVEL_SHARE = 0.35

_WORD = re.compile(r"[a-z0-9']+")


def _words(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text).lower())


def novel_share(question: str, answer: str) -> float:
    """Share of the answer's words that do not appear in the question (1.0 if no words)."""
    answer_words = _words(answer)
    if not answer_words:
        return 1.0
    question_words = set(_words(question))
    novel = sum(1 for word in answer_words if word not in question_words)
    return novel / len(answer_words)


def echoes_question(question: str, answer: str) -> bool:
    """True when the answer adds almost nothing to the question's own words."""
    return novel_share(question, answer) < ECHO_MAX_NOVEL_SHARE
