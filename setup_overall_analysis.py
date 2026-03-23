"""
setup_overall_analysis.py -- Create the Overall Analysis tab + Key reference tab.

Overall Analysis: auto-populated by overall_analysis.py after each garmin_sync run.
Key: static reference tab explaining all scores, labels, and terminology.

Layout (Overall Analysis):
  A     Day
  B     Date
  C     Readiness Score (1-10)
  D     Readiness Label
  E     Confidence
  F     Cognitive/Energy Assessment
  G     Sleep Context
  H     Cognition (1-10)           -- manual
  I     Cognition Notes            -- manual
  J     Key Insights
  K     Recommendations
  L     Training Load Status
  M     Data Quality
  N     Quality Flags
"""

from pathlib import Path
from dotenv import load_dotenv
from utils import get_workbook
from schema import OVERALL_ANALYSIS_HEADERS

load_dotenv(Path(__file__).parent / ".env")

HEADER_COLOR = {"red": 0.353, "green": 0.180, "blue": 0.459}  # #5A2E75 purple
TAB_COLOR    = {"red": 0.533, "green": 0.306, "blue": 0.635}  # #884EA2 lighter purple
HEADER_FONT  = {"red": 1.0, "green": 1.0, "blue": 1.0}        # white text

# --- Readiness Label colors (same as Key tab) ---
LABEL_COLORS = {
    "Optimal": {"red": 0.851, "green": 0.918, "blue": 0.827},   # green
    "Good":    {"red": 0.898, "green": 0.941, "blue": 0.867},   # light green
    "Fair":    {"red": 1.0, "green": 0.949, "blue": 0.800},     # light amber
    "Low":     {"red": 1.0, "green": 0.878, "blue": 0.808},     # light orange
    "Poor":    {"red": 0.957, "green": 0.800, "blue": 0.800},   # light red
}

# --- Key tab content ---

KEY_CONTENT = [
    ["READINESS SCORE", ""],
    ["8.5 - 10", "Optimal -- high-intensity training OK, challenging cognitive tasks"],
    ["7.0 - 8.4", "Good -- normal training load appropriate"],
    ["5.5 - 6.9", "Fair -- moderate activity, watch for compounding fatigue"],
    ["4.0 - 5.4", "Low -- active recovery only, prioritize sleep"],
    ["1.0 - 3.9", "Poor -- rest day, NSDR, early bedtime"],
    ["", ""],
    ["ACWR (Training Load)", ""],
    ["> 1.5", "SPIKE -- significantly elevated injury/illness risk"],
    ["1.3 - 1.5", "HIGH -- above sweet spot, monitor recovery closely"],
    ["0.8 - 1.3", "SWEET SPOT -- training matches your fitness"],
    ["< 0.8", "LOW -- detraining risk, consider increasing load"],
    ["", ""],
    ["CONFIDENCE", ""],
    ["High", "All 4 readiness inputs + 14+ days baseline data"],
    ["Medium", "2-3 inputs available or baseline has gaps"],
    ["Low", "Only objective data (no subjective) or <7 days history"],
    ["", ""],
    ["Z-SCORE", ""],
    ["> +1.0", "Significantly above your 30-day baseline"],
    ["-0.5 to +1.0", "Normal range for you"],
    ["-1.0 to -0.5", "Below baseline -- caution"],
    ["< -1.0", "Significantly suppressed -- flag"],
]

