"""Given-name sanitizer: letters only, no emoji or symbols."""

from __future__ import annotations

import unicodedata

_KEEP = {" ", "\u00a0", "'", "\u2019", "\u02bc", "-"}
_MAX_LEN = 40


def sanitize_person_name(raw: str | None, *, max_len: int = _MAX_LEN) -> str:
    text = unicodedata.normalize("NFKC", raw or "")
    kept: list[str] = []
    prev_space = False
    for char in text:
        category = unicodedata.category(char)
        allowed = category.startswith("L") or category.startswith("M") or char in _KEEP
        if not allowed:
            continue
        is_space = char in {" ", "\u00a0"}
        if is_space:
            if prev_space or not kept:
                continue
            kept.append(" ")
            prev_space = True
            continue
        kept.append(char)
        prev_space = False
    cleaned = "".join(kept).strip()
    if not any(unicodedata.category(char).startswith("L") for char in cleaned):
        return ""
    return cleaned[:max_len]
