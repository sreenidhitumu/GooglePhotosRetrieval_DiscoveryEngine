from __future__ import annotations

# Canonical records matching these permalink fragments are omitted from
# calibration summary metrics (test fixtures), not from pipeline classification.
CALIBRATION_METRICS_EXCLUDED_PERMALINK_FRAGMENTS: tuple[str, ...] = (
    "/comments/abc/sample01",
)


def permalink_excluded_from_calibration_metrics(permalink: str | None) -> bool:
    if not permalink:
        return False
    normalized = permalink.rstrip("/")
    return any(fragment in normalized for fragment in CALIBRATION_METRICS_EXCLUDED_PERMALINK_FRAGMENTS)
