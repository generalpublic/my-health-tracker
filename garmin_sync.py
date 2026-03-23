"""
garmin_sync.py — Main orchestrator for daily Garmin health data sync.

Fetches data from Garmin Connect API, writes to Google Sheets (multiple tabs),
backs up to SQLite, runs overall analysis, and sends push notifications.

Usage:
    python garmin_sync.py                    # Sync yesterday (default scheduled mode)
    python garmin_sync.py --today            # Sync today (WARNING: partial data before midnight)
    python garmin_sync.py --date 2026-03-15  # Sync specific date
    python garmin_sync.py --range 2026-03-01 2026-03-15  # Sync date range
    python garmin_sync.py --sleep-notify     # Morning sleep notification mode
    python garmin_sync.py --fix-sleep-types  # Fix Sleep tab numeric types
    python garmin_sync.py --fix-variability   # Recompute bedtime/wake variability for all Sleep rows
    python garmin_sync.py --prep-day                      # Sync yesterday + create today's empty rows
    python garmin_sync.py --prep-day 2026-03-18           # Sync day before + create empty rows for date
    python garmin_sync.py --cleanup-nutrition 2026-03-06  # Delete Nutrition rows on or before date
    python garmin_sync.py --migrate-sleep-col  # Migrate Sleep tab columns
    python garmin_sync.py --probe              # Probe Garmin API for available data sources
    python garmin_sync.py --recalibrate        # Force adaptive weight recalibration

Scheduled tasks (2 triggers):
    12:05 AM  --prep-day       Sync yesterday's finalized data + create today's empty rows
    11:00 AM  --sleep-notify   Sleep analysis + morning health briefing via Pushover
"""

from datetime import date, timedelta
from pathlib import Path
import json
import sys
import time
import traceback

from dotenv import load_dotenv

from utils import get_workbook, get_sheet, _safe_float, date_to_day  # noqa: F401
from schema import (  # noqa: F401
    HEADERS, SLEEP_HEADERS, NUTRITION_HEADERS, STRENGTH_LOG_HEADERS,
    ARCHIVE_HEADERS, ARCHIVE_KEYS, YELLOW,
    NUTRITION_MANUAL_COLS, SESSION_MANUAL_COLS, SLEEP_MANUAL_COLS,
    SL_EFFORT, SL_ENERGY, SL_NOTES, SL_ACTIVITY,
    TAB_ARCHIVE as ARCHIVE_TAB,
)
from garmin_client import get_garmin_data  # direct import kept for backward compat


def _fetch_via_adapter(target_date, yesterday=None):
    """Fetch data using the configured adapter from user_config.json.

    Falls back to direct get_garmin_data() if data_source is "garmin" or unset,
    so existing behavior is unchanged for current users.
    """
    from utils import load_user_config
    source = load_user_config().get("user", {}).get("data_source", "garmin")
    if source == "garmin":
        # Direct call — avoids extra wrapper overhead for the common case
        return get_garmin_data(target_date, yesterday or target_date)
    from data_sources import get_adapter
    adapter = get_adapter(source)
    adapter.authenticate()
    return adapter.fetch_data(target_date, yesterday)
