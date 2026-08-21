-- Migration: Add provider-versioned semantic embedding store
-- Date: 2026-05-05
-- Description: Adds a shadow-only OpenAI embedding store without changing legacy vector(1752) columns.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS semantic_embeddings (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(80) NOT NULL,
    source_id VARCHAR(200) NOT NULL,
    source_label VARCHAR(1000),
    source_text TEXT NOT NULL,
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(200) NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    -- Unconstrained vector keeps this store provider/model-versioned without
    -- guessing the OpenAI dimension before live discovery. Dimension-specific
    -- vector indexes should be added after backfill evidence confirms the size.
    embedding vector NOT NULL,
    source_text_hash VARCHAR(64) NOT NULL,
    embedding_hash VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, model, source_type, source_id, source_text_hash)
);

CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_source
ON semantic_embeddings(source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_provider_model
ON semantic_embeddings(provider, model);

CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_dimension
ON semantic_embeddings(provider, model, dimension);

CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_active
ON semantic_embeddings(is_active);

COMMENT ON TABLE semantic_embeddings IS
'Provider-versioned semantic embeddings for shadow comparison; legacy vector(1752) columns are preserved for rollback.';

COMMENT ON COLUMN semantic_embeddings.embedding IS
'Unconstrained pgvector embedding; row-level dimension records the actual provider/model vector length.';
