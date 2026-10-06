from __future__ import annotations

from pathlib import Path

from discover.config import Settings
from discover.db import get_engine, run_migrations
from discover.ingest.service import run_ingest
from discover.ingestors.reddit_apify import RedditApifyIngestor
from discover.pipeline.cluster import run_cluster
from discover.pipeline.cluster_options import ClusterOptions
from discover.pipeline.clustering_math import choose_num_clusters, vectorize_documents
from discover.pipeline.extract import ExtractOptions, run_extract
from discover.pipeline.features import build_clustering_document
from discover.pipeline.opportunity import run_opportunity
from discover.pipeline.publish import PublishOptions, render_opportunity_markdown, run_publish
from discover.pipeline.preprocess import run_preprocess
from discover.pipeline.relevance import RelevanceOptions, run_relevance

FIXTURE = Path(__file__).parent / "fixtures" / "reddit_apify_sample.json"


def test_build_clustering_document() -> None:
    doc = build_clustering_document(
        title="Lost photo",
        body="Cannot find it in Google Photos",
        structured_fields={"search_attempt": "tried keywords", "outcome": "failure"},
    )
    assert "search_attempt" in doc
    assert "Google Photos" in doc


def test_choose_num_clusters_small() -> None:
    docs = [
        "find screenshot google photos search failed",
        "remember wallpaper google photo cannot find",
        "recipe unrelated cooking",
        "another unrelated post about cats",
    ]
    _, matrix = vectorize_documents(docs)
    k = choose_num_clusters(matrix, len(docs), None)
    assert 2 <= k <= 3


def test_phase4_mock_pipeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'p4.db').as_posix()}")
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    settings = Settings.from_env()
    engine = get_engine(settings.database_url)
    run_migrations(engine)

    run_ingest(engine, RedditApifyIngestor.from_path(FIXTURE), source_path=FIXTURE, archive_raw=False)
    run_preprocess(engine, dry_run=False)

    rel = run_relevance(
        engine,
        settings,
        RelevanceOptions(llm_provider="mock"),
        dry_run=False,
    )
    ext = run_extract(
        engine,
        settings,
        ExtractOptions(llm_provider="mock", analysis_run_id=rel.analysis_run_id),
        dry_run=False,
    )
    if ext.extracted < 2:
        return

    cluster = run_cluster(
        engine,
        settings,
        ClusterOptions(
            analysis_run_id=rel.analysis_run_id,
            llm_provider="mock",
            label_clusters=True,
            num_clusters=2,
        ),
        dry_run=False,
    )
    assert cluster.num_clusters >= 2
    assert cluster.members_assigned == cluster.records_in

    opp = run_opportunity(
        engine,
        ClusterOptions(cluster_analysis_run_id=cluster.cluster_analysis_run_id),
        dry_run=False,
    )
    assert opp.clusters_scored == cluster.num_clusters

    pub = run_publish(
        engine,
        PublishOptions(
            cluster_analysis_run_id=cluster.cluster_analysis_run_id,
            top_opportunities=3,
            json_output=tmp_path / "snap.json",
            markdown_output=tmp_path / "summary.md",
        ),
        dry_run=False,
    )
    assert pub.snapshot_id
    assert (tmp_path / "summary.md").is_file()
    md = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Retrieval opportunity summary" in md
    assert render_opportunity_markdown({"top_opportunities": []}).startswith("#")
