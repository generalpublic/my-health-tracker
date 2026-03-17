from garminconnect import Garmin
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime, timedelta, timezone
from dotenv import load_dotenv
from pathlib import Path
import keyring
import os
import sys
import time
import requests

from sqlite_backup import (
    get_db as _get_sqlite_db,
    close_db as _close_sqlite_db,
    upsert_garmin as _sqlite_upsert_garmin,
    upsert_sleep as _sqlite_upsert_sleep,
    upsert_nutrition as _sqlite_upsert_nutrition,
    upsert_session_log as _sqlite_upsert_session_log,
    append_archive as _sqlite_append_archive,
)

load_dotenv(Path(__file__).parent / ".env")


def date_to_day(date_str):
    """Convert 'YYYY-MM-DD' string to 3-letter day abbreviation (Mon, Tue, etc.)."""
    from datetime import date as _d
    try:
        d = _d.fromisoformat(str(date_str))
        return d.strftime("%a")  # Mon, Tue, Wed, Thu, Fri, Sat, Sun
    except (ValueError, TypeError):
        return ""


# --- CONFIG ---
GARMIN_EMAIL    = os.getenv("GARMIN_EMAIL")
GARMIN_PASSWORD = keyring.get_password("garmin_connect", GARMIN_EMAIL)
SHEET_ID        = os.getenv("SHEET_ID")
_json_key_name  = os.getenv("JSON_KEY_FILE")
JSON_KEY_FILE   = str(Path(__file__).parent / _json_key_name) if _json_key_name else None

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

HEADERS = [
    "Day",                           # A
    "Date",                          # B
    "Sleep Score",                   # C
    "HRV (overnight avg)",           # D
    "HRV 7-day avg",                 # E
    "Resting HR",                    # F
    "Sleep Duration (hrs)",          # G
    "Body Battery",                  # H
    "Steps",                         # I
    # Daily wellness
    "Total Calories Burned",         # J
    "Active Calories Burned",        # K
    "BMR Calories",                  # L
    "Avg Stress Level",              # M
    "Stress Qualifier",              # N
    "Floors Ascended",               # O
    "Moderate Intensity Min",        # P
    "Vigorous Intensity Min",        # Q
    "Body Battery at Wake",          # R
    "Body Battery High",             # S
    "Body Battery Low",              # T
    # Activity
    "Activity Name",                 # U
    "Activity Type",                 # V
    "Start Time",                    # W
    "Distance (mi)",                 # X
    "Duration (min)",                # Y
    "Avg HR",                        # Z
    "Max HR",                        # AA
    "Calories",                      # AB
    "Elevation Gain (m)",            # AC
    "Avg Speed (mph)",               # AD
    "Aerobic Training Effect",       # AE
    "Anaerobic Training Effect",     # AF
    # HR Zones (time in minutes)
    "Zone 1 - Warm Up (min)",        # AG
    "Zone 2 - Easy (min)",           # AH
    "Zone 3 - Aerobic (min)",        # AI
    "Zone 4 - Threshold (min)",      # AJ
    "Zone 5 - Max (min)",            # AK
]

NUTRITION_HEADERS = [
    "Day",                           # A
    "Date",                          # B - auto
    "Total Calories Burned",         # C - auto
    "Active Calories Burned",        # D - auto
    "BMR Calories",                  # E - auto
    "Breakfast",                     # F - manual
    "Lunch",                         # G - manual
    "Dinner",                        # H - manual
    "Snacks",                        # I - manual
    "Total Calories Consumed",       # J - manual
    "Protein (g)",                   # K - manual
    "Carbs (g)",                     # L - manual
    "Fats (g)",                      # M - manual
    "Water (L)",                     # N - manual
    "Calorie Balance",               # O - auto (consumed - burned)
    "Notes",                         # P - manual
]

# 0-indexed columns that require manual input (light yellow)
NUTRITION_MANUAL_COLS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 15]   # F,G,H,I,J,K,L,M,N,P
SESSION_MANUAL_COLS   = [3, 4, 5, 22]                           # D,E,F,W
SLEEP_MANUAL_COLS     = [6, 7, 8]                                # G (Notes), H (Cognition), I (Cognition Notes)

YELLOW = {"red": 1.0, "green": 1.0, "blue": 0.8}              # light yellow #FFFF99

# Session Log column indices (0-based) — update these if columns change
SL_EFFORT       = 3   # D  Perceived Effort (manual)
SL_ENERGY       = 4   # E  Post-Workout Energy (manual)
SL_NOTES        = 5   # F  Notes (manual)
SL_ACTIVITY     = 6   # G  Activity Name (auto)
SL_MORNING_FEEL = 22  # W  Next Morning Feel (manual)

# --- GOOGLE SHEETS ---
def get_workbook():
    creds = Credentials.from_service_account_file(JSON_KEY_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

def get_sheet(wb):
    try:
        return wb.worksheet("Garmin")
    except gspread.exceptions.WorksheetNotFound:
        return wb.sheet1

def write_to_session_log(wb, today, data):
    """Upsert Session Log with Garmin activity data.

    Match by date + activity name:
    - Same activity for same date → overwrite (gets latest complete data)
    - Different activity on same date → append (multiple workouts in one day)
    - No existing match → append
    """
    if not data.get("activity_name"):
        return

    try:
        sheet = wb.worksheet("Session Log")
    except Exception:
        print("  Session Log tab not found — skipping. Run setup_analysis.py first.")
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
        "",                                                   # 3  Perceived Effort (D) — fill manually
        "",                                                   # 4  Post-Workout Energy (E) — fill manually 1-2 hrs after
        "",                                                   # 5  Notes (F) — fill manually
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
        "",                                                   # 22 Next Morning Feel (W) — fill manually next morning
    ]

    # Find existing row matching this date + activity name
    all_rows = sheet.get_all_values()
    activity_name = data.get("activity_name", "")
    match_row_index = None
    for i, existing_row in enumerate(all_rows[1:], start=2):  # skip header, 1-based
        if (existing_row[1] == str(today)
                and len(existing_row) > SL_ACTIVITY
                and existing_row[SL_ACTIVITY] == activity_name):
            match_row_index = i
            break

    if match_row_index:
        # Preserve manually filled columns
        existing = all_rows[match_row_index - 1]
        def _keep(idx): return existing[idx] if len(existing) > idx else ""
        effort = _keep(SL_EFFORT)
        row[SL_EFFORT]       = effort if effort not in ("", "Garmin Auto") else ""
        row[SL_ENERGY]       = _keep(SL_ENERGY)
        row[SL_NOTES]        = _keep(SL_NOTES)
        row[SL_MORNING_FEEL] = _keep(SL_MORNING_FEEL)
        row[0]               = _keep(0) or date_to_day(str(today))  # preserve Day
        sheet.update(range_name=f"A{match_row_index}", values=[row])
        print(f"  Session Log: updated {session_type} — {activity_name}.")
    else:
        sheet.append_row(row)
        print(f"  Session Log: {session_type} — {activity_name} logged.")

def write_to_nutrition_log(wb, target_date, data):
    """Upsert Nutrition tab with Garmin calorie data. Manual cells left empty on insert."""
    try:
        sheet = wb.worksheet("Nutrition")
    except Exception:
        sheet = wb.add_worksheet(title="Nutrition", rows=1000, cols=len(NUTRITION_HEADERS))
        sheet.update(range_name="A1", values=[NUTRITION_HEADERS])
        apply_yellow_columns(wb, "Nutrition", NUTRITION_MANUAL_COLS)
        print("  Nutrition tab created.")

    # Ensure headers are current
    existing_headers = sheet.row_values(1)
    if existing_headers != NUTRITION_HEADERS:
        sheet.update(range_name="A1", values=[NUTRITION_HEADERS])
        apply_yellow_columns(wb, "Nutrition", NUTRITION_MANUAL_COLS)

    date_str       = str(target_date)
    day_str        = date_to_day(date_str)
    total_cals     = data.get("total_calories", "")
    active_cals    = data.get("active_calories", "")
    bmr_cals       = data.get("bmr_calories", "")

    all_dates = sheet.col_values(2)  # Date is now column B
    if date_str in all_dates:
        row_index = all_dates.index(date_str) + 1
        existing  = sheet.row_values(row_index)
        # Preserve all manual columns (F-P), only overwrite auto columns A-E
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
            "",          # O Balance      formula (always rewritten — standard calc)
            _get(15),    # P Notes        manual
        ]
        row[14] = f'=IF(J{row_index}<>"",J{row_index}-C{row_index},"")'
        sheet.update(range_name=f"A{row_index}", values=[row], value_input_option="USER_ENTERED")
        print(f"  Nutrition: updated row for {date_str}.")
    else:
        row = [
            day_str,     # A Day
            date_str,    # B
            total_cals,  # C
            active_cals, # D
            bmr_cals,    # E
            "", "", "", "", "", "", "", "", "",   # F-N manual (blank)
            "",          # O balance (formula added after append)
            "",          # P notes
        ]
        sheet.append_row(row)
        new_row_index = len(sheet.col_values(2))  # Date is column B
        row[14] = f'=IF(J{new_row_index}<>"",J{new_row_index}-C{new_row_index},"")'
        sheet.update(range_name=f"O{new_row_index}", values=[[row[14]]], value_input_option="USER_ENTERED")
        print(f"  Nutrition: logged {date_str}.")

