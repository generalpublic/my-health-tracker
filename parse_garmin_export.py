"""
parse_garmin_export.py — Import full Garmin history from local export files.

Reads the JSON files from your Garmin Connect data export and writes all
data to Google Sheets + the Raw Data Archive. Zero Garmin API calls.

Usage:
    python parse_garmin_export.py                           # uses default folder
    python parse_garmin_export.py --folder "custom/path"   # custom export folder
    python parse_garmin_export.py --dry-run                 # preview dates, no writes
    python parse_garmin_export.py --start 2024-01-01        # only process from date
    python parse_garmin_export.py --end   2025-12-31        # only process up to date
"""

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

from utils import get_workbook, date_to_day
from schema import ARCHIVE_KEYS, SLEEP_HEADERS, NUTRITION_HEADERS
from utils import get_sheet
from writers import setup_headers, get_or_create_archive_sheet
from models import from_garmin_api, to_sheets_row

# Default export folder (relative to this script)
DEFAULT_EXPORT_FOLDER = Path(__file__).parent / "data" / "garmin_export"

# Sub-paths within the export
WELLNESS_DIR   = Path("DI_CONNECT/DI-Connect-Wellness")
AGGREGATOR_DIR = Path("DI_CONNECT/DI-Connect-Aggregator")
FITNESS_DIR    = Path("DI_CONNECT/DI-Connect-Fitness")


# ---------------------------------------------------------------------------
# Loaders — each returns a dict keyed by date string "YYYY-MM-DD"
# ---------------------------------------------------------------------------

def load_sleep(base: Path) -> dict:
    """Load all sleepData JSON files -> {date_str: sleep_record}."""
    folder = base / WELLNESS_DIR
    result = {}
    for f in sorted(folder.glob("*_sleepData.json")):
        records = _load_json(f)
        if not isinstance(records, list):
            continue
        for rec in records:
            d = rec.get("calendarDate", "")
            if d:
                result[d] = rec
    print(f"  Sleep records loaded  : {len(result)}")
    return result


def load_uds(base: Path) -> dict:
    """Load all UDSFile JSON files -> {date_str: uds_record}."""
    folder = base / AGGREGATOR_DIR
    result = {}
    for f in sorted(folder.glob("UDSFile_*.json")):
        records = _load_json(f)
        if not isinstance(records, list):
            continue
        for rec in records:
            d = rec.get("calendarDate", "")
            if d:
                result[d] = rec
    print(f"  UDS records loaded    : {len(result)}")
    return result


def load_hrv(base: Path) -> dict:
    """
    Load healthStatusData JSON files -> {date_str: hrv_value}.
    Only available from ~Aug 2025 onward in Garmin exports.
    """
    folder = base / WELLNESS_DIR
    result = {}
    for f in sorted(folder.glob("*_healthStatusData.json")):
        records = _load_json(f)
        if not isinstance(records, list):
            continue
        for rec in records:
            d = rec.get("calendarDate", "")
            if not d:
                continue
            for metric in rec.get("metrics", []):
                if metric.get("type") == "HRV" and metric.get("value"):
                    result[d] = metric["value"]
                    break
    print(f"  HRV records loaded    : {len(result)}")
    return result


def load_activities(base: Path) -> dict:
    """
    Load summarizedActivities JSON -> {date_str: activity_record}.
    One activity per date (takes the first/longest if multiple on same day).
    """
    folder = base / FITNESS_DIR
    result = {}
    for f in sorted(folder.glob("*_summarizedActivities.json")):
        outer = _load_json(f)
        if not isinstance(outer, list) or not outer:
            continue
        activities = outer[0].get("summarizedActivitiesExport", [])
        for act in activities:
            # startTimeLocal is a ms timestamp representing LOCAL time as UTC
            ts = act.get("startTimeLocal") or act.get("beginTimestamp")
            if not ts:
                continue
            try:
                local_dt = datetime.utcfromtimestamp(ts / 1000)
                d = local_dt.strftime("%Y-%m-%d")
            except Exception:
                continue
            # Keep the longer activity if two exist on the same day
            if d not in result or act.get("duration", 0) > result[d].get("duration", 0):
                result[d] = act
    print(f"  Activity records loaded: {len(result)}")
    return result


# ---------------------------------------------------------------------------
# Compute 7-day rolling HRV average
# ---------------------------------------------------------------------------

def build_hrv_7day(hrv_dict: dict) -> dict:
    """Return {date_str: 7_day_avg} computed from hrv_dict."""
    dates = sorted(hrv_dict.keys())
    result = {}
    for i, d in enumerate(dates):
        window = [
            hrv_dict[x]
            for x in dates[max(0, i - 6): i + 1]
            if hrv_dict.get(x)
        ]
        if window:
            result[d] = round(sum(window) / len(window), 1)
    return result


# ---------------------------------------------------------------------------
# Merge all sources into a single data dict for one date
# ---------------------------------------------------------------------------

