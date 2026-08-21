-- Migration: Add users table for authentication foundation
-- Date: 2026-05-19
-- Description: Minimal user account store for register/login/current-user flows.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(320) NOT NULL,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email
ON users(email);

CREATE INDEX IF NOT EXISTS idx_users_active
ON users(is_active);

COMMENT ON TABLE users IS
'Application users for authentication; product-level ownership isolation is handled by later features.';

COMMENT ON COLUMN users.password_hash IS
'PBKDF2-SHA256 password hash in algorithm$iterations$salt$hash format.';
