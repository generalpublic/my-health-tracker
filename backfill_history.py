"""
backfill_history.py — One-time historical data backfill for Health Tracker

Pulls all available Garmin data from START_DATE to yesterday and writes it
to Google Sheets (Garmin, Sleep, Session Log, Nutrition tabs).

Safe to re-run: already-synced dates are skipped unless --force is passed.

Usage:
    python backfill_history.py                        # fill from START_DATE to yesterday
    python backfill_history.py --start 2024-01-01     # custom start date
    python backfill_history.py --end 2025-12-31       # custom end date
    python backfill_history.py --force                # re-sync all dates, even existing ones
    python backfill_history.py --dry-run              # show what would be synced, no writes
"""

import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Reuse all logic from garmin_sync.py
from utils import get_workbook, get_sheet
from schema import SESSION_MANUAL_COLS, SLEEP_MANUAL_COLS, NUTRITION_MANUAL_COLS, ARCHIVE_KEYS
from writers import (
    setup_headers, upsert_row, build_garmin_row,
    write_to_session_log, write_to_sleep_log, write_to_nutrition_log,
    get_or_create_archive_sheet, write_to_archive,
)
from sheets_formatting import bold_headers, apply_yellow_columns, sort_sheet_by_date_desc


def _write_date_to_all_tabs(wb, sheet, target_date, data):
    """Write one date's data to Garmin, Session Log, Sleep, and Nutrition tabs."""
    row = build_garmin_row(target_date, data)
    upsert_row(sheet, str(target_date), row)
    write_to_session_log(wb, target_date, data)
    write_to_sleep_log(wb, target_date, data)
    write_to_nutrition_log(wb, target_date, data)

# Earliest date with confirmed Garmin data on this account
START_DATE = date(2023, 3, 4)

# Seconds to wait between each date to avoid Garmin rate-limiting
RATE_LIMIT_SECS = 3.0

# How many consecutive API errors before stopping
MAX_CONSECUTIVE_ERRORS = 5

# Pause every N dates to let quota windows reset
BATCH_SIZE = 50
BATCH_PAUSE_SECS = 45

# Retry settings for quota/rate-limit errors
MAX_RETRIES = 3
RETRY_BASE_SECS = 30  # doubles each retry: 30, 60, 120


def load_archive(archive_sheet):
    """
    Read the Raw Data Archive tab and return a dict of {date_str: data_dict}.
    This lets the backfill loop skip Garmin API calls for dates we already have.
    """
    rows = archive_sheet.get_all_values()
    if len(rows) <= 1:
        return {}
    result = {}
    for row in rows[1:]:
        if not row or len(row) < 2 or not row[1].strip():
            continue
        date_str = row[1].strip()  # Date is column B (index 1)
        data = {}
        for i, key in enumerate(ARCHIVE_KEYS):
            col_i = i + 2  # column 0 is Day, column 1 is Date
            val = row[col_i] if col_i < len(row) else ""
            # Restore numeric types where possible
            if val != "":
                try:
                    data[key] = float(val) if "." in val else int(val)
                except (ValueError, TypeError):
                    data[key] = val
            else:
                data[key] = ""
        result[date_str] = data
    return result


def parse_args():
    args = {"start": START_DATE, "end": date.today() - timedelta(days=1),
            "force": False, "dry_run": False, "restore": False}
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--start" and i + 1 < len(sys.argv):
            args["start"] = date.fromisoformat(sys.argv[i + 1]); i += 2
        elif sys.argv[i] == "--end" and i + 1 < len(sys.argv):
            args["end"] = date.fromisoformat(sys.argv[i + 1]); i += 2
        elif sys.argv[i] == "--force":
            args["force"] = True; i += 1
        elif sys.argv[i] == "--dry-run":
            args["dry_run"] = True; i += 1
        elif sys.argv[i] == "--restore":
            args["restore"] = True; i += 1
        else:
            i += 1
    return args


def get_existing_dates(sheet):
    """Return a set of date strings already in the sheet."""
    all_dates = sheet.col_values(2)  # Date is column B
    return set(d.strip() for d in all_dates[1:] if d.strip())  # skip header


