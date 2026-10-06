from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click

from discover.config import Settings, ensure_data_dirs, project_root
from discover.db import get_engine, migration_status, run_migrations
from discover.ingest.service import run_ingest
from discover.ingestors.registry import get_ingestor
from discover.logging_setup import configure_logging
from discover.metrics import MetricsCollector
from discover.pipeline.extract import (
    ExtractOptions,
    export_extraction_qa_sample,
    export_extraction_summary,
)
from discover.pipeline.relevance import RelevanceOptions, export_relevance_summary
from discover.pipeline.cluster_options import ClusterOptions
from discover.pipeline.publish import PublishOptions, export_opportunity_ranking
from discover.pipeline.runner import STAGES, run_stage

logger = logging.getLogger(__name__)


@click.group()
@click.option("--log-level", default=None, help="Override LOG_LEVEL from environment")
@click.option("--json-logs", is_flag=True, help="Emit structured JSON logs")
@click.pass_context
def cli(ctx: click.Context, log_level: str | None, json_logs: bool) -> None:
    """Discovery engine for Google Photos retrieval research."""
    settings = Settings.from_env()
    level = log_level or settings.log_level
    configure_logging(level=level, json_logs=json_logs or settings.log_json)
    ensure_data_dirs()
    ctx.ensure_object(dict)
    ctx.obj["settings"] = settings


@cli.command()
@click.pass_context
def migrate(ctx: click.Context) -> None:
    """Apply database migrations."""
    settings: Settings = ctx.obj["settings"]
    engine = get_engine(settings.database_url)
    applied = run_migrations(engine)
    if applied:
        click.echo(f"Applied migrations: {', '.join(applied)}")
    else:
        click.echo("Database is up to date.")
    for version, filename, is_applied in migration_status(engine):
        mark = "ok" if is_applied else "pending"
        click.echo(f"  [{mark}] {version} {filename}")


@cli.command()
@click.option("--source", type=str, required=True, help="Source type (e.g. reddit)")
@click.option("--file", "file_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--force", is_flag=True, help="Re-ingest even if file checksum was already imported")
@click.pass_context
def ingest(ctx: click.Context, source: str, file_path: Path, force: bool) -> None:
    """Ingest raw data from a source into raw_record."""
    settings: Settings = ctx.obj["settings"]
    engine = get_engine(settings.database_url)
    run_migrations(engine)

    ingestor = get_ingestor(source, file_path)
    result = run_ingest(engine, ingestor, source_path=file_path, force=force)
    if result.reused_existing_run:
        click.echo(
            f"Ingest skipped (checksum match). Existing ingest_run_id={result.ingest_run_id}"
        )
        return
    click.echo(
        f"Ingest complete. ingest_run_id={result.ingest_run_id} "
        f"records_ingested={result.records_ingested} "
        f"skipped_existing_native_id={result.records_skipped_existing} "
        f"checksum={result.input_checksum[:12]}…"
    )


