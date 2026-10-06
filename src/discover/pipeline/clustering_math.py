from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)


def vectorize_documents(documents: list[str]) -> Any:
    vectorizer = TfidfVectorizer(
        max_features=8000,
        ngram_range=(1, 2),
        min_df=1,
        stop_words="english",
    )
    matrix = vectorizer.fit_transform(documents)
    return vectorizer, matrix


def choose_num_clusters(matrix, n_samples: int, override: int | None = None) -> int:
    if override is not None:
        return max(2, min(override, max(2, n_samples - 1)))
    if n_samples < 4:
        return max(1, n_samples)
    k_max = min(10, max(2, n_samples // 3))
    k_min = 2
    best_k = k_min
    best_score = -1.0
    for k in range(k_min, k_max + 1):
        if k >= n_samples:
            break
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        try:
            score = silhouette_score(matrix, labels)
        except ValueError:
            continue
        if score > best_score:
            best_score = score
            best_k = k
    logger.info("Selected k=%s (best silhouette=%.3f)", best_k, best_score)
    return best_k


def run_kmeans(matrix, n_clusters: int) -> tuple[np.ndarray, np.ndarray]:
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(matrix)
    return labels, km.cluster_centers_
