# Health Tracker

Automated daily health tracking with Garmin Connect sync, Google Sheets storage, and scientific readiness analysis.

Pulls sleep, HRV, activity, stress, and body battery data from Garmin Connect every day, writes it to Google Sheets across multiple tabs, computes a composite Readiness Score using individual rolling baselines, and sends a morning briefing via push notification.

---

## What It Does

- **Daily Garmin sync** -- pulls 50+ metrics from Garmin Connect API (sleep stages, HRV, resting HR, body battery, steps, activities, HR zones, training effect)
- **Multi-tab Google Sheets** -- Garmin, Sleep, Session Log, Nutrition, Daily Log, Overall Analysis tabs with auto-formatting and color grading
- **Readiness scoring** -- composite score (1-10) using sigmoid-mapped z-scores against your own 30-day rolling baselines
- **Sleep analysis** -- independent sleep quality score with research-based thresholds for deep/REM/duration/timing
- **Morning briefing** -- push notification via Pushover with sleep summary, readiness flags, and action items
- **Weekly reports** -- 7-day trend summaries with correlation analysis
- **SQLite backup** -- parallel local database for offline analytics
- **Historical import** -- bulk import from Garmin Connect data export files
- **Auto-backfill** -- detects and backfills missed days from the last 7 days

---

## Quick Start

### Prerequisites
- Python 3.10+
- A Garmin Connect account with a Garmin wearable
- A Google Cloud service account with Sheets API enabled
- (Optional) Pushover account for push notifications

### Installation

```bash
git clone <repo-url> && cd health-tracker
pip install -r requirements.txt
```

### Configuration

1. Copy `.env.example` to `.env` and fill in your values:
   ```
   SHEET_ID=your_google_sheet_id
   JSON_KEY_FILE=your_service_account_key.json
   GARMIN_EMAIL=your@email.com
   ```

2. Store your Garmin password in the system keyring (never in a file):
   ```bash
   python -c "import keyring; keyring.set_password('garmin_connect', 'your@email.com', 'YOUR_PASSWORD')"
   ```

3. Place your Google service account JSON key file in the project folder.

4. Run the setup wizard to create all Google Sheets tabs:
   ```bash
   python setup_wizard.py
   ```

5. Test the sync:
   ```bash
   python garmin_sync.py --today
   ```

### Automate with a Scheduler

| Platform | Scheduler | Setup |
|----------|-----------|-------|
| Windows  | Task Scheduler | Run `scripts/create_schedule.bat` as Administrator |
| macOS    | launchd | Plist in `~/Library/LaunchAgents/` |
| Linux    | cron | `0 20 * * * python3 /path/to/garmin_sync.py` |

---

## Daily Usage

**Garmin data syncs automatically** at 8 PM. Nothing to do.

**Manual entries (Google Sheets):**

| When | Tab | What to enter |
|------|-----|---------------|
| Morning | Daily Log | Habit checkboxes, morning energy score |
| Midday | Daily Log | Energy, focus, mood, body feel, notes |
| Evening | Daily Log | Energy, focus, mood, stress, day rating, notes |
| After workouts | Session Log | Perceived effort, fatigue, notes |
| Anytime | Nutrition | Meals, macros, water |

---

## Google Sheets Tabs

| Tab | Auto/Manual | Contents |
|-----|-------------|----------|
| **Garmin** | Auto | Daily metrics: sleep score, HRV, resting HR, body battery, steps, stress, calories, workout summary |
| **Sleep** | Auto | Nightly detail: stages, bedtime/wake, cycles, awakenings, respiration, sleep analysis score |
| **Session Log** | Auto + Manual | Per-workout: duration, HR zones, training effect. Manual: effort, energy, notes |
| **Nutrition** | Auto + Manual | Calories burned (auto). Manual: meals, macros, water |
| **Daily Log** | Manual | 7 habits + subjective ratings (energy, focus, mood, stress, day rating) |
| **Overall Analysis** | Auto | Readiness Score, label, insights, recommendations, confidence rating |
| **Raw Data Archive** | Auto | Backup of every Garmin record for disaster recovery |

---

## How Scoring Works

### Readiness Score (1-10)

Composite score using 4 weighted components, each measured against your own 30-day rolling baseline:

| Component | Weight | Source | Method |
|-----------|--------|--------|--------|
| HRV | 35% | Overnight HRV | z-score vs baseline, trend-aware |
| Sleep | 30% | 5-day weighted avg | Van Dongen et al. 2003 cumulative debt model |
| Resting HR | 20% | RHR | z-score, inverted (lower = better) |
| Subjective | 15% | Morning energy | Reduced 50% when sleep debt > 0.75h |

Z-scores are mapped through a sigmoid function to 0-10, then weighted-summed. See `reference/METHODOLOGY.md` for full citations.

### Sleep Analysis Score

Independent nightly score based on:
- Duration: 7-9h optimal (Walker 2017)
- Deep sleep: 15-25% target
- REM sleep: 20-25% target
- Bedtime: before 11 PM optimal
- Awakenings and sleep efficiency

---

## Scripts Reference

### Core (daily use)
| Script | Purpose |
|--------|---------|
| `garmin_sync.py` | Main orchestrator -- fetches data, writes all tabs, triggers analysis |
| `overall_analysis.py` | Computes Readiness Score, generates insights, writes Overall Analysis |
| `weekly_report.py` | 7-day trend summary |

### Setup (run once)
| Script | Purpose |
|--------|---------|
| `setup_wizard.py` | Interactive setup for all tabs and configuration |
| `setup_analysis.py` | Creates Sleep, Session Log, Nutrition tabs |
| `setup_daily_log.py` | Creates Daily Log tab |
| `setup_overall_analysis.py` | Creates Overall Analysis tab with formatting |

### Analytics
| Script | Purpose |
|--------|---------|
| `analysis_correlations.py` | Pearson correlations between metric pairs (FDR-corrected) |
| `analysis_regression.py` | OLS regression with VIF multicollinearity detection |
| `analysis_lag.py` | Time-lagged correlation analysis |

### Utilities
| Script | Purpose |
|--------|---------|
| `verify_sheets.py` | Validates all tab headers match schema |
| `verify_formatting.py` | Validates conditional formatting rules and numeric types |
| `reformat_style.py` | Applies visual styling (colors, banding, column widths) |
| `sheets_to_sqlite.py` | Exports Google Sheets to local SQLite database |
| `sqlite_backup.py` | Backs up SQLite database |
| `backfill_history.py` | Backfills historical data via Garmin Connect API |
| `parse_garmin_export.py` | Imports from Garmin Connect data export files |

### Modules (imported by scripts, not run directly)
| Module | Purpose |
|--------|---------|
| `garmin_client.py` | Garmin Connect API authentication and data fetching |
| `sleep_analysis.py` | Sleep quality scoring (pure functions, no API deps) |
| `writers.py` | Google Sheets write/upsert for each tab |
| `sheets_formatting.py` | Conditional formatting, color grading, sorting |
| `notifications.py` | Pushover notification composition and delivery |
| `schema.py` | Column headers, tab names, index constants |
| `utils.py` | Shared utilities (workbook access, date helpers) |
| `profile_loader.py` | Loads user health profile for personalized analysis |

---

## Project Structure

```
health-tracker/
  *.py                      All scripts and modules
  .env                      Config (not committed)
  .env.example              Template for .env
  thresholds.json           Scoring thresholds (single source of truth)
  requirements.txt          Python dependencies
  reference/                Research library and methodology
    METHODOLOGY.md          Scientific basis for all scoring
    health_knowledge.json   Runtime knowledge base for insights
    HEALTH_INTEL.md         Evaluated health claims index
    *Research Universe.md   Domain-specific compiled research
  dashboard/                Web dashboard export
  scripts/                  Scheduler setup scripts
  tests/                    Unit tests
  migrations/               Historical one-time migration scripts
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `FileNotFoundError` on JSON key | Set `JSON_KEY_FILE=filename.json` in `.env` (filename only, no path) |
| `keyring` error | Re-store Garmin password: `python -c "import keyring; keyring.set_password(...)"` |
| Data misaligned in Sheets | Run `python verify_sheets.py` to diagnose |
| Missed days | Auto-backfill covers last 7 days. Older: `python garmin_sync.py --date YYYY-MM-DD` |
| Tab corrupted | Restore from archive: `python parse_garmin_export.py --restore` |
| Formatting missing/broken | Run `python verify_formatting.py --repair` |

---

## Security

See [SECURITY.md](SECURITY.md) for the full credential model, rotation procedures, and data privacy details.

- Garmin password: OS keyring only (never in files)
- Google service account key: gitignored JSON file
- No credentials in code, env vars committed, or logs
- Push notification tokens: `.env` (gitignored)
