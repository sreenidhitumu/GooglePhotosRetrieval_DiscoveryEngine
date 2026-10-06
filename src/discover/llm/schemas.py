from __future__ import annotations

from typing import Any


RELEVANCE_PROMPT_VERSION = "relevance_v2"

ALLOWED_SIGNAL_THEMES = frozenset(
    {
        "memory_gap",
        "recall_vs_forgotten",
        "search_formulation",
        "failure_point",
        "workaround",
        "visual_content_type",
        "product_context",
        "outcome_mentioned",
    }
)


def validate_relevance_item(item: dict[str, Any], expected_record_id: str) -> dict[str, Any]:
    if item.get("record_id") != expected_record_id:
        raise ValueError(f"record_id mismatch: expected {expected_record_id}")

    is_relevant = item.get("is_relevant")
    if not isinstance(is_relevant, bool):
        raise ValueError("is_relevant must be boolean")

    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
        raise ValueError("confidence must be number in [0,1]")

    rationale = item.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("rationale must be non-empty string")

    signals = item.get("retrieval_signal_types", [])
    if not isinstance(signals, list):
        raise ValueError("retrieval_signal_types must be a list")
    cleaned_signals: list[str] = []
    for s in signals:
        if not isinstance(s, str):
            continue
        tag = s.strip().lower().replace(" ", "_")
        if tag in ALLOWED_SIGNAL_THEMES:
            cleaned_signals.append(tag)
        elif tag:
            cleaned_signals.append(tag)

    return {
        "record_id": expected_record_id,
        "is_relevant": is_relevant,
        "confidence": float(confidence),
        "rationale": rationale.strip(),
        "retrieval_signal_types": cleaned_signals,
    }
