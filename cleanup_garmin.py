"""
cleanup_garmin.py — Review and fix duplicate entries in Google Sheets.

Rules:
  - Garmin tab:     1 entry per date -- remove duplicates, keep last (most recent run)
  - Daily Log tab:  1 entry per date -- remove duplicates, keep last
  - Session Log:    multiple entries per date allowed -- report only, never delete
  - Strength Log:   multiple entries per date allowed -- report only, never delete
"""

from garmin_sync import get_workbook

EXPECTED_COLS = {
    "Garmin": 37,  # 36 original + Day column
}


def find_tab(wb, name):
    try:
        return wb.worksheet(name)
    except Exception:
        return None


def dedup_tab(sheet, tab_name):
    """
    Remove duplicate date rows from a tab that must have 1 entry per date.
    Keeps the LAST occurrence of each date (most recent run = most complete data).
    Row 1 is always the header and is never touched.
    Returns (duplicates_removed, misaligned_rows).
    """
    print(f"\n--- {tab_name} ---")
    all_rows = sheet.get_all_values()

    if not all_rows:
        print("  Tab is empty.")
        return 0, 0

    data_rows = all_rows[1:]

    expected_cols = EXPECTED_COLS.get(tab_name)

    # Find misaligned rows (wrong column count)
    misaligned = []
    for i, row in enumerate(data_rows):
        if expected_cols and row and len(row) != expected_cols:
            sheet_row_num = i + 2
            non_empty = [c for c in row if c.strip()]
            if non_empty:
                misaligned.append((sheet_row_num, len(row), row[1] if len(row) > 1 else ""))

    if misaligned:
        print(f"  MISALIGNED ROWS (expected {expected_cols} cols):")
        for row_num, col_count, date_val in misaligned:
            print(f"    Row {row_num}: date={date_val}, cols={col_count}")

    # Build map: date -> list of sheet row numbers (1-based)
    date_positions = {}
    for i, row in enumerate(data_rows):
        date_val = row[1].strip() if row and len(row) > 1 else ""
        if not date_val:
            continue
        sheet_row_num = i + 2
        if date_val not in date_positions:
            date_positions[date_val] = []
        date_positions[date_val].append(sheet_row_num)

    # Find duplicates
    duplicates = {d: rows for d, rows in date_positions.items() if len(rows) > 1}

    if not duplicates:
        print("  No duplicates found.")
    else:
        print(f"  Found duplicates for {len(duplicates)} date(s):")
        for date_val, rows in sorted(duplicates.items()):
            print(f"    {date_val}: rows {rows} -- keeping row {rows[-1]}, deleting {rows[:-1]}")

    # Delete from bottom to top so row numbers don't shift
    rows_to_delete = []
    for rows in duplicates.values():
        rows_to_delete.extend(rows[:-1])

    rows_to_delete.sort(reverse=True)
    for row_num in rows_to_delete:
        sheet.delete_rows(row_num)
        print(f"  Deleted duplicate row {row_num}.")

    return len(rows_to_delete), len(misaligned)


def report_tab(sheet, tab_name):
    """
    Report duplicate dates in a tab but never delete anything.
    Used for Session Log and Strength Log where multiple entries per date are allowed.
    """
    print(f"\n--- {tab_name} (report only -- multiple entries per date allowed) ---")
    all_rows = sheet.get_all_values()

    if not all_rows:
        print("  Tab is empty.")
        return

    data_rows = all_rows[1:]
    date_counts = {}
    for row in data_rows:
        date_val = row[1].strip() if row and len(row) > 1 else ""
        if date_val:
            date_counts[date_val] = date_counts.get(date_val, 0) + 1

    multi = {d: c for d, c in date_counts.items() if c > 1}
    if not multi:
        print("  No dates with multiple entries.")
    else:
        print(f"  Dates with multiple entries ({len(multi)} date(s)) -- this is expected:")
        for date_val, count in sorted(multi.items()):
            print(f"    {date_val}: {count} entries")


def verify(wb):
    """Verify final state of all tabs -- print PASS/FAIL."""
    print("\n=== VERIFICATION ===")
    results = {}

    for tab_name in ["Garmin", "Daily Log"]:
        sheet = find_tab(wb, tab_name)
        if sheet is None:
            print(f"  {tab_name}: SKIP (tab not found)")
            continue

        all_rows = sheet.get_all_values()
        data_rows = all_rows[1:] if all_rows else []
        dates = [r[1].strip() for r in data_rows if r and len(r) > 1 and r[1].strip()]
        dupes = [d for d in dates if dates.count(d) > 1]

        if dupes:
            unique_dupes = list(set(dupes))
            print(f"  {tab_name}: FAIL -- still has duplicate dates: {unique_dupes}")
            results[tab_name] = False
        else:
            print(f"  {tab_name}: PASS -- no duplicate dates ({len(dates)} rows)")
            results[tab_name] = True

    return all(results.values())


def main():
    print("Connecting to Google Sheets...")
    wb = get_workbook()
    print("Connected.\n")

    total_deleted = 0
    total_misaligned = 0

    # Tabs that must have 1 entry per date -- clean duplicates
    for tab_name in ["Garmin", "Daily Log"]:
        sheet = find_tab(wb, tab_name)
        if sheet is None:
            print(f"\n--- {tab_name}: NOT FOUND (skipping) ---")
            continue
        deleted, misaligned = dedup_tab(sheet, tab_name)
        total_deleted += deleted
        total_misaligned += misaligned

    # Tabs that allow multiple entries per date -- report only
    for tab_name in ["Session Log", "Strength Log"]:
        sheet = find_tab(wb, tab_name)
        if sheet is None:
            print(f"\n--- {tab_name}: NOT FOUND (skipping) ---")
            continue
        report_tab(sheet, tab_name)

    print(f"\n=== SUMMARY ===")
    print(f"  Duplicate rows deleted: {total_deleted}")
    print(f"  Misaligned rows flagged: {total_misaligned}")
    if total_misaligned > 0:
        print("  NOTE: Misaligned rows were NOT deleted automatically.")
        print("  These rows have the wrong number of columns -- likely written by an old")
        print("  version of the script. Delete them manually in Google Sheets and re-run")
        print("  garmin_sync.py for those dates if needed.")

    verify(wb)


if __name__ == "__main__":
    main()
