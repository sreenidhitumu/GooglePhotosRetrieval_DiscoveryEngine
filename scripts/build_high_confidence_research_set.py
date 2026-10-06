#!/usr/bin/env python3
"""Build high-confidence research set from relevance_v2 positives (no LLM)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without install
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from discover.config import Settings
from discover.db import get_engine, run_migrations
from discover.research.high_confidence_set import export_research_set_manifest

DEFAULT_RUN = "d2c78beb-e832-4b0a-b930-0212aeb81481"
DEFAULT_OUT = _ROOT / "data/processed/high_confidence_research_set.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-run-id", default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--min", type=int, default=40, dest="target_min")
    parser.add_argument("--max", type=int, default=60, dest="target_max")
    parser.add_argument("--min-score", type=int, default=30)
    args = parser.parse_args()

    settings = Settings.from_env()
    engine = get_engine(settings.database_url)
    run_migrations(engine)

    manifest = export_research_set_manifest(
        engine,
        args.analysis_run_id,
        args.output,
        target_min=args.target_min,
        target_max=args.target_max,
        min_score=args.min_score,
    )
    s = manifest["summary"]
    print(
        f"Wrote {args.output}\n"
        f"  records={s['records']} unique_threads={s['unique_threads']} "
        f"score_range={s['score_min']}..{s['score_max']}"
    )


if __name__ == "__main__":
    main()
