"""
garmin_browser_fetch.py — Fetch Garmin data via Chrome DevTools Protocol.

Connects to a running Chrome instance (with --remote-debugging-port=9222)
that has an active Garmin Connect session. Fetches wellness, sleep, activity,
HRV, and stress data for the target date.

Returns the same flat dict as garmin_client.get_garmin_data() so it plugs
directly into the existing garmin_sync.py pipeline.

Usage:
    # Import from garmin_browser_export.json (already fetched)
    python garmin_browser_fetch.py --import-file garmin_browser_export.json

    # Fetch live from Chrome (must be running with debug port)
    python garmin_browser_fetch.py --date 2026-03-28

    # Fetch and run full pipeline
    python garmin_browser_fetch.py --today --sync
"""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).parent

# Garmin user GUID — extracted from browser session
_USER_GUID = "cb32d87e-3e98-4060-be4c-9438fc804a57"
_CSRF_TOKEN_FILE = PROJECT_DIR / ".garmin_csrf_token"


def _get_csrf_token():
    """Read cached CSRF token or return None."""
    if _CSRF_TOKEN_FILE.exists():
        return _CSRF_TOKEN_FILE.read_text().strip()
    return None


def fetch_via_chrome(date_str):
    """Fetch all Garmin data for a date via Chrome DevTools Protocol.

    Requires Chrome running with --remote-debugging-port=9222.
    Returns raw API responses dict.
    """
    import websocket
    import requests as req

    # Get Chrome debug targets
    try:
        targets = req.get("http://127.0.0.1:9222/json", timeout=5).json()
    except Exception:
        raise RuntimeError(
            "Cannot connect to Chrome on port 9222. "
            "Launch Chrome with: chrome.exe --remote-debugging-port=9222 "
            "--user-data-dir=\"%LOCALAPPDATA%\\Google\\Chrome\\User Data\""
        )

    # Find a Garmin Connect tab, or any tab
    garmin_tab = None
    any_tab = None
    for t in targets:
        if t.get("type") == "page":
            if "garmin" in t.get("url", "").lower():
                garmin_tab = t
                break
            if not any_tab:
                any_tab = t

    target = garmin_tab or any_tab
    if not target:
        raise RuntimeError("No browser tabs found. Open Chrome first.")

    ws_url = target["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=30)

    def evaluate_js(js_code):
        """Execute JS in the browser tab and return the result."""
        msg = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": js_code,
                "awaitPromise": True,
                "returnByValue": True,
            },
        }
        ws.send(json.dumps(msg))
        while True:
            resp = json.loads(ws.recv())
            if resp.get("id") == 1:
                result = resp.get("result", {}).get("result", {})
                if result.get("type") == "object":
                    return result.get("value")
                elif result.get("type") == "string":
                    return result.get("value")
                return result.get("value")

    # Navigate to Garmin Connect if not already there
    current_url = evaluate_js("window.location.href")
    if "connect.garmin.com" not in str(current_url):
        print("  Navigating to Garmin Connect...")
        evaluate_js("window.location.href = 'https://connect.garmin.com/app/daily-summary'")
        time.sleep(8)  # Wait for page load + possible redirects

    # Get CSRF token — it's a request header set by the Garmin JS app,
    # NOT a cookie. Intercept it by reloading the page and watching network requests.
    csrf = None

    # First try cached token
    csrf = _get_csrf_token()

    if not csrf:
        print("  Intercepting CSRF token from network requests...")
        ws.send(json.dumps({"id": 98, "method": "Network.enable"}))
        ws.recv()  # ack
        ws.send(json.dumps({"id": 99, "method": "Page.reload"}))

        start = time.time()
        while time.time() - start < 15 and not csrf:
            try:
                ws.settimeout(1)
                msg = json.loads(ws.recv())
                if msg.get("method") == "Network.requestWillBeSent":
                    headers = msg.get("params", {}).get("request", {}).get("headers", {})
                    for k, v in headers.items():
                        if "csrf" in k.lower():
                            csrf = v
                            break
            except Exception:
                pass

    if not csrf:
        ws.close()
        raise RuntimeError("No CSRF token found. Log into Garmin Connect in Chrome first.")

    # Cache token for future use
    _CSRF_TOKEN_FILE.write_text(csrf)

    uid = _USER_GUID

    # Fetch all endpoints
    js_fetch = f"""
    (async () => {{
        const uid = '{uid}';
        const csrf = '{csrf}';
        const d = '{date_str}';

        function get(url) {{
            return new Promise((resolve) => {{
                const xhr = new XMLHttpRequest();
                xhr.open('GET', url, true);
                xhr.setRequestHeader('Accept', 'application/json');
                xhr.setRequestHeader('Connect-Csrf-Token', csrf);
                xhr.withCredentials = true;
                xhr.onload = () => {{
                    try {{ resolve(JSON.parse(xhr.responseText)); }}
                    catch(e) {{ resolve(null); }}
                }};
                xhr.onerror = () => resolve(null);
                xhr.send();
            }});
        }}

        return {{
            wellness: await get(`/gc-api/usersummary-service/usersummary/daily/${{uid}}?calendarDate=${{d}}`),
            sleep: await get(`/gc-api/wellness-service/wellness/dailySleepData/${{uid}}?date=${{d}}`),
            activities: await get(`/gc-api/activitylist-service/activities/fordailysummary/${{uid}}?calendarDate=${{d}}`),
            heartRate: await get(`/gc-api/wellness-service/wellness/dailyHeartRate?date=${{d}}`),
            hrv: await get(`/gc-api/hrv-service/hrv/${{d}}`),
            stress: await get(`/gc-api/wellness-service/wellness/dailyStress/${{d}}`),
        }};
    }})()
    """

    print(f"  Fetching data for {date_str} via Chrome...")
    result = evaluate_js(js_fetch)
    ws.close()

    if not result:
        raise RuntimeError(f"Failed to fetch data for {date_str}")

    return result


