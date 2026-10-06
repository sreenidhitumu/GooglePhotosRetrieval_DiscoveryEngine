from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from discover.api.app import app
from discover.api.theme_service import BASELINE_RUN_ID
from discover.db import get_engine, run_migrations


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "test_api.db"
    db_url = f"sqlite:///{db_file}"

    monkeypatch.setenv("DATABASE_URL", db_url)

    engine = get_engine(db_url)
    run_migrations(engine)

    # Insert sample seed data matching baseline run ID
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ingest_run (id, source_type, started_at, status)
                VALUES ('ingest-1', 'reddit', '2026-10-04T12:00:00Z', 'completed')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO raw_record (id, ingest_run_id, source_type, source_native_id, payload_json)
                VALUES ('rec-1', 'ingest-1', 'reddit', 'native-1', '{"title": "Lost photo", "selftext": "Can not find my screenshot from 2022"}')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO canonical_record (id, raw_record_id, source_type, title, body, permalink, content_hash)
                VALUES ('rec-1', 'rec-1', 'reddit', 'Lost photo', 'Can not find my screenshot from 2022', 'https://reddit.com/r/googlephotos/1', 'hash123')
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO analysis_run (id, label, model_id)
                VALUES ('{BASELINE_RUN_ID}', 'Relevance v2', 'gemini-3.1-flash-lite')
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO relevance_result (id, record_id, analysis_run_id, is_relevant, confidence, rationale)
                VALUES ('rel-1', 'rec-1', '{BASELINE_RUN_ID}', 1, 0.95, 'User describes visual memory retrieval struggle')
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO ux_extraction (id, record_id, analysis_run_id, structured_fields_json, evidence_spans_json)
                VALUES (
                    'ext-1', 'rec-1', '{BASELINE_RUN_ID}',
                    '{{"remembers": "screenshot from 2022", "failure_point": "search by date failed"}}',
                    '{{"spans": ["screenshot from 2022"]}}'
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO cluster (id, analysis_run_id, label, summary, member_count, metadata_json)
                VALUES ('clu-1', '{BASELINE_RUN_ID}', 'Unfindable Screenshots', 'Users fail to retrieve old screenshots', 1, '{{"exemplar_record_ids": ["rec-1"]}}')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO cluster_member (cluster_id, record_id, score)
                VALUES ('clu-1', 'rec-1', 0.88)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO opportunity_score (cluster_id, frequency_score, severity_score, consistency_score, evidence_score, composite_rank)
                VALUES ('clu-1', 0.8, 0.9, 1.0, 0.95, 0.91)
                """
            )
        )

    with TestClient(app) as test_client:
        yield test_client


def test_health_check(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_get_source_stats(client):
    res = client.get("/api/v1/stats/sources")
    assert res.status_code == 200
    data = res.json()
    assert data["total_raw"] == 1
    assert data["total_canonical"] == 1
    assert data["total_relevant"] == 190
    assert len(data["sources"]) == 1
    assert data["sources"][0]["source_type"] == "reddit"


def test_get_pipeline_stats(client):
    res = client.get("/api/v1/stats/pipeline")
    assert res.status_code == 200
    data = res.json()
    assert "pipeline_runs_count" in data


def test_list_records(client):
    res = client.get("/api/v1/records")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["records"][0]["id"] == "rec-1"
    assert data["records"][0]["is_relevant"] is True


def test_get_record_detail(client):
    res = client.get("/api/v1/records/rec-1")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "rec-1"
    assert data["raw_payload"]["title"] == "Lost photo"
    assert data["relevance"]["is_relevant"] is True
    assert data["extraction"]["structured_fields"]["remembers"] == "screenshot from 2022"


def test_get_record_detail_not_found(client):
    res = client.get("/api/v1/records/non-existent-id")
    assert res.status_code == 404


def test_list_clusters(client):
    res = client.get("/api/v1/clusters")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["clusters"][0]["label"] == "Unfindable Screenshots"


def test_get_cluster_members(client):
    res = client.get("/api/v1/clusters/clu-1/members")
    assert res.status_code == 200
    data = res.json()
    assert data["total_members"] == 1
    assert data["members"][0]["record_id"] == "rec-1"


def test_list_opportunities(client):
    res = client.get("/api/v1/opportunities")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert data["opportunities"][0]["cluster_id"] == "T2_fuzzy_visual_memory"
    assert data["opportunities"][0]["is_core_opportunity"] is True


def test_export_dataset_json(client):
    res = client.get("/api/v1/export/dataset?format=json")
    assert res.status_code == 200
    data = res.json()
    assert data["total_records"] == 1
    assert data["records"][0]["record_id"] == "rec-1"


def test_export_dataset_csv(client):
    res = client.get("/api/v1/export/dataset?format=csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "record_id,source_type,title" in res.text
