from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from discover.calibration_exclusions import permalink_excluded_from_calibration_metrics

_RE_POST_ID = re.compile(r"/comments/([A-Za-z0-9]+)/")


@dataclass(frozen=True)
class ScoredRecord:
    record_id: str
    analysis_run_id: str
    permalink: str | None
    thread_post_id: str
    title: str | None
    body_excerpt: str
    confidence: float
    classifier_rationale: str
    score: int
    experience_tags: list[str]
    demotion_flags: list[str]
    selected_for_set: bool = False


def reddit_thread_post_id(permalink: str | None) -> str:
    if not permalink:
        return "unknown"
    m = _RE_POST_ID.search(permalink)
    return m.group(1) if m else permalink


def _combined(title: str | None, body: str | None) -> str:
    return f"{title or ''}\n{body or ''}".strip()


def score_positive_record(
    title: str | None, body: str | None, permalink: str | None
) -> tuple[int, list[str], list[str]]:
    """
    Heuristic score for audit-derived high-confidence set (not LLM).
    Higher is better. demotion_flags trigger hard excludes when severe.
    """
    text = _combined(title, body)
    tl = text.casefold()
    tags: list[str] = []
    demote: list[str] = []

    gp_named = bool(re.search(r"\bgoogle\s*photos?\b|photos\.google", tl))
    in_gp_sub = "/r/googlephotos/" in (permalink or "").casefold()

    if not gp_named and not in_gp_sub:
        demote.append("no_explicit_gp_context")
        return -100, tags, demote

    if re.search(r"found this while scrolling through my old google photos", tl):
        demote.append("successful_browse_only")
        return -80, tags, demote

    if re.search(r"google lens|help me find|where is this (photo|image) from", tl) and not gp_named:
        demote.append("web_or_lens_not_gp_library")
        return -80, tags, demote

    if re.search(
        r"\b(migrate|migration|takeout|gsuite|moved my google|import from google)\b", tl
    ) and not re.search(r"can'?t find|search.{0,30}(fail|bad|worse)|scroll.{0,25}(find|one by one)", tl):
        demote.append("migration_backup_focus")
        return -40, tags, demote

    if re.search(r"\b(all (my )?photos (are )?(gone|deleted|missing|vanished)|lost \d+ years)\b", tl):
        if not re.search(r"search|find|remember|scroll.{0,20}find", tl):
            demote.append("data_loss_without_retrieval_story")
            return -50, tags, demote

    if re.search(r"how do you (all )?go about organizing|organization help", tl, re.I):
        if not re.search(r"can'?t find|search.{0,20}(fail|doesn)", tl):
            demote.append("curation_organization")
            return -30, tags, demote

    if re.search(r"would probably make it easier|something like google photos that", tl):
        demote.append("hypothetical_gp")
        return -25, tags, demote

    score = 10
    if gp_named:
        score += 15
        tags.append("product_context")
    if in_gp_sub:
        score += 5

    if re.search(r"remember this day", tl):
        score += 35
        tags.append("memories_surface")
        if re.search(r"no idea|feel nothing|don'?t know what|absolutely no idea", tl):
            score += 25
            tags.append("recall_gap")

    if re.search(
        r"can'?t find|cannot find|won'?t find|couldn'?t find|never find it again|"
        r"hard to find|struggle to find|failed to find|doesn'?t surface|won'?t surface",
        tl,
    ):
        score += 30
        tags.append("retrieval_failure")

    if re.search(
        r"search.{0,35}(ruin|worse|broken|useless|sucks|bad|doesn'?t work|no relevance)|"
        r"ai search.{0,25}can'?t|shows (me )?thousands|thousands of (irrelevant )?photos",
        tl,
    ) or "ruin google photos search" in tl:
        score += 28
        tags.append("search_quality_failure")

    if re.search(
        r"scroll.{0,40}(one by one|for an hour|through them one|chore|thousand|daunting)|"
        r"browse.{0,20}(library|timeline)",
        tl,
    ):
        score += 22
        tags.append("browse_scroll_effort")

    if re.search(r"forgotten about|fuzzy|vague|partial memory|remember the photo but", tl):
        score += 18
        tags.append("memory_gap")

    if re.search(r"passport|global entry|screenshot|keyword", tl) and re.search(
        r"search|find", tl
    ):
        score += 12
        tags.append("search_formulation")

    if re.search(r"collage or memory.*never find|disappears and i can never find", tl):
        score += 30
        tags.append("memories_retrieval_failure")

    # Generic one-liner demotion
    if len(text) < 160 and re.search(r"worse search", tl) and "can" not in tl:
        demote.append("generic_search_complaint_one_liner")
        score -= 15

    if re.search(r"scrolling through my (thousands of )?photos instantly", tl):
        demote.append("phone_gallery_performance")
        score -= 60

    return score, tags, demote


