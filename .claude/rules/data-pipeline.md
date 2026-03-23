# Data Pipeline: Sheets -> SQLite -> Dashboard (Non-Negotiable)

Google Sheets is the source of truth. SQLite is the local mirror. The dashboard reads from SQLite.

---

## Automatic (Already Wired)
- `garmin_sync.py` writes to both Sheets AND SQLite in the same run (garmin, sleep, nutrition, session_log, archive)
- `overall_analysis.py` writes to both Sheets AND SQLite after every analysis
- `garmin_sync.py` exports the dashboard at end of pipeline

## When to Run a Full Sync (`python sheets_to_sqlite.py`)
- After any **manual edit** to Google Sheets (user typed data, column corrections, bulk fixes)
- After any **structural change** (column add/remove/move, tab creation, schema migration)
- After running **import scripts** that write to Sheets but not SQLite (e.g., `parse_garmin_export.py`, `parse_fit_files.py`)
- After running **backfill** scripts (`backfill_history.py`)
- At **end of day** if any Sheets-only work was done during the session

## After Every Full Sync, Refresh the Dashboard
```
python sheets_to_sqlite.py && python dashboard/export_dashboard_data.py
```

## Tables Synced (8 Total)
Garmin | Sleep | Nutrition | Session Log | Daily Log | Strength Log | Overall Analysis | Raw Data Archive
