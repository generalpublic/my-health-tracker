-- =============================================================================
-- Health Tracker — Supabase Schema (v3)
--
-- Multi-tenant: all data tables use (user_id, date) composite primary keys.
-- RLS policies scope all access to auth.uid().
--
-- Column-level encryption decision (2026-03-23):
--   NOT IMPLEMENTED. Supabase provides AES-256 disk-level encryption at rest.
--   Column-level pgcrypto would break WHERE/ORDER BY/aggregates on encrypted
--   columns and add key management complexity. RLS already gates per-user access.
--   Revisit only if multi-user with HIPAA/regulatory requirements.
--
-- Client-side obfuscation:
--   localStorage offline queue is encrypted via AES-256-GCM (crypto-store.js).
--   Key derived from user ID (public UUID) — obfuscation against casual
--   inspection, not confidentiality against XSS or local forensic access.
-- =============================================================================

-- garmin: primary daily wellness + activity data from Garmin
CREATE TABLE IF NOT EXISTS garmin (
    date TEXT NOT NULL,
    day TEXT,
    sleep_score REAL,
    hrv_overnight_avg REAL,
    hrv_7day_avg REAL,
    resting_hr REAL,
    sleep_duration_hrs REAL,
    body_battery REAL,
    steps INTEGER,
    total_calories_burned REAL,
    active_calories_burned REAL,
    bmr_calories REAL,
    avg_stress_level REAL,
    stress_qualifier TEXT,
    floors_ascended INTEGER,
    moderate_intensity_min REAL,
    vigorous_intensity_min REAL,
    body_battery_at_wake REAL,
    body_battery_high REAL,
    body_battery_low REAL,
    activity_name TEXT,
    activity_type TEXT,
    start_time TEXT,
    distance_mi REAL,
    duration_min REAL,
    avg_hr REAL,
    max_hr REAL,
    calories REAL,
    elevation_gain_m REAL,
    avg_speed_mph REAL,
    aerobic_training_effect REAL,
    anaerobic_training_effect REAL,
    zone_1_min REAL,
    zone_2_min REAL,
    zone_3_min REAL,
    zone_4_min REAL,
    zone_5_min REAL,
    spo2_avg REAL,
    spo2_min REAL,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, date)
);

-- sleep: detailed sleep metrics
CREATE TABLE IF NOT EXISTS sleep (
    date TEXT NOT NULL,
    day TEXT,
    garmin_sleep_score REAL,
    sleep_analysis_score REAL,
    total_sleep_hrs REAL,
    sleep_analysis TEXT,
    notes TEXT,
    bedtime TEXT,
    wake_time TEXT,
    time_in_bed_hrs REAL,
    deep_sleep_min REAL,
    light_sleep_min REAL,
    rem_min REAL,
    awake_during_sleep_min REAL,
    deep_pct REAL,
    rem_pct REAL,
    sleep_cycles INTEGER,
    awakenings INTEGER,
    avg_hr REAL,
    avg_respiration REAL,
    overnight_hrv_ms REAL,
    body_battery_gained REAL,
    sleep_feedback TEXT,
    bedtime_variability_7d REAL,
    wake_variability_7d REAL,
    manual_source TEXT,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, date)
);

-- overall_analysis: daily readiness assessment
CREATE TABLE IF NOT EXISTS overall_analysis (
    date TEXT NOT NULL,
    day TEXT,
    readiness_score REAL,
    readiness_label TEXT,
    confidence TEXT,
    cognitive_energy_assessment TEXT,
    sleep_context TEXT,
    cognition REAL,
    cognition_notes TEXT,
    key_insights TEXT,
    recommendations TEXT,
    training_load_status TEXT,
    manual_source TEXT,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, date)
);

