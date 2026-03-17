# NS Habit Tracker — Claude Rules

## Memory & Session Continuity (Non-Negotiable)

At the **start of every session**:
1. Read `MEMORY.md` from the auto-memory directory and summarize what was last worked on and what is pending
2. Use this context to continue work without the user having to re-explain anything

At the **end of every session** (or any time significant work is completed):
1. Update `MEMORY.md` with what was accomplished, what is pending, and any key decisions made
2. Keep it concise — bullet points, not paragraphs

This ensures context survives folder moves, IDE restarts, and new sessions.

## Spreadsheet Edit Rules (Non-Negotiable)

After **every** write, update, or structural change to any Google Sheets tab:
1. Run `python verify_sheets.py` (or `python verify_sheets.py --tab <TabName>` for a single tab)
2. All tabs must report PASS before the task is considered complete
3. If any tab reports FAIL or WARNING — stop, diagnose, and fix before telling the user the task is done
4. Never skip this step, even for "small" changes — misalignment compounds silently

---

## Security Rules (Non-Negotiable)

### I will NEVER:
- Ask the user to type or paste a password, API key, private key, or secret into this conversation
- Ask the user to share a new credential after they've rotated it
- Read a credentials file (JSON, .env, .pem, or similar) — doing so exposes its contents in the VSCode diff panel
- Ask the user to confirm what a new password or key is

### When credentials need to be created or updated:
- Tell the user exactly what to do and where, then have them do it themselves in a text editor or Command Prompt
- For passwords: provide the exact `keyring` command for them to run in Command Prompt — they run it, never paste the result back here
- For JSON key files: tell the user to update the filename in `.env` themselves using Notepad
- Verify everything works by running the script directly — never by reading credential files

### If a credential is accidentally exposed in this conversation:
1. Flag it immediately and clearly
2. Tell the user exactly what to rotate (password or key) and the steps to do it
3. Remind them NOT to share the new credential here
4. Confirm the fix by running the script

### The user should never:
- Paste passwords, keys, or secrets into this chat
- Share new credentials after rotating them
- Copy/paste the contents of any JSON key file here

### Security check — run at the START of every session:
Before doing any work, I must:
1. Confirm which credentials are in use (Garmin password in keyring, Google key filename in .env)
2. Check if any credentials were exposed in the previous session and flag any that still need rotating
3. Run `garmin_sync.py` to verify everything works without reading any credential files
4. Report the security status clearly before proceeding
5. If anything is unresolved, stop and address it before moving on

### Security check — run DURING the session any time I edit a file:
- Before editing any file, confirm it contains no credentials
- If a system reminder or diff reveals a credential, flag it immediately and follow the exposure protocol above

---

## Self-Verification Rules (Non-Negotiable)

After every action I take, I must verify the outcome matches what I claimed:

### For script changes:
- Run the script and confirm the output matches the expected result
- Do not tell the user something is done until the output proves it

### For Google Sheets changes:
- Query the sheet directly to confirm headers, data, or structure match what was described
- Never assume a write succeeded — verify by reading back the result

### For file edits:
- After editing, confirm the specific change is present in the file
- Never tell the user a file was updated without verifying the change took effect

### General rule:
- If what I said I did does not match what actually happened, flag it immediately and fix it before moving on
- Do not rely on the user to catch my mistakes — catch them myself first

---

## Setup Script Rules (Non-Negotiable)

All setup scripts (setup_analysis.py, setup_charts.py, etc.) must be **idempotent** — running them multiple times must always produce the correct end state regardless of current state.

### Never write "skip if exists" logic for tabs or headers:
- If a tab exists → update its headers in place, do not skip
- If a header row exists → overwrite it with the full correct header list
- If a tab doesn't exist → create it with the correct headers

### Before writing any setup or migration code:
1. State explicitly what the current state of the system is (which tabs exist, what headers they have)
2. Confirm the code handles both the "first run" case AND the "already exists" case
3. Never assume a tab is new — always write update logic for existing tabs