def parse_browser_data(raw, target_date):
    """Convert raw browser API responses into the flat dict format
    expected by garmin_sync.sync_single_date().

    Args:
        raw: dict with keys: wellness, sleep, activities, heartRate, hrv, stress
        target_date: datetime.date

    Returns:
        Flat dict matching garmin_client.get_garmin_data() output.
    """
    data = {}

    # --- HRV ---
    hrv_raw = raw.get("hrv") or {}
    hrv_summary = hrv_raw.get("hrvSummary") or {}
    data["hrv"] = hrv_summary.get("lastNightAvg", "")
    data["hrv_7day"] = hrv_summary.get("weeklyAvg", "")

    # --- Sleep ---
    sleep_raw = raw.get("sleep") or {}
    dto = sleep_raw.get("dailySleepDTO") or {}
    scores = dto.get("sleepScores") or {}

    secs = dto.get("sleepTimeSeconds") or 0
    data["sleep_duration"] = round(secs / 3600, 2) if secs else ""

    overall = scores.get("overall", {})
    data["sleep_score"] = overall.get("value", "") if isinstance(overall, dict) else ""

    # Bedtime/wake from GMT timestamps — same logic as garmin_client.py
    start_gmt = dto.get("sleepStartTimestampGMT")
    end_gmt = dto.get("sleepEndTimestampGMT")
    data["sleep_bedtime"] = datetime.fromtimestamp(start_gmt / 1000).strftime("%H:%M") if start_gmt else ""
    data["sleep_wake_time"] = datetime.fromtimestamp(end_gmt / 1000).strftime("%H:%M") if end_gmt else ""

    if start_gmt and end_gmt:
        data["sleep_time_in_bed"] = round((end_gmt - start_gmt) / 1000 / 3600, 2)
    else:
        data["sleep_time_in_bed"] = ""

    data["sleep_deep_min"] = round((dto.get("deepSleepSeconds") or 0) / 60, 1)
    data["sleep_light_min"] = round((dto.get("lightSleepSeconds") or 0) / 60, 1)
    data["sleep_rem_min"] = round((dto.get("remSleepSeconds") or 0) / 60, 1)
    data["sleep_awake_min"] = round((dto.get("awakeSleepSeconds") or 0) / 60, 1)

    def _pct(key):
        v = scores.get(key, {})
        return v.get("value", "") if isinstance(v, dict) else ""
    data["sleep_deep_pct"] = _pct("deepPercentage")
    data["sleep_rem_pct"] = _pct("remPercentage")

    # Sleep cycles = transitions INTO REM
    sleep_levels = sleep_raw.get("sleepLevels") or []
    prev_level = None
    cycle_count = 0
    for s in sleep_levels:
        level = s.get("activityLevel")
        if level == 2.0 and prev_level != 2.0:
            cycle_count += 1
        prev_level = level
    data["sleep_cycles"] = cycle_count or ""

    data["sleep_awakenings"] = dto.get("awakeCount", "")
    data["sleep_avg_hr"] = dto.get("avgHeartRate", "")
    data["sleep_avg_respiration"] = dto.get("averageRespirationValue", "")
    data["sleep_body_battery_gained"] = sleep_raw.get("bodyBatteryChange", "")

    # Sleep feedback
    _FEEDBACK_MAP = {
        "SLEEP_SCORE_FAIR_INSUFFICIENT_DATA": "Not Enough Data",
        "SLEEP_SCORE_GOOD_NOT_ENOUGH_REM": "Low REM",
        "SLEEP_SCORE_GOOD_NOT_ENOUGH_DEEP": "Low Deep",
        "SLEEP_SCORE_GOOD_SHORT_SLEEP_DURATION": "Too Short",
        "SLEEP_SCORE_EXCELLENT_LONG_AND_DEEP": "Long & Deep",
    }
    raw_fb = dto.get("sleepScoreFeedback", "")
    data["sleep_feedback"] = _FEEDBACK_MAP.get(raw_fb, raw_fb.replace("_", " ").title() if raw_fb else "")

    # --- Daily Stats (from wellness summary) ---
    w = raw.get("wellness") or {}
    data["resting_hr"] = w.get("restingHeartRate", "")
    if data["resting_hr"] == 0:
        data["resting_hr"] = ""  # Sentinel 0 = no data
    data["steps"] = w.get("totalSteps", "")
    data["total_calories"] = w.get("totalKilocalories", "")
    data["active_calories"] = w.get("activeKilocalories", "")
    data["bmr_calories"] = w.get("bmrKilocalories", "")

    avg_stress = w.get("averageStressLevel", "")
    if avg_stress in (-1, -2):
        avg_stress = ""
    data["avg_stress"] = avg_stress

    raw_sq = w.get("stressQualifier", "") or ""
    if raw_sq and raw_sq.upper() != "UNKNOWN":
        data["stress_qualifier"] = raw_sq.replace("_", " ").title()
    elif isinstance(avg_stress, (int, float)) and avg_stress >= 0:
        if avg_stress <= 25:
            data["stress_qualifier"] = "Rest"
        elif avg_stress <= 50:
            data["stress_qualifier"] = "Balanced"
        elif avg_stress <= 75:
            data["stress_qualifier"] = "Stressful"
        else:
            data["stress_qualifier"] = "Very Stressful"
    else:
        data["stress_qualifier"] = ""

    data["floors_ascended"] = round(w.get("floorsAscended", 0) or 0)
    data["moderate_min"] = w.get("moderateIntensityMinutes", "")
    data["vigorous_min"] = w.get("vigorousIntensityMinutes", "")
    data["bb_at_wake"] = w.get("bodyBatteryAtWakeTime", "")
    data["bb_high"] = w.get("bodyBatteryHighestValue", "")
    data["bb_low"] = w.get("bodyBatteryLowestValue", "")

    # Body battery current — from wellness most recent value
    data["body_battery"] = w.get("bodyBatteryMostRecentValue", "")

    # SpO2 — from wellness summary
    data["spo2_avg"] = w.get("averageSpo2", "")
    data["spo2_min"] = w.get("lowestSpo2", "")

    # --- Activities ---
    activities = raw.get("activities") or []
    if isinstance(activities, dict):
        activities = activities.get("ActivitiesForDay", {}).get("payload", [])

    if activities:
        act = activities[0]
        summary = act.get("summaryDTO", act)

        dist = summary.get("distance", 0) or act.get("distance", 0)
        dur = summary.get("duration", 0) or act.get("duration", 0)
        speed = summary.get("averageSpeed", 0) or act.get("averageSpeed", 0)
        elev = summary.get("elevationGain", "") or act.get("elevationGain", "")

        data["activity_name"] = act.get("activityName", "")
        data["activity_type"] = act.get("activityType", {}).get("typeKey", "") if isinstance(act.get("activityType"), dict) else act.get("activityType", "")
        data["activity_start"] = act.get("startTimeLocal", "")
        data["activity_distance"] = round(dist / 1609.344, 2) if dist else ""
        data["activity_duration"] = round(dur / 60, 1) if dur else ""
        data["activity_avg_hr"] = summary.get("averageHR", "") or act.get("averageHR", "")
        data["activity_max_hr"] = summary.get("maxHR", "") or act.get("maxHR", "")
        data["activity_calories"] = summary.get("calories", "") or act.get("calories", "")
        data["activity_elevation"] = round(float(elev), 1) if elev else ""
        data["activity_avg_speed"] = round(speed * 2.23694, 2) if speed else ""
        data["aerobic_te"] = summary.get("trainingEffect", "") or act.get("aerobicTrainingEffect", "")
        data["anaerobic_te"] = summary.get("anaerobicTrainingEffect", "") or act.get("anaerobicTrainingEffect", "")

        # HR zones — may not be in the summary endpoint, set to 0
        for i in range(1, 6):
            data[f"zone_{i}"] = 0
        data["zone_ranges"] = ""
    else:
        for k in ("activity_name", "activity_type", "activity_start",
                   "activity_distance", "activity_duration", "activity_avg_hr",
                   "activity_max_hr", "activity_calories", "activity_elevation",
                   "activity_avg_speed", "aerobic_te", "anaerobic_te"):
            data[k] = ""
        for i in range(1, 6):
            data[f"zone_{i}"] = 0
        data["zone_ranges"] = ""

    return data


