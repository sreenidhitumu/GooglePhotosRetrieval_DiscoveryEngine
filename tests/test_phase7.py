from __future__ import annotations

import json
from pathlib import Path
import pytest

from discover.ingestors.registry import get_ingestor
from discover.ingestors.store_review import StoreReviewIngestor
from discover.ingestors.youtube import YouTubeIngestor
from discover.llm.providers import FallbackProvider, MockRelevanceProvider, LLMProvider
from discover.metrics import TokenTelemetry
from discover.pipeline.normalize import normalize_raw_record
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_eval import run_evaluation


class FailingProvider(LLMProvider):
    @property
    def model_id(self) -> str:
        return "failing:mock"

    def generate_json(self, prompt: str) -> dict:
        raise RuntimeError("API simulated rate limit failure")


def test_youtube_ingestor_and_normalization(tmp_path: Path) -> None:
    data = [
        {
            "id": "yt-101",
            "video_id": "v123",
            "title": "Google Photos Search Demo",
            "comment_text": "I can't find my old dog photos from 2020.",
            "author": "user_yt",
            "publishedAt": "2026-01-01T10:00:00Z",
        }
    ]
    yt_file = tmp_path / "yt.json"
    yt_file.write_text(json.dumps(data), encoding="utf-8")

    ingestor = get_ingestor("youtube", yt_file)
    assert isinstance(ingestor, YouTubeIngestor)
    assert ingestor.discover() == 1

    refs = list(ingestor.iter_records())
    assert len(refs) == 1
    assert refs[0].source_native_id == "yt-101"

    draft = normalize_raw_record("youtube", refs[0].payload)
    assert draft.source_type == "youtube"
    assert "dog photos" in draft.body
    assert draft.permalink == "https://www.youtube.com/watch?v=v123"


def test_store_review_ingestor_json_and_csv(tmp_path: Path) -> None:
    json_data = [
        {
            "id": "rev-1",
            "title": "Broken search",
            "body": "Search feature returns nothing.",
            "author": "tester",
            "score": 1,
        }
    ]
    json_file = tmp_path / "google_play_reviews.json"
    json_file.write_text(json.dumps(json_data), encoding="utf-8")

    ingestor = get_ingestor("google_play", json_file)
    assert isinstance(ingestor, StoreReviewIngestor)
    assert ingestor.source_type == "google_play"
    refs = list(ingestor.iter_records())
    assert len(refs) == 1

    draft = normalize_raw_record("google_play", refs[0].payload)
    assert draft.source_type == "google_play"
    assert draft.title == "Broken search"

    # CSV Test
    csv_file = tmp_path / "appstore_reviews.csv"
    csv_file.write_text("id,review_title,body,rating\nrev-2,EXIF filter missing,Cannot filter by camera,2\n", encoding="utf-8")
    csv_ingestor = get_ingestor("app_store", csv_file)
    assert isinstance(csv_ingestor, StoreReviewIngestor)
    assert csv_ingestor.source_type == "app_store"
    csv_refs = list(csv_ingestor.iter_records())
    assert len(csv_refs) == 1

    draft_csv = normalize_raw_record("app_store", csv_refs[0].payload)
    assert draft_csv.source_type == "app_store"
    assert draft_csv.title == "EXIF filter missing"


def test_fallback_provider_resilience() -> None:
    primary = FailingProvider()
    secondary = MockRelevanceProvider()
    fallback = FallbackProvider(primary, secondary)

    assert "fallback" in fallback.model_id
    prompt = "Records:\n" + json.dumps([{"record_id": "r1", "title": "google photos", "body": "can't find my photo"}])
    res = fallback.generate_json(prompt)
    assert "results" in res
    assert res["results"][0]["is_relevant"] is True


def test_token_telemetry_cost_calculation() -> None:
    telemetry = TokenTelemetry()
    telemetry.record_llm_call("gemini:gemini-2.0-flash", input_tokens=1_000_000, output_tokens=500_000)

    # 1M input * $0.10 + 0.5M output * $0.40 = $0.10 + $0.20 = $0.30
    assert telemetry.llm_calls == 1
    assert telemetry.estimated_cost_usd == 0.30
    d = telemetry.to_dict()
    assert d["estimated_cost_usd"] == 0.30


def test_gold_set_evaluation_runner() -> None:
    report = run_evaluation(Path("data/processed/relevance_gold_set.json"), provider_name="mock")
    assert report["gold_set_size"] == 15
    assert report["metrics"]["precision"] >= 0.80
    assert "f1_score" in report["metrics"]
