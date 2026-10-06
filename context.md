# Project Context: AI-Powered Discovery Engine for Google Photos Retrieval

This document summarizes the project scope, workflow, constraints, and expected outcomes derived from the problem statement. Use it as persistent context for design, implementation, and research decisions.

---

## North Star Question

> When users vaguely remember a visual memory, what prevents them from successfully retrieving it, and which retrieval failure represents the strongest opportunity for further user research?

The final deliverable is an **evidence base** for follow-on work: 5–6 user interviews, problem definition, and selection of an AI-native MVP.

---

## Objective

Build an **AI-powered research / discovery engine** (not a product search feature) that analyzes **public user conversations at scale** to understand why people struggle to retrieve old **photos, videos, screenshots, and documents** from **Google Photos** when they have a **visual memory** but cannot describe the item precisely.

The system must **discover problems from evidence**—not assume a solution or fixed taxonomy upfront.

### Primary actor (MVP)

**Researcher / Operator** — a single role for this MVP (see [`architecture.md`](./architecture.md)): upload datasets, configure API credentials, trigger and monitor analysis runs, inspect pipeline output, and explore/export findings in the research interface.

### Questions the engine should answer from data

| Theme | What to learn |
|--------|----------------|
| Memory gaps | What types of visual memories users struggle to retrieve |
| Recall vs. loss | What users remember vs. what they have forgotten |
| Search behavior | How users formulate searches when memory is incomplete |
| Failure points | Where retrieval breaks down |
| Workarounds | What workarounds users use |
| Patterns | Recurring retrieval problem patterns and opportunity areas |

---

## Data Sources

Modular ingestion; multiple public sources:

| Source | Notes |
|--------|--------|
| **Reddit** | Apify-scraped JSON dataset (~1,000 records), uploaded by Researcher / Operator |
| **YouTube** | API key configured by Researcher / Operator; collect relevant public videos/comments |
| **Google Play Store** | Public Google Photos reviews where feasible; imported datasets as fallback |
| **Apple App Store** | Same as Play Store |
| **Other** | e.g. Google Photos Community, support threads, public forums—as useful |

---

## AI Analysis

- **Primary LLM:** Gemini (batch processing; minimize calls due to limited/free tier).
- **Optional:** Groq as alternative.
- **Relevance (source-agnostic):** Criteria tied to the **north star and discovery themes**—evidence of **vaguely remembered visual content** and **difficulty retrieving it in Google Photos** (or direct comparison while attempting GP retrieval). Applied on **`canonical_record` only** (same rules and prompts for Reddit, YouTube, Play Store, App Store). **Balanced:** not so broad that unrelated Google Photos complaints dominate; not so narrow that useful retrieval experiences are dropped. **Not** based on subreddit/Reddit idioms, platform-specific branches, or a predetermined problem taxonomy.
- **Calibration:** The first Reddit corpus (~956 canonical rows after Phase 1) is used to **tune thresholds, prompts, and gold-set metrics**—not to define Reddit-only logic. See [`docs/relevance-criteria.md`](./docs/relevance-criteria.md) (Phase 2 deliverable) and [`implementation-plan.md`](./implementation-plan.md) Phase 2.
- **Volume target (calibration):** **150–200+** relevant records on the current Reddit corpus is a **calibration outcome** for pipeline tuning (more if data supports); it is not the definition of relevance.
- **Extraction (source-agnostic):** For relevant records only, extract **experiential** structured fields when evidenced in text—**no** problem archetypes, cluster IDs, or MVP category enums (those emerge in pattern discovery, Phase 4).
- **Task:** Identify in-scope records and extract structured retrieval experiences for downstream clustering and opportunity analysis.

---

## System Workflow

### 1. Data ingestion

- Load provided Reddit dataset.
- Collect YouTube data via provided API.
- Collect or ingest Play/App Store reviews (or imports).
- Extensible ingestion for additional sources.

### 2. Preprocessing

- Normalize all sources to a **common record structure**.
- Deduplicate and remove obvious noise.
- Preserve **source metadata** and **original user content**.
- Store **raw** data separately from **processed** data.

### 3. Relevance identification

