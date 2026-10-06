from __future__ import annotations

import json
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from discover.api.dependencies import get_db_connection
from discover.api.schemas import (
    RecordClusterMembership,
    RecordDetailResponse,
    RecordListResponse,
    RecordSummary,
    RelevanceDetail,
    ResearchThemeDTO,
    UXExtractionDetail,
)
from discover.api.theme_service import (
    BASELINE_RUN_ID,
    get_record_theme_mapping,
    get_validated_themes,
)

router = APIRouter(prefix="/records", tags=["Records"])


@router.get("", response_model=RecordListResponse)
def list_records(
    source_type: Optional[str] = Query(None, description="Filter by source type (e.g. reddit)"),
    is_relevant: Optional[bool] = Query(None, description="Filter by relevance status"),
    cluster_id: Optional[str] = Query(None, description="Filter by exploratory machine cluster ID"),
    theme_id: Optional[str] = Query(None, description="Filter by validated research theme ID (T1, T2, T3, T4, T5)"),
    q: Optional[str] = Query(None, description="Search text in body or title"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db_connection),
):
    theme_mapping = get_record_theme_mapping(conn)

    query_parts = [
        """
        SELECT 
            c.id, c.source_type, c.title, c.body, c.author_handle, c.posted_at, c.permalink,
            r.is_relevant, r.confidence AS relevance_confidence,
            cl.id AS cluster_id, cl.label AS cluster_label
        FROM canonical_record c
        LEFT JOIN relevance_result r ON c.id = r.record_id AND r.analysis_run_id = ?
        LEFT JOIN cluster_member cm ON c.id = cm.record_id
        LEFT JOIN cluster cl ON cm.cluster_id = cl.id
        WHERE 1=1
        """
    ]
    params: list[object] = [BASELINE_RUN_ID]

    if source_type:
        query_parts.append("AND c.source_type = ?")
        params.append(source_type)

    if is_relevant is not None:
        query_parts.append("AND r.is_relevant = ?")
        params.append(1 if is_relevant else 0)

    if cluster_id:
        query_parts.append("AND cm.cluster_id = ?")
        params.append(cluster_id)

    if q:
        query_parts.append("AND (c.title LIKE ? OR c.body LIKE ?)")
        search_pattern = f"%{q}%"
        params.extend([search_pattern, search_pattern])

    # If theme_id is specified, filter matching record IDs and enforce is_relevant=1
    matching_theme_rids: set[str] | None = None
    if theme_id:
        query_parts.append("AND r.is_relevant = 1")
        matching_theme_rids = set()
        for rid, t_items in theme_mapping.items():
            if any(t[0] == theme_id or t[0].startswith(theme_id + "_") for t in t_items):
                matching_theme_rids.add(rid)

    all_rows = conn.execute(" ".join(query_parts) + " ORDER BY c.created_at DESC", params).fetchall()

    if matching_theme_rids is not None:
        filtered_rows = [row for row in all_rows if row["id"] in matching_theme_rids]
    else:
        filtered_rows = all_rows

    total = len(filtered_rows)
    paged_rows = filtered_rows[offset : offset + limit]

    records = []
    for row in paged_rows:
        rid = row["id"]
        t_items = theme_mapping.get(rid, [])
        t_ids = [item[0] for item in t_items]
        t_titles = [item[1] for item in t_items]

        records.append(
            RecordSummary(
                id=rid,
                source_type=row["source_type"],
                title=row["title"],
                body=row["body"],
                author_handle=row["author_handle"],
                posted_at=row["posted_at"],
                permalink=row["permalink"],
                is_relevant=bool(row["is_relevant"]) if row["is_relevant"] is not None else None,
                relevance_confidence=row["relevance_confidence"],
                cluster_id=row["cluster_id"],
                cluster_label=row["cluster_label"],
                theme_ids=t_ids,
                theme_titles=t_titles,
            )
        )

    return RecordListResponse(
        total=total,
        limit=limit,
        offset=offset,
        records=records,
    )


