"""
sheets_formatting.py — Google Sheets formatting, styling, and layout functions.

Handles: color grading, verdict formatting, yellow manual columns, bold headers,
sorting, row auto-resize, and numeric type fixing.
"""

import gspread
from gspread import Cell

from schema import SLEEP_HEADERS, YELLOW


# --- Color constants ---

_GRADE_GREEN  = {"red": 0.776, "green": 0.918, "blue": 0.765}   # #C6EAC3 soft mint
_GRADE_YELLOW = {"red": 1.0,   "green": 0.929, "blue": 0.706}   # #FFEDB4 warm amber
_GRADE_RED    = {"red": 0.957, "green": 0.733, "blue": 0.718}   # #F4BBB7 soft coral

_GRADE_LIGHT_GREEN  = {"red": 0.878, "green": 0.945, "blue": 0.843}  # #E0F1D7
_GRADE_ORANGE_RED   = {"red": 0.976, "green": 0.816, "blue": 0.714}  # #F9D0B6

_VERDICT_COLORS = {
    "GOOD": {"red": 0.15, "green": 0.50, "blue": 0.15},   # green
    "FAIR": {"red": 0.85, "green": 0.55, "blue": 0.0},     # orange
    "POOR": {"red": 0.80, "green": 0.10, "blue": 0.10},    # red
}
_BLACK = {"red": 0, "green": 0, "blue": 0}

# Tabs with free-text columns that need row auto-resize after writes
_TEXT_HEAVY_TABS = {"Sleep", "Nutrition", "Daily Log", "Session Log", "Overall Analysis"}

# Numeric columns in SLEEP_HEADERS -- derived by name so reordering won't break this
_SLEEP_NUMERIC_HEADER_NAMES = {
    "Garmin Sleep Score", "Sleep Analysis Score", "Total Sleep (hrs)",
    "Time in Bed (hrs)", "Deep Sleep (min)", "Light Sleep (min)", "REM (min)",
    "Awake During Sleep (min)", "Deep %", "REM %", "Sleep Cycles",
    "Awakenings", "Avg HR", "Avg Respiration", "Overnight HRV (ms)",
    "Body Battery Gained",
    "Bedtime Variability (7d)", "Wake Variability (7d)",
}
_SLEEP_NUMERIC_COLS = {i for i, h in enumerate(SLEEP_HEADERS) if h in _SLEEP_NUMERIC_HEADER_NAMES}


# --- Sorting & Layout ---

def sort_sheet_by_date_desc(wb, sheet_title):
    """Sort all data rows by Date column (B) descending.

    First normalises Date column to plain text so mixed types don't break sorting.
    """
    try:
        sheet = wb.worksheet(sheet_title)
    except Exception:
        return

    date_col = sheet.get_values("B:B", value_render_option="FORMATTED_VALUE")
    if not date_col or len(date_col) < 3:
        return

    fixed = []
    for cell in date_col[1:]:
        val = cell[0].strip() if cell else ""
        fixed.append([val])

    if not fixed:
        return

    last_data_row = len(fixed) + 1
    sheet.update(range_name=f"B2:B{last_data_row}", values=fixed,
                 value_input_option="RAW")

    wb.batch_update({"requests": [{
        "sortRange": {
            "range": {
                "sheetId": sheet.id,
                "startRowIndex": 1,
                "endRowIndex": last_data_row,
                "startColumnIndex": 0,
                "endColumnIndex": sheet.col_count,
            },
            "sortSpecs": [{"dimensionIndex": 1, "sortOrder": "DESCENDING"}],
        }
    }]})


def auto_resize_rows(wb, sheet_title):
    """Auto-resize row heights to fit wrapped text content."""
    if sheet_title not in _TEXT_HEAVY_TABS:
        return
    try:
        sheet = wb.worksheet(sheet_title)
    except Exception:
        return
    row_count = sheet.row_count
    if row_count < 2:
        return
    wb.batch_update({"requests": [{"autoResizeDimensions": {
        "dimensions": {
            "sheetId": sheet.id,
            "dimension": "ROWS",
            "startIndex": 1,
            "endIndex": row_count,
        },
    }}]})


