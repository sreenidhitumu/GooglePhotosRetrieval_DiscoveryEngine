from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from discover.config import project_root
from discover.ingestors.base import SourceIngestor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    ingest_run_id: str
    records_ingested: int
    records_skipped_existing: int
    input_checksum: str
    reused_existing_run: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_run_by_checksum(engine: Engine, checksum: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id FROM ingest_run
                WHERE input_checksum = :checksum AND status = 'completed'
                ORDER BY started_at DESC
                LIMIT 1
                """
            ),
            {"checksum": checksum},
        ).fetchone()
    return row[0] if row else None


def run_ingest(
    engine: Engine,
    ingestor: SourceIngestor,
    *,
    source_path: Path,
    force: bool = False,
    archive_raw: bool = True,
) -> IngestResult:
    checksum = file_sha256(source_path)
    if not force:
        existing = _find_run_by_checksum(engine, checksum)
        if existing:
            logger.info("Ingest skipped: checksum already ingested (run %s)", existing)
            return IngestResult(
                ingest_run_id=existing,
                records_ingested=0,
                records_skipped_existing=ingestor.discover(),
                input_checksum=checksum,
                reused_existing_run=True,
            )

    run_id = str(uuid.uuid4())
    started = _utc_now()
    total = ingestor.discover()

    archive_uri: str | None = None
    if archive_raw:
        dest_dir = project_root() / "data" / "raw" / run_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / source_path.name
        shutil.copy2(source_path, dest_file)
        archive_uri = dest_file.relative_to(project_root()).as_posix()

    ingested = 0
    skipped = 0

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ingest_run (
                    id, source_type, started_at, status, input_checksum, record_count, metadata_json
                )
                VALUES (:id, :source_type, :started, 'running', :checksum, :count, :meta)
                """
            ),
            {
                "id": run_id,
                "source_type": ingestor.source_type,
                "started": started,
                "checksum": checksum,
                "count": total,
                "meta": json.dumps(
                    {
                        "source_file": source_path.name,
                        "archive_uri": archive_uri,
                    }
                ),
            },
        )

        for ref in ingestor.iter_records():
            exists = conn.execute(
                text(
                    """
                    SELECT id FROM raw_record
                    WHERE source_type = :source_type AND source_native_id = :native_id
                    """
                ),
                {
                    "source_type": ingestor.source_type,
                    "native_id": ref.source_native_id,
                },
            ).fetchone()
            if exists:
                skipped += 1
                continue

            raw_id = str(uuid.uuid4())
            conn.execute(
                text(
                    """
                    INSERT INTO raw_record (
                        id, ingest_run_id, source_type, source_native_id,
                        payload_json, content_uri
                    )
                    VALUES (:id, :run_id, :source_type, :native_id, :payload, :uri)
                    """
                ),
                {
                    "id": raw_id,
                    "run_id": run_id,
                    "source_type": ingestor.source_type,
                    "native_id": ref.source_native_id,
                    "payload": json.dumps(ref.payload, ensure_ascii=False),
                    "uri": archive_uri,
                },
            )
            ingested += 1

        conn.execute(
            text(
                """
                UPDATE ingest_run
                SET status = 'completed', finished_at = :finished, record_count = :count
                WHERE id = :id
                """
            ),
            {
                "id": run_id,
                "finished": _utc_now(),
                "count": ingested,
            },
        )

    logger.info(
        "Ingest complete run=%s ingested=%s skipped_existing_native_id=%s",
        run_id,
        ingested,
        skipped,
    )
    return IngestResult(
        ingest_run_id=run_id,
        records_ingested=ingested,
        records_skipped_existing=skipped,
        input_checksum=checksum,
        reused_existing_run=False,
    )