from sleep_analysis import generate_sleep_analysis, compute_independent_score, _parse_bedtime_hour, load_circadian_profile  # noqa: F401
from utils import get_scoring_thresholds as _get_scoring_thresholds
from notifications import send_pushover_notification, compose_briefing_notification
from sheets_formatting import (
    sort_sheet_by_date_desc, auto_resize_rows, bold_headers,
    apply_yellow_columns, apply_sleep_color_grading,
    apply_session_log_color_grading,
    apply_sleep_verdict_formatting, fix_sleep_numeric_types,
    _TEXT_HEAVY_TABS, _SLEEP_NUMERIC_COLS,  # noqa: F401
)
from writers import (
    setup_headers, upsert_row,
    write_to_session_log, write_to_sleep_log, write_to_nutrition_log,
    write_to_daily_log,
    get_or_create_archive_sheet, write_to_archive,
    find_stale_or_missing_dates,
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
from supabase_sync import (
    init_supabase as _init_supabase,
    upsert_garmin as _supa_upsert_garmin,
    upsert_sleep as _supa_upsert_sleep,
    upsert_nutrition as _supa_upsert_nutrition,
    upsert_session_log as _supa_upsert_session_log,
    upsert_overall_analysis as _supa_upsert_overall_analysis,
    upsert_daily_log as _supa_upsert_daily_log,
)

load_dotenv(Path(__file__).parent / ".env")

PENDING_SYNC_PATH = Path(__file__).parent / "pending_sync.json"

# Supabase client — initialized once in main() / sleep_notify_mode()
_supa_client = None


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
            data = _fetch_via_adapter(target_date)
            sync_single_date(wb, sheet, target_date, data)
            print(f"    -> {date_str} synced successfully (SQLite + Sheets)")
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

    # Pre-compute sleep analysis score + text so all stores get it
    if data.get("sleep_duration") and "sleep_analysis_score" not in data:
        try:
            scoring_t = _get_scoring_thresholds()
            circ = load_circadian_profile()
            score, analysis_text, descriptor = generate_sleep_analysis(data, thresholds=scoring_t, circadian_profile=circ)
            if score is not None:
                data["sleep_analysis_score"] = score
            if analysis_text:
                data["sleep_analysis_text"] = analysis_text
            if descriptor:
                data["sleep_descriptor"] = descriptor
        except Exception as e:
            print(f"  Sleep analysis score computation warning: {e}")

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
        print(f"  SQLite write warning: {e}\n{traceback.format_exc()}")

    # 1b. Supabase -- mirrors SQLite writes, failures never break pipeline
    try:
        if _supa_client is not None:
            _supa_upsert_garmin(_supa_client, date_str, data)
            _supa_upsert_sleep(_supa_client, date_str, data)
            _supa_upsert_nutrition(_supa_client, date_str, data)
            _supa_upsert_session_log(_supa_client, date_str, data)
    except Exception as e:
        print(f"  Supabase write warning: {e}\n{traceback.format_exc()}")

    # 1c. Supabase Daily Log -- push existing Sheets habit data so PWA can read it
    try:
        if _supa_client is not None:
            from supabase_sync import push_daily_log_from_sheets
            push_daily_log_from_sheets(_supa_client, wb, date_str)
    except Exception as e:
        print(f"  Supabase daily_log sync warning: {e}")

    # 2. Google Sheets -- retry-safe, queues on failure
    #    Feature flags control which optional tabs get written
    from utils import load_user_config
    _cfg = load_user_config()
    _features = _cfg.get("features", {})
    try:
        from models import from_garmin_api, to_sheets_row
        record = from_garmin_api(data, target_date)
        row = to_sheets_row(record)
        upsert_row(sheet, date_str, row)
        if _features.get("session_log", True):
            write_to_session_log(wb, target_date, data)
        write_to_sleep_log(wb, target_date, data)
        if _features.get("nutrition", True):
            write_to_nutrition_log(wb, target_date, data)
        if _features.get("daily_log", True):
            write_to_daily_log(wb, target_date)

        archive_sheet = get_or_create_archive_sheet(wb)
        write_to_archive(archive_sheet, date_str, data)
    except Exception as e:
        print(f"  Google Sheets write FAILED for {date_str}: {e}\n{traceback.format_exc()}")
        print(f"  Data saved to SQLite. Queuing {date_str} for Sheets retry.")
        _queue_pending_sync(date_str)


# --- Sleep Notify Mode ---

def sleep_notify_mode():
    """Pull today's sleep data with smart retry, write Sleep tab, send notification."""
    global _supa_client
    today = date.today()
    date_str = str(today)
    max_attempts = 3
    retry_wait = 1800  # 30 minutes

    for attempt in range(1, max_attempts + 1):
        print(f"\n[Sleep Notify] Attempt {attempt}/{max_attempts}: checking sleep data for {today}...")
        data = _fetch_via_adapter(today)

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

    # Initialize Supabase client early (used after analysis)
    _supa_client = _init_supabase()

    wb = get_workbook()
    sheet = wb.worksheet("Sleep")

    existing_headers = sheet.row_values(1)
    if existing_headers != SLEEP_HEADERS:
        sheet.update(range_name="A1", values=[SLEEP_HEADERS])

    write_to_sleep_log(wb, today, data)
    scoring_t = _get_scoring_thresholds()
    circ = load_circadian_profile()
    ind_score, analysis, _descriptor = generate_sleep_analysis(data, thresholds=scoring_t, circadian_profile=circ)

    # Inject analysis score into data dict before database writes
    data["sleep_analysis_score"] = ind_score
    data["sleep_analysis_text"] = analysis
    data["sleep_descriptor"] = _descriptor

    # SQLite write (after analysis so score is included)
    try:
        db = _get_sqlite_db()
        _sqlite_upsert_sleep(db, date_str, data)
        _sqlite_upsert_garmin(db, date_str, data)
        db.commit()
    except Exception as e:
        print(f"  SQLite write warning: {e}")

    # Supabase write (after analysis so score is included)
    try:
        if _supa_client is not None:
            _supa_upsert_sleep(_supa_client, date_str, data)
            _supa_upsert_garmin(_supa_client, date_str, data)
    except Exception as e:
        print(f"  Supabase write warning: {e}")

    # Run morning briefing: full overall analysis + send notification
    try:
        from overall_analysis import run_analysis
        result = run_analysis(wb, today)
        # Sync overall analysis to Supabase
        if _supa_client is not None and result:
            try:
                _supa_upsert_overall_analysis(_supa_client, date_str, {
                    "readiness_score": result.get("score"),
                    "readiness_label": result.get("label"),
                    "confidence": result.get("confidence"),
                    "cognitive_energy_assessment": result.get("cognitive_assessment"),
                    "sleep_context": result.get("sleep_context"),
                    "key_insights": "\n".join(f"- {i}" for i in result.get("phone_insights", result.get("insights", []))),
                    "recommendations": "\n".join(f"- {r}" for r in result.get("phone_recommendations", result.get("recommendations", []))),
                    "sleep_need_hrs": result.get("sleep_need", {}).get("sleep_need_hrs") if result.get("sleep_need") else None,
                    "recommended_bedtime": result.get("sleep_need", {}).get("recommended_bedtime") if result.get("sleep_need") else None,
                    "sleep_debt": result.get("sleep_debt"),
                })
            except Exception as e:
                print(f"  Supabase overall_analysis write warning: {e}")
        compose_briefing_notification(str(today), result, data)
        # Sync Daily Log from Sheets so PWA sees morning habits
        if _supa_client is not None:
            try:
                from supabase_sync import push_daily_log_from_sheets
                push_daily_log_from_sheets(_supa_client, wb, date_str)
            except Exception as e:
                print(f"  Supabase daily_log sync warning: {e}")
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
        "sleep_feedback":            ["Sleep Descriptor", "Sleep Feedback"],
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
        scoring_t = _get_scoring_thresholds()
        circ = load_circadian_profile()
        ind_score, analysis, _descriptor = generate_sleep_analysis(data, thresholds=scoring_t, circadian_profile=circ)

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

    from gspread.utils import rowcol_to_a1
    end_col = rowcol_to_a1(1, len(new_headers)).rstrip("1")
    range_name = f"A1:{end_col}{len(new_all_rows)}"
    sheet.update(range_name=range_name, values=new_all_rows, value_input_option="RAW")

    clear_start_col = rowcol_to_a1(1, len(new_headers) + 1).rstrip("1")
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

def _run_full_sync(target_date, do_backfill=True):
    """Full sync pipeline for a single date: fetch -> write all tabs -> analysis -> dashboard.

    Called by both main() (CLI) and prep_day() (midnight scheduled task).
    """
    global _supa_client

    # Initialize Supabase client (None if not configured — all calls become no-ops)
    _supa_client = _init_supabase()

    wb    = get_workbook()
    sheet = get_sheet(wb)
    setup_headers(sheet)

    _retry_pending_syncs(wb, sheet)

    data = _fetch_via_adapter(target_date)
    sync_single_date(wb, sheet, target_date, data)

    # Auto-backfill: check last 7 days for gaps AND stale data
    if do_backfill:
        result = find_stale_or_missing_dates(sheet)
        if result["stale"]:
            for d, steps in result["stale"]:
                print(f"\n  STALE DATA: {d} has only {steps} steps — re-fetching finalized data")
        if result["all"]:
            print(f"\n  Backfilling {len(result['all'])} date(s): "
                  f"{len(result['missing'])} missing + {len(result['stale'])} stale")
            for missed_date in result["all"]:
                print(f"  Backfilling {missed_date}...")
                missed_data = _fetch_via_adapter(missed_date)
                sync_single_date(wb, sheet, missed_date, missed_data)
                print(f"    -> {missed_date} done (HRV: {missed_data.get('hrv', 'N/A')}, "
                      f"Steps: {missed_data.get('steps', 'N/A')}, "
                      f"Score: {missed_data.get('sleep_score', 'N/A')})")

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
        result = None
        for _attempt in range(3):
            try:
                result = run_analysis(wb, target_date)
                break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = 65 * (_attempt + 1)
                    print(f"\n  Rate limit hit during analysis (attempt {_attempt + 1}/3). Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        # Sync overall analysis to Supabase
        if _supa_client is not None and result:
            try:
                _supa_upsert_overall_analysis(_supa_client, str(target_date), {
                    "readiness_score": result.get("score"),
                    "readiness_label": result.get("label"),
                    "confidence": result.get("confidence"),
                    "cognitive_energy_assessment": result.get("cognitive_assessment"),
                    "sleep_context": result.get("sleep_context"),
                    "key_insights": "\n".join(f"- {i}" for i in result.get("phone_insights", result.get("insights", []))),
                    "recommendations": "\n".join(f"- {r}" for r in result.get("phone_recommendations", result.get("recommendations", []))),
                    "sleep_need_hrs": result.get("sleep_need", {}).get("sleep_need_hrs") if result.get("sleep_need") else None,
                    "recommended_bedtime": result.get("sleep_need", {}).get("recommended_bedtime") if result.get("sleep_need") else None,
                    "sleep_debt": result.get("sleep_debt"),
                })
            except Exception as e:
                print(f"  Supabase overall_analysis write warning: {e}\n{traceback.format_exc()}")
    except Exception as e:
        print(f"\n  Overall Analysis skipped (non-fatal): {e}\n{traceback.format_exc()}")

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

    # Auto-calibration check: run after 14+ days if never calibrated
    try:
        from utils import load_user_config
        cfg = load_user_config()
        cal_date = cfg.get("thresholds", {}).get("calibration_date")
        if cal_date is None:
            # Check if we have enough data
            import sqlite3
            _db = sqlite3.connect(str(Path(__file__).parent / "health_tracker.db"))
            _count = _db.execute("SELECT COUNT(*) FROM sleep WHERE overnight_hrv_ms IS NOT NULL").fetchone()[0]
            _db.close()
            if _count >= 14:
                print("\n  14+ days of data available. Running auto-calibration...")
                from calibrate_thresholds import calibrate
                calibrate()
        elif cal_date:
            # Re-calibrate monthly
            from datetime import datetime as _dt
            cal_dt = _dt.strptime(cal_date, "%Y-%m-%d")
            if (_dt.now() - cal_dt).days >= 30:
                print("\n  Monthly recalibration triggered...")
                from calibrate_thresholds import calibrate
                calibrate()
    except Exception as e:
        print(f"\n  Auto-calibration skipped (non-fatal): {e}")

    # Behavioral correlations (weekly or on-demand)
    if "--correlations" in sys.argv or target_date.weekday() == 6:  # Sunday auto-run
        try:
            from behavioral_correlations import run_analysis as run_correlations
            include_lags = "--correlations" in sys.argv  # full lag analysis only on demand
            print("\n  Running behavioral correlation engine...")
            corr_output = run_correlations(include_lags=include_lags)
            top = corr_output.get("top_findings", [])
            if top:
                print(f"  Top finding: {top[0]}")
        except Exception as e:
            print(f"\n  Behavioral correlations skipped (non-fatal): {e}")

    # Weekly validation check (runs on Sundays alongside correlations)
    if target_date.weekday() == 6:  # Sunday
        try:
            from overall_analysis import run_validation
            print("\n  Running weekly validation check...")
            val_result = run_validation(wb, target_date)
            # Alert if prediction quality drops
            if val_result:
                rs = [val_result.get("r_energy"), val_result.get("r_rating")]
                rs = [r for r in rs if r is not None]
                if rs:
                    avg_r = sum(rs) / len(rs)
                    if avg_r < 0.15:
                        try:
                            import requests as _req
                            _user = os.getenv("PUSHOVER_USER_KEY")
                            _token = os.getenv("PUSHOVER_API_TOKEN")
                            if _user and _token:
                                _req.post("https://api.pushover.net/1/messages.json", data={
                                    "token": _token, "user": _user,
                                    "title": "Health Tracker: Validation Alert",
                                    "message": f"Readiness predictions not tracking outcomes (avg r={avg_r:.2f}). "
                                               f"Check Morning Energy/Day Rating logging consistency.",
                                    "priority": 0,
                                }, timeout=10)
                                print("  Pushover: validation alert sent (low prediction quality)")
                        except Exception:
                            pass
        except Exception as e:
            print(f"\n  Validation check skipped (non-fatal): {e}")

    print(f"\nDone! Data written for {target_date}")
    print(f"  HRV:   {data.get('hrv', 'N/A')} ms  |  7-day avg: {data.get('hrv_7day', 'N/A')} ms")
    print(f"  Sleep: {data.get('sleep_duration', 'N/A')} hrs  |  Score: {data.get('sleep_score', 'N/A')}")
    print(f"  Steps: {data.get('steps', 'N/A')}")
    print(f"  Calories: {data.get('total_calories', 'N/A')} total | {data.get('active_calories', 'N/A')} active | BMR {data.get('bmr_calories', 'N/A')}")
    print(f"  Stress: {data.get('avg_stress', 'N/A')} ({data.get('stress_qualifier', 'N/A')})  |  Floors: {data.get('floors_ascended', 'N/A')}")

    # Sync PWA manual entries from Supabase -> SQLite + Sheets
    try:
        from sync_pwa_to_stores import sync_pwa_entries
        sync_pwa_entries(_supa_client, wb)
    except Exception as e:
        print(f"\n  PWA manual sync skipped (non-fatal): {e}")

    try:
        _close_sqlite_db()
    except Exception:
        pass


def main():
    global _supa_client

    if "--sleep-notify" in sys.argv or "--morning-briefing" in sys.argv:
        sleep_notify_mode()
        return

    today     = date.today()
    yesterday = today - timedelta(days=1)

    if "--range" in sys.argv:
        # Range mode: sync each date in the range sequentially
        _supa_client = _init_supabase()
        idx = sys.argv.index("--range")
        range_start = date.fromisoformat(sys.argv[idx + 1])
        range_end = date.fromisoformat(sys.argv[idx + 2])
        print(f"\nRange sync -- pulling Garmin data for {range_start} to {range_end}...")

        wb    = get_workbook()
        sheet = get_sheet(wb)
        setup_headers(sheet)
        _retry_pending_syncs(wb, sheet)

        current = range_start
        count = 0
        while current <= range_end:
            count += 1
            print(f"\n  [{count}] Syncing {current}...")
            data = _fetch_via_adapter(current)
            sync_single_date(wb, sheet, current, data)
            print(f"    -> HRV: {data.get('hrv', 'N/A')} ms | Score: {data.get('sleep_score', 'N/A')}")
            current += timedelta(days=1)
            if current <= range_end:
                time.sleep(3)

        # Post-range formatting
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
        print(f"\nDone! Range sync complete for {range_start} to {range_end}.")
    elif "--probe" in sys.argv:
        from garmin_client import probe_available_data, GARMIN_EMAIL as _probe_email
        from garminconnect import Garmin as _Garmin
        import keyring
        _pw = keyring.get_password("garmin_connect", _probe_email)
        _client = _Garmin(_probe_email, _pw)
        _client.login()
        probe_available_data(_client, yesterday.isoformat())
    elif "--date" in sys.argv:
        idx = sys.argv.index("--date")
        target_date = date.fromisoformat(sys.argv[idx + 1])
        print(f"\nManual refresh -- pulling Garmin data for {target_date}...")
        _run_full_sync(target_date, do_backfill=False)
    elif "--today" in sys.argv:
        target_date = today
        from datetime import datetime
        now = datetime.now()
        if now.hour < 23:  # before 11 PM
            print(f"\n  WARNING: Running --today at {now.strftime('%I:%M %p')}.")
            print(f"  Daily stats (steps, calories, stress) are still accumulating.")
            print(f"  This data WILL be partial. The midnight sync will overwrite with final values.")
            print(f"  To sync finalized data, use: --date {(today - timedelta(days=1)).isoformat()}")
        print(f"\nManual refresh -- pulling Garmin data for {target_date}...")
        _run_full_sync(target_date, do_backfill=False)
    else:
        target_date = yesterday
        print(f"\nPulling Garmin data for {target_date} (sleep/HRV and steps from {target_date})...")
        _run_full_sync(target_date, do_backfill=True)


def fix_all_variability():
    """Recompute bedtime/wake variability for every row in the Sleep tab (batch)."""
    from writers import _time_to_minutes, _rolling_sd_minutes
    import gspread

    wb = get_workbook()
    sheet = wb.worksheet("Sleep")
    all_data = sheet.get_values()
    headers = all_data[0]
    date_ci = headers.index("Date")
    bed_ci = headers.index("Bedtime")
    wake_ci = headers.index("Wake Time")

    # Sort data rows by date descending for lookback
    data_rows = all_data[1:]
    total = len(data_rows)
    print(f"\nRecomputing sleep variability for {total} rows...")

    # Index rows by date for fast lookback
    sorted_rows = sorted(data_rows, key=lambda r: r[date_ci] if len(r) > date_ci else "", reverse=True)
    sorted_dates = [r[date_ci] if len(r) > date_ci else "" for r in sorted_rows]

    cells = []
    supa_updates = []
    for i, row in enumerate(data_rows):
        row_date = row[date_ci] if len(row) > date_ci else ""
        if not row_date:
            continue

        # Find this date in sorted list and collect 7 consecutive entries
        try:
            start_idx = sorted_dates.index(row_date)
        except ValueError:
            continue

        bed_vals = []
        wake_vals = []
        for j in range(start_idx, min(start_idx + 7, len(sorted_rows))):
            sr = sorted_rows[j]
            bed_vals.append(_time_to_minutes(sr[bed_ci] if len(sr) > bed_ci else ""))
            wake_vals.append(_time_to_minutes(sr[wake_ci] if len(sr) > wake_ci else ""))

        bed_sd = _rolling_sd_minutes(bed_vals)
        wake_sd = _rolling_sd_minutes(wake_vals)

        sheet_row = i + 2  # 1-indexed, skip header
        if bed_sd is not None:
            cells.append(gspread.Cell(sheet_row, 10, bed_sd))  # J
        if wake_sd is not None:
            cells.append(gspread.Cell(sheet_row, 11, wake_sd))  # K

        update = {}
        if bed_sd is not None:
            update["bedtime_variability_7d"] = bed_sd
        if wake_sd is not None:
            update["wake_variability_7d"] = wake_sd
        if update:
            supa_updates.append((row_date, update))

        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{total} computed...")

    # Batch write to Sheets
    if cells:
        # Write in chunks of 1000 to stay within API limits
        for chunk_start in range(0, len(cells), 1000):
            chunk = cells[chunk_start:chunk_start + 1000]
            sheet.update_cells(chunk, value_input_option="USER_ENTERED")
            print(f"  Sheets: wrote cells {chunk_start + 1}-{chunk_start + len(chunk)}")

    # Batch update Supabase
    try:
        from supabase_sync import init_supabase
        supa = init_supabase()
        if supa is not None:
            for date_str, update in supa_updates:
                supa.table("sleep").update(update).eq("date", date_str).execute()
            print(f"  Supabase: updated {len(supa_updates)} rows")
    except Exception as e:
        print(f"  Supabase variability backfill skipped: {e}")

    print(f"Done! Variability recomputed for {total} rows.")


def prep_day(target_date=None):
    """Sync yesterday's finalized Garmin data, then create empty rows for today.

    Runs at 12:05 AM via Task Scheduler. Two phases:
      Phase 1: Full sync of the previous day's complete data (all tabs + analysis)
      Phase 2: Create empty Nutrition + Daily Log skeleton rows for manual entry
    """
    if target_date is None:
        target_date = date.today()

    # Phase 1: Sync yesterday's finalized data
    yesterday = target_date - timedelta(days=1)
    print(f"\n=== Phase 1: Syncing finalized data for {yesterday} ===")
    _run_full_sync(yesterday, do_backfill=True)

    # Phase 2: Create empty rows for today
    print(f"\n=== Phase 2: Prepping empty rows for {target_date} ===")
    from reformat_style import apply_weekly_banding_to_tab
    from utils import load_user_config
    _cfg = load_user_config()
    _features = _cfg.get("features", {})
    wb = get_workbook()
    if _features.get("nutrition", True):
        write_to_nutrition_log(wb, target_date, {})  # Empty data -> no calorie values, just skeleton
        sort_sheet_by_date_desc(wb, "Nutrition")
    if _features.get("daily_log", True):
        write_to_daily_log(wb, target_date)
        sort_sheet_by_date_desc(wb, "Daily Log")
    if _features.get("nutrition", True):
        apply_weekly_banding_to_tab(wb, "Nutrition")
    if _features.get("daily_log", True):
        apply_weekly_banding_to_tab(wb, "Daily Log")
    active = []
    if _features.get("nutrition", True):
        active.append("Nutrition")
    if _features.get("daily_log", True):
        active.append("Daily Log")
    print(f"Done — {yesterday} synced, {' + '.join(active) or 'no tabs'} rows ready for {target_date}.")


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
    elif "--backfill-daily-log" in sys.argv:
        print("\n=== Backfilling Daily Log from Sheets to Supabase ===")
        supa = _init_supabase()
        if supa is None:
            print("ERROR: Supabase not configured. Set SUPABASE_URL and key in .env")
            sys.exit(1)
        wb = get_workbook()
        from supabase_sync import backfill_daily_log_from_sheets
        backfill_daily_log_from_sheets(supa, wb)
    else:
        main()
