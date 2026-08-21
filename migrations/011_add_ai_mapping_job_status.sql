-- Migration: Add AI mapping suggestion generation status to filing jobs
-- Date: 2026-05-29
-- Description: Track asynchronous Qwen suggestion generation status separately from filing review status.

ALTER TABLE filing_jobs
    ADD COLUMN IF NOT EXISTS ai_mapping_status VARCHAR(20) NOT NULL DEFAULT 'not_started';

ALTER TABLE filing_jobs
    ADD COLUMN IF NOT EXISTS ai_mapping_last_error_message TEXT;

CREATE INDEX IF NOT EXISTS idx_filing_jobs_ai_mapping_status
    ON filing_jobs(ai_mapping_status);

COMMENT ON COLUMN filing_jobs.ai_mapping_status IS
'AI mapping suggestion generation status: not_started, running, completed, failed, or rate_limited.';

COMMENT ON COLUMN filing_jobs.ai_mapping_last_error_message IS
'Last AI mapping suggestion generation error, if any.';