def _utc_offset_hours(u: dict) -> int:
    """
    Infer UTC offset (e.g. -5 for EST, -4 for EDT) from UDS wellness timestamps.
    Compares wellnessStartTimeGmt vs wellnessStartTimeLocal — handles DST automatically.
    Falls back to -5 (EST) if fields are missing or unparseable.
    """
    gmt_str   = u.get("wellnessStartTimeGmt", "")
    local_str = u.get("wellnessStartTimeLocal", "")
    if gmt_str and local_str:
        try:
            gmt_dt   = datetime.fromisoformat(gmt_str.split(".")[0])
            local_dt = datetime.fromisoformat(local_str.split(".")[0])
            return int((local_dt - gmt_dt).total_seconds() // 3600)
        except Exception:
            pass
    return -5  # default: US Eastern Standard Time


def merge(date_str: str, sleep: dict, uds: dict, hrv: dict,
          hrv_7day: dict, activities: dict) -> dict:
    data = {}

    # --- HRV ---
    data["hrv"]      = hrv.get(date_str, "")
    data["hrv_7day"] = hrv_7day.get(date_str, "")

    # --- UDS (daily wellness summary) ---
    u = uds.get(date_str, {})
    data["resting_hr"]      = u.get("restingHeartRate", "")
    data["steps"]           = u.get("totalSteps", "")
    data["total_calories"]  = u.get("totalKilocalories", "")
    data["active_calories"] = u.get("activeKilocalories", "")
    data["bmr_calories"]    = u.get("bmrKilocalories", "")
    data["moderate_min"]    = u.get("moderateIntensityMinutes", "")
    data["vigorous_min"]    = u.get("vigorousIntensityMinutes", "")

    floors_m = u.get("floorsAscendedInMeters", "")
    data["floors_ascended"] = round(floors_m / 3.048) if floors_m else ""

    # Stress — use TOTAL aggregator; Garmin uses -1/-2 as "no data" sentinels
    data["avg_stress"] = ""
    data["stress_qualifier"] = ""
    stress_obj = u.get("allDayStress", {})
    for agg in stress_obj.get("aggregatorList", []):
        if agg.get("type") == "TOTAL":
            raw_stress = agg.get("averageStressLevel", "")
            data["avg_stress"] = raw_stress if isinstance(raw_stress, (int, float)) and raw_stress >= 0 else ""
            break

    # Body battery
    data["body_battery"] = ""
    data["bb_high"]      = ""
    data["bb_low"]       = ""
    data["bb_at_wake"]   = ""
    data["sleep_body_battery_gained"] = ""
    bb_obj = u.get("bodyBattery", {})
    if bb_obj:
        data["body_battery"] = bb_obj.get("chargedValue", "")
        for stat in bb_obj.get("bodyBatteryStatList", []):
            t = stat.get("bodyBatteryStatType", "")
            v = stat.get("statsValue", "")
            if t == "HIGHEST":
                data["bb_high"] = v
            elif t == "LOWEST":
                data["bb_low"] = v
            elif t == "SLEEPEND":       # body battery value at end of sleep (wake)
                data["bb_at_wake"] = v
            elif t == "DURINGSLEEP":    # net body battery gained during sleep
                data["sleep_body_battery_gained"] = v

    # --- Sleep ---
    s = sleep.get(date_str, {})
    deep_s  = s.get("deepSleepSeconds",  0) or 0
    light_s = s.get("lightSleepSeconds", 0) or 0
    rem_s   = s.get("remSleepSeconds",   0) or 0
    awake_s = s.get("awakeSleepSeconds", 0) or 0

    data["sleep_duration"]   = round((deep_s + light_s + rem_s) / 3600, 2) if s else ""
    data["sleep_deep_min"]   = round(deep_s  / 60, 1) if s else ""
    data["sleep_light_min"]  = round(light_s / 60, 1) if s else ""
    data["sleep_rem_min"]    = round(rem_s   / 60, 1) if s else ""
    data["sleep_awake_min"]  = round(awake_s / 60, 1) if s else ""

    scores = s.get("sleepScores", {})
    data["sleep_score"]       = scores.get("overallScore", "")
    data["sleep_awakenings"]  = s.get("awakeCount", "")
    data["sleep_avg_respiration"] = s.get("averageRespiration", "")

    # Bedtime / wake — convert GMT to local time using per-day UTC offset from UDS
    from datetime import timedelta as _td
    _tz_offset = _utc_offset_hours(u)  # e.g. -5 for EST, -4 for EDT
    start_str = s.get("sleepStartTimestampGMT", "")
    end_str   = s.get("sleepEndTimestampGMT",   "")

    def _fmt_local(ts_str):
        if not ts_str:
            return ""
        try:
            dt = datetime.fromisoformat(ts_str.split(".")[0])
            dt_local = dt + _td(hours=_tz_offset)
            return dt_local.strftime("%H:%M")
        except Exception:
            return ""

    data["sleep_bedtime"]   = _fmt_local(start_str)
    data["sleep_wake_time"] = _fmt_local(end_str)

    if start_str and end_str:
        try:
            start_dt = datetime.fromisoformat(start_str.split(".")[0])
            end_dt   = datetime.fromisoformat(end_str.split(".")[0])
            data["sleep_time_in_bed"] = round((end_dt - start_dt).total_seconds() / 3600, 2)
        except Exception:
            data["sleep_time_in_bed"] = ""
    else:
        data["sleep_time_in_bed"] = ""

    # Deep/REM percentages
    total_sleep_s = deep_s + light_s + rem_s
    data["sleep_deep_pct"] = round(deep_s / total_sleep_s * 100, 1) if total_sleep_s else ""
    data["sleep_rem_pct"]  = round(rem_s  / total_sleep_s * 100, 1) if total_sleep_s else ""

    data["sleep_cycles"]   = ""   # not in export
    data["sleep_avg_hr"]   = ""   # not in export at record level

    _feedback_map = {
        "POSITIVE_LONG_AND_DEEP": "Long & Deep",
        "POSITIVE_REFRESHING":    "Refreshing",
        "POSITIVE_LATE_BED_TIME": "Late Bedtime",
        "NEGATIVE_SHORT":         "Too Short",
        "NEGATIVE_FRAGMENTED":    "Fragmented",
        "NEGATIVE_POOR_QUALITY":  "Poor Quality",
        "NEGATIVE_LATE_BED_TIME": "Late Bedtime",
    }
    raw_fb = scores.get("feedback", "")
    data["sleep_feedback"] = _feedback_map.get(
        raw_fb, raw_fb.replace("_", " ").title() if raw_fb else ""
    )
    data["sleep_body_battery_gained"] = ""   # use bb chargedValue proxy if needed

    # --- Activity ---
    act = activities.get(date_str, {})
    if act:
        dist  = act.get("distance",     0) or 0
        dur   = act.get("duration",     0) or 0
        speed = act.get("avgSpeed",     0) or 0
        elev  = act.get("elevationGain", "")

        ts_local = act.get("startTimeLocal") or act.get("beginTimestamp", 0)
        try:
            start_local = datetime.utcfromtimestamp(ts_local / 1000).strftime("%Y-%m-%d %H:%M")
        except Exception:
            start_local = ""

        # Export units: distance=centimeters, duration=milliseconds, speed=(m/s)/10, elevation=centimeters
        data["activity_name"]     = act.get("name", "")
        data["activity_type"]     = act.get("activityType", "")
        data["activity_start"]    = start_local
        data["activity_distance"] = round(dist / 160934.4,      2) if dist  else ""   # cm -> miles
        data["activity_duration"] = round(dur  / 1000 / 60,     1) if dur   else ""   # ms -> minutes
        data["activity_avg_hr"]   = act.get("avgHr", "") or ""  # 0 means no data
        data["activity_max_hr"]   = act.get("maxHr", "") or ""  # 0 means no data
        if data["activity_avg_hr"] == 0: data["activity_avg_hr"] = ""
        if data["activity_max_hr"] == 0: data["activity_max_hr"] = ""
        data["activity_calories"] = round(act.get("calories", 0))  if act.get("calories") else ""
        data["activity_elevation"]= round(elev / 100,           1) if elev  else ""   # cm -> meters
        data["activity_avg_speed"]= round(speed * 10 * 2.23694, 2) if speed else ""   # (m/s)/10 -> mph
        data["aerobic_te"]        = act.get("aerobicTrainingEffect", "")
        data["anaerobic_te"]      = act.get("anaerobicTrainingEffect", "")
        # HR zones: export stores milliseconds in hrTimeInZone_0..6 — convert to minutes
        for i in range(1, 6):
            zone_ms = act.get(f"hrTimeInZone_{i}", 0) or 0
            data[f"zone_{i}"] = round(zone_ms / 60000, 1) if zone_ms else ""
    else:
        for k in ["activity_name", "activity_type", "activity_start", "activity_distance",
                  "activity_duration", "activity_avg_hr", "activity_max_hr", "activity_calories",
                  "activity_elevation", "activity_avg_speed", "aerobic_te", "anaerobic_te",
                  "zone_1", "zone_2", "zone_3", "zone_4", "zone_5"]:
            data[k] = ""

    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  Warning: could not read {path.name}: {e}")
        return []



# ---------------------------------------------------------------------------
# Validation — reads back every tab from Google Sheets and verifies accuracy
# ---------------------------------------------------------------------------

# Expected column headers and their validation rules per tab.
# Rules: type ("numeric"/"date"/"time"/"text"), min/max for numeric, optional=True means blank is OK.
TAB_VALIDATIONS = {
    "Garmin": [
        ("Date",                        {"type": "date"}),
        ("HRV (overnight avg)",         {"type": "numeric", "min": 10,  "max": 200,   "optional": True}),
        ("HRV 7-day avg",               {"type": "numeric", "min": 10,  "max": 200,   "optional": True}),
        ("Resting HR",                  {"type": "numeric", "min": 30,  "max": 120,   "optional": True}),
        ("Sleep Duration (hrs)",        {"type": "numeric", "min": 0,   "max": 16,    "optional": True}),
        ("Sleep Score",                 {"type": "numeric", "min": 0,   "max": 100,   "optional": True}),
        ("Body Battery",                {"type": "numeric", "min": 0,   "max": 110,   "optional": True}),
        ("Steps",                       {"type": "numeric", "min": 0,   "max": 60000, "optional": True}),
        ("Total Calories Burned",       {"type": "numeric", "min": 100, "max": 10000, "optional": True}),
        ("Active Calories Burned",      {"type": "numeric", "min": 0,   "max": 8000,  "optional": True}),
        ("BMR Calories",                {"type": "numeric", "min": 100, "max": 5000,  "optional": True}),
        ("Avg Stress Level",            {"type": "numeric", "min": 0,   "max": 100,   "optional": True}),
        ("Floors Ascended",             {"type": "numeric", "min": 0,   "max": 200,   "optional": True}),
        ("Distance (mi)",               {"type": "numeric", "min": 0,   "max": 150,   "optional": True}),
        ("Duration (min)",              {"type": "numeric", "min": 0,   "max": 600,   "optional": True}),
        ("Avg Speed (mph)",             {"type": "numeric", "min": 0,   "max": 30,    "optional": True}),
    ],
    "Sleep": [
        ("Date",                        {"type": "date"}),
        ("Total Sleep (hrs)",           {"type": "numeric", "min": 0,   "max": 16,    "optional": True}),
        ("Deep Sleep (min)",            {"type": "numeric", "min": 0,   "max": 600,   "optional": True}),
        ("Light Sleep (min)",           {"type": "numeric", "min": 0,   "max": 600,   "optional": True}),
        ("REM (min)",                   {"type": "numeric", "min": 0,   "max": 600,   "optional": True}),
        ("Awake During Sleep (min)",    {"type": "numeric", "min": 0,   "max": 480,   "optional": True}),
        ("Sleep Score",                 {"type": "numeric", "min": 0,   "max": 100,   "optional": True}),
        ("Overnight HRV (ms)",          {"type": "numeric", "min": 10,  "max": 200,   "optional": True}),
    ],
    "Nutrition": [
        ("Date",                        {"type": "date"}),
        ("Total Calories Burned",       {"type": "numeric", "min": 100, "max": 10000, "optional": True}),
        ("Active Calories Burned",      {"type": "numeric", "min": 0,   "max": 8000,  "optional": True}),
        ("BMR Calories",                {"type": "numeric", "min": 100, "max": 5000,  "optional": True}),
    ],
    "Session Log": [
        ("Date",                        {"type": "date"}),
        ("Duration (min)",              {"type": "numeric", "min": 0,   "max": 600,   "optional": True}),
        ("Distance (km)",               {"type": "numeric", "min": 0,   "max": 150,   "optional": True}),
        ("Avg HR",                      {"type": "numeric", "min": 30,  "max": 220,   "optional": True}),
        ("Max HR",                      {"type": "numeric", "min": 30,  "max": 220,   "optional": True}),
    ],
}

import re as _re
_DATE_RE  = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE  = _re.compile(r"^\d{2}:\d{2}$")


def _check_cell(col_name, value, rules):
    """Return a list of issue strings for a single cell, or [] if clean."""
    issues = []
    is_blank = (value == "" or value is None)

    if is_blank:
        if not rules.get("optional"):
            issues.append(f"{col_name}: MISSING (required)")
        return issues

    vtype = rules.get("type", "text")

    if vtype == "date":
        if not _DATE_RE.match(str(value)):
            issues.append(f"{col_name}: bad date format '{value}'")

    elif vtype == "time":
        if not _TIME_RE.match(str(value)):
            issues.append(f"{col_name}: bad time format '{value}'")

    elif vtype == "numeric":
        try:
            num = float(str(value).replace(",", ""))
            mn = rules.get("min")
            mx = rules.get("max")
            if mn is not None and num < mn:
                issues.append(f"{col_name}: {num} below min {mn} — possible unit error")
            if mx is not None and num > mx:
                issues.append(f"{col_name}: {num} above max {mx} — possible unit error")
        except ValueError:
            issues.append(f"{col_name}: expected number, got '{value}'")

    return issues


def verify_import(wb, written_dates: set):
    """
    Read back every tab from Google Sheets and validate:
      1. Row count matches what was written
      2. No duplicate dates
      3. Dates are in correct YYYY-MM-DD format
      4. Numeric columns contain numbers in expected ranges
      5. No column misalignment (text in numeric columns)
      6. Cross-tab: every date in Sleep tab exists in Garmin tab

    Prints a PASS / FAIL report for each tab.
    """
    print("\n" + "=" * 60)
    print("DATA VALIDATION REPORT")
    print("=" * 60)

    all_pass = True
    garmin_dates = set()

    for tab_name, col_rules in TAB_VALIDATIONS.items():
        print(f"\n  Tab: {tab_name}")
        try:
            sheet = wb.worksheet(tab_name)
        except Exception:
            print(f"    SKIP — tab not found")
            continue

        all_rows = sheet.get_all_values()
        if not all_rows:
            print(f"    FAIL — tab is empty")
            all_pass = False
            continue

        headers = all_rows[0]
        data_rows = all_rows[1:]
        data_rows = [r for r in data_rows if any(c.strip() for c in r)]  # skip blanks

        # Build col index map from actual headers
        col_idx = {h.strip(): i for i, h in enumerate(headers)}

        row_issues = []
        seen_dates = set()
        seen_sess_keys = set()  # (date, activity_name) for Session Log
        duplicate_dates = []

        for row_num, row in enumerate(data_rows, start=2):
            date_val = row[1].strip() if len(row) > 1 else ""

            # Duplicate check:
            # Session Log allows multiple rows per date (one per activity),
            # so deduplicate by (date, activity_name) instead of date alone.
            if tab_name == "Session Log":
                act_name = row[6].strip() if len(row) > 6 else ""
                sess_key = (date_val, act_name)
                if sess_key in seen_sess_keys:
                    duplicate_dates.append(date_val)
                seen_sess_keys.add(sess_key)
            else:
                if date_val in seen_dates:
                    duplicate_dates.append(date_val)
            seen_dates.add(date_val)

            if tab_name == "Garmin":
                garmin_dates.add(date_val)

            # Validate each watched column
            for col_name, rules in col_rules:
                if col_name not in col_idx:
                    continue  # column doesn't exist in this tab (schema mismatch handled separately)
                ci = col_idx[col_name]
                cell_val = row[ci].strip() if ci < len(row) else ""
                cell_issues = _check_cell(col_name, cell_val, rules)
                for iss in cell_issues:
                    row_issues.append(f"    Row {row_num} ({date_val}): {iss}")

        # --- Summary for this tab ---
        total_rows = len(data_rows)
        issue_count = len(row_issues)

        # Row count vs written dates (only for Garmin tab, which has one row per date)
        if tab_name == "Garmin" and written_dates:
            missing_from_sheet = written_dates - seen_dates
            extra_in_sheet     = seen_dates - written_dates
        else:
            missing_from_sheet = set()
            extra_in_sheet     = set()

        status = "PASS" if issue_count == 0 and not duplicate_dates and not missing_from_sheet else "FAIL"
        if status == "FAIL":
            all_pass = False

        print(f"    Status      : {status}")
        print(f"    Rows found  : {total_rows}")

        if duplicate_dates:
            print(f"    Duplicates  : {len(duplicate_dates)} — {duplicate_dates[:5]}")

        if missing_from_sheet:
            print(f"    Missing     : {len(missing_from_sheet)} dates not written — {sorted(missing_from_sheet)[:5]}")

        if extra_in_sheet:
            print(f"    Extra rows  : {len(extra_in_sheet)} pre-existing rows (OK)")

        if row_issues:
            print(f"    Issues      : {issue_count}")
            for iss in row_issues[:10]:   # show first 10 only
                print(f"  {iss}")
            if issue_count > 10:
                print(f"    ... and {issue_count - 10} more issues")
        else:
            print(f"    Issues      : 0")

    # Cross-tab check: Sleep dates vs Garmin dates
    print(f"\n  Cross-tab check: Sleep vs Garmin")
    try:
        sleep_sheet  = wb.worksheet("Sleep")
        sleep_dates  = set(v.strip() for v in sleep_sheet.col_values(2)[1:] if v.strip())
        only_in_garmin = garmin_dates - sleep_dates
        only_in_sleep  = sleep_dates - garmin_dates
        if only_in_garmin:
            # Expected: many days have no sleep tracking (watch not worn, data not recorded)
            print(f"    INFO — {len(only_in_garmin)} dates have no sleep data (watch off / no tracking)")
        if only_in_sleep:
            # Unexpected: sleep data exists for dates not in the Garmin tab
            print(f"    FAIL — {len(only_in_sleep)} Sleep dates missing from Garmin tab")
            all_pass = False
        if not only_in_sleep:
            print(f"    PASS — all Sleep dates exist in Garmin tab")
    except Exception as e:
        print(f"    SKIP — {e}")

    print("\n" + "=" * 60)
    if all_pass:
        print("OVERALL: PASS — all tabs validated clean")
    else:
        print("OVERALL: FAIL — review issues above before relying on this data")
    print("=" * 60 + "\n")

    return all_pass


def _fill_garmin_tab(wb, sleep_data, uds_data, hrv_data, hrv_7day, activities):
    """Fill blank Garmin tab cells where the export has data."""
    import gspread as _gspread
    from utils import get_sheet

    sheet = get_sheet(wb)
    all_rows = sheet.get_all_values()
    if len(all_rows) < 2:
        print("  Garmin tab: empty, skipping.")
        return

    col_of = {h.strip(): i for i, h in enumerate(all_rows[0])}
    GARMIN_KEY = {
        "HRV (overnight avg)": "hrv", "HRV 7-day avg": "hrv_7day",
        "Resting HR": "resting_hr", "Sleep Duration (hrs)": "sleep_duration",
        "Sleep Score": "sleep_score", "Body Battery": "body_battery",
        "Steps": "steps", "Total Calories Burned": "total_calories",
        "Active Calories Burned": "active_calories", "BMR Calories": "bmr_calories",
        "Avg Stress Level": "avg_stress", "Floors Ascended": "floors_ascended",
        "Moderate Intensity Min": "moderate_min", "Vigorous Intensity Min": "vigorous_min",
        "Body Battery at Wake": "bb_at_wake", "Body Battery High": "bb_high",
        "Body Battery Low": "bb_low", "Activity Name": "activity_name",
        "Activity Type": "activity_type", "Start Time": "activity_start",
        "Distance (mi)": "activity_distance", "Duration (min)": "activity_duration",
        "Avg HR": "activity_avg_hr", "Max HR": "activity_max_hr",
        "Calories": "activity_calories", "Elevation Gain (m)": "activity_elevation",
        "Avg Speed (mph)": "activity_avg_speed",
        "Aerobic Training Effect": "aerobic_te", "Anaerobic Training Effect": "anaerobic_te",
        "Zone 1 - Warm Up (min)": "zone_1", "Zone 2 - Easy (min)": "zone_2",
        "Zone 3 - Aerobic (min)": "zone_3", "Zone 4 - Threshold (min)": "zone_4",
        "Zone 5 - Max (min)": "zone_5",
    }

    garmin_cells = []
    for ri, row in enumerate(all_rows[1:], start=2):
        date_str = row[1].strip() if len(row) > 1 else ""
        if not date_str:
            continue
        data = merge(date_str, sleep_data, uds_data, hrv_data, hrv_7day, activities)
        for header, key in GARMIN_KEY.items():
            if header not in col_of:
                continue
            ci_0 = col_of[header]
            current = row[ci_0].strip() if ci_0 < len(row) else ""
            new_val = data.get(key, "")
            if current == "" and new_val != "" and new_val is not None:
                garmin_cells.append(_gspread.Cell(ri, ci_0 + 1, new_val))

    if garmin_cells:
        print(f"  Garmin tab: filling {len(garmin_cells)} missing cells...")
        sheet.update_cells(garmin_cells, value_input_option="USER_ENTERED")
        print("  Garmin tab: done.")
    else:
        print("  Garmin tab: no missing cells found.")


def _fill_sleep_tab(wb, sleep_data, uds_data, hrv_data, hrv_7day, activities):
    """Fill blank Sleep tab cells; overwrite Bedtime/Wake Time for timezone correction."""
    import gspread as _gspread

    FILL_KEYS = {"Body Battery Gained": "sleep_body_battery_gained"}
    OVERWRITE_KEYS = {
        "Bedtime":   "sleep_bedtime",
        "Wake Time": "sleep_wake_time",
    }
    try:
        sleep_sheet = wb.worksheet("Sleep")
        sleep_rows  = sleep_sheet.get_all_values()
        sleep_col   = {h.strip(): i for i, h in enumerate(sleep_rows[0])}
        sleep_cells = []
        for ri, row in enumerate(sleep_rows[1:], start=2):
            date_str = row[1].strip() if len(row) > 1 else ""
            if not date_str:
                continue
            data = merge(date_str, sleep_data, uds_data, hrv_data, hrv_7day, activities)
            for header, key in FILL_KEYS.items():
                if header not in sleep_col:
                    continue
                ci_0 = sleep_col[header]
                current = row[ci_0].strip() if ci_0 < len(row) else ""
                new_val = data.get(key, "")
                if current == "" and new_val != "" and new_val is not None:
                    sleep_cells.append(_gspread.Cell(ri, ci_0 + 1, new_val))
            for header, key in OVERWRITE_KEYS.items():
                if header not in sleep_col:
                    continue
                ci_0 = sleep_col[header]
                new_val = data.get(key, "")
                if new_val:
                    sleep_cells.append(_gspread.Cell(ri, ci_0 + 1, new_val))
        if sleep_cells:
            print(f"  Sleep tab: updating {len(sleep_cells)} cells (bedtime/wake timezone fix + bb gained)...")
            sleep_sheet.update_cells(sleep_cells, value_input_option="RAW")
            print("  Sleep tab: done.")
        else:
            print("  Sleep tab: no cells to update.")
    except Exception as e:
        print(f"  Sleep tab: skipped — {e}")


def _fill_session_zones(wb, sleep_data, uds_data, hrv_data, hrv_7day, activities):
    """Fill blank HR zone cells in Session Log."""
    import gspread as _gspread

    SESS_KEY = {
        "Zone 1 (min)": "zone_1", "Zone 2 (min)": "zone_2",
        "Zone 3 (min)": "zone_3", "Zone 4 (min)": "zone_4",
        "Zone 5 (min)": "zone_5",
    }
    try:
        sess_sheet = wb.worksheet("Session Log")
        sess_rows  = sess_sheet.get_all_values()
        sess_col   = {h.strip(): i for i, h in enumerate(sess_rows[0])}
        sess_cells = []
        for ri, row in enumerate(sess_rows[1:], start=2):
            date_str = row[1].strip() if len(row) > 1 else ""
            if not date_str:
                continue
            data = merge(date_str, sleep_data, uds_data, hrv_data, hrv_7day, activities)
            for header, key in SESS_KEY.items():
                if header not in sess_col:
                    continue
                ci_0 = sess_col[header]
                current = row[ci_0].strip() if ci_0 < len(row) else ""
                new_val = data.get(key, "")
                if current == "" and new_val != "" and new_val is not None:
                    sess_cells.append(_gspread.Cell(ri, ci_0 + 1, new_val))
        if sess_cells:
            print(f"  Session Log: filling {len(sess_cells)} missing zone cells...")
            sess_sheet.update_cells(sess_cells, value_input_option="USER_ENTERED")
            print("  Session Log: done.")
        else:
            print("  Session Log: no missing zone cells found.")
    except Exception as e:
        print(f"  Session Log: skipped — {e}")


def _fill_archive_tab(wb, sleep_data, uds_data, hrv_data, hrv_7day, activities):
    """Fill blank Archive cells; overwrite time fields as plain text (RAW)."""
    import gspread as _gspread

    TIME_OVERWRITE_KEYS = {"sleep_bedtime", "sleep_wake_time"}
    try:
        from schema import ARCHIVE_KEYS
        from writers import get_or_create_archive_sheet
        archive_sheet = get_or_create_archive_sheet(wb)
        arch_rows = archive_sheet.get_all_values()
        arch_col  = {h.strip(): i for i, h in enumerate(arch_rows[0])}
        arch_raw_cells  = []
        arch_ue_cells   = []

        for ri, row in enumerate(arch_rows[1:], start=2):
            date_str = row[1].strip() if len(row) > 1 else ""
            if not date_str:
                continue
            if not date_str[0:4].isdigit() or len(date_str) < 10 or date_str[4] != '-':
                continue
            data = merge(date_str, sleep_data, uds_data, hrv_data, hrv_7day, activities)
            for key in ARCHIVE_KEYS:
                if key not in arch_col:
                    continue
                ci_0 = arch_col[key]
                current = row[ci_0].strip() if ci_0 < len(row) else ""
                new_val = data.get(key, "")
                if new_val == "" or new_val is None:
                    continue
                if key in TIME_OVERWRITE_KEYS:
                    arch_raw_cells.append(_gspread.Cell(ri, ci_0 + 1, str(new_val)))
                elif current == "":
                    arch_ue_cells.append(_gspread.Cell(ri, ci_0 + 1, new_val))

        if arch_raw_cells:
            print(f"  Archive tab: rewriting {len(arch_raw_cells)} time cells as plain text...")
            archive_sheet.update_cells(arch_raw_cells, value_input_option="RAW")
            print("  Archive tab: time fix done.")
        if arch_ue_cells:
            print(f"  Archive tab: filling {len(arch_ue_cells)} blank cells...")
            archive_sheet.update_cells(arch_ue_cells, value_input_option="USER_ENTERED")
            print("  Archive tab: fill done.")
        if not arch_raw_cells and not arch_ue_cells:
            print("  Archive tab: no cells to update.")
    except Exception as e:
        print(f"  Archive tab: skipped — {e}")


def fill_missing_data(wb, base):
    """
    Compare export data against what's currently in the sheet and fill any blank
    cells where the export has a value. Also fills previously-missing zone data
    and sleep_body_battery_gained (now parsed from export). Updates Archive tab too.

    Strategy: ONE read per tab, ONE batch update per tab — no per-row API calls.
    """
    print("\nLoading export files for missing-data fill...")
    sleep_data = load_sleep(base)
    uds_data   = load_uds(base)
    hrv_data   = load_hrv(base)
    hrv_7day   = build_hrv_7day(hrv_data)
    activities = load_activities(base)

    sources = (sleep_data, uds_data, hrv_data, hrv_7day, activities)
    _fill_garmin_tab(wb, *sources)
    _fill_sleep_tab(wb, *sources)
    _fill_session_zones(wb, *sources)
    _fill_archive_tab(wb, *sources)

    print("\nMissing-data fill complete.")


def _serial_to_datetime_str(serial):
    """Convert a Google Sheets datetime serial (float) to 'YYYY-MM-DD HH:MM'."""
    from datetime import datetime as _dt, timedelta as _td
    base = _dt(1899, 12, 30)
    days = int(serial)
    frac = serial - days
    dt = base + _td(days=days) + _td(seconds=round(frac * 86400))
    return dt.strftime("%Y-%m-%d %H:%M")


def _fix_garmin_types(wb):
    """Fix Garmin tab: datetime serials in Start Time, string-numbers to actual numbers."""
    import gspread as _gspread
    from utils import get_sheet

    sheet = get_sheet(wb)
    hdr   = sheet.row_values(1)
    raw_rows = sheet.get_values(value_render_option="UNFORMATTED_VALUE")
    garmin_cells = []
    TEXT_GARMIN = {"Date", "Stress Qualifier", "Activity Name", "Activity Type"}

    for ri, row in enumerate(raw_rows[1:], start=2):
        for ci, header in enumerate(hdr):
            if ci >= len(row): continue
            val = row[ci]
            if val == "" or val is None: continue

            if header == "Start Time" and isinstance(val, (int, float)):
                garmin_cells.append(_gspread.Cell(ri, ci+1, _serial_to_datetime_str(val)))
            elif header not in TEXT_GARMIN and header != "Start Time":
                if isinstance(val, str) and val.strip():
                    try:
                        num = float(val.strip())
                        garmin_cells.append(_gspread.Cell(ri, ci+1, int(num) if num == int(num) else num))
                    except ValueError:
                        pass

    if garmin_cells:
        raw_g = [c for c in garmin_cells if hdr[c.col-1] == "Start Time"]
        num_g = [c for c in garmin_cells if hdr[c.col-1] != "Start Time"]
        if raw_g:
            print(f"  Garmin: fixing {len(raw_g)} Start Time cells (datetime->text)...")
            sheet.update_cells(raw_g, value_input_option="RAW")
        if num_g:
            print(f"  Garmin: fixing {len(num_g)} numeric-as-string cells...")
            sheet.update_cells(num_g, value_input_option="USER_ENTERED")
    else:
        print("  Garmin: no type issues found.")


def _fix_session_types(wb):
    """Fix Session Log: column misalignment and string-number HR values."""
    import gspread as _gspread

    try:
        sess = wb.worksheet("Session Log")
        shdr = sess.row_values(1)
        scol = {h.strip(): i for i, h in enumerate(shdr)}

        zone_ranges_ci = scol.get("Zone Ranges")
        source_ci      = scol.get("Source")
        elev_ci        = scol.get("Elevation (m)")
        avg_hr_ci      = scol.get("Avg HR")
        max_hr_ci      = scol.get("Max HR")

        sraw = sess.get_values(value_render_option="UNFORMATTED_VALUE")
        sess_raw_cells = []
        sess_ue_cells  = []

        for ri, row in enumerate(sraw[1:], start=2):
            def _get(ci):
                return row[ci] if ci is not None and ci < len(row) else ""

            src_val = _get(source_ci)
            if source_ci is not None and isinstance(src_val, (int, float)):
                elev_val = src_val
                if elev_ci is not None:
                    sess_ue_cells.append(_gspread.Cell(ri, elev_ci+1, elev_val))
                sess_raw_cells.append(_gspread.Cell(ri, source_ci+1, "Garmin Export"))
                if zone_ranges_ci is not None and _get(zone_ranges_ci) == "Garmin Export":
                    sess_raw_cells.append(_gspread.Cell(ri, zone_ranges_ci+1, ""))

            for col_ci in [avg_hr_ci, max_hr_ci]:
                if col_ci is None: continue
                v = _get(col_ci)
                if isinstance(v, str) and v.strip():
                    try:
                        num = float(v.strip())
                        sess_ue_cells.append(_gspread.Cell(ri, col_ci+1,
                                             int(num) if num == int(num) else num))
                    except ValueError:
                        pass

        if sess_raw_cells:
            print(f"  Session Log: fixing {len(sess_raw_cells)} text cells...")
            sess.update_cells(sess_raw_cells, value_input_option="RAW")
        if sess_ue_cells:
            print(f"  Session Log: fixing {len(sess_ue_cells)} numeric cells...")
            sess.update_cells(sess_ue_cells, value_input_option="USER_ENTERED")
        if not sess_raw_cells and not sess_ue_cells:
            print("  Session Log: no type issues found.")
    except Exception as e:
        print(f"  Session Log: skipped — {e}")


def _fix_archive_types(wb):
    """Fix Archive tab: datetime serials in activity_start."""
    import gspread as _gspread

    try:
        from writers import get_or_create_archive_sheet
        arch = get_or_create_archive_sheet(wb)
        ahdr = arch.row_values(1)
        acol = {h.strip(): i for i, h in enumerate(ahdr)}
        araw = arch.get_values(value_render_option="UNFORMATTED_VALUE")
        start_ci = acol.get("activity_start")
        arch_cells = []
        if start_ci is not None:
            for ri, row in enumerate(araw[1:], start=2):
                if start_ci >= len(row): continue
                val = row[start_ci]
                if isinstance(val, (int, float)) and val:
                    arch_cells.append(_gspread.Cell(ri, start_ci+1,
                                                    _serial_to_datetime_str(val)))
        if arch_cells:
            print(f"  Archive: fixing {len(arch_cells)} activity_start cells (datetime->text)...")
            arch.update_cells(arch_cells, value_input_option="RAW")
        else:
            print("  Archive: no type issues found.")
    except Exception as e:
        print(f"  Archive: skipped — {e}")


def fix_data_types(wb):
    """Correct stored data types across all tabs."""
    print("\nFixing data types across all tabs...")
    _fix_garmin_types(wb)
    _fix_session_types(wb)
    _fix_archive_types(wb)
    print("Type fix complete.")


def _freeze_request(sheet_id):
    """Freeze the first row (headers) on a sheet."""
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    }


