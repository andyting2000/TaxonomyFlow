-- Migration: Add admin role flag to users
-- Date: 2026-05-28
-- Description: Supports admin-only management accounts without granting workspace access.

ALTER TABLE users
ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN users.is_admin IS
'True for management-only admin accounts; admins are blocked from normal filing/job workspaces.';
