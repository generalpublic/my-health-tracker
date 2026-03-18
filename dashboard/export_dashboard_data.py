"""Export SQLite health data to JSON for the calendar dashboard."""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "health_tracker.db"
JSON_PATH = Path(__file__).parent / "dashboard_data.json"
TEMPLATE_PATH = Path(__file__).parent / "dashboard_template.html"
OUTPUT_PATH = Path(__file__).parent / "dashboard.html"

# Load dashboard metrics from centralized thresholds.json
_THRESHOLDS_PATH = Path(__file__).parent.parent / "thresholds.json"
try:
    with open(_THRESHOLDS_PATH) as _f:
        METRICS = json.load(_f)["dashboard_metrics"]
except (FileNotFoundError, json.JSONDecodeError, KeyError):
    # Fallback: hardcoded metrics if thresholds.json missing
    METRICS = {
        "sleep_analysis_score": {
        "label": "Sleep Score (Analysis)",
        "type": "higher_better",
        "red": 65, "yellow": 70, "green": 85,
        "source": "sleep"
    },
    "total_sleep_hrs": {
        "label": "Sleep Duration",
        "type": "higher_better",
        "red": 5, "yellow": 7, "green": 8,
        "unit": "hrs",
        "source": "sleep"
    },
    "overnight_hrv_ms": {
        "label": "HRV (Overnight)",
        "type": "higher_better",
        "red": 30, "yellow": 40, "green": 48,
        "unit": "ms",
        "source": "sleep"
    },
    "bedtime": {
        "label": "Bedtime",
        "type": "time_earlier_better",
        "green": "22:00", "yellow": "23:30", "red": "01:30",
        "source": "sleep"
    },
    "deep_pct": {
        "label": "Deep Sleep %",
        "type": "higher_better",
        "red": 12, "yellow": 18, "green": 22,
        "unit": "%",
        "source": "sleep"
    },
    "rem_pct": {
        "label": "REM Sleep %",
        "type": "higher_better",
        "red": 12, "yellow": 18, "green": 22,
        "unit": "%",
        "source": "sleep"
    },
    "resting_hr": {
        "label": "Resting HR",
        "type": "lower_better",
        "green": 48, "yellow": 55, "red": 65,
        "unit": "bpm",
        "source": "garmin"
    },
    "body_battery": {
        "label": "Body Battery",
        "type": "higher_better",
        "red": 20, "yellow": 50, "green": 80,
        "source": "garmin"
    },
    "body_battery_gained": {
        "label": "Body Battery Gained (Sleep)",
        "type": "higher_better",
        "red": 15, "yellow": 40, "green": 65,
        "source": "sleep"
    },
    "steps": {
        "label": "Steps",
        "type": "higher_better",
        "red": 3000, "yellow": 7000, "green": 10000,
        "source": "garmin"
    },
    "avg_stress_level": {
        "label": "Stress Level",
        "type": "lower_better",
        "green": 15, "yellow": 30, "red": 50,
        "source": "garmin"
    },
    "habits_total": {
        "label": "Habits Completed (0-7)",
        "type": "higher_better",
        "red": 2, "yellow": 4, "green": 6,
        "source": "daily_log"
    },
    "day_rating": {
        "label": "Day Rating",
        "type": "higher_better",
        "red": 3, "yellow": 5, "green": 8,
        "source": "daily_log"
    },
    "morning_energy": {
        "label": "Morning Energy",
        "type": "higher_better",
        "red": 3, "yellow": 5, "green": 8,
        "source": "daily_log"
    },
}


def bedtime_to_minutes(bedtime_str):
    """Convert bedtime string to minutes-from-6pm for sorting.

    Earlier bedtimes = lower values = better.
    6pm = 0, 10pm = 240, midnight = 360, 2am = 480.
    """
    if not bedtime_str:
        return None
    try:
        parts = bedtime_str.split(":")
        h, m = int(parts[0]), int(parts[1])
        # Shift so 18:00 (6pm) = 0, values increase as bedtime gets later
        minutes = h * 60 + m
        if minutes < 360:  # Before 6am = very late (previous night)
            minutes += 1440  # Add 24 hours so 1am = 1500, 2am = 1560
        return minutes - 1080  # 18:00 = 0
    except (ValueError, IndexError):
        return None


