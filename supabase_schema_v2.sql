-- =============================================================================
-- Supabase Schema v2 Migration — PWA Write Support
-- Run this in Supabase SQL Editor (Dashboard > SQL Editor > New query)
-- =============================================================================

-- 1. Auto-update trigger function for updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Apply trigger to all writable tables
DO $$ BEGIN
  -- Drop if exists to make idempotent
  DROP TRIGGER IF EXISTS trg_garmin_updated_at ON garmin;
  DROP TRIGGER IF EXISTS trg_sleep_updated_at ON sleep;
  DROP TRIGGER IF EXISTS trg_overall_analysis_updated_at ON overall_analysis;
  DROP TRIGGER IF EXISTS trg_daily_log_updated_at ON daily_log;
  DROP TRIGGER IF EXISTS trg_session_log_updated_at ON session_log;
  DROP TRIGGER IF EXISTS trg_nutrition_updated_at ON nutrition;
  DROP TRIGGER IF EXISTS trg_strength_log_updated_at ON strength_log;
  DROP TRIGGER IF EXISTS trg_meta_updated_at ON _meta;
END $$;

CREATE TRIGGER trg_garmin_updated_at BEFORE UPDATE ON garmin FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_sleep_updated_at BEFORE UPDATE ON sleep FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_overall_analysis_updated_at BEFORE UPDATE ON overall_analysis FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_daily_log_updated_at BEFORE UPDATE ON daily_log FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_session_log_updated_at BEFORE UPDATE ON session_log FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_nutrition_updated_at BEFORE UPDATE ON nutrition FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_strength_log_updated_at BEFORE UPDATE ON strength_log FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_meta_updated_at BEFORE UPDATE ON _meta FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 3. Add manual_source column to tables that accept PWA writes
ALTER TABLE daily_log ADD COLUMN IF NOT EXISTS manual_source TEXT;
ALTER TABLE nutrition ADD COLUMN IF NOT EXISTS manual_source TEXT;
ALTER TABLE sleep ADD COLUMN IF NOT EXISTS manual_source TEXT;
ALTER TABLE overall_analysis ADD COLUMN IF NOT EXISTS manual_source TEXT;
ALTER TABLE session_log ADD COLUMN IF NOT EXISTS manual_source TEXT;
ALTER TABLE strength_log ADD COLUMN IF NOT EXISTS manual_source TEXT;

-- 4. Restrict DELETE to service_role only (PWA should never delete)
DROP POLICY IF EXISTS "garmin_anon_delete" ON garmin;
DROP POLICY IF EXISTS "sleep_anon_delete" ON sleep;
DROP POLICY IF EXISTS "overall_analysis_anon_delete" ON overall_analysis;
DROP POLICY IF EXISTS "daily_log_anon_delete" ON daily_log;
DROP POLICY IF EXISTS "session_log_anon_delete" ON session_log;
DROP POLICY IF EXISTS "nutrition_anon_delete" ON nutrition;
DROP POLICY IF EXISTS "strength_log_anon_delete" ON strength_log;
DROP POLICY IF EXISTS "raw_data_archive_anon_delete" ON raw_data_archive;
DROP POLICY IF EXISTS "_meta_anon_delete" ON _meta;

-- 5. Update schema version
INSERT INTO _meta (key, value) VALUES ('schema_version', '2')
ON CONFLICT (key) DO UPDATE SET value = '2';

-- Verify: check that columns and triggers were created
SELECT table_name, column_name
FROM information_schema.columns
WHERE column_name = 'manual_source' AND table_schema = 'public'
ORDER BY table_name;