# --- Header & Column Styling ---

def bold_headers(wb, sheet_title):
    """Apply uniform header formatting (bold, 11pt, centered) to row 1."""
    try:
        sheet = wb.worksheet(sheet_title)
    except Exception:
        return
    wb.batch_update({"requests": [{
        "repeatCell": {
            "range": {
                "sheetId": sheet.id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": 200,
            },
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 11},
            }},
            "fields": "userEnteredFormat(horizontalAlignment,textFormat.bold,textFormat.fontSize)",
        }
    }]})


def apply_yellow_columns(wb, sheet_title, col_indices):
    """Apply light yellow background to entire columns (header included)."""
    try:
        sheet = wb.worksheet(sheet_title)
    except Exception:
        return
    requests = []
    for col_idx in col_indices:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": 0,
                    "startColumnIndex": col_idx,
                    "endColumnIndex": col_idx + 1,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": YELLOW}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
    if requests:
        wb.batch_update({"requests": requests})


# --- Sleep Color Grading ---

def apply_sleep_color_grading(wb):
    """Apply research-based color grading (green-to-red gradients) to Sleep tab columns.

    Idempotent -- clears existing rules before applying.
    """
    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        return

    sid = sheet.id

    # Clear existing conditional format rules on this sheet
    metadata = wb.fetch_sheet_metadata()
    for s in metadata.get("sheets", []):
        if s["properties"]["sheetId"] == sid:
            existing_rules = s.get("conditionalFormats", [])
            if existing_rules:
                del_reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
                            for i in range(len(existing_rules) - 1, -1, -1)]
                wb.batch_update({"requests": del_reqs})
            break

    def _col_range(col_idx):
        return {
            "sheetId": sid,
            "startRowIndex": 1, "endRowIndex": 10000,
            "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
        }

    def _gradient_higher_better(col_idx, red_val, yellow_val, green_val):
        return {"addConditionalFormatRule": {
            "rule": {
                "ranges": [_col_range(col_idx)],
                "gradientRule": {
                    "minpoint":  {"color": _GRADE_RED,    "type": "NUMBER", "value": str(red_val)},
                    "midpoint":  {"color": _GRADE_YELLOW, "type": "NUMBER", "value": str(yellow_val)},
                    "maxpoint":  {"color": _GRADE_GREEN,  "type": "NUMBER", "value": str(green_val)},
                },
            },
            "index": 0,
        }}

    def _gradient_lower_better(col_idx, green_val, yellow_val, red_val):
        return {"addConditionalFormatRule": {
            "rule": {
                "ranges": [_col_range(col_idx)],
                "gradientRule": {
                    "minpoint":  {"color": _GRADE_GREEN,  "type": "NUMBER", "value": str(green_val)},
                    "midpoint":  {"color": _GRADE_YELLOW, "type": "NUMBER", "value": str(yellow_val)},
                    "maxpoint":  {"color": _GRADE_RED,    "type": "NUMBER", "value": str(red_val)},
                },
            },
            "index": 0,
        }}

    def _bedtime_band(formula, color):
        return {"addConditionalFormatRule": {
            "rule": {
                "ranges": [_col_range(hmap["Bedtime"])],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                    "format": {"backgroundColor": color},
                },
            },
            "index": 0,
        }}

    hmap = {h: i for i, h in enumerate(SLEEP_HEADERS)}

    # Read gradient thresholds from thresholds.json (configurable per-user)
    from utils import load_thresholds
    thresholds = load_thresholds()
    sf = thresholds.get("sheets_formatting", {}).get("Sleep", {})
    gradients = sf.get("gradient", [])

    requests = []
    for g in gradients:
        header = g["header"]
        if header not in hmap:
            continue
        col_idx = hmap[header]
        if g["direction"] == "higher_better":
            requests.append(_gradient_higher_better(col_idx, g["min"], g["mid"], g["max"]))
        else:
            requests.append(_gradient_lower_better(col_idx, g["min"], g["mid"], g["max"]))

    # Bedtime discrete bands — read from thresholds.json (configurable per-user)
    bb = thresholds.get("bedtime_bands", {})
    green_start = bb.get("green_start", "20:00")
    green_end = bb.get("green_end", "23:00")
    light_green_start = bb.get("light_green_start", "23:00")
    yellow_start = bb.get("yellow_start", "00:00")
    yellow_end = bb.get("yellow_end", "01:00")
    orange_start = bb.get("orange_start", "01:00")
    orange_end = bb.get("orange_end", "02:00")
    red_start = bb.get("red_start", "02:00")
    red_end = bb.get("red_end", "06:00")

    bt_col = gspread.utils.rowcol_to_a1(1, hmap["Bedtime"] + 1)[0]
    bt = f"{bt_col}2"
    bedtime_rules = [
        (f'=AND({bt}<>"", TIMEVALUE({bt})>=TIMEVALUE("{green_start}"), TIMEVALUE({bt})<TIMEVALUE("{green_end}"))', _GRADE_GREEN),
        (f'=AND({bt}<>"", TIMEVALUE({bt})>=TIMEVALUE("{light_green_start}"))', _GRADE_LIGHT_GREEN),
        (f'=AND({bt}<>"", TIMEVALUE({bt})>=TIMEVALUE("{yellow_start}"), TIMEVALUE({bt})<TIMEVALUE("{yellow_end}"))', _GRADE_YELLOW),
        (f'=AND({bt}<>"", TIMEVALUE({bt})>=TIMEVALUE("{orange_start}"), TIMEVALUE({bt})<TIMEVALUE("{orange_end}"))', _GRADE_ORANGE_RED),
        (f'=AND({bt}<>"", TIMEVALUE({bt})>=TIMEVALUE("{red_start}"), TIMEVALUE({bt})<TIMEVALUE("{red_end}"))', _GRADE_RED),
    ]
    for formula, color in reversed(bedtime_rules):
        requests.append(_bedtime_band(formula, color))

    wb.batch_update({"requests": requests})
    print("  Sleep: color grading applied.")


