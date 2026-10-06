from __future__ import annotations

from typing import Any

# Rough input-token estimate for Gemini budgeting (chars / 4 is standard heuristic).
_CHARS_PER_TOKEN = 4
_PROMPT_OVERHEAD_TOKENS = 900
_OUTPUT_TOKENS_PER_RECORD = 120


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_record_input_tokens(rec: dict[str, Any]) -> int:
    title = rec.get("title") or ""
    body = rec.get("body") or ""
    if len(body) > 6000:
        body = body[:6000] + "\n...[truncated]"
    permalink = rec.get("permalink") or ""
    source_type = rec.get("source_type") or ""
    rid = rec.get("record_id") or ""
    combined = f"{rid} {source_type} {title} {body} {permalink}"
    return estimate_text_tokens(combined) + 24


def estimate_batch_input_tokens(records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    return _PROMPT_OVERHEAD_TOKENS + sum(estimate_record_input_tokens(r) for r in records)


def estimate_batch_total_tokens(records: list[dict[str, Any]]) -> int:
    """Input + rough expected JSON output for TPM window accounting."""
    return estimate_batch_input_tokens(records) + _OUTPUT_TOKENS_PER_RECORD * len(records)
