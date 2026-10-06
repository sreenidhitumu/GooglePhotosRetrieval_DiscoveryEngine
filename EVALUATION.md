# Evaluation & Hardening Guide (Phase 7)

This document establishes the evaluation guidelines, gold-set benchmarks, LLM resilience patterns, and observability metrics for the Google Photos Retrieval research system.

---

## 1. Gold Set Evaluation Framework

The gold set (`data/processed/relevance_gold_set.json`) provides a multi-source benchmark for evaluating relevance classification accuracy, precision, recall, and F1 score across Reddit, YouTube, Google Play, and App Store records.

### Labeling Criteria

A record is labeled **Relevant (`is_relevant = true`)** if it provides explicit user evidence of:
1. **Google Photos retrieval intent**: Searching, locating, or recovering photos, videos, screenshots, or visual documents.
2. **Visual memory gap or recall struggle**: Partial visual cues, forgotten dates/filenames, imprecise query formulation, or search algorithm failures.
3. **Metadata & query power friction**: Inability to filter by EXIF attributes, camera model, date ranges, or combined boolean terms.
4. **Library integrity or ephemeral memory loss**: Disappearing album items, broken cloud sync, or un-findable GP collages.

A record is labeled **Irrelevant (`is_relevant = false`)** if it relates to:
- Storage tier pricing or Google One billing complaints with no retrieval context.
- Bulk deletion or storage cleanup requests with no specific search story.
- Generic app store praise ("Great app!") or off-topic bug reports (e.g. app crashes on launch).

---

## 2. Benchmark Quality Targets

| Metric | Target Standard | Description |
| ------ | --------------- | ----------- |
| **Precision** | **≥ 0.80** | Minimized false positives so noise does not contaminate research sets |
| **Recall** | **≥ 0.60** | Captures a representative volume of true visual retrieval struggles |
| **F1 Score** | **≥ 0.70** | Harmonic mean ensuring balanced classification performance |
| **Parse Errors** | **< 1%** | Handled with batch splitting and structured output validation |

---

## 3. Running Evaluation & Regression Checks

To execute the automated evaluation pipeline against the gold set:

```bash
# Evaluate mock provider
./.venv/bin/python scripts/run_eval.py --provider mock

# Evaluate Gemini provider
./.venv/bin/python scripts/run_eval.py --provider gemini

# Evaluate Auto / Fallback provider
./.venv/bin/python scripts/run_eval.py --provider auto
```

---

## 4. Multi-Source Ingestion & Normalization

The pipeline supports source-agnostic downstream processing by normalizing all raw payloads into `CanonicalDraft` instances via `src/discover/pipeline/normalize.py`:

- **Reddit**: `RedditApifyIngestor` (`source_type="reddit"`)
- **YouTube**: `YouTubeIngestor` (`source_type="youtube"`)
- **Store Reviews**: `StoreReviewIngestor` (`source_type="google_play"` | `"app_store"` | `"store_review"`)

---

## 5. Resilient LLM Fallback Architecture

To ensure operational availability during API rate limiting (429) or service outages (503), the system implements `FallbackProvider` in `src/discover/llm/providers.py`:

- **Primary Provider**: Gemini 2.0 Flash (`gemini-2.0-flash`)
- **Secondary Provider**: Groq Llama 3.3 70B (`llama-3.3-70b-versatile`) or Mock fallback
- **Failover Logic**: When the primary provider encounters unrecoverable HTTP/API errors, `FallbackProvider` seamlessly delegates requests to the secondary provider without breaking batch execution.

---

## 6. Observability & Telemetry

Pipeline execution metrics and cost estimates are tracked per run via `TokenTelemetry` in `src/discover/metrics.py`:

- **LLM Calls**: Total API calls dispatched across relevance and extraction stages.
- **Token Estimation**: Input and output token counts tracked per provider.
- **Cost Tracking**: Estimated USD spend per run calculated based on model token rates.
- **Reporting**: Emitted in structured log format and exposed via the `/stats/pipeline` and `/stats/sources` API endpoints.