### When adding new columns to an existing tab:
- The setup function must update the full header row in place, not skip because the tab exists
- Data rows are never touched — only the header row (row 1) is updated

### Every setup script must include a verify_setup() function:
- Runs automatically at the end of main()
- Independently reads back each tab's actual headers from the sheet
- Compares them to the expected headers and prints PASS or FAIL for each tab
- If any tab fails, the script must report exactly what is missing or wrong
- The script is not considered complete until all tabs print PASS

---

## Project Overview

**NS Habit Tracker** — daily habit tracking with automatic Garmin data sync to Google Sheets.

### Stack
- **Notion** — daily habit log (manual checkboxes, notes, images)
- **Google Sheets** — automated data storage and analysis
- **Python script** (`garmin_sync.py`) — pulls Garmin data daily, writes to Google Sheets
- **Windows Task Scheduler** (current) / **launchd plist** (macOS) / **cron** (Linux) — runs the script daily at 8:00 PM

### Key Files
- `garmin_sync.py` — main sync script
- `requirements.txt` — all Python dependencies for clean installs on any machine
- `.env` — non-sensitive config (email, sheet ID, JSON key filename — filename only, no absolute path)
- `CLAUDE.md` — this file

### Credentials Storage
- Garmin password: stored in **system keyring** (`keyring` library) — Windows Credential Manager on PC, macOS Keychain on Mac, libsecret on Linux. Never in any file.
- Google service account key: stored as a JSON file in this folder (never read by Claude)
- All other config: stored in `.env`

### Habits Tracked
1. Wake up at 9:30 AM
2. No screen time in the morning
3. Creatine & Hydrate
4. 20 min walk + breathing exercises
5. Physical Activity
6. No screens 1hr before bed
7. Go to bed at 10 PM

### Garmin Data Pulled
- HRV (overnight), HRV 7-day average
- Resting HR, daily avg HR
- Sleep duration, score, stages (deep/light/REM), cycles, awakenings, respiration
- Body battery (current, at wake, high, low)
- Steps, floors ascended, intensity minutes
- Total/active/BMR calories burned, stress level
- Activity name, type, distance, duration, avg HR, max HR, calories, elevation, speed, HR zones, training effect

---

## Portability & Cross-Platform Compatibility

**This project is designed to run identically on Windows, macOS, and Linux.**

### What is cross-platform by design
- All Python libraries (`garminconnect`, `gspread`, `keyring`, `python-dotenv`, `python-docx`) work on all three OS
- `keyring` abstracts credential storage: Windows Credential Manager / macOS Keychain / Linux libsecret — same API call on all platforms
- Google Sheets and Garmin Connect are cloud-based — no device dependency
- All file paths in code use `Path(__file__).parent` (dynamic, relative to script location) — never hardcoded absolute paths
- `.env` stores only the JSON key **filename** (not full path) — resolved at runtime relative to the script directory

### Platform-specific setup (scheduler only)
| Platform | Scheduler | Config |
|---|---|---|
| Windows | Task Scheduler | GUI or XML task file |
| macOS | launchd | `~/Library/LaunchAgents/com.nshabit.garmin_sync.plist` |
| Linux | cron | `0 20 * * * /usr/bin/python3 /path/to/garmin_sync.py` |

### Migrating to a new machine (checklist)
1. Copy project folder (or `git clone` from private GitHub repo)
2. Install Python 3.10+
3. `pip install -r requirements.txt`
4. Copy the Google service account JSON key file into the project folder
5. `.env` needs no changes — `JSON_KEY_FILE` is already a filename-only relative reference
6. Re-store Garmin password in the new machine's keyring: `python -c "import keyring; keyring.set_password('garmin_connect', 'EMAIL', 'PASSWORD')"` — user runs this themselves, never shared in chat
7. Set up the scheduler for the new platform (see table above)
8. Verify: `python garmin_sync.py --today`
9. If any days were missed during migration: `python garmin_sync.py --date YYYY-MM-DD`

