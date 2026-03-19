# Health Tracker — Claude Rules

## Spreadsheet Readability (Non-Negotiable — FUNCTIONAL REQUIREMENT)

Every cell in every tab must be fully readable without manual resizing. This is not cosmetic — it is a functional requirement and the #1 priority for any spreadsheet work.

### Column Widths
- Set explicit widths for EVERY column when creating or modifying any tab
- Short numbers/scores: 60-80px | Labels: 80-120px | Dates: 100px
- Short text (names, meals): 200px min | Notes/sentences: 250-350px | Long analysis: 350-500px
- Add to `WIDTH_OVERRIDES` in `reformat_style.py` when auto-sizing is insufficient

### Row Heights
- Any tab with free-text or wrapped columns MUST use `autoResizeDimensions` on data rows
- Add the tab to the auto-resize list in `reformat_style.py` (currently: Sleep, Nutrition)
- Fixed 24px height is ONLY acceptable for purely numeric/short-label tabs

### Alignment (Three-Tier Rule)
- **Short labels/categorical** (Day, Date, single-word values like "Good"/"High"/"Optimal"): CENTER — these are lookup values, not prose
- **Long-form text** (Notes, Analysis, Descriptions, Assessments, Recommendations): LEFT + TOP + WRAP — prose needs left alignment to read naturally
- **Numeric/scores**: CENTER
- **Checkboxes** (Daily Log D-J): CENTER — boolean toggles must be visually centered in their cells
- Always set explicitly — never rely on Sheets defaults
- Enforce via `FORCE_CENTER_COLS` in `reformat_style.py` for any text column that should stay centered despite auto-detection

### Process
1. When creating a new tab: set column widths in the setup script for every column
2. When adding columns: add width overrides if auto-sizing won't fit the content
3. When running reformat: verify the tab is in the auto-resize list if it has text columns
4. After any structural change: verify all content is readable at the set widths
5. The user must NEVER have to ask for resizing — anticipate it

---

## Spreadsheet Design Ruleset (Non-Negotiable — VISUAL STANDARD)

These rules define the visual design of every tab. They are checked and enforced after every structural change (column add/remove/move, tab creation, row builder update). The user must NEVER have to ask for design corrections — anticipate and apply them automatically.

### Tab Order (Non-Negotiable)
Tabs must always appear in this exact order. Enforce after any tab creation or restore operation.

1. **Daily Log** — primary daily input
2. **Overall Analysis** — daily readiness assessment
3. **Sleep** — sleep metrics and notes
4. **Garmin** — raw Garmin wellness data
5. **Nutrition** — meal tracking and macros
6. **Session Log** — workout sessions
7. **Strength Log** — weight training sets
8. **Analysis** — aggregate formulas and correlations
9. **Charts** — embedded trend charts (HRV, sleep, body battery, etc.)
10. **Raw Data Archive** — full Garmin export mirror
11. **Key** — color legend and reference (always last)

### Cell Background Color Hierarchy (in priority order)
1. **Color-graded cells** — cells with conditional formatting gradients or discrete color rules (e.g., Readiness Score red-green, Readiness Label Optimal=green/Poor=red, Sleep Analysis Score, Bedtime bands). These take highest priority — no other background color overrides them.
2. **Yellow manual-entry cells** — any column where the user types data manually gets light yellow background `{"red": 1.0, "green": 1.0, "blue": 0.8}`. This includes: Notes, Cognition (1-10), Cognition Notes, Perceived Effort, Post-Workout Energy, all Nutrition meal columns, all Daily Log subjective columns. When columns move between tabs, the yellow follows them.
3. **Weekly row banding** — all remaining cells (not color-graded, not yellow) alternate between white and light grey on a weekly basis (Sunday–Saturday). One week is white, the next is light grey `{"red": 0.95, "green": 0.95, "blue": 0.95}`. This groups data visually by week.
4. **Header row** — tab-colored background with white bold text. Never overridden by banding.

### Weekly Banding Rules
- Weeks run Sunday–Saturday (ISO week starting Sunday)
- The most recent week is white, the previous week is grey, alternating backwards
- Banding applies to ALL data cells that don't have a higher-priority color (color grade or yellow)
- Banding is applied/refreshed whenever data is written or structural changes are made
- Implementation: calculate week number from date column, apply alternating colors

### Design Audit Checklist (run after EVERY structural change)
After any column add/remove/move, tab creation, or row builder change:
1. **Yellow check**: every manual-entry column has yellow background applied
2. **Gradient check**: every numeric score/metric column has appropriate color grading
3. **Banding check**: weekly alternating white/grey is applied to non-graded, non-yellow cells
4. **No yellow on auto columns**: auto-populated columns must NOT have yellow background
5. **Column width check**: all columns have explicit widths set
6. **Wrap check**: text-heavy columns have WRAP enabled
7. **Alignment check**: short labels/categorical=CENTER, long text=LEFT+TOP+WRAP, numeric=CENTER