# --- Sleep Verdict Formatting ---

def _build_text_format_runs(cell_text, verdict):
    """Build textFormatRuns for a Sleep Analysis cell."""
    runs = [
        {"startIndex": 0, "format": {
            "bold": True,
            "foregroundColorStyle": {"rgbColor": _VERDICT_COLORS[verdict]},
        }},
        {"startIndex": len(verdict), "format": {
            "bold": False,
            "foregroundColorStyle": {"rgbColor": _BLACK},
        }},
    ]
    action_idx = cell_text.find("ACTION:")
    if action_idx != -1:
        runs.append({"startIndex": action_idx, "format": {
            "bold": True,
            "foregroundColorStyle": {"rgbColor": _BLACK},
        }})
    return runs


def apply_sleep_verdict_formatting(wb):
    """Bold and color the verdict word (GOOD/FAIR/POOR) and ACTION sentence in Sleep Analysis cells."""
    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        return

    sid = sheet.id
    analysis_col = SLEEP_HEADERS.index("Sleep Analysis")

    all_values = sheet.get_all_values()
    if len(all_values) <= 1:
        return

    rows_data = []
    for row_idx in range(1, len(all_values)):
        cell_text = all_values[row_idx][analysis_col] if analysis_col < len(all_values[row_idx]) else ""
        if not cell_text:
            rows_data.append({"values": [{"userEnteredValue": {"stringValue": ""}}]})
            continue

        verdict = None
        for v in ("GOOD", "FAIR", "POOR"):
            if cell_text.startswith(v):
                verdict = v
                break

        if verdict is None:
            rows_data.append({"values": [{"userEnteredValue": {"stringValue": cell_text}}]})
            continue

        rows_data.append({"values": [{
            "userEnteredValue": {"stringValue": cell_text},
            "textFormatRuns": _build_text_format_runs(cell_text, verdict),
        }]})

    wb.batch_update({"requests": [{
        "updateCells": {
            "range": {
                "sheetId": sid,
                "startRowIndex": 1,
                "endRowIndex": 1 + len(rows_data),
                "startColumnIndex": analysis_col,
                "endColumnIndex": analysis_col + 1,
            },
            "rows": rows_data,
            "fields": "userEnteredValue,textFormatRuns",
        }
    }]})
    print(f"  Sleep: verdict formatting applied ({len(rows_data)} cells).")


