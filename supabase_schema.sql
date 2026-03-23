
-- garmin: primary daily wellness + activity data from Garmin
CREATE TABLE IF NOT EXISTS garmin (
    date TEXT PRIMARY KEY,
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- sleep: detailed sleep metrics
CREATE TABLE IF NOT EXISTS sleep (
    date TEXT PRIMARY KEY,
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- overall_analysis: daily readiness assessment
CREATE TABLE IF NOT EXISTS overall_analysis (
    date TEXT PRIMARY KEY,
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- daily_log: daily habit tracking and subjective ratings
CREATE TABLE IF NOT EXISTS daily_log (
    date TEXT PRIMARY KEY,
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
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
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, activity_name)
);

-- nutrition: daily meal and macro tracking
CREATE TABLE IF NOT EXISTS nutrition (
    date TEXT PRIMARY KEY,
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- strength_log: individual sets for weight training
CREATE TABLE IF NOT EXISTS strength_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date TEXT NOT NULL,
    day TEXT,
    muscle_group TEXT,
    exercise TEXT,
    weight_lbs REAL,
    reps INTEGER,
    rpe REAL,
    notes TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strength_log_date ON strength_log(date);

-- raw_data_archive: full Garmin export mirror (all text columns)
CREATE TABLE IF NOT EXISTS raw_data_archive (
    date TEXT PRIMARY KEY,
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
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- _meta: schema versioning
CREATE TABLE IF NOT EXISTS _meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==========================================================================
-- RLS Policies: anon = SELECT only. All writes go through Edge Functions
-- using service_role (which bypasses RLS). This prevents browser clients
-- from inserting, updating, or deleting data directly.
-- ==========================================================================

-- garmin
ALTER TABLE garmin ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "garmin_anon_select" ON garmin;
DROP POLICY IF EXISTS "garmin_anon_insert" ON garmin;
DROP POLICY IF EXISTS "garmin_anon_update" ON garmin;
DROP POLICY IF EXISTS "garmin_anon_delete" ON garmin;
CREATE POLICY "garmin_anon_select" ON garmin FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "garmin_authenticated_all" ON garmin;
CREATE POLICY "garmin_authenticated_all" ON garmin FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- sleep
ALTER TABLE sleep ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "sleep_anon_select" ON sleep;
DROP POLICY IF EXISTS "sleep_anon_insert" ON sleep;
DROP POLICY IF EXISTS "sleep_anon_update" ON sleep;
DROP POLICY IF EXISTS "sleep_anon_delete" ON sleep;
CREATE POLICY "sleep_anon_select" ON sleep FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "sleep_authenticated_all" ON sleep;
CREATE POLICY "sleep_authenticated_all" ON sleep FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- overall_analysis
ALTER TABLE overall_analysis ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "overall_analysis_anon_select" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_anon_insert" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_anon_update" ON overall_analysis;
DROP POLICY IF EXISTS "overall_analysis_anon_delete" ON overall_analysis;
CREATE POLICY "overall_analysis_anon_select" ON overall_analysis FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "overall_analysis_authenticated_all" ON overall_analysis;
CREATE POLICY "overall_analysis_authenticated_all" ON overall_analysis FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- daily_log
ALTER TABLE daily_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "daily_log_anon_select" ON daily_log;
DROP POLICY IF EXISTS "daily_log_anon_insert" ON daily_log;
DROP POLICY IF EXISTS "daily_log_anon_update" ON daily_log;
DROP POLICY IF EXISTS "daily_log_anon_delete" ON daily_log;
CREATE POLICY "daily_log_anon_select" ON daily_log FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "daily_log_authenticated_all" ON daily_log;
CREATE POLICY "daily_log_authenticated_all" ON daily_log FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- session_log
ALTER TABLE session_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "session_log_anon_select" ON session_log;
DROP POLICY IF EXISTS "session_log_anon_insert" ON session_log;
DROP POLICY IF EXISTS "session_log_anon_update" ON session_log;
DROP POLICY IF EXISTS "session_log_anon_delete" ON session_log;
CREATE POLICY "session_log_anon_select" ON session_log FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "session_log_authenticated_all" ON session_log;
CREATE POLICY "session_log_authenticated_all" ON session_log FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- nutrition
ALTER TABLE nutrition ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "nutrition_anon_select" ON nutrition;
DROP POLICY IF EXISTS "nutrition_anon_insert" ON nutrition;
DROP POLICY IF EXISTS "nutrition_anon_update" ON nutrition;
DROP POLICY IF EXISTS "nutrition_anon_delete" ON nutrition;
CREATE POLICY "nutrition_anon_select" ON nutrition FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "nutrition_authenticated_all" ON nutrition;
CREATE POLICY "nutrition_authenticated_all" ON nutrition FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- strength_log
ALTER TABLE strength_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "strength_log_anon_select" ON strength_log;
DROP POLICY IF EXISTS "strength_log_anon_insert" ON strength_log;
DROP POLICY IF EXISTS "strength_log_anon_update" ON strength_log;
DROP POLICY IF EXISTS "strength_log_anon_delete" ON strength_log;
CREATE POLICY "strength_log_anon_select" ON strength_log FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "strength_log_authenticated_all" ON strength_log;
CREATE POLICY "strength_log_authenticated_all" ON strength_log FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- raw_data_archive
ALTER TABLE raw_data_archive ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "raw_data_archive_anon_select" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_anon_insert" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_anon_update" ON raw_data_archive;
DROP POLICY IF EXISTS "raw_data_archive_anon_delete" ON raw_data_archive;
CREATE POLICY "raw_data_archive_anon_select" ON raw_data_archive FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "raw_data_archive_authenticated_all" ON raw_data_archive;
CREATE POLICY "raw_data_archive_authenticated_all" ON raw_data_archive FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- _meta
ALTER TABLE _meta ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "_meta_anon_select" ON _meta;
DROP POLICY IF EXISTS "_meta_anon_insert" ON _meta;
DROP POLICY IF EXISTS "_meta_anon_update" ON _meta;
DROP POLICY IF EXISTS "_meta_anon_delete" ON _meta;
CREATE POLICY "_meta_anon_select" ON _meta FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "_meta_authenticated_all" ON _meta;
CREATE POLICY "_meta_authenticated_all" ON _meta FOR ALL TO authenticated USING (true) WITH CHECK (true);