-- daily_log: daily habit tracking and subjective ratings
CREATE TABLE IF NOT EXISTS daily_log (
    date TEXT NOT NULL,
    day TEXT,
    morning_energy REAL,
    wake_at_930 INTEGER,
    no_morning_screens INTEGER,
    creatine_hydrate INTEGER,
    walk_breathing INTEGER,
    physical_activity INTEGER,
    no_screens_before_bed INTEGER,
    bed_at_10pm INTEGER,
    habits_total INTEGER,
    midday_energy REAL,
    midday_focus REAL,
    midday_mood REAL,
    midday_body_feel REAL,
    midday_notes TEXT,
    evening_energy REAL,
    evening_focus REAL,
    evening_mood REAL,
    perceived_stress REAL,
    day_rating REAL,
    evening_notes TEXT,
    manual_source TEXT,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, date)
);

-- session_log: workout sessions (multiple per day allowed)
CREATE TABLE IF NOT EXISTS session_log (
    date TEXT NOT NULL,
    activity_name TEXT NOT NULL,
    day TEXT,
    session_type TEXT,
    perceived_effort REAL,
    post_workout_energy REAL,
    notes TEXT,
    duration_min REAL,
    distance_mi REAL,
    avg_hr REAL,
    max_hr REAL,
    calories REAL,
    aerobic_te REAL,
    anaerobic_te REAL,
    zone_1_min REAL,
    zone_2_min REAL,
    zone_3_min REAL,
    zone_4_min REAL,
    zone_5_min REAL,
    zone_ranges TEXT,
    source TEXT,
    elevation_m REAL,
    manual_source TEXT,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, date, activity_name)
);

-- nutrition: daily meal and macro tracking
CREATE TABLE IF NOT EXISTS nutrition (
    date TEXT NOT NULL,
    day TEXT,
    total_calories_burned REAL,
    active_calories_burned REAL,
    bmr_calories REAL,
    breakfast TEXT,
    lunch TEXT,
    dinner TEXT,
    snacks TEXT,
    total_calories_consumed REAL,
    protein_g REAL,
    carbs_g REAL,
    fats_g REAL,
    water_l REAL,
    calorie_balance REAL,
    notes TEXT,
    manual_source TEXT,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, date)
);

-- strength_log: individual sets for weight training
-- set_id: client-generated UUID per set — allows multiple sets of the same
-- exercise on the same day while deduplicating offline replays.
CREATE TABLE IF NOT EXISTS strength_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date TEXT NOT NULL,
    day TEXT,
    muscle_group TEXT,
    exercise TEXT,
    set_id TEXT NOT NULL DEFAULT gen_random_uuid()::text,
    weight_lbs REAL,
    reps INTEGER,
    rpe REAL,
    notes TEXT,
    manual_source TEXT,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strength_log_date ON strength_log(date);
CREATE INDEX IF NOT EXISTS idx_strength_log_user_date ON strength_log(user_id, date);

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

-- raw_data_archive: full Garmin export mirror (all text columns)
CREATE TABLE IF NOT EXISTS raw_data_archive (
    date TEXT NOT NULL,
    day TEXT,
    hrv TEXT, hrv_7day TEXT, resting_hr TEXT, body_battery TEXT, steps TEXT,
    total_calories TEXT, active_calories TEXT, bmr_calories TEXT,
    avg_stress TEXT, stress_qualifier TEXT, floors_ascended TEXT,
    moderate_min TEXT, vigorous_min TEXT,
    bb_at_wake TEXT, bb_high TEXT, bb_low TEXT,
    sleep_duration TEXT, sleep_score TEXT, sleep_bedtime TEXT, sleep_wake_time TEXT,
    sleep_time_in_bed TEXT, sleep_deep_min TEXT, sleep_light_min TEXT, sleep_rem_min TEXT,
    sleep_awake_min TEXT, sleep_deep_pct TEXT, sleep_rem_pct TEXT, sleep_cycles TEXT,
    sleep_awakenings TEXT, sleep_avg_hr TEXT, sleep_avg_respiration TEXT,
    sleep_body_battery_gained TEXT, sleep_feedback TEXT,
    activity_name TEXT, activity_type TEXT, activity_start TEXT,
    activity_distance TEXT, activity_duration TEXT, activity_avg_hr TEXT, activity_max_hr TEXT,
    activity_calories TEXT, activity_elevation TEXT, activity_avg_speed TEXT,
    aerobic_te TEXT, anaerobic_te TEXT,
    zone_1 TEXT, zone_2 TEXT, zone_3 TEXT, zone_4 TEXT, zone_5 TEXT,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, date)
);

