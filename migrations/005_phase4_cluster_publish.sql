ALTER TABLE cluster ADD COLUMN metadata_json TEXT;
ALTER TABLE published_snapshot ADD COLUMN snapshot_json TEXT;

CREATE INDEX IF NOT EXISTS idx_cluster_run ON cluster(analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_cluster_member_record ON cluster_member(record_id);
