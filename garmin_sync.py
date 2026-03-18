"""
garmin_sync.py — Main orchestrator for daily Garmin health data sync.

Fetches data from Garmin Connect API, writes to Google Sheets (multiple tabs),
backs up to SQLite, runs overall analysis, and sends push notifications.

Usage:
    python garmin_sync.py                    # Sync yesterday (default scheduled mode)
    python garmin_sync.py --today            # Sync today (WARNING: partial data before 8 PM)
    python garmin_sync.py --date 2026-03-15  # Sync specific date
    python garmin_sync.py --range 2026-03-01 2026-03-15  # Sync date range
    python garmin_sync.py --sleep-notify     # Morning sleep notification mode
    python garmin_sync.py --fix-sleep-types  # Fix Sleep tab numeric types
    python garmin_sync.py --fix-variability   # Recompute bedtime/wake variability for all Sleep rows
    python garmin_sync.py --prep-day                      # Create empty Nutrition + Daily Log rows for today
    python garmin_sync.py --prep-day 2026-03-18           # Create empty rows for specific date
    python garmin_sync.py --cleanup-nutrition 2026-03-06  # Delete Nutrition rows on or before date
    python garmin_sync.py --migrate-sleep-col  # Migrate Sleep tab columns

Scheduled tasks (3 triggers):
    12:00 AM  --prep-day       Empty Nutrition + Daily Log rows for manual entry
    11:00 AM  --sleep-notify   Sleep analysis + morning health briefing via Pushover
     8:00 PM  (default)        Full sync of yesterday's finalized Garmin data
"""

from datetime import date, timedelta
from pathlib import Path
import json
import sys
import time

from dotenv import load_dotenv

from utils import get_workbook, get_sheet, _safe_float, date_to_day  # noqa: F401
from schema import (  # noqa: F401
    HEADERS, SLEEP_HEADERS, NUTRITION_HEADERS, STRENGTH_LOG_HEADERS,
    ARCHIVE_HEADERS, ARCHIVE_KEYS, YELLOW,
    NUTRITION_MANUAL_COLS, SESSION_MANUAL_COLS, SLEEP_MANUAL_COLS,
    SL_EFFORT, SL_ENERGY, SL_NOTES, SL_ACTIVITY,
    TAB_ARCHIVE as ARCHIVE_TAB,
)
from garmin_client import get_garmin_data
from sleep_analysis import generate_sleep_analysis, compute_independent_score, _parse_bedtime_hour  # noqa: F401
from notifications import send_pushover_notification, compose_briefing_notification
from sheets_formatting import (
    sort_sheet_by_date_desc, auto_resize_rows, bold_headers,
    apply_yellow_columns, apply_sleep_color_grading,
    apply_session_log_color_grading,
    apply_sleep_verdict_formatting, fix_sleep_numeric_types,
    _TEXT_HEAVY_TABS, _SLEEP_NUMERIC_COLS,  # noqa: F401
)
from writers import (
    setup_headers, upsert_row, build_garmin_row,
    write_to_session_log, write_to_sleep_log, write_to_nutrition_log,
    write_to_daily_log,
    get_or_create_archive_sheet, write_to_archive, find_missing_dates,
)
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

PENDING_SYNC_PATH = Path(__file__).parent / "pending_sync.json"


# --- Pending Sync Queue (retry logic for failed Sheets writes) ---

