# System Architecture: AI-Powered Discovery Engine for Google Photos Retrieval

This document describes the technical architecture for the research discovery engine defined in [`context.md`](./context.md). The system ingests public conversations, identifies evidence about **vague visual-memory retrieval** in Google Photos, extracts structured experiences, discovers patterns, and presents traceable findings to researchers.

---

## 1. Architecture goals

| Goal | Architectural response |
|------|-------------------------|
| Evidence-first discovery | Immutable raw store; all insights reference record IDs |
| Multi-source ingestion | Pluggable source adapters behind a common contract |
| Cost-efficient LLM use | Deterministic pre-filter → batched classification → extraction only on positives |
| Resumable pipelines | Job queue with checkpoints, idempotent writes, versioned model outputs |
| Researcher traceability | UI and exports preserve lineage: cluster → structured fields → raw text → source URL |
| No premature taxonomy | Clustering is a separate stage; archetypes emerge from data + optional LLM synthesis |
| Source-agnostic intelligence | Relevance + UX extraction read **only** `canonical_record`; ingest adapters are the sole per-source code path ([`implementation-plan.md`](./implementation-plan.md) Phases 2–3) |
| Calibrate on Reddit, generalize to all sources | Gold set and volume targets tune prompts; **no** `source_type` branches in labeling logic; Phase 7 re-runs same stages |

---

## 2. High-level system context

External actors and systems interact with the discovery engine as a **batch-analytics + research portal**, not as a consumer Google Photos integration.

**Primary actor:** **Researcher / Operator** — uploads datasets, configures API credentials, triggers analysis runs, monitors processing, inspects results, and explores findings in the research interface (single role for this MVP).

```mermaid
flowchart TB
    RO[Researcher / Operator]

    subgraph ExternalData["Public data & credentials"]
        RedditDS[Reddit Apify JSON]
        YT[YouTube Data API]
        Play[Google Play reviews]
        AppStore[Apple App Store reviews]
        Other[Forums / Community / Support]
        Keys[API keys in env / secrets]
    end

    subgraph DiscoveryEngine["Discovery Engine"]
        Ingest[Ingestion layer]
        Store[(Data stores)]
        Pipeline[Analysis pipeline]
        API[Research API]
        UI[Research UI]
    end

    subgraph LLMProviders["LLM providers"]
        Gemini[Gemini primary]
        Groq[Groq optional]
    end

    RO -->|upload datasets, configure runs| Ingest
    RO --> Keys
    RedditDS --> Ingest
    YT --> Ingest
    Play --> Ingest
    AppStore --> Ingest
    Other --> Ingest

    Ingest --> Store
    Pipeline --> Store
    Pipeline --> Gemini
    Pipeline --> Groq

    RO --> UI
    UI --> API
    API --> Store
```

---

## 3. Logical architecture (layers)

The system is organized into five layers. Each layer has a narrow responsibility; cross-cutting concerns (logging, config, secrets) apply to all.

```mermaid
flowchart TB
    subgraph Presentation["Presentation layer"]
        WebUI[Research web application]
        ExportSvc[Export service CSV JSON reports]
    end

    subgraph Application["Application layer"]
        ResearchAPI[REST or GraphQL API]
        QuerySvc[Query aggregation and filters]
        InsightSvc[Cluster and opportunity read models]
    end

    subgraph Domain["Domain & pipeline layer"]
        Orchestrator[Pipeline orchestrator]
        Ingestors[Source ingestors]
        Preprocess[Normalizer deduper]
        Relevance[Relevance stage]
        Extract[UX extraction stage]
        Cluster[Pattern discovery stage]
        Opp[Opportunity scoring stage]
    end

    subgraph Integration["Integration layer"]
        LLMGateway[LLM gateway batch retry rate limit]
        YTClient[YouTube client]
        StoreScrapers[Store review collectors or importers]
    end

    subgraph Persistence["Persistence layer"]
        RawDB[(Raw object store)]
        ProcDB[(Processed relational DB)]
        JobDB[(Job state and checkpoints)]
        ArtifactStore[(Run artifacts prompts schemas)]
    end

    WebUI --> ResearchAPI
    ExportSvc --> ResearchAPI
    ResearchAPI --> QuerySvc
    ResearchAPI --> InsightSvc

    Orchestrator --> Ingestors
    Orchestrator --> Preprocess
    Orchestrator --> Relevance
    Orchestrator --> Extract
    Orchestrator --> Cluster
    Orchestrator --> Opp

    Ingestors --> YTClient
    Ingestors --> StoreScrapers
    Relevance --> LLMGateway
    Extract --> LLMGateway
    Cluster --> LLMGateway

    Ingestors --> RawDB
    Preprocess --> ProcDB
    Relevance --> ProcDB
    Extract --> ProcDB
    Cluster --> ProcDB
    Opp --> ProcDB
    Orchestrator --> JobDB
    LLMGateway --> ArtifactStore
```

