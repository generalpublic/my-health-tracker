"""Setup Supabase tables for Health Tracker.

Creates all tables matching the SQLite schema in sqlite_backup.py,
sets RLS policies for anonymous access, and optionally seeds data
from the local SQLite database.

Usage:
    python setup_supabase.py            # Create tables only
    python setup_supabase.py --seed     # Create tables + seed from SQLite
"""
import argparse
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SQLITE_DB = Path(__file__).parent / "health_tracker.db"

# Batch size for upserts
BATCH_SIZE = 500

# ---------------------------------------------------------------------------
# SQL: Table creation (idempotent — CREATE TABLE IF NOT EXISTS)
# ---------------------------------------------------------------------------

CREATE_TABLES_SQL = """
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
    spo2_avg REAL,
    spo2_min REAL,
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
"""

# ---------------------------------------------------------------------------
# SQL: RLS policies (allow anon read/write for personal app)
# ---------------------------------------------------------------------------

RLS_TABLES = [
    "garmin", "sleep", "overall_analysis", "daily_log",
    "session_log", "nutrition", "strength_log", "raw_data_archive", "_meta"
]

def _rls_sql():
    """Generate RLS enable + policy statements for all tables."""
    stmts = []
    for table in RLS_TABLES:
        stmts.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        # Drop existing policies first (idempotent)
        stmts.append(
            f"DROP POLICY IF EXISTS \"{table}_anon_select\" ON {table};"
        )
        stmts.append(
            f"DROP POLICY IF EXISTS \"{table}_anon_insert\" ON {table};"
        )
        stmts.append(
            f"DROP POLICY IF EXISTS \"{table}_anon_update\" ON {table};"
        )
        stmts.append(
            f"DROP POLICY IF EXISTS \"{table}_anon_delete\" ON {table};"
        )
        # Create permissive policies for anon role
        stmts.append(
            f"CREATE POLICY \"{table}_anon_select\" ON {table} FOR SELECT TO anon USING (true);"
        )
        stmts.append(
            f"CREATE POLICY \"{table}_anon_insert\" ON {table} FOR INSERT TO anon WITH CHECK (true);"
        )
        stmts.append(
            f"CREATE POLICY \"{table}_anon_update\" ON {table} FOR UPDATE TO anon USING (true) WITH CHECK (true);"
        )
        stmts.append(
            f"CREATE POLICY \"{table}_anon_delete\" ON {table} FOR DELETE TO anon USING (true);"
        )
    return "\n".join(stmts)


# ---------------------------------------------------------------------------
# Supabase connection
# ---------------------------------------------------------------------------

