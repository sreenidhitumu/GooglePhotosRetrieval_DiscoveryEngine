from __future__ import annotations

import re
from dataclasses import dataclass

from discover.text_utils import combined_text

# Source-agnostic patterns on canonical title+body only (no platform branches).

_VISUAL_CUES = re.compile(
    r"\b(photo|photos|picture|pictures|screenshot|screenshots|video|videos|"
    r"image|images|selfie|album|scan|document|pdf|meme|gif)\b",
    re.I,
)

_GP_CUES = re.compile(
    r"\b(google\s*photos|gphotos|google\s*photo)\b",
    re.I,
)

_LIBRARY_CUES = re.compile(
    r"\b(photo\s*library|my\s*photos|photos\s*app|gallery\s*app|cloud\s*photos)\b",
    re.I,
)

_RETRIEVAL_CUES = re.compile(
    r"\b("
    r"find|finding|found|search|searching|look(?:ing)?\s+for|"
    r"can'?t\s+find|cannot\s+find|couldn'?t\s+find|"
    r"locate|retrieve|retriev|missing|lost|browse|scrolling|scroll\s+through"
    r")\b",
    re.I,
)

_MEMORY_CUES = re.compile(
    r"\b(remember|remembered|forgot|forget|memory|memories|years?\s+ago|"
    r"vague|fuzzy|kind\s+of\s+remember)\b",
    re.I,
)

_OFF_TOPIC_STRONG = re.compile(
    r"\b(subscription|billing|refund|cancel\s+my|pricing|payment|"
    r"customer\s+service|delete\s+my\s+account)\b",
    re.I,
)

_GENERIC_COMPLAINT = re.compile(
    r"\b(app\s+is\s+slow|laggy|crash|bug|update\s+ruined|hate\s+the\s+ui)\b",
    re.I,
)


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    reason: str


def evaluate_deterministic_gate(title: str | None, body: str | None) -> GateDecision:
    """
    Lightweight candidate filter before LLM. Must not use source_type or Reddit-specific rules.
    """
    text = combined_text(title, body)
    if not text.strip():
        return GateDecision(False, "empty_content")

    has_visual = bool(_VISUAL_CUES.search(text))
    has_gp = bool(_GP_CUES.search(text))
    has_library = bool(_LIBRARY_CUES.search(text))
    has_retrieval = bool(_RETRIEVAL_CUES.search(text))
    has_memory = bool(_MEMORY_CUES.search(text))

    product_context = has_gp or has_library
    retrieval_story = has_retrieval or has_memory

    if _OFF_TOPIC_STRONG.search(text) and not (retrieval_story and (has_visual or product_context)):
        return GateDecision(False, "off_topic_billing_account")

    if _GENERIC_COMPLAINT.search(text) and not retrieval_story:
        return GateDecision(False, "generic_complaint_no_retrieval")

    if not has_visual and not product_context:
        return GateDecision(False, "no_visual_or_library_context")

    if not retrieval_story:
        return GateDecision(False, "no_retrieval_or_memory_cue")

    if product_context and retrieval_story:
        return GateDecision(True, "product_and_retrieval")

    if has_visual and retrieval_story:
        return GateDecision(True, "visual_and_retrieval")

    return GateDecision(False, "insufficient_retrieval_evidence")
