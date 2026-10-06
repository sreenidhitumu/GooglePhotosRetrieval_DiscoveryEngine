from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from discover.config import Settings
from discover.llm.batch_pack import pack_relevance_batches
from discover.llm.gateway import LLMGateway, get_llm_gateway
from discover.llm.rate_limit import SlidingWindowRateLimiter
from discover.llm.token_estimate import estimate_batch_total_tokens
from discover.calibration_exclusions import (
    CALIBRATION_METRICS_EXCLUDED_PERMALINK_FRAGMENTS,
)
from discover.pipeline.calibration_prefilter import evaluate_calibration_prefilter
from discover.pipeline.gate import evaluate_deterministic_gate

logger = logging.getLogger(__name__)


@dataclass
class RelevanceOptions:
    resume: bool = False
    limit: int | None = None
    analysis_run_id: str | None = None
    force: bool = False
    llm_provider: str | None = None
    batch_size: int | None = None
    bypass_gate: bool = False


@dataclass
class RelevanceReport:
    canonical_total: int = 0
    already_processed: int = 0
    gate_skipped: int = 0
    llm_classified: int = 0
    relevant: int = 0
    not_relevant: int = 0
    analysis_failed: int = 0
    analysis_run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_run_id": self.analysis_run_id,
            "canonical_total": self.canonical_total,
            "already_processed": self.already_processed,
            "gate_skipped": self.gate_skipped,
            "llm_classified": self.llm_classified,
            "relevant": self.relevant,
            "not_relevant": self.not_relevant,
            "analysis_failed": self.analysis_failed,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _create_analysis_run(engine: Engine, gateway: LLMGateway, label: str | None = None) -> str:
    run_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO analysis_run (id, label, model_id, prompt_version)
                VALUES (:id, :label, :model_id, :prompt_version)
                """
            ),
            {
                "id": run_id,
                "label": label or f"relevance_{_utc_now()}",
                "model_id": gateway.model_id,
                "prompt_version": gateway.prompt_version,
            },
        )
    return run_id


def _resolve_analysis_run_id(
    engine: Engine, gateway: LLMGateway, opts: RelevanceOptions
) -> str:
    if opts.analysis_run_id:
        return opts.analysis_run_id
    if opts.bypass_gate and not opts.resume:
        return _create_analysis_run(engine, gateway, label="calibration_bypass_gate")
    if opts.resume:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT ar.id FROM analysis_run ar
                    WHERE ar.prompt_version = :pv
                    ORDER BY ar.created_at DESC
                    LIMIT 1
                    """
                ),
                {"pv": gateway.prompt_version},
            ).fetchone()
        if row:
            return row[0]
    return _create_analysis_run(engine, gateway, label="relevance")


def _fetch_canonical_records(
    engine: Engine, *, source_type: str | None = None
) -> list[dict[str, Any]]:
    query = """
        SELECT id, source_type, title, body, permalink
        FROM canonical_record
    """
    params: dict[str, Any] = {}
    if source_type:
        query += " WHERE source_type = :source_type"
        params["source_type"] = source_type
    query += " ORDER BY created_at, id"
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()
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