KEY_COLORS = {
    "8.5 - 10":     {"red": 0.851, "green": 0.918, "blue": 0.827},   # green
    "7.0 - 8.4":    {"red": 0.898, "green": 0.941, "blue": 0.867},   # light green
    "5.5 - 6.9":    {"red": 1.0, "green": 0.949, "blue": 0.800},     # light amber
    "4.0 - 5.4":    {"red": 1.0, "green": 0.878, "blue": 0.808},     # light orange
    "1.0 - 3.9":    {"red": 0.957, "green": 0.800, "blue": 0.800},   # light red
    "0.8 - 1.3":    {"red": 0.851, "green": 0.918, "blue": 0.827},   # green
    "1.3 - 1.5":    {"red": 1.0, "green": 0.878, "blue": 0.808},     # light orange
    "> 1.5":        {"red": 0.957, "green": 0.800, "blue": 0.800},   # light red
    "< 0.8":        {"red": 1.0, "green": 0.949, "blue": 0.800},     # light amber
    "> +1.0":       {"red": 0.851, "green": 0.918, "blue": 0.827},   # green
    "-0.5 to +1.0": {"red": 0.898, "green": 0.941, "blue": 0.867},   # light green
    "-1.0 to -0.5": {"red": 1.0, "green": 0.949, "blue": 0.800},    # light amber
    "< -1.0":       {"red": 0.957, "green": 0.800, "blue": 0.800},   # light red
}

KEY_TAB_COLOR = {"red": 0.400, "green": 0.400, "blue": 0.400}  # grey


