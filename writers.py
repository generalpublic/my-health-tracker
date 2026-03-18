"""
writers.py — Per-tab Google Sheets write functions.

Handles upsert logic for Garmin, Session Log, Sleep, Nutrition, and Archive tabs.
"""

import re
import gspread

from utils import date_to_day, _safe_float
from schema import (
    HEADERS, SLEEP_HEADERS, NUTRITION_HEADERS, DAILY_LOG_HEADERS,
    ARCHIVE_HEADERS, ARCHIVE_KEYS,
    NUTRITION_MANUAL_COLS, SLEEP_MANUAL_COLS, DAILY_LOG_MANUAL_COLS,
    SL_EFFORT, SL_ENERGY, SL_NOTES, SL_ACTIVITY,
    TAB_ARCHIVE,
)
from sheets_formatting import apply_yellow_columns, bold_headers
from sleep_analysis import generate_sleep_analysis


# --- Garmin Tab ---

def setup_headers(sheet):
    """Ensure Garmin tab headers match schema."""
    if sheet.row_values(1) != HEADERS:
        sheet.update(range_name="A1", values=[HEADERS])


def upsert_row(sheet, date_str, row):
    """Update existing row for date, or append if not found."""
    all_dates = sheet.col_values(2)  # Date is column B
    if date_str in all_dates:
        row_index = all_dates.index(date_str) + 1
        sheet.update(range_name=f"A{row_index}", values=[row])
        print(f"  Updated existing row for {date_str}.")
    else:
        sheet.append_row(row)
        print(f"  Appended new row for {date_str}.")


def build_garmin_row(target_date, data):
    """Build a Garmin tab row from a data dict."""
    return [
        date_to_day(str(target_date)),
        str(target_date),
        data.get("sleep_score", ""),
        data.get("hrv", ""),
        data.get("hrv_7day", ""),
        data.get("resting_hr", ""),
        data.get("sleep_duration", ""),
        data.get("body_battery", ""),
        data.get("steps", ""),
        data.get("total_calories", ""),
        data.get("active_calories", ""),
        data.get("bmr_calories", ""),
        data.get("avg_stress", ""),
        data.get("stress_qualifier", ""),
        data.get("floors_ascended", ""),
        data.get("moderate_min", ""),
        data.get("vigorous_min", ""),
        data.get("bb_at_wake", ""),
        data.get("bb_high", ""),
        data.get("bb_low", ""),
        data.get("activity_name", ""),
        data.get("activity_type", ""),
        data.get("activity_start", ""),
        data.get("activity_distance", ""),
        data.get("activity_duration", ""),
        data.get("activity_avg_hr", ""),
        data.get("activity_max_hr", ""),
        data.get("activity_calories", ""),
        data.get("activity_elevation", ""),
        data.get("activity_avg_speed", ""),
        data.get("aerobic_te", ""),
        data.get("anaerobic_te", ""),
        data.get("zone_1", ""),
        data.get("zone_2", ""),
        data.get("zone_3", ""),
        data.get("zone_4", ""),
        data.get("zone_5", ""),
    ]


# --- Session Log Tab ---

