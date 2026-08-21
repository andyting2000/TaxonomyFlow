-- Migration: Initial database schema
-- Date: 2025-10-16
-- Description: Complete initial schema for XBRL Filing Platform
-- This creates all tables, indexes, and extensions needed for the application

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Table: xml_template_fields
CREATE TABLE IF NOT EXISTS xml_template_fields (
    id SERIAL PRIMARY KEY,
    field_id VARCHAR(200) NOT NULL,
    statement_code VARCHAR(20) NOT NULL,
    statement_type VARCHAR(100) NOT NULL,
    label VARCHAR(500) NOT NULL,
    xbrl_tag VARCHAR(200) NOT NULL,
    data_type VARCHAR(50) DEFAULT 'string',
    required BOOLEAN DEFAULT FALSE,
    position INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    path VARCHAR(500),
    embedding vector(1752),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

-- Indexes for xml_template_fields
CREATE INDEX IF NOT EXISTS idx_template_field_id ON xml_template_fields(field_id);
CREATE INDEX IF NOT EXISTS idx_template_statement_code ON xml_template_fields(statement_code);
CREATE INDEX IF NOT EXISTS idx_template_label ON xml_template_fields(label);
CREATE INDEX IF NOT EXISTS idx_template_xbrl_tag ON xml_template_fields(xbrl_tag);

-- Table: mbrs_taxonomy_tags
CREATE TABLE IF NOT EXISTS mbrs_taxonomy_tags (
    id SERIAL PRIMARY KEY,
    label VARCHAR(1000) NOT NULL,
    xbrl_tag VARCHAR(1000) NOT NULL,
    namespace VARCHAR(50) NOT NULL,
    period_type VARCHAR(10) DEFAULT 'duration',
    embedding vector(1752)
);

-- Indexes for mbrs_taxonomy_tags
CREATE INDEX IF NOT EXISTS idx_label_search ON mbrs_taxonomy_tags(label);
CREATE INDEX IF NOT EXISTS idx_xbrl_tag ON mbrs_taxonomy_tags(xbrl_tag);
CREATE INDEX IF NOT EXISTS idx_namespace_period ON mbrs_taxonomy_tags(namespace, period_type);

-- Table: filing_jobs
CREATE TABLE IF NOT EXISTS filing_jobs (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(555) NOT NULL,
    registration_number VARCHAR(100),
    financial_year_end TIMESTAMP NOT NULL,
    source_pdf_path VARCHAR(500) NOT NULL,
    status VARCHAR(10) DEFAULT 'PROCESSING',
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    directors_report_html TEXT
);

-- Indexes for filing_jobs
CREATE INDEX IF NOT EXISTS idx_status_uploaded ON filing_jobs(status, uploaded_at);

-- Table: financial_statement_pages
CREATE TABLE IF NOT EXISTS financial_statement_pages (
    id VARCHAR(36) PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES filing_jobs(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    image_path VARCHAR(500) NOT NULL
);

-- Indexes for financial_statement_pages
CREATE INDEX IF NOT EXISTS idx_job_page ON financial_statement_pages(job_id, page_number);

-- Table: extracted_data_items
CREATE TABLE IF NOT EXISTS extracted_data_items (
    id VARCHAR(36) PRIMARY KEY,
    page_id VARCHAR(36) NOT NULL REFERENCES financial_statement_pages(id) ON DELETE CASCADE,
    extracted_label VARCHAR(1000) NOT NULL,
    extracted_value TEXT NOT NULL,
    financial_year INTEGER,
    value_previous_year TEXT,
    financial_year_previous INTEGER,
    statement_type VARCHAR(100),
    template_field_id VARCHAR(200),
    template_position INTEGER,
    is_required_field BOOLEAN DEFAULT FALSE,
    is_reviewed BOOLEAN DEFAULT FALSE,
    confirmed_tag_id INTEGER REFERENCES mbrs_taxonomy_tags(id) ON DELETE SET NULL,
    validation_warnings TEXT,
    has_calculation_warning BOOLEAN DEFAULT FALSE
);

-- Indexes for extracted_data_items
CREATE INDEX IF NOT EXISTS idx_page_item ON extracted_data_items(page_id, id);
CREATE INDEX IF NOT EXISTS idx_reviewed_confirmed ON extracted_data_items(is_reviewed, confirmed_tag_id);
CREATE INDEX IF NOT EXISTS idx_statement_year ON extracted_data_items(statement_type, financial_year);
CREATE INDEX IF NOT EXISTS idx_template_field ON extracted_data_items(template_field_id, statement_type);
CREATE INDEX IF NOT EXISTS idx_template_position ON extracted_data_items(statement_type, template_position);
CREATE INDEX IF NOT EXISTS idx_validation_warnings ON extracted_data_items(has_calculation_warning);

-- Comments on key columns
COMMENT ON COLUMN extracted_data_items.validation_warnings IS
'JSON array of validation warning objects from calculation linkbase validation';

COMMENT ON COLUMN extracted_data_items.has_calculation_warning IS
'Quick flag to identify items with calculation validation warnings';

COMMENT ON TABLE filing_jobs IS
'Main entity representing a filing submission';

COMMENT ON TABLE financial_statement_pages IS
'Individual PDF pages rendered as images';

COMMENT ON TABLE extracted_data_items IS
'Financial line items extracted from pages';

COMMENT ON TABLE mbrs_taxonomy_tags IS
'MBRS XBRL taxonomy tags with embeddings for semantic search';

COMMENT ON TABLE xml_template_fields IS
'MPERS template fields from XML files with embeddings';