### Layer responsibilities

| Layer | Responsibility |
|--------|----------------|
| **Presentation** | Dashboards, record explorer, cluster views, opportunity comparison, export downloads |
| **Application** | Auth (if needed), pagination, filtering, read-optimized DTOs, export bundling |
| **Domain & pipeline** | Source-agnostic relevance + experiential extraction; clustering metrics and opportunity scoring (taxonomy only after clustering) |
| **Integration** | External APIs, LLM abstraction (Gemini/Groq), retries, token budgeting |
| **Persistence** | Raw vs processed separation, job checkpoints, immutable run metadata |

---

## 4. End-to-end data flow

The discovery pipeline mirrors the workflow in `context.md`. Stages are **sequential with optional re-runs** per stage when prompts or models change.

```mermaid
flowchart LR
    A[Raw conversations] --> B[Normalized records]
    B --> C{Deterministic filter}
    C -->|pass| D[LLM relevance batch]
    C -->|fail| X[Excluded with reason]
    D -->|relevant| E[LLM UX extraction batch]
    D -->|not relevant| Y[Stored classification only]
    E --> F[Structured experiences]
    F --> G[Embedding or feature matrix]
    G --> H[Clustering archetypes]
    H --> I[Opportunity scoring]
    I --> J[Research UI and exports]

    style A fill:#f9f9f9
    style J fill:#e8f4fc
```

### Stage I/O summary

| Stage | Input | Output | LLM? |
|--------|--------|--------|------|
| Ingest | Source files / APIs | `raw_records` blobs + metadata | No |
| Preprocess | `raw_records` | `canonical_records` | No |
| Deterministic filter | `canonical_records` | candidate subset + `filter_reason` | No |
| Relevance | candidates (`canonical_record`) | `relevance_label`, confidence, rationale, `retrieval_signal_types[]` (theme labels, not archetypes) | Yes (batched); **one prompt all sources** |
| UX extraction | relevant records (any `source_type`) | experiential JSON per schema; **no** cluster/taxonomy fields | Yes (batched); **one prompt all sources** |
| Pattern discovery | structured set | `cluster_id`, labels, exemplars | Optional LLM for naming |
| Opportunity analysis | clusters + records | scores, rankings, evidence links | Optional LLM for narrative |
| Serve | all tables | API responses, exports | No |

**Volume target:** on the **first (Reddit) corpus**, calibration should yield **≥150–200** records marked relevant before clustering, without sacrificing the balanced, **source-agnostic** relevance criterion in `context.md`. Additional sources (Phase 7) use the **same** relevance stage; volume targets are reported per corpus, not baked into code.

---

## 5. Detailed component architecture

### 5.1 Ingestion subsystem

Each source implements a shared **`SourceIngestor`** contract:

- `discover()` — list or fetch available items (API pagination, file glob).
- `fetch(record_ref)` — retrieve one raw payload.
- `map_to_raw()` — produce source-native JSON stored verbatim in raw store.

