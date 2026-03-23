-- ============================================================================
-- Migration: Add user_id + UNIQUE constraints + per-table RLS
-- Health Tracker — Security Hardening
--
-- Run in Supabase SQL Editor in order. Each section is idempotent (safe to re-run).
--
-- BEFORE RUNNING:
-- 1. Take a Supabase backup (Dashboard -> Settings -> Database -> Backups)
-- 2. Pause scheduled jobs (Task Scheduler: disable garmin_sync triggers)
-- 3. Create your auth user (Dashboard -> Auth -> Users -> Add User)
-- 4. Copy your UUID and replace <YOUR-UUID-HERE> below
-- ============================================================================

-- *** Find-and-replace YOUR-UUID-HERE with your actual UUID from Supabase Auth ***
-- Example: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'

-- ============================================================================
-- STEP 1: Add user_id column (nullable, with DEFAULT) to all data tables
-- ============================================================================

ALTER TABLE garmin ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();
ALTER TABLE sleep ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();
ALTER TABLE overall_analysis ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();
ALTER TABLE daily_log ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();
ALTER TABLE session_log ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();
ALTER TABLE nutrition ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();
ALTER TABLE strength_log ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();
ALTER TABLE raw_data_archive ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();
ALTER TABLE illness_state ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();
ALTER TABLE illness_daily_log ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT auth.uid();

-- Verify: all tables should show user_id column
SELECT table_name, column_name, is_nullable
FROM information_schema.columns
WHERE column_name = 'user_id' AND table_schema = 'public'
ORDER BY table_name;


-- ============================================================================
-- STEP 2: Backfill user_id on all existing rows
-- NOTE: Replace <YOUR-UUID-HERE> with your actual UUID before running!
-- ============================================================================

UPDATE garmin SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;
UPDATE sleep SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;
UPDATE overall_analysis SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;
UPDATE daily_log SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;
UPDATE session_log SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;
UPDATE nutrition SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;
UPDATE strength_log SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;
UPDATE raw_data_archive SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;
UPDATE illness_state SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;
UPDATE illness_daily_log SET user_id = '9a1aa6b9-e257-471a-82ad-c3a284706a3c' WHERE user_id IS NULL;

-- Verify: zero NULL user_ids
SELECT 'garmin' AS t, count(*) FROM garmin WHERE user_id IS NULL
UNION ALL SELECT 'sleep', count(*) FROM sleep WHERE user_id IS NULL
UNION ALL SELECT 'overall_analysis', count(*) FROM overall_analysis WHERE user_id IS NULL
UNION ALL SELECT 'daily_log', count(*) FROM daily_log WHERE user_id IS NULL
UNION ALL SELECT 'session_log', count(*) FROM session_log WHERE user_id IS NULL
UNION ALL SELECT 'nutrition', count(*) FROM nutrition WHERE user_id IS NULL
UNION ALL SELECT 'strength_log', count(*) FROM strength_log WHERE user_id IS NULL
UNION ALL SELECT 'raw_data_archive', count(*) FROM raw_data_archive WHERE user_id IS NULL
UNION ALL SELECT 'illness_state', count(*) FROM illness_state WHERE user_id IS NULL
UNION ALL SELECT 'illness_daily_log', count(*) FROM illness_daily_log WHERE user_id IS NULL;


-- ============================================================================
-- STEP 3: Set user_id NOT NULL on all data tables
-- (Run AFTER deploying code with _with_owner() — Step 4 in migration plan)
-- ============================================================================

ALTER TABLE garmin ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE sleep ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE overall_analysis ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE daily_log ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE session_log ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE nutrition ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE strength_log ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE raw_data_archive ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE illness_state ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE illness_daily_log ALTER COLUMN user_id SET NOT NULL;

-- Verify: all NOT NULL
SELECT table_name, is_nullable
FROM information_schema.columns
WHERE column_name = 'user_id' AND table_schema = 'public'
ORDER BY table_name;


