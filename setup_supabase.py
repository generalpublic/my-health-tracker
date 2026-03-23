"""Setup Supabase tables for Health Tracker.

Creates all tables using supabase_schema.sql as the single source of truth,
sets RLS policies for authenticated access, and optionally seeds data
from the local SQLite database.

Usage:
    python setup_supabase.py            # Create tables only
    python setup_supabase.py --seed     # Create tables + seed from SQLite
"""
import argparse
import re
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

# Schema version — single source of truth.
# Update here when migrations change the schema. Must match supabase_schema.sql header.
SCHEMA_VERSION = "3.2"

# ---------------------------------------------------------------------------
# SQL: Table creation — read from supabase_schema.sql (canonical source)
# ---------------------------------------------------------------------------

_SCHEMA_SQL_FILE = Path(__file__).parent / "supabase_schema.sql"


def _load_ddl_from_schema_file():
    """Read CREATE TABLE / INDEX / constraint DDL from supabase_schema.sql.

    Extracts only the DDL portion (stops before the RLS policy section,
    which is generated dynamically by _rls_sql()).
    """
    if not _SCHEMA_SQL_FILE.exists():
        print(f"ERROR: Schema file not found: {_SCHEMA_SQL_FILE}")
        print("Expected supabase_schema.sql in the project root.")
        sys.exit(1)

    sql = _SCHEMA_SQL_FILE.read_text(encoding="utf-8")

    # The RLS section starts with a long ====== comment block containing "RLS Policies"
    rls_marker = re.search(r'^-- =+\n-- RLS Policies', sql, re.MULTILINE)
    if rls_marker:
        sql = sql[:rls_marker.start()]

    return sql.strip()


# Legacy constant — kept as a lazy-loaded reference for backward compatibility.
# All callers now use _load_ddl_from_schema_file() instead.
# ---------------------------------------------------------------------------
# SQL: RLS policies (generated dynamically, not read from schema file)
# ---------------------------------------------------------------------------

RLS_TABLES = [
    "garmin", "sleep", "overall_analysis", "daily_log",
    "session_log", "nutrition", "strength_log", "raw_data_archive", "_meta",
    "illness_state", "illness_daily_log",
]

# Per-table access levels for least-privilege RLS
# "rw"       = SELECT + INSERT + UPDATE (browser writable)
# "insert"   = SELECT + INSERT (browser insert-only)
# "ro"       = SELECT only (browser read-only)
# "none"     = no browser policies (server-only via service_role)
_TABLE_ACCESS = {
    "daily_log": "rw",
    "nutrition": "rw",
    "session_log": "rw",
    "sleep": "rw",
    "overall_analysis": "rw",
    "strength_log": "insert",
    "garmin": "ro",
    "illness_state": "ro",
    "illness_daily_log": "ro",
    "raw_data_archive": "none",
    "_meta": "none",
}