def normalize_date(date_str):
    """Ensure date is in YYYY-MM-DD format."""
    if not date_str:
        return None
    if len(date_str) == 10 and date_str[4] == "-":
        return date_str  # Already ISO
    # Try M/D/YYYY or MM/DD/YYYY
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str  # Return as-is if unparseable


def query_table(conn, table, columns="*"):
    """Query a table and return rows as list of dicts keyed by date."""
    cur = conn.cursor()
    cur.execute(f"SELECT {columns} FROM {table}")
    col_names = [desc[0] for desc in cur.description]
    result = {}
    for row in cur.fetchall():
        d = dict(zip(col_names, row))
        date = normalize_date(d.get("date"))
        if date:
            d["date"] = date
            result[date] = d
    return result


def query_sessions(conn):
    """Query session_log, returning list of sessions per date."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM session_log ORDER BY date DESC")
    col_names = [desc[0] for desc in cur.description]
    result = {}
    for row in cur.fetchall():
        d = dict(zip(col_names, row))
        date = normalize_date(d.pop("date", None))
        d.pop("updated_at", None)
        if date:
            result.setdefault(date, []).append(d)
    return result


def query_strength(conn):
    """Query strength_log, returning list of exercises per date."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM strength_log ORDER BY date DESC")
    col_names = [desc[0] for desc in cur.description]
    result = {}
    for row in cur.fetchall():
        d = dict(zip(col_names, row))
        date = normalize_date(d.pop("date", None))
        d.pop("updated_at", None)
        d.pop("id", None)
        if date:
            result.setdefault(date, []).append(d)
    return result


def export():
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Run sheets_to_sqlite.py first to populate the database.")
        return False

    conn = sqlite3.connect(str(DB_PATH))

    # Load all tables
    garmin = query_table(conn, "garmin")
    sleep = query_table(conn, "sleep")
    nutrition = query_table(conn, "nutrition")
    daily_log = query_table(conn, "daily_log")
    overall_analysis = query_table(conn, "overall_analysis")
    sessions = query_sessions(conn)
    strength = query_strength(conn)
    conn.close()

    # Collect all unique dates
    all_dates = sorted(set(
        list(garmin.keys()) + list(sleep.keys()) +
        list(nutrition.keys()) + list(daily_log.keys()) +
        list(overall_analysis.keys()) +
        list(sessions.keys()) + list(strength.keys())
    ))

    # Build per-day data
    days = {}
    for date in all_dates:
        day_data = {}

        # Garmin
        g = garmin.get(date, {})
        if g:
            g.pop("updated_at", None)
            day_data["garmin"] = g

        # Sleep
        s = sleep.get(date, {})
        if s:
            s.pop("updated_at", None)
            # Add bedtime as minutes for color grading
            s["bedtime_minutes"] = bedtime_to_minutes(s.get("bedtime"))
            day_data["sleep"] = s

        # Nutrition
        n = nutrition.get(date, {})
        if n:
            n.pop("updated_at", None)
            day_data["nutrition"] = n

        # Daily Log
        dl = daily_log.get(date, {})
        if dl:
            dl.pop("updated_at", None)
            day_data["daily_log"] = dl

        # Overall Analysis
        oa = overall_analysis.get(date, {})
        if oa:
            oa.pop("updated_at", None)
            day_data["overall_analysis"] = oa

        # Sessions
        if date in sessions:
            day_data["sessions"] = sessions[date]

        # Strength
        if date in strength:
            day_data["strength"] = strength[date]

        days[date] = day_data

    output = {
        "generated_at": datetime.now().isoformat(),
        "total_days": len(days),
        "date_range": {"start": all_dates[0], "end": all_dates[-1]} if all_dates else {},
        "metrics": METRICS,
        "days": days,
    }

    json_str = json.dumps(output, default=str)
    JSON_PATH.write_text(json.dumps(output, indent=2, default=str))

    # Embed data directly into HTML (avoids file:// fetch restrictions)
    if not TEMPLATE_PATH.exists():
        print(f"ERROR: Template not found at {TEMPLATE_PATH}")
        return False

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("/*__DASHBOARD_DATA__*/", f"const DATA = {json_str};", 1)
    OUTPUT_PATH.write_text(html, encoding="utf-8")

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"Exported {len(days)} days -> {OUTPUT_PATH.name} ({size_kb:.0f} KB)")
    print(f"Date range: {all_dates[0]} to {all_dates[-1]}")
    return True


if __name__ == "__main__":
    export()