def write_to_session_log(wb, today, data):
    """Upsert Session Log with Garmin activity data.

    Match by date + activity name (composite key for multi-activity days).
    """
    if not data.get("activity_name"):
        return

    try:
        sheet = wb.worksheet("Session Log")
    except Exception:
        print("  Session Log tab not found -- skipping. Run setup_analysis.py first.")
        return

    activity_type = data.get("activity_type", "").lower()
    if any(x in activity_type for x in ["running", "run", "trail"]):
        session_type = "Run"
    elif any(x in activity_type for x in ["cycling", "bike", "biking"]):
        session_type = "Cycle"
    elif any(x in activity_type for x in ["swimming", "swim"]):
        session_type = "Swim"
    elif any(x in activity_type for x in ["strength", "weight", "gym"]):
        session_type = "Strength"
    else:
        session_type = "Other"

    row = [
        date_to_day(str(today)),                              # 0  Day (A)
        str(today),                                           # 1  Date (B)
        session_type,                                         # 2  Session Type (C)
        "",                                                   # 3  Perceived Effort (D)
        "",                                                   # 4  Post-Workout Energy (E)
        "",                                                   # 5  Notes (F)
        data.get("activity_name", ""),                        # 6  Activity Name (G)
        data.get("activity_duration", ""),                    # 7  Duration (min) (H)
        data.get("activity_distance", ""),                    # 8  Distance (mi) (I)
        data.get("activity_avg_hr", ""),                      # 9  Avg HR (J)
        data.get("activity_max_hr", ""),                      # 10 Max HR (K)
        data.get("activity_calories", ""),                    # 11 Calories (L)
        data.get("aerobic_te", ""),                           # 12 Aerobic TE (M)
        data.get("anaerobic_te", ""),                         # 13 Anaerobic TE (N)
        data.get("zone_1", ""),                               # 14 Zone 1 (O)
        data.get("zone_2", ""),                               # 15 Zone 2 (P)
        data.get("zone_3", ""),                               # 16 Zone 3 (Q)
        data.get("zone_4", ""),                               # 17 Zone 4 (R)
        data.get("zone_5", ""),                               # 18 Zone 5 (S)
        data.get("zone_ranges", ""),                          # 19 Zone Ranges (T)
        "Garmin Auto",                                        # 20 Source (U)
        data.get("activity_elevation", ""),                   # 21 Elevation (m) (V)
    ]

    # Find existing row matching this date + activity name
    all_rows = sheet.get_all_values()
    activity_name = data.get("activity_name", "")
    match_row_index = None
    for i, existing_row in enumerate(all_rows[1:], start=2):
        if (existing_row[1] == str(today)
                and len(existing_row) > SL_ACTIVITY
                and existing_row[SL_ACTIVITY] == activity_name):
            match_row_index = i
            break

    if match_row_index:
        existing = all_rows[match_row_index - 1]
        def _keep(idx): return existing[idx] if len(existing) > idx else ""
        effort = _keep(SL_EFFORT)
        row[SL_EFFORT]       = effort if effort not in ("", "Garmin Auto") else ""
        row[SL_ENERGY]       = _keep(SL_ENERGY)
        row[SL_NOTES]        = _keep(SL_NOTES)
        row[0]               = _keep(0) or date_to_day(str(today))
        sheet.update(range_name=f"A{match_row_index}", values=[row])
        print(f"  Session Log: updated {session_type} -- {activity_name}.")
    else:
        sheet.append_row(row)
        print(f"  Session Log: {session_type} -- {activity_name} logged.")


# --- Nutrition Tab ---

def write_to_nutrition_log(wb, target_date, data):
    """Upsert Nutrition tab with Garmin calorie data. Manual cells left empty on insert."""
    try:
        sheet = wb.worksheet("Nutrition")
    except Exception:
        sheet = wb.add_worksheet(title="Nutrition", rows=1000, cols=len(NUTRITION_HEADERS))
        sheet.update(range_name="A1", values=[NUTRITION_HEADERS])
        apply_yellow_columns(wb, "Nutrition", NUTRITION_MANUAL_COLS)
        print("  Nutrition tab created.")

    existing_headers = sheet.row_values(1)
    if existing_headers != NUTRITION_HEADERS:
        sheet.update(range_name="A1", values=[NUTRITION_HEADERS])
        apply_yellow_columns(wb, "Nutrition", NUTRITION_MANUAL_COLS)

    date_str       = str(target_date)
    day_str        = date_to_day(date_str)
    total_cals     = data.get("total_calories", "")
    active_cals    = data.get("active_calories", "")
    bmr_cals       = data.get("bmr_calories", "")

    all_dates = sheet.col_values(2)
    if date_str in all_dates:
        row_index = all_dates.index(date_str) + 1
        existing  = sheet.row_values(row_index)
        def _get(i): return existing[i] if len(existing) > i else ""
        row = [
            _get(0) or day_str,  # A Day
            date_str,    # B auto
            total_cals,  # C auto
            active_cals, # D auto
            bmr_cals,    # E auto
            _get(5),     # F Breakfast    manual
            _get(6),     # G Lunch        manual
            _get(7),     # H Dinner       manual
            _get(8),     # I Snacks       manual
            _get(9),     # J Cal Consumed manual
            _get(10),    # K Protein      manual
            _get(11),    # L Carbs        manual
            _get(12),    # M Fats         manual
            _get(13),    # N Water        manual
            "",          # O Balance      formula
            _get(15),    # P Notes        manual
        ]
        row[14] = f'=IF(J{row_index}<>"",J{row_index}-C{row_index},"")'
        sheet.update(range_name=f"A{row_index}", values=[row], value_input_option="USER_ENTERED")
        print(f"  Nutrition: updated row for {date_str}.")
    else:
        row = [
            day_str, date_str, total_cals, active_cals, bmr_cals,
            "", "", "", "", "", "", "", "", "",  # F-N manual (blank)
            "",  # O balance
            "",  # P notes
        ]
        sheet.append_row(row)
        new_row_index = len(sheet.get_all_values())
        row[14] = f'=IF(J{new_row_index}<>"",J{new_row_index}-C{new_row_index},"")'
        sheet.update(range_name=f"O{new_row_index}", values=[[row[14]]], value_input_option="USER_ENTERED")
        print(f"  Nutrition: logged {date_str}.")


