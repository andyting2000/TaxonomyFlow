-- Migration: Add user token version for bearer-token revocation
-- Date: 2026-05-20
-- Description: Invalidates old bearer tokens after account-sensitive changes.

ALTER TABLE users
ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN users.token_version IS
'Version included in signed auth tokens; increment to invalidate previously issued tokens.';
