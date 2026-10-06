from __future__ import annotations

import sqlite3
from fastapi import APIRouter, Depends
from discover.api.dependencies import get_db_connection
from discover.api.schemas import (
    PipelineStatsResponse,
    SourceStats,
    SourceStatsResponse,
    StageMetric,
)

router = APIRouter(prefix="/stats", tags=["Stats"])


BASELINE_RUN_ID = "d2c78beb-e832-4b0a-b930-0212aeb81481"


@router.get("/sources", response_model=SourceStatsResponse)
def get_source_stats(conn: sqlite3.Connection = Depends(get_db_connection)):
    distinct_sources = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT source_type FROM raw_record UNION SELECT DISTINCT source_type FROM canonical_record"
        ).fetchall()
        if row[0]
    ]

    sources_list: list[SourceStats] = []
    total_raw = 0
    total_canonical = 0
    total_relevant = 0
    total_extracted = 0

    for st in distinct_sources:
        raw_count = conn.execute(
            "SELECT COUNT(*) FROM raw_record WHERE source_type = ?", (st,)
        ).fetchone()[0]

        canonical_count = conn.execute(
            "SELECT COUNT(*) FROM canonical_record WHERE source_type = ?", (st,)
        ).fetchone()[0]

        relevant_count = conn.execute(
            """
            SELECT COUNT(*) FROM relevance_result rr
            JOIN canonical_record cr ON cr.id = rr.record_id
            WHERE cr.source_type = ? AND rr.analysis_run_id = ? AND rr.is_relevant = 1
            AND (cr.permalink IS NULL OR cr.permalink NOT LIKE '%sample01%')
            """,
            (st, BASELINE_RUN_ID),
        ).fetchone()[0]

        extracted_count = conn.execute(
            """
            SELECT COUNT(*) FROM ux_extraction ux
            JOIN canonical_record cr ON cr.id = ux.record_id
            WHERE cr.source_type = ? AND ux.analysis_run_id = ?
            """,
            (st, BASELINE_RUN_ID),
        ).fetchone()[0]

        sources_list.append(
            SourceStats(
                source_type=st,
                raw_count=raw_count,
                canonical_count=canonical_count,
                relevant_count=relevant_count,
                extracted_count=extracted_count,
            )
        )
        total_raw += raw_count
        total_canonical += canonical_count
        total_relevant += relevant_count
        total_extracted += extracted_count

    sources_list.sort(key=lambda s: s.canonical_count, reverse=True)

    return SourceStatsResponse(
        sources=sources_list,
        total_raw=total_raw,
        total_canonical=total_canonical,
        total_relevant=total_relevant,
        total_extracted=total_extracted,
    )


@router.get("/pipeline", response_model=PipelineStatsResponse)
def get_pipeline_stats(conn: sqlite3.Connection = Depends(get_db_connection)):
    pipeline_runs_count = conn.execute(
        "SELECT COUNT(*) FROM pipeline_run"
    ).fetchone()[0]

    analysis_runs = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT id FROM analysis_run ORDER BY created_at DESC"
        ).fetchall()
    ]

    stage_rows = conn.execute(
        """
        SELECT stage, status, updated_at, dry_run, error_message
        FROM pipeline_run
        ORDER BY updated_at DESC
        """
    ).fetchall()

    seen_stages: set[str] = set()
    stage_metrics: list[StageMetric] = []
    for row in stage_rows:
        stg = row["stage"]
        if stg not in seen_stages:
            seen_stages.add(stg)
            stage_metrics.append(
                StageMetric(
                    stage=stg,
                    last_status=row["status"],
                    last_updated_at=row["updated_at"],
                    dry_run=bool(row["dry_run"]),
                    error_message=row["error_message"],
                )
            )

    return PipelineStatsResponse(
        pipeline_runs_count=pipeline_runs_count,
        active_analysis_run_ids=analysis_runs,
        stage_metrics=stage_metrics,
    )
