"""Restore all Google Sheets tabs from SQLite backup.

Reads every table from health_tracker.db and writes the data back to
the corresponding Google Sheets tab, creating tabs as needed.

Usage:
    python restore_from_sqlite.py          # restore all tabs
    python restore_from_sqlite.py --tab Sleep   # restore one tab
    python restore_from_sqlite.py --dry-run     # preview without writing
"""

import sqlite3
import sys
import os
import time
from pathlib import Path
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

from schema import (
    HEADERS, SLEEP_HEADERS, NUTRITION_HEADERS, SESSION_LOG_HEADERS,
    DAILY_LOG_HEADERS, OVERALL_ANALYSIS_HEADERS, STRENGTH_LOG_HEADERS,
    ARCHIVE_HEADERS,
)

DB_PATH = Path(__file__).parent / "health_tracker.db"
SHEET_ID = os.getenv("SHEET_ID", "")
JSON_KEY = Path(__file__).parent / os.getenv("JSON_KEY_FILE", "")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Mapping: (tab_name, headers, sql_table, sql_columns_in_header_order)
# sql_columns lists the SQLite column to pull for each Sheets column, in order.
# None = skip (formula column, computed in Sheets).

TAB_SPECS = [
    ("Garmin", HEADERS, "garmin", [
        "day", "date", "sleep_score", "hrv_overnight_avg", "hrv_7day_avg",
        "resting_hr", "sleep_duration_hrs", "body_battery", "steps",
        "total_calories_burned", "active_calories_burned", "bmr_calories",
        "avg_stress_level", "stress_qualifier", "floors_ascended",
        "moderate_intensity_min", "vigorous_intensity_min",
        "body_battery_at_wake", "body_battery_high", "body_battery_low",
        "activity_name", "activity_type", "start_time",
        "distance_mi", "duration_min", "avg_hr", "max_hr", "calories",
        "elevation_gain_m", "avg_speed_mph",
        "aerobic_training_effect", "anaerobic_training_effect",
        "zone_1_min", "zone_2_min", "zone_3_min", "zone_4_min", "zone_5_min",
    ]),
    ("Sleep", SLEEP_HEADERS, "sleep", [
        "day", "date", "garmin_sleep_score", "sleep_analysis_score",
        "total_sleep_hrs", "sleep_analysis", "notes",
        "bedtime", "wake_time", "bedtime_variability_7d", "wake_variability_7d",
        "time_in_bed_hrs", "deep_sleep_min", "light_sleep_min", "rem_min",
        "awake_during_sleep_min", "deep_pct", "rem_pct",
        "sleep_cycles", "awakenings", "avg_hr", "avg_respiration",
        "overnight_hrv_ms", "body_battery_gained", "sleep_feedback",
    ]),
    ("Nutrition", NUTRITION_HEADERS, "nutrition", [
        "day", "date", "total_calories_burned", "active_calories_burned",
        "bmr_calories", "breakfast", "lunch", "dinner", "snacks",
        "total_calories_consumed", "protein_g", "carbs_g", "fats_g",
        "water_l", None,  # O = Calorie Balance (formula)
        "notes",
    ]),
    ("Session Log", SESSION_LOG_HEADERS, "session_log", [
        "day", "date", "session_type", "perceived_effort", "post_workout_energy",
        "notes", "activity_name", "duration_min", "distance_mi",
        "avg_hr", "max_hr", "calories", "aerobic_te", "anaerobic_te",
        "zone_1_min", "zone_2_min", "zone_3_min", "zone_4_min", "zone_5_min",
        "zone_ranges", "source", "elevation_m",
    ]),
    ("Daily Log", DAILY_LOG_HEADERS, "daily_log", [
        "day", "date", "morning_energy", "wake_at_930", "no_morning_screens",
        "creatine_hydrate", "walk_breathing", "physical_activity",
        "no_screens_before_bed", "bed_at_10pm",
        None,  # K = Habits Total (formula)
        "midday_energy", "midday_focus", "midday_mood", "midday_body_feel",
        "midday_notes", "evening_energy", "evening_focus", "evening_mood",
        "perceived_stress", "day_rating", "evening_notes",
    ]),
    ("Overall Analysis", OVERALL_ANALYSIS_HEADERS, "overall_analysis", [
        "day", "date", "readiness_score", "readiness_label", "confidence",
        "cognitive_energy_assessment", "sleep_context",
        "cognition", "cognition_notes",
        "key_insights", "recommendations", "training_load_status",
        "data_quality", "quality_flags",
    ]),
    ("Strength Log", STRENGTH_LOG_HEADERS, "strength_log", [
        "day", "date", "muscle_group", "exercise",
        "weight_lbs", "reps", "rpe", "notes",
    ]),
    ("Raw Data Archive", ARCHIVE_HEADERS, "raw_data_archive", [
        "day", "date",
        "hrv", "hrv_7day", "resting_hr", "body_battery", "steps",
        "total_calories", "active_calories", "bmr_calories",
        "avg_stress", "stress_qualifier", "floors_ascended",
        "moderate_min", "vigorous_min", "bb_at_wake", "bb_high", "bb_low",
        "sleep_duration", "sleep_score", "sleep_bedtime", "sleep_wake_time",
        "sleep_time_in_bed", "sleep_deep_min", "sleep_light_min", "sleep_rem_min",
        "sleep_awake_min", "sleep_deep_pct", "sleep_rem_pct", "sleep_cycles",
        "sleep_awakenings", "sleep_avg_hr", "sleep_avg_respiration",
        "sleep_body_battery_gained", "sleep_feedback",
        "activity_name", "activity_type", "activity_start",
        "activity_distance", "activity_duration", "activity_avg_hr", "activity_max_hr",
        "activity_calories", "activity_elevation", "activity_avg_speed",
        "aerobic_te", "anaerobic_te",
        "zone_1", "zone_2", "zone_3", "zone_4", "zone_5",
    ]),
]

