-- Phase 0: core persistence + stubbed analysis tables (no pipeline logic yet)

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ingest_run (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    input_checksum TEXT,
    record_count INTEGER DEFAULT 0,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS raw_record (
    id TEXT PRIMARY KEY,
    ingest_run_id TEXT NOT NULL REFERENCES ingest_run(id),
    source_type TEXT NOT NULL,
    source_native_id TEXT,
    payload_json TEXT NOT NULL,
    content_uri TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_raw_record_ingest_run ON raw_record(ingest_run_id);

CREATE TABLE IF NOT EXISTS canonical_record (
    id TEXT PRIMARY KEY,
    raw_record_id TEXT NOT NULL UNIQUE REFERENCES raw_record(id),
    source_type TEXT NOT NULL,
    title TEXT,
    body TEXT NOT NULL,
    author_handle TEXT,
    posted_at TEXT,
    permalink TEXT,
    content_hash TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_canonical_source ON canonical_record(source_type);
CREATE INDEX IF NOT EXISTS idx_canonical_content_hash ON canonical_record(content_hash);

CREATE TABLE IF NOT EXISTS pipeline_run (
    id TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_message TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_stage ON pipeline_run(stage);

CREATE TABLE IF NOT EXISTS job_checkpoint (
    id TEXT PRIMARY KEY,
    pipeline_run_id TEXT NOT NULL REFERENCES pipeline_run(id),
    stage TEXT NOT NULL,
    last_batch_index INTEGER NOT NULL DEFAULT 0,
    cursor_json TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(pipeline_run_id, stage)
);

-- Stubbed analysis tables (Phase 2+ logic)

CREATE TABLE IF NOT EXISTS analysis_run (
    id TEXT PRIMARY KEY,
    label TEXT,
    model_id TEXT,
    prompt_version TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS relevance_result (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES canonical_record(id),
    analysis_run_id TEXT NOT NULL REFERENCES analysis_run(id),
    is_relevant INTEGER,
    confidence REAL,
    rationale TEXT,
    model_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(record_id, analysis_run_id)
);

CREATE TABLE IF NOT EXISTS ux_extraction (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES canonical_record(id),
    analysis_run_id TEXT NOT NULL REFERENCES analysis_run(id),
    structured_fields_json TEXT,
    evidence_spans_json TEXT,
    model_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(record_id, analysis_run_id)
);

CREATE TABLE IF NOT EXISTS cluster (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL REFERENCES analysis_run(id),
    label TEXT,
    summary TEXT,
    member_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cluster_member (
    cluster_id TEXT NOT NULL REFERENCES cluster(id),
    record_id TEXT NOT NULL REFERENCES canonical_record(id),
    score REAL,
    PRIMARY KEY (cluster_id, record_id)
);

CREATE TABLE IF NOT EXISTS opportunity_score (
    cluster_id TEXT PRIMARY KEY REFERENCES cluster(id),
    frequency_score REAL,
    severity_score REAL,
    consistency_score REAL,
    evidence_score REAL,
    composite_rank REAL
);

CREATE TABLE IF NOT EXISTS published_snapshot (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT REFERENCES analysis_run(id),
    pipeline_run_id TEXT REFERENCES pipeline_run(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT
);
