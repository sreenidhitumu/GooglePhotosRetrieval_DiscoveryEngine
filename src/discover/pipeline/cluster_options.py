from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ClusterOptions:
    """Pattern discovery options (cluster + opportunity share relevance/extraction run id)."""

    analysis_run_id: str | None = None
    cluster_analysis_run_id: str | None = None
    research_set_path: Path | None = None
    num_clusters: int | None = None
    label_clusters: bool = True
    llm_provider: str | None = None
    force: bool = False