### Current Color-Graded Columns (update when adding new ones)
- **Sleep tab**: Sleep Analysis Score, Total Sleep, Time in Bed, Deep/Light/REM/Awake min, Deep%/REM%, Sleep Cycles, Awakenings, Avg HR, Avg Respiration, Overnight HRV, Body Battery Gained, Bedtime (discrete bands)
- **Overall Analysis tab**: Readiness Score (C, gradient 1-10), Readiness Label (D, discrete Optimal/Good/Fair/Low/Poor), Confidence (E, discrete High/Medium-High/Medium/Low), Cognition (H, gradient 1-10)
- **Session Log**: (none currently — add if needed)

### Current Manual-Entry (Yellow) Columns
- **Sleep**: G (Notes)
- **Overall Analysis**: H (Cognition 1-10), I (Cognition Notes)
- **Nutrition**: F-N (meal columns), P (Notes)
- **Session Log**: D (Perceived Effort), E (Post-Workout Energy), F (Notes)
- **Daily Log**: C-V (all subjective columns)

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
2. **Include clock-time ranges** — run `date` at task start and completion. Include both in the entry: `### [5:04 PM → 6:30 PM] Task name (~1h 25m)`
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

## Spreadsheet Edit Rules (Non-Negotiable)

After **every** write, update, or structural change to any Google Sheets tab:
1. Run `python verify_sheets.py` (or `python verify_sheets.py --tab <TabName>` for a single tab)
2. All tabs must report PASS before the task is considered complete
3. If any tab reports FAIL or WARNING — stop, diagnose, and fix before telling the user the task is done

---

## Formatting Verification (Non-Negotiable)

After **every** script that applies or could affect conditional formatting:
1. Run `python verify_formatting.py` (or call `verify_and_repair(wb)` in code)
2. All tabs must report PASS for conditional formatting rules AND numeric data types
3. If any tab reports FAIL — auto-repair fixes numeric types AND re-applies rules, then re-verifies
4. After auto-repair, if still FAIL — stop and investigate manually

### What it checks (two layers):
1. **Rules exist** — all expected conditional format rules are present on the correct columns with correct thresholds
2. **Data types are numeric** — spot-checks graded columns to verify values are actual numbers, not text strings. Gradient formatting silently ignores text cells even if the text looks like "82". This is the #1 cause of "rules exist but colors don't show."

### What auto-repair does:
1. Converts all text-as-number cells to actual numbers (batch write with USER_ENTERED)
2. Re-applies conditional format rules for the failing tab

### Already integrated (runs automatically):
- `garmin_sync.py` — calls `verify_and_repair(wb)` at end of main(); also calls `fix_sleep_numeric_types()` before color grading
- `reformat_style.py` — calls `verify_and_repair(wb)` at end of main()
- `overall_analysis.py` — calls `verify_tab_formatting` + repair after weekly banding
- `setup_overall_analysis.py` — calls `verify_tab_formatting` in verify()

### Critical data type rule:
- When writing rows with BOTH text (dates, times) AND numbers: write full row with `RAW`, then re-write numeric columns with `USER_ENTERED`
- NEVER use `USER_ENTERED` for an entire row containing dates ("YYYY-MM-DD") or times ("HH:MM") — Sheets converts them to serials
- NEVER leave numeric columns as `RAW` — gradient conditional formatting won't render on text

### When adding new color-graded columns:
1. Add the grading logic in the relevant setup/apply function
2. Add the column to `EXPECTED_RULES` in `verify_formatting.py`
3. Ensure the write function stores values as numbers (not RAW text)
4. Run `python verify_formatting.py --repair` to confirm it passes
5. Never skip this step, even for "small" changes — misalignment compounds silently

---

## Sheets -> SQLite -> Dashboard Sync (Non-Negotiable)

Google Sheets is the source of truth. SQLite is the local mirror. The dashboard reads from SQLite.

### Automatic (already wired):
- `garmin_sync.py` writes to both Sheets AND SQLite in the same run (garmin, sleep, nutrition, session_log, archive)
- `overall_analysis.py` writes to both Sheets AND SQLite after every analysis
- `garmin_sync.py` exports the dashboard at end of pipeline

### When to run a full sync (`python sheets_to_sqlite.py`):
- After any **manual edit** to Google Sheets (user typed data, column corrections, bulk fixes)
- After any **structural change** (column add/remove/move, tab creation, schema migration)
- After running **import scripts** that write to Sheets but not SQLite (e.g., `parse_garmin_export.py`, `parse_fit_files.py`)
- After running **backfill** scripts (`backfill_history.py`)
- At **end of day** if any Sheets-only work was done during the session

### After every full sync, refresh the dashboard:
```
python sheets_to_sqlite.py && python dashboard/export_dashboard_data.py
```

### Tables synced (8 total):
Garmin | Sleep | Nutrition | Session Log | Daily Log | Strength Log | Overall Analysis | Raw Data Archive

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

## Health Profile PHI Security (Non-Negotiable)

The `profiles/` directory contains Protected Health Information (PHI). These rules prevent PHI from leaking into tracked files, external services, or cross-project logs.

