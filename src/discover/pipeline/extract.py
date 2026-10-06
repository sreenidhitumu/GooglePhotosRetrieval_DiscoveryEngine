from __future__ import annotations

import json
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from discover.config import Settings
from discover.llm.batch_pack import pack_relevance_batches
from discover.llm.extraction_gateway import ExtractionGateway, get_extraction_gateway
from discover.llm.extraction_schemas import count_populated_fields
from discover.llm.rate_limit import SlidingWindowRateLimiter
from discover.llm.token_estimate import estimate_batch_total_tokens

logger = logging.getLogger(__name__)


@dataclass
class ExtractOptions:
    resume: bool = False
    limit: int | None = None
    analysis_run_id: str | None = None
    force: bool = False
    llm_provider: str | None = None
    batch_size: int | None = None
    research_set_path: Path | None = None


@dataclass
class ExtractReport:
    relevance_analysis_run_id: str = ""
    relevant_total: int = 0
    already_processed: int = 0
    extracted: int = 0
    extraction_failed: int = 0
    sparse_extractions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevance_analysis_run_id": self.relevance_analysis_run_id,
            "relevant_total": self.relevant_total,
            "already_processed": self.already_processed,
            "extracted": self.extracted,
            "extraction_failed": self.extraction_failed,
            "sparse_extractions": self.sparse_extractions,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_research_set_record_ids(path: Path) -> frozenset[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != "high_confidence_research_set":
        raise ValueError(f"Unsupported research set manifest: {path}")
    ids: list[str] = []
    for rec in data.get("records", []):
        if isinstance(rec, dict) and rec.get("record_id"):
            ids.append(str(rec["record_id"]))
    if not ids:
        raise ValueError(f"No record_id entries in research set: {path}")
    return frozenset(ids)


def _resolve_relevance_analysis_run_id(engine: Engine, opts: ExtractOptions) -> str:
    if opts.analysis_run_id:
        return opts.analysis_run_id
    if opts.resume:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT analysis_run_id
                    FROM ux_extraction
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
            ).fetchone()
        if row:
            return row[0]
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT rr.analysis_run_id
                FROM relevance_result rr
                WHERE rr.is_relevant = 1 AND rr.analysis_status = 'completed'
                GROUP BY rr.analysis_run_id
                ORDER BY COUNT(*) DESC, MAX(rr.analysis_run_id) DESC
                LIMIT 1
                """
            )
        ).fetchone()
    if not row:
        raise ValueError(
            "No relevance analysis run with relevant records; run relevance stage first "
            "or pass --analysis-run-id"
        )
    return row[0]


def _fetch_relevant_records(engine: Engine, analysis_run_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT cr.id, cr.source_type, cr.title, cr.body, cr.permalink
                FROM relevance_result rr
                JOIN canonical_record cr ON cr.id = rr.record_id
                WHERE rr.analysis_run_id = :aid
                  AND rr.is_relevant = 1
                  AND rr.analysis_status = 'completed'
                ORDER BY cr.created_at, cr.id
                """
            ),
            {"aid": analysis_run_id},
        ).fetchall()
    return [
        {
            "record_id": r[0],
            "source_type": r[1],
            "title": r[2],
            "body": r[3],
            "permalink": r[4],
        }
        for r in rows
    ]


