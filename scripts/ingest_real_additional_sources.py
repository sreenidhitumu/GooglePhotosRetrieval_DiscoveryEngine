#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Add src/ to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from google_play_scraper import Sort, reviews
from sqlalchemy import text

from discover.config import Settings, project_root
from discover.db import get_engine
from discover.ingest.service import run_ingest
from discover.ingestors.store_review import StoreReviewIngestor
from discover.ingestors.youtube import YouTubeIngestor
from discover.pipeline.extract import ExtractOptions, run_extract
from discover.pipeline.preprocess import run_preprocess
from discover.pipeline.relevance import RelevanceOptions, run_relevance


# Query Families for YouTube
YOUTUBE_QUERY_FAMILIES = {
    "Search failure": [
        "Google Photos can't find photo",
        "Google Photos search not working",
        "Google Photos can't find pictures",
        "Google Photos search bad",
    ],
    "Memory / retrieval": [
        "Google Photos find old photo",
        "Google Photos find specific photo",
        "Google Photos find a photo I remember",
        "Google Photos find forgotten photo",
        "Google Photos where is my photo",
    ],
    "Browsing / workarounds": [
        "Google Photos thousands of photos",
        "Google Photos scrolling to find photo",
        "Google Photos search tips",
        "Google Photos find hidden photos",
    ],
    "AI / Ask Photos": [
        "Google Photos Ask Photos search",
        "Google Photos AI search problems",
        "Google Photos Ask Photos not finding",
        "Google Photos Gemini Photos search",
    ],
}


