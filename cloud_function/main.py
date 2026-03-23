"""
cloud_function/main.py — Google Cloud Function for Health Tracker pull-to-refresh.

HTTP trigger that fetches Garmin data and writes to Supabase.
Reuses existing garmin_client.py, supabase_sync.py, and sleep_analysis.py.

Deployment:
    gcloud functions deploy health-refresh \
        --runtime python312 \
        --trigger-http \
        --allow-unauthenticated \
        --set-secrets 'GARMIN_PASSWORD=garmin-password:latest' \
        --set-env-vars 'GARMIN_EMAIL=...,SUPABASE_URL=...' \
        --set-secrets 'SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest' \
        --source cloud_function/ \
        --entry-point health_refresh \
        --memory 256MB \
        --timeout 60s \
        --region us-east1

Environment variables (set via GCP Secret Manager or --set-env-vars):
    GARMIN_EMAIL              — Garmin Connect email
    GARMIN_PASSWORD           — Garmin Connect password (from Secret Manager)
    SUPABASE_URL              — Supabase project URL
    SUPABASE_SERVICE_ROLE_KEY — Supabase service role key (from Secret Manager)
    REFRESH_SECRET            — Shared secret for request authentication
    ALLOWED_ORIGINS           — Comma-separated allowed CORS origins
                                (e.g. "https://user.github.io,http://localhost:8000")
"""

import json
import os
import sys
import traceback
from datetime import datetime, timedelta

# Add parent directory to path so we can import project modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _check_auth(request):
    """Validate request via shared secret header.

    Returns None if authorized, or an error response tuple if not.
    """
    expected = os.environ.get("REFRESH_SECRET")
    if not expected:
        return (json.dumps({"error": "REFRESH_SECRET not configured — refusing all requests"}), 500,
                {"Content-Type": "application/json"})

    provided = request.headers.get("X-Refresh-Secret", "")
    if not provided or provided != expected:
        return (json.dumps({"error": "Unauthorized"}), 401,
                {"Content-Type": "application/json"})
    return None


# ---------------------------------------------------------------------------
# Rate limiting (simple in-memory, resets on cold start)
# ---------------------------------------------------------------------------

_last_refresh = {}
_RATE_LIMIT_SECONDS = 300  # 5 minutes