SLEEP_HEADERS = [
    "Day",                           # A
    "Date",                          # B
    "Garmin Sleep Score",            # C
    "Sleep Analysis Score",          # D  auto-calculated independent score
    "Total Sleep (hrs)",             # E  moved up for visibility
    "Sleep Analysis",                # F  auto-generated text
    "Notes",                         # G  manual
    "Cognition (1-10)",              # H  manual — next-day mental sharpness
    "Cognition Notes",               # I  manual — optional free text
    "Bedtime",                       # J
    "Wake Time",                     # K
    "Time in Bed (hrs)",             # L
    "Deep Sleep (min)",              # M
    "Light Sleep (min)",             # N
    "REM (min)",                     # O
    "Awake During Sleep (min)",      # P
    "Deep %",                        # Q
    "REM %",                         # R
    "Sleep Cycles",                  # S
    "Awakenings",                    # T
    "Avg HR",                        # U
    "Avg Respiration",               # V
    "Overnight HRV (ms)",            # W
    "Body Battery Gained",           # X
    "Sleep Feedback",                # Y
]

def _safe_float(val, default=None):
    """Convert a value to float, returning default if empty or invalid."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_bedtime_hour(bedtime_str):
    """Parse HH:MM bedtime string into a float hour (0-24). Returns None if invalid."""
    if not bedtime_str or not isinstance(bedtime_str, str):
        return None
    import re
    m = re.match(r'^(\d{1,2}):(\d{2})$', bedtime_str.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h + mi / 60.0


def compute_independent_score(data):
    """Compute a 0-100 independent sleep quality score from raw metrics.

    Weighted composite:
      Total sleep:       25 pts (0 at <=4h, max at >=7h)
      Deep %:            20 pts (0 at <=10%, max at >=20%)
      REM %:             20 pts (0 at <=10%, max at >=20%)
      HRV:               15 pts (0 at <=30ms, max at >=45ms)
      Awakenings:        10 pts (max at 0, 0 at >=8)
      Body battery:      10 pts (0 at 0, max at >=60)
      Bedtime modifier:  +5 before midnight, -10 after 1:30 AM
    """
    score = 0.0
    metrics_found = 0

    # Total sleep (25 pts)
    total = _safe_float(data.get("sleep_duration"))
    if total is not None:
        score += min(25, max(0, (total - 4) / (7 - 4) * 25))
        metrics_found += 1

    # Deep % (20 pts)
    deep = _safe_float(data.get("sleep_deep_pct"))
    if deep is not None:
        score += min(20, max(0, (deep - 10) / (20 - 10) * 20))
        metrics_found += 1

    # REM % (20 pts)
    rem = _safe_float(data.get("sleep_rem_pct"))
    if rem is not None:
        score += min(20, max(0, (rem - 10) / (20 - 10) * 20))
        metrics_found += 1

    # HRV (15 pts)
    hrv = _safe_float(data.get("hrv"))
    if hrv is not None:
        score += min(15, max(0, (hrv - 30) / (45 - 30) * 15))
        metrics_found += 1

    # Awakenings (10 pts) — fewer is better
    awake = _safe_float(data.get("sleep_awakenings"))
    if awake is not None:
        score += min(10, max(0, (8 - awake) / 8 * 10))
        metrics_found += 1

    # Body battery gained (10 pts)
    bb = _safe_float(data.get("sleep_body_battery_gained"))
    if bb is not None:
        score += min(10, max(0, bb / 60 * 10))
        metrics_found += 1

    # Bedtime modifier
    bedtime_str = data.get("sleep_bedtime")
    bt_hour = _parse_bedtime_hour(bedtime_str)
    if bt_hour is not None:
        if bt_hour < 24:
            # Convert: 22:00=22, 23:30=23.5, 0:30=0.5, 1:45=1.75
            # Normalize so after-midnight hours are >24 for comparison
            effective = bt_hour if bt_hour >= 18 else bt_hour + 24
            if effective <= 24:      # before midnight
                score += 5
            elif effective >= 25.5:  # after 1:30 AM
                score -= 10

    if metrics_found == 0:
        return None

    return round(max(0, min(100, score)))


def generate_sleep_analysis(data):
    """Generate an interpretive sleep analysis from Garmin metrics.

    Uses research-based thresholds from Perfecting Sleep 2.md to evaluate
    sleep architecture and produce cross-metric pattern analysis with
    specific, actionable guidance.
    """
    findings = []      # (severity, short_text)
    insights = []      # cross-metric interpretations
    actions = []       # specific actionable recommendations

    total = _safe_float(data.get("sleep_duration"))
    deep_pct = _safe_float(data.get("sleep_deep_pct"))
    rem_pct = _safe_float(data.get("sleep_rem_pct"))
    hrv = _safe_float(data.get("hrv"))
    resp = _safe_float(data.get("sleep_avg_respiration"))
    awakenings = _safe_float(data.get("sleep_awakenings"))
    cycles = _safe_float(data.get("sleep_cycles"))
    bb_gained = _safe_float(data.get("sleep_body_battery_gained"))
    deep_min = _safe_float(data.get("sleep_deep_min"))
    rem_min = _safe_float(data.get("sleep_rem_min"))
    light_min = _safe_float(data.get("sleep_light_min"))
    awake_min = _safe_float(data.get("sleep_awake_min"))
    time_in_bed = _safe_float(data.get("sleep_time_in_bed"))
    garmin_score = _safe_float(data.get("sleep_score"))
    bedtime_str = data.get("sleep_bedtime", "")

    has_data = any(v is not None for v in [total, deep_pct, rem_pct])
    if not has_data:
        return None, "Insufficient data for analysis"

    # Derive effective deep/rem percentages (prefer reported, compute from minutes)
    eff_deep_pct = deep_pct
    if eff_deep_pct is None and deep_min is not None and total and total > 0:
        eff_deep_pct = (deep_min / (total * 60)) * 100
    eff_rem_pct = rem_pct
    if eff_rem_pct is None and rem_min is not None and total and total > 0:
        eff_rem_pct = (rem_min / (total * 60)) * 100

    # Parse bedtime
    bt_hour = _parse_bedtime_hour(bedtime_str)
    effective_bt = None
    if bt_hour is not None:
        effective_bt = bt_hour if bt_hour >= 18 else bt_hour + 24
    is_late_bed = effective_bt is not None and effective_bt >= 25.0  # after 1 AM
    is_very_late = effective_bt is not None and effective_bt >= 25.5  # after 1:30 AM

    # Sleep efficiency (time asleep / time in bed)
    sleep_efficiency = None
    if total is not None and time_in_bed is not None and time_in_bed > 0:
        sleep_efficiency = (total / time_in_bed) * 100

    # --- Evaluate each metric with interpretive context ---

    # 1. Total sleep duration
    if total is not None:
        if total < 5:
            findings.append(("poor", f"{total:.1f}h sleep - severely short, body cannot complete enough 90-min cycles for proper restoration"))
        elif total < 6:
            findings.append(("poor", f"{total:.1f}h sleep - too short for adequate deep+REM; need 7-9h"))
        elif total < 7:
            findings.append(("fair", f"{total:.1f}h - slightly under the 7h minimum; last cycles (REM-heavy) likely cut short"))
        elif total >= 8:
            findings.append(("good", f"{total:.1f}h total - solid duration, enough time for full sleep architecture"))
        else:
            findings.append(("good", f"{total:.1f}h total - adequate"))

    # 2. Deep sleep
    if eff_deep_pct is not None:
        deep_min_val = deep_min if deep_min is not None else (eff_deep_pct / 100 * (total or 0) * 60)
        if eff_deep_pct >= 20:
            findings.append(("good", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - target met, strong glymphatic clearing and physical recovery"))
        elif eff_deep_pct >= 17:
            findings.append(("fair", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - slightly under the 20-25% target; memory consolidation may be reduced"))
        elif eff_deep_pct >= 15:
            findings.append(("poor", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - below threshold; impaired waste clearance and growth hormone release"))
        else:
            findings.append(("poor", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - critically low; brain waste clearing and physical repair significantly compromised"))

    # 3. REM sleep
    if eff_rem_pct is not None:
        rem_min_val = rem_min if rem_min is not None else (eff_rem_pct / 100 * (total or 0) * 60)
        if eff_rem_pct >= 20:
            findings.append(("good", f"REM {eff_rem_pct:.0f}% ({rem_min_val:.0f}min) - target met, emotional processing and creative problem-solving supported"))
        elif eff_rem_pct >= 15:
            findings.append(("fair", f"REM {eff_rem_pct:.0f}% ({rem_min_val:.0f}min) - under 20% target; some emotional processing left incomplete"))
        else:
            findings.append(("poor", f"REM {eff_rem_pct:.0f}% ({rem_min_val:.0f}min) - low; expect reduced emotional regulation and learning consolidation"))

    # 4. HRV
    if hrv is not None:
        if hrv < 30:
            findings.append(("poor", f"HRV {hrv:.0f}ms - very low; body under significant stress or not recovered"))
        elif hrv < 38:
            findings.append(("fair", f"HRV {hrv:.0f}ms - below your 38ms baseline; autonomic recovery incomplete"))
        elif hrv >= 48:
            findings.append(("good", f"HRV {hrv:.0f}ms - excellent parasympathetic recovery"))
        elif hrv >= 42:
            findings.append(("good", f"HRV {hrv:.0f}ms - above target, strong nervous system recovery"))

    # 5. Respiration
    if resp is not None and resp > 18:
        findings.append(("warning", f"Respiration {resp:.0f} breaths/min - elevated (normal 12-16); may indicate stress, congestion, or sleep-disordered breathing"))

    # 6. Bedtime
    if effective_bt is not None:
        if is_very_late:
            findings.append(("poor", f"Bedtime {bedtime_str} - deep sleep concentrates in the first third of the night (10PM-2AM window); sleeping past this window means less time in the deep sleep zone even if total hours are adequate"))
            actions.append(f"aim for bed before midnight to capture the deep sleep window")
        elif effective_bt >= 24.5:  # 12:30-1:00 AM
            findings.append(("fair", f"Bedtime {bedtime_str} - slightly late; you may lose some early-night deep sleep but most architecture intact"))
            actions.append("shift bedtime 30-60min earlier for better deep sleep")
        elif effective_bt <= 23.5:
            findings.append(("good", f"Bedtime {bedtime_str} - well-aligned with circadian deep sleep window"))

    # 7. Sleep cycles
    if cycles is not None:
        if cycles < 3:
            findings.append(("poor", f"Only {cycles:.0f} sleep cycles (target 4-5) - each cycle is ~90min; not enough cycles means incomplete rotation through all sleep stages"))
        elif cycles >= 5:
            findings.append(("good", f"{cycles:.0f} sleep cycles - full architecture completion"))
        elif cycles >= 4:
            findings.append(("good", f"{cycles:.0f} sleep cycles - adequate"))

    # 8. Awakenings
    if awakenings is not None:
        if awakenings > 5:
            findings.append(("poor", f"{awakenings:.0f} awakenings - highly fragmented; each waking resets the cycle, so deep and REM stages keep getting interrupted"))
        elif awakenings > 3:
            findings.append(("fair", f"{awakenings:.0f} awakenings - moderate fragmentation; may have prevented some cycles from completing"))
        elif awakenings <= 1:
            findings.append(("good", f"{awakenings:.0f} awakenings - excellent continuity"))

    # 9. Body battery
    if bb_gained is not None:
        if bb_gained < 20:
            findings.append(("poor", f"BB gained only {bb_gained:.0f} - body barely recovered despite time in bed"))
        elif bb_gained >= 65:
            findings.append(("good", f"BB +{bb_gained:.0f} - strong recovery"))

    # --- Cross-metric pattern detection (the interpretive layer) ---

    # Late bedtime + adequate hours but low deep%
    if is_late_bed and total is not None and total >= 7 and eff_deep_pct is not None and eff_deep_pct < 20:
        insights.append(f"Despite {total:.1f}h in bed, deep sleep was only {eff_deep_pct:.0f}% because the late bedtime ({bedtime_str}) missed the circadian deep sleep window - the body's strongest deep sleep drive is 10PM-2AM regardless of when you fall asleep")

    # Enough hours but few cycles = restlessness / fragmentation
    if total is not None and total >= 7 and cycles is not None and cycles < 3:
        if awakenings is not None and awakenings > 3:
            insights.append(f"Slept {total:.1f}h but only completed {cycles:.0f} cycles due to {awakenings:.0f} awakenings - frequent wake-ups keep resetting the 90-min cycle, preventing progression to deep/REM stages")
        elif light_min is not None and total > 0 and (light_min / (total * 60) * 100) > 55:
            light_pct = light_min / (total * 60) * 100
            insights.append(f"Slept {total:.1f}h but only {cycles:.0f} cycles with unusually high light sleep ({light_pct:.0f}%) - likely restlessness preventing descent into deeper stages; possible causes: caffeine, stress, room temperature, or alcohol")
        else:
            insights.append(f"Slept {total:.1f}h but only {cycles:.0f} cycles - poor sleep architecture despite adequate time; the body struggled to transition between sleep stages")

    # Short sleep + late bedtime = compounding problem
    if total is not None and total < 6 and is_late_bed:
        insights.append(f"Late bedtime + short duration is a double hit: missed the deep sleep window AND cut REM-heavy later cycles")

    # Good deep but low REM (or vice versa) = architectural imbalance
    if eff_deep_pct is not None and eff_rem_pct is not None:
        if eff_deep_pct >= 20 and eff_rem_pct < 15:
            if total is not None and total < 7:
                insights.append(f"Deep sleep is strong but REM is low - likely woke too early and cut the REM-heavy final cycles (REM concentrates in the last third of sleep)")
            else:
                insights.append(f"Deep sleep is strong but REM is low despite adequate hours - unusual pattern; possible early morning light exposure or alarm disruption during REM")
        elif eff_rem_pct >= 20 and eff_deep_pct < 15:
            insights.append(f"REM is healthy but deep sleep is critically low - late bedtime or alcohol consumption can suppress N3 slow-wave sleep specifically while leaving REM intact")

    # High awake time but few recorded awakenings = tossing/turning
    if awake_min is not None and awake_min > 30 and awakenings is not None and awakenings <= 2:
        insights.append(f"{awake_min:.0f}min awake during the night with only {awakenings:.0f} recorded awakenings - likely prolonged restlessness rather than brief wake-ups")

    # Low sleep efficiency
    if sleep_efficiency is not None and sleep_efficiency < 85:
        insights.append(f"Sleep efficiency {sleep_efficiency:.0f}% (spent {time_in_bed:.1f}h in bed but only slept {total:.1f}h) - significant time lost to wakefulness")

    # Low HRV + poor deep = overtraining / stress signal
    if hrv is not None and hrv < 33 and eff_deep_pct is not None and eff_deep_pct < 17:
        insights.append(f"Low HRV ({hrv:.0f}ms) combined with low deep sleep ({eff_deep_pct:.0f}%) suggests the body is under significant physiological stress - possible overtraining, illness, or accumulated sleep debt")

    # --- Compute independent score and discrepancy ---
    ind_score = compute_independent_score(data)
    discrepancy_note = ""
    if ind_score is not None and garmin_score is not None:
        diff = garmin_score - ind_score
        if diff > 20:
            discrepancy_note = f"Garmin scored this {garmin_score:.0f} but architecture suggests ~{ind_score:.0f} - Garmin may be overweighting duration while underweighting stage quality"
        elif diff < -20:
            discrepancy_note = f"Garmin scored this only {garmin_score:.0f} but metrics suggest ~{ind_score:.0f} - the sleep stages were better than Garmin's score implies"

    # --- Determine verdict ---
    severity_counts = {"good": 0, "fair": 0, "poor": 0, "warning": 0}
    for sev, _ in findings:
        if sev in severity_counts:
            severity_counts[sev] += 1

    if severity_counts["poor"] >= 3:
        verdict = "POOR"
    elif severity_counts["poor"] >= 1 and severity_counts["good"] <= severity_counts["poor"]:
        verdict = "POOR"
    elif severity_counts["poor"] == 0 and severity_counts["fair"] <= 1:
        verdict = "GOOD"
    else:
        verdict = "FAIR"

    # --- Generate specific actions based on what went wrong ---
    if not actions:
        if verdict == "POOR" and total is not None and total < 6:
            actions.append("prioritize getting 7+ hours tonight - sleep debt compounds")
        elif verdict == "POOR":
            actions.append("favor light activity today; avoid hard training until recovery improves")
        elif verdict == "FAIR":
            actions.append("functional day - save high-stakes cognitive work for when you feel most alert")
        else:
            actions.append("well-rested - good day for demanding work or hard training")

    if hrv is not None and hrv < 33 and verdict != "GOOD":
        actions.append("skip intense exercise today; walk or light stretching instead")

    # --- Build output string ---
    parts = []

    # Include discrepancy if present
    if discrepancy_note:
        parts.append(discrepancy_note)

    # Key metric findings - prioritize poor, then fair, then good (limit good to 2)
    key_findings = []
    for sev, text in findings:
        if sev in ("poor", "warning"):
            key_findings.append(text)
    for sev, text in findings:
        if sev == "fair":
            key_findings.append(text)
    good_count = 0
    for sev, text in findings:
        if sev == "good" and good_count < 2:
            key_findings.append(text)
            good_count += 1
    parts.extend(key_findings[:4])

    # Cross-metric insights (the most valuable part - limit to 2)
    parts.extend(insights[:2])

    # Actionable recommendation
    parts.append("ACTION: " + "; ".join(actions[:2]))

    body = ". ".join(parts) + "."
    body = body.replace("..", ".").replace("  ", " ").strip()
    analysis = f"{verdict} - {body}"

    return ind_score, analysis


def send_pushover_notification(date_str, ind_score, analysis):
    """Send sleep analysis as a push notification via Pushover (optional)."""
    user_key = os.getenv("PUSHOVER_USER_KEY")
    api_token = os.getenv("PUSHOVER_API_TOKEN")
    if not user_key or not api_token:
        return

    # Extract verdict from "GOOD - body text..." format
    verdict = analysis.split(" - ", 1)[0] if " - " in analysis else ""
    score_str = f" ({ind_score})" if ind_score is not None else ""

    # Format date nicely: "Mar 15"
    try:
        d = date.fromisoformat(date_str)
        date_nice = d.strftime("%b %-d")
    except (ValueError, OSError):
        # Windows strftime doesn't support %-d, fall back to %d
        try:
            d = date.fromisoformat(date_str)
            date_nice = d.strftime("%b %d").replace(" 0", " ")
        except Exception:
            date_nice = date_str

    title = f"Sleep: {date_nice} -- {verdict}{score_str}"

    # Split analysis body into readable lines
    body = analysis.split(" - ", 1)[1] if " - " in analysis else analysis
    # Put each sentence on its own line for readability
    body = body.replace(". ", ".\n")

    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": api_token,
                "user": user_key,
                "title": title,
                "message": body,
                "priority": 0,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"  Pushover: notification sent for {date_str}.")
        else:
            print(f"  Pushover: failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"  Pushover: could not send notification: {e}")


def write_to_sleep_log(wb, target_date, data):
    """Upsert Sleep tab with detailed nightly sleep data."""
    if not data.get("sleep_duration"):
        return

    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        print("  Sleep tab not found — skipping. Run setup_analysis.py first.")
        return

    # Ensure headers are current (adds Notes col B if missing)
    existing_headers = sheet.row_values(1)
    if existing_headers != SLEEP_HEADERS:
        sheet.update(range_name="A1", values=[SLEEP_HEADERS])
        apply_yellow_columns(wb, "Sleep", SLEEP_MANUAL_COLS)

    date_str = str(target_date)
    day_str  = date_to_day(date_str)
    all_dates = sheet.col_values(2)  # Date is now column B

    import re as _re
    if date_str in all_dates:
        row_index = all_dates.index(date_str) + 1
        existing  = sheet.row_values(row_index)
        # Notes = col G (index 6), Cognition = col H (index 7), Cognition Notes = col I (index 8)
        raw_g     = existing[6] if len(existing) > 6 else ""
        # Only keep G if it looks like real notes (not a HH:MM time from old schema)
        notes     = raw_g if raw_g and not _re.match(r'^\d{2}:\d{2}$', raw_g.strip()) else ""
        # Preserve manual Cognition columns (H=7, I=8)
        cognition       = existing[7] if len(existing) > 7 else ""
        cognition_notes = existing[8] if len(existing) > 8 else ""
    else:
        row_index = None
        notes     = ""
        cognition       = ""
        cognition_notes = ""

    # Generate sleep analysis and independent score from the data
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
        cognition,                                     # H  Cognition (1-10) (manual)
        cognition_notes,                               # I  Cognition Notes (manual)
        data.get("sleep_bedtime", ""),                 # J  Bedtime
        data.get("sleep_wake_time", ""),               # K  Wake Time
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
        sheet.update(range_name=f"A{row_index}", values=[row])
        print(f"  Sleep: updated row for {date_str}.")
    else:
        sheet.append_row(row)
        print(f"  Sleep: logged {date_str}.")


def sort_sheet_by_date_desc(wb, sheet_title):
    """
    Sort all data rows (row 2 onward) by column A (date) descending.

    First normalises the Date column to plain text "YYYY-MM-DD" stored with RAW
    mode so that dates written by different code paths (text vs Sheets serial
    numbers) are always the same type.  Mixed types break Google Sheets sorting.
    """
    from datetime import date as _date, timedelta as _td
    try:
        sheet = wb.worksheet(sheet_title)
    except Exception:
        return

    # Read Date column (B) with FORMATTED_VALUE so serials display as "YYYY-MM-DD"
    date_col = sheet.get_values("B:B", value_render_option="FORMATTED_VALUE")
    if not date_col or len(date_col) < 3:
        return

    # Build list of plain-text date values for rows 2+ (skip header at index 0)
    fixed = []
    for cell in date_col[1:]:
        val = cell[0].strip() if cell else ""
        fixed.append([val])  # keep as-is — FORMATTED_VALUE already gives "YYYY-MM-DD"

    if not fixed:
        return

    # Rewrite Date column as plain text so all values are the same type
    last_data_row = len(fixed) + 1   # 1-based, header is row 1
    sheet.update(range_name=f"B2:B{last_data_row}", values=fixed,
                 value_input_option="RAW")

    # Now sort by column B (Date) — all dates are text "YYYY-MM-DD", descending = newest first
    wb.batch_update({"requests": [{
        "sortRange": {
            "range": {
                "sheetId": sheet.id,
                "startRowIndex": 1,         # row 2 (skip header)
                "endRowIndex": last_data_row,
                "startColumnIndex": 0,
                "endColumnIndex": sheet.col_count,
            },
            "sortSpecs": [{"dimensionIndex": 1, "sortOrder": "DESCENDING"}],
        }
    }]})

def apply_yellow_columns(wb, sheet_title, col_indices):
    """Apply light yellow background to entire columns (header included)."""
    try:
        sheet = wb.worksheet(sheet_title)
    except Exception:
        return
    requests = []
    for col_idx in col_indices:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": 0,
                    "startColumnIndex": col_idx,
                    "endColumnIndex": col_idx + 1,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": YELLOW}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
    if requests:
        wb.batch_update({"requests": requests})

def setup_headers(sheet):
    if sheet.row_values(1) != HEADERS:
        sheet.update(range_name="A1", values=[HEADERS])

def upsert_row(sheet, date_str, row):
    """Update existing row for date, or append if not found."""
    all_dates = sheet.col_values(2)  # Date is now column B
    if date_str in all_dates:
        row_index = all_dates.index(date_str) + 1  # 1-based
        sheet.update(range_name=f"A{row_index}", values=[row])
        print(f"  Updated existing row for {date_str}.")
    else:
        sheet.append_row(row)
        print(f"  Appended new row for {date_str}.")

# --- GARMIN ---
_SLEEP_DATA_KEYS = [
    "sleep_duration", "sleep_score", "sleep_bedtime", "sleep_wake_time",
    "sleep_time_in_bed", "sleep_deep_min", "sleep_light_min", "sleep_rem_min",
    "sleep_awake_min", "sleep_deep_pct", "sleep_rem_pct", "sleep_cycles",
    "sleep_awakenings", "sleep_avg_hr", "sleep_avg_respiration",
    "sleep_body_battery_gained", "sleep_feedback",
]

_ACTIVITY_KEYS = [
    "activity_name", "activity_type", "activity_start",
    "activity_distance", "activity_duration", "activity_avg_hr",
    "activity_max_hr", "activity_calories", "activity_elevation",
    "activity_avg_speed", "aerobic_te", "anaerobic_te",
    "zone_1", "zone_2", "zone_3", "zone_4", "zone_5",
]

_STATS_KEYS = [
    "resting_hr", "steps", "total_calories", "active_calories", "bmr_calories",
    "avg_stress", "stress_qualifier", "floors_ascended", "moderate_min",
    "vigorous_min", "bb_at_wake", "bb_high", "bb_low",
]

_FEEDBACK_MAP = {
    "POSITIVE_LONG_AND_DEEP":  "Long & Deep",
    "POSITIVE_LATE_BED_TIME":  "Late Bedtime",
    "NEGATIVE_SHORT":          "Too Short",
    "NEGATIVE_FRAGMENTED":     "Fragmented",
    "NEGATIVE_POOR_QUALITY":   "Poor Quality",
    "NEGATIVE_LATE_BED_TIME":  "Late Bedtime",
}


def _fetch_sleep_data(client, date_iso):
    """Fetch and parse sleep data from Garmin API. Returns dict of sleep keys."""
    data = {}
    try:
        sleep = client.get_sleep_data(date_iso)
        if not (sleep and "dailySleepDTO" in sleep):
            return {k: "" for k in _SLEEP_DATA_KEYS}

        dto    = sleep["dailySleepDTO"]
        scores = dto.get("sleepScores") or {}

        secs = dto.get("sleepTimeSeconds", 0)
        data["sleep_duration"] = round(secs / 3600, 2) if secs else ""

        overall = scores.get("overall", {})
        data["sleep_score"] = overall.get("value", "") if isinstance(overall, dict) else ""

        start_local = dto.get("sleepStartTimestampLocal")
        end_local   = dto.get("sleepEndTimestampLocal")
        data["sleep_bedtime"]   = datetime.fromtimestamp(start_local / 1000, tz=timezone.utc).strftime("%H:%M") if start_local else ""
        data["sleep_wake_time"] = datetime.fromtimestamp(end_local / 1000, tz=timezone.utc).strftime("%H:%M") if end_local   else ""

        if start_local and end_local:
            data["sleep_time_in_bed"] = round((end_local - start_local) / 1000 / 3600, 2)
        else:
            data["sleep_time_in_bed"] = ""

        data["sleep_deep_min"]  = round(dto.get("deepSleepSeconds",  0) / 60, 1)
        data["sleep_light_min"] = round(dto.get("lightSleepSeconds", 0) / 60, 1)
        data["sleep_rem_min"]   = round(dto.get("remSleepSeconds",   0) / 60, 1)
        data["sleep_awake_min"] = round(dto.get("awakeSleepSeconds", 0) / 60, 1)

        def _pct(key):
            v = scores.get(key, {})
            return v.get("value", "") if isinstance(v, dict) else ""
        data["sleep_deep_pct"] = _pct("deepPercentage")
        data["sleep_rem_pct"]  = _pct("remPercentage")

        # Sleep cycles = transitions INTO REM (activityLevel 2.0)
        sleep_levels = sleep.get("sleepLevels", [])
        prev_level = None
        cycle_count = 0
        for s in sleep_levels:
            level = s.get("activityLevel")
            if level == 2.0 and prev_level != 2.0:
                cycle_count += 1
            prev_level = level
        data["sleep_cycles"] = cycle_count or ""

        data["sleep_awakenings"]          = dto.get("awakeCount", "")
        data["sleep_avg_hr"]              = dto.get("avgHeartRate", "")
        data["sleep_avg_respiration"]     = dto.get("averageRespirationValue", "")
        data["sleep_body_battery_gained"] = sleep.get("bodyBatteryChange", "")

        raw_fb = dto.get("sleepScoreFeedback", "")
        data["sleep_feedback"] = _FEEDBACK_MAP.get(raw_fb, raw_fb.replace("_", " ").title() if raw_fb else "")

        print(f"  Sleep: {data['sleep_bedtime']} -> {data['sleep_wake_time']} | "
              f"Deep {data['sleep_deep_min']}m  Light {data['sleep_light_min']}m  "
              f"REM {data['sleep_rem_min']}m  Cycles ~{data['sleep_cycles']}")
    except Exception as e:
        print(f"  Sleep data not available: {e}")
        return {k: "" for k in _SLEEP_DATA_KEYS}
    return data


def _fetch_activity_data(client, date_iso):
    """Fetch and parse activity data from Garmin API. Returns dict of activity keys."""
    data = {}
    try:
        raw = client.get_activities_fordate(date_iso)
        if isinstance(raw, dict):
            activities = raw.get("ActivitiesForDay", {}).get("payload", [])
        else:
            activities = raw or []

        if not activities:
            print("  No activities logged.")
            return {k: "" for k in _ACTIVITY_KEYS}

        act = activities[0]
        activity_id = act.get("activityId")
        detail  = client.get_activity(activity_id)
        summary = detail.get("summaryDTO", {})

        dist  = summary.get("distance", 0)
        dur   = summary.get("duration", 0)
        speed = summary.get("averageSpeed", 0)
        elev  = summary.get("elevationGain", "")

        data["activity_name"]      = act.get("activityName", "")
        data["activity_type"]      = act.get("activityType", {}).get("typeKey", "")
        data["activity_start"]     = act.get("startTimeLocal", "")
        data["activity_distance"]  = round(dist / 1609.344, 2) if dist else ""
        data["activity_duration"]  = round(dur / 60, 1) if dur else ""
        data["activity_avg_hr"]    = summary.get("averageHR", "")
        data["activity_max_hr"]    = summary.get("maxHR", "")
        data["activity_calories"]  = summary.get("calories", "")
        data["activity_elevation"] = round(elev, 1) if elev else ""
        data["activity_avg_speed"] = round(speed * 2.23694, 2) if speed else ""
        data["aerobic_te"]         = summary.get("trainingEffect", "")
        data["anaerobic_te"]       = summary.get("anaerobicTrainingEffect", "")

        # HR Zones + dynamic boundaries
        try:
            zones = client.get_activity_hr_in_timezones(activity_id)
            boundaries = []
            for i in range(5):
                zone_secs = zones[i].get("secsInZone", 0) if i < len(zones) else 0
                data[f"zone_{i+1}"] = round(zone_secs / 60, 1) if zone_secs else 0
                low = int(zones[i].get("zoneLowBoundary", 0)) if i < len(zones) else "?"
                next_low = zones[i+1].get("zoneLowBoundary") if i + 1 < len(zones) else None
                if next_low is not None:
                    boundaries.append(f"Z{i+1}:{low}-{int(next_low) - 1}")
                else:
                    boundaries.append(f"Z{i+1}:{low}+")
            data["zone_ranges"] = ", ".join(boundaries)
        except Exception as ze:
            print(f"  HR zones not available: {ze}")
            for i in range(1, 6):
                data[f"zone_{i}"] = 0
            data["zone_ranges"] = ""

        print(f"  Activity: {data['activity_name']} | {data['activity_duration']} min | "
              f"Avg HR: {data['activity_avg_hr']} | Max HR: {data['activity_max_hr']}")
    except Exception as e:
        print(f"  Activities not available: {e}")
        return {k: "" for k in _ACTIVITY_KEYS}
    return data


def get_garmin_data(today, yesterday):
    print("Connecting to Garmin Connect...")
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()
    print("Connected successfully.")

    t = today.isoformat()
    y = yesterday.isoformat()
    data = {}

    # HRV — from last night (yesterday)
    try:
        hrv = client.get_hrv_data(y)
        if hrv and "hrvSummary" in hrv:
            s = hrv["hrvSummary"]
            data["hrv"]      = s.get("lastNightAvg", "")
            data["hrv_7day"] = s.get("weeklyAvg", "")
        else:
            data["hrv"] = data["hrv_7day"] = ""
    except Exception as e:
        print(f"  HRV not available: {e}")
        data["hrv"] = data["hrv_7day"] = ""

    # Sleep — from last night (yesterday)
    data.update(_fetch_sleep_data(client, y))

    # Daily stats — yesterday
    try:
        stats = client.get_stats(y)
        data["resting_hr"]       = stats.get("restingHeartRate", "")
        data["steps"]            = stats.get("totalSteps", "")
        data["total_calories"]   = stats.get("totalKilocalories", "")
        data["active_calories"]  = stats.get("activeKilocalories", "")
        data["bmr_calories"]     = stats.get("bmrKilocalories", "")
        data["avg_stress"]       = stats.get("averageStressLevel", "")
        raw_sq = stats.get("stressQualifier", "") or ""
        data["stress_qualifier"] = raw_sq.replace("_", " ").title() if raw_sq and raw_sq.upper() != "UNKNOWN" else ""
        data["floors_ascended"]  = round(stats.get("floorsAscended", 0) or 0)
        data["moderate_min"]     = stats.get("moderateIntensityMinutes", "")
        data["vigorous_min"]     = stats.get("vigorousIntensityMinutes", "")
        data["bb_at_wake"]       = stats.get("bodyBatteryAtWakeTime", "")
        data["bb_high"]          = stats.get("bodyBatteryHighestValue", "")
        data["bb_low"]           = stats.get("bodyBatteryLowestValue", "")
    except Exception as e:
        print(f"  Stats not available: {e}")
        for k in _STATS_KEYS:
            data[k] = ""

    # Body battery — today
    try:
        bb = client.get_body_battery(t)
        data["body_battery"] = bb[0].get("charged", "") if bb else ""
    except Exception as e:
        print(f"  Body battery not available: {e}")
        data["body_battery"] = ""

    # Activities — today
    data.update(_fetch_activity_data(client, t))

    return data

# ---------------------------------------------------------------------------
# RAW DATA ARCHIVE — single source of truth for all fetched Garmin data.
# Every key ever returned by _fetch_data / get_garmin_data is stored here.
# The archive is write-once: rows are never overwritten, only appended.
# This lets us rebuild any tab from the archive without calling Garmin again.
# ---------------------------------------------------------------------------
ARCHIVE_TAB = "Raw Data Archive"

ARCHIVE_KEYS = [
    # Core daily
    "hrv", "hrv_7day", "resting_hr", "body_battery", "steps",
    "total_calories", "active_calories", "bmr_calories",
    "avg_stress", "stress_qualifier", "floors_ascended",
    "moderate_min", "vigorous_min",
    "bb_at_wake", "bb_high", "bb_low",
    # Sleep
    "sleep_duration", "sleep_score", "sleep_bedtime", "sleep_wake_time",
    "sleep_time_in_bed", "sleep_deep_min", "sleep_light_min", "sleep_rem_min",
    "sleep_awake_min", "sleep_deep_pct", "sleep_rem_pct", "sleep_cycles",
    "sleep_awakenings", "sleep_avg_hr", "sleep_avg_respiration",
    "sleep_body_battery_gained", "sleep_feedback",
    # Activity
    "activity_name", "activity_type", "activity_start",
    "activity_distance", "activity_duration", "activity_avg_hr", "activity_max_hr",
    "activity_calories", "activity_elevation", "activity_avg_speed",
    "aerobic_te", "anaerobic_te",
    "zone_1", "zone_2", "zone_3", "zone_4", "zone_5",
]
ARCHIVE_HEADERS = ["Day", "Date"] + ARCHIVE_KEYS

STRENGTH_LOG_HEADERS = [
    "Day", "Date", "Muscle Group", "Exercise", "Weight (lbs)", "Reps", "RPE (1-10)", "Notes"
]


def get_or_create_archive_sheet(wb):
    """Get the Raw Data Archive sheet, creating it with headers if missing."""
    try:
        return wb.worksheet(ARCHIVE_TAB)
    except gspread.exceptions.WorksheetNotFound:
        sheet = wb.add_worksheet(
            title=ARCHIVE_TAB,
            rows=5000,
            cols=len(ARCHIVE_HEADERS),
        )
        sheet.update(range_name="A1", values=[ARCHIVE_HEADERS])
        bold_headers(wb, ARCHIVE_TAB)
        print(f"  Created '{ARCHIVE_TAB}' tab.")
        return sheet


def write_to_archive(archive_sheet, date_str, data):
    """Append a date's raw data to the archive. Skips if date already archived."""
    all_dates = archive_sheet.col_values(2)  # Date is column B
    if date_str in all_dates:
        return  # archive is write-once; skip silently for daily runs
    row = [date_to_day(date_str), date_str] + [str(data.get(k, "")) if data.get(k, "") != "" else "" for k in ARCHIVE_KEYS]
    archive_sheet.append_row(row)


