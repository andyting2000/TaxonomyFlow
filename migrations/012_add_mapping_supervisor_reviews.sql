-- Migration: Add Supervisor mapping review persistence
-- Date: 2026-06-17
-- Description: Persist advisory Supervisor review metadata without mutating mappings.

CREATE TABLE IF NOT EXISTS mapping_supervisor_reviews (
    id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    job_id INTEGER NOT NULL REFERENCES filing_jobs(id) ON DELETE CASCADE,
    extracted_data_item_id VARCHAR(36) REFERENCES extracted_data_items(id) ON DELETE SET NULL,
    llm_mapping_suggestion_id VARCHAR(36) REFERENCES llm_mapping_suggestions(id) ON DELETE SET NULL,
    mapper_selected_template_field_id VARCHAR(200),
    mapper_selected_qname VARCHAR(300),
    mapper_confidence DOUBLE PRECISION,
    mapper_status VARCHAR(40),
    review_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    supervisor_decision VARCHAR(40),
    supervisor_risk_level VARCHAR(20),
    supervisor_recommended_action VARCHAR(50),
    supervisor_safe_to_accept BOOLEAN NOT NULL DEFAULT FALSE,
    calibrated_safe_to_accept BOOLEAN NOT NULL DEFAULT FALSE,
    supervisor_confidence_adjustment VARCHAR(20),
    supervisor_issues_json TEXT,
    supervisor_reason TEXT,
    supervisor_model_provider VARCHAR(50),
    supervisor_model_id VARCHAR(200),
    supervisor_prompt_version VARCHAR(80),
    supervisor_schema_version VARCHAR(80),
    supervisor_payload_hash VARCHAR(64),
    supervisor_response_hash VARCHAR(64),
    error_type VARCHAR(80),
    error_message_sanitized TEXT,
    started_at TIMESTAMP WITHOUT TIME ZONE,
    completed_at TIMESTAMP WITHOUT TIME ZONE,
    review_attempt INTEGER NOT NULL DEFAULT 1,
    source VARCHAR(20) NOT NULL DEFAULT 'mock',
    is_latest BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_mapping_supervisor_reviews_status
        CHECK (review_status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    CONSTRAINT chk_mapping_supervisor_reviews_decision
        CHECK (supervisor_decision IS NULL OR supervisor_decision IN ('agree', 'disagree', 'needs_human_review')),
    CONSTRAINT chk_mapping_supervisor_reviews_risk
        CHECK (supervisor_risk_level IS NULL OR supervisor_risk_level IN ('low', 'medium', 'high')),
    CONSTRAINT chk_mapping_supervisor_reviews_action
        CHECK (
            supervisor_recommended_action IS NULL
            OR supervisor_recommended_action IN ('accept', 'reject', 'keep_for_human_review', 'request_better_candidate')
        ),
    CONSTRAINT chk_mapping_supervisor_reviews_confidence_adjustment
        CHECK (supervisor_confidence_adjustment IS NULL OR supervisor_confidence_adjustment IN ('increase', 'keep', 'decrease')),
    CONSTRAINT chk_mapping_supervisor_reviews_source
        CHECK (source IN ('mock', 'live', 'imported', 'manual')),
    CONSTRAINT chk_mapping_supervisor_reviews_mapper_confidence
        CHECK (mapper_confidence IS NULL OR (mapper_confidence >= 0 AND mapper_confidence <= 1)),
    CONSTRAINT chk_mapping_supervisor_reviews_attempt
        CHECK (review_attempt >= 1)
);

CREATE INDEX IF NOT EXISTS idx_mapping_supervisor_reviews_job
    ON mapping_supervisor_reviews(job_id, review_status);

CREATE INDEX IF NOT EXISTS idx_mapping_supervisor_reviews_suggestion
    ON mapping_supervisor_reviews(llm_mapping_suggestion_id);

CREATE INDEX IF NOT EXISTS idx_mapping_supervisor_reviews_item
    ON mapping_supervisor_reviews(extracted_data_item_id);

CREATE INDEX IF NOT EXISTS idx_mapping_supervisor_reviews_status
    ON mapping_supervisor_reviews(review_status);

CREATE INDEX IF NOT EXISTS idx_mapping_supervisor_reviews_safe
    ON mapping_supervisor_reviews(job_id, supervisor_safe_to_accept);

CREATE INDEX IF NOT EXISTS idx_mapping_supervisor_reviews_calibrated_safe
    ON mapping_supervisor_reviews(job_id, calibrated_safe_to_accept);

CREATE INDEX IF NOT EXISTS idx_mapping_supervisor_reviews_risk
    ON mapping_supervisor_reviews(job_id, supervisor_risk_level);

CREATE INDEX IF NOT EXISTS idx_mapping_supervisor_reviews_created
    ON mapping_supervisor_reviews(created_at);

COMMENT ON TABLE mapping_supervisor_reviews IS
'Advisory Supervisor review metadata for mapper suggestions or extracted rows. Reviews do not mutate final mappings.';

COMMENT ON COLUMN mapping_supervisor_reviews.supervisor_safe_to_accept IS
'Advisory Supervisor safe-to-accept result. Human confirmation remains required.';

COMMENT ON COLUMN mapping_supervisor_reviews.calibrated_safe_to_accept IS
'Advisory calibrated safe-to-accept result from deterministic guardrails. Human confirmation remains required.';

COMMENT ON COLUMN mapping_supervisor_reviews.supervisor_payload_hash IS
'SHA-256 hash of the canonical sanitized Supervisor payload. Raw payload is not stored by default.';

COMMENT ON COLUMN mapping_supervisor_reviews.supervisor_response_hash IS
'SHA-256 hash of the canonical normalized Supervisor response. Raw response is not stored by default.';
