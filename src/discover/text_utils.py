from __future__ import annotations

import hashlib
import re
from html import unescape

_REMOVED_MARKERS = frozenset({"[removed]", "[deleted]"})
_WS_RE = re.compile(r"\s+")


def decode_reddit_text(value: str | None) -> str:
    if not value:
        return ""
    return unescape(value).strip()


def combine_title_body(title: str | None, body: str | None) -> tuple[str, str]:
    """Return (title, body) with HTML entities decoded."""
    t = decode_reddit_text(title)
    b = decode_reddit_text(body)
    return t, b


def combined_text(title: str | None, body: str | None) -> str:
    t, b = combine_title_body(title, body)
    if t and b:
        return f"{t}\n\n{b}"
    return t or b


def normalize_for_hash(text: str) -> str:
    lowered = text.casefold()
    collapsed = _WS_RE.sub(" ", lowered).strip()
    return collapsed


def content_hash(source_type: str, text: str) -> str:
    payload = f"{source_type}\n{normalize_for_hash(text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_boilerplate_removed(text: str) -> bool:
    stripped = text.strip().casefold()
    return stripped in _REMOVED_MARKERS


def is_empty_content(title: str | None, body: str | None) -> bool:
    return not combined_text(title, body).strip()
