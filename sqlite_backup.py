"""SQLite local backup module for Health Tracker.

Provides a local SQLite database as a parallel backup to Google Sheets.
Every daily sync writes to both Sheets and SQLite via these functions.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "health_tracker.db"
SCHEMA_VERSION = 1

_conn = None


def _to_num(val):
    """Convert empty strings and non-numeric values to None for SQLite."""
    if val is None or val == "":
        return None
    try:
        f = float(val)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return str(val)


def _to_text(val):
    """Convert to text, returning None for empty strings."""
    if val is None or val == "":
        return None
    return str(val)


def get_db():
    """Return a module-level SQLite connection, creating DB on first call."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH))
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        init_db(_conn)
    return _conn


def close_db():
    """Close the module-level connection if open."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def init_db(conn):
    """Create all tables if they don't exist."""
    conn.executescript("""
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
        spo2_avg REAL,
        spo2_min REAL,
        updated_at TEXT DEFAULT (datetime('now'))
    );

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
        updated_at TEXT DEFAULT (datetime('now'))
    );

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
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS session_log (
        date TEXT NOT NULL,
        day TEXT,
        session_type TEXT,
        perceived_effort REAL,
        post_workout_energy REAL,
        notes TEXT,
        activity_name TEXT NOT NULL,
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
        updated_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (date, activity_name)
    );

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
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS strength_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        day TEXT,
        muscle_group TEXT,
        exercise TEXT,
        weight_lbs REAL,
        reps INTEGER,
        rpe REAL,
        notes TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_strength_log_date ON strength_log(date);

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
        created_at TEXT DEFAULT (datetime('now'))
    );

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
        data_quality TEXT,
        quality_flags TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS _meta (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS illness_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        onset_date TEXT NOT NULL,
        confirmed_date TEXT,
        resolved_date TEXT,
        resolution_method TEXT,
        peak_score REAL,
        notes TEXT,
        created_at TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS illness_daily_log (
        date TEXT PRIMARY KEY,
        illness_state_id INTEGER REFERENCES illness_state(id),
        anomaly_score REAL,
        signals TEXT,
        label TEXT
    );

    CREATE TABLE IF NOT EXISTS kb_personal_validations (
        kb_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        r REAL,
        n INTEGER,
        p REAL,
        last_computed TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );
    """)

    # Migrate: add new columns to existing tables (safe — ALTER ignores if col exists)
    for col, ctype in [("bedtime_variability_7d", "REAL"), ("wake_variability_7d", "REAL")]:
        try:
            conn.execute(f"ALTER TABLE sleep ADD COLUMN {col} {ctype}")
        except Exception:
            pass  # column already exists

    for col, ctype in [("spo2_avg", "REAL"), ("spo2_min", "REAL")]:
        try:
            conn.execute(f"ALTER TABLE garmin ADD COLUMN {col} {ctype}")
        except Exception:
            pass  # column already exists

    for col, ctype in [("data_quality", "TEXT"), ("quality_flags", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE overall_analysis ADD COLUMN {col} {ctype}")
        except Exception:
            pass  # column already exists

    # Set schema version
    conn.execute(
        "INSERT OR REPLACE INTO _meta (key, value, updated_at) VALUES ('schema_version', ?, datetime('now'))",
        (str(SCHEMA_VERSION),)
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Upsert functions — accept the same `data` dict used by Sheets write functions
# ---------------------------------------------------------------------------

def upsert_garmin(conn, date_str, data):
    """Upsert one row into the garmin table from a Garmin data dict."""
    conn.execute("""
        INSERT OR REPLACE INTO garmin (
            date, day, sleep_score, hrv_overnight_avg, hrv_7day_avg, resting_hr,
            sleep_duration_hrs, body_battery, steps, total_calories_burned,
            active_calories_burned, bmr_calories, avg_stress_level, stress_qualifier,
            floors_ascended, moderate_intensity_min, vigorous_intensity_min,
            body_battery_at_wake, body_battery_high, body_battery_low,
            activity_name, activity_type, start_time, distance_mi, duration_min,
            avg_hr, max_hr, calories, elevation_gain_m, avg_speed_mph,
            aerobic_training_effect, anaerobic_training_effect,
            zone_1_min, zone_2_min, zone_3_min, zone_4_min, zone_5_min,
            spo2_avg, spo2_min
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        date_str,
        _day_from_date(date_str),
        _to_num(data.get("sleep_score")),
        _to_num(data.get("hrv")),
        _to_num(data.get("hrv_7day")),
        _to_num(data.get("resting_hr")),
        _to_num(data.get("sleep_duration")),
        _to_num(data.get("body_battery")),
        _to_num(data.get("steps")),
        _to_num(data.get("total_calories")),
        _to_num(data.get("active_calories")),
        _to_num(data.get("bmr_calories")),
        _to_num(data.get("avg_stress")),
        _to_text(data.get("stress_qualifier")),
        _to_num(data.get("floors_ascended")),
        _to_num(data.get("moderate_min")),
        _to_num(data.get("vigorous_min")),
        _to_num(data.get("bb_at_wake")),
        _to_num(data.get("bb_high")),
        _to_num(data.get("bb_low")),
        _to_text(data.get("activity_name")),
        _to_text(data.get("activity_type")),
        _to_text(data.get("activity_start")),
        _to_num(data.get("activity_distance")),
        _to_num(data.get("activity_duration")),
        _to_num(data.get("activity_avg_hr")),
        _to_num(data.get("activity_max_hr")),
        _to_num(data.get("activity_calories")),
        _to_num(data.get("activity_elevation")),
        _to_num(data.get("activity_avg_speed")),
        _to_num(data.get("aerobic_te")),
        _to_num(data.get("anaerobic_te")),
        _to_num(data.get("zone_1")),
        _to_num(data.get("zone_2")),
        _to_num(data.get("zone_3")),
        _to_num(data.get("zone_4")),
        _to_num(data.get("zone_5")),
        _to_num(data.get("spo2_avg")),
        _to_num(data.get("spo2_min")),
    ))


def upsert_sleep(conn, date_str, data):
    """Upsert one row into the sleep table. Only writes if sleep data exists."""
    if not data.get("sleep_duration"):
        return
    conn.execute("""
        INSERT INTO sleep (
            date, day, garmin_sleep_score, sleep_analysis_score, total_sleep_hrs,
            bedtime, wake_time, time_in_bed_hrs,
            deep_sleep_min, light_sleep_min, rem_min, awake_during_sleep_min,
            deep_pct, rem_pct, sleep_cycles, awakenings,
            avg_hr, avg_respiration, overnight_hrv_ms,
            body_battery_gained, sleep_feedback
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            garmin_sleep_score = excluded.garmin_sleep_score,
            sleep_analysis_score = excluded.sleep_analysis_score,
            total_sleep_hrs = excluded.total_sleep_hrs,
            bedtime = excluded.bedtime,
            wake_time = excluded.wake_time,
            time_in_bed_hrs = excluded.time_in_bed_hrs,
            deep_sleep_min = excluded.deep_sleep_min,
            light_sleep_min = excluded.light_sleep_min,
            rem_min = excluded.rem_min,
            awake_during_sleep_min = excluded.awake_during_sleep_min,
            deep_pct = excluded.deep_pct,
            rem_pct = excluded.rem_pct,
            sleep_cycles = excluded.sleep_cycles,
            awakenings = excluded.awakenings,
            avg_hr = excluded.avg_hr,
            avg_respiration = excluded.avg_respiration,
            overnight_hrv_ms = excluded.overnight_hrv_ms,
            body_battery_gained = excluded.body_battery_gained,
            sleep_feedback = excluded.sleep_feedback,
            updated_at = datetime('now')
    """, (
        date_str,
        _day_from_date(date_str),
        _to_num(data.get("sleep_score")),
        _to_num(data.get("sleep_analysis_score")),
        _to_num(data.get("sleep_duration")),
        _to_text(data.get("sleep_bedtime")),
        _to_text(data.get("sleep_wake_time")),
        _to_num(data.get("sleep_time_in_bed")),
        _to_num(data.get("sleep_deep_min")),
        _to_num(data.get("sleep_light_min")),
        _to_num(data.get("sleep_rem_min")),
        _to_num(data.get("sleep_awake_min")),
        _to_num(data.get("sleep_deep_pct")),
        _to_num(data.get("sleep_rem_pct")),
        _to_num(data.get("sleep_cycles")),
        _to_num(data.get("sleep_awakenings")),
        _to_num(data.get("sleep_avg_hr")),
        _to_num(data.get("sleep_avg_respiration")),
        _to_num(data.get("hrv")),
        _to_num(data.get("sleep_body_battery_gained")),
        _to_text(data.get("sleep_feedback")),
    ))


def upsert_nutrition(conn, date_str, data):
    """Upsert one row into the nutrition table. Only writes auto-populated columns."""
    conn.execute("""
        INSERT INTO nutrition (date, day, total_calories_burned, active_calories_burned, bmr_calories)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            total_calories_burned = excluded.total_calories_burned,
            active_calories_burned = excluded.active_calories_burned,
            bmr_calories = excluded.bmr_calories,
            updated_at = datetime('now')
    """, (
        date_str,
        _day_from_date(date_str),
        _to_num(data.get("total_calories")),
        _to_num(data.get("active_calories")),
        _to_num(data.get("bmr_calories")),
    ))


def upsert_session_log(conn, date_str, data):
    """Upsert one row into session_log. Skips if no activity. Preserves manual columns."""
    activity_name = data.get("activity_name")
    if not activity_name:
        return

    # Determine session type (mirrors garmin_sync.py logic)
    activity_type = (data.get("activity_type") or "").lower()
    if any(x in activity_type for x in ("running", "run", "trail")):
        session_type = "Run"
    elif any(x in activity_type for x in ("cycling", "bike", "biking")):
        session_type = "Cycle"
    elif any(x in activity_type for x in ("swimming", "swim")):
        session_type = "Swim"
    elif any(x in activity_type for x in ("strength", "weight", "gym")):
        session_type = "Strength"
    else:
        session_type = "Other"

    conn.execute("""
        INSERT INTO session_log (
            date, day, session_type, activity_name, duration_min, distance_mi,
            avg_hr, max_hr, calories, aerobic_te, anaerobic_te,
            zone_1_min, zone_2_min, zone_3_min, zone_4_min, zone_5_min,
            zone_ranges, source, elevation_m
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date, activity_name) DO UPDATE SET
            session_type = excluded.session_type,
            duration_min = excluded.duration_min,
            distance_mi = excluded.distance_mi,
            avg_hr = excluded.avg_hr,
            max_hr = excluded.max_hr,
            calories = excluded.calories,
            aerobic_te = excluded.aerobic_te,
            anaerobic_te = excluded.anaerobic_te,
            zone_1_min = excluded.zone_1_min,
            zone_2_min = excluded.zone_2_min,
            zone_3_min = excluded.zone_3_min,
            zone_4_min = excluded.zone_4_min,
            zone_5_min = excluded.zone_5_min,
            zone_ranges = excluded.zone_ranges,
            source = excluded.source,
            elevation_m = excluded.elevation_m,
            updated_at = datetime('now')
    """, (
        date_str,
        _day_from_date(date_str),
        session_type,
        activity_name,
        _to_num(data.get("activity_duration")),
        _to_num(data.get("activity_distance")),
        _to_num(data.get("activity_avg_hr")),
        _to_num(data.get("activity_max_hr")),
        _to_num(data.get("activity_calories")),
        _to_num(data.get("aerobic_te")),
        _to_num(data.get("anaerobic_te")),
        _to_num(data.get("zone_1")),
        _to_num(data.get("zone_2")),
        _to_num(data.get("zone_3")),
        _to_num(data.get("zone_4")),
        _to_num(data.get("zone_5")),
        _to_text(data.get("zone_ranges")),
        "Garmin Auto",
        _to_num(data.get("activity_elevation")),
    ))


def upsert_overall_analysis(conn, date_str, data):
    """Upsert one row into overall_analysis. Preserves manual columns (cognition, cognition_notes)."""
    conn.execute("""
        INSERT INTO overall_analysis (
            date, day, readiness_score, readiness_label, confidence,
            cognitive_energy_assessment, sleep_context,
            cognition, cognition_notes,
            key_insights, recommendations, training_load_status,
            data_quality, quality_flags
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            day = excluded.day,
            readiness_score = excluded.readiness_score,
            readiness_label = excluded.readiness_label,
            confidence = excluded.confidence,
            cognitive_energy_assessment = excluded.cognitive_energy_assessment,
            sleep_context = excluded.sleep_context,
            key_insights = excluded.key_insights,
            recommendations = excluded.recommendations,
            training_load_status = excluded.training_load_status,
            data_quality = excluded.data_quality,
            quality_flags = excluded.quality_flags,
            updated_at = datetime('now')
    """, (
        date_str,
        _day_from_date(date_str),
        _to_num(data.get("readiness_score")),
        _to_text(data.get("readiness_label")),
        _to_text(data.get("confidence")),
        _to_text(data.get("cognitive_energy_assessment")),
        _to_text(data.get("sleep_context")),
        _to_num(data.get("cognition")),
        _to_text(data.get("cognition_notes")),
        _to_text(data.get("key_insights")),
        _to_text(data.get("recommendations")),
        _to_text(data.get("training_load_status")),
        _to_text(data.get("data_quality")),
        _to_text(data.get("quality_flags")),
    ))


def upsert_kb_validation(conn, kb_id, status, r, n, p, last_computed):
    """Upsert one row into kb_personal_validations."""
    conn.execute("""
        INSERT OR REPLACE INTO kb_personal_validations
            (kb_id, status, r, n, p, last_computed, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (kb_id, status, r, n, p, last_computed))


def load_kb_validations(conn):
    """Load all personal validations from SQLite.

    Returns dict mapping kb_id -> {"status", "r", "n", "p", "last_computed"}.
    """
    if conn is None:
        return {}
    try:
        rows = conn.execute(
            "SELECT kb_id, status, r, n, p, last_computed FROM kb_personal_validations"
        ).fetchall()
    except Exception:
        return {}
    return {
        row[0]: {
            "status": row[1],
            "r": row[2],
            "n": row[3],
            "p": row[4],
            "last_computed": row[5],
        }
        for row in rows
    }


def append_archive(conn, date_str, data):
    """Append to raw_data_archive. Skips if date already exists (write-once)."""
    from schema import ARCHIVE_KEYS
    columns = ["date", "day"] + ARCHIVE_KEYS
    values = [date_str, _day_from_date(date_str)]
    values += [_to_text(data.get(k)) for k in ARCHIVE_KEYS]
    col_names = ",".join(columns)
    placeholders = ",".join(["?"] * len(values))
    conn.execute(f"INSERT OR IGNORE INTO raw_data_archive ({col_names}) VALUES ({placeholders})", values)


# ---------------------------------------------------------------------------
# Row-based upserts — used by migration script (accepts positional row lists)
# ---------------------------------------------------------------------------

def upsert_garmin_row(conn, row):
    """Upsert garmin table from a positional row list (39 columns, matching HEADERS)."""
    if len(row) < 39:
        row = row + [""] * (39 - len(row))
    conn.execute("""
        INSERT OR REPLACE INTO garmin (
            day, date, sleep_score, hrv_overnight_avg, hrv_7day_avg, resting_hr,
            sleep_duration_hrs, body_battery, steps, total_calories_burned,
            active_calories_burned, bmr_calories, avg_stress_level, stress_qualifier,
            floors_ascended, moderate_intensity_min, vigorous_intensity_min,
            body_battery_at_wake, body_battery_high, body_battery_low,
            activity_name, activity_type, start_time, distance_mi, duration_min,
            avg_hr, max_hr, calories, elevation_gain_m, avg_speed_mph,
            aerobic_training_effect, anaerobic_training_effect,
            zone_1_min, zone_2_min, zone_3_min, zone_4_min, zone_5_min,
            spo2_avg, spo2_min
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        _to_text(row[0]),   # day
        _to_text(row[1]),   # date
        _to_num(row[2]),    # sleep_score
        _to_num(row[3]),    # hrv
        _to_num(row[4]),    # hrv_7day
        _to_num(row[5]),    # resting_hr
        _to_num(row[6]),    # sleep_duration
        _to_num(row[7]),    # body_battery
        _to_num(row[8]),    # steps
        _to_num(row[9]),    # total_calories
        _to_num(row[10]),   # active_calories
        _to_num(row[11]),   # bmr_calories
        _to_num(row[12]),   # avg_stress
        _to_text(row[13]),  # stress_qualifier
        _to_num(row[14]),   # floors
        _to_num(row[15]),   # moderate_min
        _to_num(row[16]),   # vigorous_min
        _to_num(row[17]),   # bb_at_wake
        _to_num(row[18]),   # bb_high
        _to_num(row[19]),   # bb_low
        _to_text(row[20]),  # activity_name
        _to_text(row[21]),  # activity_type
        _to_text(row[22]),  # start_time
        _to_num(row[23]),   # distance
        _to_num(row[24]),   # duration
        _to_num(row[25]),   # avg_hr
        _to_num(row[26]),   # max_hr
        _to_num(row[27]),   # calories
        _to_num(row[28]),   # elevation
        _to_num(row[29]),   # avg_speed
        _to_num(row[30]),   # aerobic_te
        _to_num(row[31]),   # anaerobic_te
        _to_num(row[32]),   # zone_1
        _to_num(row[33]),   # zone_2
        _to_num(row[34]),   # zone_3
        _to_num(row[35]),   # zone_4
        _to_num(row[36]),   # zone_5
        _to_num(row[37]),   # spo2_avg
        _to_num(row[38]),   # spo2_min
    ))


def upsert_sleep_row(conn, row):
    """Upsert sleep table from a positional row list (25 columns, matching SLEEP_HEADERS)."""
    if len(row) < 25:
        row = row + [""] * (25 - len(row))
    conn.execute("""
        INSERT OR REPLACE INTO sleep (
            day, date, garmin_sleep_score, sleep_analysis_score, total_sleep_hrs,
            sleep_analysis, notes,
            bedtime, wake_time,
            bedtime_variability_7d, wake_variability_7d,
            time_in_bed_hrs,
            deep_sleep_min, light_sleep_min, rem_min, awake_during_sleep_min,
            deep_pct, rem_pct, sleep_cycles, awakenings,
            avg_hr, avg_respiration, overnight_hrv_ms,
            body_battery_gained, sleep_feedback
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        _to_text(row[0]),   # day
        _to_text(row[1]),   # date
        _to_num(row[2]),    # garmin_sleep_score
        _to_num(row[3]),    # sleep_analysis_score
        _to_num(row[4]),    # total_sleep_hrs
        _to_text(row[5]),   # sleep_analysis
        _to_text(row[6]),   # notes (manual)
        _to_text(row[7]),   # bedtime
        _to_text(row[8]),   # wake_time
        _to_num(row[9]),    # bedtime_variability_7d
        _to_num(row[10]),   # wake_variability_7d
        _to_num(row[11]),   # time_in_bed
        _to_num(row[12]),   # deep_sleep
        _to_num(row[13]),   # light_sleep
        _to_num(row[14]),   # rem
        _to_num(row[15]),   # awake
        _to_num(row[16]),   # deep_pct
        _to_num(row[17]),   # rem_pct
        _to_num(row[18]),   # sleep_cycles
        _to_num(row[19]),   # awakenings
        _to_num(row[20]),   # avg_hr
        _to_num(row[21]),   # avg_respiration
        _to_num(row[22]),   # overnight_hrv
        _to_num(row[23]),   # body_battery_gained
        _to_text(row[24]),  # sleep_feedback
    ))


def upsert_nutrition_row(conn, row):
    """Upsert nutrition table from a positional row list (16 columns, matching NUTRITION_HEADERS)."""
    if len(row) < 16:
        row = row + [""] * (16 - len(row))
    conn.execute("""
        INSERT OR REPLACE INTO nutrition (
            day, date, total_calories_burned, active_calories_burned, bmr_calories,
            breakfast, lunch, dinner, snacks, total_calories_consumed,
            protein_g, carbs_g, fats_g, water_l, calorie_balance, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        _to_text(row[0]),   # day
        _to_text(row[1]),   # date
        _to_num(row[2]),    # total_calories_burned
        _to_num(row[3]),    # active_calories_burned
        _to_num(row[4]),    # bmr_calories
        _to_text(row[5]),   # breakfast
        _to_text(row[6]),   # lunch
        _to_text(row[7]),   # dinner
        _to_text(row[8]),   # snacks
        _to_num(row[9]),    # total_calories_consumed
        _to_num(row[10]),   # protein
        _to_num(row[11]),   # carbs
        _to_num(row[12]),   # fats
        _to_num(row[13]),   # water
        _to_num(row[14]),   # calorie_balance
        _to_text(row[15]),  # notes
    ))


def upsert_session_log_row(conn, row):
    """Upsert session_log from a positional row list (22 columns, matching SESSION_LOG_HEADERS)."""
    if len(row) < 22:
        row = row + [""] * (22 - len(row))
    date_str = _to_text(row[1])
    activity_name = _to_text(row[6])
    if not date_str or not activity_name:
        return
    conn.execute("""
        INSERT OR REPLACE INTO session_log (
            day, date, session_type, perceived_effort, post_workout_energy,
            notes, activity_name, duration_min, distance_mi,
            avg_hr, max_hr, calories, aerobic_te, anaerobic_te,
            zone_1_min, zone_2_min, zone_3_min, zone_4_min, zone_5_min,
            zone_ranges, source, elevation_m
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        _to_text(row[0]),   # day
        date_str,           # date
        _to_text(row[2]),   # session_type
        _to_num(row[3]),    # perceived_effort
        _to_num(row[4]),    # post_workout_energy
        _to_text(row[5]),   # notes
        activity_name,      # activity_name
        _to_num(row[7]),    # duration
        _to_num(row[8]),    # distance
        _to_num(row[9]),    # avg_hr
        _to_num(row[10]),   # max_hr
        _to_num(row[11]),   # calories
        _to_num(row[12]),   # aerobic_te
        _to_num(row[13]),   # anaerobic_te
        _to_num(row[14]),   # zone_1
        _to_num(row[15]),   # zone_2
        _to_num(row[16]),   # zone_3
        _to_num(row[17]),   # zone_4
        _to_num(row[18]),   # zone_5
        _to_text(row[19]),  # zone_ranges
        _to_text(row[20]),  # source
        _to_num(row[21]),   # elevation
    ))


def upsert_daily_log_row(conn, row):
    """Upsert daily_log from a positional row list (22 columns, matching DAILY_LOG_HEADERS)."""
    if len(row) < 22:
        row = row + [""] * (22 - len(row))
    date_str = _to_text(row[1])
    if not date_str:
        return

    def _to_bool(val):
        if val is None or val == "":
            return None
        return 1 if str(val).upper() == "TRUE" else 0

    conn.execute("""
        INSERT OR REPLACE INTO daily_log (
            day, date, morning_energy,
            wake_at_930, no_morning_screens, creatine_hydrate,
            walk_breathing, physical_activity, no_screens_before_bed, bed_at_10pm,
            habits_total, midday_energy, midday_focus, midday_mood, midday_body_feel,
            midday_notes, evening_energy, evening_focus, evening_mood,
            perceived_stress, day_rating, evening_notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        _to_text(row[0]),   # day
        date_str,           # date
        _to_num(row[2]),    # morning_energy
        _to_bool(row[3]),   # wake_at_930
        _to_bool(row[4]),   # no_morning_screens
        _to_bool(row[5]),   # creatine_hydrate
        _to_bool(row[6]),   # walk_breathing
        _to_bool(row[7]),   # physical_activity
        _to_bool(row[8]),   # no_screens_before_bed
        _to_bool(row[9]),   # bed_at_10pm
        _to_num(row[10]),   # habits_total
        _to_num(row[11]),   # midday_energy
        _to_num(row[12]),   # midday_focus
        _to_num(row[13]),   # midday_mood
        _to_num(row[14]),   # midday_body_feel
        _to_text(row[15]),  # midday_notes
        _to_num(row[16]),   # evening_energy
        _to_num(row[17]),   # evening_focus
        _to_num(row[18]),   # evening_mood
        _to_num(row[19]),   # perceived_stress
        _to_num(row[20]),   # day_rating
        _to_text(row[21]),  # evening_notes
    ))


def upsert_strength_log_row(conn, row):
    """Insert strength_log row. Uses (date, exercise, weight, reps) as logical dedup."""
    if len(row) < 8:
        row = row + [""] * (8 - len(row))
    date_str = _to_text(row[1])
    exercise = _to_text(row[3])
    if not date_str or not exercise:
        return
    # Check for existing row to avoid duplicates
    existing = conn.execute(
        "SELECT id FROM strength_log WHERE date=? AND exercise=? AND weight_lbs=? AND reps=?",
        (date_str, exercise, _to_num(row[4]), _to_num(row[5]))
    ).fetchone()
    if existing:
        conn.execute("""
            UPDATE strength_log SET day=?, muscle_group=?, rpe=?, notes=?, updated_at=datetime('now')
            WHERE id=?
        """, (_to_text(row[0]), _to_text(row[2]), _to_num(row[6]), _to_text(row[7]), existing[0]))
    else:
        conn.execute("""
            INSERT INTO strength_log (day, date, muscle_group, exercise, weight_lbs, reps, rpe, notes)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            _to_text(row[0]), date_str, _to_text(row[2]), exercise,
            _to_num(row[4]), _to_num(row[5]), _to_num(row[6]), _to_text(row[7])
        ))


def upsert_overall_analysis_row(conn, row):
    """Upsert overall_analysis from a positional row list (14 columns, matching OVERALL_ANALYSIS_HEADERS)."""
    if len(row) < 14:
        row = row + [""] * (14 - len(row))
    date_str = _to_text(row[1])
    if not date_str:
        return
    conn.execute("""
        INSERT OR REPLACE INTO overall_analysis (
            day, date, readiness_score, readiness_label, confidence,
            cognitive_energy_assessment, sleep_context,
            cognition, cognition_notes,
            key_insights, recommendations, training_load_status,
            data_quality, quality_flags
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        _to_text(row[0]),   # day
        date_str,           # date
        _to_num(row[2]),    # readiness_score
        _to_text(row[3]),   # readiness_label
        _to_text(row[4]),   # confidence
        _to_text(row[5]),   # cognitive_energy_assessment
        _to_text(row[6]),   # sleep_context
        _to_num(row[7]),    # cognition (manual)
        _to_text(row[8]),   # cognition_notes (manual)
        _to_text(row[9]),   # key_insights
        _to_text(row[10]),  # recommendations
        _to_text(row[11]),  # training_load_status
        _to_text(row[12]),  # data_quality
        _to_text(row[13]),  # quality_flags
    ))


def upsert_archive_row(conn, row):
    """Insert into raw_data_archive from a positional row list. Write-once (INSERT OR IGNORE).

    Sheets row order: [Day(0), Date(1), ...ARCHIVE_KEYS]
    SQLite column order: [day, date, ...ARCHIVE_KEYS]
    """
    from schema import ARCHIVE_KEYS
    # Sheets: row[0]=Day, row[1]=Date — map to SQLite: day, date
    columns = ["day", "date"] + ARCHIVE_KEYS
    expected_len = len(columns)
    if len(row) < expected_len:
        row = row + [""] * (expected_len - len(row))
    values = [_to_text(row[i]) for i in range(expected_len)]
    col_names = ",".join(columns)
    placeholders = ",".join(["?"] * len(values))
    conn.execute(f"INSERT OR IGNORE INTO raw_data_archive ({col_names}) VALUES ({placeholders})", values)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _day_from_date(date_str):
    """Convert YYYY-MM-DD to 3-letter day abbreviation."""
    from datetime import date as _d
    try:
        d = _d.fromisoformat(str(date_str))
        return d.strftime("%a")
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Illness state — episode tracking + daily anomaly log
# ---------------------------------------------------------------------------

def get_active_illness(conn):
    """Return the active (unresolved) illness episode, or None."""
    cur = conn.execute(
        "SELECT id, onset_date, confirmed_date, resolved_date, "
        "resolution_method, peak_score, notes "
        "FROM illness_state WHERE resolved_date IS NULL "
        "ORDER BY onset_date DESC LIMIT 1"
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "onset_date": row[1], "confirmed_date": row[2],
        "resolved_date": row[3], "resolution_method": row[4],
        "peak_score": row[5], "notes": row[6],
    }


def start_illness_episode(conn, onset_date, initial_score=None):
    """Start a new illness episode. Returns the episode id."""
    cur = conn.execute(
        "INSERT INTO illness_state (onset_date, peak_score, created_at, updated_at) "
        "VALUES (?, ?, datetime('now'), datetime('now'))",
        (str(onset_date), initial_score)
    )
    conn.commit()
    return cur.lastrowid


def update_illness_peak(conn, episode_id, new_peak):
    """Update the peak anomaly score for an episode."""
    conn.execute(
        "UPDATE illness_state SET peak_score = ?, updated_at = datetime('now') "
        "WHERE id = ?", (new_peak, episode_id)
    )
    conn.commit()


def resolve_illness_episode(conn, episode_id, resolved_date, method):
    """Mark an illness episode as resolved.

    method: 'biometric' | 'user_confirmed'
    """
    conn.execute(
        "UPDATE illness_state SET resolved_date = ?, resolution_method = ?, "
        "updated_at = datetime('now') WHERE id = ?",
        (str(resolved_date), method, episode_id)
    )
    conn.commit()


def confirm_illness(conn, episode_id):
    """Record that the user confirmed they are sick."""
    conn.execute(
        "UPDATE illness_state SET confirmed_date = datetime('now'), "
        "updated_at = datetime('now') WHERE id = ?", (episode_id,)
    )
    conn.commit()


def upsert_illness_daily(conn, date_str, data):
    """Log daily illness anomaly score and signals."""
    import json
    signals_json = json.dumps(data.get("signals", []))
    conn.execute(
        "INSERT OR REPLACE INTO illness_daily_log "
        "(date, illness_state_id, anomaly_score, signals, label) "
        "VALUES (?, ?, ?, ?, ?)",
        (str(date_str), data.get("illness_state_id"),
         data.get("anomaly_score"), signals_json, data.get("label"))
    )
    conn.commit()


def get_recent_illness_scores(conn, target_date, days=5):
    """Fetch the last N daily illness scores BEFORE target_date (exclusive).

    Today's score hasn't been logged yet when recovery is checked,
    so we look at the N days ending at yesterday.
    Returns list of scores in chronological order (oldest first).
    """
    from datetime import timedelta
    end = str(target_date - timedelta(days=1))
    start = str(target_date - timedelta(days=days))
    cur = conn.execute(
        "SELECT anomaly_score FROM illness_daily_log "
        "WHERE date >= ? AND date <= ? ORDER BY date ASC",
        (start, end)
    )
    return [row[0] for row in cur.fetchall()]