### PHI Boundaries
| Location | PHI Allowed? | Rule |
|----------|-------------|------|
| `profiles/` | Yes | Gitignored — the PHI boundary |
| Google Sheets | Yes | User's private cloud data store |
| Pushover notifications | **Sanitized only** | Use `sanitize_for_notification()` — strips condition/med names |
| `.claude/projects/*/memory/` | **NO** | Counts and categories only, never names or values |
| `.today_work.md`, `WORKLOG.md`, `BILLING.md` | **NO** | Generic: "Updated profile with lab results" |
| Commit messages | **NO** | "Updated health profile" not "Added ADHD diagnosis" |
| `SESSION.md` | **NO** | Capabilities built, not medical details |
| `CLAUDE.md` | **NO** | Rules and structure, not data |
| Terminal / stdout | **Counts only** | "2 conditions, 12 biomarkers" — never names or values |
| `reference/` (committed) | **NO** | `/update-intel` guard rejects medical docs |

### Skill Cross-Contamination Guards
| Skill | Guard | Action |
|-------|-------|--------|
| `/update-intel` | File from `profiles/` or `Priv -` dir | Reject -> redirect to `/update-profile` |
| `/update-profile` | File from `reference/transcripts/` or `reference/books/` | Reject -> redirect to `/update-intel` |
| `/verify-intel` | First-person medical claim ("my blood work", "I was diagnosed") | Warn -> redirect to `/update-profile` |

### Key Files
- `profile_loader.py` — committed loader module (no PHI, prints counts only)
- `profiles/<name>/profile.json` — gitignored master profile
- `profiles/<name>/profile_summary.md` — gitignored token-efficient summary
- `.claude/skills/update-profile/SKILL.md` — committed ingestion skill definition

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

## Post-Change Verification (Non-Negotiable)

After any structural change — renames, file/folder restructuring, schema migrations, column reordering, major refactors, dependency changes, or any change that touches multiple files for the same logical operation — the plan MUST include a full verification cycle as the final step. Do not wait for the user to ask for this.

**Structural changes that trigger mandatory verification:**
- Project or file renames (names, paths, references)
- Database schema changes (columns added/removed/reordered)
- Google Sheets tab structure changes (headers, column order)
- File or folder moves/reorganization
- Configuration key renames
- Dependency upgrades that change APIs
- Any multi-file find-and-replace operation

**The verification cycle for this project:**
1. **Import/load check** — `python -c "import garmin_sync; import sqlite_backup"` — all modules load without errors
2. **Reference sweep** — grep the entire codebase for stale references to old names/paths/values (zero results required)
3. **Sheets verification** — `python verify_sheets.py` — all tabs must report PASS
4. **Functional test** — `python garmin_sync.py --today` — full pipeline runs end-to-end (Garmin API -> Sheets -> SQLite -> Overall Analysis -> Dashboard)
5. **Automated systems check** — `python garmin_sync.py --sleep-notify` — notification pipeline works, user confirms receipt on phone
6. **Scheduler check** — confirm Task Scheduler tasks exist, point to correct paths, and use **full python path** (never bare `python`). After registering tasks, trigger `schtasks /run /tn "Health Tracker - Garmin Sync"` and verify `garmin_sync.log` shows a successful run. "Ready" status alone is not proof of working — a task can show Ready but fail on every execution.

**Rules:**
- Never declare a structural change "done" without completing the verification cycle
- If verification reveals additional issues, fix them and re-run the cycle
- Include verification as an explicit step in every plan that involves structural changes
- The cost of verifying is always lower than the cost of silent breakage discovered later

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

**Health Tracker** — daily habit tracking with automatic Garmin data sync to Google Sheets.

### Stack
- **Notion** — daily habit log (manual checkboxes, notes, images)
- **Google Sheets** — automated data storage and analysis
- **Python script** (`garmin_sync.py`) — pulls Garmin data daily, writes to Google Sheets
- **Windows Task Scheduler** (current) / **launchd plist** (macOS) / **cron** (Linux) — runs the script daily at 8:00 PM

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

### Garmin export timezone handling (export file — string timestamps)
- `sleepStartTimestampGMT` and `sleepEndTimestampGMT` are TRUE UTC — always convert to local before displaying
- Compute per-day UTC offset from UDS record: `wellnessStartTimeLocal - wellnessStartTimeGmt` in hours
- This automatically handles EST (-5) vs EDT (-4) DST transitions — never hardcode a single offset
- Default fallback if UDS record missing: -5 (EST)

### Garmin API timezone handling (Connect API — epoch timestamps)
- NEVER use `sleepStartTimestampLocal` / `sleepEndTimestampLocal` — these are NOT reliable local times
- ALWAYS use `sleepStartTimestampGMT` / `sleepEndTimestampGMT` with `datetime.fromtimestamp(epoch_ms / 1000)` (no tz arg)
- `fromtimestamp()` without a tz argument converts UTC epoch to system local time — this is the correct behavior
- Bug history: v2.1 used "Local" fields without `tz=timezone.utc`, producing bedtime/wake times shifted by the timezone offset (4-5h). Downstream impact: ±15 point sleep analysis score swing, inverted color grading, wrong analysis text

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
