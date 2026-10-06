from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from discover.config import project_root
from discover.pipeline.cluster_options import ClusterOptions

logger = logging.getLogger(__name__)


@dataclass
class PublishOptions(ClusterOptions):
    top_opportunities: int = 5
    markdown_output: Path | None = None
    json_output: Path | None = None


@dataclass
class PublishReport:
    snapshot_id: str = ""
    cluster_analysis_run_id: str = ""
    opportunities_published: int = 0
    markdown_path: str = ""
    json_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "cluster_analysis_run_id": self.cluster_analysis_run_id,
            "opportunities_published": self.opportunities_published,
            "markdown_path": self.markdown_path,
            "json_path": self.json_path,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_publish_payload(engine: Engine, cluster_aid: str, top_n: int) -> dict[str, Any]:
    with engine.connect() as conn:
        opp_rows = conn.execute(
            text(
                """
                SELECT c.id, c.label, c.summary, c.member_count, c.metadata_json,
                       o.frequency_score, o.severity_score, o.consistency_score,
                       o.evidence_score, o.composite_rank
                FROM cluster c
                JOIN opportunity_score o ON o.cluster_id = c.id
                WHERE c.analysis_run_id = :aid
                ORDER BY o.composite_rank DESC
                LIMIT :limit
                """
            ),
            {"aid": cluster_aid, "limit": top_n},
        ).fetchall()

        clusters: list[dict[str, Any]] = []
        for row in opp_rows:
            cid = row[0]
            meta: dict[str, Any] = {}
            if row[4]:
                try:
                    meta = json.loads(row[4])
                except json.JSONDecodeError:
                    pass
            exemplar_ids = meta.get("exemplar_record_ids") or []
            member_rows = conn.execute(
                text(
                    """
                    SELECT cm.record_id, cm.score, cr.permalink, cr.source_type
                    FROM cluster_member cm
                    JOIN canonical_record cr ON cr.id = cm.record_id
                    WHERE cm.cluster_id = :cid
                    ORDER BY cm.score DESC
                    LIMIT 10
                    """
                ),
                {"cid": cid},
            ).fetchall()
            clusters.append(
                {
                    "cluster_id": cid,
                    "label": row[1],
                    "summary": row[2],
                    "member_count": row[3],
                    "exemplar_record_ids": exemplar_ids,
                    "scores": {
                        "frequency": row[5],
                        "severity": row[6],
                        "consistency": row[7],
                        "evidence": row[8],
                        "composite_rank": row[9],
                    },
                    "members": [
                        {
                            "record_id": m[0],
                            "membership_score": m[1],
                            "permalink": m[2],
                            "source_type": m[3],
                        }
                        for m in member_rows
                    ],
                }
            )

        source_aid = None
        if opp_rows and opp_rows[0][4]:
            try:
                source_aid = json.loads(opp_rows[0][4]).get("source_analysis_run_id")
            except json.JSONDecodeError:
                pass

    return {
        "generated_at": _utc_now(),
        "cluster_analysis_run_id": cluster_aid,
        "source_analysis_run_id": source_aid,
        "top_opportunities": clusters,
    }


def render_opportunity_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Retrieval opportunity summary",
        "",
        f"Generated: {payload.get('generated_at')}",
        f"Cluster analysis run: `{payload.get('cluster_analysis_run_id')}`",
        "",
    ]
    for idx, opp in enumerate(payload.get("top_opportunities") or [], start=1):
        scores = opp.get("scores") or {}
        lines.append(f"## {idx}. {opp.get('label')}")
        lines.append("")
        lines.append(opp.get("summary") or "")
        lines.append("")
        lines.append(
            f"- Members: **{opp.get('member_count')}** | "
            f"Composite rank: **{scores.get('composite_rank')}** "
            f"(freq={scores.get('frequency')}, severity={scores.get('severity')}, "
            f"evidence={scores.get('evidence')})"
        )
        exemplars = opp.get("exemplar_record_ids") or []
        if exemplars:
            lines.append(f"- Exemplar record IDs: {', '.join(f'`{e}`' for e in exemplars)}")
        lines.append("")
        for member in (opp.get("members") or [])[:5]:
            link = member.get("permalink") or ""
            score = member.get("membership_score")
            score_txt = f"{score:.3f}" if isinstance(score, (int, float)) else "n/a"
            lines.append(
                f"  - `{member.get('record_id')}` ({member.get('source_type')}) "
                f"score={score_txt}"
                + (f" — [source]({link})" if link else "")
            )
        lines.append("")
    return "\n".join(lines)


def export_opportunity_ranking(engine: Engine, cluster_analysis_run_id: str) -> dict[str, Any]:
    payload = _load_publish_payload(engine, cluster_analysis_run_id, top_n=100)
    return {
        "cluster_analysis_run_id": cluster_analysis_run_id,
        "opportunities": payload.get("top_opportunities") or [],
    }


def run_publish(
    engine: Engine,
    opts: PublishOptions,
    *,
    dry_run: bool = False,
    pipeline_run_id: str | None = None,
) -> PublishReport:
    cluster_aid = opts.cluster_analysis_run_id
    if not cluster_aid:
        raise ValueError("cluster_analysis_run_id required (from cluster stage)")

    report = PublishReport(cluster_analysis_run_id=cluster_aid)
    payload = _load_publish_payload(engine, cluster_aid, opts.top_opportunities)
    if not payload.get("top_opportunities"):
        raise ValueError(
            f"No opportunity scores for cluster analysis run {cluster_aid}. Run opportunity stage first."
        )
    report.opportunities_published = len(payload["top_opportunities"])

    json_out = opts.json_output or (
        project_root()
        / "data"
        / "processed"
        / f"published_snapshot_{cluster_aid[:8]}.json"
    )
    md_out = opts.markdown_output or (
        project_root()
        / "data"
        / "processed"
        / f"opportunity_summary_{cluster_aid[:8]}.md"
    )

    if dry_run:
        report.json_path = str(json_out)
        report.markdown_path = str(md_out)
        logger.info("publish dry-run: %s", report.to_dict())
        return report

    snapshot_id = str(uuid.uuid4())
    report.snapshot_id = snapshot_id
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_out.write_text(render_opportunity_markdown(payload), encoding="utf-8")
    report.json_path = str(json_out)
    report.markdown_path = str(md_out)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO published_snapshot (
                    id, analysis_run_id, pipeline_run_id, notes, snapshot_json
                )
                VALUES (:id, :aid, :pid, :notes, :snap)
                """
            ),
            {
                "id": snapshot_id,
                "aid": cluster_aid,
                "pid": pipeline_run_id,
                "notes": f"top_{opts.top_opportunities}_opportunities",
                "snap": json.dumps(payload),
            },
        )

    logger.info("publish report: %s", report.to_dict())
    return report
