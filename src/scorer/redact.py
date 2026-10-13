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
# Letters of any script are allowed, so an address with an accented letter goes whole.
_EMAIL = re.compile(r"(?<![\w.%+-])[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")
# A bare domain such as "example.com/profile". The ending list is short on purpose, so a
# missing space after a full stop ("done.Then") is not read as a web address. An ending
# that is also part of a product name ("asp.net") needs a path or a third label.
_PATH = r"/[^\s<>\[\]\"']*"
_END = r"(?![\w-]|\.\w)"  # the ending is the last label, not a label in the middle
_BARE_DOMAIN = re.compile(
    r"(?<![\w@.-])(?:"
    rf"(?:[a-z0-9-]+\.)+(?:com|org|edu|gov|co\.uk|org\.uk|ac\.uk|example){_END}(?:{_PATH})?"
    rf"|(?:[a-z0-9-]+\.)+(?:net|io|dev|app|info|uk){_END}{_PATH}"
    rf"|(?:[a-z0-9-]+\.){{2,}}(?:net|io|dev|app|info|uk){_END}"
    r")",
    re.IGNORECASE,
)
# Groups of digits joined by one separator each, as people write phone numbers:
# "+44 (0)20 7946 0958", "07700 900123", "(555) 123-4567". Groups and separators use
# different characters, so matching stays linear. `_looks_like_phone` then decides, so
# that years, dates, times and reference numbers are left alone.
_PHONE_CANDIDATE = re.compile(r"(?<![\w+,.])\+?\(?\d[\d()]*(?:[ \t.\-][\d()]+)*(?![\w])")
_INTERNATIONAL_DIGITS = (8, 15)
_NATIONAL_DIGITS = (10, 11)
_AREA_CODE = re.compile(r"\(?0\d{2,}")
_NORTH_AMERICAN = re.compile(r"(?:1[ .\-])?\(?\d{3}\)?[ .\-]\d{3}[ .\-]\d{4}")

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


def _looks_like_phone(number: str) -> bool:
    """True for a number written the way phone numbers are.

    International: a leading "+" or "00" and 8 to 15 digits. National: an area code that
    starts with 0 and has at least three digits, and 10 or 11 digits in all. North
    American: three, three and four digits. Anything else, such as "2019 2020 2021",
    "2021-03-15 10" or a nine-digit reference, is not a phone number.
    """
    digits = sum(char.isdigit() for char in number)
    if number.startswith(("+", "00")):
        return _INTERNATIONAL_DIGITS[0] <= digits <= _INTERNATIONAL_DIGITS[1]
    if _AREA_CODE.match(number):
        return _NATIONAL_DIGITS[0] <= digits <= _NATIONAL_DIGITS[1]
    return bool(_NORTH_AMERICAN.fullmatch(number))


def _replace_phones(text: str) -> tuple[str, int]:
    count = 0

    def swap(match: re.Match[str]) -> str:
        nonlocal count
        found = match.group(0)
        number = found.rstrip("(")
        if not _looks_like_phone(number):
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
