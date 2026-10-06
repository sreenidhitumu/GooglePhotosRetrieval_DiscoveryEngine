from __future__ import annotations

from dataclasses import dataclass

from discover.pipeline.normalize import CanonicalDraft
from discover.text_utils import combined_text, is_boilerplate_removed, is_empty_content


@dataclass(frozen=True)
class NoiseDecision:
    exclude: bool
    reason: str | None = None
    detail: str | None = None


def evaluate_noise(draft: CanonicalDraft) -> NoiseDecision:
    if is_empty_content(draft.title, draft.body):
        return NoiseDecision(True, "empty_content", "No title or body text after normalization")

    combined = combined_text(draft.title, draft.body)
    if is_boilerplate_removed(combined):
        return NoiseDecision(True, "removed_content", combined)

    if draft.body and is_boilerplate_removed(draft.body):
        return NoiseDecision(True, "removed_content", draft.body)

    if draft.title and is_boilerplate_removed(draft.title):
        return NoiseDecision(True, "removed_content", draft.title)

    return NoiseDecision(False)