def _check_rate_limit(request):
    """Simple rate limiting per source IP. Returns error tuple or None."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    ip = ip.split(",")[0].strip()

    now = datetime.utcnow()
    last = _last_refresh.get(ip)
    if last and (now - last).total_seconds() < _RATE_LIMIT_SECONDS:
        remaining = _RATE_LIMIT_SECONDS - int((now - last).total_seconds())
        return (json.dumps({
            "error": "Rate limited",
            "retry_after_seconds": remaining
        }), 429, {"Content-Type": "application/json"})

    _last_refresh[ip] = now
    return None


# ---------------------------------------------------------------------------
# Garmin fetch (replaces keyring with env var)
# ---------------------------------------------------------------------------

def _fetch_garmin_data(date_str):
    """Fetch Garmin data for a date, using env var for password instead of keyring.

    Args:
        date_str: "YYYY-MM-DD" target date

    Returns:
        dict with all Garmin metrics (same shape as garmin_client.get_garmin_data)
    """
    from garminconnect import Garmin

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError("GARMIN_EMAIL and GARMIN_PASSWORD must be set")

    client = Garmin(email, password)
    client.login()

    from datetime import date
    target = date.fromisoformat(date_str)
    target_iso = target.isoformat()

    data = {}

    # HRV
    try:
        hrv = client.get_hrv_data(target_iso)
        if hrv and "hrvSummary" in hrv:
            s = hrv["hrvSummary"]
            data["hrv"] = s.get("lastNightAvg", "")
            data["hrv_7day"] = s.get("weeklyAvg", "")
        else:
            data["hrv"] = data["hrv_7day"] = ""
    except Exception:
        data["hrv"] = data["hrv_7day"] = ""

    # Sleep
    try:
        from garmin_client import _fetch_sleep_data
        data.update(_fetch_sleep_data(client, target_iso))
    except Exception as e:
        print(f"Sleep fetch failed: {e}")
        from garmin_client import _SLEEP_DATA_KEYS
        for k in _SLEEP_DATA_KEYS:
            data[k] = ""

    # Daily stats
    try:
        stats = client.get_stats(target_iso)
        data["resting_hr"] = stats.get("restingHeartRate", "")
        data["steps"] = stats.get("totalSteps", "")
        data["total_calories"] = stats.get("totalKilocalories", "")
        data["active_calories"] = stats.get("activeKilocalories", "")
        data["bmr_calories"] = stats.get("bmrKilocalories", "")
        avg_stress = stats.get("averageStressLevel", "")
        data["avg_stress"] = avg_stress
        raw_sq = stats.get("stressQualifier", "") or ""
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
        data["floors_ascended"] = round(stats.get("floorsAscended", 0) or 0)
        data["moderate_min"] = stats.get("moderateIntensityMinutes", "")
        data["vigorous_min"] = stats.get("vigorousIntensityMinutes", "")
        data["bb_at_wake"] = stats.get("bodyBatteryAtWakeTime", "")
        data["bb_high"] = stats.get("bodyBatteryHighestValue", "")
        data["bb_low"] = stats.get("bodyBatteryLowestValue", "")
    except Exception:
        for k in ["resting_hr", "steps", "total_calories", "active_calories",
                   "bmr_calories", "avg_stress", "stress_qualifier",
                   "floors_ascended", "moderate_min", "vigorous_min",
                   "bb_at_wake", "bb_high", "bb_low"]:
            data[k] = ""

    # Body battery (today, not target date)
    try:
        today_iso = datetime.now().date().isoformat()
        bb = client.get_body_battery(today_iso)
        data["body_battery"] = bb[0].get("charged", "") if bb else ""
    except Exception:
        data["body_battery"] = ""

    # SpO2
    try:
        spo2 = client.get_spo2_data(target_iso)
        if spo2:
            data["spo2_avg"] = spo2.get("averageSpO2", "")
            data["spo2_min"] = spo2.get("lowestSpO2", "")
        else:
            data["spo2_avg"] = data["spo2_min"] = ""
    except Exception:
        data["spo2_avg"] = data["spo2_min"] = ""

    # Activities (check target date)
    try:
        from garmin_client import _fetch_activity_data
        data.update(_fetch_activity_data(client, target_iso))
    except Exception as e:
        print(f"Activity fetch failed: {e}")
        from garmin_client import _ACTIVITY_KEYS
        for k in _ACTIVITY_KEYS:
            data[k] = ""

    return data


# ---------------------------------------------------------------------------
# Sleep analysis (pure function, no I/O)
# ---------------------------------------------------------------------------

def _run_sleep_analysis(data):
    """Compute sleep score and analysis text. Returns (score, text, descriptor)."""
    try:
        from sleep_analysis import generate_sleep_analysis
        score, text, descriptor = generate_sleep_analysis(data)
        return score, text, descriptor
    except Exception as e:
        print(f"Sleep analysis failed: {e}")
        return None, "", ""


# ---------------------------------------------------------------------------
# Supabase write
# ---------------------------------------------------------------------------

def _write_to_supabase(date_str, data):
    """Initialize Supabase client from env vars and upsert all tables.

    Returns dict with sync results.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return {"error": "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"}

    from supabase import create_client
    client = create_client(url, key)

    from supabase_sync import (
        upsert_garmin, upsert_sleep, upsert_nutrition, upsert_session_log
    )

    results = {}
    try:
        upsert_garmin(client, date_str, data)
        results["garmin"] = "ok"
    except Exception as e:
        results["garmin"] = str(e)

    try:
        upsert_sleep(client, date_str, data)
        results["sleep"] = "ok"
    except Exception as e:
        results["sleep"] = str(e)

    try:
        upsert_nutrition(client, date_str, data)
        results["nutrition"] = "ok"
    except Exception as e:
        results["nutrition"] = str(e)

    try:
        upsert_session_log(client, date_str, data)
        results["session_log"] = "ok"
    except Exception as e:
        results["session_log"] = str(e)

    return results


# ---------------------------------------------------------------------------
# Simplified readiness estimate (for PWA "Preliminary" badge)
# ---------------------------------------------------------------------------

# Thresholds for readiness estimation (matches existing THRESHOLDS in overall_analysis.py)
_READINESS_WEIGHTS = {
    "sleep_score":   {"weight": 0.30, "min": 40, "max": 90},
    "hrv":           {"weight": 0.25, "min": 20, "max": 80},
    "body_battery":  {"weight": 0.20, "min": 10, "max": 80},
    "resting_hr":    {"weight": 0.15, "min": 45, "max": 75, "invert": True},
    "avg_stress":    {"weight": 0.10, "min": 15, "max": 60, "invert": True},
}