def get_supabase():
    """Create and return a Supabase client."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
        print("Add these lines to your .env file:")
        print("  SUPABASE_URL=https://your-project.supabase.co")
        print("  SUPABASE_ANON_KEY=your-anon-key")
        sys.exit(1)

    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# ---------------------------------------------------------------------------
# Table creation via Supabase SQL (uses the rpc endpoint or REST)
# ---------------------------------------------------------------------------

def create_tables(supabase):
    """Create all tables using Supabase's SQL execution."""
    print("Creating tables...")

    # Execute table creation SQL
    # Supabase requires using the postgrest or management API.
    # The cleanest approach: use supabase.rpc() with a raw SQL function,
    # or use the REST SQL endpoint directly via httpx.
    full_sql = CREATE_TABLES_SQL + "\n" + _rls_sql()

    # Use the Supabase management SQL endpoint
    import httpx

    # Extract project ref from URL (https://xxx.supabase.co -> xxx)
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }

    # Try using the pg_net / SQL API via rpc
    # Supabase exposes raw SQL via the /rest/v1/rpc endpoint if you create
    # a function, or via the /pg/ endpoint on the management API.
    # The simplest approach: use the service_role key with the SQL endpoint.

    # Method: Execute SQL via Supabase's built-in `query` rpc or the
    # management API. Since we have the anon key, we'll try creating
    # a temporary function first.

    # Actually, the most reliable way is using the Supabase SQL editor API
    # which requires the service role key, or we can use psycopg2 directly
    # via the connection string.

    # Let's try the supabase-py approach first: execute via rpc
    # If that fails, fall back to direct PostgreSQL connection.

    # Attempt 1: Use the Supabase REST SQL endpoint
    sql_url = f"{SUPABASE_URL}/rest/v1/rpc/exec_sql"
    try:
        resp = httpx.post(sql_url, json={"query": full_sql}, headers=headers, timeout=30)
        if resp.status_code == 200:
            print("  Tables created via rpc/exec_sql")
            return True
        # If the function doesn't exist, fall through
    except Exception:
        pass

    # Attempt 2: Direct PostgreSQL connection
    # Supabase provides a direct connection string
    db_url = os.getenv("SUPABASE_DB_URL")
    if db_url:
        try:
            import psycopg2
            conn = psycopg2.connect(db_url)
            conn.autocommit = True
            cur = conn.cursor()
            # Execute each statement separately for better error handling
            for statement in _split_sql_statements(full_sql):
                statement = statement.strip()
                if statement:
                    try:
                        cur.execute(statement)
                    except Exception as e:
                        # Skip "already exists" errors for idempotency
                        err_msg = str(e).lower()
                        if "already exists" in err_msg or "duplicate" in err_msg:
                            conn.rollback() if not conn.autocommit else None
                            continue
                        print(f"  WARNING: {e}")
                        conn.rollback() if not conn.autocommit else None
            cur.close()
            conn.close()
            print("  Tables created via direct PostgreSQL connection")
            return True
        except ImportError:
            print("  psycopg2 not installed. Install with: pip install psycopg2-binary")
        except Exception as e:
            print(f"  Direct connection failed: {e}")

    # Attempt 3: Use Supabase Management API (requires service_role key)
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if service_key:
        mgmt_headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        sql_url = f"{SUPABASE_URL}/rest/v1/rpc/exec_sql"
        try:
            resp = httpx.post(sql_url, json={"query": full_sql}, headers=mgmt_headers, timeout=30)
            if resp.status_code == 200:
                print("  Tables created via service_role rpc")
                return True
        except Exception:
            pass

    # If none of the above worked, print SQL for manual execution
    print("\n" + "=" * 70)
    print("MANUAL SETUP REQUIRED")
    print("=" * 70)
    print()
    print("Could not auto-execute SQL. Please run the following SQL in your")
    print("Supabase dashboard (SQL Editor -> New Query -> paste and run):")
    print()
    print("Add one of these to your .env for automatic setup:")
    print("  SUPABASE_DB_URL=postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres")
    print("  SUPABASE_SERVICE_ROLE_KEY=your-service-role-key")
    print()
    print("Or paste this SQL into the Supabase SQL Editor:")
    print("-" * 70)
    print(full_sql)
    print("-" * 70)

    # Write SQL to file for convenience
    sql_file = Path(__file__).parent / "supabase_schema.sql"
    sql_file.write_text(full_sql, encoding="utf-8")
    print(f"\nSQL also saved to: {sql_file}")
    return False


def _split_sql_statements(sql):
    """Split SQL into individual statements, respecting semicolons."""
    statements = []
    current = []
    for line in sql.split("\n"):
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current))
            current = []
    if current:
        stmt = "\n".join(current).strip()
        if stmt:
            statements.append(stmt)
    return statements


# ---------------------------------------------------------------------------
# Seed: copy data from SQLite to Supabase
# ---------------------------------------------------------------------------

