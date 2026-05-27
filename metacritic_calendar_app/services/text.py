from __future__ import annotations

import re


MOJIBAKE_SEQUENCE_RE = re.compile(r"[\u00c2-\u00df][\u0080-\u00bf]")
RENT_BUY_RE = re.compile(r"\brent\s*/\s*buy\b", re.IGNORECASE)


def contains_rent_buy(value: object) -> bool:
    return bool(value is not None and RENT_BUY_RE.search(str(value)))


def repair_mojibake(value: str) -> str:
    """Repair common UTF-8 text that arrived as Latin-1-style mojibake."""
    if not value or not MOJIBAKE_SEQUENCE_RE.search(value):
        return value

    def decode_match(match: re.Match[str]) -> str:
        text = match.group(0)
        try:
            return text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return text

    return MOJIBAKE_SEQUENCE_RE.sub(decode_match, value)