def progress_bar(current, total, start_time, width=35):
    pct  = current / total if total else 0
    done = int(width * pct)
    bar  = "█" * done + "░" * (width - done)
    elapsed = time.time() - start_time
    eta_secs = (elapsed / current * (total - current)) if current > 0 else 0
    eta_str  = f"{int(eta_secs // 60)}m {int(eta_secs % 60)}s" if eta_secs > 0 else "--"
    return f"[{bar}] {current}/{total} ({pct*100:.0f}%)  ETA {eta_str}"


def _apply_final_formatting(wb):
    print("\n\nApplying formatting...")
    apply_yellow_columns(wb, "Session Log", SESSION_MANUAL_COLS)
    apply_yellow_columns(wb, "Sleep", SLEEP_MANUAL_COLS)
    apply_yellow_columns(wb, "Nutrition", NUTRITION_MANUAL_COLS)
    for tab in ["Garmin", "Sleep", "Session Log", "Nutrition", "Raw Data Archive"]:
        bold_headers(wb, tab)
        sort_sheet_by_date_desc(wb, tab)


def main():
    args = parse_args()
    start_date = args["start"]
    end_date   = args["end"]
    force      = args["force"]
    dry_run    = args["dry_run"]
    restore    = args["restore"]

    # Connect to Google Sheets once (needed for all modes)
    print("\nHealth Tracker — Historical Backfill")
    print("Connecting to Google Sheets...")
    wb    = get_workbook()
    sheet = get_sheet(wb)
    setup_headers(sheet)
    archive_sheet = get_or_create_archive_sheet(wb)

    # -----------------------------------------------------------------------
    # RESTORE MODE: rebuild all tabs from archive, zero Garmin calls
    # Usage: python backfill_history.py --restore
    # -----------------------------------------------------------------------
    if restore:
        print("\nRESTORE MODE — rebuilding all tabs from archive (no Garmin calls)...")
        archive_cache = load_archive(archive_sheet)
        total_archived = len(archive_cache)
        print(f"  {total_archived} dates found in archive.\n")
        if not archive_cache:
            print("Archive is empty. Run a normal backfill first.")
            return
        input("  Press Enter to start restore (Ctrl+C to cancel)...")
        synced = 0
        for date_str in sorted(archive_cache.keys()):
            target_date = date.fromisoformat(date_str)
            _write_date_to_all_tabs(wb, sheet, target_date, archive_cache[date_str])
            synced += 1
            print(f"  Restored {date_str}  ({synced}/{total_archived})")
        _apply_final_formatting(wb)
        print(f"\nRestore complete. {synced} dates rebuilt from archive — no Garmin API calls made.")
        return

    # -----------------------------------------------------------------------
    # NORMAL / DRY-RUN MODE
    # -----------------------------------------------------------------------
    # Build full date range
    date_range = []
    d = start_date
    while d <= end_date:
        date_range.append(d)
        d += timedelta(days=1)
    total = len(date_range)

    if dry_run:
        print(f"\n[DRY RUN]  Range : {start_date} to {end_date}  ({total} days)")
        print(f"  Would process {total} dates. Run without --dry-run to execute.")
        return

    print(f"  Range : {start_date} to {end_date}  ({total} days)")
    print(f"  Rate  : {RATE_LIMIT_SECS}s between Garmin requests")

    # Load archive cache — dates already archived skip the Garmin API entirely
    print("Loading archive cache...")
    archive_cache = load_archive(archive_sheet)
    print(f"  {len(archive_cache)} dates already in archive.")

    # Dates not yet in the Garmin tab (always the authoritative skip-check)
    existing_dates = get_existing_dates(sheet) if not force else set()
    to_sync = [d for d in date_range if str(d) not in existing_dates]

    skipped = total - len(to_sync)
    # Split to_sync into archive hits (no API needed) and Garmin fetches
    from_archive = [d for d in to_sync if str(d) in archive_cache]
    needs_garmin = [d for d in to_sync if str(d) not in archive_cache]

    print(f"\n  Already in sheet (skipping)     : {skipped}")
    print(f"  Served from archive (no API)    : {len(from_archive)}")
    print(f"  Need Garmin fetch               : {len(needs_garmin)}")
    if not to_sync:
        print("\nAll dates already synced. Use --force to re-sync.")
        return

    est_garmin_mins = len(needs_garmin) * RATE_LIMIT_SECS / 60
    print(f"  Estimated Garmin fetch time     : ~{est_garmin_mins:.0f} minutes\n")
    input("  Press Enter to start (Ctrl+C to cancel)...")

    synced = 0
    errors = 0
    consecutive_errors = 0
    start_time = time.time()

    # --- Phase 1: serve from archive (fast, no API calls) ---
    if from_archive:
        print(f"\nPhase 1 — writing {len(from_archive)} cached dates from archive...")
        for target_date in from_archive:
            _write_date_to_all_tabs(wb, sheet, target_date, archive_cache[str(target_date)])
            synced += 1
        print(f"  Phase 1 complete — {len(from_archive)} dates written from archive.")

    # --- Phase 2: fetch missing dates from Garmin ---
    if needs_garmin:
        print(f"\nPhase 2 — fetching {len(needs_garmin)} dates from Garmin Connect...")
        from garminconnect import Garmin
        from dotenv import load_dotenv
        import keyring, os
        load_dotenv(Path(__file__).parent / ".env")
        email = os.getenv("GARMIN_EMAIL")
        pw    = keyring.get_password("garmin_connect", email)
        client = Garmin(email, pw)
        client.login()
        print("Connected.\n")

        for i, target_date in enumerate(needs_garmin):
            date_str = str(target_date)

            bar = progress_bar(i, len(needs_garmin), start_time)
            print(f"\r{bar}  {date_str}", end="", flush=True)

            # Batch pause every BATCH_SIZE dates
            if i > 0 and i % BATCH_SIZE == 0:
                print(f"\n  Batch pause {BATCH_PAUSE_SECS}s (quota cooldown)...", flush=True)
                time.sleep(BATCH_PAUSE_SECS)

            success = False
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    data = _fetch_data(client, target_date)

                    # Write to archive FIRST — so data is safe even if a tab write fails
                    write_to_archive(archive_sheet, date_str, data)
                    _write_date_to_all_tabs(wb, sheet, target_date, data)

                    synced += 1
                    consecutive_errors = 0
                    success = True
                    break

                except KeyboardInterrupt:
                    print(f"\n\nInterrupted at {date_str}. {synced} dates synced so far.")
                    _apply_final_formatting(wb)
                    raise SystemExit(0)

                except Exception as e:
                    err_str = str(e).lower()
                    is_quota = any(x in err_str for x in ("quota", "rate", "429", "too many", "limit exceeded"))
                    if is_quota and attempt < MAX_RETRIES:
                        wait = RETRY_BASE_SECS * (2 ** (attempt - 1))
                        print(f"\n  Rate limit ({date_str}), waiting {wait}s, retry {attempt}/{MAX_RETRIES - 1}...", flush=True)
                        time.sleep(wait)
                    else:
                        errors += 1
                        consecutive_errors += 1
                        print(f"\n  Error {date_str}: {e}")
                        break

            if not success and consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"\nStopping: {MAX_CONSECUTIVE_ERRORS} consecutive errors. Re-run to resume.")
                break

            time.sleep(RATE_LIMIT_SECS)

    # Final formatting pass
    _apply_final_formatting(wb)

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed/60:.1f} minutes.")
    print(f"  Synced  : {synced}  (archive: {len(from_archive)}, Garmin: {synced - len(from_archive)})")
    print(f"  Errors  : {errors}")
    print(f"  Skipped : {skipped}")


