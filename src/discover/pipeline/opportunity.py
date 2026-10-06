from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from discover.llm.extraction_schemas import STRUCTURED_FIELD_NAMES, count_populated_fields
from discover.pipeline.cluster_options import ClusterOptions
from discover.pipeline.features import parse_structured_fields

logger = logging.getLogger(__name__)

WEIGHT_FREQUENCY = 0.35
WEIGHT_SEVERITY = 0.30
WEIGHT_CONSISTENCY = 0.15
WEIGHT_EVIDENCE = 0.20


@dataclass
class OpportunityReport:
    cluster_analysis_run_id: str = ""
    clusters_scored: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_analysis_run_id": self.cluster_analysis_run_id,
            "clusters_scored": self.clusters_scored,
        }


def _severity_score(structured: dict[str, Any]) -> float:
    score = 0.25
    outcome = (structured.get("outcome") or "").casefold()
    if any(tok in outcome for tok in ("fail", "unsuccess", "not found", "give up")):
        score += 0.35
    elif outcome:
        score += 0.1
    if structured.get("failure_point"):
        score += 0.2
    if structured.get("forgotten"):
        score += 0.1
    if structured.get("search_attempt"):
        score += 0.05
    return min(1.0, score)


def _evidence_score(structured: dict[str, Any], evidence_span_count: int) -> float:
    field_ratio = count_populated_fields(structured) / max(1, len(STRUCTURED_FIELD_NAMES))
    span_ratio = min(1.0, evidence_span_count / 3.0)
    return min(1.0, 0.6 * field_ratio + 0.4 * span_ratio)


def _consistency_score(source_types: list[str]) -> float:
    if not source_types:
        return 0.5
    unique = len(set(source_types))
    if unique <= 1:
        return 1.0
    return max(0.2, 1.0 - (unique - 1) / len(source_types))


def _source_analysis_run_id(engine: Engine, cluster_analysis_run_id: str) -> str | None:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT metadata_json FROM cluster WHERE analysis_run_id = :aid LIMIT 1"),
            {"aid": cluster_analysis_run_id},
        ).fetchone()
    if not rows or not rows[0]:
        return None
    try:
        meta = json.loads(rows[0])
    except json.JSONDecodeError:
        return None
    return meta.get("source_analysis_run_id")


def _fetch_cluster_groups(
    engine: Engine, cluster_analysis_run_id: str, source_analysis_run_id: str | None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"aid": cluster_analysis_run_id}
    join_ux = ""
    if source_analysis_run_id:
        join_ux = "AND ux.analysis_run_id = :src"
        params["src"] = source_analysis_run_id

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT c.id, c.label, c.member_count,
                       cm.record_id, cm.score,
                       cr.source_type,
                       ux.structured_fields_json, ux.evidence_spans_json
                FROM cluster c
                JOIN cluster_member cm ON cm.cluster_id = c.id
                JOIN canonical_record cr ON cr.id = cm.record_id
                LEFT JOIN ux_extraction ux ON ux.record_id = cm.record_id {join_ux}
                WHERE c.analysis_run_id = :aid
                ORDER BY c.id, cm.score DESC
                """
            ),
            params,
        ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cid = row[0]
        structured = parse_structured_fields(row[6])
        span_count = 0
        if row[7]:
            try:
                spans = json.loads(row[7])
                if isinstance(spans, dict):
                    span_count = len(spans)
            except json.JSONDecodeError:
                pass
        grouped.setdefault(cid, []).append(
            {
                "cluster_id": cid,
                "cluster_label": row[1],
                "member_count": row[2],
                "record_id": row[3],
                "membership_score": row[4],
                "source_type": row[5],
                "structured_fields": structured,
                "evidence_span_count": span_count,
            }
        )
    return [{"cluster_id": cid, "members": members} for cid, members in grouped.items()]


def run_opportunity(
    engine: Engine,
    opts: ClusterOptions,
    *,
    dry_run: bool = False,
) -> OpportunityReport:
    cluster_aid = opts.cluster_analysis_run_id
    if not cluster_aid:
        raise ValueError("cluster_analysis_run_id required (from cluster stage)")

    report = OpportunityReport(cluster_analysis_run_id=cluster_aid)
    source_aid = _source_analysis_run_id(engine, cluster_aid)
    groups = _fetch_cluster_groups(engine, cluster_aid, source_aid)
    if not groups:
        raise ValueError(f"No clusters found for analysis_run_id={cluster_aid}")

    total_records = sum(len(g["members"]) for g in groups)
    scored: list[tuple[str, dict[str, float]]] = []

    for group in groups:
        members = group["members"]
        cid = group["cluster_id"]
        freq = len(members) / max(1, total_records)
        severity = sum(_severity_score(m["structured_fields"]) for m in members) / len(members)
        consistency = _consistency_score([m["source_type"] for m in members])
        evidence = sum(
            _evidence_score(m["structured_fields"], m["evidence_span_count"]) for m in members
        ) / len(members)
        composite = (
            WEIGHT_FREQUENCY * freq
            + WEIGHT_SEVERITY * severity
            + WEIGHT_CONSISTENCY * consistency
            + WEIGHT_EVIDENCE * evidence
        )
        scored.append(
            (
                cid,
                {
                    "frequency_score": round(freq, 4),
                    "severity_score": round(severity, 4),
                    "consistency_score": round(consistency, 4),
                    "evidence_score": round(evidence, 4),
                    "composite_rank": round(composite, 4),
                },
            )
        )

    report.clusters_scored = len(scored)
    if dry_run:
        logger.info("opportunity dry-run: %s", report.to_dict())
        return report

    if opts.force:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    DELETE FROM opportunity_score
                    WHERE cluster_id IN (
                        SELECT id FROM cluster WHERE analysis_run_id = :aid
                    )
                    """
                ),
                {"aid": cluster_aid},
            )

    with engine.begin() as conn:
        for cid, scores in scored:
            conn.execute(
                text(
                    """
                    INSERT INTO opportunity_score (
                        cluster_id, frequency_score, severity_score,
                        consistency_score, evidence_score, composite_rank
                    )
                    VALUES (
                        :cid, :freq, :sev, :cons, :ev, :comp
                    )
                    ON CONFLICT(cluster_id) DO UPDATE SET
                        frequency_score = excluded.frequency_score,
                        severity_score = excluded.severity_score,
                        consistency_score = excluded.consistency_score,
                        evidence_score = excluded.evidence_score,
                        composite_rank = excluded.composite_rank
                    """
                ),
                {
                    "cid": cid,
                    "freq": scores["frequency_score"],
                    "sev": scores["severity_score"],
                    "cons": scores["consistency_score"],
                    "ev": scores["evidence_score"],
                    "comp": scores["composite_rank"],
                },
            )

    logger.info("opportunity report: %s", report.to_dict())
    return report