# --- Session Log Color Grading ---

# Gradient thresholds for Session Log (higher = better for all three).
# Derived from overall distribution across all 580 sessions.
_SESSION_GRADIENTS = [
    # (col_index, red_val, yellow_val, green_val)
    (7,  15,  35,  60),    # H: Duration (min) — ACSM: 15 vigorous min, 35 moderate, 60 substantial
    (8,  1,   5,   15),    # I: Distance (mi)
    (11, 100, 400, 900),   # L: Calories — Harvard: 100 trivial, 400 moderate, 900 vigorous hour
]


def apply_session_log_color_grading(wb):
    """Apply gradient color grading to Session Log Duration/Distance/Calories.

    Uses universal thresholds from overall session distribution.
    Smooth gradient: red (low) -> yellow (mid) -> green (high).
    Idempotent — clears existing rules before applying.
    """
    try:
        sheet = wb.worksheet("Session Log")
    except Exception:
        return

    sid = sheet.id

    # Clear existing conditional format rules on this sheet
    metadata = wb.fetch_sheet_metadata()
    for s in metadata.get("sheets", []):
        if s["properties"]["sheetId"] == sid:
            existing_rules = s.get("conditionalFormats", [])
            if existing_rules:
                del_reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
                            for i in range(len(existing_rules) - 1, -1, -1)]
                wb.batch_update({"requests": del_reqs})
            break

    def _col_range(col_idx):
        return {
            "sheetId": sid,
            "startRowIndex": 1, "endRowIndex": 10000,
            "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
        }

    requests = []
    for col_idx, red_val, yellow_val, green_val in _SESSION_GRADIENTS:
        requests.append({"addConditionalFormatRule": {
            "rule": {
                "ranges": [_col_range(col_idx)],
                "gradientRule": {
                    "minpoint":  {"color": _GRADE_RED,    "type": "NUMBER", "value": str(red_val)},
                    "midpoint":  {"color": _GRADE_YELLOW, "type": "NUMBER", "value": str(yellow_val)},
                    "maxpoint":  {"color": _GRADE_GREEN,  "type": "NUMBER", "value": str(green_val)},
                },
            },
            "index": 0,
        }})

    wb.batch_update({"requests": requests})
    print(f"  Session Log: gradient color grading applied ({len(requests)} rules).")


# --- Numeric Type Fixing ---

def fix_sleep_numeric_types(wb):
    """Convert text-number strings to actual numbers in Sleep tab numeric columns.

    Gradient conditional formatting only works on cells containing actual numbers.
    """
    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        return

    all_rows = sheet.get_all_values()
    if len(all_rows) < 2:
        return

    cells = []
    for row_idx, row in enumerate(all_rows[1:], start=2):
        for col_idx in _SLEEP_NUMERIC_COLS:
            if col_idx >= len(row):
                continue
            val = row[col_idx]
            if val == "":
                continue
            try:
                num = float(val)
                cells.append(Cell(row=row_idx, col=col_idx + 1,
                                  value=int(num) if num == int(num) else num))
            except (ValueError, TypeError):
                continue

    if cells:
        chunk_size = 5000
        for i in range(0, len(cells), chunk_size):
            sheet.update_cells(cells[i:i + chunk_size], value_input_option="USER_ENTERED")
        print(f"  Sleep: converted {len(cells)} cells to numeric type.")
    else:
        print("  Sleep: all numeric cells already correct.")
