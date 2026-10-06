from __future__ import annotations

from typing import Any

from discover.llm.token_estimate import (
    _PROMPT_OVERHEAD_TOKENS,
    estimate_record_input_tokens,
)


def pack_relevance_batches(
    records: list[dict[str, Any]],
    *,
    max_records_per_batch: int,
    max_input_tokens_per_batch: int,
) -> list[list[dict[str, Any]]]:
    """
    Pack as many records as fit under token and count caps (architecture: dynamic batching).
    """
    if max_records_per_batch < 1:
        raise ValueError("max_records_per_batch must be >= 1")
    if max_input_tokens_per_batch < 1:
        raise ValueError("max_input_tokens_per_batch must be >= 1")

    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_body_tokens = 0

    for rec in records:
        rec_tokens = estimate_record_input_tokens(rec)

        if current and (
            len(current) >= max_records_per_batch
            or _PROMPT_OVERHEAD_TOKENS + current_body_tokens + rec_tokens
            > max_input_tokens_per_batch
        ):
            batches.append(current)
            current = []
            current_body_tokens = 0

        if not current and _PROMPT_OVERHEAD_TOKENS + rec_tokens > max_input_tokens_per_batch:
            batches.append([rec])
            continue

        current.append(rec)
        current_body_tokens += rec_tokens

    if current:
        batches.append(current)

    return batches
