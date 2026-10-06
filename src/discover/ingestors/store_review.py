from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterator

from discover.ingestors.base import RawRecordRef, SourceIngestor


class StoreReviewIngestor(SourceIngestor):
    source_type = "store_review"

    def __init__(self, records: list[dict[str, Any]], source_path: Path, source_type: str = "store_review") -> None:
        self._records = records
        self.source_path = source_path
        self.source_type = source_type

    @classmethod
    def from_path(cls, path: Path) -> StoreReviewIngestor:
        source_type = "google_play" if "play" in path.name.lower() else ("app_store" if ("appstore" in path.name.lower() or "app_store" in path.name.lower() or "apple" in path.name.lower()) else "store_review")
        if path.suffix.lower() == ".csv":
            records: list[dict[str, Any]] = []
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    records.append(dict(row))
            return cls(records=records, source_path=path, source_type=source_type)
        else:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and "reviews" in data:
                data = data["reviews"]
            if not isinstance(data, list):
                raise ValueError(f"Expected JSON array or dict with 'reviews' key in {path}")
            return cls(records=data, source_path=path, source_type=source_type)

    def discover(self) -> int:
        return len(self._records)

    def iter_records(self) -> Iterator[RawRecordRef]:
        for idx, item in enumerate(self._records):
            if not isinstance(item, dict):
                continue
            native_id = (
                item.get("id")
                or item.get("review_id")
                or item.get("reviewId")
                or f"review_{idx}"
            )
            yield RawRecordRef(source_native_id=str(native_id), payload=item)
