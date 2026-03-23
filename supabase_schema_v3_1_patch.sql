-- =============================================================================
-- Supabase Schema v3.1 Patch — strength_log multi-set fix
-- Run this in Supabase SQL Editor (Dashboard > SQL Editor > New query)
--
-- What this does:
--   1. Adds set_id column to strength_log (client-generated UUID per set)
--   2. Drops the old (user_id, date, exercise) UNIQUE constraint
--      (which blocked multiple sets of the same exercise per day)
--   3. Adds new (user_id, set_id) UNIQUE constraint for offline replay dedup
--   4. Backfills existing rows with generated UUIDs
--
-- Safety: All operations are idempotent — safe to run multiple times
-- =============================================================================

-- Step 1: Add set_id column if it doesn't exist
ALTER TABLE strength_log ADD COLUMN IF NOT EXISTS set_id TEXT;

-- Step 2: Backfill existing rows with unique IDs
UPDATE strength_log SET set_id = gen_random_uuid()::text WHERE set_id IS NULL;

-- Step 3: Drop old constraint that blocks multi-set logging
ALTER TABLE strength_log DROP CONSTRAINT IF EXISTS strength_log_owner_uq;

-- Step 4: Add new constraint for offline replay dedup
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'strength_log_set_uq'
    AND conrelid = 'strength_log'::regclass
  ) THEN
    ALTER TABLE strength_log
      ADD CONSTRAINT strength_log_set_uq UNIQUE (user_id, set_id);
  END IF;
END $$;

-- Step 5: Update schema version
INSERT INTO _meta (key, value) VALUES ('schema_version', '3.1')
ON CONFLICT (key) DO UPDATE SET value = '3.1';

-- Verify
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'strength_log'::regclass
ORDER BY conname;