def _queue_pending_sync(date_str):
    """Add a date to the pending Sheets sync queue."""
    pending = []
    if PENDING_SYNC_PATH.exists():
        try:
            pending = json.loads(PENDING_SYNC_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pending = []
    if date_str not in pending:
        pending.append(date_str)
        PENDING_SYNC_PATH.write_text(json.dumps(sorted(set(pending))))


def _retry_pending_syncs(wb, sheet):
    """Retry any queued Sheets writes from previous failed syncs."""
    if not PENDING_SYNC_PATH.exists():
        return
    try:
        pending = json.loads(PENDING_SYNC_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if not pending:
        return

    print(f"\n  Retrying {len(pending)} pending Sheets sync(s): {pending}")
    still_pending = []
    for date_str in pending:
        try:
            target_date = date.fromisoformat(date_str)
            data = get_garmin_data(target_date, target_date)
            row = build_garmin_row(target_date, data)
            upsert_row(sheet, date_str, row)
            write_to_session_log(wb, target_date, data)
            write_to_sleep_log(wb, target_date, data)
            write_to_nutrition_log(wb, target_date, data)
            write_to_daily_log(wb, target_date)
            archive_sheet = get_or_create_archive_sheet(wb)
            write_to_archive(archive_sheet, date_str, data)
            print(f"    -> {date_str} synced to Sheets successfully")
        except Exception as e:
            print(f"    -> {date_str} still failing: {e}")
            still_pending.append(date_str)

    if still_pending:
        PENDING_SYNC_PATH.write_text(json.dumps(sorted(set(still_pending))))
    else:
        PENDING_SYNC_PATH.unlink(missing_ok=True)
        print("  All pending syncs completed.")


# --- Core Sync ---

def sync_single_date(wb, sheet, target_date, data):
    """Write one date's data to all tabs. SQLite first, then Sheets with retry queue."""
    date_str = str(target_date)

    # 1. SQLite FIRST -- always succeeds locally
    try:
        db = _get_sqlite_db()
        _sqlite_upsert_garmin(db, date_str, data)
        _sqlite_upsert_session_log(db, date_str, data)
        _sqlite_upsert_sleep(db, date_str, data)
        _sqlite_upsert_nutrition(db, date_str, data)
        _sqlite_append_archive(db, date_str, data)
        db.commit()
    except Exception as e:
        print(f"  SQLite write warning: {e}")

    # 2. Google Sheets -- retry-safe, queues on failure
    try:
        row = build_garmin_row(target_date, data)
        upsert_row(sheet, date_str, row)
        write_to_session_log(wb, target_date, data)
        write_to_sleep_log(wb, target_date, data)
        write_to_nutrition_log(wb, target_date, data)
        write_to_daily_log(wb, target_date)

        archive_sheet = get_or_create_archive_sheet(wb)
        write_to_archive(archive_sheet, date_str, data)
    except Exception as e:
        print(f"  Google Sheets write FAILED for {date_str}: {e}")
        print(f"  Data saved to SQLite. Queuing {date_str} for Sheets retry.")
        _queue_pending_sync(date_str)


# --- Sleep Notify Mode ---

def sleep_notify_mode():
    """Pull today's sleep data with smart retry, write Sleep tab, send notification."""
    today = date.today()
    max_attempts = 3
    retry_wait = 1800  # 30 minutes

    for attempt in range(1, max_attempts + 1):
        print(f"\n[Sleep Notify] Attempt {attempt}/{max_attempts}: checking sleep data for {today}...")
        data = get_garmin_data(today, today)

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

    wb = get_workbook()
    sheet = wb.worksheet("Sleep")

    existing_headers = sheet.row_values(1)
    if existing_headers != SLEEP_HEADERS:
        sheet.update(range_name="A1", values=[SLEEP_HEADERS])

    write_to_sleep_log(wb, today, data)
    ind_score, analysis = generate_sleep_analysis(data)

    # Run morning briefing: full overall analysis + send notification
    try:
        from overall_analysis import run_analysis
        result = run_analysis(wb, today)
        compose_briefing_notification(str(today), result, data)
    except Exception as e:
        print(f"  Morning briefing failed ({e}), falling back to sleep notification.")
        if analysis:
            send_pushover_notification(str(today), ind_score, analysis)
        elif not analysis:
            print("[Sleep Notify] No analysis generated (insufficient data).")

    bold_headers(wb, "Sleep")
    sort_sheet_by_date_desc(wb, "Sleep")
    apply_sleep_color_grading(wb)
    auto_resize_rows(wb, "Sleep")

    print(f"\n[Sleep Notify] Done for {today}.")


# --- Migration ---

def migrate_sleep_analysis_col():
    """Migration: ensure Sleep tab matches current SLEEP_HEADERS layout.

    Idempotent -- safe to re-run. Always regenerates analysis + independent score.
    """
    from sheets_formatting import _SLEEP_NUMERIC_COLS as numeric_cols

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
    target = SLEEP_HEADERS

    old_hmap = {h: i for i, h in enumerate(headers)}

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

    remap = {}
    for key, names in METRIC_HEADER_MAP.items():
        idx = _find_old_idx(names)
        if idx is not None:
            remap[key] = idx

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

        data = {k: _old_cell(k) for k in METRIC_HEADER_MAP}
        ind_score, analysis = generate_sleep_analysis(data)

        notes = ""
        if notes_idx is not None and notes_idx < len(old_row):
            notes = old_row[notes_idx]

        date_val = old_row[0] if len(old_row) > 0 else ""
        if date_val and date_val.startswith("20"):
            day_val = date_to_day(date_val)
        else:
            day_val = date_val
            date_val = old_row[1] if len(old_row) > 1 else ""

        new_row = [
            day_val, date_val,
            _old_cell("sleep_score"),
            ind_score if ind_score is not None else "",
            _old_cell("sleep_duration"), analysis, notes,
            _old_cell("sleep_bedtime"), _old_cell("sleep_wake_time"),
            _old_cell("sleep_time_in_bed"),
            _old_cell("sleep_deep_min"), _old_cell("sleep_light_min"),
            _old_cell("sleep_rem_min"), _old_cell("sleep_awake_min"),
            _old_cell("sleep_deep_pct"), _old_cell("sleep_rem_pct"),
            _old_cell("sleep_cycles"), _old_cell("sleep_awakenings"),
            _old_cell("sleep_avg_hr"), _old_cell("sleep_avg_respiration"),
            _old_cell("hrv"), _old_cell("sleep_body_battery_gained"),
            _old_cell("sleep_feedback"),
        ]
        new_all_rows.append(new_row)
        updated_count += 1

    # Parse numeric columns
    for row in new_all_rows[1:]:
        for col_idx in numeric_cols:
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

    end_col = chr(64 + len(new_headers))
    range_name = f"A1:{end_col}{len(new_all_rows)}"
    sheet.update(range_name=range_name, values=new_all_rows, value_input_option="RAW")

    clear_start_col = chr(65 + len(new_headers))
    if clear_start_col <= 'Z':
        try:
            sheet.batch_clear([f"{clear_start_col}1:Z{len(new_all_rows)}"])
        except Exception:
            pass

    apply_yellow_columns(wb, "Sleep", SLEEP_MANUAL_COLS)
    bold_headers(wb, "Sleep")
    apply_sleep_color_grading(wb)
    apply_sleep_verdict_formatting(wb)

    print(f"  Migration complete. {updated_count} rows updated.")
    print(f"  New column layout: {len(new_headers)} columns (A-{end_col})")


# --- Main ---

def main():
    if "--sleep-notify" in sys.argv or "--morning-briefing" in sys.argv:
        sleep_notify_mode()
        return

    today     = date.today()
    yesterday = today - timedelta(days=1)

    range_mode = False
    if "--range" in sys.argv:
        idx = sys.argv.index("--range")
        range_start = date.fromisoformat(sys.argv[idx + 1])
        range_end = date.fromisoformat(sys.argv[idx + 2])
        range_mode = True
        print(f"\nRange sync -- pulling Garmin data for {range_start} to {range_end}...")
    elif "--date" in sys.argv:
        idx = sys.argv.index("--date")
        target_date = date.fromisoformat(sys.argv[idx + 1])
        print(f"\nManual refresh -- pulling Garmin data for {target_date}...")
    elif "--today" in sys.argv:
        target_date = today
        from datetime import datetime
        now = datetime.now()
        if now.hour < 20:  # before 8 PM
            print(f"\n  WARNING: Running --today at {now.strftime('%I:%M %p')}.")
            print(f"  Daily stats (steps, calories, stress) are still accumulating.")
            print(f"  This data WILL be partial. The 8 PM sync will overwrite with final values.")
            print(f"  To sync finalized data, use: --date {(today - timedelta(days=1)).isoformat()}")
        print(f"\nManual refresh -- pulling Garmin data for {target_date}...")
    else:
        target_date = yesterday
        print(f"\nPulling Garmin data for {target_date} (sleep/HRV and steps from {target_date})...")

    wb    = get_workbook()
    sheet = get_sheet(wb)
    setup_headers(sheet)

    _retry_pending_syncs(wb, sheet)

    if range_mode:
        current = range_start
        count = 0
        while current <= range_end:
            count += 1
            print(f"\n  [{count}] Syncing {current}...")
            data = get_garmin_data(current, current)
            sync_single_date(wb, sheet, current, data)
            print(f"    -> HRV: {data.get('hrv', 'N/A')} ms | Score: {data.get('sleep_score', 'N/A')}")
            current += timedelta(days=1)
            if current <= range_end:
                time.sleep(3)
        target_date = range_end
        data = get_garmin_data(target_date, target_date)
    else:
        data = get_garmin_data(target_date, target_date)
        sync_single_date(wb, sheet, target_date, data)

        # Auto-backfill: check last 7 days for gaps
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
    for tab in ["Garmin", "Sleep", "Session Log", "Nutrition", "Daily Log", "Raw Data Archive"]:
        bold_headers(wb, tab)
        sort_sheet_by_date_desc(wb, tab)
    fix_sleep_numeric_types(wb)
    apply_sleep_color_grading(wb)
    apply_session_log_color_grading(wb)

    from reformat_style import apply_weekly_banding_to_tab
    for tab in ["Garmin", "Sleep", "Session Log", "Nutrition", "Daily Log"]:
        apply_weekly_banding_to_tab(wb, tab)

    for tab in _TEXT_HEAVY_TABS:
        auto_resize_rows(wb, tab)

    try:
        from overall_analysis import run_analysis
        run_analysis(wb, target_date)
    except Exception as e:
        print(f"\n  Overall Analysis skipped (non-fatal): {e}")

    try:
        sys.path.insert(0, str(Path(__file__).parent / "dashboard"))
        from export_dashboard_data import export as export_dashboard
        print("\n  Refreshing dashboard...")
        export_dashboard()
    except Exception as e:
        print(f"\n  Dashboard export skipped (non-fatal): {e}")

    try:
        from verify_formatting import verify_and_repair
        verify_and_repair(wb)
    except Exception as e:
        print(f"\n  Formatting verification skipped (non-fatal): {e}")

    print(f"\nDone! Data written for {target_date}")
    print(f"  HRV:   {data.get('hrv', 'N/A')} ms  |  7-day avg: {data.get('hrv_7day', 'N/A')} ms")
    print(f"  Sleep: {data.get('sleep_duration', 'N/A')} hrs  |  Score: {data.get('sleep_score', 'N/A')}")
    print(f"  Steps: {data.get('steps', 'N/A')}")
    print(f"  Calories: {data.get('total_calories', 'N/A')} total | {data.get('active_calories', 'N/A')} active | BMR {data.get('bmr_calories', 'N/A')}")
    print(f"  Stress: {data.get('avg_stress', 'N/A')} ({data.get('stress_qualifier', 'N/A')})  |  Floors: {data.get('floors_ascended', 'N/A')}")

    try:
        _close_sqlite_db()
    except Exception:
        pass


def fix_all_variability():
    """Recompute bedtime/wake variability for every row in the Sleep tab."""
    from writers import _update_sleep_variability
    wb = get_workbook()
    sheet = wb.worksheet("Sleep")
    all_dates = sheet.col_values(2)
    total = len(all_dates) - 1  # exclude header
    print(f"\nRecomputing sleep variability for {total} rows...")
    for row_idx in range(2, total + 2):
        _update_sleep_variability(sheet, row_idx)
        if (row_idx - 1) % 10 == 0:
            print(f"  {row_idx - 1}/{total} rows processed...")
    print(f"Done! Variability recomputed for {total} rows.")


def prep_day(target_date=None):
    """Create empty Nutrition + Daily Log skeleton rows for a date (default: today).

    Meant to run at midnight so rows are available for manual entry throughout the day.
    The 8 PM sync will upsert Garmin calorie data into the existing Nutrition row.
    """
    if target_date is None:
        target_date = date.today()
    from reformat_style import apply_weekly_banding_to_tab
    print(f"\nPrepping rows for {target_date}...")
    wb = get_workbook()
    write_to_nutrition_log(wb, target_date, {})  # Empty data -> no calorie values, just skeleton
    write_to_daily_log(wb, target_date)
    sort_sheet_by_date_desc(wb, "Nutrition")
    sort_sheet_by_date_desc(wb, "Daily Log")
    apply_weekly_banding_to_tab(wb, "Nutrition")
    apply_weekly_banding_to_tab(wb, "Daily Log")
    print(f"Done — Nutrition + Daily Log rows ready for {target_date}.")


def cleanup_nutrition(cutoff_date_str):
    """Delete Nutrition rows dated on or before cutoff_date_str."""
    wb = get_workbook()
    sheet = wb.worksheet("Nutrition")
    all_data = sheet.get_values()
    headers = all_data[0]
    date_ci = headers.index("Date")

    # Find rows to delete (on or before cutoff)
    rows_to_delete = []
    for i, row in enumerate(all_data[1:], start=2):
        row_date = row[date_ci] if len(row) > date_ci else ""
        if row_date and row_date <= cutoff_date_str:
            rows_to_delete.append((i, row_date))

    if not rows_to_delete:
        print(f"No Nutrition rows found on or before {cutoff_date_str}.")
        return

    print(f"Deleting {len(rows_to_delete)} Nutrition rows (dates {rows_to_delete[-1][1]} to {rows_to_delete[0][1]})...")

    # Delete in reverse order (bottom to top) to preserve indices
    from googleapiclient.discovery import build
    from google.oauth2.service_account import Credentials
    import os
    creds = Credentials.from_service_account_file(
        str(Path(__file__).parent / os.getenv("JSON_KEY_FILE")),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    sheet_id = None
    result = service.spreadsheets().get(spreadsheetId=os.getenv("SHEET_ID")).execute()
    for s in result["sheets"]:
        if s["properties"]["title"] == "Nutrition":
            sheet_id = s["properties"]["sheetId"]
            break

    if sheet_id is None:
        print("  ERROR: Nutrition tab not found.")
        return

    # Build batch delete requests (reverse order)
    requests = []
    for row_idx, _ in sorted(rows_to_delete, key=lambda x: x[0], reverse=True):
        requests.append({
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": row_idx - 1,  # 0-indexed
                    "endIndex": row_idx
                }
            }
        })

    service.spreadsheets().batchUpdate(
        spreadsheetId=os.getenv("SHEET_ID"),
        body={"requests": requests}
    ).execute()

    print(f"  Deleted {len(rows_to_delete)} rows.")

    # Re-apply formatting
    from reformat_style import apply_weekly_banding_to_tab
    sort_sheet_by_date_desc(wb, "Nutrition")
    bold_headers(wb, "Nutrition")
    apply_weekly_banding_to_tab(wb, "Nutrition")
    print("  Reformatted Nutrition tab.")


if __name__ == "__main__":
    if "--fix-sleep-types" in sys.argv:
        wb = get_workbook()
        fix_sleep_numeric_types(wb)
        apply_sleep_color_grading(wb)
        sys.exit(0)
    elif "--fix-variability" in sys.argv:
        fix_all_variability()
    elif "--prep-day" in sys.argv:
        idx = sys.argv.index("--prep-day")
        if len(sys.argv) > idx + 1 and not sys.argv[idx + 1].startswith("--"):
            prep_day(date.fromisoformat(sys.argv[idx + 1]))
        else:
            prep_day()
    elif "--cleanup-nutrition" in sys.argv:
        idx = sys.argv.index("--cleanup-nutrition")
        cutoff = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "2026-03-06"
        cleanup_nutrition(cutoff)
    elif "--migrate-sleep-col" in sys.argv:
        migrate_sleep_analysis_col()
    else:
        main()
