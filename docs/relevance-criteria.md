# Relevance criteria (source-agnostic)

Normative definition for Phase 2 relevance classification. Applies to every `canonical_record` regardless of `source_type`. Reddit is used first for **calibration** only ([`implementation-plan.md`](../implementation-plan.md)).

## Research objective

Identify public conversations that contain **evidence** about **Google Photos** and a **retrieval or memory experience** with visual media in that product context (library search, browse, Memories, shared albums, etc.).

## In scope (`is_relevant = true`)

Require **both** of the following, grounded in the text (no inference):

### 1. Google Photos context

Explicit mention or unambiguous reference to **Google Photos** as a product/library: the app, `photos.google.com`, Google Photos search or browse, albums in Google Photos, or **Memories** / “remember this day” / resurfaced photos from Google Photos.

Not sufficient on their own: Google Search, Google Lens, Image Search, Pixel camera, generic “Google”, or other Google services unless the narrative is clearly about **their Google Photos library**.

### 2. Retrieval or memory experience

At least one of:

- **Search** — keyword, natural language, object/person search, filters; failed, weak, or regressed results in Google Photos.  
- **Browse / scroll** — timeline or library navigation to find something they are trying to recover.  
- **Memories** — Google Photos surfaces media and the user describes a **memory gap** or missing context for that item.  
- **Search-quality issues** — first-person complaint that Google Photos (especially AI/NL search) no longer finds items they expect in **their** library.  
- **Success after struggle** — found the item after incomplete memory and GP retrieval attempts (workarounds included).

**Memory / recall gap** is required for classic “fuzzy memory” stories, but **Memories-without-context** and **library search/browse failure** can satisfy the memory/retrieval side when the text supports it.

### Theme tags (`retrieval_signal_types`)

Optional open tags aligned to discovery themes (not problem archetypes):

| Tag | Meaning |
|-----|---------|
| `memory_gap` | Partial or vague memory of the visual item |
| `recall_vs_forgotten` | Contrasts what they remember vs forgot |
| `search_formulation` | How they phrased or iterated searches |
| `failure_point` | Where retrieval broke down |
| `workaround` | Alternative path (Drive, another app, person, etc.) |
| `visual_content_type` | Screenshot, video, document, etc. mentioned |
| `product_context` | Google Photos / library context |
| `outcome_mentioned` | Success, failure, or partial result stated |

## Out of scope (`is_relevant = false`)

- **Google Search / Lens / web** — reverse image, “where is this photo from”, help-me-find on the internet, without searching Google Photos.  
- **Data loss / sync / backup / Takeout / trash** — missing files with **no** search/browse for a **specific remembered** item ([`edge-cases.md`](../edge-cases.md) REL-002).  
- **Non–Google Photos products** — Immich, PhotoPrism, Apple Photos, etc., unless Google Photos retrieval is part of the story.  
- Generic app complaints (speed, UI, pricing, editing) **without** GP retrieval/memory evidence.  
- Hypothetical or third-person advice with **no** first-person GP experience.  
- Content where **either** GP context **or** retrieval/memory behavior cannot be cited from the text.

## LLM classification

Prompt version **`relevance_v2`** for all sources. The model must:

- Set `is_relevant` only when **(A) GP context** and **(B) retrieval/memory** are evidenced in the record text.  
- Use `rationale` to state support for (A) and (B) separately; if either is absent, `is_relevant=false`.  
- Not invent products, quotes, or retrieval attempts.

**Do not** use cluster names, MVP labels, or fixed problem taxonomies in relevance output.

## Deterministic gate (pre-LLM)

Optional lightweight filter on **title + body** only (when gate bypass is off):

- Requires visual/library cues **and** retrieval or memory cues.  
- **Must not** use subreddit lists, Reddit-only keywords, or `source_type` branches.

Failed gate → stored as `gate_skipped` (no LLM spend).

## Calibration & volume

- Gold set: ~30 manually labeled records (stratified relevant / irrelevant / borderline). Target **≥0.8 precision** on labeled relevant.  
- **150–200+** relevant rows on the initial Reddit corpus is a **calibration target**, not the definition of relevance.  
- Export summary: `discover relevance-report --analysis-run-id <uuid>`.  
- **Test fixtures** (e.g. permalink containing `/comments/abc/sample01`) are **excluded from calibration metric totals** in the export; they may still be classified in the pipeline.

## Portability

Phase 7 sources re-run **`discover run --stage relevance`** with the **same** prompt version—only new canonical IDs.