def _col_format_request(sheet_id, col_0, num_rows, fmt_pattern, is_number):
    """Build a repeatCell request for one column (col_0 is 0-based)."""
    if fmt_pattern == "HH:MM":
        sheet_type, align = "TIME", "LEFT"
    elif fmt_pattern == "yyyy-mm-dd":
        sheet_type, align = "DATE", "LEFT"
    elif is_number:
        sheet_type, align = "NUMBER", "RIGHT"
    else:
        sheet_type, align = "TEXT", "LEFT"

    cell_format = {"horizontalAlignment": align}
    if fmt_pattern:
        cell_format["numberFormat"] = {"type": sheet_type, "pattern": fmt_pattern}
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": num_rows + 1,
                "startColumnIndex": col_0,
                "endColumnIndex": col_0 + 1,
            },
            "cell": {"userEnteredFormat": cell_format},
            "fields": "userEnteredFormat(horizontalAlignment,numberFormat)",
        }
    }


def _header_format_request(sheet_id, num_cols):
    """Bold, centered, wrapped header row."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": num_cols,
            },
            "cell": {
                "userEnteredFormat": {
                    "horizontalAlignment": "CENTER",
                    "textFormat": {"bold": True},
                    "wrapStrategy": "WRAP",
                }
            },
            "fields": "userEnteredFormat(horizontalAlignment,textFormat,wrapStrategy)",
        }
    }


# Column format specs: (header_name, format_pattern, is_number)
# is_number=True -> right-align + number format
# is_number=False -> left-align, no number format
_GARMIN_FORMATS = [
        ("Date",                        "yyyy-mm-dd",  False),
        ("HRV (overnight avg)",         "0",           True),
        ("HRV 7-day avg",               "0.0",         True),
        ("Resting HR",                  "0",           True),
        ("Sleep Duration (hrs)",        "0.00",        True),
        ("Sleep Score",                 "0",           True),
        ("Body Battery",                "0",           True),
        ("Steps",                       "#,##0",       True),
        ("Total Calories Burned",       "#,##0",       True),
        ("Active Calories Burned",      "#,##0",       True),
        ("BMR Calories",                "#,##0",       True),
        ("Avg Stress Level",            "0",           True),
        ("Stress Qualifier",            "",            False),
        ("Floors Ascended",             "0",           True),
        ("Moderate Intensity Min",      "0",           True),
        ("Vigorous Intensity Min",      "0",           True),
        ("Body Battery at Wake",        "0",           True),
        ("Body Battery High",           "0",           True),
        ("Body Battery Low",            "0",           True),
        ("Activity Name",               "",            False),
        ("Activity Type",               "",            False),
        ("Start Time",                  "yyyy-mm-dd HH:MM", False),
        ("Distance (mi)",               "0.00",        True),
        ("Duration (min)",              "0.0",         True),
        ("Avg HR",                      "0",           True),
        ("Max HR",                      "0",           True),
        ("Calories",                    "#,##0",       True),
        ("Elevation Gain (m)",          "0.0",         True),
        ("Avg Speed (mph)",             "0.00",        True),
        ("Aerobic Training Effect",     "0.0",         True),
        ("Anaerobic Training Effect",   "0.0",         True),
        ("Zone 1 - Warm Up (min)",      "0.0",         True),
        ("Zone 2 - Easy (min)",         "0.0",         True),
        ("Zone 3 - Aerobic (min)",      "0.0",         True),
        ("Zone 4 - Threshold (min)",    "0.0",         True),
        ("Zone 5 - Max (min)",          "0.0",         True),
    ]

_SLEEP_FORMATS = [
    ("Date",                        "yyyy-mm-dd",  False),
    ("Notes",                       "",            False),
    ("Bedtime",                     "HH:MM",       True),
    ("Wake Time",                   "HH:MM",       True),
    ("Time in Bed (hrs)",           "0.00",        True),
    ("Total Sleep (hrs)",           "0.00",        True),
    ("Deep Sleep (min)",            "0.0",         True),
    ("Light Sleep (min)",           "0.0",         True),
    ("REM (min)",                   "0.0",         True),
    ("Awake During Sleep (min)",    "0.0",         True),
    ("Deep %",                      "0.0",         True),
    ("REM %",                       "0.0",         True),
    ("Sleep Cycles",                "0",           True),
    ("Awakenings",                  "0",           True),
    ("Avg HR",                      "0",           True),
    ("Avg Respiration",             "0.0",         True),
    ("Overnight HRV (ms)",          "0",           True),
    ("Body Battery Gained",         "0",           True),
    ("Sleep Score",                 "0",           True),
    ("Sleep Descriptor",            "",            False),
]

_NUTR_FORMATS = [
    ("Date",                        "yyyy-mm-dd",  False),
    ("Total Calories Burned",       "#,##0",       True),
    ("Active Calories Burned",      "#,##0",       True),
    ("BMR Calories",                "#,##0",       True),
    ("Breakfast",                   "",            False),
    ("Lunch",                       "",            False),
    ("Dinner",                      "",            False),
    ("Snacks",                      "",            False),
    ("Total Calories Consumed",     "#,##0",       True),
    ("Protein (g)",                 "0",           True),
    ("Carbs (g)",                   "0",           True),
    ("Fats (g)",                    "0",           True),
    ("Water (L)",                   "0.0",         True),
    ("Calorie Balance",             "#,##0",       True),
    ("Notes",                       "",            False),
]

_SESS_FORMATS = [
    ("Date",                          "yyyy-mm-dd",  False),
    ("Session Type",                  "",            False),
    ("Perceived Effort",              "0",           True),
    ("Post-Workout Energy (1-10)",   "0",           True),
    ("Notes",                         "",            False),
    ("Activity Name",                 "",            False),
    ("Duration (min)",                "0.0",         True),
    ("Distance (mi)",                 "0.00",        True),
    ("Distance (km)",                 "0.00",        True),  # legacy header
    ("Avg HR",                        "0",           True),
    ("Max HR",                        "0",           True),
    ("Calories",                      "#,##0",       True),
    ("Aerobic TE (0-5)",              "0.0",         True),
    ("Anaerobic TE (0-5)",            "0.0",         True),
    ("Zone 1 (min)",                  "0.0",         True),
    ("Zone 2 (min)",                  "0.0",         True),
    ("Zone 3 (min)",                  "0.0",         True),
    ("Zone 4 (min)",                  "0.0",         True),
    ("Zone 5 (min)",                  "0.0",         True),
    ("Zone Ranges",                   "",            False),
    ("Source",                        "",            False),
    ("Elevation (m)",                 "0.0",         True),
]

_ARCHIVE_COL_FORMATS = {
    "resting_hr": "0", "body_battery": "0", "steps": "#,##0",
    "total_calories": "#,##0", "active_calories": "#,##0", "bmr_calories": "#,##0",
    "avg_stress": "0", "floors_ascended": "0",
    "moderate_min": "0", "vigorous_min": "0",
    "bb_at_wake": "0", "bb_high": "0", "bb_low": "0",
    "sleep_score": "0", "sleep_awakenings": "0",
    "sleep_deep_min": "0.0", "sleep_light_min": "0.0",
    "sleep_rem_min": "0.0", "sleep_awake_min": "0.0",
    "sleep_body_battery_gained": "0",
    "activity_avg_hr": "0", "activity_max_hr": "0",
    "activity_calories": "#,##0",
    "hrv": "0", "hrv_7day": "0.0",
    "sleep_duration": "0.00", "sleep_time_in_bed": "0.00",
    "sleep_deep_pct": "0.0", "sleep_rem_pct": "0.0",
    "sleep_avg_respiration": "0.0",
    "activity_distance": "0.00", "activity_duration": "0.0",
    "activity_elevation": "0.0", "activity_avg_speed": "0.00",
    "aerobic_te": "0.0", "anaerobic_te": "0.0",
    "zone_1": "0.0", "zone_2": "0.0", "zone_3": "0.0",
    "zone_4": "0.0", "zone_5": "0.0",
}


def _apply_tab_format(wb, tab_name, col_formats, ws=None):
    """Apply freeze, header formatting, and column formats to a single tab."""
    try:
        s = ws or wb.worksheet(tab_name)
    except Exception:
        print(f"  {tab_name}: tab not found, skipping.")
        return
    nrows = max(len(s.col_values(2)), 1)
    ncols = len(col_formats)
    hdr   = s.row_values(1)
    col_map = {h.strip(): i for i, h in enumerate(hdr)}
    requests = [_freeze_request(s.id), _header_format_request(s.id, max(ncols, len(hdr)))]
    for col_name, fmt_pat, is_num in col_formats:
        ci = col_map.get(col_name)
        if ci is None:
            continue
        requests.append(_col_format_request(s.id, ci, nrows, fmt_pat, is_num))
    wb.batch_update({"requests": requests})
    print(f"  {tab_name}: formatting applied ({len(requests)-2} columns).")


def reformat_sheets(wb):
    """Apply uniform formatting to all tabs."""
    from utils import get_sheet
    from schema import ARCHIVE_KEYS
    from writers import get_or_create_archive_sheet

    print("\nApplying uniform formatting to all tabs...")
    _apply_tab_format(wb, "Garmin",      _GARMIN_FORMATS, ws=get_sheet(wb))
    _apply_tab_format(wb, "Sleep",       _SLEEP_FORMATS)
    _apply_tab_format(wb, "Nutrition",   _NUTR_FORMATS)
    _apply_tab_format(wb, "Session Log", _SESS_FORMATS)

    # Archive tab — build format list from ARCHIVE_KEYS
    try:
        arch = get_or_create_archive_sheet(wb)
        nrows = max(len(arch.col_values(2)), 1)
        hdr   = arch.row_values(1)
        col_map = {h.strip(): i for i, h in enumerate(hdr)}
        requests = [_freeze_request(arch.id), _header_format_request(arch.id, len(hdr))]
        requests.append(_col_format_request(arch.id, 0, nrows, "yyyy-mm-dd", False))
        for key in ARCHIVE_KEYS:
            ci = col_map.get(key)
            if ci is None:
                continue
            fmt = _ARCHIVE_COL_FORMATS.get(key, "")
            is_num = bool(fmt)
            requests.append(_col_format_request(arch.id, ci, nrows, fmt, is_num))
        wb.batch_update({"requests": requests})
        print(f"  Raw Data Archive: formatting applied.")
    except Exception as e:
        print(f"  Raw Data Archive: skipped — {e}")

    print("Formatting complete.")


def fix_existing_data(wb):
    """
    Patch already-written sheet data without re-importing.
    Uses single batch reads and single batch writes — minimal API calls.

    1. Garmin tab: blank Avg Stress Level cells that are -1 or -2 (Garmin sentinels)
       -> reads entire stress column once, rewrites entire column in ONE update call
    2. Session Log: blank Avg HR / Max HR cells that are 0 (Garmin sentinel)
       -> reads both columns once, rewrites them in ONE update call each
    3. Session Log: remove duplicate rows (same date + activity name)
    """
    from utils import get_sheet
    from schema import HEADERS
    import string

    def col_letter(n):
        """Convert 1-based column number to letter(s): 1->A, 26->Z, 27->AA."""
        result = ""
        while n:
            n, rem = divmod(n - 1, 26)
            result = string.ascii_uppercase[rem] + result
        return result

    print("\nFixing existing sheet data...")

    # --- Garmin tab: fix stress sentinels via single column rewrite ---
    sheet = get_sheet(wb)
    stress_col_1 = HEADERS.index("Avg Stress Level") + 1  # 1-based
    stress_letter = col_letter(stress_col_1)

    print(f"  Garmin tab: reading stress column ({stress_letter})...")
    # Read full column including header to know total height
    all_rows = sheet.get_all_values()
    nrows = len(all_rows)

    fixed_stress = []  # list of [value] for each data row (row 2 onward)
    changed = 0
    for row in all_rows[1:]:  # skip header row
        val = row[stress_col_1 - 1].strip() if len(row) >= stress_col_1 else ""
        try:
            fval = float(val)
            if fval < 0:
                fixed_stress.append([""])
                changed += 1
            else:
                fixed_stress.append([val])
        except (ValueError, TypeError):
            fixed_stress.append([val])

    if changed:
        col_range = f"{stress_letter}2:{stress_letter}{nrows}"
        print(f"  Garmin tab: rewriting column {stress_letter} ({nrows-1} cells, {changed} sentinels blanked)...")
        sheet.update(range_name=col_range, values=fixed_stress)
        print(f"  Garmin tab: stress fix complete.")
    else:
        print(f"  Garmin tab: no stress sentinel values found.")

    # --- Session Log: fix HR=0 and remove duplicates ---
    try:
        sess_sheet = wb.worksheet("Session Log")
    except Exception:
        print("  Session Log: tab not found, skipping.")
        return

    print("  Session Log: reading all rows...")
    all_sess = sess_sheet.get_all_values()
    if len(all_sess) <= 1:
        print("  Session Log: empty, nothing to fix.")
        return

    # Session Log column layout (1-based):
    # A=Day(1), B=Date(2), C=Type(3), D=Effort(4), E=Fatigue(5), F=Notes(6),
    # G=Activity Name(7), H=Duration(8), I=Distance(9),
    # J=Avg HR(10), K=Max HR(11), ...
    AVG_HR_COL_1 = 10  # 1-based -> column J
    MAX_HR_COL_1 = 11  # 1-based -> column K
    ACTNAME_IDX  = 6   # 0-based for list access (column G)
    nsess = len(all_sess)

    avg_hr_vals = []
    max_hr_vals = []
    avg_changed = 0
    max_changed = 0

    for row in all_sess[1:]:
        # Avg HR
        v = row[AVG_HR_COL_1 - 1].strip() if len(row) >= AVG_HR_COL_1 else ""
        try:
            if float(v) == 0:
                avg_hr_vals.append([""])
                avg_changed += 1
            else:
                avg_hr_vals.append([v])
        except (ValueError, TypeError):
            avg_hr_vals.append([v])

        # Max HR
        v = row[MAX_HR_COL_1 - 1].strip() if len(row) >= MAX_HR_COL_1 else ""
        try:
            if float(v) == 0:
                max_hr_vals.append([""])
                max_changed += 1
            else:
                max_hr_vals.append([v])
        except (ValueError, TypeError):
            max_hr_vals.append([v])

    avg_letter = col_letter(AVG_HR_COL_1)
    max_letter = col_letter(MAX_HR_COL_1)

    if avg_changed:
        r = f"{avg_letter}2:{avg_letter}{nsess}"
        print(f"  Session Log: rewriting Avg HR column ({avg_changed} zeros blanked)...")
        sess_sheet.update(range_name=r, values=avg_hr_vals)
    else:
        print(f"  Session Log: no Avg HR=0 sentinel values found.")

    if max_changed:
        r = f"{max_letter}2:{max_letter}{nsess}"
        print(f"  Session Log: rewriting Max HR column ({max_changed} zeros blanked)...")
        sess_sheet.update(range_name=r, values=max_hr_vals)
    else:
        print(f"  Session Log: no Max HR=0 sentinel values found.")

    # Remove duplicates (keep first occurrence of date+activity_name)
    # Re-read after HR fixes
    all_sess = sess_sheet.get_all_values()
    seen_sess = set()
    rows_to_delete = []
    for ri, row in enumerate(all_sess[1:], start=2):
        key = (row[1].strip() if len(row) > 1 else "", row[ACTNAME_IDX].strip() if len(row) > ACTNAME_IDX else "")
        if key in seen_sess:
            rows_to_delete.append(ri)
        else:
            seen_sess.add(key)

    if rows_to_delete:
        print(f"  Session Log: removing {len(rows_to_delete)} duplicate row(s)...")
        for ri in reversed(rows_to_delete):
            sess_sheet.delete_rows(ri)
        print(f"  Session Log: deduplication complete.")
    else:
        print(f"  Session Log: no duplicates found.")

    print("\nFix complete. Re-running validation...")


def parse_args():
    args = {
        "folder":       DEFAULT_EXPORT_FOLDER,
        "dry_run":      False,
        "start":        None,
        "end":          None,
        "fix_data":     False,
        "fill_missing": False,
        "reformat":     False,
        "fix_types":    False,
    }
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--folder" and i + 1 < len(sys.argv):
            args["folder"] = Path(sys.argv[i + 1]); i += 2
        elif sys.argv[i] == "--dry-run":
            args["dry_run"] = True; i += 1
        elif sys.argv[i] == "--fix-data":
            args["fix_data"] = True; i += 1
        elif sys.argv[i] == "--fill-missing":
            args["fill_missing"] = True; i += 1
        elif sys.argv[i] == "--reformat":
            args["reformat"] = True; i += 1
        elif sys.argv[i] == "--fix-types":
            args["fix_types"] = True; i += 1
        elif sys.argv[i] == "--start" and i + 1 < len(sys.argv):
            args["start"] = sys.argv[i + 1]; i += 2
        elif sys.argv[i] == "--end" and i + 1 < len(sys.argv):
            args["end"] = sys.argv[i + 1]; i += 2
        else:
            i += 1
    return args


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _load_export_data(base):
    """Load all export sources and return (sleep, uds, hrv, hrv_7day, activities)."""
    print("Loading export files...")
    sleep      = load_sleep(base)
    uds        = load_uds(base)
    hrv        = load_hrv(base)
    hrv_7day   = build_hrv_7day(hrv)
    activities = load_activities(base)
    return sleep, uds, hrv, hrv_7day, activities


def _read_existing_dates(wb):
    """Read existing dates from every tab. Returns dict of sheet objects and date sets."""
    from utils import get_sheet
    from writers import setup_headers
    sheet         = get_sheet(wb)
    setup_headers(sheet)
    archive_sheet = get_or_create_archive_sheet(wb)

    print("Reading existing sheet state (one read per tab)...")
    existing = {
        "garmin":  set(v.strip() for v in sheet.col_values(2)[1:]         if v.strip()),
        "archive": set(v.strip() for v in archive_sheet.col_values(2)[1:] if v.strip()),
    }
    sheets = {"garmin": sheet, "archive": archive_sheet}

    try:
        sleep_sheet = wb.worksheet("Sleep")
        existing["sleep"] = set(v.strip() for v in sleep_sheet.col_values(2)[1:] if v.strip())
    except Exception:
        sleep_sheet = wb.add_worksheet(title="Sleep", rows=2000, cols=len(SLEEP_HEADERS))
        sleep_sheet.update(range_name="A1", values=[SLEEP_HEADERS])
        existing["sleep"] = set()
    sheets["sleep"] = sleep_sheet

    try:
        nutr_sheet = wb.worksheet("Nutrition")
        existing["nutr"] = set(v.strip() for v in nutr_sheet.col_values(2)[1:] if v.strip())
    except Exception:
        nutr_sheet = wb.add_worksheet(title="Nutrition", rows=2000, cols=len(NUTRITION_HEADERS))
        nutr_sheet.update(range_name="A1", values=[NUTRITION_HEADERS])
        existing["nutr"] = set()
    sheets["nutr"] = nutr_sheet

    try:
        sess_sheet = wb.worksheet("Session Log")
        existing["sess"] = set(v.strip() for v in sess_sheet.col_values(2)[1:] if v.strip())
    except Exception:
        sess_sheet = None
        existing["sess"] = set()
    sheets["sess"] = sess_sheet

    print(f"  Garmin tab   : {len(existing['garmin'])} existing rows")
    print(f"  Archive tab  : {len(existing['archive'])} existing rows")
    print(f"  Sleep tab    : {len(existing['sleep'])} existing rows")
    print(f"  Nutrition tab: {len(existing['nutr'])} existing rows")

    return sheets, existing


def _build_session_type(activity_type):
    """Map Garmin activity type string to session type label."""
    act_type = (activity_type or "").lower()
    if any(x in act_type for x in ["running", "run", "trail"]):
        return "Run"
    if any(x in act_type for x in ["cycling", "bike", "road_biking"]):
        return "Cycle"
    if any(x in act_type for x in ["swimming", "swim"]):
        return "Swim"
    if any(x in act_type for x in ["strength", "weight", "gym"]):
        return "Strength"
    return "Other"


def _build_sleep_row(date_str, data):
    """Build a Sleep tab row from merged data dict."""
    from sleep_analysis import generate_sleep_analysis
    ind_score, analysis, descriptor = generate_sleep_analysis(data)
    return [
        date_to_day(date_str),                     # A  Day
        date_str,                                  # B  Date
        data.get("sleep_score", ""),                # C  Garmin Sleep Score
        ind_score if ind_score is not None else "",  # D  Sleep Analysis Score
        data.get("sleep_duration", ""),             # E  Total Sleep (hrs)
        analysis,                                  # F  Sleep Analysis (auto)
        "",                                        # G  Notes (manual)
        data.get("sleep_bedtime", ""),              # H  Bedtime
        data.get("sleep_wake_time", ""),            # I  Wake Time
        "",                                        # J  Bedtime Variability (7d) — computed post-write
        "",                                        # K  Wake Variability (7d) — computed post-write
        data.get("sleep_time_in_bed", ""),          # L  Time in Bed (hrs)
        data.get("sleep_deep_min", ""),             # M  Deep Sleep (min)
        data.get("sleep_light_min", ""),            # N  Light Sleep (min)
        data.get("sleep_rem_min", ""),              # O  REM (min)
        data.get("sleep_awake_min", ""),            # P  Awake During Sleep (min)
        data.get("sleep_deep_pct", ""),             # Q  Deep %
        data.get("sleep_rem_pct", ""),              # R  REM %
        data.get("sleep_cycles", ""),               # S  Sleep Cycles
        data.get("sleep_awakenings", ""),           # T  Awakenings
        data.get("sleep_avg_hr", ""),               # U  Avg HR
        data.get("sleep_avg_respiration", ""),      # V  Avg Respiration
        data.get("hrv", ""),                        # W  Overnight HRV (ms)
        data.get("sleep_body_battery_gained", ""),  # X  Body Battery Gained
        descriptor or "",                           # Y  Sleep Descriptor
    ]


def _build_session_row(date_str, data):
    """Build a Session Log row from merged data dict."""
    return [
        date_to_day(date_str),                     # A  Day
        date_str,
        _build_session_type(data.get("activity_type", "")),
        "", "", "",                            # Perceived Effort, Fatigue, Notes (manual)
        data.get("activity_name", ""),
        data.get("activity_duration", ""),
        data.get("activity_distance", ""),
        data.get("activity_avg_hr", ""),
        data.get("activity_max_hr", ""),
        data.get("activity_calories", ""),
        data.get("aerobic_te", ""),
        data.get("anaerobic_te", ""),
        data.get("zone_1", ""),                # Zone 1
        data.get("zone_2", ""),                # Zone 2
        data.get("zone_3", ""),                # Zone 3
        data.get("zone_4", ""),                # Zone 4
        data.get("zone_5", ""),                # Zone 5
        "",                                    # Zone Ranges — manual
        "Garmin Export",                       # Source
        data.get("activity_elevation", ""),    # Elevation (m)
    ]


def _build_all_rows(all_dates, existing, sheets, sleep, uds, hrv, hrv_7day, activities):
    """Phase 1: Build all rows in memory — zero API calls."""
    print("\nBuilding rows in memory...")
    rows = {"archive": [], "garmin": [], "sleep": [], "nutr": [], "sess": []}
    skipped = 0

    for date_str in all_dates:
        if date_str in existing["garmin"] and date_str in existing["archive"]:
            skipped += 1
            continue

        target_date = date.fromisoformat(date_str)
        data = merge(date_str, sleep, uds, hrv, hrv_7day, activities)

        if date_str not in existing["archive"]:
            archive_row = [date_to_day(date_str), date_str] + [
                str(data.get(k, "")) if data.get(k, "") != "" else ""
                for k in ARCHIVE_KEYS
            ]
            rows["archive"].append(archive_row)

        if date_str not in existing["garmin"]:
            rows["garmin"].append(to_sheets_row(from_garmin_api(data, target_date)))

        if date_str not in existing["sleep"] and data.get("sleep_duration"):
            rows["sleep"].append(_build_sleep_row(date_str, data))

        if date_str not in existing["nutr"]:
            rows["nutr"].append([
                date_to_day(date_str),               # Day
                date_str,
                data.get("total_calories", ""),
                data.get("active_calories", ""),
                data.get("bmr_calories", ""),
                "", "", "", "", "", "", "", "", "",  # manual cols
                "",                                  # Calorie Balance
                "",                                  # Notes
            ])

        if sheets["sess"] and date_str not in existing["sess"] and data.get("activity_name"):
            rows["sess"].append(_build_session_row(date_str, data))

    print(f"  Dates to write : {len(rows['garmin'])}  |  Skipped : {skipped}")
    return rows, skipped


def _write_all_rows(wb, rows, sheets, base):
    """Phase 2-5: Batch write, fix types, fill missing, reformat and sort."""
    start_time = time.time()
    print("\nWriting to Google Sheets (batch mode)...")

    tab_writes = [
        ("archive", "Archive",      sheets["archive"]),
        ("garmin",  "Garmin tab",    sheets["garmin"]),
        ("sleep",   "Sleep tab",     sheets["sleep"]),
        ("nutr",    "Nutrition tab", sheets["nutr"]),
    ]
    for key, label, sheet in tab_writes:
        if rows[key]:
            print(f"  {label:14s}: writing {len(rows[key])} rows...", end=" ", flush=True)
            sheet.append_rows(rows[key], value_input_option="USER_ENTERED")
            print("OK")

    if rows["sess"] and sheets["sess"]:
        sess_sheet = sheets["sess"]
        print(f"  Session Log  : writing {len(rows['sess'])} rows...", end=" ", flush=True)
        sess_sheet.append_rows(rows["sess"], value_input_option="USER_ENTERED")
        print("OK")
        # Deduplicate Session Log: keep first occurrence of each date+activity_name pair
        all_sess = sess_sheet.get_all_values()
        if len(all_sess) > 1:
            seen_sess = set()
            rows_to_delete = []
            for ri, row in enumerate(all_sess[1:], start=2):
                key = (row[1].strip() if len(row) > 1 else "", row[6].strip() if len(row) > 6 else "")
                if key in seen_sess:
                    rows_to_delete.append(ri)
                else:
                    seen_sess.add(key)
            for ri in reversed(rows_to_delete):
                sess_sheet.delete_rows(ri)
            if rows_to_delete:
                print(f"  Session Log  : removed {len(rows_to_delete)} duplicate row(s)")

    # Phase 3-5
    print("\nFixing data types (dates, times, numbers)...")
    fix_data_types(wb)

    print("\nFilling any remaining missing cells from export...")
    fill_missing_data(wb, base)

    print("\nApplying formatting and sorting...")
    reformat_sheets(wb)
    from sheets_formatting import sort_sheet_by_date_desc
    for tab in ["Garmin", "Sleep", "Session Log", "Nutrition", "Raw Data Archive"]:
        sort_sheet_by_date_desc(wb, tab)

    elapsed = time.time() - start_time
    return elapsed


def main():
    args = parse_args()
    base    = args["folder"]
    dry_run = args["dry_run"]

    # --fix-data mode: patch sentinel values and remove Session Log duplicates
    if args.get("fix_data"):
        print("\nHealth Tracker — Fix Existing Sheet Data")
        print("Connecting to Google Sheets...")
        wb = get_workbook()
        fix_existing_data(wb)
        verify_import(wb, set())
        return

    # --fill-missing mode: fill blank cells where export has data (incl. zones + bb gained)
    if args.get("fill_missing"):
        if not base.exists():
            print(f"ERROR: Export folder not found: {base}")
            return
        print("\nHealth Tracker — Fill Missing Cells from Export")
        print("Connecting to Google Sheets...")
        wb = get_workbook()
        fill_missing_data(wb, base)
        return

    # --fix-types mode: correct stored data types (text vs number vs datetime)
    if args.get("fix_types"):
        if not base.exists():
            print(f"ERROR: Export folder not found: {base}")
            return
        print("\nHealth Tracker — Fix Data Types")
        print("Connecting to Google Sheets...")
        wb = get_workbook()
        fix_data_types(wb)
        return

    # --reformat mode: apply uniform formatting to all tabs
    if args.get("reformat"):
        print("\nHealth Tracker — Reformat All Sheets")
        print("Connecting to Google Sheets...")
        wb = get_workbook()
        reformat_sheets(wb)
        return

    print(f"\nHealth Tracker — Garmin Export Importer")
    print(f"  Export folder : {base}")
    print(f"  Mode          : {'DRY RUN' if dry_run else 'LIVE'}\n")

    if not base.exists():
        print(f"ERROR: Export folder not found: {base}")
        print("  Pass the correct path with --folder")
        return

    sleep, uds, hrv, hrv_7day, activities = _load_export_data(base)

    all_dates = sorted(set(list(sleep.keys()) + list(uds.keys())))
    if args["start"]:
        all_dates = [d for d in all_dates if d >= args["start"]]
    if args["end"]:
        all_dates = [d for d in all_dates if d <= args["end"]]

    print(f"\n  Total dates to process: {len(all_dates)}")
    print(f"  Date range            : {all_dates[0]} to {all_dates[-1]}")

    if dry_run:
        print("\nDry run complete. Run without --dry-run to write to Google Sheets.")
        return

    input("\n  Press Enter to start writing to Google Sheets (Ctrl+C to cancel)...")

    print("\nConnecting to Google Sheets...")
    wb = get_workbook()
    sheets, existing = _read_existing_dates(wb)
    rows, skipped = _build_all_rows(all_dates, existing, sheets,
                                     sleep, uds, hrv, hrv_7day, activities)

    if len(rows["garmin"]) == 0:
        print("\nAll dates already synced.")
        verify_import(wb, set())
        return

    input("\n  Press Enter to write to Google Sheets (Ctrl+C to cancel)...")

    elapsed = _write_all_rows(wb, rows, sheets, base)

    print(f"\nDone in {elapsed:.0f}s ({elapsed/60:.1f} min).")
    print(f"  Written  : {len(rows['garmin'])}")
    print(f"  Skipped  : {skipped}  (already in sheet + archive)")

    written_dates = set(row[1] for row in rows["garmin"])
    verify_import(wb, written_dates)


if __name__ == "__main__":
    main()
