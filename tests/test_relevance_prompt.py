from __future__ import annotations

import uuid

from sqlalchemy import text

from discover.db import get_engine, run_migrations
from discover.config import Settings
from discover.llm.prompts import build_relevance_batch_prompt
from discover.llm.schemas import RELEVANCE_PROMPT_VERSION
from discover.pipeline.relevance import export_relevance_summary


def test_relevance_prompt_version_v2() -> None:
    assert RELEVANCE_PROMPT_VERSION == "relevance_v2"


def test_prompt_requires_gp_and_retrieval_rationale() -> None:
    prompt = build_relevance_batch_prompt(
        [
            {
                "record_id": "x",
                "source_type": "reddit",
                "title": "t",
                "body": "body",
                "permalink": "https://example.com",
            }
        ]
    )
    assert "relevance_v2" in prompt
    assert "Google Photos context" in prompt or "(A)" in prompt
    assert "do not infer" in prompt.lower() or "do not infer" in prompt
    assert "Google Lens" in prompt


def test_export_relevance_summary_excludes_sample01_fixture(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    engine = get_engine(Settings.from_env().database_url)
    run_migrations(engine)
    aid = str(uuid.uuid4())
    rid_fixture = str(uuid.uuid4())
    rid_normal = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO analysis_run (id, label, model_id, prompt_version)
                VALUES (:id, 't', 'mock:x', 'relevance_v2')
                """
            ),
            {"id": aid},
        )
        ingest_id = str(uuid.uuid4())
        conn.execute(
            text(
                """
                INSERT INTO ingest_run (id, source_type, started_at, status)
                VALUES (:id, 'reddit', datetime('now'), 'completed')
                """
            ),
            {"id": ingest_id},
        )
        for rid, permalink in (
            (
                rid_fixture,
                "https://www.reddit.com/r/googlephotos/comments/abc/sample01/",
            ),
            (rid_normal, "https://www.reddit.com/r/test/comments/real/"),
        ):
            raw_id = str(uuid.uuid4())
            conn.execute(
                text(
                    """
                    INSERT INTO raw_record (id, ingest_run_id, source_type, payload_json)
                    VALUES (:id, :ingest, 'reddit', '{}')
                    """
                ),
                {"id": raw_id, "ingest": ingest_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO canonical_record (
                        id, raw_record_id, source_type, title, body, permalink, content_hash
                    )
                    VALUES (:id, :raw, 'reddit', '', 'x', :link, :hash)
                    """
                ),
                {"id": rid, "raw": raw_id, "hash": rid, "link": permalink},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO relevance_result (
                        id, record_id, analysis_run_id, is_relevant, confidence, rationale,
                        model_id, gate_passed, gate_reason, analysis_status, prompt_version
                    )
                    VALUES (
                        :id, :rid, :aid, 1, 0.9, 'r', 'mock', 1, 'passed', 'completed', 'relevance_v2'
                    )
                    """
                ),
                {"id": str(uuid.uuid4()), "rid": rid, "aid": aid},
            )
    summary = export_relevance_summary(engine, aid)
    assert summary["counts"]["excluded_calibration_fixtures"] == 1
    assert summary["counts"]["labeled_total"] == 1
    assert summary["counts"]["relevant"] == 1
