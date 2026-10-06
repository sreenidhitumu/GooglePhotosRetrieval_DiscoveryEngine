from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from discover.ingestors.base import RawRecordRef, SourceIngestor


class RedditApifyIngestor(SourceIngestor):
    source_type = "reddit"

    def __init__(self, records: list[dict[str, Any]], source_path: Path) -> None:
        self._records = records
        self.source_path = source_path

    @classmethod
    def from_path(cls, path: Path) -> RedditApifyIngestor:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError(f"Expected JSON array in {path}")
        return cls(records=data, source_path=path)

    def discover(self) -> int:
        return len(self._records)

    def iter_records(self) -> Iterator[RawRecordRef]:
        for item in self._records:
            if not isinstance(item, dict):
                continue
            native_id = item.get("id") or item.get("parsedId")
            if not native_id:
                continue
            yield RawRecordRef(source_native_id=str(native_id), payload=item)
