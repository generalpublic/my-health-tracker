"""
overall_analysis.py -- Scientifically-grounded daily health analysis engine.

Reads data from all Google Sheets tabs (Garmin, Sleep, Daily Log, Session Log,
Nutrition), computes a composite Readiness Score using individual rolling
baselines, and generates actionable insights with scientific citations.

Methodology:
  - Individual z-scores vs 30-day rolling baseline (not population norms)
  - 5-day weighted sleep average (Van Dongen et al. 2003)
  - ACWR training load ratio (Gabbett 2016)
  - Keyword-based diet/behavior flagging from free-text notes
  - Confidence rating based on data completeness

Usage:
    python overall_analysis.py                     # Analyze yesterday
    python overall_analysis.py --date 2026-03-15   # Analyze specific date
    python overall_analysis.py --today             # Analyze today
    python overall_analysis.py --week              # 7-day summary

See reference/METHODOLOGY.md for full scientific basis and citations.
"""

import os
import re
import sys
import json
import math
import argparse
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from utils import get_workbook, _safe_float, date_to_day, load_thresholds
from schema import OVERALL_ANALYSIS_HEADERS
from profile_loader import (
    load_profile, get_accommodations, get_relevant_conditions,
    get_threshold_overrides, get_priority_concerns, check_biomarker_staleness,
    format_recommendation, sanitize_for_notification, merge_knowledge
)

# Load scoring thresholds from thresholds.json (falls back to hardcoded defaults)
_THRESHOLDS = load_thresholds()

# ---------------------------------------------------------------------------
# Health Knowledge Base Loader
# ---------------------------------------------------------------------------

def load_health_knowledge():
    """Load structured health knowledge from reference/health_knowledge.json.

    Returns dict keyed by entry 'id' for fast lookup.
    Falls back to empty dict if file missing or malformed.
    """
    kb_path = Path(__file__).parent / "reference" / "health_knowledge.json"
    if not kb_path.exists():
        print("  [knowledge] health_knowledge.json not found -- using hardcoded fallbacks.")
        return {}
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = {entry["id"]: entry for entry in data.get("knowledge", [])}
        pending = sum(1 for e in entries.values() if e.get("confidence") == "Pending")
        if pending:
            print(f"  [knowledge] Loaded {len(entries)} knowledge entries ({pending} pending evaluation).")
        else:
            print(f"  [knowledge] Loaded {len(entries)} knowledge entries.")
        return entries
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  [knowledge] Error loading health_knowledge.json: {e} -- using fallbacks.")
        return {}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Readiness label thresholds (from thresholds.json)
READINESS_LABELS = [
    (entry["min_score"], entry["label"])
    for entry in _THRESHOLDS["readiness_labels"]
]

# Diet/behavior keywords to flag in notes
ALCOHOL_KEYWORDS = ["alcohol", "beer", "wine", "drink", "drinks", "cocktail",
                    "whiskey", "vodka", "tequila", "bourbon", "sake", "soju"]
SUGAR_KEYWORDS = ["sugar", "candy", "ice cream", "cake", "cookies", "pastry",
                  "chocolate", "soda", "dessert", "sweets", "donut", "brownie"]
FAST_FOOD_KEYWORDS = ["fast food", "mcdonald", "burger king", "wendy", "taco bell",
                      "pizza", "fried", "takeout", "take out", "take-out"]
LATE_MEAL_KEYWORDS = ["late meal", "late dinner", "ate late", "midnight snack",
                      "late night eat", "eating late"]
CAFFEINE_LATE_KEYWORDS = ["coffee afternoon", "coffee evening", "late coffee",
                          "caffeine late", "energy drink"]

# ACWR thresholds (Gabbett 2016, from thresholds.json)
ACWR_HIGH = _THRESHOLDS["acwr"]["elevated"]        # elevated injury risk
ACWR_LOW = _THRESHOLDS["acwr"]["detraining"]       # detraining risk
ACWR_SWEET_LOW = _THRESHOLDS["acwr"]["sweet_low"]
ACWR_SWEET_HIGH = _THRESHOLDS["acwr"]["sweet_high"]


# ---------------------------------------------------------------------------
# Data Reading
# ---------------------------------------------------------------------------

def _read_tab_as_dicts(wb, tab_name):
    """Read a sheet tab and return list of dicts keyed by header names."""
    try:
        sheet = wb.worksheet(tab_name)
    except Exception:
        return []
    rows = sheet.get_all_values()
    if len(rows) < 2:
        return []
    headers = rows[0]
    result = []
    for row in rows[1:]:
        if not row or len(row) < 2 or not row[0]:
            continue
        d = {}
        for i, h in enumerate(headers):
            d[h] = row[i] if i < len(row) else ""
        result.append(d)
    return result


def _get_date_col(row_dict, tab_name):
    """Extract date string from a row dict. Date is col B for most tabs, col A for Overall Analysis."""
    if tab_name == "Overall Analysis":
        return row_dict.get("Date", "")
    return row_dict.get("Date", "")


def read_all_data(wb):
    """Read all tabs into a unified data structure keyed by tab name.

    Respects feature flags from user_config.json — disabled tabs return empty
    lists so downstream code gracefully skips their analysis.
    """
    from utils import load_user_config
    features = load_user_config().get("features", {})
    return {
        "garmin": _read_tab_as_dicts(wb, "Garmin"),
        "sleep": _read_tab_as_dicts(wb, "Sleep"),
        "daily_log": _read_tab_as_dicts(wb, "Daily Log") if features.get("daily_log", True) else [],
        "session_log": _read_tab_as_dicts(wb, "Session Log") if features.get("session_log", True) else [],
        "nutrition": _read_tab_as_dicts(wb, "Nutrition") if features.get("nutrition", True) else [],
    }


def read_all_data_from_supabase():
    """Read all data from Supabase instead of Google Sheets.

    Returns same dict structure as read_all_data(wb) with Sheets-compatible
    header names so downstream analysis code works unchanged.

    Used by GitHub Actions (--cloud flag) when Google Sheets is not available.
    """
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and key must be set for --cloud mode")

    client = create_client(url, key)

    def _query_all(table, order_col="date"):
        """Fetch all rows from a Supabase table, ordered by date desc."""
        rows = []
        offset = 0
        batch = 1000
        while True:
            resp = client.table(table).select("*").order(
                order_col, desc=True
            ).range(offset, offset + batch - 1).execute()
            rows.extend(resp.data)
            if len(resp.data) < batch:
                break
            offset += batch
        return rows

    # Supabase column -> Sheets header mappings
    _GARMIN_MAP = {
        "day": "Day", "date": "Date", "sleep_score": "Sleep Score",
        "hrv_overnight_avg": "HRV (overnight avg)", "hrv_7day_avg": "HRV 7-day avg",
        "resting_hr": "Resting HR", "sleep_duration_hrs": "Sleep Duration (hrs)",
        "body_battery": "Body Battery", "steps": "Steps",
        "total_calories_burned": "Total Calories Burned",
        "active_calories_burned": "Active Calories Burned",
        "bmr_calories": "BMR Calories", "avg_stress_level": "Avg Stress Level",
        "stress_qualifier": "Stress Qualifier", "floors_ascended": "Floors Ascended",
        "moderate_intensity_min": "Moderate Intensity Min",
        "vigorous_intensity_min": "Vigorous Intensity Min",
        "body_battery_at_wake": "Body Battery at Wake",
        "body_battery_high": "Body Battery High", "body_battery_low": "Body Battery Low",
        "activity_name": "Activity Name", "activity_type": "Activity Type",
        "start_time": "Start Time", "distance_mi": "Distance (mi)",
        "duration_min": "Duration (min)", "avg_hr": "Avg HR", "max_hr": "Max HR",
        "calories": "Calories", "elevation_gain_m": "Elevation Gain (m)",
        "avg_speed_mph": "Avg Speed (mph)",
        "aerobic_training_effect": "Aerobic Training Effect",
        "anaerobic_training_effect": "Anaerobic Training Effect",
        "zone_1_min": "Zone 1 - Warm Up (min)", "zone_2_min": "Zone 2 - Easy (min)",
        "zone_3_min": "Zone 3 - Aerobic (min)", "zone_4_min": "Zone 4 - Threshold (min)",
        "zone_5_min": "Zone 5 - Max (min)",
        "spo2_avg": "SpO2 Avg", "spo2_min": "SpO2 Min",
    }

    _SLEEP_MAP = {
        "day": "Day", "date": "Date", "garmin_sleep_score": "Garmin Sleep Score",
        "sleep_analysis_score": "Sleep Analysis Score",
        "total_sleep_hrs": "Total Sleep (hrs)", "sleep_analysis": "Sleep Analysis",
        "notes": "Notes", "bedtime": "Bedtime", "wake_time": "Wake Time",
        "bedtime_variability_7d": "Bedtime Variability (7d)",
        "wake_variability_7d": "Wake Variability (7d)",
        "time_in_bed_hrs": "Time in Bed (hrs)", "deep_sleep_min": "Deep Sleep (min)",
        "light_sleep_min": "Light Sleep (min)", "rem_min": "REM (min)",
        "awake_during_sleep_min": "Awake During Sleep (min)",
        "deep_pct": "Deep %", "rem_pct": "REM %",
        "sleep_cycles": "Sleep Cycles", "awakenings": "Awakenings",
        "avg_hr": "Avg HR", "avg_respiration": "Avg Respiration",
        "overnight_hrv_ms": "Overnight HRV (ms)",
        "body_battery_gained": "Body Battery Gained",
        "sleep_feedback": "Sleep Descriptor",
    }

    _SESSION_MAP = {
        "day": "Day", "date": "Date", "session_type": "Session Type",
        "activity_name": "Activity", "duration_min": "Duration (min)",
        "distance_mi": "Distance (mi)", "avg_hr": "Avg HR", "max_hr": "Max HR",
        "calories": "Calories", "aerobic_te": "Aerobic Training Effect",
        "anaerobic_te": "Anaerobic Training Effect",
        "zone_1_min": "Zone 1 (min)", "zone_2_min": "Zone 2 (min)",
        "zone_3_min": "Zone 3 (min)", "zone_4_min": "Zone 4 (min)",
        "zone_5_min": "Zone 5 (min)", "zone_ranges": "Zone Ranges",
        "source": "Source", "elevation_m": "Elevation (m)",
        "perceived_effort": "Perceived Effort",
        "post_workout_energy": "Post-Workout Energy (1-10)",
        "notes": "Notes",
    }

    _NUTRITION_MAP = {
        "day": "Day", "date": "Date",
        "total_calories_burned": "Total Calories Burned",
        "active_calories_burned": "Active Calories Burned",
        "bmr_calories": "BMR Calories",
        "breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner",
        "snacks": "Snacks", "total_calories_consumed": "Total Calories Consumed",
        "protein_g": "Protein (g)", "carbs_g": "Carbs (g)", "fats_g": "Fats (g)",
        "water_l": "Water (L)", "calorie_balance": "Calorie Balance",
        "notes": "Notes",
    }

    _DAILY_LOG_MAP = {
        "day": "Day", "date": "Date", "morning_energy": "Morning Energy (1-10)",
        "wake_at_930": "Wake at 9:30 AM", "no_morning_screens": "No Morning Screens",
        "creatine_hydrate": "Creatine & Hydrate",
        "walk_breathing": "20 Min Walk + Breathing",
        "physical_activity": "Physical Activity",
        "no_screens_before_bed": "No Screens Before Bed",
        "bed_at_10pm": "Bed at 10 PM", "habits_total": "Habits Total (0-7)",
        "midday_energy": "Midday Energy (1-10)", "midday_focus": "Midday Focus (1-10)",
        "midday_mood": "Midday Mood (1-10)",
        "midday_body_feel": "Midday Body Feel (1-10)", "midday_notes": "Midday Notes",
        "evening_energy": "Evening Energy (1-10)", "evening_focus": "Evening Focus (1-10)",
        "evening_mood": "Evening Mood (1-10)",
        "perceived_stress": "Perceived Stress (1-10)",
        "day_rating": "Day Rating (1-10)", "evening_notes": "Evening Notes",
    }

    def _remap(rows, col_map):
        """Convert Supabase rows to Sheets-header-keyed dicts."""
        result = []
        for row in rows:
            d = {}
            for supa_col, sheet_header in col_map.items():
                val = row.get(supa_col)
                d[sheet_header] = str(val) if val is not None else ""
            result.append(d)
        return result

    print("[cloud] Reading data from Supabase...")
    garmin_rows = _query_all("garmin")
    sleep_rows = _query_all("sleep")
    daily_log_rows = _query_all("daily_log")
    session_rows = _query_all("session_log")
    nutrition_rows = _query_all("nutrition")

    print(f"[cloud] Loaded: garmin={len(garmin_rows)}, sleep={len(sleep_rows)}, "
          f"daily_log={len(daily_log_rows)}, sessions={len(session_rows)}, "
          f"nutrition={len(nutrition_rows)}")

    return {
        "garmin": _remap(garmin_rows, _GARMIN_MAP),
        "sleep": _remap(sleep_rows, _SLEEP_MAP),
        "daily_log": _remap(daily_log_rows, _DAILY_LOG_MAP),
        "session_log": _remap(session_rows, _SESSION_MAP),
        "nutrition": _remap(nutrition_rows, _NUTRITION_MAP),
    }


def _rows_by_date(rows):
    """Index rows by date string for fast lookup."""
    by_date = {}
    for r in rows:
        d = r.get("Date", "")
        if d and d.startswith("20"):
            if d not in by_date:
                by_date[d] = r
            # For session log, multiple entries per date -- handled separately
    return by_date


def _sessions_by_date(rows):
    """Index session log: date -> list of sessions (multiple per day allowed)."""
    by_date = {}
    for r in rows:
        d = r.get("Date", "")
        if d and d.startswith("20"):
            by_date.setdefault(d, []).append(r)
    return by_date


def _norm_cdf(x):
    """Standard normal CDF approximation (Abramowitz & Stegun 26.2.17).

    Max error < 7.5e-8. Stdlib-only — no scipy dependency required.
    """
    import math
    if x < 0:
        return 1.0 - _norm_cdf(-x)
    p = 0.2316419
    b1, b2, b3, b4, b5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    t = 1.0 / (1.0 + p * x)
    phi = (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x)
    return 1.0 - phi * (b1 * t + b2 * t**2 + b3 * t**3 + b4 * t**4 + b5 * t**5)


# ---------------------------------------------------------------------------
# Baseline Computation (z-score methodology)
# ---------------------------------------------------------------------------

def _get_values_in_window(by_date, target_date, days_back, field):
    """Get numeric values for a field over a date window (excluding target_date)."""
    values = []
    for offset in range(1, days_back + 1):
        d = str(target_date - timedelta(days=offset))
        row = by_date.get(d)
        if row:
            v = _safe_float(row.get(field))
            if v is not None:
                values.append(v)
    return values


def _get_values_including_today(by_date, target_date, days_back, field):
    """Get numeric values for a field over a date window (including target_date)."""
    values = []
    for offset in range(0, days_back):
        d = str(target_date - timedelta(days=offset))
        row = by_date.get(d)
        if row:
            v = _safe_float(row.get(field))
            if v is not None:
                values.append(v)
    return values


def compute_baselines(by_date_garmin, by_date_sleep, target_date):
    """Compute rolling baselines for key metrics.

    Uses a single 180-day lookback window. Minimum 7 data points for any
    baseline. The wide window ensures sparse metrics never lose observations
    to an artificial cutoff.

    Also computes HRV trend direction (5-day slope) to distinguish
    overtraining (declining) from detraining (flat-low) patterns.

    Returns dict with mean, std, today's value, z-score, n, outliers,
    and (for HRV) trend direction.
    """
    baselines = {}

    MAX_LOOKBACK = 180
    MIN_POINTS = 7

    metrics = [
        ("hrv", by_date_garmin, "HRV (overnight avg)"),
        ("rhr", by_date_garmin, "Resting HR"),
        ("sleep_score", by_date_sleep, "Garmin Sleep Score"),
        ("sleep_analysis_score", by_date_sleep, "Sleep Analysis Score"),
        ("sleep_duration", by_date_sleep, "Total Sleep (hrs)"),
        ("body_battery", by_date_garmin, "Body Battery"),
        ("steps", by_date_garmin, "Steps"),
        ("stress", by_date_garmin, "Avg Stress Level"),
    ]

    for key, source, field in metrics:
        window_values = _get_values_in_window(source, target_date, MAX_LOOKBACK, field)

        today_row = source.get(str(target_date), {})
        today_val = _safe_float(today_row.get(field))

        if len(window_values) >= MIN_POINTS:
            mean = sum(window_values) / len(window_values)
            variance = sum((v - mean) ** 2 for v in window_values) / (len(window_values) - 1)
            std = variance ** 0.5 if variance > 0 else 1.0
            z = (today_val - mean) / std if today_val is not None and std > 0 else None
        else:
            mean, std, z = None, None, None

        # Flag outliers (>3 SD from mean) — don't exclude, just flag
        outliers = []
        if mean is not None and std is not None and std > 0:
            for v in window_values:
                if abs(v - mean) > 3 * std:
                    outliers.append(v)
            if today_val is not None and abs(today_val - mean) > 3 * std:
                outliers.append(today_val)

        entry = {
            "mean": mean,
            "std": std,
            "today": today_val,
            "z": z,
            "n": len(window_values),
            "outliers": outliers,
        }

        # HRV trend direction: 5-day slope to distinguish overtraining vs detraining
        if key == "hrv":
            recent_hrv = []
            for offset in range(5):
                d = str(target_date - timedelta(days=offset))
                row = source.get(d, {})
                v = _safe_float(row.get(field))
                if v is not None:
                    recent_hrv.append((offset, v))
            if len(recent_hrv) >= 3:
                # Simple linear regression slope (negative offset = recent first)
                n_pts = len(recent_hrv)
                x_mean = sum(x for x, _ in recent_hrv) / n_pts
                y_mean = sum(y for _, y in recent_hrv) / n_pts
                num = sum((x - x_mean) * (y - y_mean) for x, y in recent_hrv)
                den = sum((x - x_mean) ** 2 for x, _ in recent_hrv)
                slope = num / den if den > 0 else 0
                # Positive slope = recent values lower (declining, since offset 0 = today)
                # Negative slope = recent values higher (recovering)
                if slope > 1.0:
                    entry["trend"] = "declining"
                elif slope < -1.0:
                    entry["trend"] = "recovering"
                else:
                    entry["trend"] = "stable"
            else:
                entry["trend"] = None

        baselines[key] = entry

    return baselines


# ---------------------------------------------------------------------------
# Sleep Context (5-day weighted rolling average)
# ---------------------------------------------------------------------------

def analyze_sleep_context(by_date_sleep, by_date_garmin, target_date, baselines):
    """Analyze 5-day sleep trend with recent nights weighted 2x.

    Returns (context_text, sleep_debt_hours, trend_direction, deep_trend, rem_trend,
            debt_night_count).
    Based on Van Dongen et al. 2003 -- cumulative sleep restriction model.
    """
    # Collect last 5 nights of sleep data
    scores = []
    durations = []
    for offset in range(0, 5):
        d = str(target_date - timedelta(days=offset))
        row = by_date_sleep.get(d)
        if row:
            s = _safe_float(row.get("Garmin Sleep Score"))
            dur = _safe_float(row.get("Total Sleep (hrs)"))
            weight = 2.0 if offset == 0 else 1.0  # most recent night weighted 2x
            if s is not None:
                scores.append((s, weight))
            if dur is not None:
                durations.append((dur, weight))

    if not scores:
        return "No sleep data available for analysis window.", None, None, None, None

    weighted_score = sum(s * w for s, w in scores) / sum(w for _, w in scores)
    weighted_duration = sum(d * w for d, w in durations) / sum(w for _, w in durations) if durations else None

    # Sleep debt: compare weighted avg to 30-day baseline
    baseline_duration = baselines.get("sleep_duration", {}).get("mean")
    sleep_debt = None
    if weighted_duration is not None and baseline_duration is not None:
        sleep_debt = baseline_duration - weighted_duration  # positive = debt

    # Trend direction: are last 3 nights improving or declining?
    recent_scores = []
    for offset in range(0, 3):
        d = str(target_date - timedelta(days=offset))
        row = by_date_sleep.get(d)
        if row:
            s = _safe_float(row.get("Garmin Sleep Score"))
            if s is not None:
                recent_scores.append(s)

    trend = None
    if len(recent_scores) >= 2:
        if recent_scores[0] > recent_scores[-1]:
            trend = "improving"
        elif recent_scores[0] < recent_scores[-1]:
            trend = "declining"
        else:
            trend = "stable"

    # Build context text
    parts = []
    parts.append(f"5-day weighted avg: {weighted_score:.0f} score")
    if weighted_duration is not None:
        parts.append(f"{weighted_duration:.1f}h duration")
    if sleep_debt is not None and sleep_debt > 0.5:
        parts.append(f"sleep debt: {sleep_debt:.1f}h below baseline")
    if trend:
        parts.append(f"trend: {trend}")

    # Today's specific data
    today = by_date_sleep.get(str(target_date))
    if today:
        today_score = _safe_float(today.get("Garmin Sleep Score"))
        today_dur = _safe_float(today.get("Total Sleep (hrs)"))
        today_deep = _safe_float(today.get("Deep %"))
        today_rem = _safe_float(today.get("REM %"))
        specifics = []
        if today_score is not None:
            specifics.append(f"last night: {today_score:.0f}")
        if today_dur is not None:
            specifics.append(f"{today_dur:.1f}h")
        if today_deep is not None:
            specifics.append(f"deep {today_deep:.0f}%")
        if today_rem is not None:
            specifics.append(f"REM {today_rem:.0f}%")
        if specifics:
            parts.append("(" + ", ".join(specifics) + ")")

    # --- Deep/REM 3-night trends (mirrors sleep score trend logic) ---
    deep_trend = None
    rem_trend = None
    recent_deep = []
    recent_rem = []
    for offset in range(0, 3):
        d = str(target_date - timedelta(days=offset))
        row = by_date_sleep.get(d)
        if row:
            dp = _safe_float(row.get("Deep %"))
            rp = _safe_float(row.get("REM %"))
            if dp is not None:
                recent_deep.append(dp)
            if rp is not None:
                recent_rem.append(rp)

    if len(recent_deep) >= 2:
        if recent_deep[0] > recent_deep[-1]:
            deep_trend = "improving"
        elif recent_deep[0] < recent_deep[-1]:
            deep_trend = "declining"
        else:
            deep_trend = "stable"

    if len(recent_rem) >= 2:
        if recent_rem[0] > recent_rem[-1]:
            rem_trend = "improving"
        elif recent_rem[0] < recent_rem[-1]:
            rem_trend = "declining"
        else:
            rem_trend = "stable"

    # Count individual nights with sleep debt > threshold (for Van Dongen penalty)
    debt_threshold = 0.75  # hours below baseline to count as a debt night
    debt_night_count = 0
    if baseline_duration is not None:
        for offset in range(0, 5):
            d = str(target_date - timedelta(days=offset))
            row = by_date_sleep.get(d)
            if row:
                dur = _safe_float(row.get("Total Sleep (hrs)"))
                if dur is not None and (baseline_duration - dur) > debt_threshold:
                    debt_night_count += 1

    context_text = " | ".join(parts)
    return context_text, sleep_debt, trend, deep_trend, rem_trend, debt_night_count


# ---------------------------------------------------------------------------
# Dynamic Sleep Need Calculator
# ---------------------------------------------------------------------------

def compute_sleep_need(baselines, sleep_debt, acwr, target_date):
    """Compute tonight's personalized sleep need based on training load and debt.

    Formula: tonight_need = base_need + strain_adjustment + debt_payoff

    Where:
      - base_need = user's 30-day average sleep duration (natural equilibrium)
      - strain_adjustment = 0-45 min based on ACWR
      - debt_payoff = recover 30% of debt per night, capped at 60 min

    Returns dict with sleep_need_hrs, recommended_bedtime, breakdown, or None.
    """
    base_need = baselines.get("sleep_duration", {}).get("mean")
    if base_need is None:
        return None

    # Strain adjustment based on ACWR
    strain_min = 0
    if acwr is not None:
        if acwr > 1.5:
            strain_min = 45
        elif acwr > 1.3:
            strain_min = 30
        elif acwr >= 0.8:
            strain_min = 15
        # acwr < 0.8 = low training, no extra sleep needed

    # Debt payoff: recover 30% of accumulated debt per night, capped at 60 min
    debt_min = 0
    if sleep_debt is not None and sleep_debt > 0.25:
        debt_min = min(sleep_debt * 0.3 * 60, 60)  # convert hours to minutes, cap at 60

    tonight_need_hrs = base_need + (strain_min + debt_min) / 60.0

    # Recommended bedtime: assume default wake target of 9:30 AM (from habits)
    wake_target_hr = 9.5  # 9:30 AM as decimal hours
    recommended_bedtime_hr = wake_target_hr - tonight_need_hrs
    if recommended_bedtime_hr < 0:
        recommended_bedtime_hr += 24  # wrap around

    # Format bedtime as HH:MM
    bt_h = int(recommended_bedtime_hr)
    bt_m = int((recommended_bedtime_hr - bt_h) * 60)
    suffix = "PM" if bt_h >= 12 and bt_h < 24 else "AM"
    bt_h12 = bt_h if bt_h <= 12 else bt_h - 12
    if bt_h12 == 0:
        bt_h12 = 12
    bedtime_str = f"{bt_h12}:{bt_m:02d} {suffix}"

    # Build breakdown explanation
    breakdown_parts = [f"base {base_need:.1f}h"]
    if strain_min > 0:
        breakdown_parts.append(f"+{strain_min}min training load")
    if debt_min > 0:
        breakdown_parts.append(f"+{debt_min:.0f}min debt recovery")

    return {
        "sleep_need_hrs": round(tonight_need_hrs, 2),
        "recommended_bedtime": bedtime_str,
        "recommended_bedtime_hr": round(recommended_bedtime_hr, 2),
        "base_need": round(base_need, 2),
        "strain_adjustment_min": strain_min,
        "debt_payoff_min": round(debt_min),
        "breakdown": " + ".join(breakdown_parts),
    }


# ---------------------------------------------------------------------------
# Illness Detection Heuristic (Multi-Metric Anomaly Score)
# ---------------------------------------------------------------------------

def _compute_trend_direction(values):
    """Determine if a 3-day series is worsening, improving, or stable.

    values: list of numeric values in chronological order (oldest first).
    Returns: 'worsening', 'improving', or 'stable'
    """
    if len(values) < 2:
        return "stable"
    first = values[0]
    last = values[-1]
    if first is None or first == 0:
        return "stable"
    pct_change = (last - first) / abs(first)
    if pct_change > 0.05:
        return "worsening"  # values increasing (bad for RHR, stress, resp)
    elif pct_change < -0.05:
        return "improving"
    return "stable"


def _get_metric_history(by_date_dict, key, target_date, days=30):
    """Get historical values for a metric (excludes today)."""
    values = []
    for offset in range(1, days + 1):
        d = str(target_date - timedelta(days=offset))
        row = by_date_dict.get(d, {})
        v = _safe_float(row.get(key))
        if v is not None:
            values.append(v)
    return values


def _get_recent_values(by_date_dict, key, target_date, days=3):
    """Get the last N days of values in chronological order (oldest first)."""
    values = []
    for offset in range(days - 1, -1, -1):
        d = str(target_date - timedelta(days=offset))
        row = by_date_dict.get(d, {})
        v = _safe_float(row.get(key))
        values.append(v)
    return values