-- _meta: schema versioning (system metadata, no user_id)
CREATE TABLE IF NOT EXISTS _meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- illness_state: illness episode tracking
CREATE TABLE IF NOT EXISTS illness_state (
    onset_date TEXT NOT NULL,
    confirmed_date TEXT,
    resolved_date TEXT,
    resolution_method TEXT,
    peak_score REAL,
    notes TEXT,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, onset_date)
);

-- illness_daily_log: daily illness anomaly scores
CREATE TABLE IF NOT EXISTS illness_daily_log (
    date TEXT NOT NULL,
    illness_state_id REAL,
    anomaly_score REAL,
    signals TEXT,
    label TEXT,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, date)
);

-- ==========================================================================
-- RLS Policies: per-table least privilege, scoped to auth.uid()
--
-- Browser writable: daily_log, nutrition, session_log, sleep, overall_analysis
--   -> SELECT + INSERT + UPDATE (no DELETE)
-- Browser insert-only: strength_log
--   -> SELECT + INSERT (no UPDATE, no DELETE)
-- Browser read-only: garmin, illness_state, illness_daily_log
--   -> SELECT only
-- Server-only: raw_data_archive, _meta
--   -> No browser policies (service_role bypasses RLS)
-- ==========================================================================

-- ---------- Browser writable: SELECT + INSERT + UPDATE ----------

-- daily_log
ALTER TABLE daily_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "daily_log_anon_select" ON daily_log;
DROP POLICY IF EXISTS "daily_log_anon_insert" ON daily_log;
DROP POLICY IF EXISTS "daily_log_anon_update" ON daily_log;
DROP POLICY IF EXISTS "daily_log_anon_delete" ON daily_log;
DROP POLICY IF EXISTS "daily_log_authenticated_all" ON daily_log;
DROP POLICY IF EXISTS "daily_log_owner_select" ON daily_log;
DROP POLICY IF EXISTS "daily_log_owner_insert" ON daily_log;
DROP POLICY IF EXISTS "daily_log_owner_update" ON daily_log;
CREATE POLICY "daily_log_owner_select" ON daily_log FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "daily_log_owner_insert" ON daily_log FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "daily_log_owner_update" ON daily_log FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- nutrition
ALTER TABLE nutrition ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "nutrition_anon_select" ON nutrition;
DROP POLICY IF EXISTS "nutrition_anon_insert" ON nutrition;
DROP POLICY IF EXISTS "nutrition_anon_update" ON nutrition;
DROP POLICY IF EXISTS "nutrition_anon_delete" ON nutrition;
DROP POLICY IF EXISTS "nutrition_authenticated_all" ON nutrition;
DROP POLICY IF EXISTS "nutrition_owner_select" ON nutrition;
DROP POLICY IF EXISTS "nutrition_owner_insert" ON nutrition;
DROP POLICY IF EXISTS "nutrition_owner_update" ON nutrition;
CREATE POLICY "nutrition_owner_select" ON nutrition FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "nutrition_owner_insert" ON nutrition FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "nutrition_owner_update" ON nutrition FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- session_log
ALTER TABLE session_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "session_log_anon_select" ON session_log;
DROP POLICY IF EXISTS "session_log_anon_insert" ON session_log;
DROP POLICY IF EXISTS "session_log_anon_update" ON session_log;
DROP POLICY IF EXISTS "session_log_anon_delete" ON session_log;
DROP POLICY IF EXISTS "session_log_authenticated_all" ON session_log;
DROP POLICY IF EXISTS "session_log_owner_select" ON session_log;
DROP POLICY IF EXISTS "session_log_owner_insert" ON session_log;
DROP POLICY IF EXISTS "session_log_owner_update" ON session_log;
CREATE POLICY "session_log_owner_select" ON session_log FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "session_log_owner_insert" ON session_log FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "session_log_owner_update" ON session_log FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- sleep
ALTER TABLE sleep ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "sleep_anon_select" ON sleep;
DROP POLICY IF EXISTS "sleep_anon_insert" ON sleep;
DROP POLICY IF EXISTS "sleep_anon_update" ON sleep;
DROP POLICY IF EXISTS "sleep_anon_delete" ON sleep;
DROP POLICY IF EXISTS "sleep_authenticated_all" ON sleep;
DROP POLICY IF EXISTS "sleep_owner_select" ON sleep;
DROP POLICY IF EXISTS "sleep_owner_insert" ON sleep;
DROP POLICY IF EXISTS "sleep_owner_update" ON sleep;
CREATE POLICY "sleep_owner_select" ON sleep FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "sleep_owner_insert" ON sleep FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "sleep_owner_update" ON sleep FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- overall_analysis
ALTER TABLE overall_analysis ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "overall_analysis_anon_select" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_anon_insert" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_anon_update" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_anon_delete" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_authenticated_all" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_owner_select" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_owner_insert" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_owner_update" ON overall_analysis;
CREATE POLICY "overall_analysis_owner_select" ON overall_analysis FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "overall_analysis_owner_insert" ON overall_analysis FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY "overall_analysis_owner_update" ON overall_analysis FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- ---------- Browser insert-only: SELECT + INSERT ----------

