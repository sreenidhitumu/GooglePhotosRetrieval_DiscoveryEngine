from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class RawRecordRef:
    """Reference to one source-native item before persistence."""

    source_native_id: str
    payload: dict[str, Any]


class SourceIngestor(ABC):
    source_type: str

    @abstractmethod
    def discover(self) -> int:
        """Return number of records available for ingestion."""

    @abstractmethod
    def iter_records(self) -> Iterator[RawRecordRef]:
        """Yield records to store verbatim in raw_record.payload_json."""

    @classmethod
    @abstractmethod
    def from_path(cls, path: Path) -> SourceIngestor:
        """Build ingestor from a local dataset path."""
