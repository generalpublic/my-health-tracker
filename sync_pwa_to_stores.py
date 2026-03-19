"""Sync PWA-entered manual data from Supabase -> SQLite + Google Sheets.

This script pulls rows from Supabase where manual_source='pwa' and syncs
them to SQLite and Google Sheets. It only updates manual-entry columns,
never overwriting auto-populated data (Garmin metrics, analysis scores, etc.).

Usage:
    python sync_pwa_to_stores.py              # Sync all pending PWA entries
    python sync_pwa_to_stores.py --since 2h   # Only entries from last 2 hours
    python sync_pwa_to_stores.py --dry-run    # Show what would be synced
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "health_tracker.db"

# Manual-only columns per table — these are the ONLY columns we sync from PWA.
# Auto columns (Garmin metrics, analysis scores) are never touched.
MANUAL_COLUMNS = {
    "daily_log": [
        "morning_energy", "wake_at_930", "no_morning_screens", "creatine_hydrate",
        "walk_breathing", "physical_activity", "no_screens_before_bed", "bed_at_10pm",
        "habits_total", "midday_energy", "midday_focus", "midday_mood", "midday_body_feel",
        "midday_notes", "evening_energy", "evening_focus", "evening_mood",
        "perceived_stress", "day_rating", "evening_notes",
    ],
    "nutrition": [
        "breakfast", "lunch", "dinner", "snacks",
        "total_calories_consumed", "protein_g", "carbs_g", "fats_g",
        "water_l", "calorie_balance", "notes",
    ],
    "sleep": ["notes"],
    "overall_analysis": ["cognition", "cognition_notes"],
    "strength_log": ["muscle_group", "exercise", "weight_lbs", "reps", "rpe", "notes"],
    "session_log": ["perceived_effort", "post_workout_energy", "notes"],
}

# Sheets tab names and their manual column letters (1-indexed)
# These map manual columns to their positions in the Google Sheets tabs
SHEETS_MANUAL_COLS = {
    "daily_log": {
        "tab": "Daily Log",
        "date_col": "B",
        "cols": {
            "morning_energy": "C", "wake_at_930": "D", "no_morning_screens": "E",
            "creatine_hydrate": "F", "walk_breathing": "G", "physical_activity": "H",
            "no_screens_before_bed": "I", "bed_at_10pm": "J", "habits_total": "K",
            "midday_energy": "L", "midday_focus": "M", "midday_mood": "N",
            "midday_body_feel": "O", "midday_notes": "P",
            "evening_energy": "Q", "evening_focus": "R", "evening_mood": "S",
            "perceived_stress": "T", "day_rating": "U", "evening_notes": "V",
        },
    },
    "nutrition": {
        "tab": "Nutrition",
        "date_col": "B",
        "cols": {
            "breakfast": "F", "lunch": "G", "dinner": "H", "snacks": "I",
            "total_calories_consumed": "J", "protein_g": "K", "carbs_g": "L",
            "fats_g": "M", "water_l": "N", "calorie_balance": "O", "notes": "P",
        },
    },
    "sleep": {
        "tab": "Sleep",
        "date_col": "B",
        "cols": {"notes": "G"},
    },
    "overall_analysis": {
        "tab": "Overall Analysis",
        "date_col": "B",
        "cols": {"cognition": "H", "cognition_notes": "I"},
    },
    "session_log": {
        "tab": "Session Log",
        "date_col": "B",
        "cols": {
            "perceived_effort": "D", "post_workout_energy": "E", "notes": "F",
        },
    },
}


# ---------------------------------------------------------------------------
# Supabase pull
# ---------------------------------------------------------------------------

def pull_pwa_entries(client, since=None):
    """Pull all manual entries written by PWA since last sync.

    Returns dict of {table_name: [rows]} for tables with PWA-written data.
    """
    if client is None:
        return {}

    results = {}
    for table in MANUAL_COLUMNS:
        try:
            query = client.table(table).select("*").eq("manual_source", "pwa")
            if since:
                query = query.gte("updated_at", since)
            response = query.execute()
            if response.data:
                results[table] = response.data
                print(f"  [Supabase] Pulled {len(response.data)} PWA entries from {table}")
        except Exception as e:
            print(f"  [Supabase] Pull failed for {table}: {e}")

    return results


def get_last_sync_time(client):
    """Read last_pwa_sync timestamp from Supabase _meta table."""
    if client is None:
        return None
    try:
        resp = client.table("_meta").select("value").eq("key", "last_pwa_sync").execute()
        if resp.data and resp.data[0].get("value"):
            return resp.data[0]["value"]
    except Exception:
        pass
    return None


def set_last_sync_time(client):
    """Update last_pwa_sync timestamp in Supabase _meta table."""
    if client is None:
        return
    try:
        now = datetime.utcnow().isoformat() + "Z"
        client.table("_meta").upsert(
            {"key": "last_pwa_sync", "value": now}, on_conflict="key"
        ).execute()
        print(f"  [Supabase] Updated last_pwa_sync = {now}")
    except Exception as e:
        print(f"  [Supabase] Failed to update last_pwa_sync: {e}")


# ---------------------------------------------------------------------------
# SQLite write — column-specific updates (never clobbers auto data)
# ---------------------------------------------------------------------------

def _sqlite_connect():
    return sqlite3.connect(str(DB_PATH))


def sync_to_sqlite(entries, dry_run=False):
    """Write PWA manual entries to SQLite, updating only manual columns."""
    if not entries:
        return 0

    conn = _sqlite_connect()
    total = 0

    for table, rows in entries.items():
        manual_cols = MANUAL_COLUMNS.get(table, [])
        if not manual_cols:
            continue

        for row in rows:
            date_str = row.get("date")
            if not date_str:
                continue

            if table == "strength_log":
                # Strength log: INSERT (auto-increment), check for duplicates
                exercise = row.get("exercise")
                weight = row.get("weight_lbs")
                reps = row.get("reps")
                if not exercise:
                    continue
                existing = conn.execute(
                    "SELECT id FROM strength_log WHERE date=? AND exercise=? AND weight_lbs=? AND reps=?",
                    (date_str, exercise, weight, reps)
                ).fetchone()
                if existing:
                    continue
                if dry_run:
                    print(f"    [dry-run] SQLite INSERT strength_log: {date_str} {exercise} {weight}x{reps}")
                    total += 1
                    continue
                cols = ["date", "day"] + manual_cols
                vals = [date_str, row.get("day")]
                for c in manual_cols:
                    vals.append(row.get(c))
                placeholders = ",".join(["?"] * len(cols))
                conn.execute(
                    f"INSERT INTO strength_log ({','.join(cols)}) VALUES ({placeholders})",
                    vals
                )
                total += 1
                continue

            if table == "session_log":
                # Session log: composite key (date, activity_name)
                activity_name = row.get("activity_name")
                if not activity_name:
                    continue
                sets = []
                for c in manual_cols:
                    val = row.get(c)
                    if val is not None:
                        sets.append((c, val))
                if not sets:
                    continue
                if dry_run:
                    print(f"    [dry-run] SQLite UPDATE session_log {date_str}/{activity_name}: {[s[0] for s in sets]}")
                    total += 1
                    continue
                set_clause = ", ".join(f"{c}=?" for c, _ in sets)
                vals = [v for _, v in sets] + [date_str, activity_name]
                conn.execute(
                    f"UPDATE session_log SET {set_clause} WHERE date=? AND activity_name=?",
                    vals
                )
                total += 1
                continue

            # Standard tables: UPDATE only manual columns that have values
            sets = []
            for c in manual_cols:
                val = row.get(c)
                if val is not None:
                    sets.append((c, val))
            if not sets:
                continue

            # Check if row exists
            existing = conn.execute(f"SELECT date FROM {table} WHERE date=?", (date_str,)).fetchone()

            if dry_run:
                action = "UPDATE" if existing else "INSERT"
                print(f"    [dry-run] SQLite {action} {table} {date_str}: {[s[0] for s in sets]}")
                total += 1
                continue

            if existing:
                set_clause = ", ".join(f"{c}=?" for c, _ in sets)
                vals = [v for _, v in sets] + [date_str]
                conn.execute(f"UPDATE {table} SET {set_clause} WHERE date=?", vals)
            else:
                cols = ["date", "day"] + [c for c, _ in sets]
                vals = [date_str, row.get("day")] + [v for _, v in sets]
                placeholders = ",".join(["?"] * len(cols))
                conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", vals)

            total += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return total


# ---------------------------------------------------------------------------
# Google Sheets write — targeted cell updates (never clobbers auto data)
# ---------------------------------------------------------------------------

def sync_to_sheets(entries, wb=None, dry_run=False):
    """Write PWA manual entries to Google Sheets, updating only manual columns."""
    if not entries or wb is None:
        return 0

    total = 0

    for table, rows in entries.items():
        config = SHEETS_MANUAL_COLS.get(table)
        if not config:
            continue

        tab_name = config["tab"]
        date_col = config["date_col"]
        col_map = config["cols"]

        try:
            sheet = wb.worksheet(tab_name)
        except Exception as e:
            print(f"    [Sheets] Tab '{tab_name}' not found: {e}")
            continue

        # Read all dates from the date column to find row numbers
        date_values = sheet.col_values(ord(date_col) - ord("A") + 1)
        date_to_row = {}
        for i, d in enumerate(date_values):
            if d:
                date_to_row[d] = i + 1  # 1-indexed

        for row in rows:
            date_str = row.get("date")
            if not date_str:
                continue

            sheet_row = date_to_row.get(date_str)
            if not sheet_row:
                if not dry_run:
                    print(f"    [Sheets] {tab_name}: no row for date {date_str}, skipping")
                continue

            # Build cell updates for manual columns that have values
            updates = []
            for col_name, col_letter in col_map.items():
                val = row.get(col_name)
                if val is not None:
                    cell_ref = f"{col_letter}{sheet_row}"
                    updates.append((cell_ref, val))

            if not updates:
                continue

            if dry_run:
                print(f"    [dry-run] Sheets {tab_name} row {sheet_row}: {[u[0] for u in updates]}")
                total += 1
                continue

            # Batch update cells
            cells_to_update = []
            for cell_ref, val in updates:
                cell = sheet.acell(cell_ref)
                cell.value = val
                cells_to_update.append(cell)

            if cells_to_update:
                sheet.update_cells(cells_to_update, value_input_option="RAW")
                print(f"    [Sheets] {tab_name} {date_str}: updated {len(cells_to_update)} cells")
                total += 1

    return total


# ---------------------------------------------------------------------------
# Main sync function — called by garmin_sync.py or standalone
# ---------------------------------------------------------------------------

def sync_pwa_entries(supabase_client, wb=None, dry_run=False, since_override=None):
    """Pull PWA manual entries from Supabase and sync to SQLite + Sheets.

    Args:
        supabase_client: Initialized Supabase client (from supabase_sync.init_supabase())
        wb: gspread Workbook object (optional — if None, skips Sheets sync)
        dry_run: If True, print what would be synced without writing
        since_override: ISO timestamp string to override last sync time
    """
    print("\n--- PWA Manual Entry Sync ---")

    if supabase_client is None:
        print("  Supabase client not available, skipping")
        return

    # Determine since timestamp
    since = since_override
    if not since:
        since = get_last_sync_time(supabase_client)
    if since:
        print(f"  Syncing entries since: {since}")
    else:
        print("  No previous sync — pulling all PWA entries")

    # Pull from Supabase
    entries = pull_pwa_entries(supabase_client, since=since)
    if not entries:
        print("  No PWA entries to sync")
        return

    total_rows = sum(len(rows) for rows in entries.values())
    print(f"  Found {total_rows} PWA entries across {len(entries)} tables")

    # Sync to SQLite
    sqlite_count = sync_to_sqlite(entries, dry_run=dry_run)
    print(f"  SQLite: {'would sync' if dry_run else 'synced'} {sqlite_count} rows")

    # Sync to Sheets
    if wb:
        sheets_count = sync_to_sheets(entries, wb=wb, dry_run=dry_run)
        print(f"  Sheets: {'would sync' if dry_run else 'synced'} {sheets_count} rows")
    else:
        print("  Sheets: skipped (no workbook provided)")

    # Update last sync timestamp
    if not dry_run:
        set_last_sync_time(supabase_client)

    print("--- PWA Sync Complete ---\n")


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sync PWA manual entries from Supabase to SQLite + Sheets")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be synced without writing")
    parser.add_argument("--since", type=str, default=None,
                        help="Only sync entries newer than this (e.g. '2h', '1d', or ISO timestamp)")
    parser.add_argument("--all", action="store_true", help="Sync all PWA entries regardless of last sync time")
    args = parser.parse_args()

    # Parse --since shorthand
    since = None
    if args.all:
        since = None  # Will pull all PWA entries
    elif args.since:
        if args.since.endswith("h"):
            hours = int(args.since[:-1])
            since = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
        elif args.since.endswith("d"):
            days = int(args.since[:-1])
            since = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
        else:
            since = args.since  # Assume ISO timestamp

    # Initialize Supabase
    try:
        from supabase_sync import init_supabase
        supa = init_supabase()
    except Exception as e:
        print(f"Failed to init Supabase: {e}")
        sys.exit(1)

    # Initialize Google Sheets (optional)
    wb = None
    try:
        from dotenv import load_dotenv
        import gspread
        from google.oauth2.service_account import Credentials

        load_dotenv(SCRIPT_DIR / ".env")
        json_key = SCRIPT_DIR / os.getenv("JSON_KEY_FILE", "")
        sheet_id = os.getenv("GOOGLE_SHEET_ID", "")

        if json_key.exists() and sheet_id:
            creds = Credentials.from_service_account_file(
                str(json_key),
                scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"],
            )
            gc = gspread.authorize(creds)
            wb = gc.open_by_key(sheet_id)
            print(f"  Google Sheets connected: {wb.title}")
    except Exception as e:
        print(f"  Google Sheets not available: {e}")

    sync_pwa_entries(supa, wb=wb, dry_run=args.dry_run, since_override=since)


if __name__ == "__main__":
    main()