-- strength_log
ALTER TABLE strength_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "strength_log_anon_select" ON strength_log;
DROP POLICY IF EXISTS "strength_log_anon_insert" ON strength_log;
DROP POLICY IF EXISTS "strength_log_anon_update" ON strength_log;
DROP POLICY IF EXISTS "strength_log_anon_delete" ON strength_log;
DROP POLICY IF EXISTS "strength_log_authenticated_all" ON strength_log;
DROP POLICY IF EXISTS "strength_log_owner_select" ON strength_log;
DROP POLICY IF EXISTS "strength_log_owner_insert" ON strength_log;
CREATE POLICY "strength_log_owner_select" ON strength_log FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY "strength_log_owner_insert" ON strength_log FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());

-- ---------- Browser read-only: SELECT only ----------

-- garmin
ALTER TABLE garmin ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "garmin_anon_select" ON garmin;
DROP POLICY IF EXISTS "garmin_anon_insert" ON garmin;
DROP POLICY IF EXISTS "garmin_anon_update" ON garmin;
DROP POLICY IF EXISTS "garmin_anon_delete" ON garmin;
DROP POLICY IF EXISTS "garmin_authenticated_all" ON garmin;
DROP POLICY IF EXISTS "garmin_owner_select" ON garmin;
CREATE POLICY "garmin_owner_select" ON garmin FOR SELECT TO authenticated USING (user_id = auth.uid());

-- illness_state
ALTER TABLE illness_state ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "illness_state_anon_select" ON illness_state;
DROP POLICY IF EXISTS "illness_state_authenticated_all" ON illness_state;
DROP POLICY IF EXISTS "illness_state_owner_select" ON illness_state;
CREATE POLICY "illness_state_owner_select" ON illness_state FOR SELECT TO authenticated USING (user_id = auth.uid());

-- illness_daily_log
ALTER TABLE illness_daily_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "illness_daily_log_anon_select" ON illness_daily_log;
DROP POLICY IF EXISTS "illness_daily_log_authenticated_all" ON illness_daily_log;
DROP POLICY IF EXISTS "illness_daily_log_owner_select" ON illness_daily_log;
CREATE POLICY "illness_daily_log_owner_select" ON illness_daily_log FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ---------- Server-only: no browser policies ----------

-- raw_data_archive (service_role only — no authenticated policies)
ALTER TABLE raw_data_archive ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "raw_data_archive_anon_select" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_anon_insert" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_anon_update" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_anon_delete" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_authenticated_all" ON raw_data_archive;

-- _meta (service_role only — no authenticated policies)
ALTER TABLE _meta ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "_meta_anon_select" ON _meta;
DROP POLICY IF EXISTS "_meta_anon_insert" ON _meta;
DROP POLICY IF EXISTS "_meta_anon_update" ON _meta;
DROP POLICY IF EXISTS "_meta_anon_delete" ON _meta;
DROP POLICY IF EXISTS "_meta_authenticated_all" ON _meta;