```mermaid
flowchart TB
    subgraph IngestionOrchestrator
        Registry[Ingestor registry]
        Run[Ingest run manifest]
    end

    subgraph Adapters
        RedditIng[Reddit Apify JSON adapter]
        YTIng[YouTube adapter]
        PlayIng[Play Store adapter]
        IOSIng[App Store adapter]
        GenericIng[Generic CSV JSON importer]
    end

    Registry --> RedditIng
    Registry --> YTIng
    Registry --> PlayIng
    Registry --> IOSIng
    Registry --> GenericIng

    RedditIng --> Raw[(raw_records)]
    YTIng --> Raw
    PlayIng --> Raw
    IOSIng --> Raw
    GenericIng --> Raw

    Run --> Registry
```

**Design notes**

- Reddit: single bulk import from stakeholder file; checksum stored on manifest.
- YouTube: search + video metadata + top comments; respect quota; cache responses in raw store.
- App stores: prefer official/public APIs or stakeholder imports; treat scrapers as replaceable adapters.
- Every ingest run gets `ingest_run_id`, timestamp, source version, and record counts.

### 5.2 Preprocessing subsystem

```mermaid
flowchart TB
    Raw[(raw_records)] --> Norm[Normalizer]
    Norm --> Canon[canonical_records]
    Canon --> Dedup[Deduplication]
    Dedup --> Noise[Noise rules]
    Noise --> Clean[canonical_records clean]

    Dedup --> DupLog[duplicate_groups]
    Noise --> NoiseLog[excluded_noise]
```

**Normalizer** maps to a **canonical record** (see §6). Rules are source-specific; structure is shared.

**Deduplication** uses a composite key where possible: `(source, content_hash)` and fuzzy match on near-duplicate text for cross-posts.

**Noise removal** is conservative: drop empty bodies, bot-like spam, non-user-generated boilerplate—log exclusions for audit.

### 5.3 Relevance subsystem (hybrid, source-agnostic)

**Inputs:** `canonical_record` fields only (`title`, `body`, optional `source_type` / `permalink` in prompt context). **No** relevance logic in ingestors beyond normalization (§5.1–5.2).

**Criteria:** Documented in [`docs/relevance-criteria.md`](./docs/relevance-criteria.md)—aligned to `context.md` north star and discovery themes, **not** Reddit patterns, subreddit lists, or predetermined problem archetypes.

Two phases minimize LLM cost:

1. **Deterministic gate** — lightweight pass on canonical text: Google Photos / visual-library **retrieval intent**; exclude obvious off-topic items (billing, unrelated apps, generic praise with no retrieval story). Must not rely on platform-specific mandatory keywords as the sole signal.
2. **LLM batch classifier** — single prompt version per `analysis_run_id` for all `source_type` values. JSON schema: `is_relevant`, `confidence`, `rationale`, `retrieval_signal_types[]` (open **theme** tags, not cluster/MVP enums).

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant F as Deterministic filter
    participant B as Batch builder
    participant G as LLM gateway
    participant DB as Processed DB

    O->>F: canonical_records batch
    F->>DB: mark skipped + reason
    F->>B: candidates only
    B->>G: batch prompt N records
    G->>DB: relevance results per record_id
    Note over G,DB: Checkpoint after each batch
