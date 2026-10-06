from __future__ import annotations

from typing import Any

EXTRACTION_PROMPT_VERSION = "extraction_v1"

STRUCTURED_FIELD_NAMES = (
    "retrieval_scenario",
    "remembers",
    "forgotten",
    "search_attempt",
    "failure_point",
    "workaround",
    "outcome",
)

FORBIDDEN_EXTRACTION_KEYS = frozenset(
    {
        "problem_archetype",
        "cluster_id",
        "opportunity_rank",
        "mvp_label",
        "taxonomy",
        "archetype",
    }
)


def _nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def count_populated_fields(structured: dict[str, Any]) -> int:
    return sum(1 for key in STRUCTURED_FIELD_NAMES if _nullable_str(structured.get(key)))


def validate_extraction_item(item: dict[str, Any], expected_record_id: str) -> dict[str, Any]:
    if item.get("record_id") != expected_record_id:
        raise ValueError(f"record_id mismatch: expected {expected_record_id}")

    for key in item:
        if key in FORBIDDEN_EXTRACTION_KEYS or key.replace(" ", "_").lower() in FORBIDDEN_EXTRACTION_KEYS:
            raise ValueError(f"forbidden extraction field: {key}")

    structured = {name: _nullable_str(item.get(name)) for name in STRUCTURED_FIELD_NAMES}

    evidence = item.get("evidence_spans")
    cleaned_evidence: dict[str, str] = {}
    if isinstance(evidence, dict):
        for field, quote in evidence.items():
            if field not in STRUCTURED_FIELD_NAMES:
                continue
            q = _nullable_str(quote)
            if q:
                cleaned_evidence[field] = q

    return {
        "record_id": expected_record_id,
        "structured_fields": structured,
        "evidence_spans": cleaned_evidence,
        "extraction_sparse": count_populated_fields(structured) < 3,
    }
