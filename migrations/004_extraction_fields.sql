ALTER TABLE ux_extraction ADD COLUMN extraction_status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE ux_extraction ADD COLUMN error_message TEXT;
ALTER TABLE ux_extraction ADD COLUMN prompt_version TEXT;

CREATE INDEX IF NOT EXISTS idx_ux_extraction_run ON ux_extraction(analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_ux_extraction_status ON ux_extraction(extraction_status);
