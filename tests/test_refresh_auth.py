"""
Tests for HMAC authentication in cloud_function/main.py.

Covers:
  - Valid HMAC signature accepted
  - Expired timestamp rejected (replay protection)
  - Tampered signature rejected
  - Tampered body rejected
  - Legacy X-Refresh-Secret fallback (accepted with warning)
  - Missing secret env var returns 500
  - Missing all auth headers returns 401
"""

import hashlib
import hmac
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on sys.path so cloud_function imports resolve
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "cloud_function"))

from cloud_function.main import _check_auth, _HMAC_MAX_AGE_SECONDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_SECRET = "test-hmac-secret-32bytes-long!!"


class FakeRequest:
    """Minimal mock of a Flask request object for _check_auth."""

    def __init__(self, headers=None, body=""):
        self._headers = headers or {}
        self._body = body

    def get_data(self, as_text=False):
        return self._body if as_text else self._body.encode()

    @property
    def headers(self):
        return self._headers


def _sign(secret, timestamp, body):
    """Produce a valid HMAC-SHA256 hex signature."""
    message = str(timestamp) + "|" + body
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@patch.dict(os.environ, {"REFRESH_SECRET": TEST_SECRET})
class TestHMACAuth(unittest.TestCase):

    def _make_signed_request(self, body='{"date":"2026-03-23"}', time_offset=0):
        """Build a FakeRequest with valid HMAC headers."""
        ts = str(int(time.time()) + time_offset)
        sig = _sign(TEST_SECRET, ts, body)
        return FakeRequest(
            headers={
                "X-Refresh-Timestamp": ts,
                "X-Refresh-Signature": sig,
            },
            body=body,
        )

    def test_valid_hmac_accepted(self):
        req = self._make_signed_request()
        self.assertIsNone(_check_auth(req))

    def test_valid_hmac_empty_body(self):
        req = self._make_signed_request(body="")
        self.assertIsNone(_check_auth(req))

    def test_expired_timestamp_rejected(self):
        req = self._make_signed_request(time_offset=-(_HMAC_MAX_AGE_SECONDS + 60))
        result = _check_auth(req)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 401)
        self.assertIn("expired", json.loads(result[0])["error"].lower())

    def test_future_timestamp_rejected(self):
        req = self._make_signed_request(time_offset=_HMAC_MAX_AGE_SECONDS + 60)
        result = _check_auth(req)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 401)

    def test_tampered_signature_rejected(self):
        body = '{"date":"2026-03-23"}'
        ts = str(int(time.time()))
        req = FakeRequest(
            headers={
                "X-Refresh-Timestamp": ts,
                "X-Refresh-Signature": "bad" + _sign(TEST_SECRET, ts, body)[3:],
            },
            body=body,
        )
        result = _check_auth(req)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 401)

    def test_tampered_body_rejected(self):
        body = '{"date":"2026-03-23"}'
        ts = str(int(time.time()))
        sig = _sign(TEST_SECRET, ts, body)
        req = FakeRequest(
            headers={
                "X-Refresh-Timestamp": ts,
                "X-Refresh-Signature": sig,
            },
            body='{"date":"2099-01-01"}',  # different from signed body
        )
        result = _check_auth(req)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 401)

    def test_non_numeric_timestamp_rejected(self):
        body = '{"date":"2026-03-23"}'
        req = FakeRequest(
            headers={
                "X-Refresh-Timestamp": "not-a-number",
                "X-Refresh-Signature": "deadbeef",
            },
            body=body,
        )
        result = _check_auth(req)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 401)


@patch.dict(os.environ, {"REFRESH_SECRET": TEST_SECRET})
class TestLegacyFallback(unittest.TestCase):

    def test_legacy_secret_accepted(self):
        req = FakeRequest(headers={"X-Refresh-Secret": TEST_SECRET})
        self.assertIsNone(_check_auth(req))

    def test_legacy_wrong_secret_rejected(self):
        req = FakeRequest(headers={"X-Refresh-Secret": "wrong-secret"})
        result = _check_auth(req)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 401)


class TestMissingConfig(unittest.TestCase):

    @patch.dict(os.environ, {}, clear=True)
    def test_no_secret_configured_returns_500(self):
        req = FakeRequest(headers={})
        result = _check_auth(req)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 500)
        self.assertIn("not configured", json.loads(result[0])["error"].lower())

    @patch.dict(os.environ, {"REFRESH_SECRET": TEST_SECRET})
    def test_no_auth_headers_returns_401(self):
        req = FakeRequest(headers={})
        result = _check_auth(req)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 401)


if __name__ == "__main__":
    unittest.main()
