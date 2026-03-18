"""GET /api/health — Health check + TOTP login endpoint."""

from http.server import BaseHTTPRequestHandler
import time
import hashlib

from _shared import (
    json_response, read_body, verify_totp, TOTP_SECRET,
    check_rate_limit,
)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        json_response(self, 204, "")

    def do_GET(self):
        """Simple health check — no auth required."""
        json_response(self, 200, {"status": "ok", "timestamp": int(time.time())})

    def do_POST(self):
        """TOTP login — exchange a 6-digit code for a session token.

        POST /api/health
        Body: {"totp_code": "123456"}
        Returns: {"session_token": "abc123...", "expires_in": 1800}
        """
        body = read_body(self)
        if body is None:
            json_response(self, 400, {"error": "Invalid JSON"})
            return
        totp_code = body.get("totp_code", "").strip()

        if not totp_code:
            json_response(self, 400, {"error": "Missing 'totp_code' field"})
            return

        # Rate limit login attempts (keyed by "login" to share across all clients)
        ok, remaining = check_rate_limit("login_attempts")
        if not ok:
            json_response(self, 429, {"error": "Too many login attempts. Try again later."})
            return

        if not verify_totp(totp_code):
            json_response(self, 401, {"error": "Invalid TOTP code"})
            return

        # Generate session token (valid for 30-minute window)
        current_window = int(time.time()) // 1800
        session_token = hashlib.sha256(
            f"{TOTP_SECRET}:session:{current_window}".encode()
        ).hexdigest()[:32]

        json_response(self, 200, {
            "session_token": session_token,
            "expires_in": 1800,
        })

    def log_message(self, format, *args):
        pass
