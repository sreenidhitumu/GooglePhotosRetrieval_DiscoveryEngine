from __future__ import annotations

import json
from typing import Any

STRUCTURED_KEYS = (
    "retrieval_scenario",
    "remembers",
    "forgotten",
    "search_attempt",
    "failure_point",
    "workaround",
    "outcome",
)


def build_clustering_document(
    *,
    title: str | None,
    body: str | None,
    structured_fields: dict[str, Any],
    max_body_chars: int = 2000,
) -> str:
    parts: list[str] = []
    for key in STRUCTURED_KEYS:
        val = structured_fields.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(f"{key}: {val.strip()}")
    if title and title.strip():
        parts.append(title.strip())
    if body and body.strip():
        text = body.strip()
        if len(text) > max_body_chars:
            text = text[:max_body_chars] + "\n...[truncated]"
        parts.append(text)
    return "\n".join(parts) if parts else "(empty)"


def parse_structured_fields(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