@cli.command("run")
@click.option(
    "--stage",
    type=click.Choice(STAGES, case_sensitive=False),
    required=True,
    help="Pipeline stage to run",
)
@click.option("--dry-run", is_flag=True, help="Simulate stage without writing pipeline results")
@click.option(
    "--resume",
    is_flag=True,
    help="Continue latest analysis run (relevance or extract)",
)
@click.option("--limit", type=int, default=None, help="Max new records to process (relevance)")
@click.option(
    "--analysis-run-id",
    default=None,
    help="Relevance analysis run UUID (relevance + extract)",
)
@click.option("--force", is_flag=True, help="Re-classify even if result exists (relevance)")
@click.option(
    "--llm-provider",
    type=click.Choice(["gemini", "groq", "mock"], case_sensitive=False),
    default=None,
)
@click.option(
    "--bypass-gate",
    is_flag=True,
    help="Relevance calibration: skip deterministic gate; minimal prefilter only",
)
@click.option(
    "--research-set",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Limit to record_ids from research-set JSON (extract, cluster)",
)
@click.option(
    "--cluster-analysis-run-id",
    default=None,
    help="Clustering analysis run UUID (opportunity, publish; optional resume for cluster)",
)
@click.option("--num-clusters", type=int, default=None, help="Override k for k-means (cluster)")
@click.option(
    "--no-cluster-labels",
    is_flag=True,
    help="Skip LLM cluster naming (cluster stage)",
)
@click.option(
    "--top-opportunities",
    type=int,
    default=5,
    help="How many ranked opportunities to publish (publish stage)",
)
@click.pass_context
def run_pipeline(
    ctx: click.Context,
    stage: str,
    dry_run: bool,
    resume: bool,
    limit: int | None,
    analysis_run_id: str | None,
    force: bool,
    llm_provider: str | None,
    bypass_gate: bool,
    research_set: Path | None,
    cluster_analysis_run_id: str | None,
    num_clusters: int | None,
    no_cluster_labels: bool,
    top_opportunities: int,
) -> None:
    """Run a pipeline stage."""
    settings: Settings = ctx.obj["settings"]
    engine = get_engine(settings.database_url)
    run_migrations(engine)

    metrics = MetricsCollector()
    if bypass_gate and stage.lower() != "relevance":
        raise click.ClickException("--bypass-gate is only valid with --stage relevance")
    stage_l = stage.lower()
    if research_set and stage_l not in ("extract", "cluster"):
        raise click.ClickException("--research-set is only valid with --stage extract or cluster")
    if cluster_analysis_run_id and stage_l not in ("cluster", "opportunity", "publish"):
        raise click.ClickException(
            "--cluster-analysis-run-id is only valid with cluster, opportunity, or publish"
        )
    if num_clusters is not None and stage_l != "cluster":
        raise click.ClickException("--num-clusters is only valid with --stage cluster")
    if no_cluster_labels and stage_l != "cluster":
        raise click.ClickException("--no-cluster-labels is only valid with --stage cluster")
    if top_opportunities != 5 and stage_l != "publish":
        raise click.ClickException("--top-opportunities is only valid with --stage publish")

    relevance_opts = RelevanceOptions(
        resume=resume,
        limit=limit,
        analysis_run_id=analysis_run_id,
        force=force,
        llm_provider=llm_provider,
        bypass_gate=bypass_gate,
    )
    extract_opts = ExtractOptions(
        resume=resume,
        limit=limit,
        analysis_run_id=analysis_run_id,
        force=force,
        llm_provider=llm_provider,
        research_set_path=research_set if stage_l == "extract" else None,
    )
    cluster_opts = ClusterOptions(
        analysis_run_id=analysis_run_id,
        cluster_analysis_run_id=cluster_analysis_run_id,
        research_set_path=research_set if stage_l == "cluster" else None,
        num_clusters=num_clusters,
        label_clusters=not no_cluster_labels,
        llm_provider=llm_provider,
        force=force,
    )
    publish_opts = PublishOptions(
        analysis_run_id=analysis_run_id,
        cluster_analysis_run_id=cluster_analysis_run_id,
        top_opportunities=top_opportunities,
        llm_provider=llm_provider,
        force=force,
    )
    try:
        run_id = run_stage(
            engine,
            stage_l,
            dry_run=dry_run,
            metrics=metrics,
            settings=settings,
            relevance_opts=relevance_opts,
            extract_opts=extract_opts,
            cluster_opts=cluster_opts,
            publish_opts=publish_opts,
        )
    except NotImplementedError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    except ValueError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc

    suffix = " (dry-run)" if dry_run else ""
    click.echo(f"Stage '{stage}' finished{suffix}. pipeline_run_id={run_id}")


