from __future__ import annotations

import json
from typing import Any

from discover.llm.extraction_schemas import EXTRACTION_PROMPT_VERSION, STRUCTURED_FIELD_NAMES

EXTRACTION_SYSTEM_INSTRUCTIONS = """You extract structured user experience fields from public posts about visual-media retrieval in Google Photos.

Rules:
- Use only the provided text. Do not invent URLs, dates, search queries, or events.
- Use null for any field not supported by the text.
- source_type and permalink are metadata only; apply the same standard for all sources.
- Do NOT output problem archetypes, cluster IDs, opportunity ranks, MVP labels, or fixed category enums.

Fields (all nullable strings):
- retrieval_scenario: What they were trying to find or recover in context.
- remembers: Partial memory cues they still have.
- forgotten: What they cannot recall or lacks detail.
- search_attempt: What they tried in Google Photos (search, browse, albums, Memories) or compared tools.
- failure_point: Where retrieval broke down.
- workaround: Alternative tactics they used.
- outcome: success, failure, partial, or unknown if stated.

evidence_spans: optional object mapping field names to short verbatim quotes from the text (max ~200 chars each).

Respond with JSON only matching the schema."""


def build_extraction_batch_prompt(records: list[dict[str, Any]]) -> str:
    payload = []
    for rec in records:
        body = rec.get("body") or ""
        if len(body) > 6000:
            body = body[:6000] + "\n...[truncated]"
        payload.append(
            {
                "record_id": rec["record_id"],
                "source_type": rec.get("source_type"),
                "title": rec.get("title"),
                "body": body,
                "permalink": rec.get("permalink"),
            }
        )

    schema = {
        "results": [
            {
                "record_id": "string",
                **{name: "string|null" for name in STRUCTURED_FIELD_NAMES},
                "evidence_spans": {name: "string" for name in STRUCTURED_FIELD_NAMES},
            }
        ]
    }

    return (
        f"{EXTRACTION_SYSTEM_INSTRUCTIONS}\n\n"
        f"Prompt version: {EXTRACTION_PROMPT_VERSION}\n\n"
        f"Extract each record. Return JSON: {json.dumps(schema)}\n\n"
        f"Records:\n{json.dumps(payload, ensure_ascii=False)}"
    )
