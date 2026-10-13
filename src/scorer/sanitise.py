"""Deterministic sanitiser (spec FR-4 step 2, first layer of FR-6).

Normalises to Unicode NFKC, then removes invisible characters and HTML tags. Text that a
reader cannot see can still steer a model, so removing anything that can hide content sets
`hidden_text_removed`, which the pipeline also counts as an injection signal. A soft
hyphen is removed without the flag, and a zero-width joiner inside an emoji is kept.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Characters with no visible form, beyond the general category check in `_is_invisible`:
# fillers and joiners that Unicode classes as letters or marks, the whole tag block
# (U+E0000 to U+E007F, which mirrors ASCII invisibly), and the variation selectors.
# The emoji presentation selector U+FE0F is left alone because ordinary emoji carry it.
_INVISIBLE_EXTRA = frozenset(
    [0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180C, 0x180D, 0x180F, 0x3164, 0xFFA0]
)
_INVISIBLE_RANGES = (
    (0xE0000, 0xE007F),  # Unicode tag characters
    (0xFE00, 0xFE0E),  # variation selectors 1 to 15
    (0xE0100, 0xE01EF),  # variation selectors supplement
)
_KEPT_CONTROLS = frozenset("\n\t")

# Two invisible characters that carry no hidden content. They are handled without setting
# the flag (decision S2-15): a soft hyphen only marks where a word may break, and text
# pasted from a document often has one; a zero-width joiner between two emoji is part of
# one visible emoji and is kept.
_SOFT_HYPHEN = chr(0x00AD)
_ZERO_WIDTH_JOINER = chr(0x200D)
_EMOJI_SELECTOR = chr(0xFE0F)
_SKIN_TONES = (0x1F3FB, 0x1F3FF)

# HTML comments go with their content (a renderer would hide it). Tags go, their visible
# text stays. Only text shaped like a real tag is removed: a tag name straight after the
# bracket, then nothing, or attributes with "=", or bare attributes when the bracket does
# not touch a word. So "a < b", "<3" and "if a<b then c>d" are kept.
_TAG_NAME = r"[A-Za-z][\w:.-]*"
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_HTML_TAG = re.compile(
    rf"</?{_TAG_NAME}\s*/?>"
    rf"|<{_TAG_NAME}\s[^<>=]*=[^<>]*>"
    rf"|(?<![A-Za-z0-9])<{_TAG_NAME}\s[^<>]*>"
    r"|<![A-Za-z][^<>]*>|<\?[^<>]*\?>"
)
# Removing a tag can leave another one behind, so tags are stripped again, up to this
# many times. Text that still forms tags after that loses its angle brackets.
_MAX_TAG_PASSES = 8
_ANGLE_BRACKETS = re.compile(r"[<>]")


@dataclass(frozen=True)
class SanitiseResult:
    text: str
    hidden_text_removed: bool


def _is_invisible(char: str) -> bool:
    """True for zero-width, bidirectional, tag, control and other unseen characters."""
    if char in _KEPT_CONTROLS:
        return False
    code = ord(char)
    if code in _INVISIBLE_EXTRA or any(low <= code <= high for low, high in _INVISIBLE_RANGES):
        return True
    # Cf: format characters (zero-width space and joiners, bidirectional controls, word
    # joiner, byte order mark, soft hyphen). Cc: control characters. Cs: lone surrogates,
    # which are not text and cannot be encoded.
    return unicodedata.category(char) in ("Cf", "Cc", "Cs")


def _is_emoji_part(char: str) -> bool:
    code = ord(char)
    return (
        char == _EMOJI_SELECTOR
        or _SKIN_TONES[0] <= code <= _SKIN_TONES[1]
        or unicodedata.category(char) == "So"
    )


def _joins_emoji(text: str, index: int) -> bool:
    """True if the character at `index` sits between two emoji characters."""
    return (
        0 < index < len(text) - 1
        and _is_emoji_part(text[index - 1])
        and _is_emoji_part(text[index + 1])
    )


def _strip_invisible(text: str) -> tuple[str, bool]:
    """Remove invisible characters. The flag is set only for ones that can hide content."""
    kept: list[str] = []
    hidden = False
    for index, char in enumerate(text):
        if char == _SOFT_HYPHEN:
            continue
        if char == _ZERO_WIDTH_JOINER and _joins_emoji(text, index):
            kept.append(char)
        elif _is_invisible(char):
            hidden = True
        else:
            kept.append(char)
    return "".join(kept), hidden


def _strip_tags(text: str) -> tuple[str, bool]:
    """Remove HTML comments and tags, again while removing one leaves another behind."""
    removed = False
    for _ in range(_MAX_TAG_PASSES):
        stripped = _HTML_TAG.sub("", _HTML_COMMENT.sub("", text))
        if stripped == text:
            return text, removed
        text, removed = stripped, True
    return _ANGLE_BRACKETS.sub("", text), True


def sanitise(text: str) -> SanitiseResult:
    """Return the cleaned text and whether anything hidden was removed."""
    normalised = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n"))
    visible, hidden = _strip_invisible(normalised)
    cleaned, tags = _strip_tags(visible)
    return SanitiseResult(text=cleaned, hidden_text_removed=hidden or tags)