def setup_overall_analysis(wb):
    """Create/update the Overall Analysis tab (data only, no legend)."""
    import gspread
    try:
        sheet = wb.worksheet("Overall Analysis")
        print("  Overall Analysis tab exists -- updating headers and formatting.")
    except gspread.exceptions.WorksheetNotFound:
        sheet = wb.add_worksheet(title="Overall Analysis", rows=2000, cols=len(OVERALL_ANALYSIS_HEADERS))
        print("  Overall Analysis tab created.")

    # Ensure exact column count
    if sheet.col_count != len(OVERALL_ANALYSIS_HEADERS):
        sheet.resize(cols=len(OVERALL_ANALYSIS_HEADERS))

    # Clear ALL existing conditional formatting rules to prevent stale rules accumulating
    # Use the Sheets API directly to delete all rules on this sheet
    try:
        resp = wb.fetch_sheet_metadata()
        for s in resp.get("sheets", []):
            if s["properties"]["sheetId"] == sheet.id:
                rules = s.get("conditionalFormats", [])
                if rules:
                    # Delete rules in reverse order to keep indices stable
                    del_requests = [
                        {"deleteConditionalFormatRule": {"sheetId": sheet.id, "index": i}}
                        for i in range(len(rules) - 1, -1, -1)
                    ]
                    wb.batch_update({"requests": del_requests})
                    print(f"  Cleared {len(rules)} old conditional format rules.")
                break
    except Exception:
        pass  # If metadata fetch fails, proceed — rules will just accumulate

    # Write headers
    sheet.update(range_name="A1", values=[OVERALL_ANALYSIS_HEADERS], value_input_option="RAW")

    requests = []
    sheet_id = sheet.id
    num_cols = len(OVERALL_ANALYSIS_HEADERS)

    # Header row: purple background, white bold 11pt centered text, wrapped
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": num_cols,
            },
            "cell": {"userEnteredFormat": {
                "backgroundColor": HEADER_COLOR,
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
                "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": HEADER_FONT},
            }},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)",
        }
    })

    # All data cells: top + left aligned
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": 2000,
                "startColumnIndex": 0, "endColumnIndex": num_cols,
            },
            "cell": {"userEnteredFormat": {
                "verticalAlignment": "TOP",
                "horizontalAlignment": "LEFT",
            }},
            "fields": "userEnteredFormat(verticalAlignment,horizontalAlignment)",
        }
    })

    # Light yellow background for manual-entry columns: H (Cognition), I (Cognition Notes)
    YELLOW = {"red": 1.0, "green": 1.0, "blue": 0.8}
    for col_idx in [7, 8]:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1, "endRowIndex": 2000,
                    "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": YELLOW}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

    # Centered columns: C (Readiness Score), D (Readiness Label), E (Confidence), H (Cognition)
    for col_idx in [2, 3, 4, 7]:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1, "endRowIndex": 2000,
                    "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
                },
                "cell": {"userEnteredFormat": {
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "TOP",
                }},
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)",
            }
        })

    # Readiness Score discrete bands (C): same colors as Readiness Label (D)
    # Uses CUSTOM_FORMULA so each band maps to the same color as its label
    score_bands = [
        # (formula, color) — checked top-down, first match wins
        ('=AND(C2>=8.5, C2<=10)',  LABEL_COLORS["Optimal"]),   # 8.5-10 = green
        ('=AND(C2>=7.0, C2<8.5)',  LABEL_COLORS["Good"]),      # 7.0-8.4 = light green
        ('=AND(C2>=5.5, C2<7.0)',  LABEL_COLORS["Fair"]),      # 5.5-6.9 = amber
        ('=AND(C2>=4.0, C2<5.5)',  LABEL_COLORS["Low"]),       # 4.0-5.4 = orange
        ('=AND(C2>=1.0, C2<4.0)',  LABEL_COLORS["Poor"]),      # 1.0-3.9 = red
    ]
    for formula, color in score_bands:
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet_id,
                        "startRowIndex": 1, "endRowIndex": 2000,
                        "startColumnIndex": 2, "endColumnIndex": 3,
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": formula}],
                        },
                        "format": {"backgroundColor": color},
                    },
                },
                "index": 0,
            }
        })

    # Cognition gradient (H): red (1) -> green (10)
    requests.append({
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{
                    "sheetId": sheet_id,
                    "startRowIndex": 1, "endRowIndex": 2000,
                    "startColumnIndex": 7, "endColumnIndex": 8,
                }],
                "gradientRule": {
                    "minpoint": {
                        "color": {"red": 0.957, "green": 0.800, "blue": 0.800},
                        "type": "NUMBER", "value": "1",
                    },
                    "midpoint": {
                        "color": {"red": 1.0, "green": 0.949, "blue": 0.800},
                        "type": "NUMBER", "value": "5",
                    },
                    "maxpoint": {
                        "color": {"red": 0.851, "green": 0.918, "blue": 0.827},
                        "type": "NUMBER", "value": "10",
                    },
                }
            },
            "index": 0,
        }
    })

    # Readiness Label discrete colors (D): Optimal=green, Good=light green, Fair=amber, Low=orange, Poor=red
    for label_text, color in LABEL_COLORS.items():
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet_id,
                        "startRowIndex": 1, "endRowIndex": 2000,
                        "startColumnIndex": 3, "endColumnIndex": 4,
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_EQ",
                            "values": [{"userEnteredValue": label_text}],
                        },
                        "format": {"backgroundColor": color},
                    },
                },
                "index": 0,
            }
        })

    # Confidence discrete colors (E): High=green, Medium-High=light green, Medium=amber, Low=red
    CONFIDENCE_COLORS = {
        "High":        LABEL_COLORS["Optimal"],   # green
        "Medium-High": LABEL_COLORS["Good"],       # light green
        "Medium":      LABEL_COLORS["Fair"],       # amber
        "Low":         LABEL_COLORS["Poor"],        # red
    }
    for conf_text, color in CONFIDENCE_COLORS.items():
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet_id,
                        "startRowIndex": 1, "endRowIndex": 2000,
                        "startColumnIndex": 4, "endColumnIndex": 5,
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_EQ",
                            "values": [{"userEnteredValue": conf_text}],
                        },
                        "format": {"backgroundColor": color},
                    },
                },
                "index": 0,
            }
        })

    # Freeze header row + Day+Date columns
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2},
            },
            "fields": "gridProperties(frozenRowCount,frozenColumnCount)",
        }
    })

    # Tab color
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
        0: 60,    # A  Day
        1: 100,   # B  Date
        2: 105,   # C  Readiness Score (1-10) -- header wraps to 2 lines
        3: 100,   # D  Readiness Label -- "Optimal" is the widest value
        4: 105,   # E  Confidence (High/Med-High/Med/Low)
        5: 350,   # F  Cognitive/Energy Assessment (concise 1-sentence summary)
        6: 350,   # G  Sleep Context (multi-part summary)
        7: 80,    # H  Cognition (1-10) -- manual numeric score
        8: 250,   # I  Cognition Notes -- manual free text
        9: 400,   # J  Key Insights (max 5 concise bullets)
        10: 350,  # K  Recommendations (max 3 action items)
        11: 380,  # L  Training Load Status (ACWR sentence)
        12: 120,  # M  Data Quality (short summary)
        13: 250,  # N  Quality Flags (pipe-separated flags)
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

    # Text wrapping for text-heavy columns: F, G, I, J, K, L, N
    for col_idx in [5, 6, 8, 9, 10, 11, 13]:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1, "endRowIndex": 2000,
                    "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
                },
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }
        })

    wb.batch_update({"requests": requests})
    print("  Overall Analysis formatted.")

    # Apply weekly row banding
    apply_weekly_banding(wb, sheet)

    return sheet