-- ============================================================================
-- STEP 4: Add owner-scoped UNIQUE constraints (idempotent)
-- ============================================================================

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'garmin_owner_uq' AND conrelid = 'garmin'::regclass
  ) THEN
    ALTER TABLE garmin ADD CONSTRAINT garmin_owner_uq UNIQUE (user_id, date);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'sleep_owner_uq' AND conrelid = 'sleep'::regclass
  ) THEN
    ALTER TABLE sleep ADD CONSTRAINT sleep_owner_uq UNIQUE (user_id, date);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'overall_analysis_owner_uq' AND conrelid = 'overall_analysis'::regclass
  ) THEN
    ALTER TABLE overall_analysis ADD CONSTRAINT overall_analysis_owner_uq UNIQUE (user_id, date);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'daily_log_owner_uq' AND conrelid = 'daily_log'::regclass
  ) THEN
    ALTER TABLE daily_log ADD CONSTRAINT daily_log_owner_uq UNIQUE (user_id, date);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'session_log_owner_uq' AND conrelid = 'session_log'::regclass
  ) THEN
    ALTER TABLE session_log ADD CONSTRAINT session_log_owner_uq UNIQUE (user_id, date, activity_name);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'nutrition_owner_uq' AND conrelid = 'nutrition'::regclass
  ) THEN
    ALTER TABLE nutrition ADD CONSTRAINT nutrition_owner_uq UNIQUE (user_id, date);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'raw_data_archive_owner_uq' AND conrelid = 'raw_data_archive'::regclass
  ) THEN
    ALTER TABLE raw_data_archive ADD CONSTRAINT raw_data_archive_owner_uq UNIQUE (user_id, date);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'illness_state_owner_uq' AND conrelid = 'illness_state'::regclass
  ) THEN
    ALTER TABLE illness_state ADD CONSTRAINT illness_state_owner_uq UNIQUE (user_id, onset_date);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'illness_daily_log_owner_uq' AND conrelid = 'illness_daily_log'::regclass
  ) THEN
    ALTER TABLE illness_daily_log ADD CONSTRAINT illness_daily_log_owner_uq UNIQUE (user_id, date);
  END IF;
END $$;

-- strength_log: no UNIQUE constraint (INSERT-only), but add index for query performance
CREATE INDEX IF NOT EXISTS idx_strength_log_user_date ON strength_log (user_id, date);

-- Verify: all constraints exist
SELECT conname, conrelid::regclass AS table_name
FROM pg_constraint
WHERE contype = 'u'
  AND connamespace = 'public'::regnamespace
  AND conname LIKE '%_owner_uq'
ORDER BY conname;


-- ============================================================================
-- STEP 5: Replace RLS policies — per-table least privilege
-- ============================================================================

-- Enable RLS on all tables (idempotent)
ALTER TABLE garmin ENABLE ROW LEVEL SECURITY;
ALTER TABLE sleep ENABLE ROW LEVEL SECURITY;
ALTER TABLE overall_analysis ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE nutrition ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_data_archive ENABLE ROW LEVEL SECURITY;
ALTER TABLE _meta ENABLE ROW LEVEL SECURITY;
ALTER TABLE illness_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE illness_daily_log ENABLE ROW LEVEL SECURITY;

-- ---- Drop ALL old policies (both old naming conventions and new) ----

-- garmin (read-only for browser)
DROP POLICY IF EXISTS "garmin_anon_select" ON garmin;
DROP POLICY IF EXISTS "garmin_authenticated_all" ON garmin;
DROP POLICY IF EXISTS "garmin_owner_select" ON garmin;

-- sleep (rw for browser)
DROP POLICY IF EXISTS "sleep_anon_select" ON sleep;
DROP POLICY IF EXISTS "sleep_authenticated_all" ON sleep;
DROP POLICY IF EXISTS "sleep_owner_select" ON sleep;
DROP POLICY IF EXISTS "sleep_owner_insert" ON sleep;
DROP POLICY IF EXISTS "sleep_owner_update" ON sleep;

-- overall_analysis (rw for browser)
DROP POLICY IF EXISTS "overall_analysis_anon_select" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_authenticated_all" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_owner_select" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_owner_insert" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_owner_update" ON overall_analysis;

-- daily_log (rw for browser)
DROP POLICY IF EXISTS "daily_log_anon_select" ON daily_log;
DROP POLICY IF EXISTS "daily_log_authenticated_all" ON daily_log;
DROP POLICY IF EXISTS "daily_log_owner_select" ON daily_log;
DROP POLICY IF EXISTS "daily_log_owner_insert" ON daily_log;
DROP POLICY IF EXISTS "daily_log_owner_update" ON daily_log;

-- session_log (rw for browser)
DROP POLICY IF EXISTS "session_log_anon_select" ON session_log;
DROP POLICY IF EXISTS "session_log_authenticated_all" ON session_log;
DROP POLICY IF EXISTS "session_log_owner_select" ON session_log;
DROP POLICY IF EXISTS "session_log_owner_insert" ON session_log;
DROP POLICY IF EXISTS "session_log_owner_update" ON session_log;