def _has_extraction(
    engine: Engine, record_id: str, analysis_run_id: str, force: bool
) -> bool:
    if force:
        return False
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT extraction_status FROM ux_extraction
                WHERE record_id = :rid AND analysis_run_id = :aid
                """
            ),
            {"rid": record_id, "aid": analysis_run_id},
        ).fetchone()
    return bool(row and row[0] == "completed")


def _save_extraction(
    engine: Engine,
    *,
    analysis_run_id: str,
    gateway: ExtractionGateway,
    item: dict[str, Any],
) -> None:
    structured = item["structured_fields"]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ux_extraction (
                    id, record_id, analysis_run_id,
                    structured_fields_json, evidence_spans_json,
                    model_id, extraction_status, prompt_version
                )
                VALUES (
                    :id, :rid, :aid,
                    :structured, :evidence,
                    :model_id, 'completed', :prompt_version
                )
                ON CONFLICT(record_id, analysis_run_id) DO UPDATE SET
                    structured_fields_json = excluded.structured_fields_json,
                    evidence_spans_json = excluded.evidence_spans_json,
                    model_id = excluded.model_id,
                    extraction_status = excluded.extraction_status,
                    prompt_version = excluded.prompt_version,
                    error_message = NULL
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "rid": item["record_id"],
                "aid": analysis_run_id,
                "structured": json.dumps(structured, ensure_ascii=False),
                "evidence": json.dumps(item.get("evidence_spans") or {}, ensure_ascii=False),
                "model_id": gateway.model_id,
                "prompt_version": gateway.prompt_version,
            },
        )


def _save_extraction_failure(
    engine: Engine,
    *,
    record_id: str,
    analysis_run_id: str,
    gateway: ExtractionGateway,
    error: str,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ux_extraction (
                    id, record_id, analysis_run_id,
                    structured_fields_json, evidence_spans_json,
                    model_id, extraction_status, error_message, prompt_version
                )
                VALUES (
                    :id, :rid, :aid,
                    '{}', '{}',
                    :model_id, 'failed', :error, :prompt_version
                )
                ON CONFLICT(record_id, analysis_run_id) DO UPDATE SET
                    extraction_status = excluded.extraction_status,
                    error_message = excluded.error_message,
                    prompt_version = excluded.prompt_version
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "rid": record_id,
                "aid": analysis_run_id,
                "model_id": gateway.model_id,
                "error": error[:2000],
                "prompt_version": gateway.prompt_version,
            },
        )


def _save_checkpoint(
    engine: Engine, pipeline_run_id: str, batch_index: int, cursor: dict | None = None
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO job_checkpoint (
                    id, pipeline_run_id, stage, last_batch_index, cursor_json, updated_at
                )
                VALUES (:id, :pr, 'extract', :idx, :cursor, :updated)
                ON CONFLICT(pipeline_run_id, stage) DO UPDATE SET
                    last_batch_index = excluded.last_batch_index,
                    cursor_json = excluded.cursor_json,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "pr": pipeline_run_id,
                "idx": batch_index,
                "cursor": json.dumps(cursor or {}),
                "updated": _utc_now(),
            },
        )


def run_extract(
    engine: Engine,
    settings: Settings,
    opts: ExtractOptions,
    *,
    dry_run: bool = False,
    pipeline_run_id: str | None = None,
) -> ExtractReport:
    gateway = get_extraction_gateway(settings, opts.llm_provider)
    analysis_run_id = _resolve_relevance_analysis_run_id(engine, opts)
    report = ExtractReport(relevance_analysis_run_id=analysis_run_id)

    records = _fetch_relevant_records(engine, analysis_run_id)
    if opts.research_set_path:
        allowed = load_research_set_record_ids(opts.research_set_path)
        records = [r for r in records if r["record_id"] in allowed]
        logger.info(
            "Extraction limited to research set %s (%s records)",
            opts.research_set_path,
            len(records),
        )
    report.relevant_total = len(records)

    pending: list[dict[str, Any]] = []
    for rec in records:
        if _has_extraction(engine, rec["record_id"], analysis_run_id, opts.force):
            report.already_processed += 1
            continue
        pending.append(rec)

    max_records = opts.batch_size or settings.relevance_batch_size
    max_tokens = settings.relevance_max_batch_input_tokens
    batches = pack_relevance_batches(
        pending,
        max_records_per_batch=max_records,
        max_input_tokens_per_batch=max_tokens,
    )
    if pending:
        logger.info(
            "Extraction LLM plan: %s relevant records, %s pending, %s API batch(es)",
            len(records),
            len(pending),
            len(batches),
        )

    use_gemini_limits = gateway.model_id.startswith("gemini:")
    rate_limiter = SlidingWindowRateLimiter(
        requests_per_minute=settings.gemini_rpm_limit if use_gemini_limits else None,
        tokens_per_minute=settings.gemini_tpm_limit if use_gemini_limits else None,
        min_interval_seconds=settings.relevance_batch_delay_seconds
        if use_gemini_limits
        else 0.0,
    )

    batch_index = 0
    processed_for_limit = 0
    llm_calls = 0
    max_calls = settings.relevance_max_llm_calls

    for batch in batches:
        if max_calls is not None and llm_calls >= max_calls:
            logger.info("Reached RELEVANCE_MAX_LLM_CALLS=%s during extract", max_calls)
            break
        if opts.limit is not None and processed_for_limit >= opts.limit:
            break
        if opts.limit is not None:
            remaining = opts.limit - processed_for_limit
            if remaining <= 0:
                break
            if len(batch) > remaining:
                batch = batch[:remaining]

        batch_index += 1
        if dry_run:
            report.extracted += len(batch)
            processed_for_limit += len(batch)
            continue

        try:
            est_tokens = estimate_batch_total_tokens(batch)
            rate_limiter.wait_for_slot(est_tokens)
            llm_calls += 1
            results = gateway.extract_batch(batch)
            rate_limiter.record_request(est_tokens)
            for item in results:
                _save_extraction(
                    engine, analysis_run_id=analysis_run_id, gateway=gateway, item=item
                )
                report.extracted += 1
                processed_for_limit += 1
                if item.get("extraction_sparse"):
                    report.sparse_extractions += 1
        except Exception as exc:
            logger.exception("Extraction batch %s failed: %s", batch_index, exc)
            for rec_fail in batch:
                _save_extraction_failure(
                    engine,
                    record_id=rec_fail["record_id"],
                    analysis_run_id=analysis_run_id,
                    gateway=gateway,
                    error=str(exc),
                )
                report.extraction_failed += 1
                processed_for_limit += 1

        if pipeline_run_id:
            _save_checkpoint(
                engine,
                pipeline_run_id,
                batch_index,
                {"analysis_run_id": analysis_run_id},
            )

    logger.info("extract report: %s", report.to_dict())
    return report


def export_extraction_summary(engine: Engine, analysis_run_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        totals = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN extraction_status = 'completed' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN extraction_status = 'failed' THEN 1 ELSE 0 END)
                FROM ux_extraction
                WHERE analysis_run_id = :aid
                """
            ),
            {"aid": analysis_run_id},
        ).fetchone()

        relevant = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM relevance_result
                WHERE analysis_run_id = :aid AND is_relevant = 1
                  AND analysis_status = 'completed'
                """
            ),
            {"aid": analysis_run_id},
        ).scalar()

        sparse = 0
        populated_hist: dict[int, int] = {}
        rows = conn.execute(
            text(
                """
                SELECT structured_fields_json FROM ux_extraction
                WHERE analysis_run_id = :aid AND extraction_status = 'completed'
                """
            ),
            {"aid": analysis_run_id},
        ).fetchall()
        for (raw,) in rows:
            fields = json.loads(raw or "{}")
            n = count_populated_fields(fields)
            populated_hist[n] = populated_hist.get(n, 0) + 1
            if n < 3:
                sparse += 1

    rel = int(relevant or 0)
    ext = int(totals[0] or 0)
    return {
        "analysis_run_id": analysis_run_id,
        "relevant_records": rel,
        "counts": {
            "extraction_rows": ext,
            "completed": int(totals[1] or 0),
            "failed": int(totals[2] or 0),
            "missing_extraction": max(0, rel - ext),
            "sparse_lt_3_fields": sparse,
        },
        "populated_field_histogram": populated_hist,
        "benchmark_ge_3_non_null_fields_pct": round(
            (sum(c for k, c in populated_hist.items() if k >= 3) / max(1, ext)) * 100,
            1,
        ),
    }


def export_extraction_qa_sample(
    engine: Engine,
    analysis_run_id: str,
    *,
    sample_size: int = 20,
    seed: int = 42,
) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT cr.source_type, cr.id, cr.title, cr.body, cr.permalink,
                       ux.structured_fields_json, ux.evidence_spans_json, ux.model_id
                FROM ux_extraction ux
                JOIN canonical_record cr ON cr.id = ux.record_id
                WHERE ux.analysis_run_id = :aid AND ux.extraction_status = 'completed'
                """
            ),
            {"aid": analysis_run_id},
        ).fetchall()

    by_source: dict[str, list] = {}
    for row in rows:
        by_source.setdefault(row[0] or "unknown", []).append(row)

    rng = random.Random(seed)
    picked: list = []
    sources = sorted(by_source.keys())
    per_source = max(1, sample_size // max(1, len(sources)))
    for st in sources:
        pool = list(by_source[st])
        rng.shuffle(pool)
        picked.extend(pool[:per_source])
    if len(picked) < sample_size:
        rest = [r for r in rows if r not in picked]
        rng.shuffle(rest)
        picked.extend(rest[: sample_size - len(picked)])
    picked = picked[:sample_size]

    out: list[dict[str, Any]] = []
    for row in picked:
        structured = json.loads(row[5] or "{}")
        out.append(
            {
                "record_id": row[1],
                "source_type": row[0],
                "permalink": row[4],
                "title": row[2],
                "body_excerpt": (row[3] or "")[:400],
                "structured_fields": structured,
                "evidence_spans": json.loads(row[6] or "{}"),
                "populated_field_count": count_populated_fields(structured),
                "model_id": row[7],
            }
        )
    return out
