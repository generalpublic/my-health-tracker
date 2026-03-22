"""
utils.py -- Shared utility functions for the Health Tracker project.

Extracted from garmin_sync.py to reduce coupling. All scripts should import
shared helpers from here instead of from garmin_sync.py.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def get_workbook():
    """Return gspread Spreadsheet object for the configured SHEET_ID."""
    import gspread
    from google.oauth2.service_account import Credentials

    sheet_id = os.getenv("SHEET_ID")
    _json_key_name = os.getenv("JSON_KEY_FILE")
    json_key_file = str(Path(__file__).parent / _json_key_name) if _json_key_name else None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(json_key_file, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id)


def get_sheet(wb):
    """Return the 'Garmin' worksheet, falling back to sheet1."""
    import gspread
    try:
        return wb.worksheet("Garmin")
    except gspread.exceptions.WorksheetNotFound:
        return wb.sheet1


def _safe_float(val, default=None):
    """Convert a value to float, returning default if empty or invalid."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def date_to_day(date_str):
    """Convert date string to 3-letter day abbreviation (Mon, Tue, etc.).

    Handles both ISO format (YYYY-MM-DD) and Google Sheets format (M/D/YYYY).
    """
    from datetime import date as _d, datetime as _dt
    s = str(date_str).strip()
    # Try ISO format first (YYYY-MM-DD)
    try:
        return _d.fromisoformat(s).strftime("%a")
    except (ValueError, TypeError):
        pass
    # Try Google Sheets format (M/D/YYYY)
    try:
        return _dt.strptime(s, "%m/%d/%Y").strftime("%a")
    except (ValueError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# User config — per-user settings for multi-user generalization
# ---------------------------------------------------------------------------

# Default habits (backward compatible — matches original Daily Log schema)
DEFAULT_HABITS = [
    {"id": "h1", "label": "Wake at 9:30 AM"},
    {"id": "h2", "label": "No Morning Screens"},
    {"id": "h3", "label": "Creatine & Hydrate"},
    {"id": "h4", "label": "20 Min Walk + Breathing"},
    {"id": "h5", "label": "Physical Activity"},
    {"id": "h6", "label": "No Screens Before Bed"},
    {"id": "h7", "label": "Bed at 10 PM"},
]

DEFAULT_USER_CONFIG = {
    "user": {
        "display_name": "",
        "data_source": "garmin",
        "profile_dir": "",
    },
    "habits": {
        "enabled": True,
        "items": DEFAULT_HABITS,
    },
    "schedule": {
        "bedtime_target": "23:00",
        "wake_target": "07:00",
        "sync_time": "20:00",
    },
    "features": {
        "daily_log": True,
        "nutrition": True,
        "strength_log": True,
        "session_log": True,
        "notifications": False,
        "supabase_sync": False,
        "dashboard": True,
    },
    "thresholds": {
        "mode": "defaults",
        "calibration_date": None,
        "overrides": {},
    },
}


def _deep_merge(base, override):
    """Recursively merge override dict into base dict. Override wins on conflicts."""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_user_config():
    """Load user_config.json with fallback to defaults.

    If user_config.json doesn't exist, returns DEFAULT_USER_CONFIG unchanged.
    If it exists, deep-merges user values over defaults so missing keys are filled.
    """
    config_path = Path(__file__).parent / "user_config.json"
    if not config_path.exists():
        return DEFAULT_USER_CONFIG.copy()
    try:
        with open(config_path) as f:
            user = json.load(f)
        # Strip _comment keys used for documentation in the example file
        user.pop("_comment", None)
        return _deep_merge(DEFAULT_USER_CONFIG, user)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_USER_CONFIG.copy()


def get_habit_labels(config=None):
    """Return list of habit label strings from config (or defaults)."""
    cfg = config or load_user_config()
    if not cfg.get("habits", {}).get("enabled", True):
        return []
    return [h["label"] for h in cfg.get("habits", {}).get("items", DEFAULT_HABITS)]


def get_scoring_thresholds(config=None):
    """Build scoring thresholds dict by merging three layers (lowest to highest priority):

    1. Hardcoded defaults (population norms)
    2. thresholds.json scoring_params (project-level config)
    3. user_config.json thresholds.overrides (per-user calibration)

    Returns a dict with keys like 'hrv_floor', 'hrv_ceiling', 'bedtime_target', etc.
    Used by sleep_analysis.py and overall_analysis.py for personalized scoring.
    """
    cfg = config or load_user_config()
    schedule = cfg.get("schedule", {})
    user_overrides = cfg.get("thresholds", {}).get("overrides", {})

    # Layer 1: Hardcoded population defaults
    defaults = {
        "sleep_duration_floor": 4.0,
        "sleep_duration_ceiling": 7.0,
        "deep_pct_floor": 10.0,
        "deep_pct_ceiling": 20.0,
        "rem_pct_floor": 10.0,
        "rem_pct_ceiling": 20.0,
        "hrv_floor": 37.0,
        "hrv_ceiling": 44.0,
        "awakenings_max": 8.0,
        "body_battery_ceiling": 60.0,
        "bedtime_target": schedule.get("bedtime_target", "23:00"),
        "bedtime_bonus_before_target": 5,
        "bedtime_penalty_offset_min": 90,
        "bedtime_penalty_points": -10,
    }

    # Layer 2: thresholds.json scoring_params
    thresholds_file = load_thresholds()
    file_params = thresholds_file.get("scoring_params", {})
    # Strip _comment keys
    file_params = {k: v for k, v in file_params.items() if not k.startswith("_")}
    defaults.update(file_params)

    # Layer 3: user_config.json overrides (highest priority — from auto-calibration)
    defaults.update(user_overrides)

    # Always apply schedule bedtime_target from user config (if set)
    if schedule.get("bedtime_target"):
        defaults["bedtime_target"] = schedule["bedtime_target"]

    return defaults


def load_thresholds():
    """Load scoring thresholds from thresholds.json.

    Returns dict of thresholds. Falls back to hardcoded defaults if file
    is missing or malformed, so the system never crashes on a bad config.
    """
    thresholds_path = Path(__file__).parent / "thresholds.json"
    try:
        with open(thresholds_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # Hardcoded fallbacks — keep in sync with thresholds.json
        return {
            "readiness_labels": [
                {"min_score": 8.5, "label": "Optimal"},
                {"min_score": 7.0, "label": "Good"},
                {"min_score": 5.5, "label": "Fair"},
                {"min_score": 4.0, "label": "Low"},
                {"min_score": 0.0, "label": "Poor"},
            ],
            "component_weights": {
                "HRV": 0.35, "Sleep": 0.30, "RHR": 0.20, "Subjective": 0.15,
            },
            "acwr": {
                "elevated": 1.3, "detraining": 0.8,
                "sweet_low": 0.8, "sweet_high": 1.3,
            },
            "confidence": {
                "high_min_n": 90,
                "medium_high_min_n": 60,
                "medium_min_n": 30,
            },
        }
