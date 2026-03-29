"""
Extract Garmin OAuth tokens from an active browser session.

Usage:
  1. Log into connect.garmin.com in Chrome
  2. Dev Tools (F12) -> Network tab -> click any API request (e.g. user-settings/)
  3. Right-click the request -> "Copy as cURL (bash)"
  4. Paste into Notepad, find the Cookie header value
  5. Run this script and paste the cookie string when prompted
"""

import requests
import json
import os
import time
import re

GARTH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".garth")


def extract_tokens():
    print("=" * 60)
    print("Garmin Token Extractor")
    print("=" * 60)
    print()
    print("Paste your Cookie header value from Chrome Dev Tools.")
    print("(The long string starting with '_ga=GA1...')")
    print("Then press Enter twice (empty line) to finish:")
    print()

    lines = []
    while True:
        line = input()
        if line.strip() == "":
            break
        lines.append(line)
    cookie_str = " ".join(lines).strip()

    if not cookie_str:
        print("ERROR: No cookie provided.")
        return

    # Clean up - remove surrounding quotes if present
    cookie_str = cookie_str.strip("'\"")

    # Extract JWT from cookie
    jwt_match = re.search(r'JWT_WEB=([^;]+)', cookie_str)
    if not jwt_match:
        print("ERROR: Could not find JWT_WEB in cookies.")
        print("Make sure you copied the full cookie string.")
        return

    jwt_token = jwt_match.group(1)
    print(f"\nFound JWT_WEB token ({len(jwt_token)} chars)")

    # Use the session cookies to call the OAuth exchange endpoint
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/146.0.0.0 Mobile Safari/537.36",
        "Cookie": cookie_str,
        "Accept": "application/json",
        "Origin": "https://connect.garmin.com",
        "Referer": "https://connect.garmin.com/",
    })

    # Try to get an OAuth2 token via the exchange endpoint
    print("\nAttempting to exchange session for OAuth tokens...")

    # Method 1: Try the OAuth exchange endpoint
    try:
        resp = session.post(
            "https://connect.garmin.com/services/auth/token/exchange",
            json={"consumer": "GCM_WEB"},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"Got OAuth exchange response: {list(data.keys())}")
            _save_oauth2_from_exchange(data)
            return
        else:
            print(f"Exchange endpoint returned {resp.status_code}")
    except Exception as e:
        print(f"Exchange endpoint failed: {e}")

    # Method 2: Try using the JWT directly as a bearer token
    print("\nTrying JWT as direct bearer token...")
    test = requests.get(
        "https://connect.garmin.com/userprofile-service/usersettings",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/json",
        },
        timeout=30,
    )
    if test.status_code == 200:
        print("JWT works as bearer token!")
        _save_jwt_as_oauth2(jwt_token)
        return

    # Method 3: Use cookies directly to hit the Garmin API and
    # create a minimal token file that our sync can use
    print("\nTrying direct cookie-based API access...")
    test2 = session.get(
        "https://connect.garmin.com/userprofile-service/usersettings",
        timeout=30,
    )
    if test2.status_code == 200:
        print("Cookie-based access works!")
        print("\nThe cookies work but we need OAuth tokens for garth.")
        print("Attempting OAuth1 ticket exchange...")
        _try_service_ticket_exchange(session, cookie_str)
        return

    print(f"\nAll methods failed. Last status: {test2.status_code}")
    print("Your session may have expired. Try logging in again.")


def _save_oauth2_from_exchange(data):
    """Save OAuth2 token from exchange endpoint response."""
    os.makedirs(GARTH_DIR, exist_ok=True)

    oauth2 = {
        "scope": data.get("scope", ""),
        "jti": data.get("jti", ""),
        "token_type": data.get("token_type", "Bearer"),
        "access_token": data.get("access_token", ""),
        "refresh_token": data.get("refresh_token", ""),
        "expires_in": data.get("expires_in", 3600),
        "expires_at": int(time.time()) + data.get("expires_in", 3600),
        "refresh_token_expires_in": data.get("refresh_token_expires_in", 7776000),
        "refresh_token_expires_at": int(time.time()) + data.get("refresh_token_expires_in", 7776000),
    }

    with open(os.path.join(GARTH_DIR, "oauth2_token.json"), "w") as f:
        json.dump(oauth2, f, indent=4)

    # Create a minimal oauth1 token file
    oauth1 = {
        "oauth_token": "",
        "oauth_token_secret": "",
        "mfa_token": None,
        "mfa_expiration_timestamp": None,
        "domain": "garmin.com",
    }
    with open(os.path.join(GARTH_DIR, "oauth1_token.json"), "w") as f:
        json.dump(oauth1, f, indent=4)

    print(f"\nTokens saved to {GARTH_DIR}")
    print("Try running: python garmin_sync.py --today")


def _save_jwt_as_oauth2(jwt_token):
    """Save a JWT token in garth's OAuth2 format."""
    os.makedirs(GARTH_DIR, exist_ok=True)

    oauth2 = {
        "scope": "",
        "jti": "",
        "token_type": "Bearer",
        "access_token": jwt_token,
        "refresh_token": "",
        "expires_in": 86400,
        "expires_at": int(time.time()) + 86400,
        "refresh_token_expires_in": 7776000,
        "refresh_token_expires_at": int(time.time()) + 7776000,
    }

    with open(os.path.join(GARTH_DIR, "oauth2_token.json"), "w") as f:
        json.dump(oauth2, f, indent=4)

    oauth1 = {
        "oauth_token": "",
        "oauth_token_secret": "",
        "mfa_token": None,
        "mfa_expiration_timestamp": None,
        "domain": "garmin.com",
    }
    with open(os.path.join(GARTH_DIR, "oauth1_token.json"), "w") as f:
        json.dump(oauth1, f, indent=4)

    print(f"\nTokens saved to {GARTH_DIR}")
    print("Try running: python garmin_sync.py --today")


def _try_service_ticket_exchange(session, cookie_str):
    """Try to get a service ticket that can be exchanged for OAuth tokens."""
    # Get a service ticket for the Connect API
    try:
        resp = session.get(
            "https://sso.garmin.com/sso/embed"
            "?id=gauth-widget"
            "&embedWidget=true",
            allow_redirects=False,
            timeout=30,
        )
        print(f"SSO embed returned {resp.status_code}")
        if "ticket" in resp.text.lower() or "ST-" in resp.text:
            print("Found service ticket reference!")
    except Exception as e:
        print(f"SSO embed failed: {e}")

    # Fallback: save cookie-based session info so we can build
    # a custom fetch path that doesn't need garth
    print("\nCould not obtain OAuth tokens from session.")
    print("Creating a cookie-based session file instead...")
    _save_cookie_session(cookie_str)


def _save_cookie_session(cookie_str):
    """Save cookies for direct API access (bypass garth)."""
    os.makedirs(GARTH_DIR, exist_ok=True)
    session_file = os.path.join(GARTH_DIR, "cookie_session.json")

    data = {
        "cookies": cookie_str,
        "created_at": int(time.time()),
        "note": "Cookie-based session - use with direct requests, not garth",
    }

    with open(session_file, "w") as f:
        json.dump(data, f, indent=4)

    print(f"\nCookie session saved to {session_file}")
    print("NOTE: garmin_sync.py will need a code update to use cookie auth.")
    print("Run this script again if you get new tokens.")


if __name__ == "__main__":
    extract_tokens()
