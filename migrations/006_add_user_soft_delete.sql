-- Migration: Add soft-delete state for user accounts
-- Date: 2026-05-19
-- Description: Supports authenticated account deletion without hard-deleting user rows.

ALTER TABLE users
ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_users_deleted
ON users(is_deleted);

COMMENT ON COLUMN users.is_deleted IS
'Soft-delete marker for deleted accounts; deleted users cannot authenticate.';

COMMENT ON COLUMN users.deleted_at IS
'Timestamp when the account was soft-deleted.';
