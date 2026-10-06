from __future__ import annotations

from pathlib import Path

from discover.ingestors.base import SourceIngestor
from discover.ingestors.reddit_apify import RedditApifyIngestor
from discover.ingestors.store_review import StoreReviewIngestor
from discover.ingestors.youtube import YouTubeIngestor

_REGISTRY: dict[str, type[SourceIngestor]] = {
    "reddit": RedditApifyIngestor,
    "youtube": YouTubeIngestor,
    "google_play": StoreReviewIngestor,
    "app_store": StoreReviewIngestor,
    "store_review": StoreReviewIngestor,
}


def get_ingestor(source: str, path: Path) -> SourceIngestor:
    key = source.lower().strip()
    cls = _REGISTRY.get(key)
    if cls is None:
        supported = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"Unknown source '{source}'. Supported: {supported}")
    return cls.from_path(path)
