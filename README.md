# Google Photos Retrieval — Discovery Engine

AI-powered research pipeline to discover evidence about **vague visual-memory retrieval** in Google Photos from public conversations ([`context.md`](context.md), [`architecture.md`](architecture.md)).

**Primary actor (MVP):** Researcher / Operator — ingest data, configure keys, run the pipeline, explore findings.

## Requirements

- Python **3.9+** (3.11+ recommended)
- Optional: virtualenv

## Quickstart

```bash
cd GooglePhotosRetrieval
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env if needed (defaults use SQLite under data/processed/)

discover migrate
discover ingest --source reddit --file dataset_reddit-scraper-lite_2026-09-29_17-56-33-680.json
discover run --stage preprocess
discover run --stage relevance --resume   # requires GEMINI_API_KEY or LLM_PROVIDER=mock
discover relevance-report --analysis-run-id <uuid>
discover run --stage extract --analysis-run-id <uuid> --llm-provider gemini
discover extract-report --analysis-run-id <uuid>
discover extract-qa-sample --analysis-run-id <uuid>
```

Expected: migrations apply; ingest loads ~1000 raw Reddit records; preprocess produces ≥900 canonical records (remainder: noise, duplicates). Relevance uses a source-agnostic gate + LLM ([`docs/relevance-criteria.md`](docs/relevance-criteria.md)).

## CLI

| Command | Description |
|---------|-------------|
| `discover migrate` | Apply SQL migrations from `migrations/` |
| `discover ingest --source reddit --file path.json [--force]` | Load Apify Reddit JSON into `raw_record` |
| `discover run --stage <stage> [--dry-run]` | Run pipeline stage |
| `discover publish` | Publish snapshot stub (Phase 4+) |

Stages: `preprocess`, `relevance`, `extract`, `cluster`, `opportunity`, `publish`.

Relevance options: `--resume`, `--limit N`, `--analysis-run-id`, `--force`, `--llm-provider gemini|groq|mock`, `--bypass-gate` (calibration: minimal prefilter only, sends rest to LLM).

**Batching:** Each Gemini **API request** classifies up to `RELEVANCE_BATCH_SIZE` records (default 12), subject to `RELEVANCE_MAX_BATCH_INPUT_TOKENS`. A full calibration run is ~900 **records** → on the order of **~75–240 API calls** depending on batch packing, not one call per record. `GEMINI_RPM_LIMIT` / `GEMINI_TPM_LIMIT` throttle requests; results checkpoint per batch (`--resume` skips rows already in `relevance_result`).

## Project layout

```
migrations/           # Versioned SQL schema
src/discover/         # CLI, config, DB, pipeline, ingestors (Phase 1+), api (Phase 5+)
ui/                   # Research UI (Phase 6)
data/raw/             # Raw ingest artifacts (gitignored)
data/processed/       # SQLite DB and processed outputs (gitignored)
docs/adr/             # Architecture decision records
```

Stack decisions: [`docs/adr/001-stack.md`](docs/adr/001-stack.md).

## Environment variables

See [`.env.example`](.env.example). Never commit `.env` or API keys.

## Tests

```bash
pytest
```

## Implementation phases

See [`implementation-plan.md`](implementation-plan.md). **Phase 0** foundation; **Phase 1** adds Reddit ingest + preprocess (dedupe, noise filter, audit tables).
