from __future__ import annotations

from discover.llm.batch_pack import pack_relevance_batches


def _rec(rid: str, body: str) -> dict:
    return {
        "record_id": rid,
        "source_type": "reddit",
        "title": "t",
        "body": body,
        "permalink": "https://example.com/r/x",
    }


def test_pack_respects_max_records() -> None:
    records = [_rec(str(i), "short") for i in range(25)]
    batches = pack_relevance_batches(
        records, max_records_per_batch=12, max_input_tokens_per_batch=100_000
    )
    assert sum(len(b) for b in batches) == 25
    assert all(len(b) <= 12 for b in batches)
    assert len(batches) == 3


def test_pack_splits_on_token_budget() -> None:
    big = "word " * 5000
    records = [_rec("a", big), _rec("b", big)]
    batches = pack_relevance_batches(
        records, max_records_per_batch=12, max_input_tokens_per_batch=2_500
    )
    assert len(batches) == 2
    assert len(batches[0]) == 1 and len(batches[1]) == 1
