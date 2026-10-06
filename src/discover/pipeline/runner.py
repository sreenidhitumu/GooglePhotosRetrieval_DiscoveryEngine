from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

from discover.config import Settings
from discover.metrics import MetricsCollector
from discover.pipeline.preprocess import run_preprocess
from discover.pipeline.cluster import run_cluster
from discover.pipeline.cluster_options import ClusterOptions
from discover.pipeline.extract import ExtractOptions, run_extract
from discover.pipeline.opportunity import run_opportunity
from discover.pipeline.publish import PublishOptions, run_publish
from discover.pipeline.relevance import RelevanceOptions, run_relevance

logger = logging.getLogger(__name__)

STAGES = (
    "preprocess",
    "relevance",
    "extract",
    "cluster",
    "opportunity",
    "publish",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_stage(
    engine: Engine,
    stage: str,
    *,
    dry_run: bool = False,
    metrics: MetricsCollector | None = None,
    settings: Settings | None = None,
    relevance_opts: RelevanceOptions | None = None,
    extract_opts: ExtractOptions | None = None,
    cluster_opts: ClusterOptions | None = None,
    publish_opts: PublishOptions | None = None,
) -> str:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}. Choose from: {', '.join(STAGES)}")

    metrics = metrics or MetricsCollector()
    stage_metrics = metrics.for_stage(stage)
    run_id = str(uuid.uuid4())
    now = _utc_now()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO pipeline_run (id, stage, status, dry_run, started_at, updated_at)
                VALUES (:id, :stage, :status, :dry_run, :started, :updated)
                """
            ),
            {
                "id": run_id,
                "stage": stage,
                "status": "running",
                "dry_run": 1 if dry_run else 0,
                "started": now,
                "updated": now,
            },
        )

    try:
        if stage == "preprocess":
            _run_preprocess(engine, dry_run=dry_run, stage_metrics=stage_metrics)
        elif stage == "relevance":
            if settings is None:
                settings = Settings.from_env()
            rep = run_relevance(
                engine,
                settings,
                relevance_opts or RelevanceOptions(),
                dry_run=dry_run,
                pipeline_run_id=run_id,
            )
            stage_metrics.records_seen = rep.canonical_total
            stage_metrics.records_processed = rep.llm_classified + rep.gate_skipped
            stage_metrics.records_skipped = rep.already_processed
            stage_metrics.records_failed = rep.analysis_failed
            stage_metrics.inc("gate_skipped", rep.gate_skipped)
            stage_metrics.inc("relevant", rep.relevant)
            stage_metrics.inc("not_relevant", rep.not_relevant)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE pipeline_run
                        SET metadata_json = :meta
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": run_id,
                        "meta": f'{{"analysis_run_id":"{rep.analysis_run_id}"}}',
                    },
                )
        elif stage == "extract":
            if settings is None:
                settings = Settings.from_env()
            rep = run_extract(
                engine,
                settings,
                extract_opts or ExtractOptions(),
                dry_run=dry_run,
                pipeline_run_id=run_id,
            )
            stage_metrics.records_seen = rep.relevant_total
            stage_metrics.records_processed = rep.extracted
            stage_metrics.records_skipped = rep.already_processed
            stage_metrics.records_failed = rep.extraction_failed
            stage_metrics.inc("sparse_extractions", rep.sparse_extractions)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE pipeline_run
                        SET metadata_json = :meta
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": run_id,
                        "meta": json.dumps(
                            {"relevance_analysis_run_id": rep.relevance_analysis_run_id}
                        ),
                    },
                )
        elif stage == "cluster":
            if settings is None:
                settings = Settings.from_env()
            c_opts = cluster_opts or ClusterOptions()
            if not c_opts.analysis_run_id and extract_opts and extract_opts.analysis_run_id:
                c_opts = ClusterOptions(
                    analysis_run_id=extract_opts.analysis_run_id,
                    cluster_analysis_run_id=c_opts.cluster_analysis_run_id,
                    research_set_path=c_opts.research_set_path or extract_opts.research_set_path,
                    num_clusters=c_opts.num_clusters,
                    label_clusters=c_opts.label_clusters,
                    llm_provider=c_opts.llm_provider or extract_opts.llm_provider,
                    force=c_opts.force,
                )
            rep = run_cluster(engine, settings, c_opts, dry_run=dry_run)
            stage_metrics.records_seen = rep.records_in
            stage_metrics.records_processed = rep.members_assigned
            stage_metrics.inc("num_clusters", rep.num_clusters)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE pipeline_run
                        SET metadata_json = :meta
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": run_id,
                        "meta": json.dumps(
                            {
                                "source_analysis_run_id": rep.source_analysis_run_id,
                                "cluster_analysis_run_id": rep.cluster_analysis_run_id,
                            }
                        ),
                    },
                )
        elif stage == "opportunity":
            c_opts = cluster_opts or ClusterOptions()
            if not c_opts.cluster_analysis_run_id and publish_opts and publish_opts.cluster_analysis_run_id:
                c_opts = ClusterOptions(
                    cluster_analysis_run_id=publish_opts.cluster_analysis_run_id,
                    force=c_opts.force,
                )
            rep = run_opportunity(engine, c_opts, dry_run=dry_run)
            stage_metrics.records_processed = rep.clusters_scored
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE pipeline_run
                        SET metadata_json = :meta
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": run_id,
                        "meta": json.dumps(
                            {"cluster_analysis_run_id": rep.cluster_analysis_run_id}
                        ),
                    },
                )
        elif stage == "publish":
            p_opts = publish_opts or PublishOptions()
            if cluster_opts and cluster_opts.cluster_analysis_run_id and not p_opts.cluster_analysis_run_id:
                p_opts = PublishOptions(
                    analysis_run_id=cluster_opts.analysis_run_id or p_opts.analysis_run_id,
                    cluster_analysis_run_id=cluster_opts.cluster_analysis_run_id,
                    research_set_path=cluster_opts.research_set_path or p_opts.research_set_path,
                    num_clusters=cluster_opts.num_clusters,
                    label_clusters=cluster_opts.label_clusters,
                    llm_provider=cluster_opts.llm_provider or p_opts.llm_provider,
                    force=cluster_opts.force,
                    top_opportunities=p_opts.top_opportunities,
                    markdown_output=p_opts.markdown_output,
                    json_output=p_opts.json_output,
                )
            rep = run_publish(
                engine, p_opts, dry_run=dry_run, pipeline_run_id=run_id
            )
            stage_metrics.records_processed = rep.opportunities_published
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE pipeline_run
                        SET metadata_json = :meta
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": run_id,
                        "meta": json.dumps(
                            {
                                "snapshot_id": rep.snapshot_id,
                                "cluster_analysis_run_id": rep.cluster_analysis_run_id,
                                "markdown_path": rep.markdown_path,
                                "json_path": rep.json_path,
                            }
                        ),
                    },
                )
        else:
            _run_not_implemented(stage, dry_run=dry_run, stage_metrics=stage_metrics)

        status = "completed_dry_run" if dry_run else "completed"
        _update_pipeline_run(engine, run_id, status=status)
    except Exception as exc:
        _update_pipeline_run(engine, run_id, status="failed", error=str(exc))
        raise

    metrics.emit_all()
    return run_id


def _update_pipeline_run(
    engine: Engine,
    run_id: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE pipeline_run
                SET status = :status, updated_at = :updated, error_message = :error
                WHERE id = :id
                """
            ),
            {
                "id": run_id,
                "status": status,
                "updated": _utc_now(),
                "error": error,
            },
        )


def _run_preprocess(engine: Engine, *, dry_run: bool, stage_metrics) -> None:
    report = run_preprocess(engine, dry_run=dry_run)
    stage_metrics.records_seen = report.raw_seen
    stage_metrics.records_processed = report.canonical_created
    stage_metrics.records_skipped = (
        report.already_canonical + report.excluded_noise + report.exact_duplicates + report.near_duplicates
    )
    stage_metrics.records_failed = report.failed
    stage_metrics.inc("excluded_noise", report.excluded_noise)
    stage_metrics.inc("exact_duplicates", report.exact_duplicates)
    stage_metrics.inc("near_duplicates", report.near_duplicates)
    if dry_run:
        logger.info("preprocess dry-run complete: %s", report.to_dict())
    else:
        logger.info("preprocess complete: %s", report.to_dict())


def _run_not_implemented(stage: str, *, dry_run: bool, stage_metrics) -> None:
    stage_metrics.records_seen = 0
    msg = f"Stage '{stage}' is not implemented yet (see implementation-plan.md)."
    if dry_run:
        logger.info("%s (dry-run acknowledged)", msg)
        return
    raise NotImplementedError(msg)
