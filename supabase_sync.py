"""Supabase sync module for Health Tracker.

Mirrors sqlite_backup.py function signatures but writes to Supabase (PostgreSQL)
instead of local SQLite. All functions are wrapped in try/except so Supabase
failures never break the main Sheets + SQLite pipeline.

Requires SUPABASE_URL and SUPABASE_ANON_KEY in .env.
Install: pip install supabase
"""
import os
import traceback
from pathlib import Path

_client = None


# ---------------------------------------------------------------------------
# Helpers — same pattern as sqlite_backup.py
# ---------------------------------------------------------------------------

def _to_num(val):
    """Convert empty strings and non-numeric values to None for Supabase."""
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


def _day_from_date(date_str):
    """Convert YYYY-MM-DD to 3-letter day abbreviation."""
    from datetime import date as _d
    try:
        d = _d.fromisoformat(str(date_str))
        return d.strftime("%a")
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Client initialization
# ---------------------------------------------------------------------------

def init_supabase():
    """Load SUPABASE_URL and SUPABASE_ANON_KEY from .env, return a Supabase client.

    Returns None if credentials are missing or the supabase package is not installed.
    """
    global _client
    if _client is not None:
        return _client

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / ".env")

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_ANON_KEY")

        if not url or not key:
            print("[Supabase] SUPABASE_URL or SUPABASE_ANON_KEY not set in .env - skipping")
            return None

        from supabase import create_client
        _client = create_client(url, key)
        print("[Supabase] Client initialized")
        return _client
    except ImportError:
        print("[Supabase] supabase package not installed - run: pip install supabase")
        return None
    except Exception as e:
        print(f"[Supabase] Init failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Upsert functions — accept the same `data` dict used by Sheets/SQLite writes
# ---------------------------------------------------------------------------

def upsert_garmin(client, date_str, data):
    """Upsert one row into the garmin table from a Garmin data dict."""
    if client is None:
        return
    try:
        row = {
            "date": date_str,
            "day": _day_from_date(date_str),
            "sleep_score": _to_num(data.get("sleep_score")),
            "hrv_overnight_avg": _to_num(data.get("hrv")),
            "hrv_7day_avg": _to_num(data.get("hrv_7day")),
            "resting_hr": _to_num(data.get("resting_hr")),
            "sleep_duration_hrs": _to_num(data.get("sleep_duration")),
            "body_battery": _to_num(data.get("body_battery")),
            "steps": _to_num(data.get("steps")),
            "total_calories_burned": _to_num(data.get("total_calories")),
            "active_calories_burned": _to_num(data.get("active_calories")),
            "bmr_calories": _to_num(data.get("bmr_calories")),
            "avg_stress_level": _to_num(data.get("avg_stress")),
            "stress_qualifier": _to_text(data.get("stress_qualifier")),
            "floors_ascended": _to_num(data.get("floors_ascended")),
            "moderate_intensity_min": _to_num(data.get("moderate_min")),
            "vigorous_intensity_min": _to_num(data.get("vigorous_min")),
            "body_battery_at_wake": _to_num(data.get("bb_at_wake")),
            "body_battery_high": _to_num(data.get("bb_high")),
            "body_battery_low": _to_num(data.get("bb_low")),
            "activity_name": _to_text(data.get("activity_name")),
            "activity_type": _to_text(data.get("activity_type")),
            "start_time": _to_text(data.get("activity_start")),
            "distance_mi": _to_num(data.get("activity_distance")),
            "duration_min": _to_num(data.get("activity_duration")),
            "avg_hr": _to_num(data.get("activity_avg_hr")),
            "max_hr": _to_num(data.get("activity_max_hr")),
            "calories": _to_num(data.get("activity_calories")),
            "elevation_gain_m": _to_num(data.get("activity_elevation")),
            "avg_speed_mph": _to_num(data.get("activity_avg_speed")),
            "aerobic_training_effect": _to_num(data.get("aerobic_te")),
            "anaerobic_training_effect": _to_num(data.get("anaerobic_te")),
            "zone_1_min": _to_num(data.get("zone_1")),
            "zone_2_min": _to_num(data.get("zone_2")),
            "zone_3_min": _to_num(data.get("zone_3")),
            "zone_4_min": _to_num(data.get("zone_4")),
            "zone_5_min": _to_num(data.get("zone_5")),
        }
        client.table("garmin").upsert(row, on_conflict="date").execute()
        print(f"[Supabase] garmin upserted for {date_str}")
    except Exception as e:
        print(f"[Supabase] garmin upsert failed for {date_str}: {e}")


def upsert_sleep(client, date_str, data):
    """Upsert one row into the sleep table. Only writes if sleep data exists."""
    if client is None:
        return
    if not data.get("sleep_duration"):
        return
    try:
        row = {
            "date": date_str,
            "day": _day_from_date(date_str),
            "garmin_sleep_score": _to_num(data.get("sleep_score")),
            "total_sleep_hrs": _to_num(data.get("sleep_duration")),
            "bedtime": _to_text(data.get("sleep_bedtime")),
            "wake_time": _to_text(data.get("sleep_wake_time")),
            "time_in_bed_hrs": _to_num(data.get("sleep_time_in_bed")),
            "deep_sleep_min": _to_num(data.get("sleep_deep_min")),
            "light_sleep_min": _to_num(data.get("sleep_light_min")),
            "rem_min": _to_num(data.get("sleep_rem_min")),
            "awake_during_sleep_min": _to_num(data.get("sleep_awake_min")),
            "deep_pct": _to_num(data.get("sleep_deep_pct")),
            "rem_pct": _to_num(data.get("sleep_rem_pct")),
            "sleep_cycles": _to_num(data.get("sleep_cycles")),
            "awakenings": _to_num(data.get("sleep_awakenings")),
            "avg_hr": _to_num(data.get("sleep_avg_hr")),
            "avg_respiration": _to_num(data.get("sleep_avg_respiration")),
            "overnight_hrv_ms": _to_num(data.get("hrv")),
            "body_battery_gained": _to_num(data.get("sleep_body_battery_gained")),
            "sleep_feedback": _to_text(data.get("sleep_feedback")),
            "sleep_analysis_score": _to_num(data.get("sleep_analysis_score")),
            "sleep_analysis": _to_text(data.get("sleep_analysis_text")),
            "bedtime_variability_7d": _to_num(data.get("bedtime_variability_7d")),
            "wake_variability_7d": _to_num(data.get("wake_variability_7d")),
        }
        client.table("sleep").upsert(row, on_conflict="date").execute()
        print(f"[Supabase] sleep upserted for {date_str}")
    except Exception as e:
        print(f"[Supabase] sleep upsert failed for {date_str}: {e}")


def upsert_nutrition(client, date_str, data):
    """Upsert one row into the nutrition table. Only writes auto-populated columns."""
    if client is None:
        return
    try:
        row = {
            "date": date_str,
            "day": _day_from_date(date_str),
            "total_calories_burned": _to_num(data.get("total_calories")),
            "active_calories_burned": _to_num(data.get("active_calories")),
            "bmr_calories": _to_num(data.get("bmr_calories")),
        }
        client.table("nutrition").upsert(row, on_conflict="date").execute()
        print(f"[Supabase] nutrition upserted for {date_str}")
    except Exception as e:
        print(f"[Supabase] nutrition upsert failed for {date_str}: {e}")


def upsert_session_log(client, date_str, data):
    """Upsert one row into session_log. Skips if no activity."""
    if client is None:
        return
    activity_name = data.get("activity_name")
    if not activity_name:
        return
    try:
        # Determine session type (mirrors garmin_sync.py / sqlite_backup.py logic)
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

        row = {
            "date": date_str,
            "day": _day_from_date(date_str),
            "session_type": session_type,
            "activity_name": activity_name,
            "duration_min": _to_num(data.get("activity_duration")),
            "distance_mi": _to_num(data.get("activity_distance")),
            "avg_hr": _to_num(data.get("activity_avg_hr")),
            "max_hr": _to_num(data.get("activity_max_hr")),
            "calories": _to_num(data.get("activity_calories")),
            "aerobic_te": _to_num(data.get("aerobic_te")),
            "anaerobic_te": _to_num(data.get("anaerobic_te")),
            "zone_1_min": _to_num(data.get("zone_1")),
            "zone_2_min": _to_num(data.get("zone_2")),
            "zone_3_min": _to_num(data.get("zone_3")),
            "zone_4_min": _to_num(data.get("zone_4")),
            "zone_5_min": _to_num(data.get("zone_5")),
            "zone_ranges": _to_text(data.get("zone_ranges")),
            "source": "Garmin Auto",
            "elevation_m": _to_num(data.get("activity_elevation")),
        }
        # Composite primary key: (date, activity_name)
        client.table("session_log").upsert(row, on_conflict="date,activity_name").execute()
        print(f"[Supabase] session_log upserted for {date_str} - {activity_name}")
    except Exception as e:
        print(f"[Supabase] session_log upsert failed for {date_str}: {e}")


def upsert_overall_analysis(client, date_str, data):
    """Upsert one row into overall_analysis.

    Only includes non-null fields to prevent clobbering existing data with partial payloads.
    cognition and cognition_notes are manual-only (PWA writes) — always excluded.
    """
    if client is None:
        return
    try:
        row = {"date": date_str, "day": _day_from_date(date_str)}
        # Only include fields that have actual values — never overwrite with null
        _field_map = {
            "readiness_score": ("readiness_score", _to_num),
            "readiness_label": ("readiness_label", _to_text),
            "confidence": ("confidence", _to_text),
            "cognitive_energy_assessment": ("cognitive_energy_assessment", _to_text),
            "sleep_context": ("sleep_context", _to_text),
            "key_insights": ("key_insights", _to_text),
            "recommendations": ("recommendations", _to_text),
            "training_load_status": ("training_load_status", _to_text),
        }
        for data_key, (col_name, converter) in _field_map.items():
            val = data.get(data_key)
            if val is not None and val != "":
                row[col_name] = converter(val)
        client.table("overall_analysis").upsert(row, on_conflict="date").execute()
        print(f"[Supabase] overall_analysis upserted for {date_str}")
    except Exception as e:
        print(f"[Supabase] overall_analysis upsert failed for {date_str}: {e}")


def upsert_daily_log(client, date_str, data):
    """Upsert one row into daily_log."""
    if client is None:
        return
    try:
        row = {
            "date": date_str,
            "day": _day_from_date(date_str),
            "morning_energy": _to_num(data.get("morning_energy")),
            "wake_at_930": _to_num(data.get("wake_at_930")),
            "no_morning_screens": _to_num(data.get("no_morning_screens")),
            "creatine_hydrate": _to_num(data.get("creatine_hydrate")),
            "walk_breathing": _to_num(data.get("walk_breathing")),
            "physical_activity": _to_num(data.get("physical_activity")),
            "no_screens_before_bed": _to_num(data.get("no_screens_before_bed")),
            "bed_at_10pm": _to_num(data.get("bed_at_10pm")),
            "habits_total": _to_num(data.get("habits_total")),
            "midday_energy": _to_num(data.get("midday_energy")),
            "midday_focus": _to_num(data.get("midday_focus")),
            "midday_mood": _to_num(data.get("midday_mood")),
            "midday_body_feel": _to_num(data.get("midday_body_feel")),
            "midday_notes": _to_text(data.get("midday_notes")),
            "evening_energy": _to_num(data.get("evening_energy")),
            "evening_focus": _to_num(data.get("evening_focus")),
            "evening_mood": _to_num(data.get("evening_mood")),
            "perceived_stress": _to_num(data.get("perceived_stress")),
            "day_rating": _to_num(data.get("day_rating")),
            "evening_notes": _to_text(data.get("evening_notes")),
        }
        client.table("daily_log").upsert(row, on_conflict="date").execute()
        print(f"[Supabase] daily_log upserted for {date_str}")
    except Exception as e:
        print(f"[Supabase] daily_log upsert failed for {date_str}: {e}")


# ---------------------------------------------------------------------------
# Convenience — call all upserts in one shot
# ---------------------------------------------------------------------------

def sync_all(client, date_str, garmin_data, sleep_data, nutrition_data, sessions_data):
    """Call all upsert functions for a single date.

    Args:
        client: Supabase client from init_supabase()
        date_str: "YYYY-MM-DD"
        garmin_data: dict for upsert_garmin (Garmin wellness data)
        sleep_data: dict for upsert_sleep (same data dict — sleep fields extracted)
        nutrition_data: dict for upsert_nutrition (calorie fields)
        sessions_data: list of dicts for upsert_session_log (one per activity)
    """
    if client is None:
        return

    upsert_garmin(client, date_str, garmin_data)
    upsert_sleep(client, date_str, sleep_data)
    upsert_nutrition(client, date_str, nutrition_data)

    if sessions_data:
        if isinstance(sessions_data, dict):
            # Single session passed as dict
            upsert_session_log(client, date_str, sessions_data)
        else:
            # List of sessions
            for session in sessions_data:
                upsert_session_log(client, date_str, session)