def _has_result(
    engine: Engine, record_id: str, analysis_run_id: str, force: bool
) -> bool:
    if force:
        return False
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 FROM relevance_result
                WHERE record_id = :rid AND analysis_run_id = :aid
                AND analysis_status IN ('completed', 'gate_skipped')
                """
            ),
            {"rid": record_id, "aid": analysis_run_id},
        ).fetchone()
        return row is not None


def _save_gate_skip(
    engine: Engine,
    *,
    record_id: str,
    analysis_run_id: str,
    gate_reason: str,
    gateway: LLMGateway,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO relevance_result (
                    id, record_id, analysis_run_id, is_relevant, confidence, rationale,
                    model_id, gate_passed, gate_reason, retrieval_signal_types_json,
                    analysis_status, prompt_version
                )
                VALUES (
                    :id, :rid, :aid, 0, 0.0, :rationale,
                    :model_id, 0, :gate_reason, '[]',
                    'gate_skipped', :prompt_version
                )
                ON CONFLICT(record_id, analysis_run_id) DO UPDATE SET
                    is_relevant = excluded.is_relevant,
                    confidence = excluded.confidence,
                    rationale = excluded.rationale,
                    gate_passed = excluded.gate_passed,
                    gate_reason = excluded.gate_reason,
                    analysis_status = excluded.analysis_status,
                    prompt_version = excluded.prompt_version
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "rid": record_id,
                "aid": analysis_run_id,
                "rationale": f"Deterministic gate: {gate_reason}",
                "model_id": gateway.model_id,
                "gate_reason": gate_reason,
                "prompt_version": gateway.prompt_version,
            },
        )


def _save_llm_result(
    engine: Engine,
    *,
    analysis_run_id: str,
    gateway: LLMGateway,
    item: dict[str, Any],
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO relevance_result (
                    id, record_id, analysis_run_id, is_relevant, confidence, rationale,
                    model_id, gate_passed, gate_reason, retrieval_signal_types_json,
                    analysis_status, prompt_version
                )
                VALUES (
                    :id, :rid, :aid, :is_relevant, :confidence, :rationale,
                    :model_id, 1, 'passed', :signals,
                    'completed', :prompt_version
                )
                ON CONFLICT(record_id, analysis_run_id) DO UPDATE SET
                    is_relevant = excluded.is_relevant,
                    confidence = excluded.confidence,
                    rationale = excluded.rationale,
                    retrieval_signal_types_json = excluded.retrieval_signal_types_json,
                    analysis_status = excluded.analysis_status,
                    gate_passed = excluded.gate_passed,
                    gate_reason = excluded.gate_reason,
                    prompt_version = excluded.prompt_version,
                    error_message = NULL
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "rid": item["record_id"],
                "aid": analysis_run_id,
                "is_relevant": 1 if item["is_relevant"] else 0,
                "confidence": item["confidence"],
                "rationale": item["rationale"],
                "model_id": gateway.model_id,
                "signals": json.dumps(item.get("retrieval_signal_types", [])),
                "prompt_version": gateway.prompt_version,
            },
        )


def _save_failure(
    engine: Engine,
    *,
    record_id: str,
    analysis_run_id: str,
    gateway: LLMGateway,
    error: str,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO relevance_result (
                    id, record_id, analysis_run_id, is_relevant, confidence, rationale,
                    model_id, gate_passed, gate_reason, analysis_status, error_message,
                    prompt_version
                )
                VALUES (
                    :id, :rid, :aid, NULL, NULL, :rationale,
                    :model_id, 1, 'passed', 'analysis_failed', :error,
                    :prompt_version
                )
                ON CONFLICT(record_id, analysis_run_id) DO UPDATE SET
                    analysis_status = excluded.analysis_status,
                    error_message = excluded.error_message
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "rid": record_id,
                "aid": analysis_run_id,
                "rationale": "LLM classification failed",
                "model_id": gateway.model_id,
                "error": error[:2000],
                "prompt_version": gateway.prompt_version,
            },
        )


def _save_checkpoint(
    engine: Engine, pipeline_run_id: str, batch_index: int, cursor: dict | None = None
) -> None:
    cp_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO job_checkpoint (
                    id, pipeline_run_id, stage, last_batch_index, cursor_json, updated_at
                )
                VALUES (:id, :pr, 'relevance', :idx, :cursor, :updated)
                ON CONFLICT(pipeline_run_id, stage) DO UPDATE SET
                    last_batch_index = excluded.last_batch_index,
                    cursor_json = excluded.cursor_json,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "id": cp_id,
                "pr": pipeline_run_id,
                "idx": batch_index,
                "cursor": json.dumps(cursor or {}),
                "updated": _utc_now(),
            },
        )


def run_relevance(
    engine: Engine,
    settings: Settings,
    opts: RelevanceOptions,
    *,
    dry_run: bool = False,
    pipeline_run_id: str | None = None,
) -> RelevanceReport:
    gateway = get_llm_gateway(settings, opts.llm_provider)
    analysis_run_id = _resolve_analysis_run_id(engine, gateway, opts)
    report = RelevanceReport(analysis_run_id=analysis_run_id)

    records = _fetch_canonical_records(
        engine, source_type=None
    )
    report.canonical_total = len(records)
    if opts.bypass_gate:
        logger.info(
            "Relevance calibration mode: deterministic gate bypassed; "
            "minimal prefilter only (empty/removed/artifacts)"
        )

    pending_llm: list[dict[str, Any]] = []
    max_records_per_batch = opts.batch_size or settings.relevance_batch_size
    max_input_tokens = settings.relevance_max_batch_input_tokens
    llm_calls = 0
    max_calls = settings.relevance_max_llm_calls
    batch_index = 0
    processed_for_limit = 0
    use_gemini_limits = gateway.model_id.startswith("gemini:")
    rate_limiter = SlidingWindowRateLimiter(
        requests_per_minute=settings.gemini_rpm_limit if use_gemini_limits else None,
        tokens_per_minute=settings.gemini_tpm_limit if use_gemini_limits else None,
        min_interval_seconds=settings.relevance_batch_delay_seconds
        if use_gemini_limits
        else 0.0,
    )

    for rec in records:
        rid = rec["record_id"]
        if _has_result(engine, rid, analysis_run_id, opts.force):
            report.already_processed += 1
            continue

        if opts.limit is not None and processed_for_limit >= opts.limit:
            break

        if opts.bypass_gate:
            pre = evaluate_calibration_prefilter(rec.get("title"), rec.get("body"))
            if pre.exclude:
                report.gate_skipped += 1
                processed_for_limit += 1
                if not dry_run:
                    _save_gate_skip(
                        engine,
                        record_id=rid,
                        analysis_run_id=analysis_run_id,
                        gate_reason=pre.reason or "calibration_excluded",
                        gateway=gateway,
                    )
                continue
        else:
            gate = evaluate_deterministic_gate(rec.get("title"), rec.get("body"))
            if not gate.passed:
                report.gate_skipped += 1
                processed_for_limit += 1
                if not dry_run:
                    _save_gate_skip(
                        engine,
                        record_id=rid,
                        analysis_run_id=analysis_run_id,
                        gate_reason=gate.reason,
                        gateway=gateway,
                    )
                continue

        pending_llm.append(rec)

    def flush_batch(batch: list[dict[str, Any]]) -> None:
        nonlocal llm_calls, batch_index, processed_for_limit
        if not batch:
            return
        batch_index += 1
        if dry_run:
            report.llm_classified += len(batch)
            processed_for_limit += len(batch)
            return
        try:
            est_tokens = estimate_batch_total_tokens(batch)
            rate_limiter.wait_for_slot(est_tokens)
            llm_calls += 1
            results = gateway.classify_relevance_batch(batch)
            rate_limiter.record_request(est_tokens)
            for item in results:
                _save_llm_result(
                    engine, analysis_run_id=analysis_run_id, gateway=gateway, item=item
                )
                report.llm_classified += 1
                processed_for_limit += 1
        except Exception as exc:
            logger.exception("Batch %s failed: %s", batch_index, exc)
            for rec_fail in batch:
                _save_failure(
                    engine,
                    record_id=rec_fail["record_id"],
                    analysis_run_id=analysis_run_id,
                    gateway=gateway,
                    error=str(exc),
                )
                report.analysis_failed += 1
                processed_for_limit += 1
        if pipeline_run_id:
            _save_checkpoint(
                engine,
                pipeline_run_id,
                batch_index,
                {"analysis_run_id": analysis_run_id},
            )

    llm_batches = pack_relevance_batches(
        pending_llm,
        max_records_per_batch=max_records_per_batch,
        max_input_tokens_per_batch=max_input_tokens,
    )
    if pending_llm:
        logger.info(
            "Relevance LLM plan: %s records in %s API batch(es) "
            "(max %s records, ~%s input tokens/batch cap)",
            len(pending_llm),
            len(llm_batches),
            max_records_per_batch,
            max_input_tokens,
        )

    for batch in llm_batches:
        if max_calls is not None and llm_calls >= max_calls:
            logger.info("Reached RELEVANCE_MAX_LLM_CALLS=%s", max_calls)
            break
        if opts.limit is not None and processed_for_limit >= opts.limit:
            break
        if opts.limit is not None:
            remaining = opts.limit - processed_for_limit
            if remaining <= 0:
                break
            if len(batch) > remaining:
                batch = batch[:remaining]
        flush_batch(batch)

    if not dry_run:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                        SUM(CASE WHEN is_relevant = 1 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN is_relevant = 0 AND analysis_status = 'completed' THEN 1 ELSE 0 END)
                    FROM relevance_result
                    WHERE analysis_run_id = :aid
                    """
                ),
                {"aid": analysis_run_id},
            ).fetchone()
        if row:
            report.relevant = int(row[0] or 0)
            report.not_relevant = int(row[1] or 0)

    logger.info("relevance report: %s", report.to_dict())
    return report