def detect_illness(baselines, by_date_sleep, daily_log_by_date,
                   acwr, target_date, by_date_garmin=None, conn=None):
    """Probabilistic illness detection using multi-metric anomaly scoring.

    This is a PROBABILISTIC system, not a diagnostic tool. Biometrics cannot
    always accurately indicate illness -- HRV can be high while sick, RHR can
    stay flat during onset. The system surfaces elevated probability and
    suggests the user pay attention to how they feel, never diagnoses.

    Uses 10 signals with optional trend context to distinguish illness from
    overtraining or normal variation. The key differentiator is the "no
    training explanation" check combined with multi-metric convergence.

    Scoring signals (cumulative, max ~15):
        RHR > 1.5 SD above baseline:           +2 (+ trend bonus +0.5)
        HRV > 1.5 SD below baseline:           +2 (+ trend bonus +0.5)
        Respiratory rate > 1 SD above baseline: +2
        Stress > 1.0 SD above baseline:        +1
        BB@Wake > 1.0 SD below baseline:       +1
        SpO2 > 1.0 SD below baseline or < 94%: +1
        Body battery gained < p15:              +1
        Sleep score declined 3+ nights:         +1
        No high training load (ACWR < 1.0):     +2
        Subjective energy < 4 for 2 days:       +1

    Classification:
        0-3: Normal variation
        4-6: Possible illness -- biometrics suggest something unusual
        7+:  Likely illness -- multiple indicators significantly disrupted

    State persistence (requires conn):
        Once 'likely_illness' triggers, an episode is created in SQLite.
        The episode persists until 5 consecutive normal days OR user
        confirms recovery via PWA. This prevents premature flag-dropping
        when biometrics bounce before symptoms resolve.
    """
    score = 0.0
    signals = []
    if by_date_garmin is None:
        by_date_garmin = {}

    today_sleep = by_date_sleep.get(str(target_date), {})
    today_garmin = by_date_garmin.get(str(target_date), {})

    # --- Signal 1: RHR elevated > 1.5 SD above baseline (+2) ---
    # Trend bonus: +0.5 if z > 0.7 AND 3-day RHR trend is worsening
    rhr = baselines.get("rhr", {})
    rhr_z = rhr.get("z")
    if rhr_z is not None:
        if rhr_z > 1.5:
            score += 2
            rhr_val = rhr.get("today", "?")
            rhr_mean = rhr.get("mean")
            delta = f" (+{rhr_val - rhr_mean:.0f} bpm)" if rhr_mean and rhr_val else ""
            signals.append(f"RHR elevated {rhr_val} bpm{delta} [z={rhr_z:.1f}]")
        elif rhr_z > 0.7:
            rhr_recent = _get_recent_values(by_date_garmin, "Resting HR", target_date, 3)
            rhr_nums = [v for v in rhr_recent if v is not None]
            if _compute_trend_direction(rhr_nums) == "worsening":
                score += 0.5
                signals.append(f"RHR trending up [z={rhr_z:.1f}, worsening]")

    # --- Signal 2: HRV suppressed > 1.5 SD below baseline (+2) ---
    # Trend bonus: +0.5 if z < -0.7 AND 3-day HRV trend is declining
    hrv = baselines.get("hrv", {})
    hrv_z = hrv.get("z")
    if hrv_z is not None:
        if hrv_z < -1.5:
            score += 2
            hrv_val = hrv.get("today", "?")
            hrv_mean = hrv.get("mean")
            delta = f" ({hrv_val - hrv_mean:.0f} ms)" if hrv_mean and hrv_val else ""
            signals.append(f"HRV suppressed {hrv_val} ms{delta} [z={hrv_z:.1f}]")
        elif hrv_z < -0.7:
            hrv_recent = _get_recent_values(by_date_sleep, "Overnight HRV (ms)", target_date, 3)
            hrv_nums = [v for v in hrv_recent if v is not None]
            # For HRV, decreasing = worsening, so invert for trend check
            if len(hrv_nums) >= 2:
                inverted = [-v for v in hrv_nums]
                if _compute_trend_direction(inverted) == "worsening":
                    score += 0.5
                    signals.append(f"HRV trending down [z={hrv_z:.1f}, worsening]")

    # --- Signal 3: Respiratory rate > 1 SD above baseline (+2) ---
    resp_history = _get_metric_history(by_date_sleep, "Avg Respiration", target_date, 30)
    today_resp = _safe_float(today_sleep.get("Avg Respiration"))

    if today_resp is not None and len(resp_history) >= 7:
        resp_mean = sum(resp_history) / len(resp_history)
        resp_var = sum((v - resp_mean) ** 2 for v in resp_history) / (len(resp_history) - 1)
        resp_std = resp_var ** 0.5 if resp_var > 0 else 1.0
        resp_z = (today_resp - resp_mean) / resp_std if resp_std > 0 else 0
        if resp_z > 1.0:
            score += 2
            signals.append(f"Respiratory rate elevated {today_resp:.1f} brpm "
                           f"(baseline {resp_mean:.1f}) [z={resp_z:.1f}]")

    # --- Signal 4 (NEW): Stress elevated > 1.0 SD above baseline (+1) ---
    stress_history = _get_metric_history(by_date_garmin, "Avg Stress Level", target_date, 30)
    today_stress = _safe_float(today_garmin.get("Avg Stress Level"))

    if today_stress is not None and len(stress_history) >= 7:
        stress_mean = sum(stress_history) / len(stress_history)
        stress_var = sum((v - stress_mean) ** 2 for v in stress_history) / (len(stress_history) - 1)
        stress_std = stress_var ** 0.5 if stress_var > 0 else 1.0
        stress_z = (today_stress - stress_mean) / stress_std if stress_std > 0 else 0
        if stress_z > 1.0:
            score += 1
            signals.append(f"Stress elevated {today_stress:.0f} "
                           f"(baseline {stress_mean:.0f}) [z={stress_z:.1f}]")

    # --- Signal 5 (NEW): BB@Wake depressed > 1.0 SD below baseline (+1) ---
    bbwake_history = _get_metric_history(by_date_garmin, "Body Battery at Wake", target_date, 30)
    today_bbwake = _safe_float(today_garmin.get("Body Battery at Wake"))

    if today_bbwake is not None and len(bbwake_history) >= 7:
        bbwake_mean = sum(bbwake_history) / len(bbwake_history)
        bbwake_var = sum((v - bbwake_mean) ** 2 for v in bbwake_history) / (len(bbwake_history) - 1)
        bbwake_std = bbwake_var ** 0.5 if bbwake_var > 0 else 1.0
        bbwake_z = (today_bbwake - bbwake_mean) / bbwake_std if bbwake_std > 0 else 0
        if bbwake_z < -1.0:
            score += 1
            signals.append(f"Body battery at wake low {today_bbwake:.0f} "
                           f"(baseline {bbwake_mean:.0f}) [z={bbwake_z:.1f}]")

    # --- Signal 5b (NEW): SpO2 depressed > 1.0 SD below baseline (+1) ---
    spo2_history = _get_metric_history(by_date_garmin, "SpO2 Avg", target_date, 30)
    today_spo2 = _safe_float(today_garmin.get("SpO2 Avg"))

    if today_spo2 is not None and len(spo2_history) >= 7:
        spo2_mean = sum(spo2_history) / len(spo2_history)
        spo2_var = sum((v - spo2_mean) ** 2 for v in spo2_history) / (len(spo2_history) - 1)
        spo2_std = spo2_var ** 0.5 if spo2_var > 0 else 1.0
        spo2_z = (today_spo2 - spo2_mean) / spo2_std if spo2_std > 0 else 0
        if spo2_z < -1.0 or today_spo2 < 94:
            score += 1
            signals.append(f"SpO2 low {today_spo2:.0f}% "
                           f"(baseline {spo2_mean:.0f}%) [z={spo2_z:.1f}]")

    # --- Signal 6: Body battery gained during sleep < p15 (+1) ---
    bb_gained_history = _get_metric_history(by_date_sleep, "Body Battery Gained", target_date, 30)
    today_bb_gained = _safe_float(today_sleep.get("Body Battery Gained"))

    if today_bb_gained is not None and len(bb_gained_history) >= 7:
        bb_sorted = sorted(bb_gained_history)
        p15_idx = max(0, int(len(bb_sorted) * 0.15))
        p15 = bb_sorted[p15_idx]
        if today_bb_gained < p15:
            score += 1
            signals.append(f"Body battery gained {today_bb_gained:.0f} "
                           f"(< p15 of {p15:.0f})")

    # --- Signal 7: Sleep score declined 3+ consecutive nights (+1) ---
    recent_sleep_scores = []
    for offset in range(3):
        d = str(target_date - timedelta(days=offset))
        row = by_date_sleep.get(d, {})
        v = _safe_float(row.get("Garmin Sleep Score"))
        if v is not None:
            recent_sleep_scores.append(v)

    if len(recent_sleep_scores) == 3:
        if recent_sleep_scores[0] < recent_sleep_scores[1] < recent_sleep_scores[2]:
            drop = recent_sleep_scores[2] - recent_sleep_scores[0]
            score += 1
            signals.append(f"Sleep score declined 3 nights "
                           f"({recent_sleep_scores[2]:.0f} -> {recent_sleep_scores[0]:.0f}, "
                           f"-{drop:.0f} pts)")

    # --- Signal 8: No high training load, ACWR < 1.0 (+2) ---
    # Key differentiator: if markers are disrupted but no heavy training
    # stimulus, illness becomes a more likely explanation than overtraining.
    if acwr is not None and acwr < 1.0:
        if score >= 2:
            score += 2
            signals.append(f"No training explanation (ACWR {acwr:.2f} < 1.0)")
    elif acwr is None:
        if score >= 2:
            score += 1
            signals.append("No session data to explain disruption")

    # --- Signal 9: Subjective energy < 4/10 two consecutive days (+1) ---
    low_energy_streak = 0
    for offset in range(2):
        d = str(target_date - timedelta(days=offset))
        row = daily_log_by_date.get(d, {})
        energy = _safe_float(row.get("Morning Energy (1-10)"))
        if energy is not None and energy < 4:
            low_energy_streak += 1

    if low_energy_streak >= 2:
        score += 1
        signals.append("Low subjective energy (<4) two consecutive days")

    # --- State-aware classification ---
    active_episode = None
    if conn is not None:
        from sqlite_backup import (get_active_illness, start_illness_episode,
                                   update_illness_peak, resolve_illness_episode,
                                   upsert_illness_daily, get_recent_illness_scores)
        active_episode = get_active_illness(conn)

    if active_episode is not None:
        # Already in an illness episode -- don't drop on one good day.
        # Require 5 consecutive normal days before suggesting recovery.
        recent = get_recent_illness_scores(conn, target_date, days=5)
        if len(recent) >= 5 and all(s < 3 for s in recent):
            label = "recovering"
            recommendation = ("Biometrics have been stable for several days. "
                              "If you feel better, confirm recovery. "
                              "Ease back in with light activity.")
        else:
            label = "illness_ongoing"
            recommendation = ("Illness episode ongoing -- rest and recovery. "
                              "Light walking only, extra hydration, earlier bedtime. "
                              "Low readiness scores are expected during illness.")

        # Update peak if current is higher
        if score > (active_episode.get("peak_score") or 0):
            update_illness_peak(conn, active_episode["id"], score)

        # Auto-resolve safety valve: 21 days without user confirmation
        onset = active_episode.get("onset_date", "")
        try:
            from datetime import date as _date_cls
            onset_d = _date_cls.fromisoformat(onset)
            days_since = (target_date - onset_d).days
            if days_since >= 21 and active_episode.get("confirmed_date") is None:
                resolve_illness_episode(conn, active_episode["id"],
                                        str(target_date), "auto_expired")
                label = "normal"
                recommendation = None
                active_episode = None
        except (ValueError, TypeError):
            pass

    else:
        # No active episode -- standard probabilistic classification
        if score >= 7:
            label = "likely_illness"
            recommendation = ("Multiple biometric indicators are significantly "
                              "disrupted -- consider a rest day. Prioritize "
                              "hydration, sleep, and light activity only.")
            if conn is not None:
                ep_id = start_illness_episode(conn, str(target_date), score)
                active_episode = {"id": ep_id, "onset_date": str(target_date)}
        elif score >= 4:
            label = "possible_illness"
            recommendation = ("Your biometrics suggest something unusual -- "
                              "pay attention to how you feel. Light activity "
                              "only, extra hydration, earlier bedtime.")
        else:
            label = "normal"
            recommendation = None

    # Log daily score to SQLite
    daily_data = {
        "illness_state_id": active_episode["id"] if active_episode else None,
        "anomaly_score": score,
        "signals": [s.split("[")[0].strip() for s in signals],
        "label": label,
    }
    if conn is not None:
        upsert_illness_daily(conn, str(target_date), daily_data)

    # Mirror to Supabase (best-effort)
    try:
        from supabase_sync import (upsert_illness_state as _supa_illness_state,
                                   upsert_illness_daily as _supa_illness_daily)
        _supa_illness_daily(None, str(target_date), daily_data)
        if active_episode:
            _supa_illness_state(None, {
                "onset_date": active_episode.get("onset_date"),
                "peak_score": active_episode.get("peak_score", score),
            })
    except Exception:
        pass  # Supabase failure never breaks pipeline

    if signals:
        print(f"  Illness check: {score:.1f}/14 ({label}) -- "
              f"{', '.join(s.split('[')[0].strip() for s in signals[:3])}")

    return {
        "illness_score": score,
        "illness_label": label,
        "signals": signals,
        "recommendation": recommendation,
        "active_episode": active_episode,
    }


# ---------------------------------------------------------------------------
# Training Load (ACWR -- Acute:Chronic Workload Ratio)
# ---------------------------------------------------------------------------

def compute_acwr(sessions_by_date, target_date):
    """Compute Acute:Chronic Workload Ratio using session duration * avg HR as load proxy.

    Acute = 7-day load, Chronic = 28-day rolling average weekly load.
    Sweet spot: 0.8-1.3 (Gabbett 2016).

    Returns (acwr_value, status_text, acute_load, chronic_load).
    """
    def _session_load(session):
        """Compute load for a single session.

        Prefers sRPE (effort * duration / 10) when Perceived Effort is available
        (Foster 2001 gold standard). Falls back to TRIMP proxy (duration * HR / 100).
        Zone intensity modifier (0.9x-1.35x) adjusts for training type when zone
        data is available — high-intensity sessions (>30% Z4-5) count more.
        """
        dur = _safe_float(session.get("Duration (min)"))
        effort = _safe_float(session.get("Perceived Effort (1-10)"))
        hr = _safe_float(session.get("Avg HR"))
        # sRPE is preferred when both effort and duration are available
        if effort and dur:
            base_load = effort * dur / 10  # sRPE (session RPE)
        elif dur and hr:
            base_load = dur * hr / 100  # TRIMP-like proxy
        elif dur:
            base_load = dur  # fallback to duration only
        else:
            return 0

        # Zone intensity modifier — adjusts load based on zone distribution
        z4 = _safe_float(session.get("Zone 4 (min)")) or 0
        z5 = _safe_float(session.get("Zone 5 (min)")) or 0
        z1 = _safe_float(session.get("Zone 1 (min)")) or 0
        z2 = _safe_float(session.get("Zone 2 (min)")) or 0
        if dur and dur > 0:
            high_frac = (z4 + z5) / dur
            low_frac = (z1 + z2) / dur
            if high_frac > 0.3:
                base_load *= 1.0 + (high_frac - 0.3) * 0.5  # max ~1.35x
            elif low_frac > 0.7:
                base_load *= 0.9

        return base_load

    # Calculate weekly loads for last 4 weeks
    weekly_loads = []
    for week in range(4):
        week_load = 0
        for day_offset in range(week * 7, (week + 1) * 7):
            d = str(target_date - timedelta(days=day_offset))
            sessions = sessions_by_date.get(d, [])
            for s in sessions:
                week_load += _session_load(s)
        weekly_loads.append(week_load)

    acute_load = weekly_loads[0]  # most recent 7 days
    chronic_load = sum(weekly_loads[1:]) / 3 if sum(weekly_loads[1:]) > 0 else 0

    if chronic_load == 0:
        if acute_load == 0:
            return None, "No training data in last 28 days.", 0, 0
        return None, f"Acute load {acute_load:.0f} but no chronic baseline (new to training?).", acute_load, 0

    acwr = acute_load / chronic_load

    # Status
    if acwr > 1.5:
        status = f"ACWR {acwr:.2f}: Spike. Acute load {acute_load:.0f} is {acwr:.1f}x your 28-day average. Elevated injury/illness risk (Gabbett 2016)."
    elif acwr > ACWR_HIGH:
        status = f"ACWR {acwr:.2f}: High. Training this week exceeds your 28-day avg. Monitor recovery closely."
    elif acwr >= ACWR_LOW:
        status = f"ACWR {acwr:.2f}: Sweet spot. Training load is well-matched to your fitness level."
    else:
        status = f"ACWR {acwr:.2f}: Low. You're training below your recent capacity. Consider increasing load if recovery allows."

    return acwr, status, acute_load, chronic_load


# ---------------------------------------------------------------------------
# Notes Parsing (keyword-based heuristics)
# ---------------------------------------------------------------------------

NEGATION_WORDS = {"no", "not", "didn't", "didnt", "didn't", "avoided", "skipped",
                  "without", "zero", "none", "never", "don't", "dont", "don't",
                  "wasn't", "wasnt", "wasn't", "isn't", "isnt", "isn't"}


def _search_notes(text, keywords):
    """Check if any keywords appear in text (case-insensitive), with negation detection.

    If a keyword appears within 3 words of a negation word (no, not, avoided, etc.),
    it is NOT flagged. This prevents "avoided alcohol" from triggering the alcohol flag.
    """
    if not text:
        return []
    text_lower = text.lower()
    words = text_lower.split()
    matched = []
    for kw in keywords:
        if kw not in text_lower:
            continue
        # Find position of keyword in word list
        negated = False
        kw_words = kw.split()
        for i, word in enumerate(words):
            if kw_words[0] in word:
                # Check 3 words before for negation
                start = max(0, i - 3)
                preceding = words[start:i]
                if any(neg in w for w in preceding for neg in NEGATION_WORDS):
                    negated = True
                    break
        if not negated:
            matched.append(kw)
    return matched


def parse_notes_for_flags(daily_log_by_date, nutrition_by_date, target_date,
                          days_back=2, sessions_by_date=None, sleep_by_date=None):
    """Scan free-text notes for diet/behavior flags over the lookback window.

    Uses LLM-based extraction (Claude Haiku) when available, with graceful
    fallback to keyword matching. Returns list of (date, flag_type, detail) tuples.
    """
    try:
        from notes_extraction import extract_behaviors, behaviors_to_flags
    except ImportError:
        # notes_extraction not available (e.g. cloud mode) -- return empty flags
        return []

    flags = []

    for offset in range(0, days_back):
        d = str(target_date - timedelta(days=offset))

        # Collect all notes for this date
        notes_texts = []
        dl = daily_log_by_date.get(d, {})
        for field in ["Midday Notes", "Evening Notes"]:
            if dl.get(field):
                notes_texts.append(dl[field])

        nut = nutrition_by_date.get(d, {})
        for field in ["Breakfast", "Lunch", "Dinner", "Snacks", "Notes"]:
            if nut.get(field):
                notes_texts.append(nut[field])

        # Session Log notes (multiple sessions per day)
        if sessions_by_date:
            for session in sessions_by_date.get(d, []):
                note = session.get("Notes", "")
                if note:
                    notes_texts.append(note)

        # Sleep notes
        if sleep_by_date:
            sleep_row = sleep_by_date.get(d, {})
            sleep_note = sleep_row.get("Notes", "")
            if sleep_note:
                notes_texts.append(sleep_note)

        combined = " ".join(notes_texts)
        if not combined.strip():
            continue

        # LLM extraction with keyword fallback
        behaviors = extract_behaviors(combined)
        day_flags = behaviors_to_flags(behaviors, d)
        flags.extend(day_flags)

    return flags


# ---------------------------------------------------------------------------
# Readiness Score Composite
# ---------------------------------------------------------------------------

def _z_to_score(z):
    """Map z-score to 1-10 using sigmoid curve (more sensitive in decision zone).

    Sigmoid: score = 1 + 9 / (1 + exp(-1.5 * z))
    Compared to linear (6 + z*2):
      - More sensitive in the 5-7 range where Fair/Good decisions happen
      - Compresses at extremes (±3 SD) instead of hard clipping
      - z=0 -> ~5.5, z=+1 -> ~7.7, z=+2 -> ~9.3, z=-1 -> ~3.3, z=-2 -> ~1.7
    Modeled after WHOOP/Oura approach (sigmoid/logistic scoring curves).
    """
    return 1 + 9 / (1 + math.exp(-1.5 * z))


