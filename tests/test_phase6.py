from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from discover.api.app import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_serve_ui_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Google Photos Discovery" in res.text
    assert "Record Explorer" in res.text


def test_serve_ui_css(client):
    res = client.get("/css/styles.css")
    assert res.status_code == 200
    assert "--bg-dark:" in res.text


def test_serve_ui_js(client):
    res = client.get("/js/app.js")
    assert res.status_code == 200
    assert "loadAllData" in res.text