# Column definitions for each table (used for SQLite reads and Supabase upserts)
TABLE_CONFIGS = {
    "garmin": {
        "pk": ["date"],
        "columns": [
            "date", "day", "sleep_score", "hrv_overnight_avg", "hrv_7day_avg",
            "resting_hr", "sleep_duration_hrs", "body_battery", "steps",
            "total_calories_burned", "active_calories_burned", "bmr_calories",
            "avg_stress_level", "stress_qualifier", "floors_ascended",
            "moderate_intensity_min", "vigorous_intensity_min",
            "body_battery_at_wake", "body_battery_high", "body_battery_low",
            "activity_name", "activity_type", "start_time", "distance_mi",
            "duration_min", "avg_hr", "max_hr", "calories", "elevation_gain_m",
            "avg_speed_mph", "aerobic_training_effect", "anaerobic_training_effect",
            "zone_1_min", "zone_2_min", "zone_3_min", "zone_4_min", "zone_5_min",
            "updated_at",
        ],
    },
    "sleep": {
        "pk": ["date"],
        "columns": [
            "date", "day", "garmin_sleep_score", "sleep_analysis_score",
            "total_sleep_hrs", "sleep_analysis", "notes", "bedtime", "wake_time",
            "time_in_bed_hrs", "deep_sleep_min", "light_sleep_min", "rem_min",
            "awake_during_sleep_min", "deep_pct", "rem_pct", "sleep_cycles",
            "awakenings", "avg_hr", "avg_respiration", "overnight_hrv_ms",
            "body_battery_gained", "sleep_feedback",
            "bedtime_variability_7d", "wake_variability_7d", "updated_at",
        ],
    },
    "overall_analysis": {
        "pk": ["date"],
        "columns": [
            "date", "day", "readiness_score", "readiness_label", "confidence",
            "cognitive_energy_assessment", "sleep_context", "cognition",
            "cognition_notes", "key_insights", "recommendations",
            "training_load_status", "updated_at",
        ],
    },
    "daily_log": {
        "pk": ["date"],
        "columns": [
            "date", "day", "morning_energy", "wake_at_930", "no_morning_screens",
            "creatine_hydrate", "walk_breathing", "physical_activity",
            "no_screens_before_bed", "bed_at_10pm", "habits_total",
            "midday_energy", "midday_focus", "midday_mood", "midday_body_feel",
            "midday_notes", "evening_energy", "evening_focus", "evening_mood",
            "perceived_stress", "day_rating", "evening_notes", "updated_at",
        ],
    },
    "session_log": {
        "pk": ["date", "activity_name"],
        "columns": [
            "date", "activity_name", "day", "session_type", "perceived_effort",
            "post_workout_energy", "notes", "duration_min", "distance_mi",
            "avg_hr", "max_hr", "calories", "aerobic_te", "anaerobic_te",
            "zone_1_min", "zone_2_min", "zone_3_min", "zone_4_min", "zone_5_min",
            "zone_ranges", "source", "elevation_m", "updated_at",
        ],
    },
    "nutrition": {
        "pk": ["date"],
        "columns": [
            "date", "day", "total_calories_burned", "active_calories_burned",
            "bmr_calories", "breakfast", "lunch", "dinner", "snacks",
            "total_calories_consumed", "protein_g", "carbs_g", "fats_g",
            "water_l", "calorie_balance", "notes", "updated_at",
        ],
    },
    "strength_log": {
        "pk": None,  # Auto-increment ID, no natural upsert key
        "columns": [
            "date", "day", "muscle_group", "exercise", "weight_lbs",
            "reps", "rpe", "notes", "updated_at",
        ],
        "sqlite_select_extra": "id",  # Read ID from SQLite for dedup
    },
    "raw_data_archive": {
        "pk": ["date"],
        "columns": [
            "date", "day",
            "hrv", "hrv_7day", "resting_hr", "body_battery", "steps",
            "total_calories", "active_calories", "bmr_calories",
            "avg_stress", "stress_qualifier", "floors_ascended",
            "moderate_min", "vigorous_min",
            "bb_at_wake", "bb_high", "bb_low",
            "sleep_duration", "sleep_score", "sleep_bedtime", "sleep_wake_time",
            "sleep_time_in_bed", "sleep_deep_min", "sleep_light_min", "sleep_rem_min",
            "sleep_awake_min", "sleep_deep_pct", "sleep_rem_pct", "sleep_cycles",
            "sleep_awakenings", "sleep_avg_hr", "sleep_avg_respiration",
            "sleep_body_battery_gained", "sleep_feedback",
            "activity_name", "activity_type", "activity_start",
            "activity_distance", "activity_duration", "activity_avg_hr",
            "activity_max_hr", "activity_calories", "activity_elevation",
            "activity_avg_speed", "aerobic_te", "anaerobic_te",
            "zone_1", "zone_2", "zone_3", "zone_4", "zone_5",
            "created_at",
        ],
    },
}