def _rls_sql():
    """Generate RLS enable + per-table least-privilege policies scoped to auth.uid()."""
    stmts = []
    for table in RLS_TABLES:
        access = _TABLE_ACCESS.get(table, "none")
        stmts.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")

        # Drop ALL old policy names (anon, authenticated, owner) for idempotency
        for suffix in ["anon_select", "anon_insert", "anon_update", "anon_delete",
                        "authenticated_all", "owner_select", "owner_insert", "owner_update"]:
            stmts.append(f"DROP POLICY IF EXISTS \"{table}_{suffix}\" ON {table};")

        if access == "none":
            # Server-only: no browser policies. service_role bypasses RLS.
            stmts.append(f"-- {table}: server-only (no authenticated policies)")
        elif access == "ro":
            stmts.append(
                f"CREATE POLICY \"{table}_owner_select\" ON {table} "
                f"FOR SELECT TO authenticated USING (user_id = auth.uid());"
            )
        elif access == "insert":
            stmts.append(
                f"CREATE POLICY \"{table}_owner_select\" ON {table} "
                f"FOR SELECT TO authenticated USING (user_id = auth.uid());"
            )
            stmts.append(
                f"CREATE POLICY \"{table}_owner_insert\" ON {table} "
                f"FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());"
            )
        elif access == "rw":
            stmts.append(
                f"CREATE POLICY \"{table}_owner_select\" ON {table} "
                f"FOR SELECT TO authenticated USING (user_id = auth.uid());"
            )
            stmts.append(
                f"CREATE POLICY \"{table}_owner_insert\" ON {table} "
                f"FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());"
            )
            stmts.append(
                f"CREATE POLICY \"{table}_owner_update\" ON {table} "
                f"FOR UPDATE TO authenticated "
                f"USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());"
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
    full_sql = _load_ddl_from_schema_file() + "\n" + _rls_sql()

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
        "pk": ["user_id", "date"],
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
            "spo2_avg", "spo2_min",
            "updated_at",
        ],
    },
    "sleep": {
        "pk": ["user_id", "date"],
        "columns": [
            "date", "day", "garmin_sleep_score", "sleep_analysis_score",
            "total_sleep_hrs", "sleep_analysis", "notes", "bedtime", "wake_time",
            "time_in_bed_hrs", "deep_sleep_min", "light_sleep_min", "rem_min",
            "awake_during_sleep_min", "deep_pct", "rem_pct", "sleep_cycles",
            "awakenings", "avg_hr", "avg_respiration", "overnight_hrv_ms",
            "body_battery_gained", "sleep_feedback",
            "bedtime_variability_7d", "wake_variability_7d", "manual_source", "updated_at",
        ],
    },
    "overall_analysis": {
        "pk": ["user_id", "date"],
        "columns": [
            "date", "day", "readiness_score", "readiness_label", "confidence",
            "cognitive_energy_assessment", "sleep_context", "cognition",
            "cognition_notes", "key_insights", "recommendations",
            "training_load_status", "manual_source", "updated_at",
        ],
    },
    "daily_log": {
        "pk": ["user_id", "date"],
        "columns": [
            "date", "day", "morning_energy", "wake_at_930", "no_morning_screens",
            "creatine_hydrate", "walk_breathing", "physical_activity",
            "no_screens_before_bed", "bed_at_10pm", "habits_total",
            "midday_energy", "midday_focus", "midday_mood", "midday_body_feel",
            "midday_notes", "evening_energy", "evening_focus", "evening_mood",
            "perceived_stress", "day_rating", "evening_notes", "manual_source", "updated_at",
        ],
    },
    "session_log": {
        "pk": ["user_id", "date", "activity_name"],
        "columns": [
            "date", "activity_name", "day", "session_type", "perceived_effort",
            "post_workout_energy", "notes", "duration_min", "distance_mi",
            "avg_hr", "max_hr", "calories", "aerobic_te", "anaerobic_te",
            "zone_1_min", "zone_2_min", "zone_3_min", "zone_4_min", "zone_5_min",
            "zone_ranges", "source", "elevation_m", "manual_source", "updated_at",
        ],
    },
    "nutrition": {
        "pk": ["user_id", "date"],
        "columns": [
            "date", "day", "total_calories_burned", "active_calories_burned",
            "bmr_calories", "breakfast", "lunch", "dinner", "snacks",
            "total_calories_consumed", "protein_g", "carbs_g", "fats_g",
            "water_l", "calorie_balance", "notes", "manual_source", "updated_at",
        ],
    },
    "strength_log": {
        "pk": ["user_id", "set_id"],
        "columns": [
            "date", "day", "muscle_group", "exercise", "set_id",
            "weight_lbs", "reps", "rpe", "notes", "manual_source", "updated_at",
        ],
        "sqlite_select_extra": "id",  # Read ID from SQLite for dedup
    },
    "raw_data_archive": {
        "pk": ["user_id", "date"],
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
        "zone_4_min", "zone_5_min", "spo2_avg", "spo2_min",
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
    owner_uuid = os.environ.get("SUPABASE_OWNER_UUID")
    if not owner_uuid:
        print("ERROR: SUPABASE_OWNER_UUID not set in .env — required for seeding.")
        print("  Get it from: Supabase Dashboard -> Auth -> Users -> your UUID")
        sys.exit(1)

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

        # Inject user_id for all data tables (not _meta)
        if table_name != "_meta":
            for record in records:
                record["user_id"] = owner_uuid

        # Batch upsert into Supabase
        row_count = len(records)
        print(f"  [{table_name}] Seeding {row_count} rows...", end=" ", flush=True)

        try:
            if table_name == "strength_log":
                # strength_log uses set_id for dedup — upsert on (user_id, set_id)
                # Generate set_id for legacy rows that don't have one
                for rec in records:
                    if not rec.get("set_id"):
                        import uuid
                        rec["set_id"] = str(uuid.uuid4())
                conflict_cols = "user_id,set_id"
                for i in range(0, len(records), BATCH_SIZE):
                    batch = records[i:i + BATCH_SIZE]
                    supabase.table(table_name).upsert(
                        batch, on_conflict=conflict_cols
                    ).execute()
            elif pk:
                # Upsert using composite PK (user_id already in pk list)
                conflict_cols = ",".join(pk)
                for i in range(0, len(records), BATCH_SIZE):
                    batch = records[i:i + BATCH_SIZE]
                    supabase.table(table_name).upsert(
                        batch, on_conflict=conflict_cols
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

_VERIFY_TABLES = list(TABLE_CONFIGS.keys()) + ["_meta", "illness_state", "illness_daily_log"]


def verify_tables(supabase):
    """Verify all tables exist and report row counts."""
    print("\nVerifying tables...")
    all_ok = True
    for table_name in _VERIFY_TABLES:
        try:
            result = supabase.table(table_name).select("*", count="exact").limit(0).execute()
            count = result.count if result.count is not None else "?"
            print(f"  [{table_name}] OK - {count} rows")
        except Exception as e:
            print(f"  [{table_name}] FAIL - {e}")
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
        full_sql = _load_ddl_from_schema_file() + "\n" + _rls_sql()
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
            "value": SCHEMA_VERSION,
        }, on_conflict="key").execute()
        print(f"  Schema version set to {SCHEMA_VERSION}")
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
