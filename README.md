# NS Habit Tracker — Project Overview

A personal health tracking system that automatically pulls Garmin data into Google Sheets daily, combined with manual habit logging and subjective daily ratings. Built to answer one question: **what actually improves your HRV, sleep, and wellbeing?**

---

## What It Does

1. **Auto-syncs Garmin data** every evening at 8 PM — sleep, HRV, steps, body battery, workouts, stress, calories — all written to Google Sheets automatically
2. **Auto-backfills gaps** — if the scheduler misses a day (reboot, network issue), the next run detects and backfills any missing dates from the last 7 days
3. **Tracks 7 daily habits** in the Daily Log tab
4. **Daily subjective check-ins** (midday + evening) capture what Garmin can't — mood, brain fog, stress, overall day quality
5. **Analysis tab** runs live correlations between habits and health metrics

---

## Stack

| Layer | Tool | Purpose |
|---|---|---|
| Wearable | Garmin watch | Collects all biometric data |
| Sync script | `garmin_sync.py` (Python) | Pulls from Garmin Connect API, writes to Sheets |
| Storage | Google Sheets | All data lives here — cloud, accessible anywhere |
| Manual input | Google Sheets (Daily Log + Nutrition tabs) | Habits, mood, brain fog, day ratings, food |
| Scheduler | Windows Task Scheduler (PC) / launchd (Mac) | Runs sync script at 8 PM daily |
| Credentials | Windows Credential Manager / macOS Keychain | Garmin password stored securely, never in files |

---

## Google Sheets — Tab Guide

| Tab | Auto or Manual | What's In It |
|---|---|---|
| **Garmin** | Auto | One row per day. Sleep score, HRV, resting HR, sleep duration, body battery, steps, stress, calories, workout summary |
| **Sleep** | Auto | Detailed nightly sleep: stages (deep/light/REM), bedtime, wake time, HRV overnight, score, feedback |
| **Nutrition** | Auto + Manual | Calories burned (auto). Manual: food eaten, macros, water |
| **Session Log** | Auto + Manual | One row per workout. Duration, HR zones, training effect. Manual: effort rating, fatigue, notes |
| **Daily Log** | Manual | 7 daily habit checkboxes + morning energy + midday/evening ratings (energy, focus, mood, stress, day rating, notes) |
| **Strength Log** | Manual | Exercise, sets, reps, weight, RPE |
| **Analysis** | Formula-driven | Live averages, habit completion rates, habit vs HRV correlations |
| **Charts** | Auto | Visual trends for HRV, sleep, body battery, steps |
| **Raw Data Archive** | Auto | Backup copy of every Garmin record. Used to restore any tab if corrupted |

---

## Daily Workflow

**Nothing you need to do for Garmin data** — it syncs automatically at 8 PM.

**What to fill in manually:**

| Time | Tab | What to enter |
|---|---|---|
| Morning | Daily Log | Check off each habit you completed, morning energy score |
| 12:00 - 1:00 PM | Daily Log | Midday: energy, focus/clarity, mood, body feel, notes |
| 9:00 - 9:30 PM | Daily Log | Evening: energy, focus, mood, stress, day rating, notes |
| After workouts | Session Log | Perceived effort, fatigue rating, notes |
| Anytime | Nutrition | Food, macros, water |

---

## Project Structure

```
NS Habit tracker/
  garmin_sync.py              Core sync script + shared module
  backfill_history.py         Backfill via Garmin Connect API
  parse_garmin_export.py      Import historical data from Garmin export
  setup_analysis.py           Setup Analysis tab with live formulas
  setup_charts.py             Setup Charts tab with line charts
  setup_daily_log.py          Setup Daily Log tab
  setup_wizard.py             Interactive cross-platform setup wizard
  cleanup_garmin.py           Duplicate detection and removal
  verify_sheets.py            Integrity checker for all tabs
  format_all_headers.py       Uniform header formatting
  reformat_style.py           Visual styling (colors, banding, borders)
  analysis_correlations.py    Correlation analysis + heatmaps

  scripts/                    Scheduler wrappers (bat, ps1, command)
  data/garmin_export/         Historical Garmin JSON export files
  reference/                  Sleep research, books, transcripts, images
  analysis_output/            Generated charts and CSVs

  .env                        Config: email, Sheet ID, JSON key filename
  requirements.txt            Python dependencies
  .gitignore                  Excludes creds, cache, data, books
```

---

## Running the Sync Manually

```bash
python garmin_sync.py                     # Sync yesterday (default scheduled mode, auto-backfills gaps)
python garmin_sync.py --today             # Sync today
python garmin_sync.py --date 2026-03-01   # Sync a specific past date
```

---

## Setup on a New Machine

1. Copy project folder (or clone from private GitHub repo)
2. Install Python 3.10+
3. `pip install -r requirements.txt`
4. Copy the Google service account JSON key file into the project folder
5. Confirm `.env` has `JSON_KEY_FILE=filename.json` (filename only, no path)
6. Store Garmin password in keyring — run this in terminal (replace with real values):
   ```
   python -c "import keyring; keyring.set_password('garmin_connect', 'YOUR_EMAIL', 'YOUR_PASSWORD')"
   ```
7. Set up the scheduler (see below)
8. Test: `python garmin_sync.py --today`

### Scheduler setup

| Platform | Method |
|---|---|
| Windows | Run `scripts/create_schedule.bat` as Administrator |
| macOS | launchd plist in `~/Library/LaunchAgents/` |
| Linux | cron: `0 20 * * * /usr/bin/python3 /path/to/garmin_sync.py` |

---

## Credentials — Security Model

- **Garmin password:** stored in OS keyring (Windows Credential Manager / macOS Keychain). Never in any file.
- **Google service account key:** JSON file in project folder. Filename referenced in `.env` — never the full path.
- **Rule:** Never paste passwords or key contents into any chat or document.

---

## Analytics Roadmap

The system is designed to answer: *what behaviors actually improve HRV, sleep, and cognitive performance?*

1. **Now:** Correlation matrix across all numeric variables
2. **Next:** Regression models predicting HRV, sleep score, and focus from habits + ratings
3. **Later:** Lag analysis (does a hard workout hurt HRV for 1 day or 2?), seasonal patterns, streak effects

See `ANALYSIS.md` for the full plan and findings as they accumulate.

---

## If Something Breaks

| Problem | Fix |
|---|---|
| Script fails with `FileNotFoundError` on JSON key | `.env` has wrong path — set `JSON_KEY_FILE=filename.json` (no path) |
| Script fails with `keyring` error | Re-store Garmin password in keyring on this machine |
| Google Sheets data looks misaligned | Run `python verify_sheets.py` to diagnose |
| Missed days during downtime | Auto-backfill handles the last 7 days. For older gaps: `python garmin_sync.py --date YYYY-MM-DD` |
| Tab completely corrupted | Restore from Raw Data Archive tab using `python parse_garmin_export.py --restore` |