# --- Sleep Tab ---

def write_to_sleep_log(wb, target_date, data):
    """Upsert Sleep tab with detailed nightly sleep data."""
    if not data.get("sleep_duration"):
        return

    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        print("  Sleep tab not found -- skipping. Run setup_analysis.py first.")
        return

    existing_headers = sheet.row_values(1)
    if existing_headers != SLEEP_HEADERS:
        sheet.update(range_name="A1", values=[SLEEP_HEADERS])
        apply_yellow_columns(wb, "Sleep", SLEEP_MANUAL_COLS)

    date_str = str(target_date)
    day_str  = date_to_day(date_str)
    all_dates = sheet.col_values(2)

    if date_str in all_dates:
        row_index = all_dates.index(date_str) + 1
        existing  = sheet.row_values(row_index)
        raw_g     = existing[6] if len(existing) > 6 else ""
        notes     = raw_g if raw_g and not re.match(r'^\d{2}:\d{2}$', raw_g.strip()) else ""
    else:
        row_index = None
        existing = []
        notes     = ""

    ind_score, analysis = generate_sleep_analysis(data)

    existing_day = existing[0] if row_index and len(existing) > 0 else ""
    row = [
        existing_day or day_str,                       # A  Day
        date_str,                                      # B  Date
        data.get("sleep_score", ""),                   # C  Garmin Sleep Score
        ind_score if ind_score is not None else "",    # D  Sleep Analysis Score
        data.get("sleep_duration", ""),                # E  Total Sleep (hrs)
        analysis,                                      # F  Sleep Analysis (auto)
        notes,                                         # G  Notes  (manual)
        data.get("sleep_bedtime", ""),                 # H  Bedtime
        data.get("sleep_wake_time", ""),               # I  Wake Time
        "",                                            # J  Bedtime Variability (7d) — computed after write
        "",                                            # K  Wake Variability (7d) — computed after write
        data.get("sleep_time_in_bed", ""),             # L  Time in Bed (hrs)
        data.get("sleep_deep_min", ""),                # M  Deep Sleep (min)
        data.get("sleep_light_min", ""),               # N  Light Sleep (min)
        data.get("sleep_rem_min", ""),                 # O  REM (min)
        data.get("sleep_awake_min", ""),               # P  Awake During Sleep (min)
        data.get("sleep_deep_pct", ""),                # Q  Deep %
        data.get("sleep_rem_pct", ""),                 # R  REM %
        data.get("sleep_cycles", ""),                  # S  Sleep Cycles
        data.get("sleep_awakenings", ""),              # T  Awakenings
        data.get("sleep_avg_hr", ""),                  # U  Avg HR
        data.get("sleep_avg_respiration", ""),         # V  Avg Respiration
        data.get("hrv", ""),                           # W  Overnight HRV (ms)
        data.get("sleep_body_battery_gained", ""),     # X  Body Battery Gained
        data.get("sleep_feedback", ""),                # Y  Sleep Feedback
    ]

    if row_index:
        sheet.update(range_name=f"A{row_index}", values=[row],
                     value_input_option="RAW")
        print(f"  Sleep: updated row for {date_str}.")
    else:
        sheet.append_row(row, value_input_option="RAW")
        row_index = len(sheet.col_values(2))
        print(f"  Sleep: logged {date_str}.")

    # Re-write numeric columns as actual numbers for gradient formatting
    # All numeric columns: C-E(2-4), J-X(9-23) — excludes H/I (time text) and Y (feedback text)
    numeric_col_indices = [2, 3, 4, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
    numeric_cells = []
    for ci in numeric_col_indices:
        val = row[ci] if ci < len(row) else ""
        if val != "" and val is not None:
            try:
                numeric_cells.append(gspread.Cell(row=row_index, col=ci + 1, value=float(val)))
            except (ValueError, TypeError):
                pass
    if numeric_cells:
        sheet.update_cells(numeric_cells, value_input_option="USER_ENTERED")

    # Compute and write sleep variability (7-day rolling SD of bedtime/wake time)
    _update_sleep_variability(sheet, row_index)

    # Post-write alignment check — catch column shifts before they propagate
    _verify_sleep_row_alignment(sheet, row_index)


def _verify_sleep_row_alignment(sheet, row_index):
    """Spot-check that key columns contain the expected data types after write."""
    try:
        row = sheet.row_values(row_index)
        errors = []
        # Bedtime (H, index 7) should be HH:MM or empty
        bed = row[7] if len(row) > 7 else ""
        if bed and ":" not in bed:
            errors.append(f"H{row_index}(Bedtime)='{bed}' — expected HH:MM")
        # Wake Time (I, index 8) should be HH:MM or empty
        wake = row[8] if len(row) > 8 else ""
        if wake and ":" not in wake:
            errors.append(f"I{row_index}(Wake Time)='{wake}' — expected HH:MM")
        # Variability (J/K, indices 9/10) should be numeric or empty
        for ci, label in [(9, "Bed Var"), (10, "Wake Var")]:
            val = row[ci] if len(row) > ci else ""
            if val and not val.replace(".", "").replace("-", "").isdigit():
                from gspread.utils import rowcol_to_a1
                col_letter = rowcol_to_a1(1, ci + 1).rstrip("1")
                errors.append(f"{col_letter}{row_index}({label})='{val[:30]}' — expected numeric")
        # Sleep Feedback (Y, index 24) should be text or empty, not a pure number
        fb = row[24] if len(row) > 24 else ""
        if fb and fb.replace(".", "").isdigit() and float(fb) < 200:
            errors.append(f"Y{row_index}(Feedback)='{fb}' — expected text, got number (possible column shift)")
        if errors:
            print(f"  WARNING: Sleep row {row_index} alignment issue:")
            for e in errors:
                print(f"    {e}")
    except Exception:
        pass  # don't block writes on verification failure


def _time_to_minutes(t_str):
    """Convert 'HH:MM' to minutes since midnight, handling overnight bedtimes."""
    if not t_str or not isinstance(t_str, str):
        return None
    try:
        parts = t_str.strip().split(":")
        h, m = int(parts[0]), int(parts[1])
        mins = h * 60 + m
        # Bedtimes after midnight (00:00-05:59) treated as next-day — add 24h
        if h < 6:
            mins += 1440
        return mins
    except (ValueError, IndexError):
        return None


def _rolling_sd_minutes(values):
    """Standard deviation of a list of minute values (ignoring None)."""
    valid = [v for v in values if v is not None]
    if len(valid) < 3:
        return None
    mean = sum(valid) / len(valid)
    variance = sum((v - mean) ** 2 for v in valid) / len(valid)
    return round(variance ** 0.5, 1)


def _update_sleep_variability(sheet, target_row_index):
    """Compute 7-day rolling SD for bedtime/wake time and write to columns J/K."""
    try:
        all_data = sheet.get_values()
        headers = all_data[0]
        bed_ci = headers.index("Bedtime")
        wake_ci = headers.index("Wake Time")
        date_ci = headers.index("Date")

        # Get the target date from the row we just wrote
        target_row = all_data[target_row_index - 1]
        target_date = target_row[date_ci] if len(target_row) > date_ci else ""

        # Sort all data rows by date descending (newest first) so lookups work
        # regardless of whether the sheet has been sorted yet
        data_rows = all_data[1:]  # exclude header
        data_rows.sort(key=lambda r: r[date_ci] if len(r) > date_ci else "", reverse=True)

        # Find the target date in sorted data and collect 7 consecutive entries
        bed_vals = []
        wake_vals = []
        found = False
        for row in data_rows:
            row_date = row[date_ci] if len(row) > date_ci else ""
            if not found and row_date == target_date:
                found = True
            if found:
                bed_vals.append(_time_to_minutes(row[bed_ci] if len(row) > bed_ci else ""))
                wake_vals.append(_time_to_minutes(row[wake_ci] if len(row) > wake_ci else ""))
                if len(bed_vals) >= 7:
                    break

        bed_sd = _rolling_sd_minutes(bed_vals)
        wake_sd = _rolling_sd_minutes(wake_vals)

        cells = []
        # J = col 10, K = col 11 (1-indexed)
        if bed_sd is not None:
            cells.append(gspread.Cell(target_row_index, 10, bed_sd))
        if wake_sd is not None:
            cells.append(gspread.Cell(target_row_index, 11, wake_sd))
        if cells:
            sheet.update_cells(cells, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"  Sleep variability: skipped — {e}")


# --- Raw Data Archive Tab ---

def get_or_create_archive_sheet(wb):
    """Get the Raw Data Archive sheet, creating it with headers if missing."""
    try:
        return wb.worksheet(TAB_ARCHIVE)
    except gspread.exceptions.WorksheetNotFound:
        sheet = wb.add_worksheet(
            title=TAB_ARCHIVE,
            rows=5000,
            cols=len(ARCHIVE_HEADERS),
        )
        sheet.update(range_name="A1", values=[ARCHIVE_HEADERS])
        bold_headers(wb, TAB_ARCHIVE)
        print(f"  Created '{TAB_ARCHIVE}' tab.")
        return sheet


def write_to_archive(archive_sheet, date_str, data):
    """Append a date's raw data to the archive. Skips if date already archived."""
    all_dates = archive_sheet.col_values(2)
    if date_str in all_dates:
        return
    row = [date_to_day(date_str), date_str] + [str(data.get(k, "")) if data.get(k, "") != "" else "" for k in ARCHIVE_KEYS]
    archive_sheet.append_row(row)


# --- Daily Log Tab ---

def write_to_daily_log(wb, target_date):
    """Create a Daily Log row for the date if one doesn't already exist.

    Pre-fills Day + Date only. All other columns left empty for manual entry.
    Never overwrites existing rows (preserves user data).
    """
    try:
        sheet = wb.worksheet("Daily Log")
    except Exception:
        print("  Daily Log tab not found -- skipping. Run setup_daily_log.py first.")
        return

    existing_headers = sheet.row_values(1)
    if existing_headers != DAILY_LOG_HEADERS:
        sheet.update(range_name="A1", values=[DAILY_LOG_HEADERS])
        apply_yellow_columns(wb, "Daily Log", DAILY_LOG_MANUAL_COLS)

    date_str = str(target_date)
    all_dates = sheet.col_values(2)
    if date_str in all_dates:
        return  # Row already exists -- don't touch manual data

    row = [date_to_day(date_str), date_str] + [""] * (len(DAILY_LOG_HEADERS) - 2)
    sheet.append_row(row)
    print(f"  Daily Log: created row for {date_str}.")


# --- Gap Detection ---

def find_missing_dates(sheet, lookback_days=7):
    """Check the last N days for any dates missing from the Garmin tab."""
    from datetime import date, timedelta
    today = date.today()
    expected = {today - timedelta(days=i) for i in range(1, lookback_days + 1)}
    existing = set()
    for d in sheet.col_values(2)[1:]:
        try:
            existing.add(date.fromisoformat(d))
        except (ValueError, TypeError):
            continue
    return sorted(expected - existing)