### Planned primary host: Mac Mini (always-on)
- Target: 24/7 Mac Mini running garmin_sync.py via launchd at 8 PM daily
- Mac Mini Energy Saver: set to never sleep, enable "wake for network access"
- If Mac Mini is offline, use `--date` flag to backfill missed days from any other machine

### Risk: Mac Mini hardware failure
- Mitigation: Google Sheets is the source of truth — all data lives in the cloud regardless of local machine
- Secondary mitigation: SQLite local database (parallel write) backed up to iCloud/Google Drive
- Recovery: restore project folder from backup, re-run `pip install -r requirements.txt`, re-set keyring password

---

## Lifetime Data Storage Strategy

### Google Sheets capacity (not a concern)
- 70 years × 365 days = 25,550 rows across all tabs
- Total cells ≈ 2.4 million — well within Google Sheets' 10 million cell limit
- No action needed for capacity reasons

### Long-term database options (when analytics are needed)

**SQLite** — recommended first step
- Single `.db` file, Python built-in, zero maintenance
- Backs up automatically via iCloud/Google Drive sync
- Handles billions of rows, fast for all health queries
- Fully portable: copy the file to any machine

**PostgreSQL + TimescaleDB** — recommended for Mac Mini
- Purpose-built for time-series health data
- Automatic compression, hypertables partition by time
- Pairs with Grafana for dashboards
- Best for: multi-year trend analysis, correlation queries

**Supabase** — cloud PostgreSQL alternative
- Managed, accessible anywhere, free up to 500MB (~50 years of data)
- REST API, web dashboard
- Risk: free tier pauses inactive projects

**DuckDB** — best for analytical queries
- Columnar database, runs complex trend queries instantly
- Can query CSV files and Google Sheets directly
- No server needed

### Google Sheets → database migration
- One Python script reads all tabs and inserts into target database
- All historical data migrates in one run
- No data loss — Google Sheets remains intact as a backup

---

## Historical Import Workflow (parse_garmin_export.py)

Use this script to import all historical Garmin data from a local export file into Google Sheets.

### One-command import (all phases run automatically)
```
python parse_garmin_export.py
```
Phases run in order:
1. Parse Garmin export JSON -> write all tabs (Garmin, Sleep, Session Log, Raw Data Archive)
2. Fix existing bad data (stress sentinels, HR=0 placeholders)
3. Fix data types (datetime serials -> text, numeric strings -> numbers, column misalignment)
4. Fill missing cells (body battery, zones, sleep body battery gained, bedtime/wake time)
5. Reformat and sort all tabs newest-to-oldest

### Available flags
| Flag | Purpose |
|---|---|
| `--dry-run` | Parse and print without writing to Sheets |
| `--start YYYY-MM-DD` | Import from this date onward |
| `--end YYYY-MM-DD` | Import up to this date |
| `--fix-data` | Run Phase 2 only (fix bad sentinel values) |
| `--fix-types` | Run Phase 3 only (fix data types) |
| `--fill-missing` | Run Phase 4 only (fill blank cells) |
| `--reformat` | Run Phase 5 only (formatting + sort) |
| `--restore` | Restore from Raw Data Archive |

### Key files involved
- `parse_garmin_export.py` — historical import script
- `garmin_sync.py` — daily sync script (also calls sort after every write)
- `backfill_history.py` — backfill via Garmin Connect API (not export file)

---

## Technical Rules Learned (Non-Negotiable)

These rules were learned from real bugs. Apply them whenever touching Google Sheets data or Garmin exports.

