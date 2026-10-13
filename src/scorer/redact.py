"""Deterministic contact-detail redaction (spec FR-4 step 3).

Emails, phone numbers and URLs are replaced by fixed placeholders before the model sees
the answer. The placeholders do not count as answer text: an answer that is only contact
details has nothing left to score and is rejected by the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL_PLACEHOLDER = "[email]"
PHONE_PLACEHOLDER = "[phone]"
URL_PLACEHOLDER = "[url]"
PLACEHOLDERS = (EMAIL_PLACEHOLDER, PHONE_PLACEHOLDER, URL_PLACEHOLDER)

_TRAILING_PUNCTUATION = ".,;:!?)]}'\""

_URL_WITH_SCHEME = re.compile(r"(?:\b(?:https?|ftp)://|\bwww\.)[^\s<>\[\]\"']+", re.IGNORECASE)
# The lookbehind lets a match start only at the start of a run, which keeps it linear.
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+",
    re.IGNORECASE,
)
# A bare domain such as "example.com/profile". The ending list is short on purpose, so a
# missing space after a full stop ("done.Then") is not read as a web address.
_BARE_DOMAIN = re.compile(
    r"(?<![\w@.-])(?:[a-z0-9-]+\.)+"
    r"(?:com|org|net|edu|gov|io|dev|app|info|co\.uk|org\.uk|ac\.uk|uk|example)"
    r"(?![\w-])(?:/[^\s<>\[\]\"']*)?",
    re.IGNORECASE,
)
# Groups of digits joined by one separator each, as people write phone numbers:
# "+44 (0)20 7946 0958", "07700 900123", "(555) 123-4567". The digit count decides.
# Groups and separators use different characters, so matching stays linear.
_PHONE_CANDIDATE = re.compile(r"(?<![\w+,.])\+?\(?\d[\d()]*(?:[ \t.\-][\d()]+)*(?![\w])")
_PHONE_MIN_DIGITS = 9
_PHONE_MIN_DIGITS_INTERNATIONAL = 8
_PHONE_MAX_DIGITS = 15

_PLACEHOLDER = re.compile("|".join(re.escape(item) for item in PLACEHOLDERS))
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class RedactionResult:
    text: str
    emails: int
    phones: int
    urls: int
    remaining_chars: int

    @property
    def redactions(self) -> int:
        return self.emails + self.phones + self.urls


def _replace_keeping_tail(pattern: re.Pattern[str], placeholder: str, text: str) -> tuple[str, int]:
    """Replace each match, leaving sentence punctuation after it in place."""

    def swap(match: re.Match[str]) -> str:
        found = match.group(0)
        kept = found.rstrip(_TRAILING_PUNCTUATION)
        return placeholder + found[len(kept) :]

    return pattern.subn(swap, text)


def _replace_phones(text: str) -> tuple[str, int]:
    count = 0

    def swap(match: re.Match[str]) -> str:
        nonlocal count
        found = match.group(0)
        number = found.rstrip("(")
        digits = sum(char.isdigit() for char in number)
        international = number.startswith(("+", "00"))
        minimum = _PHONE_MIN_DIGITS_INTERNATIONAL if international else _PHONE_MIN_DIGITS
        if not minimum <= digits <= _PHONE_MAX_DIGITS:
            return found
        count += 1
        return PHONE_PLACEHOLDER + found[len(number) :]

    return _PHONE_CANDIDATE.sub(swap, text), count


def remaining_chars(text: str) -> int:
    """Characters of answer text left once placeholders and spare whitespace are gone."""
    without_placeholders = _PLACEHOLDER.sub(" ", text)
    return len(_WHITESPACE.sub(" ", without_placeholders).strip())


def redact(text: str) -> RedactionResult:
    """Redact contact details. The same input always gives the same output."""
    text, urls = _replace_keeping_tail(_URL_WITH_SCHEME, URL_PLACEHOLDER, text)
    text, emails = _replace_keeping_tail(_EMAIL, EMAIL_PLACEHOLDER, text)
    text, bare = _replace_keeping_tail(_BARE_DOMAIN, URL_PLACEHOLDER, text)
    text, phones = _replace_phones(text)
    return RedactionResult(
        text=text,
        emails=emails,
        phones=phones,
        urls=urls + bare,
        remaining_chars=remaining_chars(text),
    )