def bold_headers(wb, sheet_title):
    """Apply uniform header formatting (bold, 11pt, centered) to row 1 of a given sheet."""
    try:
        sheet = wb.worksheet(sheet_title)
    except Exception:
        return
    wb.batch_update({"requests": [{
        "repeatCell": {
            "range": {
                "sheetId": sheet.id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": 200,
            },
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 11},
            }},
            "fields": "userEnteredFormat(horizontalAlignment,textFormat)",
        }
    }]})

# --- SLEEP COLOR GRADING ---

# Modern, muted colors — legible with black text
_GRADE_GREEN  = {"red": 0.776, "green": 0.918, "blue": 0.765}   # #C6EAC3 soft mint
_GRADE_YELLOW = {"red": 1.0,   "green": 0.929, "blue": 0.706}   # #FFEDB4 warm amber
_GRADE_RED    = {"red": 0.957, "green": 0.733, "blue": 0.718}   # #F4BBB7 soft coral

# Intermediate colors for bedtime discrete bands
_GRADE_LIGHT_GREEN  = {"red": 0.878, "green": 0.945, "blue": 0.843}  # #E0F1D7
_GRADE_ORANGE_RED   = {"red": 0.976, "green": 0.816, "blue": 0.714}  # #F9D0B6


def apply_sleep_color_grading(wb):
    """Apply research-based color grading (green-to-red gradients) to Sleep tab columns.

    Uses 3-point gradient rules for numeric columns and discrete color bands
    for Bedtime (text). Thresholds derived from Perfecting Sleep 2.md.
    Idempotent — clears existing rules before applying.
    """
    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        return

    sid = sheet.id

    # Clear existing conditional format rules on this sheet
    metadata = wb.fetch_sheet_metadata()
    for s in metadata.get("sheets", []):
        if s["properties"]["sheetId"] == sid:
            existing_rules = s.get("conditionalFormats", [])
            if existing_rules:
                # Delete in reverse order to keep indices stable
                del_reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
                            for i in range(len(existing_rules) - 1, -1, -1)]
                wb.batch_update({"requests": del_reqs})
            break

    def _col_range(col_idx):
        return {
            "sheetId": sid,
            "startRowIndex": 1, "endRowIndex": 10000,
            "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
        }

    def _gradient_higher_better(col_idx, red_val, yellow_val, green_val):
        """Gradient where higher numbers are better (green=high, red=low)."""
        return {"addConditionalFormatRule": {
            "rule": {
                "ranges": [_col_range(col_idx)],
                "gradientRule": {
                    "minpoint":  {"color": _GRADE_RED,    "type": "NUMBER", "value": str(red_val)},
                    "midpoint":  {"color": _GRADE_YELLOW, "type": "NUMBER", "value": str(yellow_val)},
                    "maxpoint":  {"color": _GRADE_GREEN,  "type": "NUMBER", "value": str(green_val)},
                },
            },
            "index": 0,
        }}

    def _gradient_lower_better(col_idx, green_val, yellow_val, red_val):
        """Gradient where lower numbers are better (green=low, red=high)."""
        return {"addConditionalFormatRule": {
            "rule": {
                "ranges": [_col_range(col_idx)],
                "gradientRule": {
                    "minpoint":  {"color": _GRADE_GREEN,  "type": "NUMBER", "value": str(green_val)},
                    "midpoint":  {"color": _GRADE_YELLOW, "type": "NUMBER", "value": str(yellow_val)},
                    "maxpoint":  {"color": _GRADE_RED,    "type": "NUMBER", "value": str(red_val)},
                },
            },
            "index": 0,
        }}

    def _bedtime_band(formula, color):
        """Discrete color band for Bedtime column (J) using custom formula."""
        return {"addConditionalFormatRule": {
            "rule": {
                "ranges": [_col_range(hmap["Bedtime"])],  # I = Bedtime
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                    "format": {"backgroundColor": color},
                },
            },
            "index": 0,
        }}

    # Build header index for reference
    hmap = {h: i for i, h in enumerate(SLEEP_HEADERS)}

    requests = [
        # --- Higher = better ---
        # C: Sleep Analysis Score (65=red, 70=yellow, 85=green)
        _gradient_higher_better(hmap["Sleep Analysis Score"], 65, 70, 85),
        # D: Total Sleep hrs (5=red, 7=yellow, 8=green)
        _gradient_higher_better(hmap["Total Sleep (hrs)"], 5, 7, 8),
        # I: Time in Bed hrs (6=red, 7.5=yellow, 8.5=green)
        _gradient_higher_better(hmap["Time in Bed (hrs)"], 6, 7.5, 8.5),
        # J: Deep Sleep min (45=red, 75=yellow, 100=green)
        _gradient_higher_better(hmap["Deep Sleep (min)"], 45, 75, 100),
        # K: Light Sleep min (120=red, 180=yellow, 240=green)
        _gradient_higher_better(hmap["Light Sleep (min)"], 120, 180, 240),
        # L: REM min (45=red, 75=yellow, 100=green)
        _gradient_higher_better(hmap["REM (min)"], 45, 75, 100),
        # N: Deep % (12=red, 18=yellow, 22=green)
        _gradient_higher_better(hmap["Deep %"], 12, 18, 22),
        # O: REM % (12=red, 18=yellow, 22=green)
        _gradient_higher_better(hmap["REM %"], 12, 18, 22),
        # P: Sleep Cycles (2=red, 4=yellow, 5=green)
        _gradient_higher_better(hmap["Sleep Cycles"], 2, 4, 5),
        # T: Overnight HRV ms (30=red, 40=yellow, 48=green)
        _gradient_higher_better(hmap["Overnight HRV (ms)"], 30, 40, 48),
        # U: Body Battery Gained (15=red, 40=yellow, 65=green)
        _gradient_higher_better(hmap["Body Battery Gained"], 15, 40, 65),
        # W: Cognition 1-10 (3=red, 5=yellow, 8=green)
        _gradient_higher_better(hmap["Cognition (1-10)"], 3, 5, 8),

        # --- Lower = better ---
        # M: Awake During Sleep min (15=green, 30=yellow, 60=red)
        _gradient_lower_better(hmap["Awake During Sleep (min)"], 15, 30, 60),
        # Q: Awakenings (1=green, 3=yellow, 6=red)
        _gradient_lower_better(hmap["Awakenings"], 1, 3, 6),
        # R: Avg HR (52=green, 58=yellow, 68=red)
        _gradient_lower_better(hmap["Avg HR"], 52, 58, 68),
        # S: Avg Respiration (15=green, 17=yellow, 20=red)
        _gradient_lower_better(hmap["Avg Respiration"], 15, 17, 20),
    ]

    # --- Bedtime discrete bands (I = Bedtime) ---
    # Bedtime is HH:MM text. Use TIMEVALUE() to compare.
    # Order matters: last added rule is checked first (index 0), so add from least to most specific.
    # We add them in reverse priority so the most specific (red) wins.
    bedtime_rules = [
        # GREEN: 8:00 PM - 10:59 PM (optimal circadian window)
        ('=AND(J2<>"", TIMEVALUE(J2)>=TIMEVALUE("20:00"), TIMEVALUE(J2)<TIMEVALUE("23:00"))', _GRADE_GREEN),
        # LIGHT GREEN: 11:00 PM - 11:59 PM
        ('=AND(J2<>"", TIMEVALUE(J2)>=TIMEVALUE("23:00"))', _GRADE_LIGHT_GREEN),
        # YELLOW: midnight - 12:59 AM
        ('=AND(J2<>"", TIMEVALUE(J2)>=TIMEVALUE("00:00"), TIMEVALUE(J2)<TIMEVALUE("01:00"))', _GRADE_YELLOW),
        # ORANGE-RED: 1:00 AM - 2:00 AM
        ('=AND(J2<>"", TIMEVALUE(J2)>=TIMEVALUE("01:00"), TIMEVALUE(J2)<TIMEVALUE("02:00"))', _GRADE_ORANGE_RED),
        # RED: 2:00 AM - 3:00 AM+
        ('=AND(J2<>"", TIMEVALUE(J2)>=TIMEVALUE("02:00"), TIMEVALUE(J2)<TIMEVALUE("06:00"))', _GRADE_RED),
    ]
    # Add in reverse: last appended gets index 0 (evaluated first). RED added last = highest priority.
    for formula, color in reversed(bedtime_rules):
        requests.append(_bedtime_band(formula, color))

    wb.batch_update({"requests": requests})
    print("  Sleep: color grading applied.")