def _calibration_metrics_permalink_sql() -> str:
    clauses = " OR ".join(
        f"cr.permalink LIKE '%' || :frag{i} || '%'"
        for i in range(len(CALIBRATION_METRICS_EXCLUDED_PERMALINK_FRAGMENTS))
    )
    if not clauses:
        return "0"
    return f"({clauses})"


def export_relevance_summary(engine: Engine, analysis_run_id: str) -> dict[str, Any]:
    frag_params = {
        f"frag{i}": frag for i, frag in enumerate(CALIBRATION_METRICS_EXCLUDED_PERMALINK_FRAGMENTS)
    }
    exclude_sql = _calibration_metrics_permalink_sql()
    with engine.connect() as conn:
        totals = conn.execute(
            text(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN analysis_status = 'gate_skipped' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN analysis_status = 'completed' AND is_relevant = 1 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN analysis_status = 'completed' AND is_relevant = 0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN analysis_status = 'analysis_failed' THEN 1 ELSE 0 END)
                FROM relevance_result rr
                JOIN canonical_record cr ON cr.id = rr.record_id
                WHERE rr.analysis_run_id = :aid
                  AND NOT ({exclude_sql})
                """
            ),
            {"aid": analysis_run_id, **frag_params},
        ).fetchone()

        excluded_n = conn.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM relevance_result rr
                JOIN canonical_record cr ON cr.id = rr.record_id
                WHERE rr.analysis_run_id = :aid AND ({exclude_sql})
                """
            ),
            {"aid": analysis_run_id, **frag_params},
        ).scalar()

        gate_reasons = conn.execute(
            text(
                f"""
                SELECT gate_reason, COUNT(*) AS n
                FROM relevance_result rr
                JOIN canonical_record cr ON cr.id = rr.record_id
                WHERE rr.analysis_run_id = :aid AND analysis_status = 'gate_skipped'
                  AND NOT ({exclude_sql})
                GROUP BY gate_reason
                ORDER BY n DESC
                """
            ),
            {"aid": analysis_run_id, **frag_params},
        ).fetchall()

        run_meta = conn.execute(
            text(
                "SELECT model_id, prompt_version, created_at FROM analysis_run WHERE id = :aid"
            ),
            {"aid": analysis_run_id},
        ).fetchone()

    return {
        "analysis_run_id": analysis_run_id,
        "model_id": run_meta[0] if run_meta else None,
        "prompt_version": run_meta[1] if run_meta else None,
        "created_at": run_meta[2] if run_meta else None,
        "counts": {
            "labeled_total": int(totals[0] or 0),
            "gate_skipped": int(totals[1] or 0),
            "relevant": int(totals[2] or 0),
            "not_relevant": int(totals[3] or 0),
            "analysis_failed": int(totals[4] or 0),
            "excluded_calibration_fixtures": int(excluded_n or 0),
        },
        "calibration_metrics_exclude_permalink_fragments": list(
            CALIBRATION_METRICS_EXCLUDED_PERMALINK_FRAGMENTS
        ),
        "gate_skip_reasons": {r[0]: r[1] for r in gate_reasons},
    }
