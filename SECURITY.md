# Security Model

## Credential Overview

Health Tracker uses three credential storage mechanisms depending on context:

| Credential | Storage | Used By |
|---|---|---|
| Garmin password | System keyring (Windows Credential Manager / macOS Keychain / libsecret) | `garmin_sync.py` |
| Google service account key | JSON file in project directory (gitignored) | `garmin_sync.py`, `verify_sheets.py`, all Sheets scripts |
| Pushover API keys | `.env` file (gitignored) | `garmin_sync.py` notifications |
| TOTP secret | Vercel environment variable | Voice logger authentication |
| Anthropic API key | Vercel environment variable | Voice logger AI processing |
| Nutritionix credentials | Vercel environment variables | Voice logger nutrition lookup |
| Google service account (voice logger) | Vercel environment variable (base64-encoded JSON) | Voice logger Sheets writes |

## What Lives Where

### `.env` (local, gitignored)
- `SHEET_ID` -- Google Sheets spreadsheet ID
- `JSON_KEY_FILE` -- filename (not path) of the service account JSON key
- `GARMIN_EMAIL` -- Garmin Connect login email
- `PUSHOVER_USER_KEY` / `PUSHOVER_API_TOKEN` -- notification credentials (optional)

### System keyring
- Garmin Connect password, stored under service `garmin_connect` with the email as username
- Accessed via Python `keyring` library -- never written to any file

### Vercel environment variables (voice logger only)
- `TOTP_SECRET` -- shared secret for time-based one-time passwords
- `ANTHROPIC_API_KEY` -- Claude API access for voice processing
- `NUTRITIONIX_APP_ID` / `NUTRITIONIX_APP_KEY` -- nutrition data lookup
- `GOOGLE_SERVICE_ACCOUNT_JSON` -- base64-encoded service account key
- `SHEET_ID` -- same spreadsheet ID as local `.env`

## Voice Logger Auth Model

The voice logger uses a two-layer authentication scheme:

1. **TOTP code** -- user enters a 6-digit time-based code (standard 30-second window) to authenticate. The shared secret is stored only in Vercel env vars and the user's authenticator app.
2. **Session token** -- after TOTP verification, the server issues an HMAC-based session token derived from the TOTP secret and a time window. Subsequent requests use this token instead of re-entering TOTP.

No passwords are stored. No user accounts exist. Access requires possession of the authenticator app.

## Data Privacy

- All health data is stored in the user's own Google Sheets spreadsheet
- No data is sent to third-party analytics, tracking, or storage services
- Garmin data is pulled directly from the user's Garmin Connect account
- The Google service account has access only to the specific spreadsheet shared with it
- Voice logger processes audio transiently -- no recordings are stored server-side
- SQLite database (local backup) is gitignored and stays on the user's machine

## `.gitignore` Coverage

The following are excluded from version control:
- `.env` -- all local environment variables
- `*.json` -- service account key files
- `*.db` -- SQLite database files
- `*.log` -- error and debug logs
- `profiles/` -- user profile data
- `reference/` -- personal health references and exports
- `data/` -- local data files

## Credential Rotation

### Garmin password
1. Change password at [connect.garmin.com](https://connect.garmin.com)
2. Update keyring: `python -c "import keyring; keyring.set_password('garmin_connect', 'EMAIL', 'NEW_PASSWORD')"`
3. Verify: `python garmin_sync.py --today`

### Google service account key
1. Go to Google Cloud Console > IAM & Admin > Service Accounts
2. Create a new key for the existing service account (JSON format)
3. Download the new JSON file to the project directory
4. Update `JSON_KEY_FILE` in `.env` with the new filename
5. Delete the old JSON key file from disk and revoke it in Cloud Console
6. Verify: `python verify_sheets.py`

### Pushover keys
1. Log in at [pushover.net](https://pushover.net) and regenerate the application token
2. Update `PUSHOVER_API_TOKEN` in `.env`
3. Verify: `python garmin_sync.py --sleep-notify`

### TOTP secret (voice logger)
1. Generate a new secret: `python voice_logger/setup_totp.py`
2. Update `TOTP_SECRET` in Vercel environment variables
3. Re-scan the QR code with your authenticator app
4. Redeploy the voice logger on Vercel

### Anthropic / Nutritionix API keys
1. Regenerate at the respective provider's dashboard
2. Update in Vercel environment variables
3. Redeploy the voice logger

## If Credentials Are Exposed

1. **Assume compromised immediately** -- bots scrape public repositories within minutes
2. Rotate the exposed credential using the steps above -- do NOT reuse the old value
3. Check access logs where available (Google Cloud audit logs, Garmin account activity, Pushover delivery history)
4. If a service account key was exposed: revoke it in Google Cloud Console, then create a new one
5. If the TOTP secret was exposed: regenerate it and re-enroll your authenticator app
6. Run `git log --all --full-history -- .env *.json` to confirm secrets were never committed to history