# Verdict colors for bold rich text in Sleep Analysis column
_VERDICT_COLORS = {
    "GOOD": {"red": 0.15, "green": 0.50, "blue": 0.15},   # green
    "FAIR": {"red": 0.85, "green": 0.55, "blue": 0.0},     # orange
    "POOR": {"red": 0.80, "green": 0.10, "blue": 0.10},    # red
}
_BLACK = {"red": 0, "green": 0, "blue": 0}


def _build_text_format_runs(cell_text, verdict):
    """Build textFormatRuns for a Sleep Analysis cell.

    Formats: verdict word (bold + verdict color), body (normal black),
    ACTION sentence (bold + black).
    """
    runs = [
        {"startIndex": 0, "format": {
            "bold": True,
            "foregroundColorStyle": {"rgbColor": _VERDICT_COLORS[verdict]},
        }},
        {"startIndex": len(verdict), "format": {
            "bold": False,
            "foregroundColorStyle": {"rgbColor": _BLACK},
        }},
    ]

    action_idx = cell_text.find("ACTION:")
    if action_idx != -1:
        runs.append({"startIndex": action_idx, "format": {
            "bold": True,
            "foregroundColorStyle": {"rgbColor": _BLACK},
        }})

    return runs


def apply_sleep_verdict_formatting(wb):
    """Bold and color the verdict word (GOOD/FAIR/POOR) and ACTION sentence in Sleep Analysis cells.

    Uses textFormatRuns to format verdict (bold + green/orange/red) and
    ACTION (bold + warm gold), leaving the body text normal black.
    Idempotent — safe to re-run.
    """
    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        return

    sid = sheet.id
    analysis_col = SLEEP_HEADERS.index("Sleep Analysis")

    all_values = sheet.get_all_values()
    if len(all_values) <= 1:
        return

    rows_data = []
    for row_idx in range(1, len(all_values)):
        cell_text = all_values[row_idx][analysis_col] if analysis_col < len(all_values[row_idx]) else ""
        if not cell_text:
            rows_data.append({"values": [{"userEnteredValue": {"stringValue": ""}}]})
            continue

        verdict = None
        for v in ("GOOD", "FAIR", "POOR"):
            if cell_text.startswith(v):
                verdict = v
                break

        if verdict is None:
            rows_data.append({"values": [{"userEnteredValue": {"stringValue": cell_text}}]})
            continue

        rows_data.append({"values": [{
            "userEnteredValue": {"stringValue": cell_text},
            "textFormatRuns": _build_text_format_runs(cell_text, verdict),
        }]})

    wb.batch_update({"requests": [{
        "updateCells": {
            "range": {
                "sheetId": sid,
                "startRowIndex": 1,
                "endRowIndex": 1 + len(rows_data),
                "startColumnIndex": analysis_col,
                "endColumnIndex": analysis_col + 1,
            },
            "rows": rows_data,
            "fields": "userEnteredValue,textFormatRuns",
        }
    }]})
    print(f"  Sleep: verdict formatting applied ({len(rows_data)} cells).")


