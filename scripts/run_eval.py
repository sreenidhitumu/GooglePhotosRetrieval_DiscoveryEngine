#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from discover.config import Settings
from discover.llm.gateway import get_llm_gateway


def run_evaluation(gold_set_path: Path, provider_name: str = "mock") -> dict:
    if not gold_set_path.exists():
        raise FileNotFoundError(f"Gold set file not found: {gold_set_path}")

    gold_items = json.loads(gold_set_path.read_text(encoding="utf-8"))
    settings = Settings.from_env()
    gateway = get_llm_gateway(settings, provider_name=provider_name)

    records = [
        {
            "record_id": item["id"],
            "source_type": item["source_type"],
            "title": item["title"],
            "body": item["body"],
            "permalink": item.get("permalink", "https://example.com"),
        }
        for item in gold_items
    ]

    results = gateway.classify_relevance_batch(records)
    pred_by_id = {r["record_id"]: r["is_relevant"] for r in results}

    tp = 0
    fp = 0
    tn = 0
    fn = 0

    for item in gold_items:
        gold_rel = item["is_relevant"]
        pred_rel = pred_by_id.get(item["id"], False)
        if gold_rel and pred_rel:
            tp += 1
        elif not gold_rel and pred_rel:
            fp += 1
        elif not gold_rel and not pred_rel:
            tn += 1
        else:
            fn += 1

    total = len(gold_items)
    accuracy = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    eval_report = {
        "gold_set_size": total,
        "provider_model": gateway.model_id,
        "prompt_version": gateway.prompt_version,
        "metrics": {
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
        },
    }

    return eval_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run relevance evaluation against gold set.")
    parser.add_argument(
        "--gold-set",
        type=Path,
        default=Path("data/processed/relevance_gold_set.json"),
        help="Path to gold set JSON file",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="mock",
        help="LLM provider (mock, gemini, groq, auto)",
    )
    args = parser.parse_args()

    report = run_evaluation(args.gold_set, provider_name=args.provider)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
