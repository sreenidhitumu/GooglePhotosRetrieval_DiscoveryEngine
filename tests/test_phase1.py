from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from discover.cli import cli
from discover.db import get_engine, run_migrations
from discover.ingest.service import run_ingest
from discover.ingestors.reddit_apify import RedditApifyIngestor
from discover.pipeline.normalize import normalize_reddit_payload
from discover.pipeline.preprocess import run_preprocess
from discover.text_utils import combined_text

FIXTURE = Path(__file__).parent / "fixtures" / "reddit_apify_sample.json"
DATASET = Path(__file__).resolve().parents[1] / (
    "dataset_reddit-scraper-lite_2026-09-29_17-56-33-680.json"
)


def test_reddit_apify_normalization_golden() -> None:
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    draft = normalize_reddit_payload(records[0])
    assert draft.source_type == "reddit"
    assert draft.permalink.startswith("https://www.reddit.com/")
    assert "won't surface" in combined_text(draft.title, draft.body)
    assert draft.content_hash
    assert draft.author_handle == "test_user"


def test_ingest_and_preprocess_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "phase1.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = get_engine(url)
    run_migrations(engine)

    ingestor = RedditApifyIngestor.from_path(FIXTURE)
    first = run_ingest(engine, ingestor, source_path=FIXTURE)
    assert first.records_ingested == 1

    report = run_preprocess(engine, dry_run=False)
    assert report.canonical_created == 1

    report2 = run_preprocess(engine, dry_run=False)
    assert report2.already_canonical == 1
    assert report2.canonical_created == 0


def test_full_reddit_dataset_meets_phase1_targets(tmp_path: Path) -> None:
    if not DATASET.is_file():
        return

    db_path = tmp_path / "reddit_full.db"
    engine = get_engine(f"sqlite:///{db_path.as_posix()}")
    run_migrations(engine)

    ingestor = RedditApifyIngestor.from_path(DATASET)
    ing = run_ingest(engine, ingestor, source_path=DATASET, archive_raw=False)
    assert ing.records_ingested == 1000

    report = run_preprocess(engine, dry_run=False)
    with engine.connect() as conn:
        from sqlalchemy import text

        canonical_count = conn.execute(text("SELECT COUNT(*) FROM canonical_record")).scalar()
        with_permalink = conn.execute(
            text(
                "SELECT COUNT(*) FROM canonical_record WHERE permalink IS NOT NULL AND permalink != ''"
            )
        ).scalar()
        empty_combined = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM canonical_record
                WHERE trim(coalesce(title, '') || coalesce(body, '')) = ''
                """
            )
        ).scalar()

    assert canonical_count >= 900
    assert with_permalink == canonical_count
    assert empty_combined == 0
    assert report.excluded_noise >= 20


def test_cli_ingest_preprocess(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli_phase1.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    runner = CliRunner()
    assert runner.invoke(cli, ["migrate"]).exit_code == 0
    result = runner.invoke(
        cli,
        ["ingest", "--source", "reddit", "--file", str(FIXTURE)],
    )
    assert result.exit_code == 0
    assert "ingest_run_id=" in result.output

    result = runner.invoke(cli, ["run", "--stage", "preprocess"])
    assert result.exit_code == 0
