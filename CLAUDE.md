# Health Tracker — Claude Rules

## Rules (Loaded from .claude/rules/)

Detailed rules are in scoped files. Claude Code loads them based on context. Import all:

@.claude/rules/sheets-formatting.md
@.claude/rules/sheets-api.md
@.claude/rules/garmin-data.md
@.claude/rules/data-pipeline.md
@.claude/rules/verification.md
@.claude/rules/security.md
@.claude/rules/setup-scripts.md

---

## Memory & Session Continuity (Non-Negotiable)

At the **start of every session**:
1. Read `MEMORY.md` from the auto-memory directory and summarize what was last worked on and what is pending
2. Read `TODO.md` from the project root and summarize what's in progress, blocked, and pending
3. Use this context to continue work without the user having to re-explain anything

At the **end of every session** (or any time significant work is completed):
1. Update `MEMORY.md` with what was accomplished, what is pending, and any key decisions made
2. Update `TODO.md` — check off completed items, add new items, move items between sections
3. Keep it concise — bullet points, not paragraphs

This ensures context survives folder moves, IDE restarts, and new sessions.

---

## Work Tracking (Non-Negotiable — BILLING REQUIREMENT)

Work tracking exists to support client billing. Every task must have defensible time records.

### Three-File System
| File | Purpose | Format |
|------|---------|--------|
| `.today_work.md` | Real-time append-only log (all windows write as they go) | Timestamped entries with clock-time ranges |
| `WORKLOG.md` | Structured daily table (append-only, never overwrite) | Markdown table with Task, Category, Time, Description |
| `BILLING.md` | Client-facing weekly time report | Hours rounded to 0.5h, client-speak descriptions |

### Categories (fixed vocabulary)
`feature` | `fix` | `refactor` | `analysis` | `docs` | `infra` | `research` | `debug`

### Rules
1. **Write after every billing line item** — a deliverable is: a script that runs, a tab that passes verify, a file written, a finding documented. Write to `.today_work.md` immediately, not at session end.
2. **Include clock-time ranges** — run `date` at task start and completion. Include both in the entry: `### [5:04 PM -> 6:30 PM] Task name (~1h 25m)`
3. **Checkpoint before compaction** — when conversation is long (~30+ messages), do a forced write to `.today_work.md` with `[CHECKPOINT]` tag to preserve history.
4. **Multi-window coordination** — all windows append to the same `.today_work.md`. On window start, read it to see what other windows accomplished.
5. **"Done for the day" writes all four files + displays comprehensive narrative** — SESSION.md, WORKLOG.md, BILLING.md, and **append to WORK_HISTORY.md**. Then display in chat a **full detailed narrative summary** of ALL work from session start to end. Each task gets a full paragraph (3-8 sentences) with what/why/how/outcome and specific numbers. End with a grand totals table (Session | Date | Hours | Categories), category breakdown, and key deliverables line. This narrative is the #1 deliverable of the end-of-day process — never use brief bullets. If work extends past midnight, still include it. The same narrative appended to WORK_HISTORY.md becomes the permanent record. Clears `.today_work.md` and deletes `.session_start`. Day-level only.
6. **"Let's go" captures start time** — writes to `.session_start`, reads `.today_work.md` and `WORKLOG.md` for context. Runs security check. Day-level only.
7. **"Start" opens a window/task** — reads `.today_work.md` for cross-window context, notes task focus, runs `date` for timestamp. Does NOT create `.session_start` or run security check.
8. **"End" closes a window/task** — appends any unreported work to `.today_work.md`. Does NOT run reconciliation, write WORKLOG/BILLING/SESSION, clear `.today_work.md`, or delete `.session_start`.

### End-of-Day Reconciliation (Non-Negotiable)
When the user says "done for the day," before writing the final summary, run a reconciliation sweep to catch work from other windows that may not have logged properly:

1. **Git history scan** — run `git log --since="<session_start_time>" --oneline` and `git diff --stat HEAD~N` to see all commits and file changes made during the session. Any committed work not reflected in `.today_work.md` gets added.
2. **File modification scan** — run `git diff --name-only` (unstaged) and `git diff --cached --name-only` (staged) plus check modification timestamps of key files (`*.py`, `*.md`, config files). Any significantly modified files not mentioned in `.today_work.md` get flagged.
3. **Cross-reference** — compare the union of git history + modified files against `.today_work.md` entries. For each unlogged item:
   - Estimate time based on file size/complexity of changes
   - Add a `[RECONCILED]` tagged entry to `.today_work.md` before compiling the final summary
   - Flag it in the chat summary so the user can adjust the time estimate if needed
4. **Display reconciliation diff** — before finalizing, show the user: "Found X items from other windows not in today's log: [list]. Adding them with estimated times. Adjust if needed."
5. **Then compile** — only after reconciliation is complete, write WORKLOG.md, BILLING.md, and SESSION.md with the full picture.

---

## Project Overview

**Health Tracker** — daily habit tracking with automatic Garmin data sync to Google Sheets.

### Stack
- **Notion** — daily habit log (manual checkboxes, notes, images)
- **Google Sheets** — automated data storage and analysis
- **Python script** (`garmin_sync.py`) — pulls Garmin data daily, writes to Google Sheets
- **Windows Task Scheduler** (current) / **launchd plist** (macOS) / **cron** (Linux) — runs via two daily triggers (12:05 AM full sync + 11:00 AM sleep notify)

### Key Files
- `garmin_sync.py` — main sync script
- `requirements.txt` — all Python dependencies for clean installs on any machine
- `.env` — non-sensitive config (email, sheet ID, JSON key filename — filename only, no absolute path)
- `reference/HEALTH_INTEL.md` — evaluated health claims index (used by `/update-intel` skill)
- `reference/health_knowledge.json` — structured knowledge base loaded at runtime by `overall_analysis.py` for cognition/energy-framed insights
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
| macOS | launchd | `~/Library/LaunchAgents/com.healthtracker.garmin_sync.plist` |
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
- Target: 24/7 Mac Mini running garmin_sync.py via launchd (12:05 AM full sync + 11:00 AM sleep notify)
- Mac Mini Energy Saver: set to never sleep, enable "wake for network access"
- If Mac Mini is offline, use `--date` flag to backfill missed days from any other machine

### Risk: Mac Mini hardware failure
- Mitigation: Google Sheets is the source of truth — all data lives in the cloud regardless of local machine
- Secondary mitigation: SQLite local database (parallel write) backed up to iCloud/Google Drive
- Recovery: restore project folder from backup, re-run `pip install -r requirements.txt`, re-set keyring password

---

## Lifetime Data Storage Strategy

### Google Sheets capacity (not a concern)
- 70 years x 365 days = 25,550 rows across all tabs
- Total cells ~ 2.4 million — well within Google Sheets' 10 million cell limit
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

### Google Sheets -> database migration
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