```

**Calibration:** ~30 stratified manual labels (initially from Reddit) tune gate + prompt against the criteria doc. Reddit provides the first gold set and precision/recall checks; **portability requirement:** Phase 7 sources run this subsystem **unchanged** (incremental record IDs only).

**Anti-patterns:** `if source_type == "reddit"` labeling branches; Reddit few-shot examples that override generic criteria; enums named like future cluster labels.

### 5.4 UX extraction subsystem

Runs **only** on `is_relevant = true` from §5.3, **any source**. **One** extraction prompt per analysis run (no per-platform fork). One LLM call can cover multiple records in a batch if token limits allow; otherwise single-record batches for long threads.

**Non-goals (Phase 3):** `problem_archetype`, `cluster_id`, `opportunity_rank`, or fixed problem-type enums—clustering is §5.5.

Extracted fields (nullable when not stated in source):

- `retrieval_scenario`
- `remembers`
- `forgotten`
- `search_attempt`
- `failure_point`
- `workaround`
- `outcome`

Each field includes optional `evidence_spans` (character offsets or quoted snippets) to support UI highlighting and audit.

### 5.5 Pattern discovery subsystem

**Non-goals:** fixed taxonomy before seeing data.

**Approach (recommended hybrid):**

1. Build text features from structured + original content (e.g. embeddings of concatenated fields).
2. Cluster with algorithm suited to scale (HDBSCAN / k-means with elbow, or hierarchical for smaller N).
3. Optionally use LLM **per cluster** to generate a neutral archetype label and summary from exemplar records only.

Outputs:

- `clusters` — id, label, summary, size, source_distribution
- `cluster_members` — record_id, membership_score
- `exemplars` — top-k records closest to centroid/medoid

### 5.6 Opportunity analysis subsystem

Scores each cluster (and optionally sub-patterns) using **evidence-backed metrics**:

| Metric | Definition (example) |
|--------|----------------------|
| Frequency | Count of supporting records |
| Severity | Rubric from failure_point language + outcome (LLM or rule-assisted) |
| Cross-source consistency | Entropy of source types; bonus if ≥2 sources |
| Evidence strength | % fields with direct quotes; avg confidence |

```mermaid
flowchart LR
    C[Clusters] --> M[Metric calculator]
    R[Relevant records] --> M
    M --> Rank[Opportunity ranking]
    Rank --> Card[Opportunity cards with linked record IDs]
