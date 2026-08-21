-- Migration: Add filing job owner for user isolation
-- Date: 2026-05-19
-- Description: Associates new filing jobs with authenticated users while preserving legacy rows as unassigned.

ALTER TABLE filing_jobs
ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_filing_jobs_user_uploaded
ON filing_jobs(user_id, uploaded_at);

COMMENT ON COLUMN filing_jobs.user_id IS
'Owner user for authenticated filing isolation. NULL rows are legacy/pre-auth and are hidden from normal authenticated users until explicitly assigned.';