def _clean_numeric(val, is_integer=False):
    """Clean a value destined for a REAL/INTEGER column in PostgreSQL.

    Handles: comma-formatted numbers ("1,873" -> 1873), text in numeric
    columns ("Moderately Hard" -> None), empty strings -> None.
    Truncates floats to int when is_integer=True (e.g., 5074.0 -> 5074).
    """
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return int(val) if is_integer else val
    if isinstance(val, str):
        # Strip commas from formatted numbers
        cleaned = val.replace(",", "").strip()
        try:
            num = float(cleaned)
            return int(num) if is_integer else num
        except (ValueError, TypeError):
            # Text value in a numeric column — discard
            return None
    return val


# Columns declared as REAL or INTEGER in each table's CREATE TABLE
_NUMERIC_COLS = {
    "garmin": {
        "sleep_score", "hrv_overnight_avg", "hrv_7day_avg", "resting_hr",
        "sleep_duration_hrs", "body_battery", "steps", "total_calories_burned",
        "active_calories_burned", "bmr_calories", "avg_stress_level",
        "floors_ascended", "moderate_intensity_min", "vigorous_intensity_min",
        "body_battery_at_wake", "body_battery_high", "body_battery_low",
        "distance_mi", "duration_min", "avg_hr", "max_hr", "calories",
        "elevation_gain_m", "avg_speed_mph", "aerobic_training_effect",
        "anaerobic_training_effect", "zone_1_min", "zone_2_min", "zone_3_min",
        "zone_4_min", "zone_5_min",
    },
    "sleep": {
        "garmin_sleep_score", "sleep_analysis_score", "total_sleep_hrs",
        "time_in_bed_hrs", "deep_sleep_min", "light_sleep_min", "rem_min",
        "awake_during_sleep_min", "deep_pct", "rem_pct", "sleep_cycles",
        "awakenings", "avg_hr", "avg_respiration", "overnight_hrv_ms",
        "body_battery_gained", "bedtime_variability_7d", "wake_variability_7d",
    },
    "session_log": {
        "perceived_effort", "post_workout_energy", "duration_min", "distance_mi",
        "avg_hr", "max_hr", "calories", "aerobic_te", "anaerobic_te",
        "zone_1_min", "zone_2_min", "zone_3_min", "zone_4_min", "zone_5_min",
        "elevation_m",
    },
    "nutrition": {
        "total_calories_burned", "active_calories_burned", "bmr_calories",
        "total_calories_consumed", "protein_g", "carbs_g", "fats_g",
        "water_l", "calorie_balance",
    },
    "overall_analysis": {"readiness_score", "cognition"},
    "daily_log": {
        "morning_energy", "wake_at_930", "no_morning_screens", "creatine_hydrate",
        "walk_breathing", "physical_activity", "no_screens_before_bed",
        "bed_at_10pm", "habits_total", "midday_energy", "midday_focus",
        "midday_mood", "midday_body_feel", "evening_energy", "evening_focus",
        "evening_mood", "perceived_stress", "day_rating",
    },
    "strength_log": {"weight_lbs", "reps", "rpe"},
}

# Columns declared as INTEGER (not REAL) — need int() conversion
_INTEGER_COLS = {
    "garmin": {"steps", "floors_ascended"},
    "sleep": {"sleep_cycles", "awakenings"},
    "daily_log": {
        "wake_at_930", "no_morning_screens", "creatine_hydrate",
        "walk_breathing", "physical_activity", "no_screens_before_bed",
        "bed_at_10pm", "habits_total",
    },
    "strength_log": {"reps"},
}