# Columns exempt from banding (color-graded or yellow manual)
# C=2 (Readiness Score gradient), D=3 (Readiness Label discrete), E=4 (Confidence discrete),
# H=7 (Cognition gradient + yellow), I=8 (yellow)
_BANDING_EXEMPT_COLS = {2, 3, 4, 7, 8}

LIGHT_GREY = {"red": 0.95, "green": 0.95, "blue": 0.95}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}


def apply_weekly_banding(wb, sheet=None):
    """Apply alternating white/grey backgrounds per week (Sun-Sat) to non-exempt columns."""
    from datetime import datetime

    if sheet is None:
        try:
            sheet = wb.worksheet("Overall Analysis")
        except Exception:
            return

    all_rows = sheet.get_all_values()
    if len(all_rows) < 2:
        return

    sheet_id = sheet.id
    num_cols = len(OVERALL_ANALYSIS_HEADERS)
    # Columns that get banding (everything not exempt)
    band_cols = [i for i in range(num_cols) if i not in _BANDING_EXEMPT_COLS]

    # Parse dates and compute week numbers (Sunday-based)
    # Week = (date - epoch_sunday) // 7, alternating parity
    data_rows = all_rows[1:]
    requests = []

    for row_idx, row in enumerate(data_rows):
        date_str = row[1] if len(row) > 1 else ""
        if not date_str or not date_str.startswith("20"):
            continue

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        # Sunday-based week number: isoweekday() returns Mon=1..Sun=7
        # Shift so Sunday=0: (isoweekday % 7) gives Sun=0, Mon=1, ..., Sat=6
        # Week number from a fixed epoch
        days_since_epoch = (dt - datetime(2000, 1, 2)).days  # 2000-01-02 is a Sunday
        week_num = days_since_epoch // 7
        is_grey = (week_num % 2) == 1

        bg_color = LIGHT_GREY if is_grey else WHITE
        sheet_row = row_idx + 1  # 0-based, row 0 is header so data starts at 1

        for col_idx in band_cols:
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": sheet_row, "endRowIndex": sheet_row + 1,
                        "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": bg_color}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            })

    if requests:
        # Batch in chunks of 500 to avoid API limits
        for i in range(0, len(requests), 500):
            wb.batch_update({"requests": requests[i:i+500]})
        print(f"  Weekly banding applied ({len(data_rows)} rows).")
    else:
        print("  No data rows for banding.")


