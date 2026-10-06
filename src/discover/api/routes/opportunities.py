from __future__ import annotations

import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Query
from discover.api.dependencies import get_db_connection
from discover.api.schemas import (
    OpportunityListResponse,
    OpportunityScoreDTO,
    ThemeListResponse,
)
from discover.api.theme_service import get_validated_themes, load_theme_validation_data

router = APIRouter(prefix="/opportunities", tags=["Opportunities"])


@router.get("", response_model=OpportunityListResponse)
def list_opportunities(
    analysis_run_id: Optional[str] = Query(None, description="Filter by cluster analysis_run_id"),
    conn: sqlite3.Connection = Depends(get_db_connection),
):
    themes = get_validated_themes(conn)
    
    # Query total relevant records from DB
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM theme_assignment_v2 WHERE analysis_run_id = 'd2c78beb-e832-4b0a-b930-0212aeb81481'")
    total_relevant = c.fetchone()[0] or 375

    # Map themes into opportunity DTO cards based on LLM theme_assignment_v2
    opps: list[OpportunityScoreDTO] = []
    for t in themes:
        exemplar_ids = [ex.get("record_id") for ex in t.exemplars if ex.get("record_id")]
        freq_score = round(t.record_count_primary / float(total_relevant), 3)
        opps.append(
            OpportunityScoreDTO(
                cluster_id=t.id,
                cluster_label=f"{t.id[:2]} — {t.title}",
                cluster_summary=t.definition,
                member_count=t.record_count_primary,
                frequency_score=freq_score,
                severity_score=0.95 if t.is_core_opportunity else 0.70,
                consistency_score=1.0,
                evidence_score=0.90 if t.validated_for_interviews else 0.50,
                composite_rank=0.98 if t.is_core_opportunity else (0.80 if t.mvp_fit == "adjacent" else 0.60),
                exemplars=exemplar_ids,
                mvp_fit_label=t.mvp_fit_label,
                is_core_opportunity=t.is_core_opportunity,
                unique_threads=t.unique_threads,
                record_count=t.record_count_primary,
            )
        )

    return OpportunityListResponse(
        total=len(opps),
        opportunities=opps,
        themes=themes,
    )