def fetch_broad_youtube_comments(api_key: str) -> tuple[list[dict], dict[str, int]]:
    collected_items: list[dict] = []
    seen_ids: set[str] = set()
    family_counts: dict[str, int] = {}

    for family_name, queries in YOUTUBE_QUERY_FAMILIES.items():
        family_counts[family_name] = 0
        for query in queries:
            search_url = (
                f"https://www.googleapis.com/youtube/v3/search?"
                f"part=snippet&q={urllib.parse.quote(query)}&type=video&maxResults=5&key={api_key}"
            )
            try:
                req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    search_res = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                print(f"Warning: YouTube search failed for query '{query}': {e}")
                continue

            for item in search_res.get("items", []):
                vid = item.get("id", {}).get("videoId")
                vtitle = item.get("snippet", {}).get("title", "")
                if not vid:
                    continue

                comment_url = (
                    f"https://www.googleapis.com/youtube/v3/commentThreads?"
                    f"part=snippet&videoId={vid}&maxResults=20&key={api_key}"
                )
                try:
                    creq = urllib.request.Request(comment_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(creq, timeout=10) as cresp:
                        cdata = json.loads(cresp.read().decode("utf-8"))
                        for citem in cdata.get("items", []):
                            cid = citem.get("id")
                            if cid and cid not in seen_ids:
                                seen_ids.add(cid)
                                top = citem.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                                collected_items.append(
                                    {
                                        "id": cid,
                                        "video_id": vid,
                                        "video_title": vtitle,
                                        "comment_text": top.get("textDisplay", ""),
                                        "author": top.get("authorDisplayName", ""),
                                        "publishedAt": top.get("publishedAt", ""),
                                        "likeCount": top.get("likeCount", 0),
                                        "query_family": family_name,
                                        "query_used": query,
                                    }
                                )
                                family_counts[family_name] += 1
                except Exception:
                    continue

    return collected_items, family_counts


def fetch_broad_google_play_reviews() -> list[dict]:
    all_reviews: list[dict] = []
    seen_ids: set[str] = set()

    for sort_mode in [Sort.NEWEST, Sort.MOST_RELEVANT]:
        try:
            rvs, _ = reviews(
                "com.google.android.apps.photos",
                lang="en",
                country="us",
                sort=sort_mode,
                count=500,
            )
            for r in rvs:
                rid = r.get("reviewId")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    all_reviews.append(
                        {
                            "id": rid,
                            "title": r.get("reviewTitle") or f"Review by {r.get('userName')}",
                            "body": r.get("content"),
                            "score": r.get("score"),
                            "userName": r.get("userName"),
                            "at": r.get("at").isoformat() if r.get("at") else None,
                            "thumbsUpCount": r.get("thumbsUpCount"),
                            "appVersion": r.get("appVersion"),
                        }
                    )
        except Exception as e:
            print(f"Error fetching Google Play reviews for sort {sort_mode}: {e}")

    return all_reviews


def fetch_broad_app_store_reviews() -> list[dict]:
    collected: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(1, 11):
        url = f"https://itunes.apple.com/us/rss/customerreviews/page={page}/id=284882215/sortby=mostrecent/json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            entries = data.get("feed", {}).get("entry", [])
            for entry in entries:
                rid = entry.get("id", {}).get("label")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    title = entry.get("title", {}).get("label")
                    content = entry.get("content", {}).get("label")
                    author = entry.get("author", {}).get("name", {}).get("label")
                    rating = entry.get("im:rating", {}).get("label")
                    collected.append(
                        {
                            "id": str(rid),
                            "title": title,
                            "body": content,
                            "score": int(rating) if rating and rating.isdigit() else None,
                            "userName": author,
                            "url": f"https://apps.apple.com/us/app/google-photos/id284882215#review_{rid}",
                        }
                    )
        except Exception as e:
            print(f"Error fetching App Store page {page}: {e}")

    return collected


def main() -> None:
    settings = Settings.from_env()
    engine = get_engine(settings.database_url)

    # 1. Clean existing non-Reddit records to ensure clean broad sampling pass
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM canonical_record WHERE source_type IN ('youtube', 'google_play', 'app_store', 'store_review')"
            )
        )
        conn.execute(
            text(
                "DELETE FROM raw_record WHERE source_type IN ('youtube', 'google_play', 'app_store', 'store_review')"
            )
        )
        conn.execute(
            text(
                "DELETE FROM ingest_run WHERE source_type IN ('youtube', 'google_play', 'app_store', 'store_review')"
            )
        )

    raw_dir = project_root() / "data" / "raw" / "broad_sources"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print("=== Executing Broad Non-Reddit Multi-Query Collection ===")

    # 1. YouTube Broad Collection
    yt_items: list[dict] = []
    yt_families: dict[str, int] = {}
    if settings.youtube_api_key:
        print("Collecting YouTube comments across 4 query families...")
        yt_items, yt_families = fetch_broad_youtube_comments(settings.youtube_api_key)
    yt_file = raw_dir / "youtube_broad.json"
    yt_file.write_text(json.dumps(yt_items, indent=2), encoding="utf-8")
    print(f"Collected {len(yt_items)} YouTube records across families: {yt_families}")

    # 2. Google Play Broad Collection
    print("Collecting Google Play reviews (NEWEST + MOST_RELEVANT)...")
    gp_items = fetch_broad_google_play_reviews()
    gp_file = raw_dir / "google_play_broad.json"
    gp_file.write_text(json.dumps(gp_items, indent=2), encoding="utf-8")
    print(f"Collected {len(gp_items)} Google Play records")

    # 3. App Store Broad Collection
    print("Collecting Apple App Store reviews across 10 pages...")
    as_items = fetch_broad_app_store_reviews()
    as_file = raw_dir / "app_store_broad.json"
    as_file.write_text(json.dumps(as_items, indent=2), encoding="utf-8")
    print(f"Collected {len(as_items)} App Store records")

    # 2. Ingest
    print("\n=== Ingesting Broad Raw Records ===")
    if yt_items:
        run_ingest(engine, YouTubeIngestor.from_path(yt_file), source_path=yt_file, force=True)
    if gp_items:
        run_ingest(engine, StoreReviewIngestor.from_path(gp_file), source_path=gp_file, force=True)
    if as_items:
        run_ingest(engine, StoreReviewIngestor.from_path(as_file), source_path=as_file, force=True)

    # 3. Preprocess / Normalize / Dedupe
    print("\n=== Running Preprocessing Pipeline ===")
    preprocess_report = run_preprocess(engine)
    print(f"Preprocess Report: {preprocess_report.to_dict()}")

    # 4. Relevance Classification
    print("\n=== Running Relevance Classification (relevance_v2) on Baseline Run ===")
    baseline_run_id = "d2c78beb-e832-4b0a-b930-0212aeb81481"
    rel_opts = RelevanceOptions(
        analysis_run_id=baseline_run_id,
        resume=True,
        bypass_gate=True,
    )
    rel_report = run_relevance(engine, settings, rel_opts)
    print(f"Relevance Report for baseline run {baseline_run_id}: {rel_report.to_dict()}")

    # 5. UX Extraction on Newly Relevant Records
    print("\n=== Running UX Extraction on Baseline Run ===")
    ext_opts = ExtractOptions(
        analysis_run_id=baseline_run_id,
        resume=True,
    )
    ext_report = run_extract(engine, settings, ext_opts)
    print(f"Extract Report for baseline run {baseline_run_id}: {ext_report.to_dict()}")

    # 6. Detailed Summary Report by Source
    print("\n========================================================================")
    print("=== FINAL BROAD NON-REDDIT MULTI-SOURCE RELEVANCE & PREVALENCE REPORT ===")
    print("========================================================================")

    with engine.connect() as conn:
        sources = ["reddit", "youtube", "google_play", "app_store"]
        for st in sources:
            raw_c = conn.execute(
                text("SELECT COUNT(*) FROM raw_record WHERE source_type = :st"),
                {"st": st},
            ).scalar()
            canon_c = conn.execute(
                text("SELECT COUNT(*) FROM canonical_record WHERE source_type = :st"),
                {"st": st},
            ).scalar()
            excl_noise = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM excluded_noise e
                    JOIN raw_record r ON r.id = e.raw_record_id
                    WHERE r.source_type = :st
                    """
                ),
                {"st": st},
            ).scalar()
            dups = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM duplicate_group d
                    JOIN raw_record r ON r.id = d.duplicate_raw_record_id
                    WHERE r.source_type = :st
                    """
                ),
                {"st": st},
            ).scalar()
            rel_c = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM relevance_result rr
                    JOIN canonical_record cr ON cr.id = rr.record_id
                    WHERE cr.source_type = :st
                      AND rr.analysis_run_id = :aid
                      AND rr.is_relevant = 1
                      AND (cr.permalink IS NULL OR cr.permalink NOT LIKE '%sample01%')
                    """
                ),
                {"st": st, "aid": baseline_run_id},
            ).scalar()
            ext_c = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM ux_extraction ux
                    JOIN canonical_record cr ON cr.id = ux.record_id
                    WHERE cr.source_type = :st
                      AND ux.analysis_run_id = :aid
                      AND ux.extraction_status = 'completed'
                      AND (cr.permalink IS NULL OR cr.permalink NOT LIKE '%sample01%')
                    """
                ),
                {"st": st, "aid": baseline_run_id},
            ).scalar()

            rel_rate = round((rel_c / max(1, canon_c)) * 100, 2)

            print(f"\n--- Source: {st.upper()} ---")
            print(f"  Raw Records Collected    : {raw_c}")
            print(f"  Canonical Records Created: {canon_c}")
            print(f"  Noise / Duplicates Excluded: Noise={excl_noise}, Dups={dups}")
            print(f"  Relevant Records (Run)   : {rel_c}")
            print(f"  Relevance Rate           : {rel_rate}%")
            print(f"  Extractions Completed    : {ext_c}")
            if st == "youtube":
                print(f"  Query Families Used      : {list(YOUTUBE_QUERY_FAMILIES.keys())}")
            elif st == "google_play":
                print(f"  Retrieval/Sort Modes Used : NEWEST + MOST_RELEVANT (500 per mode)")
            elif st == "app_store":
                print(f"  Retrieval/Page Modes Used: Customer Reviews (Pages 1 to 10)")


if __name__ == "__main__":
    main()