def _fetch_data(client, target_date):
    """
    Calls the same Garmin API endpoints as garmin_sync.get_garmin_data()
    but takes an already-authenticated client instead of creating a new one.
    This avoids re-logging in for every date during backfill.
    """
    import re as _re
    t = target_date.isoformat()
    data = {}

    # HRV
    try:
        hrv = client.get_hrv_data(t)
        if hrv and "hrvSummary" in hrv:
            s = hrv["hrvSummary"]
            data["hrv"]      = s.get("lastNightAvg", "")
            data["hrv_7day"] = s.get("weeklyAvg", "")
        else:
            data["hrv"] = data["hrv_7day"] = ""
    except Exception:
        data["hrv"] = data["hrv_7day"] = ""

    # Sleep
    _sleep_keys = [
        "sleep_duration","sleep_score","sleep_bedtime","sleep_wake_time",
        "sleep_time_in_bed","sleep_deep_min","sleep_light_min","sleep_rem_min",
        "sleep_awake_min","sleep_deep_pct","sleep_rem_pct","sleep_cycles",
        "sleep_awakenings","sleep_avg_hr","sleep_avg_respiration",
        "sleep_body_battery_gained","sleep_feedback",
    ]
    try:
        sleep = client.get_sleep_data(t)
        if sleep and "dailySleepDTO" in sleep:
            dto    = sleep["dailySleepDTO"]
            scores = dto.get("sleepScores") or {}
            secs   = dto.get("sleepTimeSeconds", 0)
            data["sleep_duration"] = round(secs / 3600, 2) if secs else ""
            overall = scores.get("overall", {})
            data["sleep_score"] = overall.get("value", "") if isinstance(overall, dict) else ""
            start_local = dto.get("sleepStartTimestampLocal")
            end_local   = dto.get("sleepEndTimestampLocal")
            data["sleep_bedtime"]   = datetime.fromtimestamp(start_local/1000, tz=timezone.utc).strftime("%H:%M") if start_local else ""
            data["sleep_wake_time"] = datetime.fromtimestamp(end_local/1000,   tz=timezone.utc).strftime("%H:%M") if end_local   else ""
            data["sleep_time_in_bed"] = round((end_local - start_local)/1000/3600, 2) if start_local and end_local else ""
            data["sleep_deep_min"]  = round(dto.get("deepSleepSeconds",  0)/60, 1)
            data["sleep_light_min"] = round(dto.get("lightSleepSeconds", 0)/60, 1)
            data["sleep_rem_min"]   = round(dto.get("remSleepSeconds",   0)/60, 1)
            data["sleep_awake_min"] = round(dto.get("awakeSleepSeconds", 0)/60, 1)
            def _pct(key):
                v = scores.get(key, {})
                return v.get("value", "") if isinstance(v, dict) else ""
            data["sleep_deep_pct"] = _pct("deepPercentage")
            data["sleep_rem_pct"]  = _pct("remPercentage")
            sleep_levels = sleep.get("sleepLevels", [])
            prev_level = None
            cycle_count = 0
            for s in sleep_levels:
                level = s.get("activityLevel")
                if level == 2.0 and prev_level != 2.0:
                    cycle_count += 1
                prev_level = level
            data["sleep_cycles"] = cycle_count or ""
            data["sleep_awakenings"]      = dto.get("awakeCount", "")
            data["sleep_avg_hr"]          = dto.get("avgHeartRate", "")
            data["sleep_avg_respiration"] = dto.get("averageRespirationValue", "")
            data["sleep_body_battery_gained"] = sleep.get("bodyBatteryChange", "")
            _feedback_map = {
                "POSITIVE_LONG_AND_DEEP": "Long & Deep", "POSITIVE_LATE_BED_TIME": "Late Bedtime",
                "NEGATIVE_SHORT": "Too Short",           "NEGATIVE_FRAGMENTED": "Fragmented",
                "NEGATIVE_POOR_QUALITY": "Poor Quality", "NEGATIVE_LATE_BED_TIME": "Late Bedtime",
            }
            raw_fb = dto.get("sleepScoreFeedback", "")
            data["sleep_feedback"] = _feedback_map.get(raw_fb, raw_fb.replace("_"," ").title() if raw_fb else "")
        else:
            for k in _sleep_keys: data[k] = ""
    except Exception:
        for k in _sleep_keys: data[k] = ""

    # Daily stats
    try:
        stats = client.get_stats(t)
        data["resting_hr"]       = stats.get("restingHeartRate", "")
        data["steps"]            = stats.get("totalSteps", "")
        data["total_calories"]   = stats.get("totalKilocalories", "")
        data["active_calories"]  = stats.get("activeKilocalories", "")
        data["bmr_calories"]     = stats.get("bmrKilocalories", "")
        data["avg_stress"]       = stats.get("averageStressLevel", "")
        raw_sq = stats.get("stressQualifier", "") or ""
        data["stress_qualifier"] = raw_sq.replace("_"," ").title() if raw_sq and raw_sq.upper() != "UNKNOWN" else ""
        data["floors_ascended"]  = round(stats.get("floorsAscended", 0) or 0)
        data["moderate_min"]     = stats.get("moderateIntensityMinutes", "")
        data["vigorous_min"]     = stats.get("vigorousIntensityMinutes", "")
        data["bb_at_wake"]       = stats.get("bodyBatteryAtWakeTime", "")
        data["bb_high"]          = stats.get("bodyBatteryHighestValue", "")
        data["bb_low"]           = stats.get("bodyBatteryLowestValue", "")
    except Exception:
        for k in ["resting_hr","steps","total_calories","active_calories","bmr_calories",
                  "avg_stress","stress_qualifier","floors_ascended","moderate_min",
                  "vigorous_min","bb_at_wake","bb_high","bb_low"]:
            data[k] = ""

    # Body battery
    try:
        bb = client.get_body_battery(t)
        data["body_battery"] = bb[0].get("charged", "") if bb else ""
    except Exception:
        data["body_battery"] = ""

    # Activities
    try:
        raw = client.get_activities_fordate(t)
        activities = raw.get("ActivitiesForDay", {}).get("payload", []) if isinstance(raw, dict) else (raw or [])
        if activities:
            act        = activities[0]
            activity_id = act.get("activityId")
            detail     = client.get_activity(activity_id)
            summary    = detail.get("summaryDTO", {})
            dist  = summary.get("distance", 0)
            dur   = summary.get("duration", 0)
            speed = summary.get("averageSpeed", 0)
            elev  = summary.get("elevationGain", "")
            data["activity_name"]      = act.get("activityName", "")
            data["activity_type"]      = act.get("activityType", {}).get("typeKey", "")
            data["activity_start"]     = act.get("startTimeLocal", "")
            data["activity_distance"]  = round(dist / 1609.344, 2) if dist else ""
            data["activity_duration"]  = round(dur/60, 1)   if dur   else ""
            data["activity_avg_hr"]    = summary.get("averageHR", "")
            data["activity_max_hr"]    = summary.get("maxHR", "")
            data["activity_calories"]  = summary.get("calories", "")
            data["activity_elevation"] = round(elev, 1) if elev else ""
            data["activity_avg_speed"] = round(speed * 2.23694, 2) if speed else ""
            data["aerobic_te"]         = summary.get("trainingEffect", "")
            data["anaerobic_te"]       = summary.get("anaerobicTrainingEffect", "")
            try:
                zones = client.get_activity_hr_in_timezones(activity_id)
                for i in range(5):
                    zone_secs = zones[i].get("secsInZone", 0) if i < len(zones) else 0
                    data[f"zone_{i+1}"] = round(zone_secs/60, 1) if zone_secs else 0
            except Exception:
                for i in range(1, 6): data[f"zone_{i}"] = 0
        else:
            for k in ["activity_name","activity_type","activity_start","activity_distance",
                      "activity_duration","activity_avg_hr","activity_max_hr","activity_calories",
                      "activity_elevation","activity_avg_speed","aerobic_te","anaerobic_te",
                      "zone_1","zone_2","zone_3","zone_4","zone_5"]:
                data[k] = ""
    except Exception:
        for k in ["activity_name","activity_type","activity_start","activity_distance",
                  "activity_duration","activity_avg_hr","activity_max_hr","activity_calories",
                  "activity_elevation","activity_avg_speed","aerobic_te","anaerobic_te",
                  "zone_1","zone_2","zone_3","zone_4","zone_5"]:
            data[k] = ""

    return data


if __name__ == "__main__":
    main()