def seed_from_sqlite(supabase):
    """Copy all data from local SQLite database to Supabase."""
    if not SQLITE_DB.exists():
        print(f"ERROR: SQLite database not found at {SQLITE_DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row

    total_rows = 0

    for table_name, config in TABLE_CONFIGS.items():
        columns = config["columns"]
        pk = config["pk"]
        numeric_cols = _NUMERIC_COLS.get(table_name, set())
        integer_cols = _INTEGER_COLS.get(table_name, set())

        # Read all rows from SQLite
        col_list = ", ".join(columns)
        try:
            cursor = conn.execute(f"SELECT {col_list} FROM {table_name}")
        except sqlite3.OperationalError as e:
            print(f"  [{table_name}] SKIP - table not found in SQLite: {e}")
            continue

        rows = cursor.fetchall()
        if not rows:
            print(f"  [{table_name}] 0 rows (empty)")
            continue

        # Convert rows to list of dicts
        records = []
        for row in rows:
            record = {}
            for i, col in enumerate(columns):
                val = row[i]
                # Convert empty strings to None for Supabase/PostgreSQL
                if val == "":
                    val = None
                # Clean numeric columns (strip commas, discard text)
                if col in numeric_cols:
                    val = _clean_numeric(val, is_integer=(col in integer_cols))
                record[col] = val
            records.append(record)

        # Batch upsert into Supabase
        row_count = len(records)
        print(f"  [{table_name}] Seeding {row_count} rows...", end=" ", flush=True)

        try:
            if table_name == "strength_log":
                # strength_log uses auto-increment ID - delete and re-insert
                # to avoid ID conflicts between SQLite and Supabase
                supabase.table(table_name).delete().neq("date", "___never___").execute()
                for i in range(0, len(records), BATCH_SIZE):
                    batch = records[i:i + BATCH_SIZE]
                    supabase.table(table_name).insert(batch).execute()
            elif pk:
                # Upsert using primary key
                pk_str = ",".join(pk)
                for i in range(0, len(records), BATCH_SIZE):
                    batch = records[i:i + BATCH_SIZE]
                    supabase.table(table_name).upsert(
                        batch, on_conflict=pk_str
                    ).execute()
            else:
                # Insert without conflict resolution
                for i in range(0, len(records), BATCH_SIZE):
                    batch = records[i:i + BATCH_SIZE]
                    supabase.table(table_name).insert(batch).execute()

            print(f"OK ({row_count} rows)")
            total_rows += row_count
        except Exception as e:
            print(f"FAILED: {e}")

    conn.close()
    print(f"\nSeed complete: {total_rows} total rows across {len(TABLE_CONFIGS)} tables")


# ---------------------------------------------------------------------------
# Verify: check that tables exist and have data
# ---------------------------------------------------------------------------

def verify_tables(supabase):
    """Verify all tables exist and report row counts."""
    print("\nVerifying tables...")
    all_ok = True
    for table_name in TABLE_CONFIGS:
        try:
            result = supabase.table(table_name).select("*", count="exact").limit(0).execute()
            count = result.count if result.count is not None else "?"
            print(f"  [{table_name}] OK - {count} rows")
        except Exception as e:
            print(f"  [{table_name}] FAIL - {e}")
            all_ok = False

    # Also check _meta
    try:
        result = supabase.table("_meta").select("*", count="exact").limit(0).execute()
        count = result.count if result.count is not None else "?"
        print(f"  [_meta] OK - {count} rows")
    except Exception as e:
        print(f"  [_meta] FAIL - {e}")
        all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Setup Supabase tables for Health Tracker")
    parser.add_argument("--seed", action="store_true",
                        help="Seed data from local SQLite database")
    parser.add_argument("--verify", action="store_true",
                        help="Verify tables exist and show row counts")
    parser.add_argument("--sql-only", action="store_true",
                        help="Print SQL to stdout without executing")
    args = parser.parse_args()

    if args.sql_only:
        full_sql = CREATE_TABLES_SQL + "\n" + _rls_sql()
        print(full_sql)
        return

    print("=" * 50)
    print("Health Tracker - Supabase Setup")
    print("=" * 50)
    print()

    supabase = get_supabase()

    # Step 1: Create tables (skip if --seed or --verify — tables already exist)
    if not args.seed and not args.verify:
        success = create_tables(supabase)
        if not success:
            print("\nTable creation requires manual SQL execution.")
            print("After running the SQL, re-run this script with --seed to populate data.")
            return

    # Step 2: Set schema version
    try:
        supabase.table("_meta").upsert({
            "key": "schema_version",
            "value": "1",
        }, on_conflict="key").execute()
        print("  Schema version set to 1")
    except Exception as e:
        print(f"  WARNING: Could not set schema version: {e}")

    # Step 3: Seed from SQLite (if requested)
    if args.seed:
        print()
        seed_from_sqlite(supabase)

    # Step 4: Verify
    if args.verify or args.seed:
        verify_tables(supabase)

    print("\nDone.")


if __name__ == "__main__":
    main()
