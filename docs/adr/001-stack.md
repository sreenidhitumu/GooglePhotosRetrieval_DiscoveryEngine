# ADR 001: Technology stack (Phase 0)

## Status

Accepted — Phase 0 foundation.

## Context

The discovery engine needs a resumable batch pipeline, relational storage for provenance, a future research API/UI, and efficient LLM integration under free-tier limits ([`architecture.md`](../../architecture.md)).

## Decision

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.9+ (3.11+ recommended) | Strong ecosystem for data/LLM pipelines; single codebase for CLI + API |
| CLI / worker | `click` entry point `discover` | Simple subcommands; same process runs pipeline stages |
| Database | SQLite by default (`DATABASE_URL`); PostgreSQL via URL | Zero-config local MVP; SQLAlchemy allows Postgres later |
| Migrations | Versioned SQL under `migrations/` | Explicit schema review; no ORM-only drift |
| API (later) | FastAPI | Deferred to Phase 5; `src/discover/api/` reserved |
| UI (later) | Vite + React | Deferred to Phase 6; `ui/` reserved |
| LLM | Gemini primary, Groq optional | Per `context.md`; gateway in Phase 2 |

## Consequences

- One virtualenv and `pip install -e .` runs migrations and pipeline stubs.
- Raw JSON blobs may use filesystem under `data/raw/` with DB pointers in later phases.
- Production hardening (auth, async exports) builds on this skeleton without stack change.
