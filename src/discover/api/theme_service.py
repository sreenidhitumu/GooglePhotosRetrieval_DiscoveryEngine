from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from discover.config import project_root
from discover.api.schemas import ResearchThemeDTO

BASELINE_RUN_ID = "d2c78beb-e832-4b0a-b930-0212aeb81481"

THEME_MVP_LABELS = {
    "T1_search_ai_regression": ("ADJACENT", False),
    "T2_fuzzy_visual_memory": ("CORE MVP OPPORTUNITY", True),
    "T3_library_integrity": ("OUT OF SCOPE (INITIAL)", False),
    "T4_query_metadata_power": ("ADJACENT", False),
    "T5_ephemeral_memories": ("CORE-ADJACENT", False),
}

THEME_TITLES = {
    "T1_search_ai_regression": "Search & AI Retrieval Regression",
    "T2_fuzzy_visual_memory": "Imprecise Visual Memory Gap (Core MVP)",
    "T3_library_integrity": "Missing / Unsynced Media",
    "T4_query_metadata_power": "Query Expressiveness & Metadata",
    "T5_ephemeral_memories": "Ephemeral Memories & Collages",
    "OTHER": "Other Relevant Feedback",
}


def load_theme_validation_data() -> dict[str, Any]:
    file_path = project_root() / "data" / "processed" / "theme_validation.json"
    if not file_path.is_file():
        return {"themes": [], "analysis_run_id": BASELINE_RUN_ID}
    return json.loads(file_path.read_text(encoding="utf-8"))


def get_validated_themes(conn: sqlite3.Connection | None = None) -> list[ResearchThemeDTO]:
    data = load_theme_validation_data()
    themes: list[ResearchThemeDTO] = []
    
    # Query theme_assignment_v2 counts if conn is available
    v2_counts: dict[str, int] = {}
    if conn:
        try:
            rows = conn.execute(
                "SELECT theme, COUNT(*) FROM theme_assignment_v2 WHERE analysis_run_id = ? GROUP BY theme",
                (BASELINE_RUN_ID,),
            ).fetchall()
            for r in rows:
                v2_counts[r[0]] = r[1]
        except Exception:
            pass

    sort_order = {
        "T2_fuzzy_visual_memory": 0,
        "T1_search_ai_regression": 1,
        "T5_ephemeral_memories": 2,
        "T4_query_metadata_power": 3,
        "T3_library_integrity": 4,
    }
    
    raw_themes = sorted(data.get("themes", []), key=lambda t: sort_order.get(t["id"], 99))

    for t in raw_themes:
        tid = t["id"]
        fit_label, is_core = THEME_MVP_LABELS.get(tid, (t.get("mvp_fit", "").upper(), False))
        count_v2 = v2_counts.get(tid, t.get("record_count_primary", 0))
        
        themes.append(
            ResearchThemeDTO(
                id=tid,
                title=t["title"],
                definition=t["definition"],
                mvp_fit=t["mvp_fit"],
                mvp_fit_label=fit_label,
                is_core_opportunity=is_core,
                record_count_primary=count_v2,
                unique_threads=t.get("unique_threads", 0),
                validated_for_interviews=t.get("validated_for_interviews", True),
                exemplars=t.get("exemplars", []),
            )
        )
    return themes


def get_record_theme_mapping(conn: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    """Map record_id -> list of (theme_id, theme_title) tuples using LLM theme_assignment_v2 table."""
    mapping: dict[str, list[tuple[str, str]]] = {}
    
    try:
        rows = conn.execute(
            """
            SELECT record_id, theme
            FROM theme_assignment_v2
            WHERE analysis_run_id = ?
            """,
            (BASELINE_RUN_ID,),
        ).fetchall()

        for r in rows:
            rid = r[0]
            tid = r[1]
            if tid and tid != "OTHER":
                mapping.setdefault(rid, []).append((tid, THEME_TITLES.get(tid, tid)))
    except Exception as exc:
        pass

    return mapping
