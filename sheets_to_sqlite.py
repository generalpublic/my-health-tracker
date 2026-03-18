"""Migrate all Google Sheets data into the local SQLite backup database.

Usage:
    python sheets_to_sqlite.py              # Full migration (all tabs)
    python sheets_to_sqlite.py --tab Sleep  # Single tab only
    python sheets_to_sqlite.py --snapshot   # Same as full, labeled as snapshot
    python sheets_to_sqlite.py --dry-run    # Count rows, don't write
"""
import sys
import sqlite3
from datetime import datetime

from utils import get_workbook
from sqlite_backup import (
    get_db, close_db,
    upsert_garmin_row, upsert_sleep_row, upsert_nutrition_row,
    upsert_session_log_row, upsert_daily_log_row, upsert_strength_log_row,
    upsert_overall_analysis_row, upsert_archive_row,
)

# Tab name -> (upsert function, min expected columns)
TAB_CONFIG = {
    "Garmin":            (upsert_garmin_row,      37),
    "Sleep":             (upsert_sleep_row,        23),
    "Nutrition":         (upsert_nutrition_row,    16),
    "Session Log":       (upsert_session_log_row,  23),
    "Daily Log":         (upsert_daily_log_row,    22),
    "Strength Log":      (upsert_strength_log_row,  8),
    "Overall Analysis":  (upsert_overall_analysis_row, 12),
    "Raw Data Archive":  (upsert_archive_row,      52),
}

# Tab name -> SQLite table name (for verification)
TAB_TO_TABLE = {
    "Garmin":           "garmin",
    "Sleep":            "sleep",
    "Nutrition":        "nutrition",
    "Session Log":      "session_log",
    "Daily Log":        "daily_log",
    "Strength Log":     "strength_log",
    "Overall Analysis": "overall_analysis",
    "Raw Data Archive": "raw_data_archive",
}


def migrate_tab(wb, conn, tab_name, upsert_fn, min_cols, dry_run=False):
    """Read all rows from a Sheets tab and upsert into SQLite."""
    try:
        sheet = wb.worksheet(tab_name)
    except Exception:
        print(f"  SKIP  {tab_name}: tab not found in spreadsheet")
        return 0

    all_rows = sheet.get_all_values()
    if len(all_rows) <= 1:
        print(f"  SKIP  {tab_name}: no data rows (header only)")
        return 0

    data_rows = all_rows[1:]  # skip header
    sheets_count = len(data_rows)

    if dry_run:
        print(f"  DRY   {tab_name}: {sheets_count} rows would be migrated")
        return sheets_count

    migrated = 0
    skipped = 0
    for row in data_rows:
        # Skip rows with no date (column B = index 1)
        if len(row) < 2 or not row[1]:
            skipped += 1
            continue
        try:
            upsert_fn(conn, row)
            migrated += 1
        except Exception as e:
            print(f"  WARN  {tab_name} row {row[1]}: {e}")
            skipped += 1

    conn.commit()

    # Verify
    table_name = TAB_TO_TABLE[tab_name]
    db_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    status = "OK" if db_count >= migrated else "MISMATCH"
    print(f"  {status}  {tab_name}: {sheets_count} Sheets rows -> {db_count} SQLite rows ({skipped} skipped)")
    return migrated


def main():
    dry_run = "--dry-run" in sys.argv
    is_snapshot = "--snapshot" in sys.argv

    # Determine which tabs to migrate
    if "--tab" in sys.argv:
        idx = sys.argv.index("--tab")
        tab_filter = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if tab_filter not in TAB_CONFIG:
            print(f"Unknown tab: {tab_filter}")
            print(f"Available: {', '.join(TAB_CONFIG.keys())}")
            sys.exit(1)
        tabs = {tab_filter: TAB_CONFIG[tab_filter]}
    else:
        tabs = TAB_CONFIG

    label = "Snapshot" if is_snapshot else "Migration"
    print(f"\n{'[DRY RUN] ' if dry_run else ''}{label}: Google Sheets -> SQLite")
    print(f"  Database: health_tracker.db")
    print(f"  Tabs: {', '.join(tabs.keys())}\n")

    wb = get_workbook()
    conn = get_db()
    total = 0

    for tab_name, (upsert_fn, min_cols) in tabs.items():
        count = migrate_tab(wb, conn, tab_name, upsert_fn, min_cols, dry_run)
        total += count

    # Update snapshot timestamp
    if not dry_run:
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            ("last_snapshot" if is_snapshot else "last_migration", datetime.now().isoformat())
        )
        conn.commit()

    print(f"\nDone. {total} total rows {'would be ' if dry_run else ''}migrated.")

    # Print summary table
    if not dry_run:
        print("\nSQLite row counts:")
        for tab_name in tabs:
            table_name = TAB_TO_TABLE[tab_name]
            count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            print(f"  {table_name:25s} {count:>6d} rows")

    close_db()


if __name__ == "__main__":
    main()
