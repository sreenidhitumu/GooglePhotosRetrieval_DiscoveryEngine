# UX extraction criteria (source-agnostic)

Normative definition for Phase 3 extraction. Applies to every `canonical_record` with `is_relevant=true` from Phase 2.

## Objective

Extract **experiential** structured fields when evidenced in text. Do not invent facts. Do not assign problem archetypes, cluster IDs, or opportunity labels.

## Schema (`extraction_v1`)

| Field | Description |
|-------|-------------|
| `retrieval_scenario` | What they were trying to find or recover |
| `remembers` | Partial memory cues |
| `forgotten` | Missing descriptors |
| `search_attempt` | What they tried in Google Photos (or compared tools) |
| `failure_point` | Where retrieval broke down |
| `workaround` | Alternative tactics |
| `outcome` | Stated result (success / failure / partial) |

Optional `evidence_spans`: map of field name → short verbatim quote from source.

## QA checklist

- [ ] Every non-null value is supported by the source text or evidence span.
- [ ] No fabricated URLs, dates, or search queries.
- [ ] No taxonomy / archetype / cluster / MVP fields in output.
- [ ] Sparse extractions (`<3` non-null fields) flagged for qualitative review.

## Commands

```bash
discover run --stage extract --analysis-run-id <relevance-run-uuid> --llm-provider gemini
discover extract-report --analysis-run-id <uuid>
discover extract-qa-sample --analysis-run-id <uuid>
```

Extraction rows use the **same** `analysis_run_id` as the relevance run they depend on.
