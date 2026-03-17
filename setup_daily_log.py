"""
setup_daily_log.py — Create the unified Daily Log tab.

Replaces both the Habits tab and Daily Ratings tab with one single entry point.
All columns are manual (yellow). Garmin data is in the Garmin tab — merged by date in Python.

Layout:
  A     Date
  B     Morning Energy (1-10)
  C-I   7 habit checkboxes
  J     Habits Total (formula)
  K     Midday Energy (1-10)
  L     Midday Focus/Clarity (1-10)   <- brain fog = low
  M     Midday Mood (1-10)
  N     Midday Body Feel (1-10)
  O     Midday Notes
  P     Evening Energy (1-10)
  Q     Evening Focus/Clarity (1-10)
  R     Evening Mood (1-10)
  S     Perceived Stress (1-10)       <- subjective, not Garmin's
  T     Day Rating (1-10)
  U     Evening Notes

Migrates existing Habits tab data on first run.
"""

from pathlib import Path
from dotenv import load_dotenv
import gspread
from garmin_sync import get_workbook, YELLOW, date_to_day

load_dotenv(Path(__file__).parent / ".env")

DAILY_LOG_HEADERS = [
    # Manual entry zone
    "Day",                            # A
    "Date",                           # B
    "Morning Energy (1-10)",          # C
    "Wake at 9:30 AM",                # D  checkbox
    "No Morning Screens",             # E  checkbox
    "Creatine & Hydrate",             # F  checkbox
    "20 Min Walk + Breathing",        # G  checkbox
    "Physical Activity",              # H  checkbox
    "No Screens Before Bed",          # I  checkbox
    "Bed at 10 PM",                   # J  checkbox
    "Habits Total (0-7)",             # K  formula
    "Midday Energy (1-10)",           # L
    "Midday Focus (1-10)",            # M  brain fog = low score
    "Midday Mood (1-10)",             # N
    "Midday Body Feel (1-10)",        # O
    "Midday Notes",                   # P  free text
    "Evening Energy (1-10)",          # Q
    "Evening Focus (1-10)",           # R
    "Evening Mood (1-10)",            # S
    "Perceived Stress (1-10)",        # T
    "Day Rating (1-10)",              # U
    "Evening Notes",                  # V  free text
]

MANUAL_COLS  = list(range(2, 22))   # C through V (0-indexed 2-21)
HABIT_COLS   = list(range(3, 10))   # D through J (0-indexed 3-9)
NUMERIC_1_10 = [2, 11, 12, 13, 14, 16, 17, 18, 19, 20]  # C,L,M,N,O,Q,R,S,T,U

HEADER_COLOR = {"red": 0.235, "green": 0.286, "blue": 0.361}  # #3C495C slate
TAB_COLOR    = {"red": 0.176, "green": 0.647, "blue": 0.749}  # #2DA5BE teal
HEADER_FONT  = {"red": 1.0, "green": 1.0, "blue": 1.0}        # white text

# Color scales for 1-10 scores (applied via conditional formatting)
RED   = {"red": 0.957, "green": 0.800, "blue": 0.800}
GREEN = {"red": 0.851, "green": 0.918, "blue": 0.827}


def setup_daily_log(wb):
    # Create or get the tab
    try:
        sheet = wb.worksheet("Daily Log")
        print("  Daily Log tab exists — updating headers and formatting.")
    except gspread.exceptions.WorksheetNotFound:
        sheet = wb.add_worksheet(title="Daily Log", rows=2000, cols=len(DAILY_LOG_HEADERS))
        print("  Daily Log tab created.")

    # Write headers
    sheet.update(range_name="A1", values=[DAILY_LOG_HEADERS], value_input_option="RAW")

    requests = []
    sheet_id = sheet.id

    # Header row: teal background, white bold 11pt centered text
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": len(DAILY_LOG_HEADERS),
            },
            "cell": {"userEnteredFormat": {
                "backgroundColor": HEADER_COLOR,
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": HEADER_FONT},
            }},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)",
        }
    })

    # Manual entry columns (C-V): yellow background
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "startColumnIndex": 2, "endColumnIndex": 22,
            },
            "cell": {"userEnteredFormat": {"backgroundColor": YELLOW}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    })

    # Checkboxes for habit columns (D-J)
    requests.append({
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": 2000,
                "startColumnIndex": 3, "endColumnIndex": 10,
            },
            "rule": {
                "condition": {"type": "BOOLEAN"},
                "strict": True,
                "showCustomUi": True,
            }
        }
    })

    # Number validation (1-10) for score columns
    for col_idx in NUMERIC_1_10:
        requests.append({
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1, "endRowIndex": 2000,
                    "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
                },
                "rule": {
                    "condition": {
                        "type": "NUMBER_BETWEEN",
                        "values": [{"userEnteredValue": "1"}, {"userEnteredValue": "10"}]
                    },
                    "inputMessage": "1 = worst  |  10 = best",
                    "strict": False,
                }
            }
        })

    # Conditional color formatting for 1-10 score columns
    # Low (1-4) = light red, Mid (5-7) = light orange, High (8-10) = light green
    for col_idx in NUMERIC_1_10:
        col_range = {
            "sheetId": sheet_id,
            "startRowIndex": 1, "endRowIndex": 2000,
            "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
        }
        # Invert for Stress (col 19 = T): high stress = bad so flip colors
        is_inverted = (col_idx == 19)

        low_color  = RED   if not is_inverted else GREEN
        high_color = GREEN if not is_inverted else RED

        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [col_range],
                    "gradientRule": {
                        "minpoint": {
                            "color": low_color,
                            "type": "NUMBER", "value": "1",
                        },
                        "maxpoint": {
                            "color": high_color,
                            "type": "NUMBER", "value": "10",
                        },
                    }
                },
                "index": 0,
            }
        })

    # Freeze header row and first column
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2},
            },
            "fields": "gridProperties(frozenRowCount,frozenColumnCount)",
        }
    })

    # Tab color: teal
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "tabColorStyle": {"rgbColor": TAB_COLOR},
            },
            "fields": "tabColorStyle",
        }
    })

    # Column widths
    width_map = {
        0: 45,    # Day
        1: 110,   # Date
        2: 80,    # Morning Energy
        3: 55, 4: 55, 5: 55, 6: 55, 7: 55, 8: 55, 9: 55,  # Checkboxes
        10: 65,   # Habits Total
        11: 80, 12: 80, 13: 80, 14: 80,  # Midday scores
        15: 180,  # Midday Notes
        16: 80, 17: 80, 18: 80, 19: 80, 20: 80,  # Evening scores
        21: 180,  # Evening Notes
    }
    for col_idx, px in width_map.items():
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                },
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        })

    wb.batch_update({"requests": requests})
    print("  Daily Log formatted.")
    return sheet


