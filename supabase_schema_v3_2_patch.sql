-- =============================================================================
-- Supabase Schema v3.2 Patch — strength_log set_id NOT NULL + DEFAULT
-- Run this in Supabase SQL Editor (Dashboard > SQL Editor > New query)
--
-- What this does:
--   1. Backfills any remaining NULL set_id values
--   2. Sets a server-side DEFAULT so rows inserted without set_id get one
--   3. Makes set_id NOT NULL so the UNIQUE constraint is always enforced
--
-- Safety: All operations are idempotent — safe to run multiple times
-- Prereq: v3.1 patch must have been applied first (set_id column exists)
-- =============================================================================

-- Step 1: Backfill any NULL set_id values (idempotent)
UPDATE strength_log SET set_id = gen_random_uuid()::text WHERE set_id IS NULL;

-- Step 2: Add server-side default for new rows
ALTER TABLE strength_log ALTER COLUMN set_id SET DEFAULT gen_random_uuid()::text;

-- Step 3: Make NOT NULL (safe — Step 1 ensured no NULLs remain)
ALTER TABLE strength_log ALTER COLUMN set_id SET NOT NULL;

-- Step 4: Update schema version
INSERT INTO _meta (key, value) VALUES ('schema_version', '3.2')
ON CONFLICT (key) DO UPDATE SET value = '3.2';

-- Verify
SELECT column_name, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'strength_log' AND column_name = 'set_id';