# Numeric columns in SLEEP_HEADERS — derived by name so reordering headers won't break this
_SLEEP_NUMERIC_HEADER_NAMES = {
    "Garmin Sleep Score", "Sleep Analysis Score", "Total Sleep (hrs)",
    "Time in Bed (hrs)", "Deep Sleep (min)", "Light Sleep (min)", "REM (min)",
    "Awake During Sleep (min)", "Deep %", "REM %", "Sleep Cycles",
    "Awakenings", "Avg HR", "Avg Respiration", "Overnight HRV (ms)",
    "Body Battery Gained", "Cognition (1-10)",
}
_SLEEP_NUMERIC_COLS = {i for i, h in enumerate(SLEEP_HEADERS) if h in _SLEEP_NUMERIC_HEADER_NAMES}


def fix_sleep_numeric_types(wb):
    """Convert text-number strings to actual numbers in Sleep tab numeric columns.

    Google Sheets gradient conditional formatting only works on cells that contain
    actual numbers, not text that looks like numbers. This function reads all Sleep
    data, parses numeric columns from strings to floats/ints, and writes them back
    with USER_ENTERED so Sheets stores them as numbers. Text columns (date, times,
    analysis, notes, feedback) are left untouched.
    """
    from gspread import Cell

    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        return

    all_rows = sheet.get_all_values()
    if len(all_rows) < 2:
        return

    cells = []
    for row_idx, row in enumerate(all_rows[1:], start=2):  # row 2 onward (1-indexed)
        for col_idx in _SLEEP_NUMERIC_COLS:
            if col_idx >= len(row):
                continue
            val = row[col_idx]
            if val == "":
                continue
            try:
                num = float(val)
                cells.append(Cell(row=row_idx, col=col_idx + 1,
                                  value=int(num) if num == int(num) else num))
            except (ValueError, TypeError):
                continue  # not a number, leave as-is

    if cells:
        # Write in chunks to avoid quota issues (batch of ~5000 cells at a time)
        chunk_size = 5000
        for i in range(0, len(cells), chunk_size):
            sheet.update_cells(cells[i:i + chunk_size], value_input_option="USER_ENTERED")
        print(f"  Sleep: converted {len(cells)} cells to numeric type.")
    else:
        print("  Sleep: all numeric cells already correct.")


