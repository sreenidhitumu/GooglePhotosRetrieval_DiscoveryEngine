from __future__ import annotations

import json
from typing import Any

from discover.llm.schemas import RELEVANCE_PROMPT_VERSION

RELEVANCE_SYSTEM_INSTRUCTIONS = """You classify public posts/reviews/comments for a research study.

Research question: When users have a retrieval or memory experience with media in their Google Photos library, what evidence appears in their own words?

Mark is_relevant=true ONLY when the text contains clear evidence of BOTH:
(A) Google Photos context — the Google Photos app, photos.google.com, Google Photos search/browse, albums/shared albums in Google Photos, or Google Photos Memories features (e.g. "remember this day", memory carousel, resurfaced photos). Generic "Google", Google Search, Google Lens, Image Search, Pixel camera, or other Google products do NOT count unless the text explicitly ties the story to the Google Photos library/product.
(B) Retrieval or memory experience — at least one of:
  - Struggling to find or recover specific visual media in Google Photos (search, filters, faces/objects, albums, timeline browse, scrolling the library).
  - Google Photos search quality or AI/natural-language search failing to surface items the user expects in their library.
  - Google Photos surfacing a photo/video (especially Memories) while the user lacks context, partial memory, or cannot place the moment ("remember this day" with no recall).
  - A first-person retrieval attempt in Google Photos (including success after struggle) with incomplete or fuzzy memory of the item.

Mark is_relevant=false when:
- Only Google Search, Lens, reverse-image, or web provenance ("where is this photo from", imgur, help-me-find on the internet) without searching their Google Photos library.
- Backup/sync/Takeout/trash/deletion/account issues with no story of searching or browsing Google Photos for a specific remembered item.
- Other photo products or local galleries only (iPhoto, Immich, PhotoPrism, iOS Photos, etc.) with no Google Photos retrieval angle.
- Generic complaints (speed, UI, pricing, editing) without a retrieval/memory narrative in Google Photos.
- Hypothetical or third-person advice with no first-person Google Photos retrieval experience.
- Either (A) or (B) is missing from the text — do not infer Google Photos or retrieval from subreddit names, product guesses, or nearby topics.

Rationale rules (required for every record):
- State what in the text supports (A) Google Photos context; if none, say so and set is_relevant=false.
- State what supports (B) retrieval/memory behavior; if none, say so and set is_relevant=false.
- Quote or paraphrase only what is present. Never invent quotes, products, or attempts.

Other rules:
- source_type is metadata only; apply the same standard for all sources.
- retrieval_signal_types: use theme tags from this set when supported by text: memory_gap, recall_vs_forgotten, search_formulation, failure_point, workaround, visual_content_type, product_context, outcome_mentioned. Omit tags not evidenced. Do not use problem taxonomy, cluster names, or MVP labels.

Examples (abbreviated):
- TRUE: "I saved screenshots to Google Photos but keyword search still won't show them" — GP search failure + remembered screenshots.
- TRUE: "Google Photos 'remember this day' showed a dinner photo and I have no idea what that night was" — GP Memories + memory gap.
- TRUE: "I scroll Google Photos for an hour and still can't find that video" — GP browse/scroll + retrieval struggle.
- FALSE: "I used Google Lens and metadata but can't identify this image" — Lens/web, not GP library.
- FALSE: "All my May photos vanished from Google Photos" — data loss without search for a remembered item.
- FALSE: "Google Photos is slow after the update" — no retrieval/memory story.

Respond with JSON only matching the schema."""


def build_relevance_batch_prompt(records: list[dict[str, Any]]) -> str:
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
                "is_relevant": "boolean",
                "confidence": "number 0-1",
                "rationale": "string",
                "retrieval_signal_types": ["string"],
            }
        ]
    }

    return (
        f"{RELEVANCE_SYSTEM_INSTRUCTIONS}\n\n"
        f"Prompt version: {RELEVANCE_PROMPT_VERSION}\n\n"
        f"Classify each record. Return JSON: {json.dumps(schema)}\n\n"
        f"Records:\n{json.dumps(payload, ensure_ascii=False)}"
    )
