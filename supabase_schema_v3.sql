-- =============================================================================
-- Supabase Schema v3 Migration — Multi-Tenant Composite Primary Keys
-- Run this in Supabase SQL Editor (Dashboard > SQL Editor > New query)
--
-- What this does:
--   1. Changes PRIMARY KEY from (date) to (user_id, date) on all tables
--   2. Drops the now-redundant *_owner_uq UNIQUE constraints
--      (they were identical to the new PKs)
--   3. Updates _meta schema version to 3
--
-- Prerequisites: v2 migration must have been applied (manual_source columns exist)
-- Safety: All operations are idempotent — safe to run multiple times
-- =============================================================================

-- ---------- garmin ----------
ALTER TABLE garmin DROP CONSTRAINT IF EXISTS garmin_pkey;
ALTER TABLE garmin ADD PRIMARY KEY (user_id, date);
ALTER TABLE garmin DROP CONSTRAINT IF EXISTS garmin_owner_uq;

-- ---------- sleep ----------
ALTER TABLE sleep DROP CONSTRAINT IF EXISTS sleep_pkey;
ALTER TABLE sleep ADD PRIMARY KEY (user_id, date);
ALTER TABLE sleep DROP CONSTRAINT IF EXISTS sleep_owner_uq;

-- ---------- overall_analysis ----------
ALTER TABLE overall_analysis DROP CONSTRAINT IF EXISTS overall_analysis_pkey;
ALTER TABLE overall_analysis ADD PRIMARY KEY (user_id, date);
ALTER TABLE overall_analysis DROP CONSTRAINT IF EXISTS overall_analysis_owner_uq;

-- ---------- daily_log ----------
ALTER TABLE daily_log DROP CONSTRAINT IF EXISTS daily_log_pkey;
ALTER TABLE daily_log ADD PRIMARY KEY (user_id, date);
ALTER TABLE daily_log DROP CONSTRAINT IF EXISTS daily_log_owner_uq;

-- ---------- session_log ----------
-- session_log already has composite PK (date, activity_name) — widen to include user_id
ALTER TABLE session_log DROP CONSTRAINT IF EXISTS session_log_pkey;
ALTER TABLE session_log ADD PRIMARY KEY (user_id, date, activity_name);
ALTER TABLE session_log DROP CONSTRAINT IF EXISTS session_log_owner_uq;

-- ---------- nutrition ----------
ALTER TABLE nutrition DROP CONSTRAINT IF EXISTS nutrition_pkey;
ALTER TABLE nutrition ADD PRIMARY KEY (user_id, date);
ALTER TABLE nutrition DROP CONSTRAINT IF EXISTS nutrition_owner_uq;

-- ---------- raw_data_archive ----------
ALTER TABLE raw_data_archive DROP CONSTRAINT IF EXISTS raw_data_archive_pkey;
ALTER TABLE raw_data_archive ADD PRIMARY KEY (user_id, date);
ALTER TABLE raw_data_archive DROP CONSTRAINT IF EXISTS raw_data_archive_owner_uq;

-- ---------- illness_state ----------
-- illness_state uses onset_date as PK, not date
ALTER TABLE illness_state DROP CONSTRAINT IF EXISTS illness_state_pkey;
ALTER TABLE illness_state ADD PRIMARY KEY (user_id, onset_date);
ALTER TABLE illness_state DROP CONSTRAINT IF EXISTS illness_state_owner_uq;

-- ---------- illness_daily_log ----------
ALTER TABLE illness_daily_log DROP CONSTRAINT IF EXISTS illness_daily_log_pkey;
ALTER TABLE illness_daily_log ADD PRIMARY KEY (user_id, date);
ALTER TABLE illness_daily_log DROP CONSTRAINT IF EXISTS illness_daily_log_owner_uq;

-- ---------- strength_log ----------
-- strength_log keeps auto-increment PK (id), add composite unique constraint
-- for multi-tenant dedup (replaces any existing single-column constraints)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'strength_log_owner_uq'
    AND conrelid = 'strength_log'::regclass
  ) THEN
    ALTER TABLE strength_log
      ADD CONSTRAINT strength_log_owner_uq UNIQUE (user_id, date, exercise);
  END IF;
END $$;

-- ---------- Update schema version ----------
INSERT INTO _meta (key, value) VALUES ('schema_version', '3')
ON CONFLICT (key) DO UPDATE SET value = '3';

-- ---------- Verify ----------
SELECT
  tc.table_name,
  string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position) AS pk_columns
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
  AND tc.table_schema = kcu.table_schema
WHERE tc.constraint_type = 'PRIMARY KEY'
  AND tc.table_schema = 'public'
GROUP BY tc.table_name
ORDER BY tc.table_name;