def import_from_file(filepath):
    """Load previously exported browser data from a JSON file.

    Returns dict of {date_str: raw_api_responses}.
    """
    with open(filepath) as f:
        return json.load(f)


def sync_dates_from_file(filepath):
    """Import browser-exported data and run it through the full pipeline."""
    from garmin_sync import (
        sync_single_date, setup_headers, bold_headers, sort_sheet_by_date_desc,
        fix_sleep_numeric_types, apply_sleep_color_grading,
        apply_session_log_color_grading, apply_yellow_columns,
        auto_resize_rows, SESSION_MANUAL_COLS, _TEXT_HEAVY_TABS,
    )
    from utils import get_workbook, get_sheet

    raw_by_date = import_from_file(filepath)
    wb = get_workbook()
    sheet = get_sheet(wb)
    setup_headers(sheet)

    # Initialize Supabase so sync_single_date() writes to cloud
    import garmin_sync
    garmin_sync._supa_client = garmin_sync._init_supabase()

    for date_str, raw in sorted(raw_by_date.items()):
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        print(f"\n--- Importing {date_str} ---")
        data = parse_browser_data(raw, target_date)

        # Print summary
        print(f"  HRV: {data['hrv']} | Sleep: {data['sleep_score']} | "
              f"Steps: {data['steps']} | Stress: {data['avg_stress']} ({data['stress_qualifier']})")
        if data["activity_name"]:
            print(f"  Activity: {data['activity_name']} | {data['activity_duration']} min")

        sync_single_date(wb, sheet, target_date, data)
        print(f"  -> {date_str} synced to Sheets + SQLite")

    # Post-sync: formatting, sorting, analysis, dashboard
    print("\nRunning post-sync tasks...")
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

    # Run analysis for ALL imported dates (oldest first for correct baselines)
    from overall_analysis import run_analysis
    for date_str in sorted(raw_by_date.keys()):
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            print(f"\n  Running overall analysis for {date_str}...")
            result = run_analysis(wb, target_date)
            print(f"    Score: {result.get('score')}, Label: {result.get('label')}")
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                import time
                print(f"    Rate limited. Waiting 65s...")
                time.sleep(65)
                try:
                    result = run_analysis(wb, target_date)
                    print(f"    Score: {result.get('score')}, Label: {result.get('label')}")
                except Exception as e2:
                    print(f"    Analysis failed after retry: {e2}")
            else:
                print(f"    Analysis skipped (non-fatal): {e}")

    # Dashboard export
    try:
        sys.path.insert(0, str(PROJECT_DIR / "dashboard"))
        from export_dashboard_data import export as export_dashboard
        print("  Refreshing dashboard...")
        export_dashboard()
    except Exception as e:
        print(f"  Dashboard export skipped (non-fatal): {e}")

    # Verify formatting
    try:
        from verify_formatting import verify_and_repair
        verify_and_repair(wb)
    except Exception as e:
        print(f"  Formatting verification skipped (non-fatal): {e}")

    print("\nAll dates imported successfully!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch Garmin data via Chrome browser")
    parser.add_argument("--import-file", help="Import from previously exported JSON file")
    parser.add_argument("--date", help="Fetch a specific date (YYYY-MM-DD)")
    parser.add_argument("--today", action="store_true", help="Fetch today's data")
    parser.add_argument("--sync", action="store_true", help="Run full sync pipeline after fetch")
    args = parser.parse_args()

    if args.import_file:
        sync_dates_from_file(args.import_file)
    elif args.date or args.today:
        target = args.date or datetime.now().strftime("%Y-%m-%d")
        raw = fetch_via_chrome(target)
        target_date = datetime.strptime(target, "%Y-%m-%d").date()
        data = parse_browser_data(raw, target_date)

        if args.sync:
            # Write to a temp file and use sync_dates_from_file
            tmp = {target: raw}
            tmp_path = PROJECT_DIR / "_tmp_browser_fetch.json"
            with open(tmp_path, "w") as f:
                json.dump(tmp, f)
            sync_dates_from_file(str(tmp_path))
            tmp_path.unlink(missing_ok=True)
        else:
            print(json.dumps(data, indent=2, default=str))
    else:
        parser.print_help()
