"""
add_day_column.py — One-time migration: insert Day column as column A in all tabs.

For each tab:
1. Insert a new column at position 0 (shifts all existing data right)
2. Write "Day" header in A1
3. Read dates from column B (the old column A, now shifted)
4. Compute day abbreviations (Mon, Tue, Wed, etc.) for all dates
5. Write day values to column A using RAW mode

Usage:
    python add_day_column.py
    python add_day_column.py --dry-run    # preview changes without writing
"""

import sys
from datetime import date as _date
from garmin_sync import get_workbook, date_to_day

# All tabs that need the Day column inserted
TABS = [
    "Garmin",
    "Sleep",
    "Nutrition",
    "Session Log",
    "Daily Log",
    "Strength Log",
    "Raw Data Archive",
]


def migrate_tab(wb, tab_name, dry_run=False):
    """Insert Day column at position 0 and populate with day abbreviations."""
    try:
        sheet = wb.worksheet(tab_name)
    except Exception:
        print(f"  [{tab_name}] SKIP - tab not found")
        return

    # Check if Day column already exists
    headers = sheet.row_values(1)
    if headers and headers[0] == "Day":
        print(f"  [{tab_name}] SKIP - Day column already exists")
        return

    print(f"  [{tab_name}] Inserting Day column...")

    if dry_run:
        # Just show what would happen
        all_rows = sheet.get_all_values()
        date_count = 0
        for row in all_rows[1:]:
            if row and row[0] and row[0].startswith("20"):
                date_count += 1
        print(f"    Would insert column A, write Day header, compute {date_count} day abbreviations")
        return

    # Step 1: Insert column at position 0
    wb.batch_update({"requests": [{
        "insertDimension": {
            "range": {
                "sheetId": sheet.id,
                "dimension": "COLUMNS",
                "startIndex": 0,
                "endIndex": 1,
            },
            "inheritFromBefore": False,
        }
    }]})

    # Step 2: Write "Day" header in A1
    sheet.update(range_name="A1", values=[["Day"]], value_input_option="RAW")

    # Step 3: Read dates from column B (the old A column, now shifted right)
    date_col = sheet.col_values(2)  # column B = dates
    if len(date_col) <= 1:
        print(f"    Header written. No data rows to update.")
        return

    # Step 4: Compute day abbreviations for all data rows
    day_values = []
    for date_str in date_col[1:]:  # skip header
        day_values.append([date_to_day(date_str.strip())])

    # Step 5: Write all day values at once
    if day_values:
        last_row = len(day_values) + 1
        sheet.update(
            range_name=f"A2:A{last_row}",
            values=day_values,
            value_input_option="RAW",
        )

    print(f"    Done: {len(day_values)} day abbreviations written.")


def main():
    dry_run = "--dry-run" in sys.argv

    print("NS Habit Tracker — Add Day Column Migration")
    if dry_run:
        print("[DRY RUN] No changes will be made.\n")
    else:
        print()

    print("Connecting to Google Sheets...")
    wb = get_workbook()

    for tab_name in TABS:
        migrate_tab(wb, tab_name, dry_run=dry_run)

    if dry_run:
        print("\n[DRY RUN] No changes made. Run without --dry-run to apply.")
    else:
        print("\nMigration complete. All tabs now have Day column as column A.")
        print("Next steps:")
        print("  1. python verify_sheets.py     # confirm all tabs pass")
        print("  2. python reformat_style.py    # apply week-based banding")


if __name__ == "__main__":
    main()
