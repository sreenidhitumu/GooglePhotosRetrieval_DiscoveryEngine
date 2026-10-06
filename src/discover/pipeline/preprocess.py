from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

from discover.pipeline.noise import evaluate_noise
from discover.pipeline.normalize import normalize_raw_record
from discover.text_utils import combined_text

logger = logging.getLogger(__name__)


@dataclass
class PreprocessReport:
    raw_seen: int = 0
    already_canonical: int = 0
    canonical_created: int = 0
    excluded_noise: int = 0
    exact_duplicates: int = 0
    near_duplicates: int = 0
    failed: int = 0

    def to_dict(self) -> dict:
        return {
            "raw_seen": self.raw_seen,
            "already_canonical": self.already_canonical,
            "canonical_created": self.canonical_created,
            "excluded_noise": self.excluded_noise,
            "exact_duplicates": self.exact_duplicates,
            "near_duplicates": self.near_duplicates,
            "failed": self.failed,
            "canonical_total": self.canonical_created + self.already_canonical,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _near_duplicate_score(a: str, b: str) -> float:
    """Lightweight similarity for optional near-dup detection (Phase 1)."""
    from difflib import SequenceMatcher

    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def run_preprocess(engine: Engine, *, dry_run: bool = False) -> PreprocessReport:
    report = PreprocessReport()

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT r.id, r.ingest_run_id, r.source_type, r.payload_json
                FROM raw_record r
                LEFT JOIN canonical_record c ON c.raw_record_id = r.id
                ORDER BY r.created_at, r.id
                """
            )
        ).fetchall()

    # Build in-memory index of content hashes for near-dup hints
    hash_to_canonical: dict[str, str] = {}
    canonical_text_by_id: dict[str, str] = {}

    with engine.connect() as conn:
        for ch_row in conn.execute(
            text("SELECT id, content_hash, title, body FROM canonical_record")
        ):
            cid, chash, title, body = ch_row
            hash_to_canonical[chash] = cid
            canonical_text_by_id[cid] = combined_text(title, body)

    for row in rows:
        raw_id, ingest_run_id, source_type, payload_json = row
        report.raw_seen += 1

        with engine.connect() as conn:
            existing = conn.execute(
                text("SELECT id FROM canonical_record WHERE raw_record_id = :raw_id"),
                {"raw_id": raw_id},
            ).fetchone()
        if existing:
            report.already_canonical += 1
            continue

        try:
            payload = json.loads(payload_json)
            draft = normalize_raw_record(source_type, payload)
        except Exception as exc:
            report.failed += 1
            logger.warning("normalize failed raw_id=%s: %s", raw_id, exc)
            continue

        noise = evaluate_noise(draft)
        if noise.exclude:
            report.excluded_noise += 1
            if not dry_run:
                _insert_excluded_noise(
                    engine,
                    raw_record_id=raw_id,
                    ingest_run_id=ingest_run_id,
                    reason=noise.reason or "noise",
                    detail=noise.detail,
                )
            continue

        primary_id = hash_to_canonical.get(draft.content_hash)
        if primary_id:
            report.exact_duplicates += 1
            if not dry_run:
                _insert_duplicate_group(
                    engine,
                    primary_canonical_id=primary_id,
                    duplicate_raw_record_id=raw_id,
                    similarity_score=1.0,
                    reason="exact_content_hash",
                )
            continue

        combined = combined_text(draft.title, draft.body)
        near_primary: str | None = None
        near_score = 0.0
        for cid, existing_text in canonical_text_by_id.items():
            if abs(len(existing_text) - len(combined)) > max(50, len(combined) * 0.1):
                continue
            score = _near_duplicate_score(
                combined[:4000].casefold(), existing_text[:4000].casefold()
            )
            if score >= 0.97 and score > near_score:
                near_score = score
                near_primary = cid

        if near_primary and near_score >= 0.97:
            report.near_duplicates += 1
            if not dry_run:
                _insert_duplicate_group(
                    engine,
                    primary_canonical_id=near_primary,
                    duplicate_raw_record_id=raw_id,
                    similarity_score=near_score,
                    reason="near_duplicate_text",
                )
            continue

        report.canonical_created += 1
        if dry_run:
            continue

        canonical_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO canonical_record (
                        id, raw_record_id, source_type, title, body,
                        author_handle, posted_at, permalink, content_hash, metadata_json
                    )
                    VALUES (
                        :id, :raw_id, :source_type, :title, :body,
                        :author, :posted_at, :permalink, :content_hash, :metadata
                    )
                    """
                ),
                {
                    "id": canonical_id,
                    "raw_id": raw_id,
                    "source_type": draft.source_type,
                    "title": draft.title,
                    "body": draft.body if draft.body else combined,
                    "author": draft.author_handle,
                    "posted_at": draft.posted_at,
                    "permalink": draft.permalink,
                    "content_hash": draft.content_hash,
                    "metadata": json.dumps(draft.metadata, ensure_ascii=False),
                },
            )

        hash_to_canonical[draft.content_hash] = canonical_id
        canonical_text_by_id[canonical_id] = combined

    logger.info("preprocess report: %s", report.to_dict())
    return report


def _insert_excluded_noise(
    engine: Engine,
    *,
    raw_record_id: str,
    ingest_run_id: str,
    reason: str,
    detail: str | None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO excluded_noise (
                    id, raw_record_id, ingest_run_id, reason, detail
                )
                VALUES (:id, :raw_id, :ingest_run_id, :reason, :detail)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "raw_id": raw_record_id,
                "ingest_run_id": ingest_run_id,
                "reason": reason,
                "detail": detail,
            },
        )


def _insert_duplicate_group(
    engine: Engine,
    *,
    primary_canonical_id: str,
    duplicate_raw_record_id: str,
    similarity_score: float,
    reason: str,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO duplicate_group (
                    id, primary_canonical_id, duplicate_raw_record_id,
                    similarity_score, reason
                )
                VALUES (:id, :primary, :dup_raw, :score, :reason)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "primary": primary_canonical_id,
                "dup_raw": duplicate_raw_record_id,
                "score": similarity_score,
                "reason": reason,
            },
        )