def fetch_scored_positives(engine: Engine, analysis_run_id: str) -> list[ScoredRecord]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT cr.id, cr.title, cr.body, cr.permalink,
                       rr.confidence, rr.rationale
                FROM relevance_result rr
                JOIN canonical_record cr ON cr.id = rr.record_id
                WHERE rr.analysis_run_id = :aid
                  AND rr.is_relevant = 1
                  AND rr.analysis_status = 'completed'
                """
            ),
            {"aid": analysis_run_id},
        ).fetchall()

    scored: list[ScoredRecord] = []
    for row in rows:
        rid, title, body, permalink, confidence, rationale = row
        if permalink_excluded_from_calibration_metrics(permalink):
            continue
        score, tags, demote = score_positive_record(title, body, permalink)
        if score < 0:
            continue
        excerpt = _combined(title, body)[:500]
        scored.append(
            ScoredRecord(
                record_id=rid,
                analysis_run_id=analysis_run_id,
                permalink=permalink,
                thread_post_id=reddit_thread_post_id(permalink),
                title=title,
                body_excerpt=excerpt,
                confidence=float(confidence or 0),
                classifier_rationale=(rationale or "")[:800],
                score=score,
                experience_tags=tags,
                demotion_flags=demote,
                selected_for_set=False,
            )
        )
    return scored


def build_high_confidence_set(
    scored: list[ScoredRecord],
    *,
    target_min: int = 40,
    target_max: int = 60,
    min_score: int = 30,
) -> tuple[list[ScoredRecord], dict[str, Any]]:
    """
    One primary record per Reddit thread (highest score); expand with second record
    only if score gap is small and body length suggests OP vs comment both substantive.
    """
    by_thread: dict[str, list[ScoredRecord]] = {}
    for rec in scored:
        by_thread.setdefault(rec.thread_post_id, []).append(rec)
    for items in by_thread.values():
        items.sort(key=lambda r: (-r.score, -r.confidence, -len(r.body_excerpt)))

    thread_order = sorted(
        by_thread.keys(),
        key=lambda tid: (-by_thread[tid][0].score, tid),
    )

    selected: list[ScoredRecord] = []
    selected_ids: set[str] = set()

    def add(rec: ScoredRecord) -> None:
        if rec.record_id in selected_ids:
            return
        selected_ids.add(rec.record_id)
        selected.append(
            ScoredRecord(**{**asdict(rec), "selected_for_set": True})
        )

    for tid in thread_order:
        if len(selected) >= target_max:
            break
        best = by_thread[tid][0]
        if best.score < min_score:
            continue
        add(best)

    # Fill toward target_min with next-best threads if needed
    if len(selected) < target_min:
        for tid in thread_order:
            if len(selected) >= target_max:
                break
            items = by_thread[tid]
            if not items or items[0].record_id in selected_ids:
                continue
            if items[0].score < min_score - 5:
                continue
            add(items[0])

    # Allow a few threads to contribute a second distinct high-score comment (OP + detail)
    if len(selected) < target_max:
        for tid in thread_order:
            if len(selected) >= target_max:
                break
            items = by_thread[tid]
            if len(items) < 2:
                continue
            if items[0].record_id not in selected_ids:
                continue
            second = items[1]
            if second.score >= min_score and second.score >= items[0].score - 8:
                if len(second.body_excerpt) > 120:
                    add(second)

    meta = {
        "target_range": [target_min, target_max],
        "min_score_threshold": min_score,
        "eligible_after_demotion": len(scored),
        "unique_threads_in_set": len({r.thread_post_id for r in selected}),
        "records_in_set": len(selected),
    }
    return selected, meta


def export_research_set_manifest(
    engine: Engine,
    analysis_run_id: str,
    output_path: Path,
    *,
    target_min: int = 40,
    target_max: int = 60,
    min_score: int = 30,
) -> dict[str, Any]:
    with engine.connect() as conn:
        raw_positive_count = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM relevance_result rr
                JOIN canonical_record cr ON cr.id = rr.record_id
                WHERE rr.analysis_run_id = :aid AND rr.is_relevant = 1
                  AND rr.analysis_status = 'completed'
                  AND cr.permalink NOT LIKE '%/comments/abc/sample01%'
                """
            ),
            {"aid": analysis_run_id},
        ).scalar()

    scored = fetch_scored_positives(engine, analysis_run_id)
    selected, build_meta = build_high_confidence_set(
        scored, target_min=target_min, target_max=target_max, min_score=min_score
    )

    threads: dict[str, list[dict[str, Any]]] = {}
    for rec in selected:
        threads.setdefault(rec.thread_post_id, []).append(asdict(rec))

    manifest: dict[str, Any] = {
        "kind": "high_confidence_research_set",
        "version": "1",
        "analysis_run_id": analysis_run_id,
        "prompt_version": "relevance_v2",
        "source": "classifier_positives_plus_heuristic_curation",
        "note": "Does not modify relevance_result; downstream use only.",
        "build": {
            **build_meta,
            "classifier_positive_records": int(raw_positive_count or 0),
            "demoted_by_heuristics": int(raw_positive_count or 0) - len(scored),
        },
        "summary": {
            "records": len(selected),
            "unique_threads": build_meta["unique_threads_in_set"],
            "score_min": min(r.score for r in selected) if selected else None,
            "score_max": max(r.score for r in selected) if selected else None,
        },
        "records": [asdict(r) for r in selected],
        "threads": {
            tid: {
                "record_ids": [r["record_id"] for r in recs],
                "representative_permalink": recs[0]["permalink"],
            }
            for tid, recs in sorted(threads.items())
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest
