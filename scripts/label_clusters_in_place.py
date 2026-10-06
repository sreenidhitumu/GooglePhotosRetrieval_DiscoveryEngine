#!/usr/bin/env python3
"""Apply Gemini labels to existing clusters without re-clustering."""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from sqlalchemy import text

from discover.config import Settings
from discover.db import get_engine, run_migrations
from discover.llm.extraction_gateway import get_extraction_gateway
from discover.pipeline.features import parse_structured_fields

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LABEL_PROMPT_VERSION = "cluster_label_in_place_v1"

INSTRUCTIONS = """You label retrieval-problem clusters for research. Use ONLY the member records provided.

Rules:
- Do NOT use a fixed taxonomy or preset category names.
- Label must describe what these records actually share (user struggle with finding/recalling photos in Google Photos or similar).
- No product solutions, MVPs, or feature recommendations.
- summary: exactly ONE sentence on the shared user experience.
- representative_record_ids: pick 2-3 record_ids from the input that best illustrate the pattern.
- confidence: 0.0-1.0 how well the label fits all members (lower if heterogeneous).

Respond with JSON only:
{"label": "string", "summary": "string", "representative_record_ids": ["id", ...], "confidence": 0.0}"""


def build_prompt(members: list[dict[str, Any]]) -> str:
    return (
        f"{INSTRUCTIONS}\n\nPrompt version: {LABEL_PROMPT_VERSION}\n\n"
        f"Cluster members ({len(members)} records, ordered by centrality):\n"
        f"{json.dumps(members, ensure_ascii=False)}"
    )


def fetch_clusters(engine, cluster_analysis_run_id: str, source_analysis_run_id: str):
    with engine.connect() as conn:
        cluster_rows = conn.execute(
            text(
                """
                SELECT id, member_count, metadata_json
                FROM cluster
                WHERE analysis_run_id = :aid
                ORDER BY member_count DESC, id
                """
            ),
            {"aid": cluster_analysis_run_id},
        ).fetchall()

        results = []
        for crow in cluster_rows:
            cid = crow[0]
            members = conn.execute(
                text(
                    """
                    SELECT cm.record_id, cm.score, cr.source_type, cr.title,
                           cr.body, ux.structured_fields_json, ux.evidence_spans_json
                    FROM cluster_member cm
                    JOIN canonical_record cr ON cr.id = cm.record_id
                    JOIN ux_extraction ux ON ux.record_id = cm.record_id
                        AND ux.analysis_run_id = :src
                    WHERE cm.cluster_id = :cid
                    ORDER BY cm.score DESC
                    """
                ),
                {"cid": cid, "src": source_analysis_run_id},
            ).fetchall()
            payload: list[dict[str, Any]] = []
            for m in members:
                structured = parse_structured_fields(m[5])
                evidence = {}
                if m[6]:
                    try:
                        evidence = json.loads(m[6])
                    except json.JSONDecodeError:
                        pass
                body = (m[4] or "")[:800]
                payload.append(
                    {
                        "record_id": m[0],
                        "membership_score": round(float(m[1] or 0), 4),
                        "source_type": m[2],
                        "title": (m[3] or "")[:300],
                        "body_excerpt": body,
                        "structured_fields": structured,
                        "evidence_spans": evidence,
                    }
                )
            results.append((cid, int(crow[1]), crow[2], payload))
        return results


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: label_clusters_in_place.py <cluster_analysis_run_id> <source_analysis_run_id>")
        return 1

    cluster_aid = sys.argv[1]
    source_aid = sys.argv[2]
    settings = Settings.from_env()
    engine = get_engine(settings.database_url)
    run_migrations(engine)
    gateway = get_extraction_gateway(settings, None)

    clusters = fetch_clusters(engine, cluster_aid, source_aid)
    if not clusters:
        logger.error("No clusters found for %s", cluster_aid)
        return 1

    report: list[dict[str, Any]] = []
    for cid, member_count, meta_raw, members in clusters:
        # Send top members for context (cap tokens); include all structured fields
        for_label = members[: min(8, len(members))]
        prompt = build_prompt(for_label)
        parsed = gateway.generate_json_prompt(prompt)
        label = (parsed.get("label") or "Unlabeled").strip()[:500]
        summary = (parsed.get("summary") or "").strip()[:2000]
        rep_ids = parsed.get("representative_record_ids") or []
        if not isinstance(rep_ids, list):
            rep_ids = []
        rep_ids = [str(x) for x in rep_ids[:3] if x in {m["record_id"] for m in members}]
        if len(rep_ids) < 2 and members:
            rep_ids = [m["record_id"] for m in members[:3]]
        confidence = parsed.get("confidence")
        try:
            confidence_f = float(confidence)
        except (TypeError, ValueError):
            confidence_f = None

        meta: dict[str, Any] = {}
        if meta_raw:
            try:
                meta = json.loads(meta_raw)
            except json.JSONDecodeError:
                pass
        meta["label_confidence"] = confidence_f
        meta["representative_record_ids"] = rep_ids
        meta["label_prompt_version"] = LABEL_PROMPT_VERSION
        if "exemplar_record_ids" not in meta:
            meta["exemplar_record_ids"] = [m["record_id"] for m in members[:3]]

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE cluster
                    SET label = :label, summary = :summary, metadata_json = :meta
                    WHERE id = :cid
                    """
                ),
                {"label": label, "summary": summary, "meta": json.dumps(meta), "cid": cid},
            )

        report.append(
            {
                "cluster_id": cid,
                "member_count": member_count,
                "label": label,
                "summary": summary,
                "representative_record_ids": rep_ids,
                "confidence": confidence_f,
            }
        )
        logger.info("Labeled %s (%s members): %s", cid[:8], member_count, label)

    from discover.config import project_root

    report_path = project_root() / "data" / "processed" / f"cluster_labels_{cluster_aid[:8]}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
