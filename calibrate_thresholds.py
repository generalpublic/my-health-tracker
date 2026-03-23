"""
calibrate_thresholds.py — Auto-calibration engine for personalized health thresholds.

Analyzes a user's historical data from SQLite and sets personalized color grading
thresholds and scoring parameters based on their actual distributions.

Algorithm:
  1. Pull N days of data from SQLite (fast, no API quota)
  2. Compute per-metric percentile bands (p15, p30, p50, p70, p85)
  3. Set thresholds at percentile boundaries with clinical floor/ceiling clamps
  4. Write calibrated values to user_config.json and thresholds.json

Usage:
  python calibrate_thresholds.py              # auto-detect data availability
  python calibrate_thresholds.py --days 30    # use last 30 days
  python calibrate_thresholds.py --dry-run    # print without writing
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "health_tracker.db"
USER_CONFIG_PATH = PROJECT_DIR / "user_config.json"
THRESHOLDS_PATH = PROJECT_DIR / "thresholds.json"

# Minimum data points needed per metric group before calibration
MIN_DATA = {
    "resting_hr": 7,
    "body_battery": 7,
    "steps": 7,
    "sleep_duration": 14,
    "deep_pct": 14,
    "rem_pct": 14,
    "overnight_hrv": 14,
    "awakenings": 7,
    "body_battery_gained": 7,
    "avg_stress": 7,
    "bedtime": 7,
    "avg_hr_sleep": 7,
    "avg_respiration": 7,
}

# Clinical floor/ceiling clamps — prevent absurd thresholds regardless of user data
CLINICAL_CLAMPS = {
    # (metric_key, "green"/"red", "min"/"max", clamp_value)
    # "green min" = never set green threshold below this value
    # "red max"   = never set red threshold above this value
    "overnight_hrv":       {"green_min": 20,   "red_min": 10},
    "resting_hr":          {"green_max": 70,   "red_min": 40},
    "sleep_duration":      {"green_min": 6.5,  "red_min": 4.0},
    "deep_pct":            {"green_min": 12,   "red_min": 5},
    "rem_pct":             {"green_min": 12,   "red_min": 5},
    "body_battery_gained": {"green_min": 30,   "red_min": 5},
    "body_battery":        {"green_min": 40,   "red_min": 10},
    "steps":               {"green_min": 5000, "red_min": 1000},
    "avg_stress":          {"green_max": 40,   "red_min": 10},
    "awakenings":          {"green_max": 5,    "red_min": 0},
    "avg_hr_sleep":        {"green_max": 70,   "red_min": 40},
    "avg_respiration":     {"green_max": 20,   "red_min": 12},
}


def _fetch_metric(conn, table, column, days=None):
    """Fetch non-null numeric values for a metric from SQLite."""
    query = f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL AND {column} != ''"
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        query += f" AND date >= '{cutoff}'"
    query += " ORDER BY date DESC"
    cur = conn.execute(query)
    values = []
    for row in cur:
        try:
            v = float(row[0])
            values.append(v)
        except (ValueError, TypeError):
            continue
    return values


def _fetch_bedtimes(conn, days=None):
    """Fetch bedtime strings and convert to float hours (18-30 range)."""
    query = "SELECT bedtime FROM sleep WHERE bedtime IS NOT NULL AND bedtime != ''"
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        query += f" AND date >= '{cutoff}'"
    cur = conn.execute(query)
    import re
    hours = []
    for row in cur:
        m = re.match(r'^(\d{1,2}):(\d{2})$', str(row[0]).strip())
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            effective = h + mi / 60.0
            if effective < 18:
                effective += 24  # after-midnight bedtimes
            hours.append(effective)
    return hours


def _apply_clamps(metric_key, green, yellow, red, direction):
    """Apply clinical floor/ceiling clamps to prevent absurd thresholds."""
    clamps = CLINICAL_CLAMPS.get(metric_key, {})

    if direction == "higher_better":
        # Green is highest, red is lowest
        if "green_min" in clamps:
            green = max(green, clamps["green_min"])
        if "red_min" in clamps:
            red = max(red, clamps["red_min"])
    else:
        # Green is lowest, red is highest (lower_better)
        if "green_max" in clamps:
            green = min(green, clamps["green_max"])
        if "red_min" in clamps:
            red = max(red, clamps["red_min"])

    return green, yellow, red


def calibrate(days=None, dry_run=False):
    """Run auto-calibration on user's historical data.

    Args:
        days: number of days to analyze (None = all available data)
        dry_run: if True, print results without writing to files
    """
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Run 'python garmin_sync.py --today' first to create the database.")
        return False

    conn = sqlite3.connect(str(DB_PATH))

    # Define all metrics to calibrate
    # (key, table, column, direction, percentile_for_green, percentile_for_red)
    metrics = [
        # Sleep tab metrics (higher_better)
        ("overnight_hrv",       "sleep",  "overnight_hrv_ms",      "higher_better", 70, 15),
        ("sleep_duration",      "sleep",  "total_sleep_hrs",       "higher_better", 70, 15),
        ("deep_pct",            "sleep",  "deep_pct",              "higher_better", 70, 15),
        ("rem_pct",             "sleep",  "rem_pct",               "higher_better", 70, 15),
        ("body_battery_gained", "sleep",  "body_battery_gained",   "higher_better", 70, 15),

        # Sleep tab metrics (lower_better)
        ("awakenings",          "sleep",  "awakenings",            "lower_better",  30, 85),
        ("avg_hr_sleep",        "sleep",  "avg_hr",                "lower_better",  30, 85),
        ("avg_respiration",     "sleep",  "avg_respiration",       "lower_better",  30, 85),

        # Garmin tab metrics
        ("resting_hr",          "garmin", "resting_hr",            "lower_better",  30, 85),
        ("body_battery",        "garmin", "body_battery",          "higher_better", 70, 15),
        ("steps",               "garmin", "steps",                 "higher_better", 70, 15),
        ("avg_stress",          "garmin", "avg_stress_level",      "lower_better",  30, 85),
    ]

    results = {}
    skipped = []

    print("=" * 60)
    print("  HEALTH TRACKER — AUTO-CALIBRATION")
    print("=" * 60)
    print()

    if days:
        print(f"  Analyzing last {days} days of data...")
    else:
        print("  Analyzing all available data...")
    print()

    for key, table, column, direction, p_green, p_red in metrics:
        values = _fetch_metric(conn, table, column, days)
        min_required = MIN_DATA.get(key, 7)

        if len(values) < min_required:
            skipped.append((key, len(values), min_required))
            continue

        arr = np.array(values)
        p15 = float(np.percentile(arr, 15))
        p30 = float(np.percentile(arr, 30))
        p50 = float(np.percentile(arr, 50))
        p70 = float(np.percentile(arr, 70))
        p85 = float(np.percentile(arr, 85))

        if direction == "higher_better":
            green = float(np.percentile(arr, p_green))
            yellow = float(np.percentile(arr, 50))
            red = float(np.percentile(arr, p_red))
        else:
            green = float(np.percentile(arr, p_green))
            yellow = float(np.percentile(arr, 50))
            red = float(np.percentile(arr, p_red))

        green, yellow, red = _apply_clamps(key, green, yellow, red, direction)

        # Round to reasonable precision
        if key in ("steps",):
            green, yellow, red = round(green, -2), round(yellow, -2), round(red, -2)
        elif key in ("awakenings",):
            green, yellow, red = round(green), round(yellow), round(red)
        else:
            green, yellow, red = round(green, 1), round(yellow, 1), round(red, 1)

        results[key] = {
            "direction": direction,
            "green": green,
            "yellow": yellow,
            "red": red,
            "mean": round(float(np.mean(arr)), 1),
            "std": round(float(np.std(arr)), 1),
            "n": len(values),
            "p50": round(p50, 1),
        }

    # Bedtime calibration (special — relative to target)
    bedtimes = _fetch_bedtimes(conn, days)
    if len(bedtimes) >= MIN_DATA.get("bedtime", 7):
        bt_arr = np.array(bedtimes)
        results["bedtime"] = {
            "direction": "time_earlier_better",
            "mean_hour": round(float(np.mean(bt_arr)), 2),
            "std_hour": round(float(np.std(bt_arr)), 2),
            "n": len(bedtimes),
            "p50": round(float(np.percentile(bt_arr, 50)), 2),
        }

    conn.close()

    # Build scoring_params overrides (for sleep_analysis.py)
    scoring_overrides = {}
    if "overnight_hrv" in results:
        r = results["overnight_hrv"]
        scoring_overrides["hrv_floor"] = r["red"]
        scoring_overrides["hrv_ceiling"] = r["green"]
    if "sleep_duration" in results:
        r = results["sleep_duration"]
        scoring_overrides["sleep_duration_floor"] = max(r["red"], 4.0)
        scoring_overrides["sleep_duration_ceiling"] = r["green"]
    if "deep_pct" in results:
        r = results["deep_pct"]
        scoring_overrides["deep_pct_floor"] = r["red"]
        scoring_overrides["deep_pct_ceiling"] = r["green"]
    if "rem_pct" in results:
        r = results["rem_pct"]
        scoring_overrides["rem_pct_floor"] = r["red"]
        scoring_overrides["rem_pct_ceiling"] = r["green"]
    if "body_battery_gained" in results:
        r = results["body_battery_gained"]
        scoring_overrides["body_battery_ceiling"] = r["green"]
    if "awakenings" in results:
        r = results["awakenings"]
        scoring_overrides["awakenings_max"] = r["red"]

    # Print results table
    print(f"  {'Metric':<25} {'Your Avg':>10} {'Green':>10} {'Yellow':>10} {'Red':>10} {'Days':>6}")
    print("  " + "-" * 73)

    for key, r in results.items():
        if key == "bedtime":
            # Convert float hour back to HH:MM for display
            def _hour_to_hhmm(h):
                h = h % 24
                return f"{int(h):02d}:{int((h % 1) * 60):02d}"
            print(f"  {'Bedtime':<25} {_hour_to_hhmm(r['mean_hour']):>10} {'(relative to target)':>32} {r['n']:>6}")
            continue

        avg_str = f"{r['mean']:.1f}"
        if r["direction"] == "higher_better":
            print(f"  {key:<25} {avg_str:>10} {'>=' + str(r['green']):>10} {str(r['yellow']):>10} {'<' + str(r['red']):>10} {r['n']:>6}")
        else:
            print(f"  {key:<25} {avg_str:>10} {'<=' + str(r['green']):>10} {str(r['yellow']):>10} {'>' + str(r['red']):>10} {r['n']:>6}")

    if skipped:
        print()
        print("  Skipped (insufficient data):")
        for key, n, req in skipped:
            print(f"    {key}: {n} days (need {req})")

    print()

    if dry_run:
        print("  DRY RUN — no files written.")
        print()
        if scoring_overrides:
            print("  Scoring overrides that would be written:")
            for k, v in scoring_overrides.items():
                print(f"    {k}: {v}")
        return True

    # Write to user_config.json
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH) as f:
            config = json.load(f)
    else:
        config = {}

    config.setdefault("thresholds", {})
    config["thresholds"]["mode"] = "calibrated"
    config["thresholds"]["calibration_date"] = datetime.now().strftime("%Y-%m-%d")
    config["thresholds"]["overrides"] = scoring_overrides

    with open(USER_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  Written: {USER_CONFIG_PATH}")

    # Update dashboard_metrics in thresholds.json with calibrated color grades
    if THRESHOLDS_PATH.exists():
        with open(THRESHOLDS_PATH) as f:
            thresholds = json.load(f)

        dm = thresholds.get("dashboard_metrics", {})
        sf = thresholds.get("sheets_formatting", {}).get("Sleep", {}).get("gradient", [])

        # Map calibration keys to dashboard_metrics keys and sheets_formatting headers
        DASHBOARD_MAP = {
            "overnight_hrv":       "overnight_hrv_ms",
            "sleep_duration":      "total_sleep_hrs",
            "deep_pct":            "deep_pct",
            "rem_pct":             "rem_pct",
            "resting_hr":          "resting_hr",
            "body_battery":        "body_battery",
            "body_battery_gained": "body_battery_gained",
            "steps":               "steps",
            "avg_stress":          "avg_stress_level",
        }

        SHEETS_HEADER_MAP = {
            "overnight_hrv":       "Overnight HRV (ms)",
            "sleep_duration":      "Total Sleep (hrs)",
            "deep_pct":            "Deep %",
            "rem_pct":             "REM %",
            "body_battery_gained": "Body Battery Gained",
            "awakenings":          "Awakenings",
            "avg_hr_sleep":        "Avg HR",
            "avg_respiration":     "Avg Respiration",
        }

        for cal_key, r in results.items():
            if cal_key == "bedtime":
                continue

            # Update dashboard_metrics
            dm_key = DASHBOARD_MAP.get(cal_key)
            if dm_key and dm_key in dm:
                dm[dm_key]["red"] = r["red"]
                dm[dm_key]["yellow"] = r["yellow"]
                dm[dm_key]["green"] = r["green"]

            # Update sheets_formatting gradient thresholds
            sf_header = SHEETS_HEADER_MAP.get(cal_key)
            if sf_header:
                for g in sf:
                    if g["header"] == sf_header:
                        if r["direction"] == "higher_better":
                            g["min"] = r["red"]
                            g["mid"] = r["yellow"]
                            g["max"] = r["green"]
                        else:
                            g["min"] = r["green"]
                            g["mid"] = r["yellow"]
                            g["max"] = r["red"]
                        break

        # Write back
        with open(THRESHOLDS_PATH, "w") as f:
            json.dump(thresholds, f, indent=2)
        print(f"  Written: {THRESHOLDS_PATH}")

    print()
    print("  Calibration complete. Run 'python reformat_style.py' to apply")
    print("  new color grades to Google Sheets.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Auto-calibrate health thresholds")
    parser.add_argument("--days", type=int, default=None,
                        help="Number of days to analyze (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results without writing files")
    args = parser.parse_args()

    success = calibrate(days=args.days, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