def setup_key_tab(wb):
    """Create/update the Key reference tab (static legend for the spreadsheet)."""
    import gspread
    try:
        sheet = wb.worksheet("Key")
        print("  Key tab exists -- updating content.")
    except gspread.exceptions.WorksheetNotFound:
        sheet = wb.add_worksheet(title="Key", rows=len(KEY_CONTENT) + 2, cols=2)
        print("  Key tab created.")

    # Write content
    sheet.update(range_name=f"A1:B{len(KEY_CONTENT)}", values=KEY_CONTENT, value_input_option="RAW")

    requests = []
    sheet_id = sheet.id

    # Column widths
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id, "dimension": "COLUMNS",
                "startIndex": 0, "endIndex": 1,
            },
            "properties": {"pixelSize": 150},
            "fields": "pixelSize",
        }
    })
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id, "dimension": "COLUMNS",
                "startIndex": 1, "endIndex": 2,
            },
            "properties": {"pixelSize": 480},
            "fields": "pixelSize",
        }
    })

    # All cells: top-left aligned, wrapped
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": len(KEY_CONTENT),
                "startColumnIndex": 0, "endColumnIndex": 2,
            },
            "cell": {"userEnteredFormat": {
                "verticalAlignment": "TOP",
                "horizontalAlignment": "LEFT",
                "wrapStrategy": "WRAP",
            }},
            "fields": "userEnteredFormat(verticalAlignment,horizontalAlignment,wrapStrategy)",
        }
    })

    # Tab color: grey
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "tabColorStyle": {"rgbColor": KEY_TAB_COLOR},
            },
            "fields": "tabColorStyle",
        }
    })

    wb.batch_update({"requests": requests})

    # Format section headers and color-code value rows
    fmt_requests = []

    for i, row in enumerate(KEY_CONTENT):
        label = row[0]
        desc = row[1]

        # Section headers (text in col A, empty col B)
        if label and not desc:
            fmt_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": i, "endRowIndex": i + 1,
                        "startColumnIndex": 0, "endColumnIndex": 2,
                    },
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": HEADER_COLOR,
                        "textFormat": {"bold": True, "fontSize": 10, "foregroundColor": HEADER_FONT},
                        "verticalAlignment": "TOP",
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
                }
            })
            continue

        # Color-coded value rows
        color = KEY_COLORS.get(label)
        if color:
            fmt_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": i, "endRowIndex": i + 1,
                        "startColumnIndex": 0, "endColumnIndex": 2,
                    },
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": color,
                        "verticalAlignment": "TOP",
                    }},
                    "fields": "userEnteredFormat(backgroundColor,verticalAlignment)",
                }
            })

    if fmt_requests:
        wb.batch_update({"requests": fmt_requests})

    # Move Key tab to the last position
    all_sheets = wb.worksheets()
    last_index = len(all_sheets) - 1
    wb.batch_update({"requests": [{
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "index": last_index},
            "fields": "index",
        }
    }]})

    print("  Key tab formatted and moved to last position.")
    return sheet


def verify(wb):
    print("\n--- VERIFICATION ---")
    sheet = wb.worksheet("Overall Analysis")
    actual = sheet.row_values(1)
    actual_main = actual[:len(OVERALL_ANALYSIS_HEADERS)]
    if actual_main == OVERALL_ANALYSIS_HEADERS:
        rows = sheet.get_all_values()
        data_count = sum(1 for r in rows[1:] if r and len(r) > 1 and r[1] and str(r[1]).startswith("20"))
        print(f"  PASS  Overall Analysis: {len(actual_main)} columns, {data_count} data rows")
    else:
        missing = [h for h in OVERALL_ANALYSIS_HEADERS if h not in actual_main]
        extra   = [h for h in actual_main if h not in OVERALL_ANALYSIS_HEADERS]
        print(f"  FAIL  Overall Analysis: header mismatch")
        if missing: print(f"        Missing: {missing}")
        if extra:   print(f"        Extra:   {extra}")

    # Verify conditional formatting (color grading on C, D, E, H)
    try:
        from verify_formatting import verify_tab_formatting
        passed, issues = verify_tab_formatting(wb, "Overall Analysis")
        if passed:
            print(f"  PASS  Overall Analysis: conditional formatting intact")
        else:
            for issue in issues:
                print(f"  FAIL  {issue}")
    except Exception as e:
        print(f"  SKIP  Formatting check: {e}")


def main():
    print("Setting up Overall Analysis + Key tabs...")
    wb = get_workbook()
    setup_overall_analysis(wb)
    setup_key_tab(wb)
    verify(wb)
    print("\nDone.")


if __name__ == "__main__":
    main()
