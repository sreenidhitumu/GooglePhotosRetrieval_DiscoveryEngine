from __future__ import annotations

import json
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from discover.api.dependencies import get_db_connection
from discover.api.schemas import (
    ClusterDTO,
    ClusterListResponse,
    ClusterMemberItem,
    ClusterMembersResponse,
    ThemeListResponse,
)
from discover.api.theme_service import get_validated_themes, load_theme_validation_data

router = APIRouter(prefix="/clusters", tags=["Clusters"])


@router.get("/themes", response_model=ThemeListResponse)
def list_research_themes():
    data = load_theme_validation_data()
    themes = get_validated_themes()
    return ThemeListResponse(
        analysis_run_id=data.get("analysis_run_id", "d2c78beb-e832-4b0a-b930-0212aeb81481"),
        total_relevant_records=190,
        total_themes=len(themes),
        themes=themes,
    )


@router.get("", response_model=ClusterListResponse)
def list_clusters(
    analysis_run_id: Optional[str] = Query(None, description="Filter by cluster analysis_run_id"),
    conn: sqlite3.Connection = Depends(get_db_connection),
):
    sql = """
        SELECT id, analysis_run_id, label, summary, member_count, metadata_json, created_at
        FROM cluster
    """
    params: list[object] = []
    if analysis_run_id:
        sql += " WHERE analysis_run_id = ?"
        params.append(analysis_run_id)

    sql += " ORDER BY member_count DESC, created_at DESC"

    rows = conn.execute(sql, params).fetchall()

    clusters: list[ClusterDTO] = []
    for r in rows:
        meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
        exemplars = meta.get("exemplar_record_ids", []) or meta.get("exemplars", [])

        clusters.append(
            ClusterDTO(
                id=r["id"],
                analysis_run_id=r["analysis_run_id"],
                label=r["label"],
                summary=r["summary"],
                member_count=r["member_count"],
                metadata=meta,
                exemplars=exemplars,
                created_at=r["created_at"],
                cluster_type="exploratory_machine_cluster",
            )
        )

    return ClusterListResponse(total=len(clusters), clusters=clusters)


@router.get("/{cluster_id}/members", response_model=ClusterMembersResponse)
def get_cluster_members(
    cluster_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db_connection),
):
    # Verify cluster exists
    cl_row = conn.execute(
        "SELECT id FROM cluster WHERE id = ?", (cluster_id,)
    ).fetchone()
    if not cl_row:
        raise HTTPException(status_code=404, detail=f"Cluster '{cluster_id}' not found")

    total = conn.execute(
        "SELECT COUNT(*) FROM cluster_member WHERE cluster_id = ?",
        (cluster_id,),
    ).fetchone()[0]

    member_rows = conn.execute(
        """
        SELECT cm.record_id, cm.score, c.title, c.body, c.permalink
        FROM cluster_member cm
        JOIN canonical_record c ON cm.record_id = c.id
        WHERE cm.cluster_id = ?
        ORDER BY cm.score DESC
        LIMIT ? OFFSET ?
        """,
        (cluster_id, limit, offset),
    ).fetchall()

    members = [
        ClusterMemberItem(
            record_id=r["record_id"],
            title=r["title"],
            body=r["body"],
            permalink=r["permalink"],
            score=r["score"],
        )
        for r in member_rows
    ]

    return ClusterMembersResponse(
        cluster_id=cluster_id,
        total_members=total,
        limit=limit,
        offset=offset,
        members=members,
    )