@router.get("/{record_id}", response_model=RecordDetailResponse)
def get_record_detail(
    record_id: str,
    conn: sqlite3.Connection = Depends(get_db_connection),
):
    c_row = conn.execute(
        """
        SELECT id, raw_record_id, source_type, title, body, author_handle, posted_at, permalink, content_hash, metadata_json, created_at
        FROM canonical_record
        WHERE id = ?
        """,
        (record_id,),
    ).fetchone()

    if not c_row:
        raise HTTPException(status_code=404, detail=f"Record '{record_id}' not found")

    raw_payload = None
    if c_row["raw_record_id"]:
        raw_row = conn.execute(
            "SELECT payload_json FROM raw_record WHERE id = ?",
            (c_row["raw_record_id"],),
        ).fetchone()
        if raw_row and raw_row["payload_json"]:
            try:
                raw_payload = json.loads(raw_row["payload_json"])
            except json.JSONDecodeError:
                raw_payload = {"raw": raw_row["payload_json"]}

    rel_row = conn.execute(
        """
        SELECT id, analysis_run_id, is_relevant, confidence, rationale, model_id, created_at
        FROM relevance_result
        WHERE record_id = ? AND analysis_run_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (record_id, BASELINE_RUN_ID),
    ).fetchone()

    relevance = None
    if rel_row:
        relevance = RelevanceDetail(
            id=rel_row["id"],
            analysis_run_id=rel_row["analysis_run_id"],
            is_relevant=bool(rel_row["is_relevant"]) if rel_row["is_relevant"] is not None else None,
            confidence=rel_row["confidence"],
            rationale=rel_row["rationale"],
            model_id=rel_row["model_id"],
            created_at=rel_row["created_at"],
        )

    ext_row = conn.execute(
        """
        SELECT id, analysis_run_id, structured_fields_json, evidence_spans_json, model_id, created_at
        FROM ux_extraction
        WHERE record_id = ? AND analysis_run_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (record_id, BASELINE_RUN_ID),
    ).fetchone()

    extraction = None
    if ext_row:
        fields = json.loads(ext_row["structured_fields_json"]) if ext_row["structured_fields_json"] else None
        spans = json.loads(ext_row["evidence_spans_json"]) if ext_row["evidence_spans_json"] else None
        extraction = UXExtractionDetail(
            id=ext_row["id"],
            analysis_run_id=ext_row["analysis_run_id"],
            structured_fields=fields,
            evidence_spans=spans,
            model_id=ext_row["model_id"],
            created_at=ext_row["created_at"],
        )

    cluster_rows = conn.execute(
        """
        SELECT cm.cluster_id, cl.label, cl.summary, cm.score
        FROM cluster_member cm
        JOIN cluster cl ON cm.cluster_id = cl.id
        WHERE cm.record_id = ?
        """,
        (record_id,),
    ).fetchall()

    clusters = [
        RecordClusterMembership(
            cluster_id=crow["cluster_id"],
            cluster_label=crow["label"],
            cluster_summary=crow["summary"],
            score=crow["score"],
        )
        for crow in cluster_rows
    ]

    # Theme details
    all_themes = get_validated_themes()
    theme_mapping = get_record_theme_mapping(conn)
    record_t_items = theme_mapping.get(record_id, [])
    record_t_ids = {t[0] for t in record_t_items}
    matched_themes = [t for t in all_themes if t.id in record_t_ids or any(t.id.startswith(tid) for tid in record_t_ids)]

    metadata = json.loads(c_row["metadata_json"]) if c_row["metadata_json"] else None

    return RecordDetailResponse(
        id=c_row["id"],
        raw_record_id=c_row["raw_record_id"],
        source_type=c_row["source_type"],
        title=c_row["title"],
        body=c_row["body"],
        author_handle=c_row["author_handle"],
        posted_at=c_row["posted_at"],
        permalink=c_row["permalink"],
        content_hash=c_row["content_hash"],
        metadata=metadata,
        created_at=c_row["created_at"],
        raw_payload=raw_payload,
        relevance=relevance,
        extraction=extraction,
        clusters=clusters,
        themes=matched_themes,
    )
