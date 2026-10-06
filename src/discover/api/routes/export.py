from __future__ import annotations

import csv
import io
import json
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from discover.api.dependencies import get_db_connection

router = APIRouter(prefix="/export", tags=["Export"])


@router.get("/dataset")
def export_dataset(
    format: str = Query("json", pattern="^(json|csv)$", description="Export format: json or csv"),
    analysis_run_id: Optional[str] = Query(None, description="Filter cluster/relevance by analysis_run_id"),
    conn: sqlite3.Connection = Depends(get_db_connection),
):
    sql = """
        SELECT 
            c.id AS record_id,
            c.source_type,
            c.title,
            c.body,
            c.author_handle,
            c.posted_at,
            c.permalink,
            c.content_hash,
            r.is_relevant,
            r.confidence AS relevance_confidence,
            r.rationale AS relevance_rationale,
            u.structured_fields_json,
            u.evidence_spans_json,
            cl.id AS cluster_id,
            cl.label AS cluster_label,
            os.composite_rank AS opportunity_rank
        FROM canonical_record c
        LEFT JOIN relevance_result r ON c.id = r.record_id
        LEFT JOIN ux_extraction u ON c.id = u.record_id
        LEFT JOIN cluster_member cm ON c.id = cm.record_id
        LEFT JOIN cluster cl ON cm.cluster_id = cl.id
        LEFT JOIN opportunity_score os ON cl.id = os.cluster_id
        WHERE 1=1
    """
    params: list[object] = []
    if analysis_run_id:
        sql += " AND (cl.analysis_run_id = ? OR r.analysis_run_id = ?)"
        params.extend([analysis_run_id, analysis_run_id])

    sql += " ORDER BY c.created_at DESC"

    rows = conn.execute(sql, params).fetchall()

    export_items = []
    for row in rows:
        structured_fields = json.loads(row["structured_fields_json"]) if row["structured_fields_json"] else None
        evidence_spans = json.loads(row["evidence_spans_json"]) if row["evidence_spans_json"] else None

        export_items.append(
            {
                "record_id": row["record_id"],
                "source_type": row["source_type"],
                "title": row["title"],
                "body": row["body"],
                "author_handle": row["author_handle"],
                "posted_at": row["posted_at"],
                "permalink": row["permalink"],
                "content_hash": row["content_hash"],
                "is_relevant": bool(row["is_relevant"]) if row["is_relevant"] is not None else None,
                "relevance_confidence": row["relevance_confidence"],
                "relevance_rationale": row["relevance_rationale"],
                "structured_fields": structured_fields,
                "evidence_spans": evidence_spans,
                "cluster_id": row["cluster_id"],
                "cluster_label": row["cluster_label"],
                "opportunity_rank": row["opportunity_rank"],
            }
        )

    if format == "json":
        return JSONResponse(
            content={"total_records": len(export_items), "records": export_items},
            headers={"Content-Disposition": "attachment; filename=discovery_dataset_export.json"},
        )

    # CSV format
    output = io.StringIO()
    fieldnames = [
        "record_id",
        "source_type",
        "title",
        "body",
        "author_handle",
        "posted_at",
        "permalink",
        "content_hash",
        "is_relevant",
        "relevance_confidence",
        "relevance_rationale",
        "structured_fields",
        "evidence_spans",
        "cluster_id",
        "cluster_label",
        "opportunity_rank",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for item in export_items:
        row_copy = dict(item)
        row_copy["structured_fields"] = json.dumps(item["structured_fields"]) if item["structured_fields"] else ""
        row_copy["evidence_spans"] = json.dumps(item["evidence_spans"]) if item["evidence_spans"] else ""
        writer.writerow(row_copy)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=discovery_dataset_export.csv"},
    )
