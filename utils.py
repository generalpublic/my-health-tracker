"""
utils.py -- Shared utility functions for the Health Tracker project.

Extracted from garmin_sync.py to reduce coupling. All scripts should import
shared helpers from here instead of from garmin_sync.py.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv(Path(__file__).parent / ".env")

# --- Google Sheets config ---
SHEET_ID = os.getenv("SHEET_ID")
_json_key_name = os.getenv("JSON_KEY_FILE")
JSON_KEY_FILE = str(Path(__file__).parent / _json_key_name) if _json_key_name else None

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_workbook():
    """Return gspread Spreadsheet object for the configured SHEET_ID."""
    creds = Credentials.from_service_account_file(JSON_KEY_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)


def get_sheet(wb):
    """Return the 'Garmin' worksheet, falling back to sheet1."""
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
