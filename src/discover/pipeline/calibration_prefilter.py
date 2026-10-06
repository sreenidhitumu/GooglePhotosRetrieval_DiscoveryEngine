from __future__ import annotations

import re
from dataclasses import dataclass

from discover.text_utils import combined_text, is_boilerplate_removed, is_empty_content

# Minimal exclusions for calibration runs (gate bypass). Does not replace gate.py.

_ARTIFACT_ONLY = re.compile(
    r"^\s*(\[deleted\]|\[removed\]|\[unavailable\]|comment removed by moderator)\s*$",
    re.I,
)

_DELETED_USER_STUB = re.compile(
    r"^\s*/u/\S+\s+on\s+(deleted|removed)\s*\.?\s*$",
    re.I,
)

_AUTOMOD_STUB = re.compile(r"^\s*i am a bot\b", re.I)


@dataclass(frozen=True)
class CalibrationPrefilterDecision:
    exclude: bool
    reason: str | None = None


def evaluate_calibration_prefilter(title: str | None, body: str | None) -> CalibrationPrefilterDecision:
    """
    Exclude only empty, [removed]/[deleted], or obvious scraper stubs.
    All other records should reach the LLM when gate bypass is enabled.
    """
    if is_empty_content(title, body):
        return CalibrationPrefilterDecision(True, "calibration_empty_content")

    combined = combined_text(title, body)
    if is_boilerplate_removed(combined):
        return CalibrationPrefilterDecision(True, "calibration_removed_content")

    if _ARTIFACT_ONLY.match(combined):
        return CalibrationPrefilterDecision(True, "calibration_artifact_boilerplate")

    if _DELETED_USER_STUB.match(combined):
        return CalibrationPrefilterDecision(True, "calibration_deleted_user_stub")

    stripped = combined.strip()
    if len(stripped) < 2:
        return CalibrationPrefilterDecision(True, "calibration_too_short")

    if _AUTOMOD_STUB.match(stripped) and len(stripped) < 120:
        return CalibrationPrefilterDecision(True, "calibration_bot_stub")

    return CalibrationPrefilterDecision(False)
