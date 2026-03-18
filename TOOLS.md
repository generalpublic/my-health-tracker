# Health Tracker — Tools & Scripts Reference

> Quick-reference for every script, skill, and workflow available in this project.
> Tell Claude "run X" or run them yourself from the project directory.

---

## Daily Operations

| Command | What It Does |
|---------|-------------|
| `python garmin_sync.py` | Sync yesterday's Garmin data to Sheets + SQLite (runs automatically at 8 PM via Task Scheduler) |
| `python garmin_sync.py --today` | Sync today's data (use when you want current-day numbers) |
| `python garmin_sync.py --date 2026-03-15` | Sync a specific date |
| `python garmin_sync.py --range 2026-01-01 2026-03-15` | Sync a date range (backfill missed days) |
| `python garmin_sync.py --sleep-notify` | Send sleep report to phone via Pushover |
| `python garmin_sync.py --morning-briefing` | Send morning health briefing to phone |
| `python overall_analysis.py` | Compute Readiness Score + insights (auto-runs after garmin_sync) |
| `python overall_analysis.py --today` | Run analysis for today specifically |
| `python overall_analysis.py --week` | Generate 7-day summary |

---

## Analysis & Reports

| Command | What It Does |
|---------|-------------|
| `python analysis_correlations.py` | Find strongest predictors of HRV, Sleep Score, Body Battery (generates charts) |
| `python analysis_correlations.py --no-charts` | Same but text-only, no PNG output |
| `python analysis_lag.py` | Lag analysis: how today's behavior affects tomorrow's metrics |
| `python analysis_lag.py --days 90` | Limit to last N days |
| `python analysis_lag.py --pair "HRV -> Cognition"` | Test a specific lag relationship |
| `python analysis_regression.py` | Multiple regression: which factors predict cognition/energy/sleep/HRV? |
| `python analysis_regression.py --model energy` | Run a specific model (`energy`, `focus`, `day_rating`, `sleep`, `hrv`) |
| `python weekly_report.py` | Plain-English weekly sleep + health report |
| `python weekly_report.py --weeks 4 --save` | Multi-week report saved to `analysis_output/` |

---

## Verification & Maintenance

| Command | What It Does |
|---------|-------------|
| `python verify_sheets.py` | Check all tabs for structural integrity (headers, column alignment) |
| `python verify_sheets.py --tab Sleep` | Check a single tab |
| `python verify_formatting.py` | Verify conditional formatting rules exist and data types are correct |
| `python verify_formatting.py --repair` | Auto-fix formatting failures |
| `python reformat_style.py` | Refresh all visual styling (headers, banding, column widths, alignment) |
| `python sheets_to_sqlite.py` | Backup all Sheets data to local SQLite database |
| `python overall_analysis.py --validate` | 28-day validation: check scoring accuracy against actuals |

---

## Historical Import

| Command | What It Does |
|---------|-------------|
| `python parse_garmin_export.py` | Import Garmin export files (full history, no API needed) |
| `python parse_garmin_export.py --dry-run` | Preview import without writing |
| `python parse_garmin_export.py --start 2025-01-01 --end 2025-12-31` | Import a date range |
| `python parse_garmin_export.py --fix-data` | Fix bad sentinel values in existing data |
| `python parse_garmin_export.py --fix-types` | Fix data type issues (serials to text, strings to numbers) |
| `python backfill_history.py --start 2025-01-01 --end 2025-12-31` | Backfill via Garmin API (not export file) |

---

## Dashboard

| Command | What It Does |
|---------|-------------|
| `python dashboard/launch_dashboard.py` | Export data + open interactive HTML dashboard in browser |

---

## Setup (First-Time / New Machine)

| Command | What It Does |
|---------|-------------|
| `python setup_wizard.py` | Interactive 9-step setup wizard (dependencies, credentials, scheduler) |
| `python setup_analysis.py` | Create/update Analysis tab with habit formulas |
| `python setup_overall_analysis.py` | Create/update Overall Analysis + Key tabs |
| `python setup_daily_log.py` | Create/update Daily Log tab |
| `python setup_charts.py` | Create Charts tab with line charts |

---

## Claude Skills (Slash Commands)

These are conversational tools — type them in chat with Claude, not in a terminal.

| Skill | When To Use |
|-------|-------------|
| `/health-insight <question>` | Ask a health question cross-referencing your Garmin data + research library. Example: `/health-insight why was my HRV low this week?` |
| `/health-insight daily` | Auto-generate today's health summary |
| `/update-intel` | You have new health research material (articles, book notes, transcripts). Scans for new files, classifies them, compiles into the research library. |
| `/update-profile` | You have new personal health documents (lab results, diagnoses, provider notes). Ingests into your health profile. |
| `/verify-intel <source>` | Fact-check a health claim against peer-reviewed research before it enters the library. |

---

## Common Workflows

### "I just got new Garmin data and want everything updated"
```
python garmin_sync.py --today
```
> This automatically runs: Garmin pull -> Sheets write -> SQLite backup -> Overall Analysis -> formatting verification

### "I dropped new health research into reference/"
```
/update-intel
```
> Scans `reference/` for new files, classifies by domain, compiles into research library.

### "I have new lab results or medical docs"
```
/update-profile
```
> Ingests from `profiles/` directory into your structured health profile. Keep medical docs in `profiles/`, NOT `reference/`.

### "I want to understand my trends over the last month"
```
python analysis_correlations.py
python analysis_lag.py --days 30
python analysis_regression.py --days 30
python weekly_report.py --weeks 4 --save
```

### "Something looks wrong in the spreadsheet"
```
python verify_sheets.py
python verify_formatting.py --repair
python reformat_style.py
```

### "I missed a few days of syncing"
```
python garmin_sync.py --range 2026-03-10 2026-03-17
```

### "I want to see my dashboard"
```
python dashboard/launch_dashboard.py
```