```

---

## 6. Data model (conceptual)

Raw and processed data are **physically separated**. LLM outputs are versioned by `analysis_run_id` and `model_id`.

```mermaid
erDiagram
    INGEST_RUN ||--o{ RAW_RECORD : contains
    RAW_RECORD ||--o| CANONICAL_RECORD : normalizes_to
    CANONICAL_RECORD ||--o| RELEVANCE_RESULT : has
    CANONICAL_RECORD ||--o| UX_EXTRACTION : has
    UX_EXTRACTION }o--|| CLUSTER_MEMBER : belongs_to
    CLUSTER ||--o{ CLUSTER_MEMBER : contains
    CLUSTER ||--o{ OPPORTUNITY_SCORE : scored_by
    PIPELINE_RUN ||--o{ JOB_CHECKPOINT : tracks

    INGEST_RUN {
        uuid id PK
        string source_type
        timestamp started_at
        string input_checksum
    }

    RAW_RECORD {
        uuid id PK
        uuid ingest_run_id FK
        string source_type
        string source_native_id
        json payload
        string content_uri
    }

    CANONICAL_RECORD {
        uuid id PK
        uuid raw_record_id FK
        string source_type
        string title
        text body
        string author_handle
        timestamp posted_at
        string permalink
        string content_hash
    }

    RELEVANCE_RESULT {
        uuid id PK
        uuid record_id FK
        uuid analysis_run_id
        boolean is_relevant
        float confidence
        text rationale
        string model_id
    }

    UX_EXTRACTION {
        uuid id PK
        uuid record_id FK
        uuid analysis_run_id
        json structured_fields
        json evidence_spans
        string model_id
    }

    CLUSTER {
        uuid id PK
        uuid analysis_run_id
        string label
        text summary
        int member_count
    }

    CLUSTER_MEMBER {
        uuid cluster_id FK
        uuid record_id FK
        float score
    }

    OPPORTUNITY_SCORE {
        uuid cluster_id FK
        float frequency_score
        float severity_score
        float consistency_score
        float evidence_score
        float composite_rank
    }

    PIPELINE_RUN {
        uuid id PK
        string stage
        string status
        timestamp updated_at
    }

    JOB_CHECKPOINT {
        uuid pipeline_run_id FK
        string stage
        int last_batch_index
        json cursor
    }
```

### Canonical record (minimum fields)

| Field | Purpose |
|--------|---------|
| `id` | Stable internal UUID |
| `source_type` | `reddit`, `youtube`, `play_store`, `app_store`, `other` |
| `permalink` | Link back to public evidence |
| `body` | Primary text for NLP/LLM |
| `metadata` | Scores, likes, video id, star rating, etc. |

---

## 7. LLM gateway architecture

Single integration point for Gemini (primary) and Groq (fallback).

```mermaid
flowchart TB
    subgraph PipelineStages
        Rel[Relevance batches]
        Ext[Extraction batches]
        Clu[Cluster labeling optional]
    end

    subgraph LLMGateway
        Router[Provider router]
        Budget[Token and call budget]
        Batch[Batch splitter merger]
        Retry[Retry with backoff]
        Schema[JSON schema validator]
        Cache[Prompt result cache optional]
    end

    Rel --> Router
    Ext --> Router
    Clu --> Router

    Router --> Budget
    Budget --> Batch
    Batch --> Retry
    Retry --> Schema
    Schema --> Cache
    Cache --> PipelineStages
```

**Policies**

- **Batch size:** dynamic based on token estimate (title + body truncated with explicit `...[truncated]` marker in prompt).
- **Idempotency:** hash `(stage, model_id, prompt_version, record_id)`; skip if result exists unless `force_reanalyze`.
- **Validation:** invalid JSON → single retry with repair prompt; then mark record `analysis_failed` with error text.
- **Provenance:** store full prompt template version, not necessarily full prompt text, unless audit mode enabled.

---

## 8. Pipeline orchestration & resumability

```mermaid
stateDiagram-v2
    [*] --> ingest
    ingest --> preprocess
    preprocess --> relevance
    relevance --> extract
    extract --> cluster
    cluster --> opportunity
    opportunity --> publish
    publish --> [*]

    relevance --> relevance: resume checkpoint
    extract --> extract: resume checkpoint
```

| Mechanism | Behavior |
|-----------|----------|
| `PIPELINE_RUN` | One row per full or partial run |
| Checkpoints | After each LLM batch commit |
| Idempotent writes | Upsert on `(record_id, analysis_run_id, stage)` |
| Re-run | New `analysis_run_id` preserves history for comparison |
| Publish | Materialized views or `published_snapshot` for UI consistency |

CLI entry points (suggested):

- `discover ingest --source reddit --file ...`
- `discover run --stage relevance --resume`
- `discover publish --run-id ...`

---

## 9. Research API & UI architecture

### 9.1 API surface (read-heavy)

| Endpoint group | Examples |
|----------------|----------|
| **Stats** | `/stats/sources`, `/stats/pipeline` |
| **Records** | `/records?relevant=true&source=reddit&cluster=...` |
| **Record detail** | `/records/{id}` with raw + extractions + relevance |
| **Clusters** | `/clusters`, `/clusters/{id}/members` |
| **Opportunities** | `/opportunities` sorted by composite rank |
| **Export** | `/export/dataset`, `/export/findings-report` |

All list responses include `record_id` arrays on aggregates for traceability.

### 9.2 UI information architecture

```mermaid
flowchart TB
    Home[Dashboard counts and pipeline status]
    Explore[Record explorer table]
    Detail[Record detail evidence and extractions]
    Clusters[Cluster gallery]
    ClusterDetail[Cluster detail exemplars and distribution]
    Opp[Opportunity comparison]
    Export[Export center]

    Home --> Explore
    Home --> Clusters
    Home --> Opp
    Explore --> Detail
    Clusters --> ClusterDetail
    ClusterDetail --> Detail
    Opp --> ClusterDetail
    Export --> Home
```

**Filter dimensions (from requirements):** retrieval problem cluster, memory type (derived tag), source, relevance, outcome, date range.

---

## 10. Deployment reference architecture

Suitable for a single-operator research project with local or small-cloud deployment.

```mermaid
flowchart TB
    subgraph Runtime["Single host or small VM"]
        Worker[Pipeline worker process]
        APIProc[API server]
        Static[Static UI assets]
    end

    subgraph Data
        PG[(PostgreSQL or SQLite)]
        FS[File system raw JSON blobs]
    end

    subgraph Secrets
        Env[Environment variables]
    end

    Worker --> PG
    Worker --> FS
    APIProc --> PG
    APIProc --> FS
    Static --> APIProc
    Worker --> Env
    APIProc --> Env
```

| Component | Suggested default | Notes |
|-----------|-------------------|--------|
| Database | PostgreSQL (prod) / SQLite (local) | Relational fits filters and exports |
| Raw store | Filesystem or object storage | Large JSON from Apify/YouTube |
| Worker | Python asyncio or task queue | Same codebase as CLI |
| API | FastAPI or similar | OpenAPI for UI codegen |
| UI | React/Next or simple Vite SPA | Table-heavy explorer |

Scaling beyond ~10k records is not a primary requirement; **batch efficiency and provenance** matter more than horizontal scale.

---

## 11. Security, privacy, and compliance

- **Secrets:** YouTube and LLM keys only in environment or secret manager; never committed.
- **Data:** Public conversations only; document retention policy for exports.
- **PII:** Do not enrich records with private data; optional redaction of usernames in exports if interviews use anonymized quotes.
- **LLM:** Send minimum necessary text; truncation documented in provenance.

---

## 12. Observability

| Signal | Use |
|--------|-----|
| Per-stage record counts | Dashboard + pipeline health |
| LLM tokens / call count | Budget tracking |
| Relevance rate | Calibrate filters |
| Failed validations | Prompt/schema fixes |
| Export audit log | Who exported what snapshot |

---

## 13. Testing strategy

| Level | Focus |
|-------|--------|
| **Unit** | Normalizers, dedup keys, deterministic filter, schema validation |
| **Contract** | Golden files per ingestor → canonical JSON |
| **Integration** | Mock LLM gateway; end-to-mini-pipeline on fixture dataset |
| **Evaluation** | Gold set vs [`docs/relevance-criteria.md`](./docs/relevance-criteria.md); relevance/extraction regression; no Reddit-only prompt fixtures as sole eval |

---

## 14. Implementation phasing

```mermaid
gantt
    title Suggested build order
    dateFormat YYYY-MM-DD
    section Foundation
    Schema raw and canonical           :a1, 2026-01-01, 5d
    Reddit ingest and preprocess       :a2, after a1, 4d
    section Intelligence
    Deterministic filter plus relevance :b1, after a2, 6d
    UX extraction                      :b2, after b1, 5d
    section Insights
    Clustering and opportunities       :c1, after b2, 6d
    section Product
    API and UI explorer                :d1, after b2, 8d
    Export and polish                  :d2, after c1, 4d
```

Phases can overlap (e.g. UI on mock data while pipeline matures). YouTube and store ingestors plug in parallel once the ingestor contract exists.

---

## 15. Traceability chain (insight to evidence)

Every user-visible insight must resolve this chain:

```
Opportunity rank
  → Cluster ID
    → Member record IDs
      → UX extraction (versioned)
        → Relevance rationale (versioned)
          → Canonical record
            → Raw payload + permalink
```

The UI **Record detail** view is the leaf anchor; cluster and opportunity screens always surface exemplar links and counts.

---

## 16. Document lineage

| Document | Role |
|----------|------|
| [`problemStatement.txt`](./problemStatement.txt) | Original requirements |
| [`context.md`](./context.md) | Condensed product and research context |
| **`architecture.md`** | Technical structure, components, data model, diagrams |
| [`implementation-plan.md`](./implementation-plan.md) | Phases 2–3 source-agnostic relevance and extraction |

---

## 17. Open architecture decisions

Record choices during implementation:

1. **Embedding model** for clustering — local vs API.
2. **Cluster count** — fully unsupervised vs researcher-adjustable k.
3. **Auth** — open local tool vs login for shared deployment.
4. **Groq fallback** — automatic on Gemini rate limit vs manual switch.

These do not block the core architecture above; they affect configuration and ops only.
