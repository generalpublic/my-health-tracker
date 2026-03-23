-- Migration: Restrict anon role to SELECT-only across all tables.
-- Writes now go through Edge Functions using service_role.
--
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor > New Query).
-- This is idempotent — safe to run multiple times.
-- Drops both naming conventions (anon_insert_X and X_anon_insert).

-- daily_log
DROP POLICY IF EXISTS "anon_insert_daily_log" ON daily_log;
DROP POLICY IF EXISTS "anon_update_daily_log" ON daily_log;
DROP POLICY IF EXISTS "anon_delete_daily_log" ON daily_log;
DROP POLICY IF EXISTS "daily_log_anon_insert" ON daily_log;
DROP POLICY IF EXISTS "daily_log_anon_update" ON daily_log;
DROP POLICY IF EXISTS "daily_log_anon_delete" ON daily_log;

-- nutrition
DROP POLICY IF EXISTS "anon_insert_nutrition" ON nutrition;
DROP POLICY IF EXISTS "anon_update_nutrition" ON nutrition;
DROP POLICY IF EXISTS "anon_delete_nutrition" ON nutrition;
DROP POLICY IF EXISTS "nutrition_anon_insert" ON nutrition;
DROP POLICY IF EXISTS "nutrition_anon_update" ON nutrition;
DROP POLICY IF EXISTS "nutrition_anon_delete" ON nutrition;

-- overall_analysis
DROP POLICY IF EXISTS "anon_insert_overall_analysis" ON overall_analysis;
DROP POLICY IF EXISTS "anon_update_overall_analysis" ON overall_analysis;
DROP POLICY IF EXISTS "anon_delete_overall_analysis" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_anon_insert" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_anon_update" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_anon_delete" ON overall_analysis;

-- session_log
DROP POLICY IF EXISTS "anon_insert_session_log" ON session_log;
DROP POLICY IF EXISTS "anon_update_session_log" ON session_log;
DROP POLICY IF EXISTS "anon_delete_session_log" ON session_log;
DROP POLICY IF EXISTS "session_log_anon_insert" ON session_log;
DROP POLICY IF EXISTS "session_log_anon_update" ON session_log;
DROP POLICY IF EXISTS "session_log_anon_delete" ON session_log;

-- sleep
DROP POLICY IF EXISTS "anon_insert_sleep" ON sleep;
DROP POLICY IF EXISTS "anon_update_sleep" ON sleep;
DROP POLICY IF EXISTS "anon_delete_sleep" ON sleep;
DROP POLICY IF EXISTS "sleep_anon_insert" ON sleep;
DROP POLICY IF EXISTS "sleep_anon_update" ON sleep;
DROP POLICY IF EXISTS "sleep_anon_delete" ON sleep;

-- strength_log
DROP POLICY IF EXISTS "anon_insert_strength_log" ON strength_log;
DROP POLICY IF EXISTS "anon_update_strength_log" ON strength_log;
DROP POLICY IF EXISTS "anon_delete_strength_log" ON strength_log;
DROP POLICY IF EXISTS "strength_log_anon_insert" ON strength_log;
DROP POLICY IF EXISTS "strength_log_anon_update" ON strength_log;
DROP POLICY IF EXISTS "strength_log_anon_delete" ON strength_log;

-- garmin
DROP POLICY IF EXISTS "anon_insert_garmin" ON garmin;
DROP POLICY IF EXISTS "anon_update_garmin" ON garmin;
DROP POLICY IF EXISTS "anon_delete_garmin" ON garmin;
DROP POLICY IF EXISTS "garmin_anon_insert" ON garmin;
DROP POLICY IF EXISTS "garmin_anon_update" ON garmin;
DROP POLICY IF EXISTS "garmin_anon_delete" ON garmin;

-- raw_data_archive
DROP POLICY IF EXISTS "anon_insert_raw_data_archive" ON raw_data_archive;
DROP POLICY IF EXISTS "anon_update_raw_data_archive" ON raw_data_archive;
DROP POLICY IF EXISTS "anon_delete_raw_data_archive" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_anon_insert" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_anon_update" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_anon_delete" ON raw_data_archive;

-- _meta
DROP POLICY IF EXISTS "anon_insert__meta" ON _meta;
DROP POLICY IF EXISTS "anon_update__meta" ON _meta;
DROP POLICY IF EXISTS "anon_delete__meta" ON _meta;
DROP POLICY IF EXISTS "_meta_anon_insert" ON _meta;
DROP POLICY IF EXISTS "_meta_anon_update" ON _meta;
DROP POLICY IF EXISTS "_meta_anon_delete" ON _meta;

-- Verify: anon should only have SELECT policies remaining
-- Run this to check:
-- SELECT tablename, policyname, cmd FROM pg_policies WHERE roles @> '{anon}' ORDER BY tablename;
