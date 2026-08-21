-- Migration: Add separate Supervisor-guided advisory mapping revisions
-- Date: 2026-07-21
-- Description: Persist bounded manual mapper revisions without mutating original or final mappings.

CREATE TABLE IF NOT EXISTS supervisor_guided_mapping_revisions (
    id VARCHAR(36) PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES filing_jobs(id) ON DELETE CASCADE,
    parent_suggestion_id VARCHAR(36) NOT NULL REFERENCES llm_mapping_suggestions(id) ON DELETE CASCADE,
    supervisor_review_id VARCHAR(36) NOT NULL REFERENCES mapping_supervisor_reviews(id) ON DELETE CASCADE,
    correction_attempt INTEGER NOT NULL,
    correction_source VARCHAR(40) NOT NULL DEFAULT 'supervisor_feedback',
    original_suggested_qname VARCHAR(300),
    revised_suggested_qname VARCHAR(300),
    revised_confidence DOUBLE PRECISION,
    supervisor_decision VARCHAR(40) NOT NULL,
    reason TEXT,
    addressed_supervisor_issues_json TEXT,
    remaining_ambiguities_json TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    model_id VARCHAR(200),
    requires_human_review BOOLEAN NOT NULL DEFAULT TRUE,
    safe_for_auto_apply BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT chk_supervisor_guided_revisions_attempt CHECK (correction_attempt >= 1),
    CONSTRAINT chk_supervisor_guided_revisions_source CHECK (correction_source = 'supervisor_feedback'),
    CONSTRAINT chk_supervisor_guided_revisions_status CHECK (status IN ('running', 'completed', 'failed')),
    CONSTRAINT chk_supervisor_guided_revisions_human_review CHECK (requires_human_review = TRUE),
    CONSTRAINT chk_supervisor_guided_revisions_no_auto_apply CHECK (safe_for_auto_apply = FALSE)
);

CREATE INDEX IF NOT EXISTS idx_supervisor_guided_revisions_job
    ON supervisor_guided_mapping_revisions(job_id, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_supervisor_guided_revisions_parent
    ON supervisor_guided_mapping_revisions(parent_suggestion_id, correction_attempt);

CREATE INDEX IF NOT EXISTS idx_supervisor_guided_revisions_review
    ON supervisor_guided_mapping_revisions(supervisor_review_id);

COMMENT ON TABLE supervisor_guided_mapping_revisions IS
'Separate advisory revisions from explicit Supervisor feedback reruns. Never a final mapping or auto-apply record.';
