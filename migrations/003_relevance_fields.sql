ALTER TABLE relevance_result ADD COLUMN gate_passed INTEGER;
ALTER TABLE relevance_result ADD COLUMN gate_reason TEXT;
ALTER TABLE relevance_result ADD COLUMN retrieval_signal_types_json TEXT;
ALTER TABLE relevance_result ADD COLUMN analysis_status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE relevance_result ADD COLUMN error_message TEXT;
ALTER TABLE relevance_result ADD COLUMN prompt_version TEXT;

CREATE TABLE IF NOT EXISTS relevance_gate_skip (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL UNIQUE REFERENCES canonical_record(id),
    analysis_run_id TEXT NOT NULL REFERENCES analysis_run(id),
    gate_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_relevance_gate_skip_run ON relevance_gate_skip(analysis_run_id);
