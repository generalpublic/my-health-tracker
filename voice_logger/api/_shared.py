"""Shared utilities for Voice Logger API endpoints."""

import json
import os
import base64
import time
import hashlib

import pyotp
import gspread
from google.oauth2.service_account import Credentials
from datetime import date as _date

# ── Environment ──────────────────────────────────────────────────────────────
TOTP_SECRET = os.environ.get("TOTP_SECRET", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NUTRITIONIX_APP_ID = os.environ.get("NUTRITIONIX_APP_ID", "")
NUTRITIONIX_APP_KEY = os.environ.get("NUTRITIONIX_APP_KEY", "")
SHEET_ID = os.environ.get("SHEET_ID", "")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Rate Limiting (in-memory, per serverless invocation) ─────────────────────
# Vercel serverless functions are stateless — each cold start resets this.
# For true persistence, use Vercel KV. For now, this limits burst abuse within
# a single warm instance. TOTP is the primary security layer.
_rate_limit_store = {}  # {session_hash: [(timestamp, ...),]}
RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds


def _session_key(totp_code):
    """Hash the TOTP code to create a session identifier."""
    return hashlib.sha256(f"{totp_code}:{int(time.time()) // 30}".encode()).hexdigest()[:16]


def check_rate_limit(session_id):
    """Check if the session is within rate limits. Returns (ok, remaining)."""
    now = time.time()
    if session_id not in _rate_limit_store:
        _rate_limit_store[session_id] = []

    # Prune old entries
    _rate_limit_store[session_id] = [
        t for t in _rate_limit_store[session_id] if now - t < RATE_LIMIT_WINDOW
    ]

    if len(_rate_limit_store[session_id]) >= RATE_LIMIT_MAX:
        return False, 0

    _rate_limit_store[session_id].append(now)
    return True, RATE_LIMIT_MAX - len(_rate_limit_store[session_id])


# ── TOTP Authentication ──────────────────────────────────────────────────────

def verify_totp(code):
    """Verify a 6-digit TOTP code. Returns True if valid.

    valid_window=1 allows codes from the previous and next 30-second window,
    giving a 90-second effective window to account for clock drift.
    """
    if not TOTP_SECRET:
        return False
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.verify(code, valid_window=1)


def authenticate(headers):
    """Verify the request's TOTP session token.

    Frontend flow:
    1. User enters 6-digit TOTP code on app open
    2. Frontend sends POST /api/health with X-TOTP-Code header
    3. Backend validates and returns a session token (HMAC of code + time window)
    4. Frontend stores session token in sessionStorage
    5. All subsequent requests send session token in Authorization header

    Returns (success: bool, error_message: str, session_id: str)
    """
    # Check for session token first (normal flow after initial auth)
    auth_header = headers.get("Authorization", headers.get("authorization", ""))
    if auth_header.startswith("Bearer "):
        session_token = auth_header[7:]
        # Validate session token: it's an HMAC of TOTP_SECRET + time window
        # Valid for the current 30-min window
        current_window = int(time.time()) // 1800  # 30-minute windows
        for window in [current_window, current_window - 1]:  # allow previous window
            expected = hashlib.sha256(
                f"{TOTP_SECRET}:session:{window}".encode()
            ).hexdigest()[:32]
            if session_token == expected:
                ok, remaining = check_rate_limit(session_token[:16])
                if not ok:
                    return False, "Rate limit exceeded (20 req/hr)", ""
                return True, "", session_token[:16]
        return False, "Session expired — re-enter TOTP code", ""

    # Check for initial TOTP code (login flow)
    totp_code = headers.get("X-TOTP-Code", headers.get("x-totp-code", ""))
    if totp_code:
        if verify_totp(totp_code):
            current_window = int(time.time()) // 1800
            session_token = hashlib.sha256(
                f"{TOTP_SECRET}:session:{current_window}".encode()
            ).hexdigest()[:32]
            return True, session_token, session_token[:16]  # token returned as "error_message" field for login
        return False, "Invalid TOTP code", ""

    return False, "Authentication required", ""


# ── Google Sheets Client ─────────────────────────────────────────────────────

_sheets_client = None


def get_sheets_client():
    """Create or return cached gspread client from base64-encoded service account JSON."""
    global _sheets_client
    if _sheets_client is not None:
        return _sheets_client

    sa_json_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json_b64:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var not set")

    sa_info = json.loads(base64.b64decode(sa_json_b64))
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    _sheets_client = gspread.authorize(creds)
    return _sheets_client


def get_workbook():
    """Open the Health Tracker workbook."""
    client = get_sheets_client()
    return client.open_by_key(SHEET_ID)


# ── Date Utilities ───────────────────────────────────────────────────────────

def date_to_day(date_str):
    """Convert date string to 3-letter day abbreviation (Mon, Tue, etc.).

    Handles both ISO format (YYYY-MM-DD) and Google Sheets format (M/D/YYYY).
    """
    from datetime import datetime as _dt
    s = str(date_str).strip()
    try:
        return _date.fromisoformat(s).strftime("%a")
    except (ValueError, TypeError):
        pass
    try:
        return _dt.strptime(s, "%m/%d/%Y").strftime("%a")
    except (ValueError, TypeError):
        return ""


def today_str():
    """Return today's date as 'YYYY-MM-DD'."""
    return str(_date.today())


# ── Nutrition Tab Schema (must match garmin_sync.py exactly) ─────────────────

NUTRITION_HEADERS = [
    "Day",                           # A  0
    "Date",                          # B  1
    "Total Calories Burned",         # C  2  auto
    "Active Calories Burned",        # D  3  auto
    "BMR Calories",                  # E  4  auto
    "Breakfast",                     # F  5  manual
    "Lunch",                         # G  6  manual
    "Dinner",                        # H  7  manual
    "Snacks",                        # I  8  manual
    "Total Calories Consumed",       # J  9  manual
    "Protein (g)",                   # K  10 manual
    "Carbs (g)",                     # L  11 manual
    "Fats (g)",                      # M  12 manual
    "Water (L)",                     # N  13 manual
    "Calorie Balance",               # O  14 formula
    "Notes",                         # P  15 manual
]

MEAL_TYPE_COLS = {
    "Breakfast": 5,
    "Lunch": 6,
    "Dinner": 7,
    "Snacks": 8,
}

# Nutrition macro column indices (0-based)
COL_TOTAL_CONSUMED = 9
COL_PROTEIN = 10
COL_CARBS = 11
COL_FATS = 12
COL_NOTES = 15

STRENGTH_LOG_HEADERS = [
    "Day", "Date", "Muscle Group", "Exercise",
    "Weight (lbs)", "Reps", "RPE (1-10)", "Notes",
]


# ── HTTP Response Helpers ────────────────────────────────────────────────────

def json_response(handler, status, body):
    """Write a JSON response to the handler."""
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers",
                        "Content-Type, Authorization, X-TOTP-Code")
    handler.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
    handler.end_headers()
    handler.wfile.write(json.dumps(body).encode())


def read_body(handler):
    """Read and parse JSON request body."""
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length == 0:
        return {}
    return json.loads(handler.rfile.read(content_length))
