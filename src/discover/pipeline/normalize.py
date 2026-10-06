from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from discover.text_utils import (
    combine_title_body,
    combined_text,
    content_hash,
    decode_reddit_text,
)


@dataclass(frozen=True)
class CanonicalDraft:
    source_type: str
    title: str | None
    body: str
    author_handle: str | None
    posted_at: str | None
    permalink: str | None
    content_hash: str
    metadata: dict[str, Any]


def normalize_reddit_payload(payload: dict[str, Any]) -> CanonicalDraft:
    title, body = combine_title_body(payload.get("title"), payload.get("body"))
    combined = combined_text(title, body)
    permalink = payload.get("url") or payload.get("link")
    author = payload.get("username")
    posted_at = payload.get("createdAt")

    metadata = {
        "data_type": payload.get("dataType"),
        "community_name": payload.get("communityName"),
        "parsed_community_name": payload.get("parsedCommunityName"),
        "scraped_at": payload.get("scrapedAt"),
        "up_votes": payload.get("upVotes"),
        "up_vote_ratio": payload.get("upVoteRatio"),
        "number_of_comments": payload.get("numberOfComments"),
        "content_type": payload.get("contentType"),
        "image_urls": payload.get("imageUrls"),
        "reddit_id": payload.get("id"),
        "parsed_id": payload.get("parsedId"),
    }

    return CanonicalDraft(
        source_type="reddit",
        title=title or None,
        body=body if body else (title if title else ""),
        author_handle=decode_reddit_text(author) or None,
        posted_at=posted_at,
        permalink=permalink,
        content_hash=content_hash("reddit", combined),
        metadata=metadata,
    )


def normalize_youtube_payload(payload: dict[str, Any]) -> CanonicalDraft:
    raw_title = payload.get("title") or payload.get("video_title")
    raw_body = payload.get("body") or payload.get("comment_text") or payload.get("textDisplay") or payload.get("description")
    title, body = combine_title_body(raw_title, raw_body)
    combined = combined_text(title, body)
    
    video_id = payload.get("video_id") or payload.get("videoId")
    permalink = payload.get("url") or payload.get("link")
    if not permalink and video_id:
        permalink = f"https://www.youtube.com/watch?v={video_id}"
    
    author = payload.get("author") or payload.get("authorDisplayName") or payload.get("channelTitle")
    posted_at = payload.get("createdAt") or payload.get("publishedAt")

    metadata = {
        "video_id": video_id,
        "comment_id": payload.get("comment_id") or payload.get("id"),
        "like_count": payload.get("likeCount") or payload.get("likes"),
        "view_count": payload.get("viewCount"),
    }

    return CanonicalDraft(
        source_type="youtube",
        title=title or None,
        body=body if body else (title if title else ""),
        author_handle=author or None,
        posted_at=posted_at,
        permalink=permalink,
        content_hash=content_hash("youtube", combined),
        metadata=metadata,
    )


def normalize_store_review_payload(source_type: str, payload: dict[str, Any]) -> CanonicalDraft:
    raw_title = payload.get("title") or payload.get("review_title") or payload.get("summary")
    raw_body = payload.get("body") or payload.get("text") or payload.get("content") or payload.get("comment") or payload.get("review")
    title, body = combine_title_body(raw_title, raw_body)
    combined = combined_text(title, body)
    
    author = payload.get("author") or payload.get("userName") or payload.get("reviewer")
    posted_at = payload.get("createdAt") or payload.get("at") or payload.get("date")
    permalink = payload.get("url") or payload.get("link")

    metadata = {
        "score": payload.get("score") or payload.get("rating") or payload.get("stars"),
        "app_version": payload.get("appVersion") or payload.get("version"),
        "thumbs_up": payload.get("thumbsUpCount") or payload.get("helpful_count"),
        "device": payload.get("device"),
    }

    st = source_type if source_type in ("google_play", "app_store") else "store_review"
    return CanonicalDraft(
        source_type=st,
        title=title or None,
        body=body if body else (title if title else ""),
        author_handle=author or None,
        posted_at=posted_at,
        permalink=permalink,
        content_hash=content_hash(st, combined),
        metadata=metadata,
    )


def normalize_raw_record(source_type: str, payload: dict[str, Any]) -> CanonicalDraft:
    st = source_type.lower().strip()
    if st == "reddit":
        return normalize_reddit_payload(payload)
    if st == "youtube":
        return normalize_youtube_payload(payload)
    if st in ("google_play", "app_store", "store_review"):
        return normalize_store_review_payload(st, payload)
    raise ValueError(f"Normalization not implemented for source_type={source_type}")
