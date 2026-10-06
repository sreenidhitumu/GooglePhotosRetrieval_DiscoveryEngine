from __future__ import annotations

from pathlib import Path

from discover.config import Settings
from discover.db import get_engine, run_migrations
from discover.ingest.service import run_ingest
from discover.ingestors.reddit_apify import RedditApifyIngestor
from discover.llm.extraction_schemas import validate_extraction_item
from discover.pipeline.extract import ExtractOptions, export_extraction_summary, run_extract
from discover.pipeline.preprocess import run_preprocess
from discover.pipeline.relevance import RelevanceOptions, run_relevance

FIXTURE = Path(__file__).parent / "fixtures" / "reddit_apify_sample.json"


def test_validate_extraction_schema() -> None:
    item = validate_extraction_item(
        {
            "record_id": "abc",
            "retrieval_scenario": "Find screenshot in Google Photos",
            "remembers": "Saved APK screenshots",
            "forgotten": None,
            "search_attempt": "Keyword search in GP",
            "failure_point": "No results",
            "workaround": None,
            "outcome": "failure",
            "evidence_spans": {"search_attempt": "Keyword search in GP"},
        },
        "abc",
    )
    assert item["structured_fields"]["outcome"] == "failure"
    assert item["extraction_sparse"] is False


def test_extract_mock_pipeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'p3.db').as_posix()}")
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
    assert ext.relevant_total >= 0
    summary = export_extraction_summary(engine, rel.analysis_run_id)
    if rel.relevant > 0:
        assert summary["counts"]["completed"] >= 1
