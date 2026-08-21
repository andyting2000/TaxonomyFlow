-- Migration: Add filing job processing diagnostics
-- Date: 2026-05-21
-- Description: Persist task progress and failure details for Azure DI production processing.

ALTER TABLE filing_jobs
ADD COLUMN IF NOT EXISTS progress INTEGER,
ADD COLUMN IF NOT EXISTS error_message TEXT;

COMMENT ON COLUMN filing_jobs.progress IS
'Last persisted processing progress percentage for the filing job.';

COMMENT ON COLUMN filing_jobs.error_message IS
'Last persisted processing failure message for the filing job.';

