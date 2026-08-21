-- Migration: Add candidate-constrained LLM mapping suggestions
-- Date: 2026-05-21
-- Description: Persist backend Qwen taxonomy/template mapping suggestions without auto-confirming tags.

CREATE TABLE IF NOT EXISTS llm_mapping_suggestions (
    id VARCHAR(36) PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES filing_jobs(id) ON DELETE CASCADE,
    extracted_data_item_id VARCHAR(36) NOT NULL REFERENCES extracted_data_items(id) ON DELETE CASCADE,
    suggested_template_field_id VARCHAR(200),
    confidence DOUBLE PRECISION,
    reason TEXT,
    ranked_candidates_json TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'suggested',
    model_id VARCHAR(200) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    raw_response_preview TEXT,
    diagnostic_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_mapping_suggestions_job
    ON llm_mapping_suggestions(job_id, status);

CREATE INDEX IF NOT EXISTS idx_llm_mapping_suggestions_item
    ON llm_mapping_suggestions(extracted_data_item_id);

CREATE INDEX IF NOT EXISTS idx_llm_mapping_suggestions_template
    ON llm_mapping_suggestions(suggested_template_field_id);

COMMENT ON TABLE llm_mapping_suggestions IS
'Candidate-constrained LLM suggestions for mapping extracted data rows to existing template fields.';

COMMENT ON COLUMN llm_mapping_suggestions.suggested_template_field_id IS
'Existing template/concept identifier selected from the provided candidate list, or null when no safe suggestion exists.';

COMMENT ON COLUMN llm_mapping_suggestions.status IS
'Suggestion lifecycle: suggested, accepted, ignored, or rejected.';
