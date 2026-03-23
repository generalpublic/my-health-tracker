Run a full Sheets-to-SQLite sync and refresh the dashboard:

1. Run `python sheets_to_sqlite.py` — sync all 8 tables from Google Sheets to local SQLite
2. Run `python dashboard/export_dashboard_data.py` — export fresh data for the dashboard
3. Report success/failure and row counts for each table