-- nutrition (rw for browser)
DROP POLICY IF EXISTS "nutrition_anon_select" ON nutrition;
DROP POLICY IF EXISTS "nutrition_authenticated_all" ON nutrition;
DROP POLICY IF EXISTS "nutrition_owner_select" ON nutrition;
DROP POLICY IF EXISTS "nutrition_owner_insert" ON nutrition;
DROP POLICY IF EXISTS "nutrition_owner_update" ON nutrition;

-- strength_log (insert-only for browser)
DROP POLICY IF EXISTS "strength_log_anon_select" ON strength_log;
DROP POLICY IF EXISTS "strength_log_authenticated_all" ON strength_log;
DROP POLICY IF EXISTS "strength_log_owner_select" ON strength_log;
DROP POLICY IF EXISTS "strength_log_owner_insert" ON strength_log;

-- raw_data_archive (server-only)
DROP POLICY IF EXISTS "raw_data_archive_anon_select" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_authenticated_all" ON raw_data_archive;

-- _meta (server-only)
DROP POLICY IF EXISTS "_meta_anon_select" ON _meta;
DROP POLICY IF EXISTS "_meta_authenticated_all" ON _meta;

-- illness_state (read-only for browser)
DROP POLICY IF EXISTS "illness_state_anon_select" ON illness_state;
DROP POLICY IF EXISTS "illness_state_authenticated_all" ON illness_state;
DROP POLICY IF EXISTS "illness_state_owner_select" ON illness_state;

-- illness_daily_log (read-only for browser)
DROP POLICY IF EXISTS "illness_daily_log_anon_select" ON illness_daily_log;
DROP POLICY IF EXISTS "illness_daily_log_authenticated_all" ON illness_daily_log;
DROP POLICY IF EXISTS "illness_daily_log_owner_select" ON illness_daily_log;


-- ---- Create new per-table least-privilege policies ----

-- BROWSER WRITABLE (SELECT + INSERT + UPDATE): daily_log, nutrition, session_log, sleep, overall_analysis

CREATE POLICY "daily_log_owner_select" ON daily_log
  FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "daily_log_owner_insert" ON daily_log
  FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "daily_log_owner_update" ON daily_log
  FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "nutrition_owner_select" ON nutrition
  FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "nutrition_owner_insert" ON nutrition
  FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "nutrition_owner_update" ON nutrition
  FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "session_log_owner_select" ON session_log
  FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "session_log_owner_insert" ON session_log
  FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "session_log_owner_update" ON session_log
  FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "sleep_owner_select" ON sleep
  FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "sleep_owner_insert" ON sleep
  FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "sleep_owner_update" ON sleep
  FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "overall_analysis_owner_select" ON overall_analysis
  FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "overall_analysis_owner_insert" ON overall_analysis
  FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "overall_analysis_owner_update" ON overall_analysis
  FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- BROWSER INSERT-ONLY (SELECT + INSERT): strength_log

CREATE POLICY "strength_log_owner_select" ON strength_log
  FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "strength_log_owner_insert" ON strength_log
  FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());

-- BROWSER READ-ONLY (SELECT): garmin, illness_state, illness_daily_log

CREATE POLICY "garmin_owner_select" ON garmin
  FOR SELECT TO authenticated USING (user_id = auth.uid());

CREATE POLICY "illness_state_owner_select" ON illness_state
  FOR SELECT TO authenticated USING (user_id = auth.uid());

CREATE POLICY "illness_daily_log_owner_select" ON illness_daily_log
  FOR SELECT TO authenticated USING (user_id = auth.uid());

-- SERVER-ONLY: raw_data_archive, _meta — no browser policies (service_role bypasses RLS)


-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- 1. All policies — should match access matrix
SELECT tablename, policyname, roles, cmd
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;

-- 2. No anon policies should exist
SELECT tablename, policyname
FROM pg_policies
WHERE schemaname = 'public' AND roles @> ARRAY['anon']::name[];

-- 3. All user_id columns are NOT NULL
SELECT table_name, is_nullable
FROM information_schema.columns
WHERE column_name = 'user_id' AND table_schema = 'public'
ORDER BY table_name;

-- 4. Existing PKs still intact
SELECT conname, conrelid::regclass AS table_name
FROM pg_constraint
WHERE contype = 'p'
  AND connamespace = 'public'::regnamespace
ORDER BY conname;