### Google Sheets API data types
- NEVER use `value_input_option="USER_ENTERED"` for time strings ("HH:MM") — Sheets parses them as decimal fractions (e.g., 0.3854)
- NEVER use `USER_ENTERED` for date strings ("YYYY-MM-DD") — Sheets parses them as date serials (e.g., 46084)
- Use `value_input_option="RAW"` for all text/time/date strings that must remain plain text
- Use `value_input_option="USER_ENTERED"` only for numbers that need formula evaluation
- Apply `"type": "TIME"` format in reformat_sheets so HH:MM text displays correctly in time columns

### Google Sheets sorting with mixed types
- Mixed column (some cells = number serial, some = "YYYY-MM-DD" text) will NOT sort correctly — numbers and text sort in separate groups
- Before every sort: normalize the entire Date column to plain text using `RAW` mode
- Sort only after normalization is confirmed complete
- Pattern in `sort_sheet_by_date_desc()`: read column with FORMATTED_VALUE -> rewrite with RAW -> then sort

### Garmin export unit conversions
- Distance: stored in centimeters -> divide by 160,934.4 for miles
- Duration: stored in milliseconds -> divide by 60,000 for minutes
- Speed: stored as (m/s) * 10 -> multiply by 2.23694 for mph (or / 44.704 for mph directly)
- Elevation: stored in centimeters -> divide by 100 for meters
- HR zone time: stored in seconds -> divide by 60 for minutes

### Garmin export timezone handling
- `sleepStartTimestampGMT` and `sleepEndTimestampGMT` are TRUE UTC — always convert to local before displaying
- Compute per-day UTC offset from UDS record: `wellnessStartTimeLocal - wellnessStartTimeGmt` in hours
- This automatically handles EST (-5) vs EDT (-4) DST transitions — never hardcode a single offset
- Default fallback if UDS record missing: -5 (EST)

### Garmin export field locations
- HR zones: `hrTimeInZone_1` through `hrTimeInZone_5` on activity records (in seconds)
- Body battery gained during sleep: `statsType == "DURINGSLEEP"` in `wellnessBodBattStat` array
- Sleep bedtime/wake time: `sleepStartTimestampGMT` / `sleepEndTimestampGMT` on sleep records
- Stress qualifier: `averageStressLevel` on UDS records (sentinel -1 or -2 = no data, replace with "")
- Resting HR: sentinel 0 = no data, replace with ""

### Google Sheets batch writes (quota)
- NEVER use per-cell `update_cell()` in a loop — hits 60-req/min quota after ~60 cells
- Always batch: read entire column -> modify list -> write entire column in ONE `sheet.update(range, values)` call
- For mixed cell types in same write: use `update_cells(cell_list, value_input_option=...)` with a Cell object list

### Column alignment discipline
- Every tab's row-build function must include ALL columns in exact header order, including empty placeholder columns ("" for manual-entry fields)
- If a placeholder column is missing from the write, every column after it shifts left — data lands in wrong column
- After any column structure change: verify column count matches header count before writing
- Session Log specific: Zone Ranges (col S) is manual — always write `""` as placeholder, then "Garmin Export" for Source (col T), then elevation for Elevation (col U)

### Sheets datetime serial conversion
- Sheets epoch: December 30, 1899
- Convert serial to datetime: `base + timedelta(days=int(serial)) + timedelta(seconds=round(frac*86400))`
- Where `frac = serial - int(serial)` and `base = datetime(1899, 12, 30)`
- Always store datetime as plain text "YYYY-MM-DD HH:MM" using RAW mode — never let Sheets re-parse it

### Windows terminal compatibility
- Windows console (cp1252) cannot encode Unicode arrows like `->` (U+2192) — use ASCII `->` instead
- Interactive `input()` prompts fail when piped: use `echo "" | python script.py` or add `--no-prompt` flag
- Always test scripts in terminal before assuming they work

### Duplicate detection for multi-activity days
- Do NOT use date-only as duplicate key for Session Log — multiple workouts per day are valid
- Use `(date, activity_name)` as the composite key for deduplication

---