# --- GAP DETECTION ---
def find_missing_dates(sheet, lookback_days=7):
    """Check the last N days for any dates missing from the Garmin tab."""
    today = date.today()
    expected = {today - timedelta(days=i) for i in range(1, lookback_days + 1)}
    existing = set()
    for d in sheet.col_values(2)[1:]:  # skip header — Date is column B
        try:
            existing.add(date.fromisoformat(d))
        except (ValueError, TypeError):
            continue
    return sorted(expected - existing)


def build_garmin_row(target_date, data):
    """Build a Garmin tab row from a data dict. Shared by garmin_sync and backfill_history."""
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


def sync_single_date(wb, sheet, target_date, data):
    """Write one date's data to all tabs (Garmin, Session Log, Sleep, Nutrition, Archive)."""
    row = build_garmin_row(target_date, data)
    upsert_row(sheet, str(target_date), row)
    write_to_session_log(wb, target_date, data)
    write_to_sleep_log(wb, target_date, data)
    write_to_nutrition_log(wb, target_date, data)

    archive_sheet = get_or_create_archive_sheet(wb)
    write_to_archive(archive_sheet, str(target_date), data)

    # SQLite local backup (best-effort — never blocks Sheets writes)
    try:
        db = _get_sqlite_db()
        _sqlite_upsert_garmin(db, str(target_date), data)
        _sqlite_upsert_session_log(db, str(target_date), data)
        _sqlite_upsert_sleep(db, str(target_date), data)
        _sqlite_upsert_nutrition(db, str(target_date), data)
        _sqlite_append_archive(db, str(target_date), data)
        db.commit()
    except Exception as e:
        print(f"  SQLite backup warning: {e}")


