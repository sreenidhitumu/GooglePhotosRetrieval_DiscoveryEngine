CREATE TABLE IF NOT EXISTS excluded_noise (
    id TEXT PRIMARY KEY,
    raw_record_id TEXT NOT NULL REFERENCES raw_record(id),
    ingest_run_id TEXT REFERENCES ingest_run(id),
    reason TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_excluded_noise_raw_unique ON excluded_noise(raw_record_id);

CREATE TABLE IF NOT EXISTS duplicate_group (
    id TEXT PRIMARY KEY,
    primary_canonical_id TEXT NOT NULL REFERENCES canonical_record(id),
    duplicate_raw_record_id TEXT NOT NULL REFERENCES raw_record(id),
    similarity_score REAL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(duplicate_raw_record_id)
);

CREATE INDEX IF NOT EXISTS idx_duplicate_group_primary ON duplicate_group(primary_canonical_id);
