#!/usr/bin/env python3
"""Build theme validation artifact from UX extractions (read-only on pipeline config)."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text

from discover.config import project_root
from discover.db import get_engine, run_migrations
from discover.calibration_exclusions import permalink_excluded_from_calibration_metrics
from discover.pipeline.features import parse_structured_fields

ANALYSIS_RUN_ID = "d2c78beb-e832-4b0a-b930-0212aeb81481"

THEMES: list[dict[str, Any]] = [
    {
        "id": "T1_search_ai_regression",
        "title": "Search & AI retrieval regression",
        "definition": "Keyword/classic/natural-language search fails, degrades, or blocks terms vs. what users could find before.",
        "mvp_fit": "adjacent",
        "keywords": (
            "ai search",
            "classic search",
            "gemini",
            "keyword",
            "natural language",
            "can't find",
            "no results",
            "search sucks",
            "relevance",
            "chronological",
        ),
    },
    {
        "id": "T2_fuzzy_visual_memory",
        "title": "Imprecise visual memory → retrieval gap",
        "definition": "User holds partial visual/episodic cues; query formulation is incomplete but the job is to find a specific image.",
        "mvp_fit": "core",
        "keywords": (
            "help me find",
            "remember",
            "forgot",
            "can't remember",
            "partial",
            "specific photo",
            "screenshot",
            "arms crossed",
            "article of clothing",
            "vintage",
            "visual",
        ),
    },
    {
        "id": "T3_library_integrity",
        "title": "Missing, stacked, or unsynced media",
        "definition": "Expected photos absent from albums/library or clients show empty/wrong sets—not primarily a search wording problem.",
        "mvp_fit": "out_of_scope_initial",
        "keywords": (
            "missing",
            "disappeared",
            "gone",
            "empty",
            "sync",
            "stack",
            "devastated",
            "lost",
            "not showing",
        ),
    },
    {
        "id": "T4_query_metadata_power",
        "title": "Query expressiveness & metadata access",
        "definition": "Cannot combine filters, access metadata via search, or list structured subsets (faces, device, boolean).",
        "mvp_fit": "adjacent",
        "keywords": (
            "filter",
            "metadata",
            "boolean",
            "combine",
            "phone model",
            "unrecognized",
            "face available",
            "album",
            "not in an album",
        ),
    },
    {
        "id": "T5_ephemeral_memories",
        "title": "Ephemeral GP memories & collage→original",
        "definition": "System-surfaced collages/memories cannot be re-found; recall gap when GP prompts 'remember this day'.",
        "mvp_fit": "core_adjacent",
        "keywords": (
            "collage",
            "original photo",
            "remember this day",
            "disappears",
            "memory",
            "never find it again",
        ),
    },
]

OUT_OF_SCOPE = {
    "generic_dissatisfaction": (
        "garbage",
        "useless",
        "hate",
        "ruined",
        "worst service",
    ),
    "bulk_curation_only": (
        "delete stuff",
        "storage",
        "hours trying to delete",
        "cleaning out",
    ),
}


@dataclass
class RecordView:
    record_id: str
    permalink: str
    thread_post_id: str
    title: str
    structured: dict[str, Any]
    evidence: dict[str, str]
    outcome: str
    blob: str


def _blob(structured: dict[str, Any], title: str) -> str:
    parts = [title or ""]
    for v in structured.values():
        if isinstance(v, str):
            parts.append(v)
    return " ".join(parts).casefold()


def _score_theme(blob: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for k in keywords if k in blob)


def _best_excerpt(rec: RecordView) -> str:
    for key in ("failure_point", "search_attempt", "retrieval_scenario", "remembers", "forgotten"):
        if rec.evidence.get(key):
            return rec.evidence[key][:280]
        v = rec.structured.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:280]
    return (rec.title or "")[:200]


def main() -> None:
    from discover.config import Settings

    settings = Settings.from_env()
    engine = get_engine(settings.database_url)
    run_migrations(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT cr.id, cr.permalink, cr.title, cr.body,
                       ux.structured_fields_json, ux.evidence_spans_json,
                       ux.extraction_status
                FROM relevance_result rr
                JOIN canonical_record cr ON cr.id = rr.record_id
                LEFT JOIN ux_extraction ux ON ux.record_id = rr.record_id
                    AND ux.analysis_run_id = rr.analysis_run_id
                WHERE rr.analysis_run_id = :aid AND rr.is_relevant = 1
                ORDER BY cr.created_at, cr.id
                """
            ),
            {"aid": ANALYSIS_RUN_ID},
        ).fetchall()

    records: list[RecordView] = []
    for row in rows:
        if permalink_excluded_from_calibration_metrics(row[1] or ""):
            continue
        structured = parse_structured_fields(row[4])
        evidence: dict[str, str] = {}
        if row[5]:
            try:
                raw = json.loads(row[5])
                if isinstance(raw, dict):
                    evidence = {k: str(v) for k, v in raw.items()}
            except json.JSONDecodeError:
                pass
        permalink = row[1] or ""
        thread = ""
        m = re.search(r"/comments/([^/]+)/", permalink)
        if m:
            thread = m.group(1)
        records.append(
            RecordView(
                record_id=row[0],
                permalink=permalink,
                thread_post_id=thread,
                title=row[2] or "",
                structured=structured,
                evidence=evidence,
                outcome=(structured.get("outcome") or "").strip().lower(),
                blob=_blob(structured, row[2] or ""),
            )
        )

    completed = sum(1 for r in records if r.structured)
    theme_assignments: dict[str, list[RecordView]] = {t["id"]: [] for t in THEMES}
    primary_theme: dict[str, str] = {}
    for rec in records:
        scores = [(t["id"], _score_theme(rec.blob, tuple(t["keywords"]))) for t in THEMES]
        scores.sort(key=lambda x: -x[1])
        if scores[0][1] > 0:
            tid = scores[0][0]
            primary_theme[rec.record_id] = tid
            theme_assignments[tid].append(rec)
        else:
            primary_theme[rec.record_id] = "unassigned"

    def pick_exemplars(members: list[RecordView], n: int = 4) -> list[RecordView]:
        # Prefer failure outcomes + evidence richness
        def rank(r: RecordView) -> tuple:
            ev = len(r.evidence)
            fail = 1 if r.outcome == "failure" else 0
            return (fail, ev, len(r.blob))

        members = sorted(members, key=rank, reverse=True)
        chosen: list[RecordView] = []
        seen_threads: set[str] = set()
        for r in members:
            if r.thread_post_id and r.thread_post_id in seen_threads:
                continue
            chosen.append(r)
            if r.thread_post_id:
                seen_threads.add(r.thread_post_id)
            if len(chosen) >= n:
                break
        if len(chosen) < 3:
            for r in members:
                if r not in chosen:
                    chosen.append(r)
                if len(chosen) >= 3:
                    break
        return chosen[: max(3, min(n, len(chosen)))]

    validation: dict[str, Any] = {
        "analysis_run_id": ANALYSIS_RUN_ID,
        "relevant_records": len(records),
        "extractions_present": completed,
        "themes": [],
        "out_of_scope_notes": [],
        "north_star_slice": {
            "theme_id": "T2_fuzzy_visual_memory",
            "count": len(theme_assignments["T2_fuzzy_visual_memory"]),
        },
    }

    for theme in THEMES:
        members = theme_assignments[theme["id"]]
        threads = len({r.thread_post_id for r in members if r.thread_post_id})
        exemplars = pick_exemplars(members)
        validation["themes"].append(
            {
                "id": theme["id"],
                "title": theme["title"],
                "definition": theme["definition"],
                "mvp_fit": theme["mvp_fit"],
                "record_count_primary": len(members),
                "unique_threads": threads,
                "validated_for_interviews": len(exemplars) >= 3 and threads >= 3,
                "exemplars": [
                    {
                        "record_id": e.record_id,
                        "permalink": e.permalink,
                        "thread_post_id": e.thread_post_id,
                        "outcome": e.outcome,
                        "excerpt": _best_excerpt(e),
                    }
                    for e in exemplars
                ],
            }
        )

    # Out-of-scope spot check counts
    for label, kws in OUT_OF_SCOPE.items():
        hits = [r.record_id for r in records if any(k in r.blob for k in kws)]
        validation["out_of_scope_notes"].append({"label": label, "approx_records": len(hits)})

    out_dir = project_root() / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "theme_validation.json"
    json_path.write_text(json.dumps(validation, indent=2), encoding="utf-8")

    lines = [
        "# Theme validation (full relevant corpus)",
        "",
        f"**Analysis run:** `{ANALYSIS_RUN_ID}`",
        f"**Relevant records:** {len(records)} | **With extractions:** {completed}",
        "",
        "Themes are **not** cluster IDs. Assignment is keyword+field heuristic for interview planning; review exemplars before external use.",
        "",
        "## MVP lens",
        "",
        "- **Core:** imprecise visual memory → find the photo (`T2`)",
        "- **Adjacent:** search regression (`T1`), query/metadata (`T4`), memory surfaces (`T5`)",
        "- **Defer for MVP:** library integrity/sync (`T3`), generic dissatisfaction, bulk curation-only",
        "",
    ]
    for t in validation["themes"]:
        flag = "✓" if t["validated_for_interviews"] else "⚠"
        lines.append(f"## {flag} {t['title']} (`{t['id']}`)")
        lines.append("")
        lines.append(t["definition"])
        lines.append("")
        lines.append(
            f"- Primary assignment: **{t['record_count_primary']}** records | "
            f"**{t['unique_threads']}** distinct threads | MVP fit: **{t['mvp_fit']}**"
        )
        lines.append("")
        lines.append("**Interview exemplars (≥3 threads):**")
        lines.append("")
        for ex in t["exemplars"]:
            lines.append(f"- `{ex['record_id']}` — [{ex['thread_post_id'] or 'thread'}]({ex['permalink']})")
            lines.append(f"  - *{ex['excerpt']}*")
        lines.append("")

    lines.append("## Out-of-scope buckets (approximate)")
    lines.append("")
    for note in validation["out_of_scope_notes"]:
        lines.append(f"- **{note['label']}:** ~{note['approx_records']} records (keyword hit; overlaps themes)")
    lines.append("")
    lines.append("## Recommended interview focus")
    lines.append("")
    lines.append(
        "1. **T2** — partial cues, failed search formulation (north star). "
        "2. **T1** — how users discover regression (often masks T2). "
        "3. **T5** — memory UI surfaces content users cannot re-locate. "
        "Validate **T3** only to separate trust/sync from retrieval design."
    )

    md_path = out_dir / "theme_validation.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
