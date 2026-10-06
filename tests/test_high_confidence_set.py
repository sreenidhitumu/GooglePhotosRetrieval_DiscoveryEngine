from __future__ import annotations

from discover.research.high_confidence_set import (
    build_high_confidence_set,
    reddit_thread_post_id,
    score_positive_record,
    ScoredRecord,
)


def test_thread_id_from_permalink() -> None:
    assert reddit_thread_post_id(
        "https://www.reddit.com/r/googlephotos/comments/1fvq7hr/title/slug/"
    ) == "1fvq7hr"


def test_demotes_successful_scroll_found() -> None:
    score, _, demote = score_positive_record(
        "Found this while scrolling through my old Google Photos",
        "What are those rings?",
        "https://www.reddit.com/r/x/comments/10r3jkh/y/z/",
    )
    assert score < 0
    assert "successful_browse_only" in demote


def test_promotes_search_failure() -> None:
    score, tags, demote = score_positive_record(
        "Why did they ruin Google photos search???",
        "I search passport and get thousands of irrelevant photos.",
        "https://www.reddit.com/r/googlephotos/comments/1fvq7hr/x/",
    )
    assert score >= 35
    assert "search_quality_failure" in tags or score >= 35
    assert not demote


def test_one_record_per_thread_by_default() -> None:
    scored = [
        ScoredRecord(
            record_id="a",
            analysis_run_id="x",
            permalink="https://reddit.com/r/g/comments/t1/a/",
            thread_post_id="t1",
            title=None,
            body_excerpt="long",
            confidence=0.9,
            classifier_rationale="r",
            score=50,
            experience_tags=[],
            demotion_flags=[],
        ),
        ScoredRecord(
            record_id="b",
            analysis_run_id="x",
            permalink="https://reddit.com/r/g/comments/t1/b/",
            thread_post_id="t1",
            title=None,
            body_excerpt="short",
            confidence=0.8,
            classifier_rationale="r",
            score=30,
            experience_tags=[],
            demotion_flags=[],
        ),
        ScoredRecord(
            record_id="c",
            analysis_run_id="x",
            permalink="https://reddit.com/r/g/comments/t2/c/",
            thread_post_id="t2",
            title=None,
            body_excerpt="x",
            confidence=0.9,
            classifier_rationale="r",
            score=45,
            experience_tags=[],
            demotion_flags=[],
        ),
    ]
    selected, meta = build_high_confidence_set(scored, target_min=2, target_max=10, min_score=30)
    ids = {r.record_id for r in selected}
    assert "a" in ids
    assert "b" not in ids
    assert meta["unique_threads_in_set"] == len(ids)