- **Deterministic filtering** + **LLM classification** on normalized **canonical** text (title + body); `source_type` is metadata for traceability, not a fork in labeling logic.
- Focus on meaningful evidence of **vague or incomplete visual-content retrieval** per written criteria ([`docs/relevance-criteria.md`](./docs/relevance-criteria.md)).
- **`retrieval_signal_types`:** optional open labels aligned to discovery **themes** (memory, search attempt, failure, workaround)—not cluster names or MVP hypotheses.
- **Batch** processing to limit API usage; **one prompt version** per analysis run across all sources.
- Keep original record + relevance classification + rationale.
- **First run:** calibrate on Reddit gold set (~30 labeled records); **later sources:** re-run the **same** stage on new canonical IDs (Phase 7).

### 4. User experience extraction (relevant records only)

Runs on **`is_relevant=true`** from step 3, **any source**, with a **single source-agnostic** extraction prompt. Structured fields are **experiential descriptors**, not a problem taxonomy.

Structured fields to extract (when present in source—do not invent):

| Field | Description |
|--------|-------------|
| Retrieval scenario | Context of what they were trying to find |
| What the user remembers | Partial memory cues |
| What the user has forgotten | Missing descriptors |
| Search/retrieval attempt | What they tried in Google Photos or elsewhere |
| Retrieval failure point | Where the process broke down |
| Workaround | Alternative tactics |
| Outcome | Success/failure/partial result |

### 5. Pattern discovery

- Analyze structured records for recurring behaviors, failure modes, memory patterns.
- Group into **retrieval problem archetypes**.
- **Do not** impose a final taxonomy or solution beforehand.

### 6. Opportunity analysis

- Compare problem areas using: **frequency**, **severity/friction**, **consistency across sources**, **strength of evidence**.
- Surface areas for further user research.

### 7. Research interface & export

- Simple **Researcher / Operator** UI (explore, filter, export).
- Drill-down: clusters → individual source records.
- Filter, compare, export analyzed data and findings.

---

## Discovery Pipeline (conceptual)

```
Raw conversations
  → Relevant retrieval experiences
  → Structured user behaviors
  → Retrieval problem clusters
  → Opportunity areas
```

**Traceability:** Every major insight must link back to underlying user records and original source evidence.

---

## Required Application (research UI)

The **Researcher / Operator** must be able to:

- View source and record counts
- Explore relevant records
- Filter by retrieval problem, memory type, source, etc.
- Inspect original user evidence
- Explore identified clusters
- Compare opportunity areas
- Export analyzed dataset and findings

---

## Constraints (non-negotiable)

| Do | Don't |
|----|--------|
| Discover from evidence | Assume final user problem or solution |
| Focus on retrieval-with-fuzzy-memory research | Build a generic Google Photos search engine |
| Use LLM for relevance and structured extraction | Rely only on sentiment or keyword frequency |
| Ground outputs in source text | Invent missing information |
| Separate raw data from LLM analysis | Mix them without clear provenance |
| Design resumable, efficient pipelines | Burn free-tier LLM/API quotas unnecessarily |
| Keep relevance/extraction **source-agnostic** on `canonical_record` | Encode Reddit-only rules, subreddit lists, or per-platform prompt forks in Phases 2–3 |
| Use clustering for archetypes (Phase 4) | Hard-code problem taxonomy in relevance or extraction schemas |

---

## Technical Implications (for implementation planning)

- **Batch LLM jobs** with checkpointing/resume.
- **Schema** for normalized records + relevance flags + extracted UX fields; **cluster/opportunity IDs only after** pattern discovery (not in extraction output).
- **`docs/relevance-criteria.md`:** source-independent definition used for implementation and eval regression.
- **Provenance:** source type, URL/ID, timestamps, raw text snapshot, model version for each LLM step.
- **Modular ingestors** per platform (Reddit JSON, YouTube API, store reviews, future sources).
- **Export formats** suitable for interviews and downstream problem framing (e.g. CSV/JSON + summary reports).

---

## Out of Scope (explicit)

- End-user Google Photos search or retrieval product.
- Predefined problem taxonomy forced before clustering.
- Analysis without linkable source records.

---

## Inputs & credentials (Researcher / Operator)

Supplied and configured by the same person who runs analysis and uses the research UI:

- Reddit Apify JSON (~1k records)
- YouTube API key
- Play/App Store data collection or imported review datasets

---

## Document lineage

- **Source:** `problemStatement.txt`
- **Aligned with:** [`architecture.md`](./architecture.md), [`implementation-plan.md`](./implementation-plan.md) (phasing, source-agnostic relevance/extraction)
- **Purpose:** Persistent project context for agents and developers working in this repository.
