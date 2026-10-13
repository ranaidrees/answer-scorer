"""Deterministic sanitiser (spec FR-4 step 2, first layer of FR-6).

Normalises to Unicode NFKC, then removes invisible characters and HTML tags. Text that a
reader cannot see can still steer a model, so anything removed sets `hidden_text_removed`,
which the pipeline also counts as an injection signal.
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

# HTML comments go with their content (a renderer would hide it). Tags go, their visible
# text stays. A tag name must follow the bracket at once, so "a < b" and "<3" are kept.
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_HTML_TAG = re.compile(r"</?[A-Za-z][\w:.-]*(?:\s[^<>]*)?/?>|<![A-Za-z][^<>]*>|<\?[^<>]*\?>")


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


def sanitise(text: str) -> SanitiseResult:
    """Return the cleaned text and whether anything hidden was removed."""
    normalised = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n"))
    visible = "".join(char for char in normalised if not _is_invisible(char))
    removed = len(visible) != len(normalised)

    # Repeat until stable, so that removing one tag cannot assemble another.
    cleaned = visible
    while True:
        stripped = _HTML_TAG.sub("", _HTML_COMMENT.sub("", cleaned))
        if stripped == cleaned:
            break
        cleaned = stripped
        removed = True

    return SanitiseResult(text=cleaned, hidden_text_removed=removed)
