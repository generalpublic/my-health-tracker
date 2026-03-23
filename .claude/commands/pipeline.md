Run the full daily pipeline end-to-end:

1. Run `python garmin_sync.py --today`
2. Report results: data pulled, tabs updated, verification status
3. If any verification fails, diagnose and report the issue
4. Confirm the pipeline completed: Garmin API -> Sheets -> SQLite -> Overall Analysis -> Dashboard
