# ADR 002: Clustering embeddings (Phase 4)

## Status

Accepted — Phase 4 pattern discovery.

## Context

~56–200 extracted records; need reproducible clustering without heavy GPU deps or paid embedding APIs for MVP.

## Decision

- **Features:** Concatenate UX extraction fields + truncated canonical `title`/`body` (same text builder as pipeline).
- **Vectorization:** `sklearn.feature_extraction.text.TfidfVectorizer` (unigrams + bigrams, max 8k features).
- **Clustering:** `KMeans` with **k** chosen by best silhouette score over `k ∈ [2, min(10, n//3)]`, override via `CLUSTER_NUM_CLUSTERS` or CLI.
- **Optional LLM labels:** Neutral label + summary from **up to 3 medoid exemplars** per cluster only (`cluster_label_v1`).

## Consequences

- Dependencies: `numpy`, `scikit-learn`.
- HDBSCAN deferred; small-N Reddit v1 works with k-means + silhouette.
- Re-run creates a new `analysis_run` (`label=clustering`) without deleting prior clusters.
