from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Engine

from discover.config import Settings
from discover.llm.cluster_prompts import CLUSTER_LABEL_PROMPT_VERSION
from discover.llm.extraction_gateway import get_extraction_gateway
from discover.pipeline.cluster_options import ClusterOptions
from discover.pipeline.clustering_math import choose_num_clusters, run_kmeans, vectorize_documents
from discover.pipeline.extract import load_research_set_record_ids
from discover.pipeline.features import build_clustering_document, parse_structured_fields

logger = logging.getLogger(__name__)


@dataclass
class ClusterReport:
    cluster_analysis_run_id: str = ""
    source_analysis_run_id: str = ""
    records_in: int = 0
    num_clusters: int = 0
    members_assigned: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_analysis_run_id": self.cluster_analysis_run_id,
            "source_analysis_run_id": self.source_analysis_run_id,
            "records_in": self.records_in,
            "num_clusters": self.num_clusters,
            "members_assigned": self.members_assigned,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _create_cluster_analysis_run(
    engine: Engine, source_analysis_run_id: str, model_id: str
) -> str:
    run_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO analysis_run (id, label, model_id, prompt_version)
                VALUES (:id, :label, :model_id, :prompt_version)
                """
            ),
            {
                "id": run_id,
                "label": f"clustering_{source_analysis_run_id[:8]}",
                "model_id": model_id,
                "prompt_version": CLUSTER_LABEL_PROMPT_VERSION,
            },
        )
    return run_id


def _fetch_extraction_records(
    engine: Engine, source_analysis_run_id: str
) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT cr.id, cr.source_type, cr.title, cr.body, cr.permalink,
                       ux.structured_fields_json
                FROM ux_extraction ux
                JOIN canonical_record cr ON cr.id = ux.record_id
                WHERE ux.analysis_run_id = :aid
                  AND ux.extraction_status = 'completed'
                ORDER BY cr.created_at, cr.id
                """
            ),
            {"aid": source_analysis_run_id},
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        structured = parse_structured_fields(row[5])
        out.append(
            {
                "record_id": row[0],
                "source_type": row[1],
                "title": row[2],
                "body": row[3],
                "permalink": row[4],
                "structured_fields": structured,
                "document": build_clustering_document(
                    title=row[2], body=row[3], structured_fields=structured
                ),
            }
        )
    return out


def run_cluster(
    engine: Engine,
    settings: Settings,
    opts: ClusterOptions,
    *,
    dry_run: bool = False,
) -> ClusterReport:
    if not opts.analysis_run_id:
        raise ValueError("analysis_run_id required (relevance/extraction run)")
    source_aid = opts.analysis_run_id
    records = _fetch_extraction_records(engine, source_aid)
    if opts.research_set_path:
        allowed = load_research_set_record_ids(opts.research_set_path)
        records = [r for r in records if r["record_id"] in allowed]
    report = ClusterReport(source_analysis_run_id=source_aid, records_in=len(records))
    if len(records) < 2:
        raise ValueError(f"Need at least 2 extracted records to cluster; got {len(records)}")

    if dry_run:
        report.num_clusters = choose_num_clusters(
            vectorize_documents([r["document"] for r in records])[1],
            len(records),
            opts.num_clusters,
        )
        report.members_assigned = len(records)
        logger.info("cluster dry-run: %s", report.to_dict())
        return report

    gateway = get_extraction_gateway(settings, opts.llm_provider)
    cluster_aid = opts.cluster_analysis_run_id or _create_cluster_analysis_run(
        engine, source_aid, gateway.model_id
    )
    report.cluster_analysis_run_id = cluster_aid

    if opts.force:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM opportunity_score WHERE cluster_id IN (SELECT id FROM cluster WHERE analysis_run_id = :aid)"),
                {"aid": cluster_aid},
            )
            conn.execute(
                text("DELETE FROM cluster_member WHERE cluster_id IN (SELECT id FROM cluster WHERE analysis_run_id = :aid)"),
                {"aid": cluster_aid},
            )
            conn.execute(text("DELETE FROM cluster WHERE analysis_run_id = :aid"), {"aid": cluster_aid})

    _, matrix = vectorize_documents([r["document"] for r in records])
    k = choose_num_clusters(matrix, len(records), opts.num_clusters)
    report.num_clusters = k
    labels, centers = run_kmeans(matrix, k)

    dense = matrix.toarray()
    clusters: dict[int, list[tuple[str, float, dict[str, Any]]]] = {i: [] for i in range(k)}
    for idx, rec in enumerate(records):
        label = int(labels[idx])
        center = centers[label]
        dist = float(np.linalg.norm(dense[idx] - center))
        score = 1.0 / (1.0 + dist)
        clusters[label].append((rec["record_id"], score, rec))

    for cluster_idx, members in clusters.items():
        members.sort(key=lambda x: -x[1])
        exemplar_ids = [m[0] for m in members[:3]]
        exemplar_payload = [
            {
                "record_id": m[2]["record_id"],
                "source_type": m[2]["source_type"],
                "excerpt": m[2]["document"][:800],
            }
            for m in members[:3]
        ]
        label = f"Cluster {cluster_idx + 1}"
        summary = f"{len(members)} records with similar retrieval experiences."
        if opts.label_clusters and exemplar_payload:
            try:
                label, summary = gateway.label_cluster(exemplar_payload)
            except Exception as exc:
                logger.warning("Cluster LLM label failed: %s", exc)

        cluster_id = str(uuid.uuid4())
        meta = json.dumps(
            {"exemplar_record_ids": exemplar_ids, "source_analysis_run_id": source_aid}
        )
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO cluster (id, analysis_run_id, label, summary, member_count, metadata_json)
                    VALUES (:id, :aid, :label, :summary, :count, :meta)
                    """
                ),
                {
                    "id": cluster_id,
                    "aid": cluster_aid,
                    "label": label,
                    "summary": summary,
                    "count": len(members),
                    "meta": meta,
                },
            )
            for rid, score, _ in members:
                conn.execute(
                    text(
                        """
                        INSERT INTO cluster_member (cluster_id, record_id, score)
                        VALUES (:cid, :rid, :score)
                        """
                    ),
                    {"cid": cluster_id, "rid": rid, "score": score},
                )
        report.members_assigned += len(members)

    logger.info("cluster report: %s", report.to_dict())
    return report