def compute_adaptive_weights(conn, min_days=60):
    """Compute personalized readiness weights via constrained regression.

    Regresses readiness component z-scores against next-day outcomes
    (morning energy, day rating). Only updates weights if R² improves
    over evidence-based defaults by > 0.05 — avoids overfitting noise.

    Args:
        conn: SQLite connection
        min_days: Minimum paired observations required (default 60)

    Returns:
        dict with keys {HRV, Sleep, RHR, Subjective, r_squared, r_squared_default,
        delta_r_squared, date, n} if improvement found, else None.
    """
    if conn is None:
        return None

    try:
        from scipy.optimize import minimize
    except ImportError:
        print("  Adaptive weighting: scipy not installed, skipping")
        return None

    # Query component z-scores from overall_analysis + next-day outcomes from daily_log
    cur = conn.execute("""
        SELECT oa.date,
               oa.readiness_score,
               g.hrv_overnight_avg, g.sleep_score, g.resting_hr
        FROM overall_analysis oa
        JOIN garmin g ON oa.date = g.date
        ORDER BY oa.date ASC
    """)
    oa_rows = {row[0]: {"readiness": row[1], "hrv": row[2], "sleep": row[3], "rhr": row[4]}
               for row in cur.fetchall()}

    cur = conn.execute("""
        SELECT date, morning_energy, day_rating
        FROM daily_log
        WHERE morning_energy IS NOT NULL OR day_rating IS NOT NULL
    """)
    dl_rows = {row[0]: {"energy": row[1], "rating": row[2]} for row in cur.fetchall()}

    # Pair Day N components → Day N+1 outcomes
    from datetime import date as date_cls, timedelta
    pairs = []
    for d_str, oa in oa_rows.items():
        try:
            d = date_cls.fromisoformat(d_str)
        except (ValueError, TypeError):
            continue
        next_d = str(d + timedelta(days=1))
        if next_d not in dl_rows:
            continue
        dl = dl_rows[next_d]
        outcome_vals = [v for v in [dl.get("energy"), dl.get("rating")] if v is not None]
        if not outcome_vals:
            continue
        outcome = sum(outcome_vals) / len(outcome_vals)

        hrv = oa.get("hrv")
        sleep = oa.get("sleep")
        rhr = oa.get("rhr")
        if hrv is None or sleep is None or rhr is None:
            continue
        pairs.append((hrv, sleep, rhr, outcome))

    if len(pairs) < min_days:
        print(f"  Adaptive weighting: {len(pairs)} paired observations "
              f"(need {min_days}), keeping defaults")
        return None

    import numpy as np
    X = np.array([(p[0], p[1], p[2]) for p in pairs])
    y = np.array([p[3] for p in pairs])

    # Standardize predictors
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_std[X_std == 0] = 1
    X_z = (X - X_mean) / X_std

    # Add subjective column as zeros (no data in predictors from garmin)
    # Subjective weight will be constrained but not data-driven
    n_components = 4  # HRV, Sleep, RHR, Subjective

    def neg_r_squared(weights_3):
        """Negative R² for 3 garmin components (Subjective gets remainder)."""
        w_subj = 1.0 - sum(weights_3)
        if w_subj < 0.05 or w_subj > 0.50:
            return 1.0  # penalty
        pred = X_z @ weights_3
        ss_res = np.sum((y - pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        if ss_tot == 0:
            return 1.0
        return -(1 - ss_res / ss_tot)

    # Default weights for comparison (HRV=0.35, Sleep=0.30, RHR=0.20)
    default_w = np.array([0.35, 0.30, 0.20])
    default_pred = X_z @ default_w
    ss_res_default = np.sum((y - default_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2_default = 1 - ss_res_default / ss_tot if ss_tot > 0 else 0

    # Optimize with bounds
    bounds = [(0.05, 0.50), (0.05, 0.50), (0.05, 0.50)]
    result = minimize(neg_r_squared, default_w, method='L-BFGS-B', bounds=bounds)

    if not result.success:
        print(f"  Adaptive weighting: optimization failed ({result.message})")
        return None

    r2_adaptive = -result.fun
    delta = r2_adaptive - r2_default

    w_hrv, w_sleep, w_rhr = result.x
    w_subj = 1.0 - sum(result.x)

    # Only update if meaningful improvement
    if delta <= 0.05:
        print(f"  Adaptive weighting: no significant improvement "
              f"(ΔR²={delta:.3f} ≤ 0.05), keeping defaults")
        return None

    weights = {
        "HRV": round(float(w_hrv), 3),
        "Sleep": round(float(w_sleep), 3),
        "RHR": round(float(w_rhr), 3),
        "Subjective": round(float(w_subj), 3),
        "r_squared": round(float(r2_adaptive), 3),
        "r_squared_default": round(float(r2_default), 3),
        "delta_r_squared": round(float(delta), 3),
        "n": len(pairs),
        "date": str(date_cls.today()),
    }
    print(f"  Adaptive weighting: improvement found (ΔR²={delta:.3f})")
    print(f"    New weights: HRV={w_hrv:.1%}, Sleep={w_sleep:.1%}, "
          f"RHR={w_rhr:.1%}, Subjective={w_subj:.1%}")
    return weights


def compute_readiness(baselines, sleep_context, daily_log_by_date, target_date,
                      profile=None):
    """Compute composite readiness score (1-10) from 4 evidence-weighted components.

    Evidence-based weights (JAMA MESA 2020, Frontiers HRV meta-review 2019):
      1. HRV status   — 35% (strongest single predictor of cognitive/physical readiness)
      2. Sleep quality — 30% (second strongest; architecture + debt matter most)
      3. RHR status   — 20% (lagging indicator, less predictive than HRV)
      4. Subjective    — 15% (unreliable after 3+ days restriction; Van Dongen 2003)

    When components are missing, remaining weights are re-normalized to sum to 1.0.

    Returns (score, label, components_detail, confidence).
    """
    # Evidence-based weights from thresholds.json: HRV > Sleep > RHR > Subjective
    COMPONENT_WEIGHTS = dict(_THRESHOLDS["component_weights"])  # copy so we can modify

    # Adaptive weights disabled until feature-space mismatch is resolved.
    # Only load if explicitly enabled in user_config.json.
    from utils import load_user_config
    _user_cfg = load_user_config()
    if _user_cfg.get("enable_adaptive_weights", False):
        adaptive_weight_overrides = _user_cfg.get("adaptive_weights", {}).get("readiness_weights")
        if adaptive_weight_overrides:
            COMPONENT_WEIGHTS.update(adaptive_weight_overrides)

    # Apply profile threshold overrides (takes precedence over adaptive)
    if profile:
        overrides = get_threshold_overrides(profile)
        weight_overrides = overrides.get("readiness_weights")
        if weight_overrides:
            COMPONENT_WEIGHTS.update(weight_overrides)

    # Extract sleep context from tuple (text, debt, trend, debt_night_count)
    sleep_debt = None
    debt_night_count = 0
    if isinstance(sleep_context, tuple) and len(sleep_context) >= 2:
        sleep_debt = sleep_context[1]
    if isinstance(sleep_context, tuple) and len(sleep_context) >= 4:
        debt_night_count = sleep_context[3] or 0

    # Van Dongen subjective penalty: after 3+ nights of sleep debt > 0.75h
    # in the last 5 nights, subjective ratings become unreliable (Van Dongen
    # et al. 2003 showed subjective sleepiness plateaus while cognitive
    # impairment continues). Reduce Subjective weight by 50%.
    VAN_DONGEN_MIN_DEBT_NIGHTS = 3
    van_dongen_penalty = False
    if debt_night_count >= VAN_DONGEN_MIN_DEBT_NIGHTS:
        COMPONENT_WEIGHTS["Subjective"] = COMPONENT_WEIGHTS.get("Subjective", 0.15) * 0.5
        van_dongen_penalty = True

    components = {}

    # 1. HRV Status (z-score -> 1-10 via sigmoid)
    hrv_z = baselines.get("hrv", {}).get("z")
    if hrv_z is not None:
        hrv_score = _z_to_score(hrv_z)
        components["HRV"] = (hrv_score, f"z={hrv_z:+.1f}")

    # 2. RHR Status (inverted z-score -> 1-10 via sigmoid; lower RHR is better)
    rhr_z = baselines.get("rhr", {}).get("z")
    if rhr_z is not None:
        rhr_score = _z_to_score(-rhr_z)  # invert: low RHR = positive
        components["RHR"] = (rhr_score, f"z={rhr_z:+.1f}")

    # 3. Sleep Quality — blend Garmin Sleep Score and Sleep Analysis Score (50/50)
    # Sleep Analysis Score is architecture-aware and catches cases where Garmin
    # overweights duration. Blending stabilizes the signal while incorporating
    # the architecture critique. Fallback order: blended > analysis > garmin > raw.
    garmin_sleep_z = baselines.get("sleep_score", {}).get("z")
    analysis_sleep_z = baselines.get("sleep_analysis_score", {}).get("z")
    sleep_score_today = baselines.get("sleep_score", {}).get("today")

    if garmin_sleep_z is not None and analysis_sleep_z is not None:
        # Blend: 50% Garmin z-score + 50% Analysis z-score
        garmin_component = _z_to_score(garmin_sleep_z)
        analysis_component = _z_to_score(analysis_sleep_z)
        sleep_component = 0.5 * garmin_component + 0.5 * analysis_component
        components["Sleep"] = (sleep_component,
                               f"garmin_z={garmin_sleep_z:+.1f}, analysis_z={analysis_sleep_z:+.1f}")
    elif analysis_sleep_z is not None:
        sleep_component = _z_to_score(analysis_sleep_z)
        components["Sleep"] = (sleep_component, f"analysis_z={analysis_sleep_z:+.1f}")
    elif garmin_sleep_z is not None:
        sleep_component = _z_to_score(garmin_sleep_z)
        components["Sleep"] = (sleep_component, f"garmin_z={garmin_sleep_z:+.1f}")
    elif sleep_score_today is not None:
        sleep_component = max(1, min(10, sleep_score_today / 10))
        components["Sleep"] = (sleep_component, f"raw={sleep_score_today:.0f}")

    # 4. Subjective Wellness (Morning Energy + prev Day Rating + prev Midday Body Feel)
    today_dl = daily_log_by_date.get(str(target_date), {})
    morning_energy = _safe_float(today_dl.get("Morning Energy (1-10)"))
    prev_dl = daily_log_by_date.get(str(target_date - timedelta(days=1)), {})
    prev_day_rating = _safe_float(prev_dl.get("Day Rating (1-10)"))
    prev_body_feel = _safe_float(prev_dl.get("Midday Body Feel (1-10)"))

    subj_values = [v for v in [morning_energy, prev_day_rating, prev_body_feel]
                   if v is not None]
    if subj_values:
        subj_score = sum(subj_values) / len(subj_values)
        detail = []
        if morning_energy is not None:
            detail.append(f"morning={morning_energy:.0f}")
        if prev_day_rating is not None:
            detail.append(f"prev_day={prev_day_rating:.0f}")
        if prev_body_feel is not None:
            detail.append(f"body_feel={prev_body_feel:.0f}")
        if van_dongen_penalty:
            detail.append("VAN_DONGEN_PENALTY")
        components["Subjective"] = (subj_score, ", ".join(detail))

    # Composite score — weighted, re-normalized for missing components
    if not components:
        return None, "N/A", {}, "Low"

    weight_sum = sum(COMPONENT_WEIGHTS[k] for k in components)
    score = sum(components[k][0] * COMPONENT_WEIGHTS[k] for k in components) / weight_sum
    score = round(score, 1)

    # Label (use profile overrides if available, else global defaults)
    labels = READINESS_LABELS
    if profile:
        overrides = get_threshold_overrides(profile)
        label_overrides = overrides.get("readiness_labels")
        if label_overrides:
            labels = [(entry["min_score"], entry["label"]) for entry in label_overrides]
    label = "Poor"
    for threshold, lbl in labels:
        if score >= threshold:
            label = lbl
            break

    # Confidence — based on data sufficiency across all objective components
    # Uses minimum baseline depth across present objective components (HRV, RHR, Sleep)
    # to prevent high confidence when one key signal has thin data.
    # Sleep objective n tracks which sleep signal(s) actually contributed to readiness.
    available = len(components)
    objective_ns = []
    for _obj_key in ("hrv", "rhr"):
        _obj_bl = baselines.get(_obj_key, {})
        if _obj_bl.get("z") is not None:
            objective_ns.append(_obj_bl.get("n", 0))
    # Sleep: match the same branching used for the readiness score above
    if garmin_sleep_z is not None and analysis_sleep_z is not None:
        # Both contributed — weakest link of the pair limits confidence
        objective_ns.append(min(
            baselines.get("sleep_score", {}).get("n", 0),
            baselines.get("sleep_analysis_score", {}).get("n", 0),
        ))
    elif analysis_sleep_z is not None:
        objective_ns.append(baselines.get("sleep_analysis_score", {}).get("n", 0))
    elif garmin_sleep_z is not None:
        objective_ns.append(baselines.get("sleep_score", {}).get("n", 0))
    # Raw fallback (sleep_score_today without z-score) is not z-scored, so no objective n
    min_objective_n = min(objective_ns) if objective_ns else 0

    conf_thresholds = _THRESHOLDS["confidence"]
    if available >= 4 and min_objective_n >= conf_thresholds["high_min_n"]:
        confidence = "High"
    elif available >= 3 and min_objective_n >= conf_thresholds["medium_high_min_n"]:
        confidence = "Medium-High"
    elif available >= 2 and min_objective_n >= conf_thresholds["medium_min_n"]:
        confidence = "Medium"
    else:
        confidence = "Low"

    return score, label, components, confidence


def _assess_data_quality(baselines, components, by_date_garmin, by_date_sleep,
                         target_date):
    """Assess data completeness and quality for the current readiness output.

    Returns (data_quality, analysis_quality) dicts.
    """
    ALL_COMPONENTS = {"HRV", "RHR", "Sleep", "Subjective"}
    present = set(components.keys()) if components else set()
    missing = ALL_COMPONENTS - present

    degraded = []
    flags = []

    # Garmin data freshness
    target_str = str(target_date)
    garmin_row = by_date_garmin.get(target_str)
    if not garmin_row:
        flags.append("No Garmin data for target date")

    # Sleep record completeness
    sleep_row = by_date_sleep.get(target_str)
    if sleep_row:
        deep = sleep_row.get("Deep (min)", "")
        rem = sleep_row.get("REM (min)", "")
        if not deep and not rem:
            degraded.append("Sleep")
            flags.append("Sleep: missing stage data (deep/REM)")

    # Sleep analysis-only mode
    if "Sleep" in present and components.get("Sleep"):
        detail = components["Sleep"][1] if len(components["Sleep"]) > 1 else ""
        if "analysis_z=" in detail and "garmin_z=" not in detail:
            flags.append("Sleep: analysis-only (no Garmin score)")

    # Van Dongen penalty detection
    if "Subjective" in present and components.get("Subjective"):
        detail = components["Subjective"][1] if len(components["Subjective"]) > 1 else ""
        if "VAN_DONGEN_PENALTY" in detail:
            flags.append("Subjective weight reduced (Van Dongen penalty)")

    # Thin baselines
    for key, label in [("hrv", "HRV"), ("rhr", "RHR"), ("sleep_score", "Sleep Score")]:
        bl = baselines.get(key, {})
        n = bl.get("n", 0)
        if bl.get("z") is not None and n < 14:
            flags.append(f"{label}: thin baseline (n={n})")

    # Analysis quality basis
    n_present = len(present)
    if n_present >= 4:
        basis = "full"
    elif n_present >= 2:
        basis = "partial"
    else:
        basis = "minimal"

    data_quality = {
        "present": sorted(present),
        "missing": sorted(missing),
        "degraded": degraded,
        "flags": flags,
    }
    analysis_quality = {
        "basis": basis,
        "missing_inputs": sorted(missing),
        "warnings": flags,
    }
    return data_quality, analysis_quality


# ---------------------------------------------------------------------------
# Insight Generation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Dynamic Knowledge Trigger Scanner
# ---------------------------------------------------------------------------

def _eval_simple_trigger(trigger, data_sources, sessions_by_date, target_date):
    """Evaluate a simple threshold trigger against actual data.

    trigger schema:
      {"tab": "garmin"|"sleep"|"daily_log"|"nutrition",
       "field": "column header",
       "op": "<"|">"|"<="|">=",
       "value": number,
       "agg": "any"|"avg"|"all",
       "lookback": int (days),
       "requires_session": bool (optional)}

    Returns (fired: bool, context_str: str) where context_str has the data
    that triggered it (e.g., "avg 6,234 steps over 7 days").
    """
    tab_data = data_sources.get(trigger["tab"], {})
    lookback = trigger.get("lookback", 3)
    field = trigger["field"]
    values = []

    for offset in range(0, lookback):
        d = str(target_date - timedelta(days=offset))
        row = tab_data.get(d)
        if row:
            v = _safe_float(row.get(field))
            if v is not None:
                values.append((d, v))

    if not values:
        return False, ""

    op = trigger["op"]
    threshold = trigger["value"]
    agg = trigger.get("agg", "any")

    def _compare(val, op_, thresh):
        if op_ == "<": return val < thresh
        if op_ == ">": return val > thresh
        if op_ == "<=": return val <= thresh
        if op_ == ">=": return val >= thresh
        return False

    # Check requires_session: only fire if there was a training session on a
    # day that also meets the threshold condition
    if trigger.get("requires_session"):
        for d, v in values:
            if _compare(v, op, threshold) and sessions_by_date.get(d):
                session_name = sessions_by_date[d][0].get("Activity Name", "workout")
                return True, f"{field} was {v:.1f} on {d} (training: {session_name})"
        return False, ""

    if agg == "any":
        for d, v in values:
            if _compare(v, op, threshold):
                return True, f"{field} was {v:.1f} on {d}"
        return False, ""
    elif agg == "avg":
        avg_val = sum(v for _, v in values) / len(values)
        if _compare(avg_val, op, threshold):
            return True, f"avg {field} {avg_val:.1f} over {len(values)} days"
        return False, ""
    elif agg == "all":
        if all(_compare(v, op, threshold) for _, v in values):
            return True, f"{field} {op} {threshold} all {len(values)} days"
        return False, ""

    return False, ""


def _eval_compound_trigger(trigger, data_sources, sessions_by_date, target_date):
    """Evaluate a compound trigger (all conditions must be true)."""
    contexts = []
    for condition in trigger.get("conditions", []):
        fired, ctx = _eval_simple_trigger(condition, data_sources, sessions_by_date, target_date)
        if not fired:
            return False, ""
        contexts.append(ctx)
    return True, " + ".join(contexts)


def _eval_divergence_trigger(trigger, data_sources, target_date):
    """Evaluate a divergence trigger (subjective vs objective metrics disagree)."""
    lookback = trigger.get("lookback", 3)
    subj = trigger["subjective"]
    obj = trigger["objective"]

    subj_data = data_sources.get(subj["tab"], {})
    obj_data = data_sources.get(obj["tab"], {})

    divergence_days = 0
    for offset in range(0, lookback):
        d = str(target_date - timedelta(days=offset))
        sv = _safe_float(subj_data.get(d, {}).get(subj["field"]))
        ov = _safe_float(obj_data.get(d, {}).get(obj["field"]))

        if sv is None or ov is None:
            continue

        subj_ok = (sv >= subj["value"]) if subj["op"] == ">=" else (sv <= subj["value"])
        obj_bad = (ov < obj["value"]) if obj["op"] == "<" else (ov > obj["value"])

        if subj_ok and obj_bad:
            divergence_days += 1

    if divergence_days >= 2:
        return True, f"subjective energy OK but sleep score low for {divergence_days} days"
    return False, ""


def _eval_variance_trigger(trigger, data_sources, target_date):
    """Evaluate a variance trigger (e.g., wake time inconsistency)."""
    tab_data = data_sources.get(trigger["tab"], {})
    field = trigger["field"]
    lookback = trigger.get("lookback", 7)
    max_std = trigger.get("max_std_minutes", 30)

    times_minutes = []
    for offset in range(0, lookback):
        d = str(target_date - timedelta(days=offset))
        row = tab_data.get(d, {})
        time_str = row.get(field, "")
        if time_str and ":" in time_str:
            try:
                parts = time_str.split(":")
                minutes = int(parts[0]) * 60 + int(parts[1].split()[0])
                # Handle AM/PM if present
                if "PM" in time_str.upper() and int(parts[0]) != 12:
                    minutes += 720
                elif "AM" in time_str.upper() and int(parts[0]) == 12:
                    minutes -= 720
                times_minutes.append(minutes)
            except (ValueError, IndexError):
                continue

    if len(times_minutes) < 3:
        return False, ""

    mean_t = sum(times_minutes) / len(times_minutes)
    variance = sum((t - mean_t) ** 2 for t in times_minutes) / len(times_minutes)
    std_minutes = variance ** 0.5

    if std_minutes > max_std:
        return True, f"wake time std dev {std_minutes:.0f} min over {len(times_minutes)} days (threshold: {max_std} min)"
    return False, ""


def _eval_trend_trigger(trigger, data_sources, target_date):
    """Evaluate a trend trigger — fires when metric declines/improves for N days.

    trigger schema:
      {"type": "trend", "tab": str, "field": str,
       "direction": "declining"|"improving", "min_days": int (default 3)}
    """
    tab_data = data_sources.get(trigger["tab"], {})
    field = trigger["field"]
    min_days = trigger.get("min_days", 3)
    direction = trigger.get("direction", "declining")
    lookback = min_days + 2  # extra buffer for missing days

    values = []
    for offset in range(0, lookback):
        d = str(target_date - timedelta(days=offset))
        row = tab_data.get(d, {})
        v = _safe_float(row.get(field))
        if v is not None:
            values.append(v)
        if len(values) >= min_days + 1:
            break

    if len(values) < min_days:
        return False, ""

    # Check consecutive direction (values[0] = today, values[1] = yesterday, ...)
    consecutive = 0
    for i in range(len(values) - 1):
        if direction == "declining" and values[i] < values[i + 1]:
            consecutive += 1
        elif direction == "improving" and values[i] > values[i + 1]:
            consecutive += 1
        else:
            break

    if consecutive >= min_days - 1:
        return True, (f"{field} {direction} for {consecutive + 1} consecutive days "
                      f"({values[-1]:.1f} -> {values[0]:.1f})")
    return False, ""


def _eval_streak_trigger(trigger, data_sources, target_date):
    """Evaluate a streak trigger — fires when metric stays above/below threshold for N days.

    trigger schema:
      {"type": "streak", "tab": str, "field": str,
       "op": "<"|">"|"<="|">=", "value": number, "min_days": int (default 3)}
    """
    tab_data = data_sources.get(trigger["tab"], {})
    field = trigger["field"]
    min_days = trigger.get("min_days", 3)
    op = trigger["op"]
    threshold = trigger["value"]

    def _compare(val, op_, thresh):
        if op_ == "<": return val < thresh
        if op_ == ">": return val > thresh
        if op_ == "<=": return val <= thresh
        if op_ == ">=": return val >= thresh
        return False

    consecutive = 0
    for offset in range(0, min_days + 2):
        d = str(target_date - timedelta(days=offset))
        row = tab_data.get(d, {})
        v = _safe_float(row.get(field))
        if v is not None and _compare(v, op, threshold):
            consecutive += 1
        else:
            break

    if consecutive >= min_days:
        return True, f"{field} {op} {threshold} for {consecutive} consecutive days"
    return False, ""


_PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


# ---------------------------------------------------------------------------
# Contradiction Resolution Engine
# ---------------------------------------------------------------------------

def _pearson_r_and_p(xs, ys):
    """Compute Pearson r and two-tailed p-value for paired lists.

    Returns (r, p, n).  Falls back to (0.0, 1.0, n) on degenerate input.
    """
    n = len(xs)
    if n < 5:
        return 0.0, 1.0, n
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx == 0 or sy == 0:
        return 0.0, 1.0, n
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    r = sxy / (sx * sy) ** 0.5
    # Two-tailed p-value via t-distribution normal approximation
    if abs(r) >= 1.0:
        return r, 0.0, n
    t_stat = r * math.sqrt((n - 2) / (1 - r * r))
    z = abs(t_stat)
    if z > 8:
        return r, 0.0, n
    b1, b2, b3, b4, b5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    t_val = 1.0 / (1.0 + 0.2316419 * z)
    poly = t_val * (b1 + t_val * (b2 + t_val * (b3 + t_val * (b4 + t_val * b5))))
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    p = 2.0 * (1.0 - (1.0 - pdf * poly))
    return r, max(p, 0.0), n


def _check_personal_correlation(validation_pair, conn):
    """Check personal data correlation for a contradiction group member.

    Uses the explicit validation_pair spec to query SQLite and compute Pearson r.

    Returns dict:
      {"status": "confirmed"|"refuted"|"inconclusive"|"insufficient_data",
       "r": float, "n": int, "p": float}
    """
    if not validation_pair or not conn:
        return {"status": "insufficient_data", "r": 0.0, "n": 0, "p": 1.0}

    pred = validation_pair.get("predictor", {})
    outcome = validation_pair.get("outcome", {})
    lag_days = validation_pair.get("lag_days", 1)
    expected_dir = validation_pair.get("expected_direction", "none")

    pred_tab = pred.get("tab", "")
    pred_field = pred.get("field", "")
    out_tab = outcome.get("tab", "")
    out_field = outcome.get("field", "")

    if not all([pred_tab, pred_field, out_tab, out_field]):
        return {"status": "insufficient_data", "r": 0.0, "n": 0, "p": 1.0}

    # Map tab names to SQLite table names (lowercase, underscored)
    _tab_to_table = {
        "garmin": "garmin", "sleep": "sleep", "daily_log": "daily_log",
        "nutrition": "nutrition", "session_log": "session_log",
        "overall_analysis": "overall_analysis",
    }
    pred_table = _tab_to_table.get(pred_tab, pred_tab)
    out_table = _tab_to_table.get(out_tab, out_tab)

    # Build query — join predictor day to outcome day+lag
    try:
        cursor = conn.cursor()
        # Get column names from both tables to find best match
        query = f"""
            SELECT p."{pred_field}", o."{out_field}"
            FROM {pred_table} p
            JOIN {out_table} o ON date(p.date, '+{lag_days} day') = o.date
            WHERE p."{pred_field}" IS NOT NULL
              AND o."{out_field}" IS NOT NULL
              AND p."{pred_field}" != ''
              AND o."{out_field}" != ''
            ORDER BY p.date DESC
            LIMIT 90
        """
        cursor.execute(query)
        rows = cursor.fetchall()
    except Exception:
        return {"status": "insufficient_data", "r": 0.0, "n": 0, "p": 1.0}

    # Parse numeric values
    xs, ys = [], []
    for pv, ov in rows:
        try:
            xs.append(float(pv))
            ys.append(float(ov))
        except (ValueError, TypeError):
            continue

    if len(xs) < 20:
        return {"status": "insufficient_data", "r": 0.0, "n": len(xs), "p": 1.0}

    r, p, n = _pearson_r_and_p(xs, ys)

    # Determine status based on thresholds and expected direction
    if abs(r) < 0.15 or p >= 0.10:
        return {"status": "inconclusive", "r": r, "n": n, "p": p}

    if abs(r) >= 0.20 and n >= 20 and p < 0.05:
        # Check direction match
        if expected_dir == "positive" and r > 0:
            return {"status": "confirmed", "r": r, "n": n, "p": p}
        elif expected_dir == "negative" and r < 0:
            return {"status": "confirmed", "r": r, "n": n, "p": p}
        elif expected_dir == "none":
            # Entry claims no relationship but we found one
            return {"status": "refuted", "r": r, "n": n, "p": p}
        else:
            # Direction opposes expected
            return {"status": "refuted", "r": r, "n": n, "p": p}

    return {"status": "inconclusive", "r": r, "n": n, "p": p}


def _build_contested_insight(group_entries, personal_result):
    """Build a merged insight when a contradiction group has no clear winner.

    Returns (priority_int, insight_text) where insight_text is prefixed with
    [CONTESTED] for downstream detection (stripped before display).
    """
    # Sort by evidence tier (strongest first)
    sorted_entries = sorted(group_entries, key=lambda e: e.get("evidence_tier", 7))

    domain = sorted_entries[0].get("domain", "Health")
    group_id = sorted_entries[0].get("contradiction_group", "unknown")

    # Build position summaries (max 2 for readability)
    positions = []
    for i, entry in enumerate(sorted_entries[:2]):
        letter = chr(65 + i)  # A, B
        cit_short = entry.get("citation", "").split(";")[0].strip()[:60]
        interp_short = entry.get("interpretation", "")[:120]
        positions.append(f"Position {letter} ({cit_short}): {interp_short}")

    # Personal data summary
    if personal_result and personal_result.get("n", 0) >= 5:
        r_val = personal_result.get("r", 0)
        n_val = personal_result.get("n", 0)
        status = personal_result.get("status", "inconclusive")
        personal_text = f"Your data ({n_val} days): r={r_val:+.2f} ({status})"
    else:
        personal_text = "Your data: insufficient for comparison"

    # Conservative recommendation
    cons_rec = sorted_entries[0].get("conservative_recommendation")
    if not cons_rec:
        # Fall back to higher-evidence entry's recommendation with caveat
        best_rec = sorted_entries[0].get("recommendation", "")
        if best_rec:
            cons_rec = f"Evidence is mixed -- cautiously: {best_rec[:150]}"
        else:
            cons_rec = "Monitor this metric and discuss with your provider if concerned."

    # Priority = max (highest urgency) of all group members
    max_priority = min(
        _PRIORITY_ORDER.get(e.get("priority", "Medium"), 3)
        for e in group_entries
    )

    text_parts = [
        f"[CONTESTED] [{domain}] Evidence is mixed ({group_id}). ",
        ". ".join(positions) + ". ",
        personal_text + ". ",
        f"Conservative recommendation: {cons_rec[:200]}",
    ]

    return (max_priority, "".join(text_parts))


def resolve_contradiction_groups(fired_entries, knowledge):
    """Apply hierarchical resolution to fired entries in the same contradiction_group.

    Args:
        fired_entries: list of (kb_id, entry, priority_int, context_str) tuples
        knowledge: full KB dict {id: entry}

    Returns list of resolved tuples:
        (kb_id, entry, priority_int, context_str, resolution_metadata)
    where resolution_metadata = {"resolution": str, "annotation": str|None,
                                  "merged_text": str|None}
    """
    # Group by contradiction_group
    groups = {}  # group_id -> [(kb_id, entry, priority, context)]
    ungrouped = []

    for kb_id, entry, priority, context in fired_entries:
        group_id = entry.get("contradiction_group")
        if group_id:
            groups.setdefault(group_id, []).append((kb_id, entry, priority, context))
        else:
            ungrouped.append((kb_id, entry, priority, context))

    resolved = []

    # Pass through ungrouped entries unchanged
    for kb_id, entry, priority, context in ungrouped:
        # Check conflicts_with_hardcoded
        conflicts = entry.get("conflicts_with_hardcoded") or []
        if conflicts and any(cid in _hardcoded_kb_ids for cid in conflicts):
            # This KB entry conflicts with a hardcoded insight that already fired.
            # Suppress the dynamic entry (hardcoded insights are well-vetted).
            print(f"  [contradiction] Suppressed {kb_id}: conflicts with hardcoded "
                  f"{[c for c in conflicts if c in _hardcoded_kb_ids]}")
            continue
        resolved.append((kb_id, entry, priority, context,
                         {"resolution": "sole", "annotation": None, "merged_text": None}))

    # Resolve each contradiction group
    for group_id, members in groups.items():
        if len(members) == 1:
            kb_id, entry, priority, context = members[0]
            resolved.append((kb_id, entry, priority, context,
                             {"resolution": "sole", "annotation": None, "merged_text": None}))
            continue

        # Sort by evidence tier (ascending = strongest first)
        members.sort(key=lambda m: m[1].get("evidence_tier", 7))
        strongest = members[0]
        weakest = members[-1]
        tier_gap = weakest[1].get("evidence_tier", 7) - strongest[1].get("evidence_tier", 7)

        if tier_gap >= 2:
            # Clear evidence winner — fire the strongest, suppress the rest
            kb_id, entry, priority, context = strongest
            suppressed = [m[0] for m in members[1:]]
            print(f"  [contradiction] Group '{group_id}': {kb_id} wins (tier {entry.get('evidence_tier')}) "
                  f"over {suppressed}")
            resolved.append((kb_id, entry, priority, context,
                             {"resolution": "evidence_winner", "annotation": None,
                              "merged_text": None}))
            continue

        # Close evidence — check personal validation (precomputed)
        personal = strongest[1].get("personal_validation")
        if personal and personal.get("status") == "confirmed":
            kb_id, entry, priority, context = strongest
            r_val = personal.get("r", 0)
            n_val = personal.get("n", 0)
            annotation = f"Confirmed by your data (r={r_val:+.2f}, {n_val} days)"
            suppressed = [m[0] for m in members[1:]]
            print(f"  [contradiction] Group '{group_id}': {kb_id} confirmed by personal data "
                  f"over {suppressed}")
            resolved.append((kb_id, entry, priority, context,
                             {"resolution": "personal_confirmed", "annotation": annotation,
                              "merged_text": None}))
            continue

        # Check if a weaker entry is personally confirmed
        for i, (mid, mentry, mpri, mctx) in enumerate(members[1:], 1):
            mp = mentry.get("personal_validation")
            if mp and mp.get("status") == "confirmed":
                r_val = mp.get("r", 0)
                n_val = mp.get("n", 0)
                annotation = f"Confirmed by your data (r={r_val:+.2f}, {n_val} days)"
                suppressed = [m[0] for m in members if m[0] != mid]
                print(f"  [contradiction] Group '{group_id}': {mid} personally confirmed "
                      f"despite weaker evidence, over {suppressed}")
                resolved.append((mid, mentry, mpri, mctx,
                                 {"resolution": "personal_confirmed", "annotation": annotation,
                                  "merged_text": None}))
                break
        else:
            # No personal confirmation — emit merged contested insight
            all_entries = [m[1] for m in members]
            personal_result = personal or {}
            priority_int, merged_text = _build_contested_insight(all_entries, personal_result)
            # Use a synthetic entry for the merged insight
            print(f"  [contradiction] Group '{group_id}': no winner, emitting mixed-evidence insight")
            resolved.append((f"__contested_{group_id}", strongest[1], priority_int, "",
                             {"resolution": "merged_mixed", "annotation": None,
                              "merged_text": merged_text}))

    return resolved


def update_personal_validations(knowledge, conn):
    """Monthly job: compute personal correlations for all contested KB entries.

    For every entry with a contradiction_group and validation_pair, compute
    Pearson correlation from SQLite and store results in the
    kb_personal_validations table (not health_knowledge.json).

    Returns count of entries updated.
    """
    if not conn:
        print("  [validation] No SQLite connection -- skipping personal validations.")
        return 0

    from sqlite_backup import upsert_kb_validation, load_kb_validations

    # Load existing validations from SQLite for skip-if-recent check
    existing_validations = load_kb_validations(conn)

    updated = 0
    today_str = str(date.today())

    for kb_id, entry in knowledge.items():
        group = entry.get("contradiction_group")
        vpair = entry.get("validation_pair")
        if not group or not vpair:
            continue

        # Skip if validated within last 30 days
        existing = existing_validations.get(kb_id, {})
        last_computed = existing.get("last_computed", "")
        if last_computed:
            try:
                days_since = (date.today() - date.fromisoformat(last_computed)).days
                if days_since < 30:
                    continue
            except ValueError:
                pass

        result = _check_personal_correlation(vpair, conn)
        val_data = {
            "status": result["status"],
            "r": round(result["r"], 4),
            "n": result["n"],
            "p": round(result["p"], 6),
            "last_computed": today_str,
        }

        # Write to SQLite
        upsert_kb_validation(
            conn, kb_id, val_data["status"],
            val_data["r"], val_data["n"], val_data["p"], today_str
        )

        # Update in-memory knowledge dict so current run uses fresh data
        entry["personal_validation"] = val_data
        updated += 1

    if updated:
        conn.commit()
        print(f"  [validation] Updated personal validations for {updated} KB entries (SQLite).")

    return updated


def _build_trigger_insight(entry, context, annotation=None):
    """Build an insight string from a knowledge entry that fired a trigger."""
    parts = [f"[{entry['domain']}] {context}. "]
    parts.append(entry["interpretation"][:200])
    if entry.get("cognitive_impact"):
        parts.append(f" Cognitive: {entry['cognitive_impact'][:150]}")
    if entry.get("recommendation"):
        parts.append(f" Action: {entry['recommendation'][:150]}")
    conf = entry.get("confidence", "Pending")
    parts.append(f" [{entry['citation']}: {conf}]")
    if annotation:
        parts.append(f" ({annotation})")
    return "".join(parts)


def scan_knowledge_triggers(knowledge, data_sources, sessions_by_date, target_date):
    """Scan all knowledge entries with triggers and generate insights.

    This is the automatic bridge between health_knowledge.json and the analysis
    engine. When /update-intel adds new entries with trigger fields, they
    automatically fire here without any code changes.

    Phase 1: Fire all triggers, collect structured data.
    Phase 2: Resolve contradictions between fired entries.
    Phase 3: Build insight text from resolved entries.

    Returns list of insight strings sorted by priority (Critical first, Low last).
    """
    # --- Phase 1: Fire triggers and collect structured results ---
    fired_entries = []  # (kb_id, entry, priority_int, context_str)

    for kb_id, entry in knowledge.items():
        trigger = entry.get("trigger")
        if not trigger:
            continue

        # Skip entries already covered by hardcoded insights (dedup)
        if kb_id in _hardcoded_kb_ids:
            continue
        # Skip superseded entries (replaced by a newer entry via contradiction resolution)
        if entry.get("superseded_by"):
            continue

        trigger_type = trigger.get("type", "simple")
        fired = False
        context = ""

        if trigger_type == "simple" or "tab" in trigger:
            fired, context = _eval_simple_trigger(
                trigger, data_sources, sessions_by_date, target_date)
        elif trigger_type == "compound":
            fired, context = _eval_compound_trigger(
                trigger, data_sources, sessions_by_date, target_date)
        elif trigger_type == "divergence":
            fired, context = _eval_divergence_trigger(
                trigger, data_sources, target_date)
        elif trigger_type == "variance":
            fired, context = _eval_variance_trigger(
                trigger, data_sources, target_date)
        elif trigger_type == "trend":
            fired, context = _eval_trend_trigger(
                trigger, data_sources, target_date)
        elif trigger_type == "streak":
            fired, context = _eval_streak_trigger(
                trigger, data_sources, target_date)

        if fired:
            priority = _PRIORITY_ORDER.get(entry.get("priority", "Medium"), 3)
            fired_entries.append((kb_id, entry, priority, context))

    if fired_entries:
        fired_ids = [fe[0] for fe in fired_entries]
        print(f"  [knowledge] Dynamic triggers fired: {', '.join(sorted(fired_ids))}")

    # --- Phase 2: Resolve contradictions ---
    resolved = resolve_contradiction_groups(fired_entries, knowledge)

    # --- Phase 3: Build insight text from resolved entries ---
    insights = []
    for kb_id, entry, priority, context, meta in resolved:
        if meta["resolution"] == "merged_mixed":
            # Merged contested insight — text already built
            insights.append((priority, meta["merged_text"]))
        else:
            text = _build_trigger_insight(entry, context, meta.get("annotation"))
            insights.append((priority, text))

    # Sort by priority (Critical=0 first), cap at 3, return strings only
    insights.sort(key=lambda x: x[0])
    MAX_TRIGGERED_INSIGHTS = 3
    return [text for _, text in insights[:MAX_TRIGGERED_INSIGHTS]]


# Registry of kb_ids used by hardcoded insights in the current analysis run.
# Populated by _kb_insight(), consumed by scan_knowledge_triggers() to avoid duplicates.
_hardcoded_kb_ids = set()


# ---------------------------------------------------------------------------
# Behavioral Correlation Integration (Phase 2)
# ---------------------------------------------------------------------------

def load_significant_correlations(conn=None, min_abs_r=0.15, min_n=30):
    """Load significant behavior-outcome correlations from SQLite.

    Returns: dict keyed by behavior name -> list of {outcome, r, n, lag, label}.
    Only includes correlations where significant=1 AND |r| >= min_abs_r AND n >= min_n.
    """
    import sqlite3
    close_conn = False
    if conn is None:
        db_path = Path(__file__).parent / "health_tracker.db"
        if not db_path.exists():
            return {}
        conn = sqlite3.connect(str(db_path))
        close_conn = True

    try:
        cursor = conn.execute(
            "SELECT behavior, outcome, lag, r, n, label "
            "FROM behavioral_correlations "
            "WHERE significant = 1 AND ABS(r) >= ? AND n >= ? "
            "ORDER BY ABS(r) DESC",
            (min_abs_r, min_n)
        )
        result = {}
        for behavior, outcome, lag, r, n, label in cursor.fetchall():
            result.setdefault(behavior, []).append({
                "outcome": outcome, "r": r, "n": n, "lag": lag, "label": label,
            })
        return result
    except Exception:
        return {}
    finally:
        if close_conn:
            conn.close()


def _personal_validation(correlations, behavior_key, outcome_keyword=None):
    """Check if user's data confirms or contradicts a health claim.

    Args:
        correlations: dict from load_significant_correlations()
        behavior_key: behavior name to look up (e.g., "stress_level", "workout_avg_hr")
        outcome_keyword: optional keyword to match in outcome name (e.g., "HRV", "Sleep")

    Returns: annotation string ("Your data confirms: ...") or empty string.
    """
    if not correlations:
        return ""
    entries = correlations.get(behavior_key, [])
    if not entries:
        return ""
    # Filter by outcome keyword if provided
    if outcome_keyword:
        entries = [e for e in entries if outcome_keyword.lower() in e["outcome"].lower()]
    if not entries:
        return ""
    # Use strongest correlation
    best = max(entries, key=lambda e: abs(e["r"]))
    r = best["r"]
    n = best["n"]
    direction = "suppression" if r < 0 else "increase"
    if abs(r) >= 0.25:
        return (f"Your data confirms: {best['label']} correlates with {best['outcome']} "
                f"{direction} (r={r:+.2f}, n={n})")
    elif abs(r) < 0.10 and n >= 40:
        return (f"Note: this pattern is weak in your data "
                f"({best['label']} -> {best['outcome']}: r={r:+.2f}, n={n})")
    return ""


def _get_active_correlations(correlations, note_flags, baselines, sessions_by_date,
                             target_date, covered_behaviors=None):
    """Find significant correlations that fired today but weren't mentioned in insights.

    Returns: list of max 2 formatted insight strings, sorted by |r| descending.
    """
    if not correlations:
        return []
    if covered_behaviors is None:
        covered_behaviors = set()

    target_str = str(target_date)
    yesterday_str = str(target_date - timedelta(days=1))

    # Map behavior keys to detection: did this behavior happen today/yesterday?
    active_behaviors = {}

    # Check note flags
    for flag in (note_flags or []):
        flag_date, flag_type = flag[0], flag[1]
        if flag_date in (target_str, yesterday_str):
            # Map flag types to correlation behavior keys
            if flag_type == "alcohol":
                active_behaviors["alcohol"] = True
            elif flag_type == "late_caffeine":
                active_behaviors["late_caffeine"] = True
            elif flag_type == "sugar":
                active_behaviors["sugar"] = True
            elif flag_type == "late_meal":
                active_behaviors["late_meal"] = True

    # Check if workout happened yesterday
    if sessions_by_date:
        if sessions_by_date.get(yesterday_str):
            active_behaviors["had_workout"] = True
            active_behaviors["Had Workout"] = True

    # Check stress level
    stress_data = baselines.get("stress", {})
    if stress_data.get("z") is not None and stress_data["z"] > 1.0:
        active_behaviors["stress_level"] = True
        active_behaviors["high_stress_day"] = True
        active_behaviors["High Stress Day (>40)"] = True

    # Find correlations for active behaviors not already covered by insights
    candidates = []
    for behavior_key, entries in correlations.items():
        # Check if this behavior is active
        bk_lower = behavior_key.lower().replace(" ", "_").replace("(", "").replace(")", "")
        is_active = (behavior_key in active_behaviors or
                     bk_lower in active_behaviors or
                     any(bk_lower.startswith(ab.lower()) for ab in active_behaviors))
        if not is_active:
            continue
        # Skip if already covered by hardcoded insights
        if behavior_key in covered_behaviors or bk_lower in covered_behaviors:
            continue
        for entry in entries:
            candidates.append(entry | {"behavior_key": behavior_key})

    # Sort by |r| and take top 2
    candidates.sort(key=lambda e: abs(e["r"]), reverse=True)
    results = []
    for c in candidates[:2]:
        direction = "lower" if c["r"] < 0 else "higher"
        results.append(
            f"YOUR DATA: {c['label']} is associated with {direction} "
            f"{c['outcome']} the next day (r={c['r']:+.2f}, n={c['n']})"
        )
    return results


def _connect_causal_chain(insights, baselines, sleep_debt, acwr, note_flags):
    """Identify when multiple insights share a causal chain and prepend a summary.

    Returns the modified insights list with a chain summary prepended if detected.
    """
    if len(insights) < 2:
        return insights

    # Detect chain patterns by scanning insight text for keywords
    texts_lower = " ".join(insights).lower()

    chains_detected = []

    # Recovery deficit: sleep debt + HRV suppressed
    has_sleep_debt = sleep_debt is not None and sleep_debt > 0.75
    hrv_z = baselines.get("hrv", {}).get("z")
    has_hrv_low = hrv_z is not None and hrv_z < -1.0
    stress_z = baselines.get("stress", {}).get("z")
    has_stress = stress_z is not None and stress_z > 1.0

    if has_sleep_debt and has_hrv_low:
        components = [f"sleep debt {sleep_debt:.1f}h", f"HRV suppressed (z={hrv_z:+.1f})"]
        if has_stress:
            components.append("elevated stress")
        chains_detected.append(("Recovery deficit building", components))

    # Training overreach: ACWR spike + HRV suppressed
    if acwr is not None and acwr > 1.3 and has_hrv_low:
        components = [f"ACWR {acwr:.2f}", f"HRV suppressed (z={hrv_z:+.1f})"]
        chains_detected.append(("Training overload", components))

    # Behavioral cascade: alcohol/caffeine + poor sleep metrics
    has_behavior = any(f[1] in ("alcohol", "late_caffeine", "late_meal")
                       for f in (note_flags or []))
    has_poor_sleep = "sleep debt" in texts_lower or "deep" in texts_lower
    if has_behavior and has_poor_sleep and has_hrv_low:
        behaviors = [f[1] for f in (note_flags or [])
                     if f[1] in ("alcohol", "late_caffeine", "late_meal")]
        chains_detected.append(("Behavioral impact",
                                [", ".join(set(behaviors)), "poor sleep metrics", "HRV dip"]))

    # Good alignment: HRV above baseline + no negatives
    if hrv_z is not None and hrv_z > 1.0 and not has_sleep_debt and not has_stress:
        chains_detected.append(("Strong alignment",
                                ["HRV above baseline", "no sleep debt", "low stress"]))

    if not chains_detected:
        return insights

    # Prepend the highest-priority chain as a summary
    chain_name, components = chains_detected[0]
    summary = f"{chain_name}: {' + '.join(components)}."
    return [summary] + insights


def _kb_insight(knowledge, kb_id, data_prefix, fallback):
    """Build an insight string from knowledge base entry, with fallback.

    Returns: data_prefix + cognitive_impact + citation, or fallback if kb_id not found.
    Entries with confidence="Pending" are used but flagged as not-yet-evaluated.
    """
    _hardcoded_kb_ids.add(kb_id)
    k = knowledge.get(kb_id)
    if not k:
        return fallback
    parts = [data_prefix]
    parts.append(k["interpretation"])
    parts.append(f"Cognitive impact: {k['cognitive_impact']}")
    if k.get("energy_impact"):
        parts.append(f"Energy: {k['energy_impact']}")
    citation = k['citation']
    if k.get("confidence") == "Pending":
        parts.append(f"[{citation} — pending evaluation]")
    else:
        parts.append(f"[{citation}]")
    return " ".join(parts)


def condense_sleep_analysis(sleep_analysis_text):
    """Condense the full sleep analysis from the Sleep tab into a brief insight.

    Fixed output order: Rating -> Bedtime -> Duration -> Deep/REM -> HRV -> Interpretation.
    Returns a single string suitable as the leading Key Insights bullet.
    """
    if not sleep_analysis_text or sleep_analysis_text == "Insufficient data for analysis":
        return None

    text = sleep_analysis_text.strip()

    # Extract verdict (first word before " - ")
    verdict = ""
    body = text
    if " - " in text:
        verdict = text.split(" - ", 1)[0].strip()
        body = text.split(" - ", 1)[1].strip()

    # Extract ACTION section
    action = ""
    if "ACTION:" in body:
        parts = body.split("ACTION:", 1)
        body = parts[0].strip().rstrip(".")
        action = parts[1].strip().rstrip(".")

    # Split body into sentences for metric extraction
    sentences = [s.strip() for s in body.split(". ") if s.strip()]

    # Extract metrics into fixed-order slots by pattern matching
    bedtime = ""
    duration = ""
    deep = ""
    rem = ""
    hrv = ""
    cycles = ""
    other = []

    for s in sentences:
        sl = s.lower()
        # Strip trailing interpretation after " - " for metric lines
        metric_short = s.split(" - ")[0].strip() if " - " in s else s
        if sl.startswith("bedtime"):
            bedtime = metric_short
        elif re.match(r'^\d+\.?\d*h\b', sl) or "total" in sl and ("h " in sl or "hr" in sl):
            duration = metric_short
        elif "severely short" in sl or "too short" in sl:
            duration = metric_short
        elif sl.startswith("deep") or "deep sleep" in sl[:20]:
            deep = metric_short
        elif sl.startswith("rem") or "rem " in sl[:10]:
            rem = metric_short
        elif "hrv" in sl[:15]:
            hrv = metric_short
        elif "sleep cycle" in sl or ("only" in sl[:8] and "cycle" in sl):
            cycles = metric_short
        else:
            other.append(metric_short)

    # Build output in fixed order: Rating | Bedtime | Duration | Deep/REM | HRV | Cycles -> Action
    parts = []
    if verdict:
        parts.append(f"Sleep Review: {verdict}")

    metrics = []
    if bedtime:
        metrics.append(bedtime)
    if duration:
        metrics.append(duration)
    if deep:
        metrics.append(deep)
    if rem:
        metrics.append(rem)
    if hrv:
        metrics.append(hrv)
    if cycles:
        metrics.append(cycles)

    if metrics:
        parts.append(". ".join(metrics))

    if action:
        first_action = action.split(". ")[0] if ". " in action else action
        parts.append(f"-> {first_action}")

    return " ||| ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Profile-aware helpers (PHI-safe — never output condition names)
# ---------------------------------------------------------------------------

def _compute_stress_budget(baselines, profile):
    """Compute personalized stress budget based on profile sensitivity.

    Returns insight string if stress exceeds 70% of adjusted capacity, else None.
    """
    if not profile:
        return None
    stress_conditions = get_relevant_conditions(profile, "stress")
    if not stress_conditions:
        return None

    stress_data = baselines.get("stress", {})
    today_stress = stress_data.get("today")
    stress_mean = stress_data.get("mean")
    if today_stress is None or stress_mean is None:
        return None

    # Condition-adjusted ceiling (lower for stress-sensitive profiles)
    accommodations = get_accommodations(profile)
    adj = accommodations.get("analysis_adjustments", {})
    if adj.get("stress_sensitivity_high"):
        ceiling = stress_mean * 1.1  # tighter ceiling for sensitive profiles
    else:
        ceiling = stress_mean * 1.3  # default: 30% above baseline

    pct = (today_stress / ceiling) * 100 if ceiling > 0 else 0
    if pct > 70:
        return (f"Stress budget at {pct:.0f}% of your adjusted capacity. "
                f"Protect remaining recovery time. Avoid stacking cognitive demands.")
    return None


def analyze_good_day_factors(baselines, by_date_sleep, daily_log_by_date,
                             by_date_garmin, target_date, profile=None):
    """When cognition >= 7, analyze what was different in preceding 24-48h.

    Returns insight string describing what predicted the good day, or None.
    """
    if not profile:
        return None
    memory_conditions = get_relevant_conditions(profile, "cognition")
    if not memory_conditions:
        return None

    today_log = daily_log_by_date.get(str(target_date), {})
    cognition = _safe_float(today_log.get("Cognition (1-10)"))
    if cognition is None or cognition < 7:
        return None

    # Analyze preceding night
    sleep = by_date_sleep.get(str(target_date), {})
    garmin = by_date_garmin.get(str(target_date), {})
    factors = []

    deep = _safe_float(sleep.get("Deep Sleep (min)"))
    if deep is not None and deep > 55:
        factors.append(f"deep sleep {deep:.0f}min (above 55min threshold)")

    hrv = _safe_float(garmin.get("HRV (overnight avg)"))
    if hrv is None:
        hrv = _safe_float(sleep.get("Overnight HRV (ms)"))
    hrv_baseline = baselines.get("hrv", {}).get("mean")
    if hrv is not None and hrv_baseline and hrv > hrv_baseline * 1.1:
        factors.append(f"HRV {hrv:.0f}ms ({((hrv/hrv_baseline)-1)*100:.0f}% above baseline)")

    rhr = _safe_float(garmin.get("Resting HR"))
    rhr_baseline = baselines.get("rhr", {}).get("mean")
    if rhr is not None and rhr_baseline and rhr < rhr_baseline * 0.95:
        factors.append(f"RHR {rhr:.0f} ({((rhr_baseline-rhr)/rhr_baseline)*100:.0f}% below baseline)")

    bb = _safe_float(garmin.get("Body Battery (at wake)"))
    if bb is not None and bb >= 80:
        factors.append(f"body battery at wake {bb:.0f}")

    if factors:
        return (f"GOOD DAY FORENSICS (cognition {cognition:.0f}/10): "
                f"preceding night had {', '.join(factors)}. "
                f"These conditions predict your best cognitive days.")
    return None


def analyze_food_cognition_lag(nutrition_by_date, daily_log_by_date,
                               target_date, profile=None):
    """Check if specific food categories predict next-day cognition drops.

    Scans 30 days for sugar/refined carb keywords in meals vs next-day cognition.
    Returns insight string if consistent pattern found, else None.
    """
    if not profile:
        return None
    memory_conditions = get_relevant_conditions(profile, "cognition")
    if not memory_conditions:
        return None

    sugar_cog = []  # (has_sugar_bool, next_day_cognition)
    for offset in range(1, 31):
        d = target_date - timedelta(days=offset)
        d_str = str(d)
        next_d_str = str(d + timedelta(days=1))

        nut = nutrition_by_date.get(d_str, {})
        next_log = daily_log_by_date.get(next_d_str, {})
        cog = _safe_float(next_log.get("Cognition (1-10)"))
        if cog is None:
            continue

        # Check meal columns for sugar keywords
        meal_text = " ".join(
            str(nut.get(col, "")) for col in
            ["Breakfast", "Lunch", "Dinner", "Snacks"]
        ).lower()

        has_sugar = any(kw in meal_text for kw in SUGAR_KEYWORDS)
        sugar_cog.append((has_sugar, cog))

    if len(sugar_cog) < 10:
        return None

    sugar_days = [c for flag, c in sugar_cog if flag]
    clean_days = [c for flag, c in sugar_cog if not flag]
    if not sugar_days or not clean_days:
        return None

    sugar_avg = sum(sugar_days) / len(sugar_days)
    clean_avg = sum(clean_days) / len(clean_days)
    diff = clean_avg - sugar_avg

    if diff > 0.5:
        return (f"Food-cognition pattern: days after sugar/refined carbs, "
                f"your cognition averages {sugar_avg:.1f}/10 "
                f"vs {clean_avg:.1f}/10 on clean days "
                f"({diff:.1f} point difference, n={len(sugar_cog)}).")
    return None


def generate_if_then_rules(baselines, by_date_sleep, daily_log_by_date,
                            by_date_garmin, target_date, profile=None):
    """Build personalized decision rules from historical correlations.

    When today matches a pattern (e.g. HRV suppressed + deep sleep < 50min),
    validates against 60-day history to compute predicted cognition.
    Returns insight string if pattern matches, else None.
    """
    if not profile:
        return None
    memory_conditions = get_relevant_conditions(profile, "cognition")
    if not memory_conditions:
        return None

    hrv_z = baselines.get("hrv", {}).get("z")
    today_sleep = by_date_sleep.get(str(target_date), {})
    deep_min = _safe_float(today_sleep.get("Deep Sleep (min)"))

    # Rule: HRV below baseline AND deep sleep low -> predict bad cognition day
    if hrv_z is None or hrv_z >= -0.5 or deep_min is None or deep_min >= 50:
        return None

    # Validate against historical data
    hrv_mean = baselines.get("hrv", {}).get("mean")
    if not hrv_mean:
        return None

    bad_day_cogs = []
    for offset in range(1, 61):
        d = target_date - timedelta(days=offset)
        d_str = str(d)

        sleep = by_date_sleep.get(d_str, {})
        garmin = by_date_garmin.get(d_str, {})
        log = daily_log_by_date.get(d_str, {})

        d_hrv = _safe_float(garmin.get("HRV (overnight avg)"))
        if d_hrv is None:
            d_hrv = _safe_float(sleep.get("Overnight HRV (ms)"))
        d_deep = _safe_float(sleep.get("Deep Sleep (min)"))
        d_cog = _safe_float(log.get("Cognition (1-10)"))

        if d_hrv and d_deep and d_cog:
            if d_hrv < hrv_mean * 0.9 and d_deep < 50:
                bad_day_cogs.append(d_cog)

    if len(bad_day_cogs) >= 5:
        avg_cog = sum(bad_day_cogs) / len(bad_day_cogs)
        return (f"PATTERN MATCH: When HRV is suppressed AND deep sleep < 50min, "
                f"your cognition averages {avg_cog:.1f}/10 (n={len(bad_day_cogs)}). "
                f"Today matches this pattern. Defer complex tasks, focus on "
                f"administrative work.")
    return None


# ---------------------------------------------------------------------------
# Profile-aware insight reframing (PHI-safe — never outputs condition names)
# ---------------------------------------------------------------------------

# Domain keyword -> condition-context suffix mapping
# Keys are substrings to match in insight text; values are (tracking_domain, suffix)
_REFRAME_RULES = [
    # HRV / autonomic
    (["hrv", "autonomic", "heart rate variability"],
     "hrv",
     "With your neurological profile, HRV suppression may reflect neuroinflammatory activity. Monitor for cognitive symptoms today."),
    # Deep sleep -> memory pipeline
    (["deep sleep", "slow-wave", "glymphatic"],
     "deep_sleep",
     "Reduced deep sleep directly impacts your primary concern: memory consolidation."),
    # REM -> emotional/procedural memory
    (["rem"],
     "rem_sleep",
     "REM below baseline affects emotional regulation and procedural memory processing."),
    # Sleep debt -> executive function
    (["sleep debt", "cumulative debt", "below-baseline sleep"],
     "sleep",
     "Sleep deficit amplifies executive dysfunction -- expect harder task-switching today."),
    # Stress
    (["stress level", "stress budget", "stress elevated"],
     "stress",
     "With your stress-sensitive profile, protect remaining recovery time."),
    # Body battery / recovery
    (["body battery", "recovery deficit", "recovery incomplete"],
     "recovery",
     "With CIRS, recovery from this deficit takes longer than baseline. Prioritize rest."),
    # Training
    (["zone 4", "zone 5", "high-intensity", "training load", "acwr"],
     "training",
     "Given your cardiac profile, sustained high-intensity carries elevated risk."),
    # Cognition / executive function
    (["cognitive", "executive function", "attention", "working memory", "brain fog"],
     "cognition",
     "Executive function factors compounding. Expect increased difficulty with planning and working memory today."),
    # Energy
    (["energy", "fatigue", "low energy"],
     "energy",
     "Energy deficits compound with your neuroimmune profile. Front-load demanding tasks."),
]


def _reframe_insights_with_profile(insights, profile):
    """Post-process insights to add condition-aware context.

    Never outputs condition names (PHI safety). Uses generic phrases like
    'your neurological profile' instead.

    Returns new list of insights with condition context appended where relevant.
    """
    if not profile:
        return insights

    reframed = []
    for insight in insights:
        # Skip reframing on condensed sleep review — it's already a summary
        if insight.upper().startswith("SLEEP REVIEW:") or insight.upper().startswith("LAST NIGHT:"):
            reframed.append(insight)
            continue
        insight_lower = insight.lower()
        suffix_added = False
        for keywords, domain, suffix in _REFRAME_RULES:
            if any(kw in insight_lower for kw in keywords):
                # Only add suffix if profile has relevant conditions for this domain
                relevant = get_relevant_conditions(profile, domain)
                if relevant and not suffix_added:
                    reframed.append(f"{insight} {suffix}")
                    suffix_added = True
                    break
        if not suffix_added:
            reframed.append(insight)
    return reframed


def generate_insights(baselines, sleep_debt, sleep_trend, acwr, acwr_status,
                      note_flags, daily_log_by_date, by_date_garmin,
                      by_date_sleep, sessions_by_date, target_date,
                      knowledge=None, sleep_analysis_text=None,
                      deep_trend=None, rem_trend=None, profile=None,
                      nutrition_by_date=None, oa_by_date=None,
                      correlations=None):
    """Generate priority-ordered insight text based on all computed data.

    Uses health_knowledge.json entries for scientifically-grounded cognitive/energy
    framing when available, with hardcoded fallbacks for backward compatibility.
    When correlations are provided, adds personal data validation annotations
    and "Your Data Shows" standalone insights.

    Returns list of insight strings, ordered by severity/relevance.
    """
    if knowledge is None:
        knowledge = {}
    if nutrition_by_date is None:
        nutrition_by_date = {}
    if correlations is None:
        correlations = {}
    insights = []
    _covered_behaviors = set()  # track which behaviors were mentioned in insights

    # --- Outlier warnings (data quality flags) ---
    METRIC_DISPLAY = {"hrv": "HRV", "rhr": "Resting HR", "sleep_score": "Sleep Score",
                      "sleep_duration": "Sleep Duration", "body_battery": "Body Battery",
                      "steps": "Steps", "stress": "Stress"}
    for key, info in baselines.items():
        if info.get("outliers"):
            name = METRIC_DISPLAY.get(key, key)
            vals = ", ".join(f"{v:.0f}" for v in info["outliers"])
            insights.append(
                f"Note: {name} has extreme value(s) ({vals}) in the baseline window "
                f"(>3 SD from mean). This may affect baseline accuracy."
            )

    # --- Last night's sleep analysis (condensed from Sleep tab) ---
    condensed = condense_sleep_analysis(sleep_analysis_text)
    if condensed:
        insights.append(condensed)

    # --- Sleep debt ---
    if sleep_debt is not None and sleep_debt > 0.75:
        if sleep_debt > 1.5:
            insights.append(_kb_insight(
                knowledge, "sleep_debt_major",
                f"CUMULATIVE SLEEP DEBT: {sleep_debt:.1f}h below your baseline over the past 5 days. ",
                f"CUMULATIVE SLEEP DEBT: {sleep_debt:.1f}h below your baseline over the past 5 days. "
                f"Research shows this level of restriction impairs reaction time, word recall, and "
                f"executive function comparably to partial sleep deprivation (Van Dongen et al. 2003). "
                f"You may experience difficulty finding words, poor focus, and increased sugar/carb cravings."
            ))
        else:
            insights.append(_kb_insight(
                knowledge, "sleep_debt_mild",
                f"Mild sleep debt: {sleep_debt:.1f}h below baseline over 5 days. ",
                f"Mild sleep debt: {sleep_debt:.1f}h below baseline over 5 days. "
                f"Not yet critical, but if this trend continues, cognitive effects compound "
                f"non-linearly. Day 5+ of restriction shows accelerating impairment."
            ))

    # --- HRV status ---
    hrv_data = baselines.get("hrv", {})
    if hrv_data.get("z") is not None:
        z = hrv_data["z"]
        hrv_trend = hrv_data.get("trend")  # "declining", "recovering", "stable", or None
        if z < -1.5:
            # Trend-aware messaging for significantly low HRV
            if hrv_trend == "declining":
                trend_msg = (
                    "5-day trend is declining. This pattern suggests overtraining or accumulated fatigue. "
                    "Prioritize rest and active recovery."
                )
            elif hrv_trend == "recovering":
                trend_msg = (
                    "However, 5-day trend shows recovery in progress. "
                    "Maintain current approach. HRV is rebounding."
                )
            else:
                trend_msg = (
                    "Your autonomic nervous system is under strain. "
                    "Common causes: accumulated training load, poor sleep, illness onset, or high stress."
                )
            insights.append(_kb_insight(
                knowledge, "hrv_critical_low",
                f"HRV significantly below baseline (z={z:+.1f}, today: {hrv_data['today']:.0f}ms vs "
                f"avg: {hrv_data['mean']:.0f}ms). ",
                f"HRV significantly below baseline (z={z:+.1f}, today: {hrv_data['today']:.0f}ms vs "
                f"avg: {hrv_data['mean']:.0f}ms). {trend_msg}"
            ))
        elif z < -1.0:
            if hrv_trend == "declining":
                trend_msg = (
                    "5-day trend is declining. If this continues, consider reducing training intensity."
                )
            elif hrv_trend == "recovering":
                trend_msg = (
                    "5-day trend shows recovery underway. Current approach is working."
                )
            else:
                trend_msg = (
                    "Recovery may be incomplete. "
                    "Monitor over the next 1-2 days. If HRV doesn't rebound, consider reducing training intensity."
                )
            insights.append(_kb_insight(
                knowledge, "hrv_below_baseline",
                f"HRV below baseline (z={z:+.1f}). ",
                f"HRV below baseline (z={z:+.1f}). {trend_msg}"
            ))
        elif z > 1.5:
            insights.append(_kb_insight(
                knowledge, "hrv_above_baseline",
                f"HRV well above baseline (z={z:+.1f}, {hrv_data['today']:.0f}ms). ",
                f"HRV well above baseline (z={z:+.1f}, {hrv_data['today']:.0f}ms). "
                f"Strong parasympathetic recovery. Your body is well-recovered and can handle higher intensity today."
            ))
        elif z < -0.5 and hrv_trend == "declining":
            # Mild dip but declining trend -- early warning
            insights.append(
                f"HRV slightly below baseline (z={z:+.1f}) with a declining 5-day trend. "
                f"Not yet concerning, but watch for continued decline over the next 2 days."
            )

    # --- RHR status ---
    rhr_data = baselines.get("rhr", {})
    if rhr_data.get("z") is not None and rhr_data["z"] > 1.5:
        insights.append(_kb_insight(
            knowledge, "rhr_elevated",
            f"Resting HR elevated (z={rhr_data['z']:+.1f}, today: {rhr_data['today']:.0f}bpm vs "
            f"avg: {rhr_data['mean']:.0f}bpm). ",
            f"Resting HR elevated (z={rhr_data['z']:+.1f}, today: {rhr_data['today']:.0f}bpm vs "
            f"avg: {rhr_data['mean']:.0f}bpm). Combined with HRV trends, this may indicate "
            f"accumulated fatigue, dehydration, or early illness."
        ))

    # --- Training load ---
    if acwr is not None:
        if acwr > 1.5:
            insights.append(_kb_insight(
                knowledge, "training_load_spike",
                f"TRAINING LOAD SPIKE: {acwr_status} ",
                f"TRAINING LOAD SPIKE: {acwr_status} "
                f"Research (Gabbett 2016) shows ACWR >1.5 significantly increases "
                f"injury and illness risk. Prioritize active recovery this week."
            ))
        elif acwr > ACWR_HIGH:
            insights.append(acwr_status)

    # --- HRV suppression after workout (check if HRV still suppressed >72h post-workout) ---
    hrv_z = hrv_data.get("z")
    if hrv_z is not None and hrv_z < -0.5:
        for offset in range(1, 4):
            d = str(target_date - timedelta(days=offset))
            sessions = sessions_by_date.get(d, [])
            for s in sessions:
                te = _safe_float(s.get("Anaerobic TE (0-5)"))
                dur = _safe_float(s.get("Duration (min)"))
                if (te and te >= 3.5) or (dur and dur >= 60):
                    if offset >= 3:
                        insights.append(_kb_insight(
                            knowledge, "hrv_suppressed_post_workout",
                            f"HRV still suppressed {offset} days after heavy session on {d} "
                            f"({s.get('Activity Name', 'workout')}). ",
                            f"HRV still suppressed {offset} days after heavy session on {d} "
                            f"({s.get('Activity Name', 'workout')}). "
                            f"Recovery typically takes 48-72h for high-intensity work; "
                            f"extended suppression suggests incomplete recovery."
                        ))
                    break

    # --- Weekly zone distribution analysis ---
    total_zones = {i: 0 for i in range(1, 6)}
    total_zone_time = 0
    for offset in range(7):
        d = str(target_date - timedelta(days=offset))
        for s in sessions_by_date.get(d, []):
            for z in range(1, 6):
                val = _safe_float(s.get(f"Zone {z} (min)")) or 0
                total_zones[z] += val
                total_zone_time += val
    if total_zone_time > 30:
        high_pct = (total_zones[4] + total_zones[5]) / total_zone_time * 100
        if high_pct > 30:
            insights.append(
                f"High-intensity dominance: {high_pct:.0f}% of this week's training "
                f"in Zone 4-5. The 80/20 polarized model suggests ~80% in Zone 1-2 "
                f"for sustainable adaptation without accumulated fatigue."
            )

    # --- Diet/behavior flags ---
    flag_kb_map = {
        "alcohol": "alcohol_sleep_disruption",
        "sugar/refined_carbs": "sugar_sleep_disruption",
        "late_meal": "late_meal_thermoregulation",
        "late_caffeine": "late_caffeine_sleep",
    }
    flag_fallbacks = {
        "alcohol": (
            "Research (Ebrahim et al. 2013) shows alcohol increases initial deep sleep "
            "but suppresses REM in the second half of the night, fragmenting sleep "
            "architecture. HRV may remain suppressed the following morning."
        ),
        "sugar/refined_carbs": (
            "High glycemic load is associated with less slow-wave (deep) sleep and "
            "more fragmented sleep (St-Onge et al. 2016). Effect is modest but "
            "compounds with other sleep disruptors."
        ),
        "late_meal": (
            "Eating within 2-3 hours of bedtime can elevate core body temperature and "
            "delay sleep onset. The thermoregulation disruption can reduce deep sleep "
            "in the first half of the night."
        ),
        "late_caffeine": (
            "Caffeine has a half-life of 5-7 hours (Huberman). Afternoon/evening caffeine "
            "can reduce total sleep time by up to 1 hour and decrease deep sleep even "
            "when you fall asleep on time."
        ),
    }

    # Map flag types to correlation behavior keys for personal validation
    _flag_to_corr = {
        "alcohol": ("alcohol", "Sleep Score"),
        "late_caffeine": ("late_caffeine", "Sleep"),
        "late_meal": ("late_meal", "Sleep"),
        "sugar/refined_carbs": ("sugar", "Sleep"),
    }

    for flag_date, flag_type, matched in note_flags:
        days_ago = (target_date - date.fromisoformat(flag_date)).days
        time_ref = "yesterday" if days_ago == 1 else f"{days_ago} days ago" if days_ago > 0 else "today"

        kb_id = flag_kb_map.get(flag_type)
        if flag_type == "alcohol":
            prefix = f"Alcohol noted {time_ref} ({matched}). "
        elif flag_type == "sugar/refined_carbs":
            prefix = f"High sugar/refined carbs noted {time_ref} ({matched}). "
        elif flag_type == "late_meal":
            prefix = f"Late meal noted {time_ref}. "
        elif flag_type == "late_caffeine":
            prefix = f"Late caffeine noted {time_ref}. "
        else:
            continue

        fallback_text = prefix + flag_fallbacks.get(flag_type, "")
        if kb_id:
            insight_text = _kb_insight(knowledge, kb_id, prefix, fallback_text)
        else:
            insight_text = fallback_text

        # Personal validation: check if user's data confirms this behavior's impact
        corr_key = _flag_to_corr.get(flag_type)
        if corr_key and correlations:
            validation = _personal_validation(correlations, corr_key[0], corr_key[1])
            if validation:
                insight_text += f" {validation}."
        insights.append(insight_text)
        _covered_behaviors.add(flag_type)

    # --- Deep sleep and REM assessment (new: cognitive-relevant sleep architecture) ---
    today_sleep = by_date_sleep.get(str(target_date), {})
    deep_pct = _safe_float(today_sleep.get("Deep %"))
    rem_pct = _safe_float(today_sleep.get("REM %"))
    if deep_pct is not None and deep_pct < 15:
        insights.append(_kb_insight(
            knowledge, "deep_sleep_deficit",
            f"Deep sleep was only {deep_pct:.0f}% last night (target: 20-25%). ",
            f"Deep sleep was only {deep_pct:.0f}% last night. Reduced deep sleep impairs "
            f"declarative memory consolidation and physical recovery."
        ))
    if rem_pct is not None and rem_pct < 15:
        insights.append(_kb_insight(
            knowledge, "rem_sleep_deficit",
            f"REM sleep was only {rem_pct:.0f}% last night (target: 20-25%). ",
            f"REM sleep was only {rem_pct:.0f}% last night. Reduced REM impairs "
            f"emotional regulation and procedural memory consolidation."
        ))

    # --- Deep/REM 3-night trends (catches slow architectural degradation) ---
    if deep_trend == "declining" and deep_pct is not None and deep_pct < 20:
        insights.append(_kb_insight(
            knowledge, "deep_sleep_deficit",
            f"Deep sleep trending down over last 3 nights (latest: {deep_pct:.0f}%). ",
            f"Deep sleep has been declining over 3 nights (latest: {deep_pct:.0f}%). "
            f"Sustained deep sleep decline impairs declarative memory consolidation "
            f"and glymphatic clearance. Avoid alcohol, keep room cool (18-19C)."
        ))
    if rem_trend == "declining" and rem_pct is not None and rem_pct < 20:
        insights.append(_kb_insight(
            knowledge, "rem_sleep_deficit",
            f"REM sleep trending down over last 3 nights (latest: {rem_pct:.0f}%). ",
            f"REM sleep has been declining over 3 nights (latest: {rem_pct:.0f}%). "
            f"Sustained REM decline impairs emotional regulation and procedural memory. "
            f"Check for late caffeine, alcohol, or truncated sleep from late bedtimes."
        ))

    # --- Sleep trend ---
    if sleep_trend == "declining":
        sleep_score_data = baselines.get("sleep_score", {})
        if sleep_score_data.get("z") is not None and sleep_score_data["z"] < -0.5:
            insights.append(_kb_insight(
                knowledge, "sleep_trend_declining",
                "Sleep quality has been declining over the last 3 nights. ",
                "Sleep quality has been declining over the last 3 nights. "
                "If this continues, expect compounding cognitive effects by day 4-5 "
                "(Van Dongen cumulative restriction model)."
            ))

    # --- Habit patterns (dynamic — reads from user config) ---
    from schema import get_habit_columns
    active_habits = get_habit_columns()
    n_habits = len(active_habits)

    # Find the Habits Total column header dynamically
    habits_total_header = f"Habits Total (0-{n_habits})"

    habit_totals = []
    for offset in range(0, 3):
        d = str(target_date - timedelta(days=offset))
        dl = daily_log_by_date.get(d, {})
        ht = _safe_float(dl.get(habits_total_header))
        if ht is not None:
            habit_totals.append(ht)

    # High-consistency threshold: >= 85% of habits completed
    high_threshold = max(1, round(n_habits * 0.85))
    if habit_totals and sum(habit_totals) / len(habit_totals) >= high_threshold:
        avg = sum(habit_totals) / len(habit_totals)
        insights.append(_kb_insight(
            knowledge, "habit_consistency_positive",
            f"Strong habit consistency ({avg:.1f}/{n_habits} avg over last {len(habit_totals)} days). ",
            f"Strong habit consistency ({avg:.1f}/{n_habits} avg over last {len(habit_totals)} days). "
            f"Research on habit stacking shows this level of consistency builds automaticity "
            f"within 2-3 weeks."
        ))

    # --- Per-habit missed pattern analysis (dynamic) ---
    # Check each configured habit over last 3 days
    for habit_label in active_habits:
        missed = 0
        total = 0
        for offset in range(0, 3):
            d = str(target_date - timedelta(days=offset))
            dl = daily_log_by_date.get(d, {})
            val = dl.get(habit_label, "")
            if str(val).upper() in ("TRUE", "FALSE"):
                total += 1
                if str(val).upper() == "FALSE":
                    missed += 1
        if total >= 2 and missed >= 2:
            # Use habit label as knowledge base key (lowercase, spaces to underscores)
            kb_key = habit_label.lower().replace(" ", "_").replace("&", "and")
            insights.append(_kb_insight(
                knowledge, kb_key,
                f"{habit_label} missed {missed}/{total} recent days. ",
                f"{habit_label} missed {missed}/{total} recent days. "
                f"Consistency with this habit may be affecting your recovery and readiness."
            ))

    # --- Calorie balance analysis (enhanced) ---
    # 1. Cumulative weekly deficit
    weekly_balances = []
    for offset in range(7):
        d = str(target_date - timedelta(days=offset))
        nut = nutrition_by_date.get(d, {})
        bal = _safe_float(nut.get("Calorie Balance"))
        if bal is not None:
            weekly_balances.append((d, bal))

    if len(weekly_balances) >= 3:
        cumulative = sum(b for _, b in weekly_balances)
        if cumulative < -3500:
            insights.append(_kb_insight(
                knowledge, "sustained_deficit",
                f"Sustained energy deficit: {cumulative:+.0f} kcal over {len(weekly_balances)} days. ",
                f"Sustained energy deficit: {cumulative:+.0f} kcal over {len(weekly_balances)} days. "
                f"Cumulative deficit >3500 kcal/week can impair recovery, suppress immune function, "
                f"and reduce HRV. Ensure this is intentional."
            ))

    # 2. Single-day deficit (with training-day context)
    for offset in range(0, 2):
        d = str(target_date - timedelta(days=offset))
        nut = nutrition_by_date.get(d, {})
        cal_balance = _safe_float(nut.get("Calorie Balance"))
        if cal_balance is not None and cal_balance < -500:
            day_sessions = sessions_by_date.get(d, [])
            if day_sessions:
                insights.append(_kb_insight(
                    knowledge, "underfueling_training_day",
                    f"Underfueling on training day {d} ({cal_balance:+.0f} kcal). ",
                    f"Underfueling on training day {d} ({cal_balance:+.0f} kcal). "
                    f"Training-day deficits impair glycogen replenishment and muscle protein "
                    f"synthesis more than rest-day deficits."
                ))
            else:
                insights.append(_kb_insight(
                    knowledge, "calorie_deficit",
                    f"Large calorie deficit on {d} ({cal_balance:+.0f} kcal). ",
                    f"Large calorie deficit on {d} ({cal_balance:+.0f} kcal). "
                    f"Deficits >500 kcal can impair next-day energy, cognitive function, "
                    f"and recovery."
                ))
            break

    # 3. Rest-day surplus (informational)
    for offset in range(0, 2):
        d = str(target_date - timedelta(days=offset))
        nut = nutrition_by_date.get(d, {})
        cal_balance = _safe_float(nut.get("Calorie Balance"))
        day_sessions = sessions_by_date.get(d, [])
        if cal_balance is not None and cal_balance > 500 and not day_sessions:
            insights.append(
                f"Calorie surplus on rest day {d} ({cal_balance:+.0f} kcal). "
                f"Informational -- occasional surpluses on rest days are normal."
            )
            break

    # --- Macro nutrition analysis (enhanced) ---
    for offset in range(0, 2):
        d = str(target_date - timedelta(days=offset))
        nut = nutrition_by_date.get(d, {})
        protein = _safe_float(nut.get("Protein (g)"))
        carbs = _safe_float(nut.get("Carbs (g)"))
        fats = _safe_float(nut.get("Fats (g)"))
        day_sessions = sessions_by_date.get(d, [])
        flagged = False

        # 1. Body-weight-normalized protein
        if protein is not None:
            body_weight_kg = None
            if profile:
                body_weight_kg = _safe_float(
                    profile.get("demographics", {}).get("weight_kg")
                )
            if body_weight_kg and body_weight_kg > 0:
                target_g = (1.6 if day_sessions else 1.2) * body_weight_kg
                if protein < target_g:
                    insights.append(_kb_insight(
                        knowledge, "low_protein_normalized",
                        f"Low protein on {d}: {protein:.0f}g (target {target_g:.0f}g). ",
                        f"Low protein on {d}: {protein:.0f}g "
                        f"(target: {target_g:.0f}g = {1.6 if day_sessions else 1.2}g/kg). "
                        f"Below target impairs muscle recovery and sleep quality."
                    ))
                    flagged = True
            elif protein < 100:
                insights.append(_kb_insight(
                    knowledge, "low_protein",
                    f"Low protein intake on {d} ({protein:.0f}g). ",
                    f"Low protein intake on {d} ({protein:.0f}g). "
                    f"Protein below 100g may impair muscle recovery and sleep quality "
                    f"(tryptophan pathway). Aim for 1.6-2.2g/kg bodyweight."
                ))
                flagged = True

        # 2. Macro ratio analysis
        if protein is not None and carbs is not None and fats is not None:
            total_macro_cal = (protein * 4) + (carbs * 4) + (fats * 9)
            if total_macro_cal > 0:
                prot_pct = (protein * 4) / total_macro_cal * 100
                fat_pct = (fats * 9) / total_macro_cal * 100
                if prot_pct < 25:
                    insights.append(
                        f"Low protein ratio on {d}: {prot_pct:.0f}% of macros. "
                        f"Aim for 25-35% protein for recovery and satiety."
                    )
                    flagged = True
                if fat_pct > 40:
                    insights.append(
                        f"High fat ratio on {d}: {fat_pct:.0f}% of macros. "
                        f"High fat meals close to bedtime may impair sleep quality."
                    )
                    flagged = True

        # 3. Training-day carb check
        if day_sessions and carbs is not None and carbs < 150:
            insights.append(
                f"Low carbs on training day {d} ({carbs:.0f}g). "
                f"Below 150g on training days may impair glycogen replenishment."
            )
            flagged = True

        if flagged:
            break

    # --- Low hydration flagging ---
    for offset in range(0, 2):
        d = str(target_date - timedelta(days=offset))
        nut = nutrition_by_date.get(d, {})
        water = _safe_float(nut.get("Water (L)"))
        if water is not None and water < 2.0:
            insights.append(_kb_insight(
                knowledge, "low_hydration",
                f"Low water intake on {d} ({water:.1f}L). ",
                f"Low water intake on {d} ({water:.1f}L). "
                f"Even mild dehydration (1-2%) reduces HRV by 5-15% and impairs "
                f"cognitive performance. Aim for 2.5-3.5L daily."
            ))
            break  # Only flag once

    # --- CNS fatigue detection (post-workout energy) ---
    yesterday = str(target_date - timedelta(days=1))
    for s in sessions_by_date.get(yesterday, []):
        pwe = _safe_float(s.get("Post-Workout Energy (1-10)"))
        effort = _safe_float(s.get("Perceived Effort (1-10)"))
        if pwe is not None and pwe <= 3 and effort is not None and effort >= 7:
            activity = s.get("Activity Name", "session")
            insights.append(
                f"Yesterday's {activity}: high effort ({effort:.0f}/10) but very low "
                f"post-workout energy ({pwe:.0f}/10). This pattern suggests CNS fatigue "
                f"-- expect longer recovery. Consider lighter activity today."
            )
            break

    # --- Stress ---
    stress_data = baselines.get("stress", {})
    if stress_data.get("z") is not None and stress_data["z"] > 1.0:
        stress_insight = _kb_insight(
            knowledge, "stress_elevated",
            f"Garmin stress level elevated (z={stress_data['z']:+.1f}, today: "
            f"{stress_data['today']:.0f} vs avg: {stress_data['mean']:.0f}). ",
            f"Garmin stress level elevated (z={stress_data['z']:+.1f}, today: "
            f"{stress_data['today']:.0f} vs avg: {stress_data['mean']:.0f}). "
            f"Sustained high stress activates the sympathetic nervous system, "
            f"suppressing HRV and impairing sleep quality."
        )
        # Personal validation: stress -> body battery / HRV
        stress_val = _personal_validation(correlations, "stress_level", "Body Battery")
        if not stress_val:
            stress_val = _personal_validation(correlations, "stress_level", "HRV")
        if stress_val:
            stress_insight += f" {stress_val}."
        insights.append(stress_insight)
        _covered_behaviors.add("stress_level")

    # --- Profile-aware insights (Steps 3-5, 6, 11) ---
    if profile:
        # Step 3: Reframe existing insights with condition context
        insights = _reframe_insights_with_profile(insights, profile)

        # Step 4: (Migrated to _REFRAME_RULES — deep_sleep and rem_sleep rules
        # now enrich the main-body insights contextually instead of adding
        # duplicate standalone bullets.)

        # Step 5: ARVC exercise guardrails
        cardiac_conditions = get_relevant_conditions(profile, "training")
        arvc_active = any(c.get("id") == "cond_008" for c in cardiac_conditions)
        if arvc_active:
            today_sessions = sessions_by_date.get(str(target_date), [])
            if isinstance(today_sessions, dict):
                today_sessions = [today_sessions]
            for s in today_sessions:
                z4 = _safe_float(s.get("Zone 4 (min)")) or 0
                z5 = _safe_float(s.get("Zone 5 (min)")) or 0
                max_hr = _safe_float(s.get("Max HR"))
                if z4 + z5 > 5:
                    insights.append(
                        f"Today's workout included {z4+z5:.0f}min in Zone 4-5. "
                        f"With your cardiac profile, sustained high-intensity "
                        f"carries elevated risk. Consider Zone 2-3 focus."
                    )
                if max_hr and max_hr > 170:
                    insights.append(
                        f"Max HR reached {max_hr:.0f} BPM today. Monitor for "
                        f"exercise-induced palpitations per your cardiac management plan."
                    )

        # Step 6: Stress budget
        stress_budget_insight = _compute_stress_budget(baselines, profile)
        if stress_budget_insight:
            insights.append(stress_budget_insight)

        # Step 11: Biomarker staleness alerts (high urgency only)
        stale_warnings = check_biomarker_staleness(profile)
        relevant_stale = [w for w in stale_warnings
                          if w["urgency"] == "high"
                          and w["category"] in ("cardiac", "antibodies", "brain_imaging")]
        if relevant_stale:
            categories = sorted(set(w["category"] for w in relevant_stale))
            oldest = max(w["months_old"] for w in relevant_stale)
            insights.append(
                f"Note: {len(relevant_stale)} biomarker(s) in {', '.join(categories)} "
                f"past recommended retest interval (oldest: {oldest:.0f} months). "
                f"Consider follow-up testing."
            )

        # Step 9: Good Day Forensics
        good_day = analyze_good_day_factors(
            baselines, by_date_sleep, daily_log_by_date,
            by_date_garmin, target_date, profile
        )
        if good_day:
            insights.append(good_day)

        # Step 14: Food -> brain fog lag analysis
        food_lag = analyze_food_cognition_lag(
            nutrition_by_date, daily_log_by_date, target_date, profile
        )
        if food_lag:
            insights.append(food_lag)

        # Step 15: If-Then decision rules
        if_then = generate_if_then_rules(
            baselines, by_date_sleep, daily_log_by_date,
            by_date_garmin, target_date, profile
        )
        if if_then:
            insights.append(if_then)

    # --- Orthosomnia safeguard (score anxiety prevention) ---
    if oa_by_date:
        consecutive_low = 0
        for offset in range(1, 6):
            d = str(target_date - timedelta(days=offset))
            prior = oa_by_date.get(d, {})
            if prior.get("Readiness Label") in ("Poor", "Low"):
                consecutive_low += 1
            else:
                break
        if consecutive_low >= 3:
            insights.append(
                "Scores have been below baseline for several days. Remember: "
                "tracking is a tool for awareness, not a verdict. Consider taking "
                "a day off from checking scores if it's causing anxiety."
            )

    # --- Day-to-day variability reassurance ---
    if oa_by_date:
        d1 = oa_by_date.get(str(target_date - timedelta(days=1)), {})
        d2 = oa_by_date.get(str(target_date - timedelta(days=2)), {})
        s1 = _safe_float(d1.get("Readiness Score (1-10)"))
        s2 = _safe_float(d2.get("Readiness Score (1-10)"))
        if s1 is not None and s2 is not None and abs(s1 - s2) > 2.0:
            insights.append(
                f"Day-to-day readiness variation of {abs(s1 - s2):.1f} points is within "
                f"normal biological noise. Focus on 7-day trends, not daily scores."
            )

    # --- Your Data Shows (correlation-backed standalone insights) ---
    if correlations:
        active_corr = _get_active_correlations(
            correlations, note_flags, baselines, sessions_by_date,
            target_date, _covered_behaviors)
        insights.extend(active_corr)

    # --- Causal chain connection (narrative synthesis) ---
    insights = _connect_causal_chain(insights, baselines, sleep_debt, acwr,
                                     note_flags)

    return insights


# ---------------------------------------------------------------------------
# Recommendation Generation
# ---------------------------------------------------------------------------

def generate_recommendations(score, label, sleep_debt, acwr, note_flags,
                             baselines, target_date, knowledge=None,
                             profile=None, sessions_by_date=None,
                             correlations=None):
    """Generate actionable recommendations based on readiness state.

    Uses a factor-driven rule system: each rule fires independently when its
    conditions are met, regardless of label. Rules are priority-ordered and
    profile-filtered at the end.

    Returns list of recommendation strings.
    """
    if knowledge is None:
        knowledge = {}
    if correlations is None:
        correlations = {}

    day_name = target_date.strftime("%A")
    hrv_z = baselines.get("hrv", {}).get("z")
    stress_z = baselines.get("stress", {}).get("z")

    # Collect (priority, rec_text) tuples — lower priority number = more important
    candidates = []

    # --- Rule 1: Sleep debt recovery (any label) ---
    if sleep_debt and sleep_debt > 1.0:
        k = knowledge.get("sleep_debt_major")
        if k:
            candidates.append((1, f"Sleep debt {sleep_debt:.1f}h. {k['recommendation']} [{k['citation']}]"))
        else:
            candidates.append((1,
                f"Sleep debt {sleep_debt:.1f}h. Aim for 8.5-9h tonight. "
                f"Full recovery from sustained restriction can take 2-3 weeks (Van Dongen 2003)."))
    elif sleep_debt and sleep_debt > 0.5:
        candidates.append((3, "Prioritize an earlier bedtime tonight. Even 30 min earlier helps restore cognitive function."))

    # --- Rule 2: Post-intensity recovery (yesterday's session was hard) ---
    if sessions_by_date:
        yesterday = str(target_date - timedelta(days=1))
        for s in sessions_by_date.get(yesterday, []):
            anaerobic_te = _safe_float(s.get("Anaerobic TE (0-5)"))
            z4 = _safe_float(s.get("Zone 4 (min)")) or 0
            z5 = _safe_float(s.get("Zone 5 (min)")) or 0
            if (anaerobic_te and anaerobic_te > 3.0) or (z4 + z5 > 15):
                activity = s.get("Activity Name", "session")
                detail = []
                if anaerobic_te:
                    detail.append(f"Anaerobic TE {anaerobic_te:.1f}")
                if z4 + z5 > 0:
                    detail.append(f"{z4 + z5:.0f}min Zone 4-5")
                candidates.append((2,
                    f"Yesterday's {activity} was high-intensity ({', '.join(detail)}). "
                    f"Allow 48-72h before next high-intensity. Zone 2 or rest today."))
                break

        # Low post-workout energy
        for s in sessions_by_date.get(yesterday, []):
            pwe = _safe_float(s.get("Post-Workout Energy (1-10)"))
            if pwe is not None and pwe < 4:
                candidates.append((2,
                    "Yesterday's post-workout energy was low. Zone 1-2 only or active recovery today."))
                break

    # --- Rule 3: HRV suppressed (any label) ---
    if hrv_z is not None and hrv_z < -1.0:
        k = knowledge.get("nsdr_recovery")
        if k:
            candidates.append((2,
                f"HRV suppressed (z={hrv_z:+.1f}). {k['recommendation']} [{k['citation']}]"))
        else:
            candidates.append((2,
                f"HRV suppressed (z={hrv_z:+.1f}). Consider 10-20 min NSDR/yoga nidra, "
                f"extend sleep by 30-60 min, avoid alcohol/caffeine today."))

    # --- Rule 4: Training load spike ---
    if acwr is not None and acwr > ACWR_HIGH:
        k = knowledge.get("training_load_spike")
        candidates.append((2, k["recommendation"] if k else
            "Training load elevated this week. Replace one session with active recovery (Zone 1-2, mobility, yoga)."))

    # --- Rule 5: Stress elevated ---
    if stress_z is not None and stress_z > 1.0:
        candidates.append((3,
            f"Stress elevated (z={stress_z:+.1f}). Protect recovery: limit stimulants, "
            f"add a 10-min breathing exercise or walk."))

    # --- Rule 6: Alcohol today ---
    alcohol_flags = [f for f in (note_flags or []) if f[1] == "alcohol" and f[0] == str(target_date)]
    if alcohol_flags:
        k = knowledge.get("alcohol_sleep_disruption")
        candidates.append((3, f"If drinking tonight: {k['recommendation']}" if k else
            "If drinking tonight: stop 3-4h before bed to minimize REM suppression. Hydrate before sleep."))

    # --- Rule 7: Training opportunity (Good/Optimal + ACWR not elevated) ---
    if label in ("Good", "Optimal"):
        if acwr is None or acwr <= ACWR_HIGH:
            k = knowledge.get("hrv_above_baseline")
            cog = k["cognitive_impact"] if k else "Good day for complex cognitive work or skill acquisition."
            candidates.append((4,
                f"Well-recovered today. Good day for high-intensity training or challenging cognitive tasks. {cog}"))
        if acwr is not None and acwr < ACWR_LOW:
            candidates.append((5,
                "Training load below recent capacity. Consider increasing intensity or volume if goals support it."))

    # --- Rule 8: Correlation-backed recommendations ---
    if correlations:
        for behavior_key, entries in correlations.items():
            # Only recommend if behavior was present yesterday
            yesterday_str = str(target_date - timedelta(days=1))
            behavior_active = any(
                f[1] == behavior_key and f[0] == yesterday_str
                for f in (note_flags or []))
            if not behavior_active:
                continue
            for entry in entries:
                if abs(entry["r"]) >= 0.30 and entry["n"] >= 50:
                    direction = "lower" if entry["r"] < 0 else "higher"
                    candidates.append((3,
                        f"Your data: {entry['label']} yesterday is associated with {direction} "
                        f"{entry['outcome']} today (r={entry['r']:+.2f}, n={entry['n']}). "
                        f"Plan accordingly."))
                    break  # One per behavior

    # --- Rule 9: Label-based framing (fallback context) ---
    if label in ("Poor", "Low") and not any(p <= 2 for p, _ in candidates):
        candidates.append((1,
            f"Today ({day_name}): prioritize rest and recovery. Light walking or NSDR only. "
            f"Cognitive capacity likely reduced; defer important decisions if possible."))
    elif label == "Fair" and not any(p <= 3 for p, _ in candidates):
        candidates.append((4,
            f"Today ({day_name}): moderate activity fine, avoid maximal efforts. "
            f"Plan demanding mental work for peak hours."))

    # --- Recovery time multiplier (profile-aware) ---
    if profile:
        from profile_loader import get_accommodations
        accom = get_accommodations(profile)
        recovery_mult = accom.get("analysis_adjustments", {}).get("recovery_time_multiplier")
        if recovery_mult and recovery_mult > 1.0 and label in ("Poor", "Low", "Fair"):
            candidates.append((2,
                f"Your health profile: recovery takes ~{recovery_mult:.0f}x longer than baseline. "
                f"Allow extra rest days and don't push through persistent fatigue."))

    # Sort by priority, extract text
    candidates.sort(key=lambda x: x[0])
    recs = [text for _, text in candidates]

    # --- Profile-aware filtering (3 layers) ---
    if profile:
        accommodations = get_accommodations(profile)

        # Layer 1: Contraindication filter — remove recs matching blocked keywords
        contraindications = accommodations.get("contraindications", [])
        if contraindications:
            filtered = []
            for rec in recs:
                rec_lower = rec.lower()
                blocked = any(c.lower() in rec_lower for c in contraindications)
                if not blocked:
                    filtered.append(rec)
            recs = filtered if filtered else recs[:1]  # never return empty

        # Layer 2: Treatment non-response filter — suppress recs for already-failed treatments
        failed_treatments = set()
        for note in profile.get("provider_notes", []):
            summary = (note.get("summary", "") + " ".join(note.get("action_items", []))).lower()
            if "no improvement" in summary or "no cognitive effect" in summary or "no cognitive improvement" in summary:
                for term in ["nad+", "nad ", "nac", "glutathione", "hbot",
                             "hyperbaric", "cryotherapy", "niagen"]:
                    if term in summary:
                        failed_treatments.add(term.strip())
        if failed_treatments:
            filtered = []
            for rec in recs:
                rec_lower = rec.lower()
                blocked = any(ft in rec_lower for ft in failed_treatments)
                if not blocked:
                    filtered.append(rec)
            recs = filtered if filtered else recs[:1]

        # Layer 3: Accommodation formatting — numbered steps, bold verbs, cap count
        if recs and (accommodations.get("output_format") or accommodations.get("analysis_adjustments")):
            recs_text = "\n".join(f"- {r}" for r in recs)
            recs_text = format_recommendation(recs_text, accommodations)
            # Split back into list, preserving formatted lines
            recs = [line for line in recs_text.split("\n") if line.strip()]

    return recs


# ---------------------------------------------------------------------------
# Cognitive & Energy Assessment
# ---------------------------------------------------------------------------

def assess_cognitive_state(baselines, sleep_debt, note_flags, by_date_sleep,
                           sessions_by_date, target_date, knowledge=None,
                           profile=None):
    """Build a concise cognitive/energy summary.

    Format: "{Level}. {top factors}." — one sentence, scannable.
    Full mechanism details available on-demand via /health-insight.
    """
    if knowledge is None:
        knowledge = {}

    factors = []  # (severity 0-3, short_factor_text)

    # --- Sleep debt (7-day lookback) ---
    if sleep_debt is not None:
        if sleep_debt > 1.5:
            factors.append((3, f"sleep debt {sleep_debt:.1f}h"))
        elif sleep_debt > 0.75:
            factors.append((2, f"mild sleep debt {sleep_debt:.1f}h"))

    # --- HRV trend (5-day) ---
    hrv_data = baselines.get("hrv", {})
    hrv_z = hrv_data.get("z")
    hrv_trend = hrv_data.get("trend")
    if hrv_z is not None:
        if hrv_z < -1.5:
            trend_tag = ""
            if hrv_trend == "declining":
                trend_tag = ", declining"
            elif hrv_trend == "recovering":
                trend_tag = ", recovering"
            factors.append((3, f"HRV suppressed{trend_tag}"))
        elif hrv_z < -1.0:
            trend_tag = ""
            if hrv_trend == "declining":
                trend_tag = ", declining"
            elif hrv_trend == "recovering":
                trend_tag = ", recovering"
            factors.append((2, f"HRV below baseline{trend_tag}"))
        elif hrv_z > 1.5:
            factors.append((-1, "HRV well above baseline"))

    # --- RHR elevated ---
    rhr_z = baselines.get("rhr", {}).get("z")
    if rhr_z is not None and rhr_z > 1.5:
        factors.append((2, "RHR elevated"))

    # --- Stress (14-day trend) ---
    stress_z = baselines.get("stress", {}).get("z")
    if stress_z is not None and stress_z > 1.0:
        factors.append((2, "stress elevated"))

    # --- Sleep architecture (3-day lookback) ---
    today_sleep = by_date_sleep.get(str(target_date), {})
    deep_pct = _safe_float(today_sleep.get("Deep %"))
    rem_pct = _safe_float(today_sleep.get("REM %"))
    if deep_pct is not None and deep_pct < 15:
        factors.append((2, f"low deep sleep {deep_pct:.0f}%"))
    if rem_pct is not None and rem_pct < 15:
        factors.append((2, f"low REM {rem_pct:.0f}%"))

    # --- Alcohol (3-day lookback) ---
    for flag_date, flag_type, _ in note_flags:
        days_ago = (target_date - date.fromisoformat(flag_date)).days
        if flag_type == "alcohol":
            if days_ago == 0:
                factors.append((2, "alcohol today"))
            elif days_ago <= 2:
                factors.append((1, f"alcohol {days_ago}d ago"))
        elif flag_type == "late_caffeine" and days_ago == 0:
            factors.append((1, "late caffeine"))

    # --- Heavy training (3-day lookback, zone-aware) ---
    for offset in range(1, 4):
        d = str(target_date - timedelta(days=offset))
        sessions = sessions_by_date.get(d, [])
        for s in sessions:
            te = _safe_float(s.get("Anaerobic TE (0-5)"))
            dur = _safe_float(s.get("Duration (min)"))
            sz4 = _safe_float(s.get("Zone 4 (min)")) or 0
            sz5 = _safe_float(s.get("Zone 5 (min)")) or 0
            if (te and te >= 3.5) or (dur and dur >= 60) or (sz4 + sz5 > 20):
                if hrv_z is not None and hrv_z < -0.5:
                    msg = f"heavy session {offset}d ago + HRV suppressed"
                    if sz4 + sz5 > 20:
                        msg += f" ({sz4 + sz5:.0f}min Z4-5, expect 48-72h recovery)"
                    factors.append((1, msg))
                break

    # --- Body battery trend (5-day) ---
    bb_data = baselines.get("body_battery", {})
    bb_today = bb_data.get("today")
    if bb_today is not None and bb_today < 40:
        factors.append((2, f"body battery low ({bb_today:.0f})"))

    # --- Profile-aware cognitive factors ---
    if profile:
        neuro_conditions = get_relevant_conditions(profile, "cognition")
        negative_count = len([s for s, _ in factors if s >= 2])
        if neuro_conditions and negative_count >= 2:
            factors.append((3, "compounding stressors on sensitive profile"))

        accommodations = get_accommodations(profile)
        adj = accommodations.get("analysis_adjustments", {})
        cog_adj = adj.get("cognitive_baseline_adjustment", 0)
        ef_adj = adj.get("executive_function_baseline_adjustment", 0)
        total_adj = cog_adj + ef_adj
        if total_adj != 0:
            factors.append((1, f"profile baseline adj {total_adj:+.1f}"))

    # --- Build assessment ---
    if not factors:
        return "Baseline capacity expected."

    negative = [(sev, txt) for sev, txt in factors if sev > 0]
    positive = [(sev, txt) for sev, txt in factors if sev < 0]

    negative.sort(key=lambda x: x[0], reverse=True)

    if not negative and positive:
        pos_text = ", ".join(txt for _, txt in positive)
        return f"Above baseline. {pos_text}."

    max_severity = max(sev for sev, _ in negative) if negative else 0

    if max_severity >= 3:
        level = "Significant reduction"
    elif max_severity >= 2:
        level = "Moderate reduction"
    else:
        level = "Mildly affected"

    factor_list = ", ".join(txt for _, txt in negative[:3])

    return f"{level}. {factor_list}."


# ---------------------------------------------------------------------------
# Distillers — compress verbose analysis into scannable spreadsheet text
# ---------------------------------------------------------------------------

def _strip_citations(text):
    """Remove [citation] blocks and collapse whitespace."""
    text = re.sub(r'\[.*?\]', '', text)
    return re.sub(r'\s{2,}', ' ', text).strip()


def _format_insight(text):
    """Restructure a verbose insight into a scannable format.

    Keeps the causal chain (trigger -> mechanism -> consequence) but strips
    citations, redundant labels, and excessive detail.

    Target: ~150-300 chars with clear structure.
    Format: "TRIGGER. Mechanism. -> Consequence."
    """
    text = _strip_citations(text)

    # Extract trigger (first sentence — the "what happened")
    # Split on double space or ". " followed by uppercase (explanation start)
    parts = re.split(r'(?<=\.)\s{2,}|(?<=\.)\s+(?=[A-Z][a-z])', text, maxsplit=1)
    trigger = parts[0].strip()
    body = parts[1].strip() if len(parts) > 1 else ""

    if not body:
        # No explanation body — return trigger as-is (already concise)
        return trigger

    # Extract cognitive/energy consequence sections
    cog_match = re.search(r'Cognitive(?:\s+impact)?:\s*(.+?)(?=Energy:|Action:|$)', body, re.IGNORECASE)
    energy_match = re.search(r'Energy:\s*(.+?)(?=Cognitive|Action:|$)', body, re.IGNORECASE)
    # Extract mechanism (everything before Cognitive/Energy/Action labels)
    mechanism = body
    for label in (r'Cognitive(?:\s+impact)?:', r'Energy:', r'Action:'):
        mechanism = re.split(label, mechanism, maxsplit=1, flags=re.IGNORECASE)[0]
    mechanism = mechanism.strip().rstrip('.')

    # Compress mechanism to ~150 chars max
    # Split on sentence boundaries (periods, semicolons)
    mech_sentences = re.split(r'(?<!\d)\.\s+|;\s*', mechanism)
    mechanism = '. '.join(s.strip() for s in mech_sentences[:2] if s.strip())
    if len(mechanism) > 150:
        mechanism = mech_sentences[0].strip() if mech_sentences else ""
    if len(mechanism) > 150:
        # Hard truncate on word boundary
        mechanism = mechanism[:147].rsplit(' ', 1)[0] + '...'
    if mechanism and not mechanism.endswith('.') and not mechanism.endswith('...'):
        mechanism += '.'

    # Build consequence from cognitive + energy impacts (pick the most relevant one)
    consequences = []
    if cog_match:
        cog = cog_match.group(1).strip().rstrip('.')
        cog_first = re.split(r'(?<!\d)\.\s+', cog)[0].strip()
        consequences.append(cog_first)
    if energy_match and not consequences:
        # Only add energy if no cognitive consequence (avoid doubling up)
        eng = energy_match.group(1).strip().rstrip('.')
        eng_first = re.split(r'(?<!\d)\.\s+', eng)[0].strip()
        consequences.append(eng_first)

    # Assemble: TRIGGER. Mechanism. -> Consequence.
    result = trigger
    if mechanism:
        result += f" {mechanism}"
    if consequences:
        effect = '. '.join(consequences)
        result += f" -> {effect}."

    return result


def _distill_insights(raw_insights, max_items=6):
    """Restructure verbose insights into scannable spreadsheet format.

    Priority: sleep verdict > training alerts > habits > nutrition > anomalies.
    Drops data quality noise. Merges related habit items.
    """
    if not raw_insights:
        return []

    # Priority buckets
    buckets = {
        0: [],  # sleep verdict (Sleep Review)
        1: [],  # training/safety alerts
        2: [],  # habit patterns
        3: [],  # nutrition flags
        4: [],  # metric anomalies
        5: [],  # knowledge-base triggers
    }

    # Collect habit-miss items separately for merging
    habit_misses = []

    for raw in raw_insights:
        text = raw.lstrip("- ").strip()
        upper = text.upper()

        # Skip data quality noise (baseline accuracy warnings)
        if any(k in upper for k in ("NOTE:", "EXTREME VALUE", "BASELINE ACCURACY")):
            continue

        if "SLEEP REVIEW" in upper or "LAST NIGHT" in upper:
            # Restructure: VERDICT ||| key metrics ||| ACTION
            parts = text.split(" ||| ")
            verdict = parts[0] if parts else text  # "Sleep Review: FAIR"
            action = ""
            body_parts = []
            for p in parts[1:]:
                ps = p.strip()
                if ps.upper().startswith("ACTION:"):
                    action = ps
                else:
                    body_parts.append(ps)

            # Compress body: split all sentences, keep short metric summaries
            body_text = " ".join(body_parts)
            sentences = re.split(r'(?<!\d)\.\s+', body_text)
            # Keep sentences that are short metric observations (< 80 chars)
            # or that contain key terms (bedtime, duration, deep, REM)
            key_findings = []
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if len(s) < 80 or any(k in s.lower() for k in
                        ("total", "deep", "rem", "bedtime", "adequate", "target")):
                    # Compress to first clause if still long
                    if len(s) > 80:
                        s = s.split(';')[0].split(' - ')[0].strip()
                    key_findings.append(s)
                if len(key_findings) >= 3:
                    break

            result = verdict
            if key_findings:
                result += ". " + ". ".join(key_findings) + "."
            if action:
                # Take just the directive, strip trailing mechanism/profile text
                action_text = re.sub(r'^ACTION:\s*', '', action, flags=re.IGNORECASE)
                # Split on proper sentence boundaries first
                action_sents = re.split(r'(?<!\d)\.\s+', action_text)
                action_short = action_sents[0].strip()
                # Also split on profile-context phrases that leak through
                # (e.g., "...window Reduced deep sleep directly impacts...")
                action_short = re.split(
                    r'\s+(?:Reduced|With your|Monitor for|This is|Your neurological|Given your)',
                    action_short)[0].strip()
                if len(action_short) > 100:
                    action_short = action_short[:97].rsplit(' ', 1)[0] + '...'
                if not action_short.endswith('.') and not action_short.endswith('...'):
                    action_short += '.'
                result += f" -> {action_short}"
            buckets[0].append(result)
        elif any(k in upper for k in ("SPIKE", "TRAINING LOAD", "ACWR", "CARDIAC", "ARVC")):
            buckets[1].append(_format_insight(text))
        elif re.search(r'MISSED \d+/\d+ RECENT DAYS', upper):
            # Collect habit-miss items for merging
            label_match = re.match(r'^(.+?)\s+missed\s+(\d+/\d+)', text, re.IGNORECASE)
            if label_match:
                habit_misses.append(label_match.group(1).strip())
            else:
                buckets[2].append(_format_insight(text))
        elif any(k in upper for k in ("SCREEN TIME", "BEDTIME", "BROKEN", "CONSISTENCY",
                                       "CONSECUTIVE")):
            buckets[2].append(_format_insight(text))
        elif any(k in upper for k in ("CALORIE", "PROTEIN", "WATER", "DEHYDR", "DEFICIT")):
            buckets[3].append(_format_insight(text))
        elif any(k in upper for k in ("HRV", "RHR", "RESTING HR", "STRESS", "BODY BATTERY",
                                       "SLEEP DEBT", "CUMULATIVE", "DEEP SLEEP", "REM SLEEP",
                                       "SLEEP TREND")):
            buckets[4].append(_format_insight(text))
        else:
            buckets[5].append(_format_insight(text))

    # Merge habit misses into one line if multiple
    if habit_misses:
        if len(habit_misses) >= 3:
            names = ", ".join(habit_misses)
            buckets[2].insert(0,
                f"HABITS: {names} all missed 2/3+ days. "
                "Consistency compounds. Each broken habit reduces recovery capacity.")
        else:
            for h in habit_misses:
                buckets[2].append(
                    f"{h} missed 2/3+ recent days. Consistency with this habit affects recovery.")

    # Build final list in priority order
    distilled = []
    for priority in sorted(buckets.keys()):
        for text in buckets[priority]:
            if len(distilled) >= max_items:
                break
            distilled.append(text)
        if len(distilled) >= max_items:
            break

    return distilled


def _distill_for_phone(raw_insights, max_items=4):
    """Distill raw insights into 3-4 high-priority actionable items for the phone app.

    Priority order (what changes your day):
      1. Recovery/stress overload signals (stress budget, cumulative load)
      2. Physiological signals (HRV suppressed, RHR elevated)
      3. Sleep quality summary (one consolidated line)
      4. Habit patterns that compound with current state
      5. Training load status

    Rules:
      - DROP all "Note:", "extreme value", baseline accuracy noise
      - DEDUPLICATE related items (deep sleep % + deep sleep trending = one item)
      - CONDENSE each item to one sentence with the key number + consequence
      - Max 4 items for phone display
    """
    if not raw_insights:
        return []

    # Clean and categorize
    candidates = {
        "stress": [],      # stress budget, overload
        "physio": [],       # HRV, RHR
        "sleep_verdict": [],  # Sleep Review line
        "sleep_quality": [],  # deep/REM/trends/declining
        "habits": [],       # screen time, bedtime, activity
        "training": [],     # ACWR, steps, training load
        "contested": [],    # mixed-evidence insights from contradiction resolution
    }

    for raw in raw_insights:
        text = raw.lstrip("- ").strip()
        upper = text.upper()

        # DROP noise
        if any(k in upper for k in ("NOTE:", "EXTREME VALUE", "BASELINE ACCURACY")):
            continue

        # Contested insights from contradiction resolution — lowest priority bucket
        if text.startswith("[CONTESTED]"):
            text = text.replace("[CONTESTED] ", "", 1)  # strip marker for display
            candidates["contested"].append(_phone_condense(text))
            continue

        if "STRESS BUDGET" in upper or "STRESS CAPACITY" in upper:
            candidates["stress"].append(text)
        elif "SLEEP REVIEW" in upper:
            candidates["sleep_verdict"].append(text)
        elif any(k in upper for k in ("HRV", "HEART RATE VARIABILITY")):
            candidates["physio"].append(text)
        elif any(k in upper for k in ("RESTING HR", "RHR")):
            candidates["physio"].append(text)
        elif "GARMIN STRESS" in upper or "STRESS LEVEL" in upper:
            candidates["stress"].append(text)
        elif any(k in upper for k in ("DEEP SLEEP", "REM SLEEP", "REM ", "SLEEP QUALITY",
                                       "SLEEP TREND", "SLEEP DEBT", "DECLINING")):
            candidates["sleep_quality"].append(text)
        elif any(k in upper for k in ("SCREEN TIME", "BEDTIME TARGET", "BEDTIME MISSED",
                                       "CONSECUTIVE", "BROKEN", "MISSED")):
            candidates["habits"].append(text)
        elif any(k in upper for k in ("TRAINING", "ACWR", "STEPS")):
            candidates["training"].append(text)
        else:
            # Catch-all — try to fit into most relevant bucket
            if any(k in upper for k in ("COGNITIVE", "MEMORY", "EMOTIONAL REGULATION")):
                candidates["sleep_quality"].append(text)
            else:
                candidates["training"].append(text)

    distilled = []

    # 1. Stress/recovery — prefer "stress budget" over generic Garmin stress
    if candidates["stress"]:
        budget_item = next((t for t in candidates["stress"] if "BUDGET" in t.upper()), None)
        text = budget_item or candidates["stress"][0]
        distilled.append(_phone_condense(text))

    # 2. Physiological signals — merge HRV + RHR into one line if both present
    if candidates["physio"]:
        hrv_item = next((t for t in candidates["physio"] if "HRV" in t.upper()), None)
        rhr_item = next((t for t in candidates["physio"] if "RESTING HR" in t.upper() or "RHR" in t.upper()), None)
        if hrv_item and rhr_item:
            # Extract key numbers
            hrv_num = re.search(r'today:\s*(\d+)\s*ms', hrv_item)
            rhr_num = re.search(r'today:\s*(\d+)\s*bpm', rhr_item)
            hrv_str = f"HRV {hrv_num.group(1)}ms" if hrv_num else "HRV suppressed"
            rhr_str = f"RHR {rhr_num.group(1)}bpm" if rhr_num else "RHR elevated"
            distilled.append(f"{hrv_str} (below baseline), {rhr_str} (above baseline) — autonomic system under strain, recovery impaired.")
        elif hrv_item:
            distilled.append(_phone_condense(hrv_item))
        elif rhr_item:
            distilled.append(_phone_condense(rhr_item))

    # 3. Sleep — consolidate all sleep items into one summary line
    if candidates["sleep_verdict"]:
        # Use the sleep review line, condensed
        distilled.append(_phone_condense(candidates["sleep_verdict"][0]))
    elif candidates["sleep_quality"]:
        # No verdict — pick the most informative sleep item
        distilled.append(_phone_condense(candidates["sleep_quality"][0]))

    # 4. Habits — merge into one line
    if candidates["habits"] and len(distilled) < max_items:
        habit_names = []
        for h in candidates["habits"]:
            if "SCREEN" in h.upper():
                habit_names.append("screen time before bed")
            elif "BEDTIME" in h.upper():
                habit_names.append("bedtime consistency")
            elif "PHYSICAL" in h.upper() or "ACTIVITY" in h.upper():
                habit_names.append("physical activity")
            else:
                # Extract first few words as label
                label = h.split(" missed")[0].split(" broken")[0][:30].strip()
                if label and label not in habit_names:
                    habit_names.append(label)
        if habit_names:
            names = ", ".join(dict.fromkeys(habit_names))  # dedupe preserving order
            days = re.search(r'(\d+)\s+(?:of last\s+)?(\d+)\s+(?:recent\s+)?days', candidates["habits"][0])
            if days:
                distilled.append(f"Habits broken recently: {names}. These compound with poor sleep to reduce recovery.")
            else:
                distilled.append(f"Habits broken recently: {names}. Consistency compounds with recovery.")

    # 5. Training — if room
    if candidates["training"] and len(distilled) < max_items:
        distilled.append(_phone_condense(candidates["training"][0]))

    # 6. Contested (mixed-evidence) — only if room remains
    if candidates["contested"] and len(distilled) < max_items:
        distilled.append(candidates["contested"][0])

    return distilled[:max_items]


def _phone_condense(text):
    """Condense a verbose insight to 1-2 sentences for phone display.

    Keeps: the trigger (what happened + key number) and the consequence.
    Drops: mechanism details, citations, profile-specific elaboration.
    """
    text = _strip_citations(text)

    # For Sleep Review lines, restructure
    if "Sleep Review:" in text:
        parts = text.split(" ||| ")
        verdict = parts[0].strip()  # "Sleep Review: POOR"
        metrics = []
        action = ""
        for p in parts[1:]:
            p = p.strip()
            if p.startswith("->") or p.startswith("ACTION"):
                action = re.sub(r'^(->|ACTION:)\s*', '', p).strip()
            else:
                metrics.append(p)
        result = verdict
        if metrics:
            result += ". " + ". ".join(m.strip() for m in metrics if m.strip())
        if action:
            # First sentence of action only
            action_first = re.split(r'(?<!\d)\.\s+', action)[0].strip()
            if not action_first.endswith('.'):
                action_first += '.'
            result += " " + action_first
        return result

    # For [Training] lines, clean the bracket prefix
    text = re.sub(r'^\[Training\]\s*', '', text)

    # Split into trigger (first sentence) and body
    sentences = re.split(r'(?<!\d)\.\s{1,2}(?=[A-Z])', text, maxsplit=1)
    trigger = sentences[0].strip()

    if len(sentences) < 2:
        # Already concise
        if not trigger.endswith('.'):
            trigger += '.'
        return trigger

    body = sentences[1].strip()

    # Extract consequence: look for "-> " or "Cognitive impact:" or "Energy:"
    consequence = ""
    arrow_match = re.search(r'->\s*(.+?)(?:\.|$)', body)
    cog_match = re.search(r'Cognitive(?:\s+impact)?:\s*(.+?)(?=Energy:|Action:|$)', body, re.IGNORECASE)
    energy_match = re.search(r'Energy:\s*(.+?)(?=Cognitive|Action:|$)', body, re.IGNORECASE)

    if arrow_match:
        consequence = arrow_match.group(1).strip()
    elif cog_match:
        consequence = re.split(r'(?<!\d)\.\s+', cog_match.group(1).strip())[0]
    elif energy_match:
        consequence = re.split(r'(?<!\d)\.\s+', energy_match.group(1).strip())[0]

    result = trigger
    if not result.endswith('.'):
        result += '.'
    if consequence:
        consequence = consequence.strip().rstrip('.')
        result += f" Impact: {consequence}."

    # Hard cap at 200 chars
    if len(result) > 200:
        result = result[:197].rsplit(' ', 1)[0] + '...'

    return result


def _polish_text(text):
    """Final-stage cleanup for all user-facing text.

    Catches remaining artifacts: double-dash separators, orphaned
    prefixes, inconsistent capitalization.
    """
    if not text:
        return text
    # Convert any remaining " -- " to ". "
    text = text.replace(" -- ", ". ")
    # Clean up consecutive periods from ". " following a period
    text = re.sub(r'\.{2,}\s*', '. ', text)
    # Strip orphaned "TODAY: " prefix
    text = re.sub(r'^TODAY:\s*', '', text)
    # Ensure first character is capitalized
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text).strip()
    return text


def _distill_recommendations(raw_recs, max_items=3):
    """Restructure recommendations: clean presentation, keep substance.

    Strips citations, markdown formatting, and redundant labels.
    Keeps the full actionable content with reasoning.
    """
    if not raw_recs:
        return []

    prioritized = []
    rest = []
    for raw in raw_recs:
        text = raw.lstrip("- ").strip()
        text = _strip_citations(text)
        # Strip markdown bold
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        # Strip numbered list prefixes
        text = re.sub(r'^\d+\.\s+', '', text)
        # Strip "Cognitive impact:" / "Energy:" labels, fold into flow
        text = re.sub(r'Cognitive(?:\s+impact)?:\s*', '', text)
        text = re.sub(r'Energy:\s*', '', text)
        # Compress to 2-3 sentences
        sentences = re.split(r'(?<!\d)\.\s+', text)
        text = '. '.join(s.strip() for s in sentences[:3] if s.strip())
        if text and not text.endswith('.'):
            text += '.'

        if "DO THIS FIRST" in raw.upper():
            # Clean up "DO THIS FIRST: 1. Today (Day):" -> direct action
            text = re.sub(r'DO THIS FIRST:\s*\d*\.?\s*', '', text, flags=re.IGNORECASE)
            # Strip "Today (Day): " prefix entirely — start with the action
            text = re.sub(r'^Today\s*\([^)]+\):\s*', '', text, flags=re.IGNORECASE)
            # Capitalize first letter of remaining text
            if text and text[0].islower():
                text = text[0].upper() + text[1:]
            prioritized.append(text)
        else:
            rest.append(text)

    ordered = prioritized + rest
    return ordered[:max_items]


# ---------------------------------------------------------------------------
# Write to Google Sheets
# ---------------------------------------------------------------------------

def write_analysis(wb, target_date, score, label, sleep_context, training_status,
                   insights, recommendations, confidence, cognitive_assessment="",
                   data_quality_text="", quality_flags_text=""):
    """Upsert one row to the Overall Analysis tab."""
    import gspread
    try:
        sheet = wb.worksheet("Overall Analysis")
    except gspread.exceptions.WorksheetNotFound:
        # Auto-create if missing
        from setup_overall_analysis import setup_overall_analysis
        sheet = setup_overall_analysis(wb)

    date_str = str(target_date)
    day_str = date_to_day(date_str)

    # Distill verbose analysis into scannable spreadsheet text, then polish
    short_insights = [_polish_text(i) for i in _distill_insights(insights)]
    short_recs = [_polish_text(r) for r in _distill_recommendations(recommendations)]
    insights_text = "\n".join(f"- {i}" for i in short_insights) if short_insights else "No notable findings."
    recs_text = "\n".join(f"- {r}" for r in short_recs) if short_recs else "Maintain current routine."

    # Columns A-G (auto) — skip H-I (Cognition manual) — columns J-L (auto)
    left_part = [
        day_str,                                     # A  Day
        date_str,                                    # B  Date
        score if score is not None else "",           # C  Readiness Score
        label,                                       # D  Readiness Label
        confidence,                                   # E  Confidence
        cognitive_assessment,                         # F  Cognitive/Energy Assessment
        sleep_context,                                # G  Sleep Context
    ]
    right_part = [
        insights_text,                                # J  Key Insights
        recs_text,                                    # K  Recommendations
        training_status,                              # L  Training Load Status
        data_quality_text,                            # M  Data Quality
        quality_flags_text,                           # N  Quality Flags
    ]

    # Upsert by date
    all_dates = sheet.col_values(2)  # Date is column B
    if date_str in all_dates:
        row_index = all_dates.index(date_str) + 1
        # Write A-G and J-N separately to preserve manual H-I (Cognition)
        # Use RAW for text (dates, strings) so Sheets doesn't parse them
        sheet.update(range_name=f"A{row_index}:G{row_index}", values=[left_part], value_input_option="RAW")
        sheet.update(range_name=f"J{row_index}:N{row_index}", values=[right_part], value_input_option="RAW")
        # Rewrite score as number (RAW stores it as text, gradient needs number)
        if score is not None:
            sheet.update(range_name=f"C{row_index}", values=[[score]], value_input_option="USER_ENTERED")
        print(f"  Overall Analysis: updated {date_str}.")
    else:
        # New row: include empty placeholders for H-I
        full_row = left_part + ["", ""] + right_part
        sheet.append_row(full_row, value_input_option="RAW")
        # Fix score to be numeric (append_row with RAW stores as text)
        new_row_idx = len(sheet.col_values(2))
        if score is not None:
            sheet.update(range_name=f"C{new_row_idx}", values=[[score]], value_input_option="USER_ENTERED")
        print(f"  Overall Analysis: logged {date_str}.")

    # Sort data rows by date descending
    _sort_analysis_tab(sheet)

    # Refresh weekly banding after data change
    from setup_overall_analysis import apply_weekly_banding
    apply_weekly_banding(wb, sheet)

    # Verify conditional format rules survived banding; repair if lost
    try:
        from verify_formatting import verify_tab_formatting, repair_tab_formatting
        passed, _ = verify_tab_formatting(wb, "Overall Analysis")
        if not passed:
            repair_tab_formatting(wb, "Overall Analysis")
    except Exception:
        pass

    # Auto-resize rows to fit analysis text
    from sheets_formatting import auto_resize_rows
    auto_resize_rows(wb, "Overall Analysis")

    # Mirror to SQLite
    try:
        from sqlite_backup import get_db, upsert_overall_analysis
        db = get_db()
        upsert_overall_analysis(db, str(target_date), {
            "readiness_score": score,
            "readiness_label": label,
            "confidence": confidence,
            "cognitive_energy_assessment": cognitive_assessment,
            "sleep_context": sleep_context,
            "key_insights": insights_text,
            "recommendations": recs_text,
            "training_load_status": training_status,
            "data_quality": data_quality_text,
            "quality_flags": quality_flags_text,
        })
        db.commit()
    except Exception as e:
        print(f"  SQLite mirror (overall_analysis): {e}")


def _sort_analysis_tab(sheet):
    """Sort Overall Analysis data rows by date descending, preserving legend."""
    rows = sheet.get_all_values()
    if len(rows) < 3:
        return  # nothing to sort
    header = rows[0]
    data = [r for r in rows[1:] if r and len(r) > 1 and r[1] and str(r[1]).startswith("20")]
    non_data = [r for r in rows[1:] if not (r and len(r) > 1 and r[1] and str(r[1]).startswith("20"))]
    data.sort(key=lambda r: r[1], reverse=True)
    all_sorted = [header] + data + non_data
    max_cols = max(len(r) for r in all_sorted)
    for r in all_sorted:
        while len(r) < max_cols:
            r.append("")
    from gspread.utils import rowcol_to_a1
    end_col = rowcol_to_a1(1, max_cols).rstrip("1")
    sheet.update(range_name=f"A1:{end_col}{len(all_sorted)}", values=all_sorted,
                 value_input_option="RAW")

    # RAW write converts Column C (Readiness Score) to text strings, which breaks
    # numeric conditional formatting. Re-write score column as numbers.
    score_values = []
    for r in all_sorted[1:]:  # skip header
        val = r[2] if len(r) > 2 else ""  # Column C = index 2
        try:
            score_values.append([float(val)])
        except (ValueError, TypeError):
            score_values.append([val])  # keep blanks/text as-is
    if score_values:
        sheet.update(range_name=f"C2:C{len(all_sorted)}", values=score_values,
                     value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# Main Analysis Pipeline
# ---------------------------------------------------------------------------

def _maybe_run_validation(wb, target_date):
    """Run validation if it hasn't been run in the last 7 days."""
    log_path = Path(__file__).parent / "reference" / "validation_log.json"
    try:
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                log = json.load(f)
            if log:
                last_date = date.fromisoformat(log[-1]["date"])
                if (target_date - last_date).days < 7:
                    return  # Already ran this week
    except Exception:
        pass  # If log is corrupted, run validation anyway
    print("\n  [Auto-validation: weekly check triggered]")
    try:
        run_validation(wb, target_date)
    except Exception as e:
        print(f"  Warning: auto-validation failed: {e}")


def run_analysis(wb, target_date, cloud=False):
    """Run the full analysis pipeline for a given date.

    Args:
        wb: gspread Workbook (None if cloud=True)
        target_date: date object
        cloud: if True, read from Supabase instead of Sheets, skip Sheets writes
    """
    print(f"\n--- Overall Analysis for {target_date} {'[cloud mode]' if cloud else ''} ---")

    # Clear dedup registry for this run
    _hardcoded_kb_ids.clear()

    # Load health knowledge base
    knowledge = load_health_knowledge()

    # Load personal health profile (empty dict if none exists — zero regression)
    profile = load_profile()
    accommodations = get_accommodations(profile)
    knowledge = merge_knowledge(knowledge, profile)

    # Hydrate KB with personal validations from SQLite (not JSON)
    try:
        from sqlite_backup import get_db as _hydrate_db, load_kb_validations
        _hconn = _hydrate_db()
        _validations = load_kb_validations(_hconn)
        for _kb_id, _val_data in _validations.items():
            if _kb_id in knowledge:
                knowledge[_kb_id]["personal_validation"] = _val_data
    except Exception:
        pass  # SQLite unavailable — entries retain JSON-embedded data if any

    # Load behavioral correlations for personal validation annotations
    correlations = load_significant_correlations()

    # Read all data
    if cloud:
        data = read_all_data_from_supabase()
    else:
        data = read_all_data(wb)
    by_date_garmin = _rows_by_date(data["garmin"])
    by_date_sleep = _rows_by_date(data["sleep"])
    daily_log_by_date = _rows_by_date(data["daily_log"])
    nutrition_by_date = _rows_by_date(data["nutrition"])
    sessions_by_date_map = _sessions_by_date(data["session_log"])

    # Read Overall Analysis tab for orthosomnia safeguard (prior readiness labels)
    try:
        oa_by_date = _rows_by_date(_read_tab_as_dicts(wb, "Overall Analysis"))
    except Exception:
        oa_by_date = {}

    # Compute baselines
    baselines = compute_baselines(by_date_garmin, by_date_sleep, target_date)

    # Sleep context
    sleep_context, sleep_debt, sleep_trend, deep_trend, rem_trend, debt_night_count = analyze_sleep_context(
        by_date_sleep, by_date_garmin, target_date, baselines
    )

    # Training load
    acwr, training_status, acute_load, chronic_load = compute_acwr(
        sessions_by_date_map, target_date
    )

    # Dynamic sleep need (depends on sleep_debt + acwr)
    sleep_need = compute_sleep_need(baselines, sleep_debt, acwr, target_date)
    if sleep_need:
        print(f"  Sleep need: {sleep_need['sleep_need_hrs']:.1f}h tonight "
              f"(bed by {sleep_need['recommended_bedtime']}) "
              f"[{sleep_need['breakdown']}]")

    # Illness detection (probabilistic multi-metric anomaly scoring)
    try:
        from sqlite_backup import get_db as _illness_get_db
        illness_conn = _illness_get_db()
    except Exception:
        illness_conn = None
    illness = detect_illness(baselines, by_date_sleep, daily_log_by_date,
                             acwr, target_date,
                             by_date_garmin=by_date_garmin, conn=illness_conn)

    # Adaptive weighting — DISABLED until feature-space mismatch is resolved.
    # The optimizer trains on raw Garmin metrics but readiness uses z-scored features.
    # Re-enable via enable_adaptive_weights=true in user_config.json after rewrite.
    from utils import load_user_config as _load_uc
    _adaptive_enabled = _load_uc().get("enable_adaptive_weights", False)
    if _adaptive_enabled and (target_date.day == 1 or "--recalibrate" in sys.argv):
        adaptive_result = compute_adaptive_weights(illness_conn)
        if adaptive_result:
            config_path = Path(__file__).parent / "user_config.json"
            config = {}
            if config_path.exists():
                with open(config_path) as f:
                    config = json.load(f)
            config["adaptive_weights"] = {
                "readiness_weights": {
                    k: adaptive_result[k] for k in ("HRV", "Sleep", "RHR", "Subjective")
                },
                "metadata": {
                    k: adaptive_result[k]
                    for k in ("r_squared", "r_squared_default", "delta_r_squared", "n", "date")
                },
            }
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            print(f"  Adaptive weights saved to user_config.json")

        # Personal validation of contested KB entries (monthly alongside adaptive weights)
        update_personal_validations(knowledge, illness_conn)

    # Notes flags -- today + yesterday (days_back=2). Same-night is the causal
    # window for sugar/alcohol -> sleep. Multi-day patterns are covered by
    # analyze_food_cognition_lag() (30-day correlation).
    note_flags = parse_notes_for_flags(daily_log_by_date, nutrition_by_date,
                                       target_date, days_back=2,
                                       sessions_by_date=sessions_by_date_map,
                                       sleep_by_date=by_date_sleep)

    # Readiness score
    score, label, components, confidence = compute_readiness(
        baselines, (sleep_context, sleep_debt, sleep_trend, debt_night_count),
        daily_log_by_date, target_date, profile=profile
    )

    # Assess data quality for transparency
    data_quality, analysis_quality = _assess_data_quality(
        baselines, components, by_date_garmin, by_date_sleep, target_date
    )
    n_present = len(data_quality["present"])
    n_total = n_present + len(data_quality["missing"])
    if data_quality["missing"]:
        data_quality_text = f"{n_present}/{n_total}, no {', '.join(data_quality['missing'])}"
    else:
        data_quality_text = "Full"
    quality_flags_text = " | ".join(data_quality["flags"]) if data_quality["flags"] else ""

    # Extract sleep analysis text and verdict from Sleep tab
    sleep_row = by_date_sleep.get(str(target_date))
    sleep_analysis_text = sleep_row.get("Sleep Analysis", "") if sleep_row else ""
    sleep_verdict = ""
    if sleep_analysis_text and " - " in sleep_analysis_text:
        sleep_verdict = sleep_analysis_text.split(" - ", 1)[0].strip()  # GOOD/FAIR/POOR

    # Insights (with knowledge base + condensed sleep analysis)
    insights = generate_insights(
        baselines, sleep_debt, sleep_trend, acwr, training_status,
        note_flags, daily_log_by_date, by_date_garmin,
        by_date_sleep, sessions_by_date_map, target_date,
        knowledge=knowledge, sleep_analysis_text=sleep_analysis_text,
        deep_trend=deep_trend, rem_trend=rem_trend, profile=profile,
        nutrition_by_date=nutrition_by_date, oa_by_date=oa_by_date,
        correlations=correlations
    )

    # Dynamic knowledge triggers — auto-fires insights for any knowledge entry
    # with a "trigger" field. New entries added by /update-intel automatically
    # participate without code changes.
    data_sources = {
        "garmin": by_date_garmin,
        "sleep": by_date_sleep,
        "daily_log": daily_log_by_date,
        "nutrition": nutrition_by_date,
    }
    # Collect IDs already used by hardcoded insights to avoid duplicates
    kb_triggered = scan_knowledge_triggers(
        knowledge, data_sources, sessions_by_date_map, target_date
    )
    insights.extend(kb_triggered)

    # Recommendations (with knowledge base + profile filtering)
    recommendations = generate_recommendations(
        score, label, sleep_debt, acwr, note_flags, baselines, target_date,
        knowledge=knowledge, profile=profile,
        sessions_by_date=sessions_by_date_map,
        correlations=correlations
    )

    # Inject illness detection results into insights + recommendations
    illness_label = illness["illness_label"]
    if illness_label != "normal":
        signal_summary = "; ".join(s.split("[")[0].strip() for s in illness["signals"][:3])
        if illness_label in ("illness_ongoing", "recovering"):
            # Active episode -- add context that low scores are expected
            illness_insight = (f"illness episode active ({illness_label.replace('_', ' ')}): "
                               f"low readiness scores are expected during recovery")
        else:
            illness_insight = (f"possible illness indicator: "
                               f"{illness_label.replace('_', ' ')} "
                               f"(score {illness['illness_score']:.0f}/14): {signal_summary}")
        insights.insert(0, illness_insight)  # highest priority
        if illness["recommendation"]:
            recommendations.insert(0, illness["recommendation"])

    # Cognitive/Energy Assessment
    cognitive_assessment = assess_cognitive_state(
        baselines, sleep_debt, note_flags, by_date_sleep,
        sessions_by_date_map, target_date, knowledge=knowledge,
        profile=profile
    )

    # Print summary to terminal
    print(f"  Readiness: {score}/10 ({label}) | Confidence: {confidence}")
    if components:
        comp_parts = [f"{k}: {v:.1f} ({d})" for k, (v, d) in components.items()]
        print(f"  Components: {' | '.join(comp_parts)}")
    print(f"  Sleep: {sleep_context}")
    print(f"  Training: {training_status}")
    print(f"  Cognitive: {cognitive_assessment[:150]}{'...' if len(cognitive_assessment) > 150 else ''}")
    if insights:
        print(f"  Insights ({len(insights)}):")
        for i in insights[:3]:
            print(f"    - {i[:120]}{'...' if len(i) > 120 else ''}")
    if recommendations:
        print(f"  Recommendations ({len(recommendations)}):")
        for r in recommendations[:2]:
            print(f"    - {r[:120]}{'...' if len(r) > 120 else ''}")

    # Write to Sheets (skip in cloud mode)
    if not cloud and wb is not None:
        write_analysis(wb, target_date, score, label, sleep_context, training_status,
                       insights, recommendations, confidence, cognitive_assessment,
                       data_quality_text, quality_flags_text)

        # Auto-validation: run weekly (every Sunday) to check prediction accuracy
        if target_date.weekday() == 6:  # Sunday
            _maybe_run_validation(wb, target_date)

    # Distill for phone app (separate from Sheets distillation)
    phone_insights = _distill_for_phone(insights)
    phone_recs = _distill_recommendations(recommendations)

    return {
        "score": score,
        "label": label,
        "confidence": confidence,
        "insights": insights,
        "phone_insights": phone_insights,
        "phone_recommendations": phone_recs,
        "recommendations": recommendations,
        "cognitive_assessment": cognitive_assessment,
        "sleep_context": sleep_context,
        "sleep_verdict": sleep_verdict,
        "sleep_trend": sleep_trend,
        "sleep_debt": sleep_debt,
        "sleep_need": sleep_need,
        "illness": illness,
        "illness_label": illness.get("illness_label", "normal"),
        "bed_variability": sleep_row.get("Bedtime Variability (7d)", "") if sleep_row else "",
        "wake_variability": sleep_row.get("Wake Variability (7d)", "") if sleep_row else "",
        "data_quality": data_quality,
        "analysis_quality": analysis_quality,
        "data_quality_text": data_quality_text,
        "quality_flags_text": quality_flags_text,
    }


def run_week_summary(wb, target_date):
    """Generate a 7-day summary analysis."""
    print(f"\n=== WEEKLY SUMMARY (ending {target_date}) ===\n")

    scores = []
    for offset in range(7):
        d = target_date - timedelta(days=offset)
        try:
            result = run_analysis(wb, d)
            score, label = result["score"], result["label"]
            if score is not None:
                scores.append((d, score, label))
        except Exception as e:
            print(f"  Skipping {d}: {e}")

    if scores:
        avg_score = sum(s for _, s, _ in scores) / len(scores)
        avg_label = "Poor"
        for threshold, lbl in READINESS_LABELS:
            if avg_score >= threshold:
                avg_label = lbl
                break
        print(f"\n  7-day average readiness: {avg_score:.1f}/10 ({avg_label})")
        print(f"  Days analyzed: {len(scores)}")
        best = max(scores, key=lambda x: x[1])
        worst = min(scores, key=lambda x: x[1])
        print(f"  Best day: {best[0]} ({best[1]}/10 {best[2]})")
        print(f"  Worst day: {worst[0]} ({worst[1]}/10 {worst[2]})")


def run_validation(wb, target_date):
    """Correlation monitor: readiness scores vs actual next-day outcomes.

    Correlates readiness scores with next-day Morning Energy and Day Rating
    over the past 28 days. Reports Pearson r, approximate p-value, and
    Fisher z 95% confidence interval. Suppresses strong interpretive language
    unless evidence meets minimum thresholds (n >= 21, CI lower > 0, p < 0.05).
    """
    import math

    print(f"\n=== CORRELATION MONITOR (28 days ending {target_date}) ===\n")

    data = read_all_data(wb)
    daily_log_by_date = _rows_by_date(data.get("daily_log", []))

    # Read Overall Analysis tab for readiness scores (not in read_all_data)
    analysis_rows = []
    try:
        sheet = wb.worksheet("Overall Analysis")
        all_vals = sheet.get_all_values()
        if len(all_vals) > 1:
            headers = all_vals[0]
            analysis_rows = [dict(zip(headers, row)) for row in all_vals[1:]]
    except Exception:
        pass

    analysis_by_date = {}
    for row in analysis_rows:
        d = row.get("Date", "")
        if d:
            analysis_by_date[d] = row

    # Collect (readiness_score, next_day_energy, next_day_rating) triplets
    pairs_energy = []
    pairs_rating = []

    for offset in range(1, 29):  # 28 days back
        d = target_date - timedelta(days=offset)
        d_str = str(d)
        next_d_str = str(d + timedelta(days=1))

        analysis = analysis_by_date.get(d_str, {})
        score = _safe_float(analysis.get("Readiness Score"))
        if score is None:
            continue

        next_dl = daily_log_by_date.get(next_d_str, {})
        energy = _safe_float(next_dl.get("Morning Energy (1-10)"))
        rating = _safe_float(next_dl.get("Day Rating (1-10)"))

        if energy is not None:
            pairs_energy.append((score, energy))
        if rating is not None:
            pairs_rating.append((score, rating))

    def _pearson_with_stats(pairs):
        """Compute Pearson r, approximate p-value, and Fisher z 95% CI."""
        n = len(pairs)
        if n < 7:
            return {"r": None, "n": n, "p": None, "ci_low": None, "ci_high": None}

        xs, ys = zip(*pairs)
        mx = sum(xs) / n
        my = sum(ys) / n
        sx = sum((x - mx) ** 2 for x in xs)
        sy = sum((y - my) ** 2 for y in ys)
        sxy = sum((x - mx) * (y - my) for x, y in pairs)
        if sx == 0 or sy == 0:
            return {"r": None, "n": n, "p": None, "ci_low": None, "ci_high": None}

        r = sxy / (sx * sy) ** 0.5
        r = max(-1.0, min(1.0, r))  # clamp for numerical safety

        # Approximate two-tailed p-value via t-distribution
        # t = r * sqrt((n-2) / (1-r²)), df = n-2
        # For df >= 7, approximate p from t using normal CDF (adequate for monitoring)
        p = None
        if abs(r) < 1.0:
            t_stat = r * math.sqrt((n - 2) / (1 - r * r))
            # Normal approximation of two-tailed p (conservative for small n)
            p = 2 * (1 - _norm_cdf(abs(t_stat)))

        # Fisher z transform for 95% CI
        ci_low, ci_high = None, None
        if n >= 10 and abs(r) < 1.0:
            z_r = 0.5 * math.log((1 + r) / (1 - r))  # Fisher z
            se = 1.0 / math.sqrt(n - 3)
            z_low = z_r - 1.96 * se
            z_high = z_r + 1.96 * se
            # Back-transform to r scale
            ci_low = (math.exp(2 * z_low) - 1) / (math.exp(2 * z_low) + 1)
            ci_high = (math.exp(2 * z_high) - 1) / (math.exp(2 * z_high) + 1)

        return {"r": r, "n": n, "p": p, "ci_low": ci_low, "ci_high": ci_high}

    stats_energy = _pearson_with_stats(pairs_energy)
    stats_rating = _pearson_with_stats(pairs_rating)

    def _format_result(label, stats):
        r, n, p = stats["r"], stats["n"], stats["p"]
        print(f"  {label}: ", end="")
        if r is None:
            print(f"insufficient data (n={n}, need 7+)")
            return
        parts = [f"r={r:+.3f}", f"n={n}"]
        if p is not None:
            parts.append(f"p={p:.3f}")
        if stats["ci_low"] is not None:
            parts.append(f"95% CI [{stats['ci_low']:+.3f}, {stats['ci_high']:+.3f}]")
        print(", ".join(parts))

    _format_result("Readiness vs next-day Morning Energy", stats_energy)
    _format_result("Readiness vs next-day Day Rating    ", stats_rating)

    # Interpretation — conservative: require n >= 21, CI lower > 0, p < 0.05
    valid_stats = [s for s in [stats_energy, stats_rating] if s["r"] is not None]
    if valid_stats:
        avg_r = sum(s["r"] for s in valid_stats) / len(valid_stats)
        print(f"\n  Average correlation: r={avg_r:+.3f}")

        # Check if ANY result meets the evidence bar
        meets_bar = any(
            s["n"] >= 21 and s["p"] is not None and s["p"] < 0.05
            and s["ci_low"] is not None and s["ci_low"] > 0
            for s in valid_stats
        )

        if meets_bar:
            if avg_r >= 0.5:
                print("  Positive trend: readiness shows strong correlation with outcomes.")
            elif avg_r >= 0.3:
                print("  Positive trend: readiness shows moderate correlation with outcomes.")
            elif avg_r >= 0.15:
                print("  Weak positive trend. Consider whether subjective logging is consistent enough.")
            else:
                print("  No meaningful correlation detected despite adequate data.")
                print("  Consider logging Morning Energy more consistently.")
        else:
            # Below the evidence bar — no strong language
            n_max = max(s["n"] for s in valid_stats)
            if n_max < 21:
                print(f"  Not enough paired observations yet (best n={n_max}, need 21+). "
                      "Trend direction is suggestive only.")
            else:
                print("  Correlation does not reach statistical significance (p >= 0.05 or CI crosses zero).")
                print("  Trend direction is suggestive only.")

    # Save validation log
    log_path = Path(__file__).parent / "reference" / "validation_log.json"
    log_entry = {
        "date": str(target_date),
        "r_energy": round(stats_energy["r"], 4) if stats_energy["r"] is not None else None,
        "n_energy": stats_energy["n"],
        "p_energy": round(stats_energy["p"], 4) if stats_energy["p"] is not None else None,
        "ci_energy": [round(stats_energy["ci_low"], 4), round(stats_energy["ci_high"], 4)]
            if stats_energy["ci_low"] is not None else None,
        "r_rating": round(stats_rating["r"], 4) if stats_rating["r"] is not None else None,
        "n_rating": stats_rating["n"],
        "p_rating": round(stats_rating["p"], 4) if stats_rating["p"] is not None else None,
        "ci_rating": [round(stats_rating["ci_low"], 4), round(stats_rating["ci_high"], 4)]
            if stats_rating["ci_low"] is not None else None,
        "window_days": 28,
    }
    try:
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                log = json.load(f)
        else:
            log = []
        log.append(log_entry)
        # Keep last 52 entries (1 year of weekly checks)
        log = log[-52:]
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        print(f"\n  Validation logged -> {log_path}")
    except Exception as e:
        print(f"\n  Warning: could not write validation log: {e}")

    # Also run personal validation of contested KB entries
    try:
        from sqlite_backup import get_db as _val_get_db
        val_conn = _val_get_db()
    except Exception:
        val_conn = None
    if val_conn:
        knowledge = load_health_knowledge()
        # Hydrate from SQLite before running validation
        try:
            from sqlite_backup import load_kb_validations as _val_load
            for _kid, _vd in _val_load(val_conn).items():
                if _kid in knowledge:
                    knowledge[_kid]["personal_validation"] = _vd
        except Exception:
            pass
        update_personal_validations(knowledge, val_conn)

    return log_entry


# ---------------------------------------------------------------------------
# Historical Reanalysis
# ---------------------------------------------------------------------------

def run_reanalysis(wb, start_date=None, skip_confirm=False):
    """Rerun analysis on all historical dates using current methodology.

    Reads all data once, computes analysis for each date in chronological order
    (oldest first so baselines build correctly), then batch-writes results.
    Preserves manual columns H (Cognition) and I (Cognition Notes) on OA tab,
    and column G (Notes) on Sleep tab.
    """
    import gspread
    import time as _time
    from sleep_analysis import generate_sleep_analysis, load_circadian_profile
    from utils import get_scoring_thresholds as _get_scoring_thresholds

    print("\n=== HISTORICAL REANALYSIS ===\n")

    # ------------------------------------------------------------------
    # Phase A: Bulk read (all data in ~8 API calls)
    # ------------------------------------------------------------------
    print("Phase A: Reading all data...")
    data = read_all_data(wb)
    by_date_garmin = _rows_by_date(data["garmin"])
    by_date_sleep = _rows_by_date(data["sleep"])
    daily_log_by_date = _rows_by_date(data["daily_log"])
    nutrition_by_date = _rows_by_date(data["nutrition"])
    sessions_by_date_map = _sessions_by_date(data["session_log"])

    # Read Overall Analysis tab — extract dates and preserve manual columns H-I
    oa_rows = _read_tab_as_dicts(wb, "Overall Analysis")
    manual_data = {}  # {date_str: (cognition_val, cognition_notes)}
    oa_dates = set()
    for row in oa_rows:
        d = row.get("Date", "")
        if d and d.startswith("20"):
            oa_dates.add(d)
            h_val = row.get("Cognition (1-10)", "")
            i_val = row.get("Cognition Notes", "")
            manual_data[d] = (h_val, i_val)

    # Read Sleep tab — build row index for targeted column updates
    sleep_sheet = wb.worksheet("Sleep")
    sleep_all = sleep_sheet.get_all_values()
    sleep_headers = sleep_all[0] if sleep_all else []
    sleep_row_index = {}  # {date_str: row_number (1-based)}
    sleep_dates = set()
    date_col_idx = sleep_headers.index("Date") if "Date" in sleep_headers else 1
    for i, row in enumerate(sleep_all[1:], start=2):
        if len(row) > date_col_idx:
            d = row[date_col_idx]
            if d and d.startswith("20"):
                sleep_row_index[d] = i
                sleep_dates.add(d)

    # Load knowledge base, profile, thresholds once
    knowledge = load_health_knowledge()
    profile = load_profile()
    knowledge = merge_knowledge(knowledge, profile)
    scoring_t = _get_scoring_thresholds()
    circ = load_circadian_profile()

    # Hydrate KB with personal validations from SQLite
    try:
        from sqlite_backup import get_db as _hydrate_db, load_kb_validations
        _hconn = _hydrate_db()
        _validations = load_kb_validations(_hconn)
        for _kb_id, _val_data in _validations.items():
            if _kb_id in knowledge:
                knowledge[_kb_id]["personal_validation"] = _val_data
    except Exception:
        pass

    # Load behavioral correlations for personal validation annotations
    correlations = load_significant_correlations()

    # Determine all dates to process (union of OA and Sleep dates)
    all_dates = sorted(oa_dates | sleep_dates)
    if start_date:
        all_dates = [d for d in all_dates if d >= str(start_date)]

    if not all_dates:
        print("No dates found to reanalyze.")
        return

    print(f"  Found {len(all_dates)} dates ({all_dates[0]} to {all_dates[-1]})")
    if start_date:
        print(f"  Filtered from {start_date}")

    # Confirmation prompt
    if not skip_confirm:
        print(f"\nThis will reanalyze {len(all_dates)} dates and rebuild illness episode history.")
        print("Manual columns (Cognition H-I, Sleep Notes G) will be preserved.")
        try:
            response = input("Proceed? [y/N] ").strip().lower()
            if response != "y":
                print("Aborted.")
                return
        except EOFError:
            print("Non-interactive mode — use --yes to skip confirmation.")
            return

    # ------------------------------------------------------------------
    # Phase B: Compute all results in memory (0 API calls)
    # ------------------------------------------------------------------
    print("\nPhase B: Computing analysis for all dates...")

    # Clear and rebuild illness state for clean chronological replay
    try:
        from sqlite_backup import get_db
        db = get_db()
        db.execute("DELETE FROM illness_state")
        db.execute("DELETE FROM illness_daily_log")
        db.commit()
        print("  Cleared illness episode history for rebuild.")
    except Exception as e:
        print(f"  Warning: could not clear illness tables: {e}")
        db = None

    # Progressive oa_by_date — starts empty, filled as we compute
    oa_by_date = {}
    oa_results = []     # [{date, day, score, label, ...}, ...]
    sleep_results = {}  # {date_str: (score, analysis_text, descriptor)}

    for i, date_str in enumerate(all_dates):
        target_date = date.fromisoformat(date_str)

        # Clear dedup registry per date
        _hardcoded_kb_ids.clear()

        # Compute baselines (180-day backward lookback)
        baselines = compute_baselines(by_date_garmin, by_date_sleep, target_date)

        # Sleep context
        sleep_context, sleep_debt, sleep_trend, deep_trend, rem_trend, debt_night_count = analyze_sleep_context(
            by_date_sleep, by_date_garmin, target_date, baselines
        )

        # Training load
        acwr, training_status, acute_load, chronic_load = compute_acwr(
            sessions_by_date_map, target_date
        )

        # Illness detection (replays episode creation chronologically)
        illness = detect_illness(baselines, by_date_sleep, daily_log_by_date,
                                 acwr, target_date,
                                 by_date_garmin=by_date_garmin, conn=db)

        # Notes flags
        note_flags = parse_notes_for_flags(daily_log_by_date, nutrition_by_date,
                                           target_date, days_back=2,
                                           sessions_by_date=sessions_by_date_map,
                                           sleep_by_date=by_date_sleep)

        # Readiness score
        score, label, components, confidence = compute_readiness(
            baselines, (sleep_context, sleep_debt, sleep_trend, debt_night_count),
            daily_log_by_date, target_date, profile=profile
        )

        # Data quality
        data_quality, analysis_quality = _assess_data_quality(
            baselines, components, by_date_garmin, by_date_sleep, target_date
        )
        n_present = len(data_quality["present"])
        n_total = n_present + len(data_quality["missing"])
        if data_quality["missing"]:
            data_quality_text = f"{n_present}/{n_total}, no {', '.join(data_quality['missing'])}"
        else:
            data_quality_text = "Full"
        quality_flags_text = " | ".join(data_quality["flags"]) if data_quality["flags"] else ""

        # Sleep analysis text for insights
        sleep_row = by_date_sleep.get(date_str)
        sleep_analysis_text = sleep_row.get("Sleep Analysis", "") if sleep_row else ""

        # Insights (with progressive oa_by_date for orthosomnia safeguard)
        insights = generate_insights(
            baselines, sleep_debt, sleep_trend, acwr, training_status,
            note_flags, daily_log_by_date, by_date_garmin,
            by_date_sleep, sessions_by_date_map, target_date,
            knowledge=knowledge, sleep_analysis_text=sleep_analysis_text,
            deep_trend=deep_trend, rem_trend=rem_trend, profile=profile,
            nutrition_by_date=nutrition_by_date, oa_by_date=oa_by_date,
            correlations=correlations
        )

        # Knowledge triggers
        data_sources = {
            "garmin": by_date_garmin, "sleep": by_date_sleep,
            "daily_log": daily_log_by_date, "nutrition": nutrition_by_date,
        }
        kb_triggered = scan_knowledge_triggers(
            knowledge, data_sources, sessions_by_date_map, target_date
        )
        insights.extend(kb_triggered)

        # Recommendations
        recommendations = generate_recommendations(
            score, label, sleep_debt, acwr, note_flags, baselines, target_date,
            knowledge=knowledge, profile=profile,
            sessions_by_date=sessions_by_date_map,
            correlations=correlations
        )

        # Inject illness results
        illness_label = illness["illness_label"]
        if illness_label != "normal":
            signal_summary = "; ".join(s.split("[")[0].strip() for s in illness["signals"][:3])
            if illness_label in ("illness_ongoing", "recovering"):
                illness_insight = (f"illness episode active ({illness_label.replace('_', ' ')}): "
                                   f"low readiness scores are expected during recovery")
            else:
                illness_insight = (f"possible illness indicator: "
                                   f"{illness_label.replace('_', ' ')} "
                                   f"(score {illness['illness_score']:.0f}/14): {signal_summary}")
            insights.insert(0, illness_insight)
            if illness["recommendation"]:
                recommendations.insert(0, illness["recommendation"])

        # Cognitive assessment
        cognitive_assessment = assess_cognitive_state(
            baselines, sleep_debt, note_flags, by_date_sleep,
            sessions_by_date_map, target_date, knowledge=knowledge,
            profile=profile
        )

        # Distill for spreadsheet
        short_insights = [_polish_text(t) for t in _distill_insights(insights)]
        short_recs = [_polish_text(r) for r in _distill_recommendations(recommendations)]
        insights_text = "\n".join(f"- {t}" for t in short_insights) if short_insights else "No notable findings."
        recs_text = "\n".join(f"- {r}" for r in short_recs) if short_recs else "Maintain current routine."

        # Store OA result
        day_str = date_to_day(date_str)
        oa_results.append({
            "date": date_str,
            "day": day_str,
            "score": score,
            "label": label,
            "confidence": confidence,
            "cognitive_assessment": cognitive_assessment,
            "sleep_context": sleep_context,
            "insights_text": insights_text,
            "recs_text": recs_text,
            "training_status": training_status,
            "data_quality_text": data_quality_text,
            "quality_flags_text": quality_flags_text,
        })

        # Update progressive oa_by_date for next iteration's orthosomnia check
        oa_by_date[date_str] = {
            "Readiness Score (1-10)": score,
            "Readiness Label": label,
            "Date": date_str,
        }

        # Regenerate sleep analysis if sleep data exists for this date
        if sleep_row and date_str in sleep_row_index:
            # Build data dict from sleep row for generate_sleep_analysis
            sleep_data = {}
            for key, header in [
                ("sleep_duration", "Total Sleep (hrs)"),
                ("sleep_score", "Garmin Sleep Score"),
                ("sleep_deep_pct", "Deep %"),
                ("sleep_rem_pct", "REM %"),
                ("hrv", "Overnight HRV (ms)"),
                ("sleep_avg_respiration", "Avg Respiration"),
                ("sleep_awakenings", "Awakenings"),
                ("sleep_cycles", "Sleep Cycles"),
                ("sleep_body_battery_gained", "Body Battery Gained"),
                ("sleep_deep_min", "Deep Sleep (min)"),
                ("sleep_rem_min", "REM (min)"),
                ("sleep_light_min", "Light Sleep (min)"),
                ("sleep_awake_min", "Awake During Sleep (min)"),
                ("sleep_time_in_bed", "Time in Bed (hrs)"),
                ("sleep_bedtime", "Bedtime"),
            ]:
                sleep_data[key] = sleep_row.get(header, "")
            # Build sleep_context dict for enriched sleep analysis
            sa_context = {
                "sleep_debt": sleep_debt,
                "deep_trend": deep_trend,
                "rem_trend": rem_trend,
                "debt_night_count": debt_night_count,
            }
            new_score, new_analysis, new_descriptor = generate_sleep_analysis(
                sleep_data, thresholds=scoring_t, circadian_profile=circ,
                knowledge=knowledge, profile=profile,
                sleep_context=sa_context, behavior_flags=note_flags
            )
            sleep_results[date_str] = (new_score, new_analysis, new_descriptor)

        # Progress reporting
        if (i + 1) % 25 == 0 or (i + 1) == len(all_dates):
            print(f"  Computed {i + 1}/{len(all_dates)} dates...")

    if db:
        db.commit()  # commit illness episode rebuilds

    # ------------------------------------------------------------------
    # Phase C: Batch write to Sheets
    # ------------------------------------------------------------------
    print(f"\nPhase C: Writing {len(oa_results)} dates to Sheets...")

    # --- C1: Overall Analysis tab ---
    _write_analysis_batch(wb, oa_results, manual_data)

    # --- C2: Sleep tab (columns D, F, Y only) ---
    if sleep_results:
        _write_sleep_batch(sleep_sheet, sleep_row_index, sleep_results)

    # --- C3: SQLite bulk upsert ---
    print("  Syncing to SQLite...")
    try:
        from sqlite_backup import get_db, upsert_overall_analysis
        db = get_db()
        for r in oa_results:
            upsert_overall_analysis(db, r["date"], {
                "readiness_score": r["score"],
                "readiness_label": r["label"],
                "confidence": r["confidence"],
                "cognitive_energy_assessment": r["cognitive_assessment"],
                "sleep_context": r["sleep_context"],
                "key_insights": r["insights_text"],
                "recommendations": r["recs_text"],
                "training_load_status": r["training_status"],
                "data_quality": r["data_quality_text"],
                "quality_flags": r["quality_flags_text"],
            })
        db.commit()
        print(f"  SQLite: upserted {len(oa_results)} rows.")
    except Exception as e:
        print(f"  SQLite sync error: {e}")

    # ------------------------------------------------------------------
    # Phase D: Finalize
    # ------------------------------------------------------------------
    print("\nPhase D: Finalizing (sort, banding, formatting)...")

    oa_sheet = wb.worksheet("Overall Analysis")

    # Sort by date descending
    _sort_analysis_tab(oa_sheet)

    # Weekly banding
    try:
        from setup_overall_analysis import apply_weekly_banding
        apply_weekly_banding(wb, oa_sheet)
    except Exception as e:
        print(f"  Warning: banding failed: {e}")

    # Verify + repair conditional formatting
    try:
        from verify_formatting import verify_tab_formatting, repair_tab_formatting
        passed, _ = verify_tab_formatting(wb, "Overall Analysis")
        if not passed:
            repair_tab_formatting(wb, "Overall Analysis")
            print("  Repaired OA formatting.")
        else:
            print("  OA formatting: PASS")
    except Exception as e:
        print(f"  Warning: formatting verify failed: {e}")

    # Auto-resize rows
    try:
        from sheets_formatting import auto_resize_rows
        auto_resize_rows(wb, "Overall Analysis")
    except Exception:
        pass

    # Export dashboard
    try:
        from dashboard.export_dashboard_data import export as export_dashboard
        export_dashboard()
        print("  Dashboard exported.")
    except Exception as e:
        print(f"  Warning: dashboard export failed: {e}")

    print(f"\n=== Reanalysis complete: {len(oa_results)} OA dates, "
          f"{len(sleep_results)} sleep dates updated ===")


def _write_analysis_batch(wb, results, manual_data):
    """Batch-write all reanalysis results to the Overall Analysis tab.

    Writes the full grid with RAW mode, then fixes numeric columns C and H
    with USER_ENTERED so gradient formatting renders correctly.
    """
    import gspread

    sheet = wb.worksheet("Overall Analysis")

    # Build complete row set sorted by date descending
    rows = []
    for r in results:
        h_val, i_val = manual_data.get(r["date"], ("", ""))
        row = [
            r["day"],                  # A  Day
            r["date"],                 # B  Date
            r["score"] if r["score"] is not None else "",  # C  Readiness Score
            r["label"],                # D  Readiness Label
            r["confidence"],           # E  Confidence
            r["cognitive_assessment"], # F  Cognitive/Energy Assessment
            r["sleep_context"],        # G  Sleep Context
            h_val,                     # H  Cognition (manual — preserved)
            i_val,                     # I  Cognition Notes (manual — preserved)
            r["insights_text"],        # J  Key Insights
            r["recs_text"],            # K  Recommendations
            r["training_status"],      # L  Training Load Status
            r["data_quality_text"],    # M  Data Quality
            r["quality_flags_text"],   # N  Quality Flags
        ]
        rows.append(row)

    # Sort descending by date (column B = index 1)
    rows.sort(key=lambda r: r[1], reverse=True)

    # Build grid with header
    header = list(OVERALL_ANALYSIS_HEADERS)
    all_data = [header] + rows
    last_row = len(all_data)

    # Single batch write with RAW (preserves date/time strings)
    print(f"  Writing {len(rows)} rows to Overall Analysis (RAW)...")
    sheet.update(range_name=f"A1:N{last_row}", values=all_data,
                 value_input_option="RAW")

    # Fix column C (Readiness Score) to numeric for gradient formatting
    score_cells = []
    for i, row in enumerate(rows, start=2):  # row 2 onward (1-indexed, skip header)
        val = row[2]  # Column C
        if val != "" and val is not None:
            try:
                score_cells.append(gspread.Cell(row=i, col=3, value=float(val)))
            except (ValueError, TypeError):
                pass
    if score_cells:
        sheet.update_cells(score_cells, value_input_option="USER_ENTERED")
        print(f"  Fixed {len(score_cells)} score cells to numeric.")

    # Fix column H (Cognition) to numeric for gradient formatting
    cog_cells = []
    for i, row in enumerate(rows, start=2):
        val = row[7]  # Column H
        if val != "" and val is not None:
            try:
                cog_cells.append(gspread.Cell(row=i, col=8, value=float(val)))
            except (ValueError, TypeError):
                pass
    if cog_cells:
        sheet.update_cells(cog_cells, value_input_option="USER_ENTERED")
        print(f"  Fixed {len(cog_cells)} cognition cells to numeric.")

    # Clear any leftover rows below the new data
    try:
        total_rows = sheet.row_count
        if total_rows > last_row:
            clear_range = f"A{last_row + 1}:N{total_rows}"
            sheet.batch_clear([clear_range])
    except Exception:
        pass


def _write_sleep_batch(sleep_sheet, sleep_row_index, sleep_results):
    """Batch-write regenerated sleep analysis to Sleep tab columns D, F, Y only.

    Performs surgical column updates — never touches other columns including
    G (Notes), raw Garmin data, or variability columns.
    """
    import gspread

    # Build cell lists for each column
    d_cells = []  # Column D (Sleep Analysis Score) — numeric, USER_ENTERED
    f_cells = []  # Column F (Sleep Analysis text) — RAW
    y_cells = []  # Column Y (Sleep Descriptor) — RAW

    for date_str, (score, analysis_text, descriptor) in sleep_results.items():
        row_num = sleep_row_index.get(date_str)
        if not row_num:
            continue

        if score is not None:
            d_cells.append(gspread.Cell(row=row_num, col=4, value=float(score)))

        f_cells.append(gspread.Cell(row=row_num, col=6, value=analysis_text or ""))
        y_cells.append(gspread.Cell(row=row_num, col=25, value=descriptor or ""))

    # Write each column batch
    if d_cells:
        sleep_sheet.update_cells(d_cells, value_input_option="USER_ENTERED")
        print(f"  Sleep col D (score): updated {len(d_cells)} cells.")

    if f_cells:
        sleep_sheet.update_cells(f_cells, value_input_option="RAW")
        print(f"  Sleep col F (analysis): updated {len(f_cells)} cells.")

    if y_cells:
        sleep_sheet.update_cells(y_cells, value_input_option="RAW")
        print(f"  Sleep col Y (descriptor): updated {len(y_cells)} cells.")


def main():
    parser = argparse.ArgumentParser(description="Overall health analysis engine.")
    parser.add_argument("--date", help="Analyze specific date (YYYY-MM-DD)")
    parser.add_argument("--today", action="store_true", help="Analyze today")
    parser.add_argument("--week", action="store_true", help="7-day summary")
    parser.add_argument("--validate", action="store_true",
                        help="Run prediction validation (28-day check)")
    parser.add_argument("--reanalyze", action="store_true",
                        help="Rerun analysis on all historical dates with current methodology")
    parser.add_argument("--reanalyze-from", metavar="YYYY-MM-DD",
                        help="Reanalyze from this date forward (default: all)")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt for --reanalyze")
    parser.add_argument("--cloud", action="store_true",
                        help="Use Supabase instead of Google Sheets (for CI/cloud)")
    parser.add_argument("--migrate-validations", action="store_true",
                        help="One-time: move personal_validation from JSON to SQLite")
    args = parser.parse_args()

    if args.migrate_validations:
        kb_path = Path(__file__).parent / "reference" / "health_knowledge.json"
        if not kb_path.exists():
            print("health_knowledge.json not found.")
            return
        with open(kb_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        from sqlite_backup import get_db, upsert_kb_validation
        mconn = get_db()
        migrated = 0
        for entry in data.get("knowledge", []):
            pv = entry.get("personal_validation")
            if pv and isinstance(pv, dict) and pv.get("status"):
                upsert_kb_validation(
                    mconn, entry["id"], pv["status"],
                    pv.get("r", 0), pv.get("n", 0), pv.get("p", 1.0),
                    pv.get("last_computed", "")
                )
                migrated += 1
        mconn.commit()
        # Strip personal_validation from JSON
        stripped = 0
        for entry in data.get("knowledge", []):
            if "personal_validation" in entry:
                del entry["personal_validation"]
                stripped += 1
        if stripped:
            with open(kb_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Migrated {migrated} validations to SQLite, stripped {stripped} from JSON.")
        return

    today = date.today()
    if args.date:
        target_date = date.fromisoformat(args.date)
    elif args.today:
        target_date = today
    else:
        target_date = today - timedelta(days=1)  # default: yesterday

    if args.cloud:
        # Cloud mode: read from Supabase, write results back to Supabase only
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / ".env")
        result = run_analysis(None, target_date, cloud=True)
        # Write results to Supabase
        from supabase_sync import init_supabase, upsert_overall_analysis
        client = init_supabase()
        if client and result:
            upsert_overall_analysis(client, str(target_date), {
                "readiness_score": result.get("score"),
                "readiness_label": result.get("label"),
                "confidence": result.get("confidence"),
                "cognitive_energy_assessment": result.get("cognitive_assessment"),
                "sleep_context": result.get("sleep_context"),
                "key_insights": "\n".join(f"- {i}" for i in result.get("phone_insights", result.get("insights", []))),
                "recommendations": "\n".join(f"- {r}" for r in result.get("phone_recommendations", result.get("recommendations", []))),
                "data_quality": result.get("data_quality_text", ""),
                "quality_flags": result.get("quality_flags_text", ""),
                "sleep_need_hrs": result.get("sleep_need", {}).get("sleep_need_hrs") if result.get("sleep_need") else None,
                "recommended_bedtime": result.get("sleep_need", {}).get("recommended_bedtime") if result.get("sleep_need") else None,
                "sleep_debt": result.get("sleep_debt"),
            })
            print("[cloud] Results written to Supabase.")
    else:
        wb = get_workbook()
        if args.reanalyze:
            start = date.fromisoformat(args.reanalyze_from) if args.reanalyze_from else None
            run_reanalysis(wb, start_date=start, skip_confirm=args.yes)
        elif args.validate:
            run_validation(wb, target_date)
        elif args.week:
            run_week_summary(wb, target_date)
        else:
            run_analysis(wb, target_date)

    print("\nDone.")


if __name__ == "__main__":
    main()
