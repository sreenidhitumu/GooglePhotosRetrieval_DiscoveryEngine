from __future__ import annotations

import json
from typing import Any

CLUSTER_LABEL_PROMPT_VERSION = "cluster_label_v1"

CLUSTER_LABEL_INSTRUCTIONS = """You name retrieval-problem clusters for a research report.

Rules:
- Use only the exemplar excerpts provided.
- Label: short neutral description of the user struggle (not a product solution).
- Summary: 2-3 sentences describing the pattern evidenced in the excerpts.
- Do NOT prescribe features, MVPs, or fixes.

Respond with JSON: {"label": "string", "summary": "string"}"""


def build_cluster_label_prompt(exemplars: list[dict[str, Any]]) -> str:
    payload = []
    for ex in exemplars:
        payload.append(
            {
                "record_id": ex.get("record_id"),
                "source_type": ex.get("source_type"),
                "excerpt": (ex.get("excerpt") or "")[:1200],
            }
        )
    return (
        f"{CLUSTER_LABEL_INSTRUCTIONS}\n\n"
        f"Prompt version: {CLUSTER_LABEL_PROMPT_VERSION}\n\n"
        f"Exemplars:\n{json.dumps(payload, ensure_ascii=False)}"
    )