def _estimate_readiness(data):
    """Quick readiness estimate from raw Garmin metrics. Returns 1-10 or None."""
    total_weight = 0
    weighted_sum = 0

    for key, cfg in _READINESS_WEIGHTS.items():
        val = data.get(key)
        if val is None or val == "":
            continue
        try:
            val = float(val)
        except (ValueError, TypeError):
            continue

        # Normalize to 0-1
        lo, hi = cfg["min"], cfg["max"]
        normalized = max(0.0, min(1.0, (val - lo) / (hi - lo)))
        if cfg.get("invert"):
            normalized = 1.0 - normalized

        weighted_sum += normalized * cfg["weight"]
        total_weight += cfg["weight"]

    if total_weight < 0.3:
        return None  # Not enough data

    # Scale to 1-10
    raw = weighted_sum / total_weight
    return max(1, min(10, round(raw * 9 + 1)))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def health_refresh(request):
    """HTTP Cloud Function entry point.

    POST /health-refresh
    Headers: X-Refresh-Secret: <shared_secret>
    Body (optional JSON): {"date": "YYYY-MM-DD"}

    Returns JSON:
        {
            "status": "success",
            "date": "YYYY-MM-DD",
            "sleep_score": 78,
            "readiness_estimate": 7,
            "preliminary": true,
            "sync_results": {"garmin": "ok", "sleep": "ok", ...},
            "data_summary": {"steps": 6239, "hrv": 42, ...}
        }
    """
    # CORS — reject if Origin header is present and not in allowed list.
    # Missing Origin = server-to-server (Edge Function) — allowed.
    # CORS is browser hygiene; real auth is REFRESH_SECRET.
    allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    request_origin = request.headers.get("Origin", "")

    if request_origin and allowed_origins and request_origin not in allowed_origins:
        return (
            json.dumps({"error": "Origin not allowed"}),
            403,
            {"Content-Type": "application/json"},
        )

    # Set CORS header to the request origin (if present), or omit
    cors_origin = request_origin if request_origin else ""

    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": cors_origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Refresh-Secret",
    }

    # Handle CORS preflight
    if request.method == "OPTIONS":
        return ("", 204, headers)

    # Auth check
    auth_error = _check_auth(request)
    if auth_error:
        return (*auth_error[:2], {**headers, **auth_error[2]})

    # Rate limit check
    rate_error = _check_rate_limit(request)
    if rate_error:
        return (*rate_error[:2], {**headers, **rate_error[2]})

    try:
        # Parse request
        body = request.get_json(silent=True) or {}
        date_str = body.get("date")
        if not date_str:
            # Default: yesterday (most common use — last night's sleep)
            date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        print(f"[health-refresh] Starting sync for {date_str}")

        # Step 1: Fetch Garmin data
        data = _fetch_garmin_data(date_str)
        print(f"[health-refresh] Garmin data fetched: {len(data)} keys")

        # Step 2: Sleep analysis (pure computation)
        sleep_score, sleep_text, sleep_descriptor = _run_sleep_analysis(data)
        data["sleep_analysis_score"] = sleep_score
        data["sleep_analysis_text"] = sleep_text
        data["sleep_descriptor"] = sleep_descriptor

        # Step 3: Quick readiness estimate
        readiness = _estimate_readiness(data)

        # Step 4: Write to Supabase
        sync_results = _write_to_supabase(date_str, data)
        print(f"[health-refresh] Supabase sync: {sync_results}")

        # Build response with key metrics for PWA
        data_summary = {
            "steps": data.get("steps"),
            "hrv": data.get("hrv"),
            "resting_hr": data.get("resting_hr"),
            "sleep_score": data.get("sleep_score"),
            "sleep_duration": data.get("sleep_duration"),
            "body_battery": data.get("body_battery"),
            "avg_stress": data.get("avg_stress"),
            "activity_name": data.get("activity_name"),
        }

        response = {
            "status": "success",
            "date": date_str,
            "sleep_analysis_score": sleep_score,
            "readiness_estimate": readiness,
            "preliminary": True,  # Full analysis runs in Tier 2 (GitHub Actions)
            "sync_results": sync_results,
            "data_summary": data_summary,
        }

        return (json.dumps(response), 200, headers)

    except Exception as e:
        print(f"[health-refresh] ERROR: {traceback.format_exc()}")
        error_response = {
            "status": "error",
            "error": str(e),
            "date": date_str if 'date_str' in dir() else None,
        }
        return (json.dumps(error_response), 500, headers)


# ---------------------------------------------------------------------------
# Local testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run locally for testing: python cloud_function/main.py [YYYY-MM-DD]"""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

    # For local testing, pull password from keyring
    if not os.environ.get("GARMIN_PASSWORD"):
        try:
            import keyring
            email = os.environ.get("GARMIN_EMAIL")
            pw = keyring.get_password("garmin_connect", email)
            if pw:
                os.environ["GARMIN_PASSWORD"] = pw
                print(f"[local] Loaded Garmin password from keyring for {email}")
        except ImportError:
            pass

    # Simulate HTTP request
    class FakeRequest:
        method = "POST"
        remote_addr = "127.0.0.1"
        headers = {}
        def get_json(self, silent=False):
            date_arg = sys.argv[1] if len(sys.argv) > 1 else None
            return {"date": date_arg} if date_arg else {}

    result = health_refresh(FakeRequest())
    body = result[0] if isinstance(result, tuple) else result
    parsed = json.loads(body)
    print(json.dumps(parsed, indent=2))