@cli.command("relevance-report")
@click.option("--analysis-run-id", required=True)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Write JSON report (default: data/processed/relevance_report_<id>.json)",
)
@click.pass_context
def relevance_report(ctx: click.Context, analysis_run_id: str, output: Path | None) -> None:
    """Export relevance calibration summary for an analysis run."""
    settings: Settings = ctx.obj["settings"]
    engine = get_engine(settings.database_url)
    run_migrations(engine)
    summary = export_relevance_summary(engine, analysis_run_id)
    if output is None:
        output = (
            project_root()
            / "data"
            / "processed"
            / f"relevance_report_{analysis_run_id[:8]}.json"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    click.echo(f"Wrote {output}")
    click.echo(
        f"relevant={summary['counts']['relevant']} "
        f"not_relevant={summary['counts']['not_relevant']} "
        f"gate_skipped={summary['counts']['gate_skipped']}"
    )


@cli.command("extract-report")
@click.option("--analysis-run-id", required=True, help="Relevance analysis run UUID")
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Write JSON report (default: data/processed/extraction_report_<id>.json)",
)
@click.pass_context
def extract_report(ctx: click.Context, analysis_run_id: str, output: Path | None) -> None:
    """Export extraction summary for a relevance analysis run."""
    settings: Settings = ctx.obj["settings"]
    engine = get_engine(settings.database_url)
    run_migrations(engine)
    summary = export_extraction_summary(engine, analysis_run_id)
    if output is None:
        output = (
            project_root()
            / "data"
            / "processed"
            / f"extraction_report_{analysis_run_id[:8]}.json"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    click.echo(f"Wrote {output}")
    click.echo(
        f"completed={summary['counts']['completed']} "
        f"failed={summary['counts']['failed']} "
        f"sparse={summary['counts']['sparse_lt_3_fields']}"
    )


@cli.command("extract-qa-sample")
@click.option("--analysis-run-id", required=True, help="Relevance analysis run UUID")
@click.option("--sample-size", type=int, default=20)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Write JSON sample (default: data/processed/extraction_qa_sample_<id>.json)",
)
@click.pass_context
def extract_qa_sample(
    ctx: click.Context, analysis_run_id: str, sample_size: int, output: Path | None
) -> None:
    """Export random extraction QA sample (stratified by source_type)."""
    settings: Settings = ctx.obj["settings"]
    engine = get_engine(settings.database_url)
    run_migrations(engine)
    sample = export_extraction_qa_sample(
        engine, analysis_run_id, sample_size=sample_size
    )
    if output is None:
        output = (
            project_root()
            / "data"
            / "processed"
            / f"extraction_qa_sample_{analysis_run_id[:8]}.json"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sample, indent=2), encoding="utf-8")
    click.echo(f"Wrote {output} ({len(sample)} records)")


@cli.command("opportunity-report")
@click.option("--cluster-analysis-run-id", required=True)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Write JSON ranking (default: data/processed/opportunity_ranking_<id>.json)",
)
@click.pass_context
def opportunity_report(
    ctx: click.Context, cluster_analysis_run_id: str, output: Path | None
) -> None:
    """Export ranked opportunity scores for a clustering run."""
    settings: Settings = ctx.obj["settings"]
    engine = get_engine(settings.database_url)
    run_migrations(engine)
    summary = export_opportunity_ranking(engine, cluster_analysis_run_id)
    if output is None:
        output = (
            project_root()
            / "data"
            / "processed"
            / f"opportunity_ranking_{cluster_analysis_run_id[:8]}.json"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    click.echo(f"Wrote {output} ({len(summary.get('opportunities', []))} clusters)")


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host interface to bind to")
@click.option("--port", type=int, default=8000, help="Port to listen on")
@click.option("--reload", is_flag=True, help="Enable auto-reload on code changes")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, reload: bool) -> None:
    """Start the Phase 5 Research API server."""
    import uvicorn
    settings: Settings = ctx.obj["settings"]
    engine = get_engine(settings.database_url)
    run_migrations(engine)
    click.echo(f"Starting Research API server at http://{host}:{port}")
    uvicorn.run("discover.api.app:app", host=host, port=port, reload=reload)


@cli.command()
@click.option("--cluster-analysis-run-id", required=True)
@click.option("--top-opportunities", type=int, default=5)
@click.option("--dry-run", is_flag=True)
@click.pass_context
def publish(
    ctx: click.Context,
    cluster_analysis_run_id: str,
    top_opportunities: int,
    dry_run: bool,
) -> None:
    """Publish ranked opportunities snapshot and markdown summary."""
    settings: Settings = ctx.obj["settings"]
    engine = get_engine(settings.database_url)
    run_migrations(engine)
    metrics = MetricsCollector()
    publish_opts = PublishOptions(
        cluster_analysis_run_id=cluster_analysis_run_id,
        top_opportunities=top_opportunities,
    )
    run_id = run_stage(
        engine,
        "publish",
        dry_run=dry_run,
        metrics=metrics,
        settings=settings,
        publish_opts=publish_opts,
    )
    suffix = " (dry-run)" if dry_run else ""
    click.echo(f"Publish finished{suffix}. pipeline_run_id={run_id}")


def main() -> None:
    try:
        cli(obj={})
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        click.echo("Interrupted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