def migrate_habits_data(wb, sheet):
    """Migrate existing Habits tab data into Daily Log."""
    try:
        habits = wb.worksheet("Habits")
    except Exception:
        print("  No Habits tab found — skipping migration.")
        return

    rows = habits.get_all_values()
    if len(rows) <= 1:
        print("  Habits tab is empty — nothing to migrate.")
        return

    data_rows = rows[1:]
    print(f"  Migrating {len(data_rows)} rows from Habits tab...")

    # Habits columns: Date(0), MorningEnergy(1), Wake(2), NoScreenMorn(3),
    #   Creatine(4), Walk(5), Physical(6), NoScreenBed(7), Bed10(8), Total(9), Notes(10)
    # Daily Log columns: A=Date, B=MorningEnergy, C-I=habits, J=Total(formula)

    new_rows = []
    for row in data_rows:
        def get(i): return row[i] if i < len(row) else ""
        date = get(0)
        if not date:
            continue

        # Convert "1"/"TRUE"/True -> TRUE for checkboxes, "0"/"FALSE"/"" -> FALSE
        def to_bool(v):
            return "TRUE" if str(v).strip() in ("1", "TRUE", "true", "True") else "FALSE"

        new_row = [
            date_to_day(date),  # A Day
            date,           # B Date
            get(1),         # C Morning Energy
            to_bool(get(2)),  # D Wake at 9:30
            to_bool(get(3)),  # E No Morning Screens
            to_bool(get(4)),  # F Creatine
            to_bool(get(5)),  # G Walk
            to_bool(get(6)),  # H Physical Activity
            to_bool(get(7)),  # I No Screens Before Bed
            to_bool(get(8)),  # J Bed at 10 PM
            "",             # K Habits Total (formula added separately)
            "", "", "", "", get(10),  # L-P: midday scores + old Notes -> Midday Notes
            "", "", "", "", "", "",   # Q-V: evening scores + evening notes
        ]
        new_rows.append(new_row)

    if not new_rows:
        print("  No valid rows to migrate.")
        return

    # Sort newest-first
    new_rows.sort(key=lambda r: r[0], reverse=True)

    # Write all rows at once
    sheet.update(
        range_name=f"A2:V{len(new_rows)+1}",
        values=new_rows,
        value_input_option="USER_ENTERED"  # needed for TRUE/FALSE checkboxes
    )

    # Add Habits Total formula for each row
    cell_updates = []
    for i, row in enumerate(new_rows):
        row_num = i + 2
        cell_updates.append(gspread.Cell(row_num, 11, f"=COUNTIF(D{row_num}:J{row_num},TRUE)"))

    chunk = 500
    for start in range(0, len(cell_updates), chunk):
        sheet.update_cells(cell_updates[start:start+chunk], value_input_option="USER_ENTERED")

    print(f"  Migrated {len(new_rows)} rows.")


def verify(wb):
    print("\n--- VERIFICATION ---")
    sheet = wb.worksheet("Daily Log")
    actual = sheet.row_values(1)
    if actual == DAILY_LOG_HEADERS:
        rows = sheet.get_all_values()
        print(f"  PASS  Daily Log: {len(actual)} columns, {len(rows)-1} data rows")
    else:
        missing = [h for h in DAILY_LOG_HEADERS if h not in actual]
        extra   = [h for h in actual if h not in DAILY_LOG_HEADERS]
        print(f"  FAIL  Daily Log: header mismatch")
        if missing: print(f"        Missing: {missing}")
        if extra:   print(f"        Extra:   {extra}")


def main():
    print("Setting up Daily Log tab...")
    wb = get_workbook()
    sheet = setup_daily_log(wb)
    migrate_habits_data(wb, sheet)
    verify(wb)
    print("\nDone.")
    print("\nDaily Log layout:")
    print("  A        Day")
    print("  B        Date")
    print("  C        Morning Energy (1-10)")
    print("  D-J      7 habit checkboxes (click to toggle)")
    print("  K        Habits Total (auto-counted)")
    print("  L-O      Midday: Energy, Focus, Mood, Body Feel (1-10)")
    print("  P        Midday Notes (free text)")
    print("  Q-U      Evening: Energy, Focus, Mood, Stress, Day Rating (1-10)")
    print("  V        Evening Notes (free text)")
    print("\n  Scores 1-10 are color-coded: red=low, green=high (Stress column is inverted)")
    print("  Fill left-to-right each day.")


if __name__ == "__main__":
    main()