# Columns that must stay as RAW text (dates, times) — everything else is USER_ENTERED
# These are 0-based column indices per tab
RAW_TEXT_COLS = {
    "Garmin": [1, 22],          # Date, Start Time
    "Sleep": [1, 7, 8],         # Date, Bedtime, Wake Time
    "Nutrition": [1],           # Date
    "Session Log": [1],         # Date
    "Daily Log": [1],           # Date
    "Overall Analysis": [1],    # Date
    "Strength Log": [1],        # Date
    "Raw Data Archive": [1],    # Date
}

# Numeric columns per tab (0-based) that MUST be written with USER_ENTERED
# so conditional formatting gradients work. Everything not in RAW_TEXT_COLS
# and not pure text gets USER_ENTERED.


def get_workbook():
    creds = Credentials.from_service_account_file(str(JSON_KEY), scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID)


def read_sqlite_table(table_name, columns):
    """Read rows from SQLite, returning list of lists in column order."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # Build SELECT with only the columns we need (skip None = formula cols)
    real_cols = [col for col in columns if col is not None]
    col_str = ", ".join(f'"{c}"' for c in real_cols)

    rows = c.execute(f"SELECT {col_str} FROM \"{table_name}\" ORDER BY date DESC").fetchall()
    conn.close()

    # Map back to full column list (inserting "" for formula columns)
    result = []
    for row in rows:
        full_row = []
        real_idx = 0
        for col in columns:
            if col is None:
                full_row.append("")  # formula placeholder
            else:
                val = row[real_idx]
                full_row.append("" if val is None else val)
                real_idx += 1
        result.append(full_row)

    return result


def write_tab(wb, tab_name, headers, rows, dry_run=False):
    """Write headers + data to a Sheets tab. Creates tab if missing."""
    print(f"\n  {tab_name}: {len(rows)} rows", end="")
    if dry_run:
        print(" (dry run — skipped)")
        return

    # Get or create tab
    try:
        sheet = wb.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        sheet = wb.add_worksheet(title=tab_name, rows=max(1000, len(rows) + 10), cols=len(headers))
        print(f" (created)", end="")

    # Ensure enough rows
    if sheet.row_count < len(rows) + 5:
        sheet.resize(rows=len(rows) + 100, cols=len(headers))

    # Write headers
    sheet.update(range_name="A1", values=[headers])
    time.sleep(1)  # API quota

    if not rows:
        print(" -> done (headers only)")
        return

    # Separate text-date columns from numeric columns
    raw_cols = set(RAW_TEXT_COLS.get(tab_name, []))

    # Phase 1: Write ALL data as RAW first (preserves dates/times as text)
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        start_row = i + 2  # row 1 is headers
        sheet.update(
            range_name=f"A{start_row}",
            values=batch,
            value_input_option="RAW",
        )
        print(".", end="", flush=True)
        time.sleep(2)  # API quota

    # Phase 2: Re-write numeric columns with USER_ENTERED so gradients work.
    # Strategy: find contiguous ranges of numeric columns and write each range
    # as a single batch call (not one column at a time).
    numeric_col_indices = []
    for ci in range(len(headers)):
        if ci in raw_cols:
            continue
        has_numeric = False
        for row in rows[:20]:
            val = row[ci] if ci < len(row) else ""
            if isinstance(val, (int, float)) and val != "":
                has_numeric = True
                break
        if has_numeric:
            numeric_col_indices.append(ci)

    if numeric_col_indices:
        # Group into contiguous ranges: [(start_col, end_col), ...]
        ranges = []
        start = numeric_col_indices[0]
        end = start
        for ci in numeric_col_indices[1:]:
            if ci == end + 1:
                end = ci
            else:
                ranges.append((start, end))
                start = ci
                end = ci
        ranges.append((start, end))

        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            start_row = i + 2

            for col_start, col_end in ranges:
                start_letter = gspread.utils.rowcol_to_a1(1, col_start + 1).rstrip("1")
                end_letter = gspread.utils.rowcol_to_a1(1, col_end + 1).rstrip("1")
                values = [
                    [row[ci] if ci < len(row) else "" for ci in range(col_start, col_end + 1)]
                    for row in batch
                ]
                sheet.update(
                    range_name=f"{start_letter}{start_row}:{end_letter}{start_row + len(batch) - 1}",
                    values=values,
                    value_input_option="USER_ENTERED",
                )
                time.sleep(2)
            print("+", end="", flush=True)

    # Phase 3: Add formulas where needed
    if tab_name == "Nutrition":
        # Column O = Calorie Balance = J - C (consumed - burned)
        formulas = []
        for ri in range(len(rows)):
            row_num = ri + 2
            formulas.append([f'=IF(J{row_num}<>"",J{row_num}-C{row_num},"")'])
        if formulas:
            sheet.update(
                range_name=f"O2",
                values=formulas,
                value_input_option="USER_ENTERED",
            )
            time.sleep(1)

    elif tab_name == "Daily Log":
        # Column K = Habits Total = SUM of checkboxes D-J
        formulas = []
        for ri in range(len(rows)):
            row_num = ri + 2
            formulas.append([f'=COUNTIF(D{row_num}:J{row_num},TRUE)'])
        if formulas:
            sheet.update(
                range_name=f"K2",
                values=formulas,
                value_input_option="USER_ENTERED",
            )
            time.sleep(1)

    print(" -> done")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Restore Google Sheets from SQLite backup")
    parser.add_argument("--tab", help="Restore only this tab")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: Database not found: {DB_PATH}")
        sys.exit(1)

    print(f"Database: {DB_PATH}")
    print(f"Sheet ID: {SHEET_ID}")

    if not args.dry_run:
        wb = get_workbook()
        print(f"Connected to: {wb.title}")

        # Delete default Sheet1 if it exists
        try:
            s1 = wb.worksheet("Sheet1")
            wb.del_worksheet(s1)
            print("  Removed default Sheet1")
        except gspread.WorksheetNotFound:
            pass
    else:
        wb = None
        print("DRY RUN — no writes will be made")

    for tab_name, headers, table, columns in TAB_SPECS:
        if args.tab and args.tab != tab_name:
            continue

        rows = read_sqlite_table(table, columns)
        write_tab(wb, tab_name, headers, rows, dry_run=args.dry_run)

    print(f"\n{'DRY RUN complete.' if args.dry_run else 'Restore complete.'}")
    if not args.dry_run:
        print("Next steps:")
        print("  1. python verify_sheets.py")
        print("  2. python reformat_style.py")
        print("  3. python verify_formatting.py --repair")


if __name__ == "__main__":
    main()