def sleep_notify_mode():
    """Pull today's sleep data with smart retry, write Sleep tab, send Pushover notification."""
    today = date.today()
    max_attempts = 3
    retry_wait = 1800  # 30 minutes

    for attempt in range(1, max_attempts + 1):
        print(f"\n[Sleep Notify] Attempt {attempt}/{max_attempts}: checking sleep data for {today}...")
        data = get_garmin_data(today, today)

        # Check if key sleep fields are present (indicates server processing is complete)
        has_score = data.get("sleep_score") not in (None, "", 0)
        has_deep = data.get("sleep_deep_pct") not in (None, "", 0)
        has_hrv = data.get("hrv") not in (None, "", 0)
        complete = has_score and has_deep and has_hrv

        if complete:
            print(f"[Sleep Notify] Full sleep data available (score={data.get('sleep_score')}, "
                  f"deep={data.get('sleep_deep_pct')}%, HRV={data.get('hrv')}ms)")
            break

        if attempt < max_attempts:
            missing = []
            if not has_score: missing.append("sleep_score")
            if not has_deep: missing.append("deep_pct")
            if not has_hrv: missing.append("hrv")
            print(f"[Sleep Notify] Incomplete data (missing: {', '.join(missing)}). "
                  f"Retrying in {retry_wait // 60} min...")
            time.sleep(retry_wait)
        else:
            print(f"[Sleep Notify] Data still incomplete after {max_attempts} attempts. "
                  f"Sending with available data.")

    # Write sleep tab and send notification regardless
    wb = get_workbook()
    sheet = wb.worksheet("Sleep")

    # Ensure headers are current
    existing_headers = sheet.row_values(1)
    if existing_headers != SLEEP_HEADERS:
        sheet.update(range_name="A1", values=[SLEEP_HEADERS])

    write_to_sleep_log(wb, today, data)

    # Generate analysis for notification (same logic as write_to_sleep_log uses)
    ind_score, analysis = generate_sleep_analysis(data)
    if analysis:
        send_pushover_notification(str(today), ind_score, analysis)
    else:
        print("[Sleep Notify] No analysis generated (insufficient data).")

    # Sort and format
    bold_headers(wb, "Sleep")
    sort_sheet_by_date_desc(wb, "Sleep")
    apply_sleep_color_grading(wb)

    print(f"\n[Sleep Notify] Done for {today}.")


