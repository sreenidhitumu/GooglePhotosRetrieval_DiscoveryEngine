from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from discover.cli import cli
from discover.config import Settings
from discover.db import get_engine, run_migrations
from discover.llm.gateway import get_llm_gateway
from discover.llm.schemas import validate_relevance_item
from discover.pipeline.calibration_prefilter import evaluate_calibration_prefilter
from discover.pipeline.gate import evaluate_deterministic_gate
from discover.pipeline.preprocess import run_preprocess
from discover.pipeline.relevance import RelevanceOptions, run_relevance
from discover.ingest.service import run_ingest
from discover.ingestors.reddit_apify import RedditApifyIngestor

FIXTURE = Path(__file__).parent / "fixtures" / "reddit_apify_sample.json"


def test_calibration_prefilter_allows_broad_photo_thread() -> None:
    """Gate would skip; calibration prefilter should pass to LLM."""
    assert not evaluate_deterministic_gate(
        None,
        "Many thanks, that software helped me a lot!",
    ).passed
    assert not evaluate_calibration_prefilter(None, "Many thanks, that software helped me a lot!").exclude


def test_calibration_prefilter_blocks_removed() -> None:
    assert evaluate_calibration_prefilter(None, "[deleted]").exclude


def test_gate_source_agnostic_examples() -> None:
    assert evaluate_deterministic_gate(
        "Lost photo",
        "I remember a screenshot in Google Photos but can't find it after searching.",
    ).passed
    assert not evaluate_deterministic_gate(
        "Slow app",
        "Google Photos is so slow after the update.",
    ).passed


def test_validate_relevance_schema() -> None:
    item = validate_relevance_item(
        {
            "record_id": "abc",
            "is_relevant": True,
            "confidence": 0.9,
            "rationale": "Describes fuzzy memory and failed GP search.",
            "retrieval_signal_types": ["memory_gap", "search_formulation"],
        },
        "abc",
    )
    assert item["is_relevant"] is True


def test_relevance_mock_pipeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'p2.db').as_posix()}")
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    engine = get_engine(Settings.from_env().database_url)
    run_migrations(engine)

    ingestor = RedditApifyIngestor.from_path(FIXTURE)
    run_ingest(engine, ingestor, source_path=FIXTURE, archive_raw=False)
    run_preprocess(engine, dry_run=False)

    report = run_relevance(
        engine,
        Settings.from_env(),
        RelevanceOptions(llm_provider="mock"),
        dry_run=False,
        pipeline_run_id="00000000-0000-4000-8000-000000000001",
    )
    assert report.llm_classified >= 0
    assert report.analysis_run_id

    gateway = get_llm_gateway(Settings.from_env(), "mock")
    batch = gateway.classify_relevance_batch(
        [
            {
                "record_id": "x",
                "source_type": "reddit",
                "title": "Google Photos search",
                "body": "I remember the screenshot but can't find it in Google Photos.",
                "permalink": "https://example.com",
            }
        ]
    )
    assert batch[0]["is_relevant"] is True


def test_relevance_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'idem.db').as_posix()}")
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    settings = Settings.from_env()
    engine = get_engine(settings.database_url)
    run_migrations(engine)
    run_ingest(engine, RedditApifyIngestor.from_path(FIXTURE), source_path=FIXTURE, archive_raw=False)
    run_preprocess(engine, dry_run=False)

    opts = RelevanceOptions(llm_provider="mock")
    r1 = run_relevance(engine, settings, opts, dry_run=False)
    r2 = run_relevance(
        engine,
        settings,
        RelevanceOptions(llm_provider="mock", analysis_run_id=r1.analysis_run_id),
        dry_run=False,
    )
    assert r2.already_processed >= 1
    assert r2.llm_classified == 0


def test_cli_relevance_dry_run(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "cli_p2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    runner = CliRunner()
    assert runner.invoke(cli, ["migrate"]).exit_code == 0
    assert runner.invoke(
        cli, ["ingest", "--source", "reddit", "--file", str(FIXTURE)]
    ).exit_code == 0
    assert runner.invoke(cli, ["run", "--stage", "preprocess"]).exit_code == 0
    result = runner.invoke(
        cli,
        ["run", "--stage", "relevance", "--dry-run", "--llm-provider", "mock"],
    )
    assert result.exit_code == 0