# --- MAIN ---
def main():
    # Handle --sleep-notify mode before anything else
    if "--sleep-notify" in sys.argv:
        sleep_notify_mode()
        return

    today     = date.today()
    yesterday = today - timedelta(days=1)

    # Flag priority: --date YYYY-MM-DD > --today > default (yesterday)
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        target_date = date.fromisoformat(sys.argv[idx + 1])
        print(f"\nManual refresh -- pulling Garmin data for {target_date}...")
    elif "--today" in sys.argv:
        target_date = today
        print(f"\nManual refresh -- pulling Garmin data for {target_date}...")
    else:
        target_date = yesterday
        print(f"\nPulling Garmin data for {target_date} (sleep/HRV and steps from {target_date})...")

    wb    = get_workbook()
    sheet = get_sheet(wb)
    setup_headers(sheet)

    data = get_garmin_data(target_date, target_date)
    sync_single_date(wb, sheet, target_date, data)

    # Auto-backfill: check last 7 days for gaps (only in default/scheduled mode)
    if "--date" not in sys.argv and "--today" not in sys.argv:
        missing = find_missing_dates(sheet)
        if missing:
            print(f"\n  Gap detected! Backfilling {len(missing)} missed date(s): {[str(d) for d in missing]}")
            for missed_date in missing:
                print(f"  Backfilling {missed_date}...")
                missed_data = get_garmin_data(missed_date, missed_date)
                sync_single_date(wb, sheet, missed_date, missed_data)
                print(f"    -> {missed_date} done (HRV: {missed_data.get('hrv', 'N/A')}, Score: {missed_data.get('sleep_score', 'N/A')})")

    apply_yellow_columns(wb, "Session Log", SESSION_MANUAL_COLS)
    for tab in ["Garmin", "Sleep", "Session Log", "Nutrition", "Raw Data Archive"]:
        bold_headers(wb, tab)
        sort_sheet_by_date_desc(wb, tab)
    apply_sleep_color_grading(wb)
    print(f"\nDone! Data written to Google Sheets for {target_date}")
    print(f"  HRV:   {data.get('hrv', 'N/A')} ms  |  7-day avg: {data.get('hrv_7day', 'N/A')} ms")
    print(f"  Sleep: {data.get('sleep_duration', 'N/A')} hrs  |  Score: {data.get('sleep_score', 'N/A')}")
    print(f"  Steps: {data.get('steps', 'N/A')}")
    print(f"  Calories: {data.get('total_calories', 'N/A')} total | {data.get('active_calories', 'N/A')} active | BMR {data.get('bmr_calories', 'N/A')}")
    print(f"  Stress: {data.get('avg_stress', 'N/A')} ({data.get('stress_qualifier', 'N/A')})  |  Floors: {data.get('floors_ascended', 'N/A')}")

    try:
        _close_sqlite_db()
    except Exception:
        pass

def migrate_sleep_analysis_col():
    """Migration: ensure Sleep tab matches current SLEEP_HEADERS layout.

    Detects the current state and migrates data columns to the target layout:
      A=Date, B=Garmin Sleep Score, C=Sleep Score (independent), D=Sleep Analysis,
      E=Notes, F=Bedtime, ... V=Sleep Feedback  (22 columns)

    Idempotent — safe to re-run. Always regenerates analysis + independent score.
    """
    print("Starting Sleep tab column migration...")
    wb = get_workbook()
    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        print("  Sleep tab not found. Nothing to migrate.")
        return

    all_rows = sheet.get_all_values()
    if not all_rows:
        print("  Sleep tab is empty. Nothing to migrate.")
        return

    headers = all_rows[0]
    target = SLEEP_HEADERS  # 24 columns (A-X)

    # Detect current layout and figure out what data columns we have
    # We need to find where each metric lives in the CURRENT headers
    # so we can remap the data to the NEW layout.
    old_hmap = {h: i for i, h in enumerate(headers)}

    # Mapping from data dict keys to possible header names (old or new)
    METRIC_HEADER_MAP = {
        "sleep_score":               ["Garmin Sleep Score", "Sleep Score"],
        "sleep_bedtime":             ["Bedtime"],
        "sleep_wake_time":           ["Wake Time"],
        "sleep_time_in_bed":         ["Time in Bed (hrs)"],
        "sleep_duration":            ["Total Sleep (hrs)"],
        "sleep_deep_min":            ["Deep Sleep (min)"],
        "sleep_light_min":           ["Light Sleep (min)"],
        "sleep_rem_min":             ["REM (min)"],
        "sleep_awake_min":           ["Awake During Sleep (min)"],
        "sleep_deep_pct":            ["Deep %"],
        "sleep_rem_pct":             ["REM %"],
        "sleep_cycles":              ["Sleep Cycles"],
        "sleep_awakenings":          ["Awakenings"],
        "sleep_avg_hr":              ["Avg HR"],
        "sleep_avg_respiration":     ["Avg Respiration"],
        "hrv":                       ["Overnight HRV (ms)"],
        "sleep_body_battery_gained": ["Body Battery Gained"],
        "sleep_feedback":            ["Sleep Feedback"],
    }

    def _find_old_idx(possible_names):
        for name in possible_names:
            if name in old_hmap:
                return old_hmap[name]
        return None

    # Build remapping: data_key -> old column index
    remap = {}
    for key, names in METRIC_HEADER_MAP.items():
        idx = _find_old_idx(names)
        if idx is not None:
            remap[key] = idx

    # Also find old Notes column
    notes_idx = old_hmap.get("Notes")

    new_headers = target

    print(f"  Current: {len(headers)} cols -> Target: {len(new_headers)} cols")

    updated_count = 0
    new_all_rows = [new_headers]

    for i in range(1, len(all_rows)):
        old_row = all_rows[i]

        def _old_cell(key):
            idx = remap.get(key)
            if idx is not None and idx < len(old_row):
                return old_row[idx]
            return ""

        # Reconstruct data dict from old row
        data = {k: _old_cell(k) for k in METRIC_HEADER_MAP}

        # Generate independent score and analysis
        ind_score, analysis = generate_sleep_analysis(data)

        # Preserve notes
        notes = ""
        if notes_idx is not None and notes_idx < len(old_row):
            notes = old_row[notes_idx]

        # Preserve Cognition columns from old layout (may be at any position)
        cog_idx = old_hmap.get("Cognition (1-10)")
        cog_notes_idx = old_hmap.get("Cognition Notes")
        old_cognition = old_row[cog_idx] if cog_idx is not None and cog_idx < len(old_row) else ""
        old_cog_notes = old_row[cog_notes_idx] if cog_notes_idx is not None and cog_notes_idx < len(old_row) else ""

        # Build new row in target column order
        date_val = old_row[0] if len(old_row) > 0 else ""
        # If Day column already exists, old_row[0] is Day and old_row[1] is Date
        # If not, old_row[0] is Date
        if date_val and date_val.startswith("20"):
            day_val = date_to_day(date_val)
        else:
            day_val = date_val  # already a day abbreviation
            date_val = old_row[1] if len(old_row) > 1 else ""
        new_row = [
            day_val,                                     # A  Day
            date_val,                                    # B  Date
            _old_cell("sleep_score"),                   # C  Garmin Sleep Score
            ind_score if ind_score is not None else "",  # D  Sleep Analysis Score
            _old_cell("sleep_duration"),                 # E  Total Sleep (hrs)
            analysis,                                    # F  Sleep Analysis
            notes,                                       # G  Notes
            old_cognition,                               # H  Cognition (1-10) (preserve)
            old_cog_notes,                               # I  Cognition Notes (preserve)
            _old_cell("sleep_bedtime"),                  # J  Bedtime
            _old_cell("sleep_wake_time"),                # K  Wake Time
            _old_cell("sleep_time_in_bed"),              # L  Time in Bed (hrs)
            _old_cell("sleep_deep_min"),                 # M  Deep Sleep (min)
            _old_cell("sleep_light_min"),                # N  Light Sleep (min)
            _old_cell("sleep_rem_min"),                  # O  REM (min)
            _old_cell("sleep_awake_min"),                # P  Awake During Sleep (min)
            _old_cell("sleep_deep_pct"),                 # Q  Deep %
            _old_cell("sleep_rem_pct"),                  # R  REM %
            _old_cell("sleep_cycles"),                   # S  Sleep Cycles
            _old_cell("sleep_awakenings"),               # T  Awakenings
            _old_cell("sleep_avg_hr"),                   # U  Avg HR
            _old_cell("sleep_avg_respiration"),           # V  Avg Respiration
            _old_cell("hrv"),                            # W  Overnight HRV (ms)
            _old_cell("sleep_body_battery_gained"),      # X  Body Battery Gained
            _old_cell("sleep_feedback"),                 # Y  Sleep Feedback
        ]
        new_all_rows.append(new_row)
        updated_count += 1

    # Parse numeric columns so they are stored as numbers, not text strings
    for row in new_all_rows[1:]:  # skip header
        for col_idx in _SLEEP_NUMERIC_COLS:
            if col_idx >= len(row):
                continue
            val = row[col_idx]
            if val == "":
                continue
            try:
                num = float(val)
                row[col_idx] = int(num) if num == int(num) else num
            except (ValueError, TypeError):
                pass

    # Batch write all rows at once
    end_col = chr(64 + len(new_headers))  # 22 -> V
    range_name = f"A1:{end_col}{len(new_all_rows)}"

    sheet.update(range_name=range_name, values=new_all_rows, value_input_option="RAW")

    # Clear any leftover data beyond new column count (old cols may be wider)
    clear_start_col = chr(65 + len(new_headers))  # first col after our data
    if clear_start_col <= 'Z':
        try:
            sheet.batch_clear([f"{clear_start_col}1:Z{len(new_all_rows)}"])
        except Exception:
            pass  # sheet may not have columns that far

    apply_yellow_columns(wb, "Sleep", SLEEP_MANUAL_COLS)
    bold_headers(wb, "Sleep")
    apply_sleep_color_grading(wb)
    apply_sleep_verdict_formatting(wb)

    print(f"  Migration complete. {updated_count} rows updated.")
    print(f"  New column layout: {len(new_headers)} columns (A-{end_col})")


if __name__ == "__main__":
    if "--fix-sleep-types" in sys.argv:
        wb = get_workbook()
        fix_sleep_numeric_types(wb)
        apply_sleep_color_grading(wb)
        sys.exit(0)
    elif "--migrate-sleep-col" in sys.argv:
        migrate_sleep_analysis_col()
    else:
        main()
