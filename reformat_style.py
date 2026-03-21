"""
reformat_style.py — Modern visual revamp of all Google Sheets tabs.

Applies per-tab header colors, alternating row banding, thin grid lines,
auto-computed column widths, and automatic text alignment (text columns
left-aligned + wrapped, numeric columns centered).

Usage:
    python reformat_style.py
"""

from pathlib import Path
from dotenv import load_dotenv
from datetime import date as _date
from utils import get_workbook
from schema import (
    HEADERS, SLEEP_HEADERS, NUTRITION_HEADERS, STRENGTH_LOG_HEADERS,
    SESSION_LOG_HEADERS, DAILY_LOG_HEADERS, OVERALL_ANALYSIS_HEADERS,
)
from sheets_formatting import (apply_sleep_color_grading, apply_sleep_verdict_formatting,
                               apply_session_log_color_grading)

load_dotenv(Path(__file__).parent / ".env")

# ── Design tokens ──────────────────────────────────────────────────────────────

# Shared colors
DEFAULT_BG = {"red": 0.235, "green": 0.286, "blue": 0.361}  # #3C495C slate (fallback)
WHITE_TEXT  = {"red": 1.0,   "green": 1.0,   "blue": 1.0  }
BLACK_TEXT  = {"red": 0.0,   "green": 0.0,   "blue": 0.0  }
BAND_ODD   = {"red": 1.0,   "green": 1.0,   "blue": 1.0  }  # white rows
BAND_EVEN  = {"red": 0.95,  "green": 0.95,  "blue": 0.95 }  # light grey weekly banding (matches CLAUDE.md spec)
CREAM      = {"red": 1.0,   "green": 1.0,   "blue": 0.8  }  # light yellow for manual-entry cells (matches CLAUDE.md spec)
BORDER_C   = {"red": 0.859, "green": 0.867, "blue": 0.882}  # #DBDDE1  subtle grid
DATA_TEXT  = {"red": 0.149, "green": 0.196, "blue": 0.275}  # #262F46  dark readable text

# Per-tab header backgrounds and text colors (matching user's Google Sheets choices)
TAB_STYLES = {
    "Garmin":       {"bg": {"red": 0.435, "green": 0.659, "blue": 0.863}, "fg": BLACK_TEXT,  # #6FA8DC light blue
                     "tab": {"red": 0.278, "green": 0.577, "blue": 0.918}},                  # #4793EA
    "Sleep":        {"bg": {"red": 0.698, "green": 0.620, "blue": 0.878}, "fg": BLACK_TEXT,      # #B29EE0 lavender
                     "tab": {"red": 0.620, "green": 0.420, "blue": 0.878}},                  # #9E6BE0
    "Nutrition":    {"bg": {"red": 0.576, "green": 0.769, "blue": 0.490}, "fg": BLACK_TEXT,  # #93C47D sage green
                     "tab": {"red": 0.220, "green": 0.698, "blue": 0.349}},                  # #37B259
    "Session Log":  {"bg": {"red": 0.984, "green": 0.737, "blue": 0.016}, "fg": BLACK_TEXT,  # #FABB04 golden yellow
                     "tab": {"red": 0.949, "green": 0.577, "blue": 0.176}},                  # #F1932D
    "Daily Log":    {"bg": DEFAULT_BG, "fg": WHITE_TEXT,                                      # #3C495C slate
                     "tab": {"red": 0.176, "green": 0.647, "blue": 0.749}},                  # #2DA5BE
    "Strength Log": {"bg": {"red": 0.918, "green": 0.600, "blue": 0.600}, "fg": BLACK_TEXT,  # #EA9999 salmon pink
                     "tab": {"red": 0.847, "green": 0.278, "blue": 0.278}},                  # #D84747
    "Overall Analysis": {"bg": {"red": 0.580, "green": 0.510, "blue": 0.690}, "fg": WHITE_TEXT,  # #9482B0 muted purple
                         "tab": {"red": 0.478, "green": 0.380, "blue": 0.620}},                  # #7A619E
}

THIN = {"style": "SOLID", "width": 1, "color": BORDER_C}

HEADER_H = 40   # px — taller for visual weight
DATA_H   = 24   # px — slightly taller than default 21

# Number formats for Garmin tab columns that need thousands separators or decimals.
# {col_index (0-based): pattern}
_GARMIN_NUMBER_FORMATS = {
    8:  "#,##0",     # I: Steps
    9:  "#,##0",     # J: Total Calories Burned
    10: "#,##0",     # K: Active Calories Burned
    11: "#,##0",     # L: BMR Calories
    27: "#,##0",     # AB: Activity Calories
    37: "0",         # AL: SpO2 Avg (integer %)
    38: "0",         # AM: SpO2 Min (integer %)
}

# manual_cols: list of (start_col, end_col) 0-indexed ranges to highlight cream
TABS = [
    ("Garmin",           HEADERS,             []),
    ("Sleep",            SLEEP_HEADERS,       [(6, 7)]),                   # G: Notes
    ("Nutrition",        NUTRITION_HEADERS,   [(5, 14), (15, 16)]),        # F-N, P
    ("Session Log",      SESSION_LOG_HEADERS, [(3, 6)]),                    # D-F
    ("Daily Log",        DAILY_LOG_HEADERS,   [(2, 22)]),                  # C-V (all manual)
    ("Strength Log",     STRENGTH_LOG_HEADERS,[]),
    ("Overall Analysis", OVERALL_ANALYSIS_HEADERS, [(7, 9)]),  # H-I: Cognition, Cognition Notes
]

# Explicit width overrides (tab_name -> {col_index: px}). Applied AFTER auto-sizing.
# Use for columns where analysis text or notes need a fixed wide column.
WIDTH_OVERRIDES = {
    "Sleep": {5: 350, 9: 100, 10: 100, 22: 130},  # F: Sleep Analysis, J-K: Variability, W: HRV
    "Garmin": {20: 200, 21: 120, 22: 100},  # U: Activity Name, V: Activity Type, W: Start Time
    "Session Log": {5: 250, 6: 160},    # F: Notes, G: Activity Name
    "Nutrition": {6: 200, 7: 200, 8: 200},  # G: Lunch, H: Dinner, I: Snacks — meal descriptions
    "Daily Log": {15: 300, 21: 300},    # P: Midday Notes, V: Evening Notes — free text
    "Overall Analysis": {5: 300, 6: 250, 9: 300, 10: 300, 11: 250},  # F,G,J,K,L: long-text cols
}

# Columns that must always be CENTER-aligned regardless of auto-detection.
# {tab_name: set of col_indices}
FORCE_CENTER_COLS = {
    "Garmin": {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 14, 15, 16, 17, 18, 19, 37, 38},
    # A-I: Day-Steps, M: Stress, O-T: Floors-BB Low, AL-AM: SpO2
    "Sleep": {0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23},
    # A-E: Day-Total Sleep, H-X: Bedtime thru Body Battery Gained (all short numeric/time)
    "Nutrition": {0, 1, 9, 10, 11, 12, 13, 14},
    # A-B: Day/Date, J-O: Total Consumed thru Calorie Balance (numeric)
    "Session Log": {0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 21},
    # A-B, C-E: Type/Effort/Energy, H-S: Duration-Zone5, V: Elevation
    "Daily Log": {3, 4, 5, 6, 7, 8, 9},  # D-J: checkbox columns
    "Overall Analysis": {0, 1, 2, 3, 4},  # A-E: Day, Date, Readiness Score, Label, Confidence
    "Strength Log": {0, 1, 4, 5, 6},  # A-B: Day/Date, E-G: Weight/Reps/RPE
}

# ── Column intelligence ───────────────────────────────────────────────────────

# Approximate pixels per character at each font size (Google Sheets, Calibri-like)
_HDR_PX_PER_CH = 7.5   # 11pt bold header
_DATA_PX_PER_CH = 7.0   # 10pt data
_PADDING = 24            # cell padding (left + right margins)
_MIN_WIDTH = 55          # absolute minimum column width
_MAX_WIDTH_NUMERIC = 155 # cap for numeric columns (header-driven width)
_MAX_WIDTH_TEXT = 200    # cap for short text columns
_WIDE_TEXT_WIDTH = 300   # for long-form text (notes, feedback, analysis)
_WIDE_TEXT_THRESHOLD = 50  # if max data > this many chars, treat as wide text


def _is_numeric_column(header, sample_values):
    """Determine if a column is numeric based on its data (not header name)."""
    # Special cases: dates, times, booleans are NOT numeric for alignment purposes
    date_like = {"Date"}
    time_like = {"Bedtime", "Wake Time", "Start Time"}
    bool_like = {"TRUE", "FALSE"}
    if header in date_like or header in time_like:
        return False
    non_empty = [v for v in sample_values if v]
    if not non_empty:
        return True  # empty columns default to numeric (scores, etc.)
    # Check if all non-empty values are booleans
    if all(v.upper() in bool_like for v in non_empty[:20]):
        return False
    # Check if majority of non-empty values parse as numbers
    numeric_count = 0
    for v in non_empty[:50]:
        try:
            float(v.replace(",", ""))
            numeric_count += 1
        except (ValueError, TypeError):
            pass
    return numeric_count > len(non_empty[:50]) * 0.7


def compute_column_widths(headers, data_rows):
    """Compute optimal pixel width for each column based on header and data.

    Returns:
        list of (width_px, is_text) tuples, one per column.
    """
    result = []
    for col_idx, header in enumerate(headers):
        # Gather sample values
        samples = []
        max_data_len = 0
        for row in data_rows[:200]:
            if col_idx < len(row) and row[col_idx]:
                val = str(row[col_idx])
                samples.append(val)
                max_data_len = max(max_data_len, len(val))

        is_text = not _is_numeric_column(header, samples)

        # Header width needed (wrapped headers get 2 lines in 40px height)
        # If header wraps to 2 lines, we only need ~half the single-line width
        header_single_px = len(header) * _HDR_PX_PER_CH + _PADDING
        # Headers wrap at 40px height; estimate 2 lines fit comfortably
        header_px = header_single_px if len(header) <= 12 else max(header_single_px * 0.6, _MIN_WIDTH)

        # Data width needed
        data_px = max_data_len * _DATA_PX_PER_CH + _PADDING

        if is_text and max_data_len > _WIDE_TEXT_THRESHOLD:
            # Long text column — fixed wide width, will wrap
            width = _WIDE_TEXT_WIDTH
        elif is_text:
            # Short text — fit header and data, cap at max
            width = min(max(header_px, data_px), _MAX_WIDTH_TEXT)
        else:
            # Numeric — fit header (usually wider than data), cap
            width = min(max(header_px, data_px), _MAX_WIDTH_NUMERIC)

        width = max(int(width), _MIN_WIDTH)
        result.append((width, is_text))

    return result


# ── Builder ────────────────────────────────────────────────────────────────────

def _compute_week_colors(all_rows):
    """Compute per-row background colors based on Sunday-Saturday week grouping.

    Returns a list of colors (one per data row), alternating white/gray per week.
    Date is in column B (index 1).
    Uses absolute week parity (week_num % 2) so colors are stable regardless of
    which rows exist or what order they appear in.
    """
    colors = []
    last_color = BAND_ODD  # fallback for non-date rows

    for row in all_rows[1:]:  # skip header
        date_str = row[1].strip() if len(row) > 1 else ""
        try:
            d = _date.fromisoformat(date_str)
            days_since_ref = (d - _date(2000, 1, 2)).days  # 2000-01-02 was a Sunday
            week_num = days_since_ref // 7
            last_color = BAND_EVEN if (week_num % 2) == 1 else BAND_ODD
        except (ValueError, TypeError):
            pass  # keep last_color for non-date rows

        colors.append(last_color)

    return colors


def build_requests(sheet_id, n_cols, data_end, manual_col_ranges,
                    header_bg=None, header_fg=None, week_colors=None):
    """Build core formatting requests for one tab (colors, borders, heights).

    If week_colors is provided, uses per-week banding instead of addBanding.
    """
    requests = []

    _bg = header_bg or DEFAULT_BG
    _fg = header_fg or WHITE_TEXT

    # 1. Header row
    requests.append({"repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 0, "endRowIndex": 1,
            "startColumnIndex": 0, "endColumnIndex": n_cols,
        },
        "cell": {"userEnteredFormat": {
            "backgroundColor":    _bg,
            "horizontalAlignment": "CENTER",
            "verticalAlignment":   "MIDDLE",
            "wrapStrategy":        "WRAP",
            "textFormat": {
                "bold": True,
                "fontSize": 11,
                "foregroundColor": _fg,
            },
        }},
        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                  "verticalAlignment,wrapStrategy,textFormat)",
    }})

    # 2. Reset data rows to white (empty {} defaults to black RGB 0,0,0)
    requests.append({"repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 1, "endRowIndex": data_end,
            "startColumnIndex": 0, "endColumnIndex": n_cols,
        },
        "cell": {"userEnteredFormat": {"backgroundColor": BAND_ODD}},
        "fields": "userEnteredFormat.backgroundColor",
    }})

    # 3. Week-based banding (group contiguous same-color rows into batch requests)
    if week_colors:
        i = 0
        while i < len(week_colors):
            color = week_colors[i]
            start = i
            while i < len(week_colors) and week_colors[i] == color:
                i += 1
            # start..i is a contiguous run of the same color
            requests.append({"repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start + 1,  # +1 for header
                    "endRowIndex": i + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": n_cols,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                "fields": "userEnteredFormat.backgroundColor",
            }})
    else:
        # Fallback: simple alternating row banding
        requests.append({"addBanding": {
            "bandedRange": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": data_end,
                    "startColumnIndex": 0,
                    "endColumnIndex": n_cols,
                },
                "rowProperties": {
                    "firstBandColor":  BAND_ODD,
                    "secondBandColor": BAND_EVEN,
                },
            }
        }})

    # 4. Manual column cream overlay
    for col_start, col_end in manual_col_ranges:
        requests.append({"repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": data_end,
                "startColumnIndex": col_start, "endColumnIndex": min(col_end, n_cols),
            },
            "cell": {"userEnteredFormat": {"backgroundColor": CREAM}},
            "fields": "userEnteredFormat.backgroundColor",
        }})

    # 5. Default data row text: dark, 10pt, centered
    requests.append({"repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 1, "endRowIndex": data_end,
            "startColumnIndex": 0, "endColumnIndex": n_cols,
        },
        "cell": {"userEnteredFormat": {
            "horizontalAlignment": "CENTER",
            "verticalAlignment":   "MIDDLE",
            "textFormat": {
                "fontSize": 10,
                "bold": False,
                "foregroundColor": DATA_TEXT,
            },
        }},
        "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat)",
    }})

    # 6. Grid borders
    requests.append({"updateBorders": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 0, "endRowIndex": data_end,
            "startColumnIndex": 0, "endColumnIndex": n_cols,
        },
        "top":             THIN,
        "bottom":          THIN,
        "left":            THIN,
        "right":           THIN,
        "innerHorizontal": THIN,
        "innerVertical":   THIN,
    }})

    # 7. Row heights
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "ROWS",
                  "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": HEADER_H},
        "fields": "pixelSize",
    }})
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "ROWS",
                  "startIndex": 1, "endIndex": data_end},
        "properties": {"pixelSize": DATA_H},
        "fields": "pixelSize",
    }})

    return requests


def build_column_format_requests(sheet_id, data_end, col_widths, overrides=None,
                                  force_center=None):
    """Build column width + text alignment requests based on auto-computed widths.

    Args:
        col_widths: list of (width_px, is_text) from compute_column_widths().
        overrides: optional dict of {col_index: width_px} for manual overrides.
        force_center: optional set of col indices that must stay centered (not left-aligned).
    """
    requests = []
    overrides = overrides or {}
    force_center = force_center or set()

    # Track contiguous runs of text columns and numeric columns for batch formatting
    text_ranges = []   # (start_idx, end_idx) of contiguous text columns
    current_text_start = None

    for col_idx, (width, is_text) in enumerate(col_widths):
        # Apply override if present
        final_width = overrides.get(col_idx, width)

        # Set column width
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": col_idx, "endIndex": col_idx + 1},
            "properties": {"pixelSize": final_width},
            "fields": "pixelSize",
        }})

        # Track text column runs (skip force-center columns)
        treat_as_text = is_text and col_idx not in force_center
        if treat_as_text:
            if current_text_start is None:
                current_text_start = col_idx
        else:
            if current_text_start is not None:
                text_ranges.append((current_text_start, col_idx))
                current_text_start = None

    # Close final run
    if current_text_start is not None:
        text_ranges.append((current_text_start, len(col_widths)))

    # Apply left-align + wrap to all text column ranges
    for start, end in text_ranges:
        requests.append({"repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": data_end,
                "startColumnIndex": start, "endColumnIndex": end,
            },
            "cell": {"userEnteredFormat": {
                "wrapStrategy": "WRAP",
                "horizontalAlignment": "LEFT",
            }},
            "fields": "userEnteredFormat(wrapStrategy,horizontalAlignment)",
        }})

    return requests


# ── Standalone banding for garmin_sync integration ────────────────────────────

# Lookup: tab name -> list of (start_col, end_col) manual (cream) column ranges
_MANUAL_COLS_BY_TAB = {name: cols for name, _hdrs, cols in TABS}


def apply_weekly_banding_to_tab(wb, tab_name):
    """Apply weekly white/grey banding to a single tab (lightweight, safe to call every sync).

    Skips manual-entry (cream) columns so their yellow background is preserved.
    """
    try:
        sheet = wb.worksheet(tab_name)
    except Exception:
        return

    all_rows = sheet.get_all_values()
    if len(all_rows) < 2:
        return

    week_colors = _compute_week_colors(all_rows)
    if not week_colors:
        return

    n_cols = len(all_rows[0])
    manual_ranges = _MANUAL_COLS_BY_TAB.get(tab_name, [])

    # Build set of column indices to skip (manual-entry cream columns)
    skip_cols = set()
    for start, end in manual_ranges:
        for c in range(start, end):
            skip_cols.add(c)

    # Determine non-skip column ranges (contiguous runs of non-manual columns)
    col_runs = []
    c = 0
    while c < n_cols:
        if c in skip_cols:
            c += 1
            continue
        run_start = c
        while c < n_cols and c not in skip_cols:
            c += 1
        col_runs.append((run_start, c))

    requests = []
    # Group contiguous same-color rows into batch requests, per column run
    i = 0
    while i < len(week_colors):
        color = week_colors[i]
        start = i
        while i < len(week_colors) and week_colors[i] == color:
            i += 1
        for col_start, col_end in col_runs:
            requests.append({"repeatCell": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": start + 1,
                    "endRowIndex": i + 1,
                    "startColumnIndex": col_start,
                    "endColumnIndex": col_end,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                "fields": "userEnteredFormat.backgroundColor",
            }})

    # Ensure Garmin number formats cover newly added rows
    if tab_name == "Garmin":
        data_end = len(all_rows) + 10  # small buffer beyond current data
        for col_idx, pattern in _GARMIN_NUMBER_FORMATS.items():
            requests.append({"repeatCell": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": 1, "endRowIndex": data_end,
                    "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
                },
                "cell": {"userEnteredFormat": {
                    "numberFormat": {"type": "NUMBER", "pattern": pattern},
                }},
                "fields": "userEnteredFormat.numberFormat",
            }})

    if requests:
        # Batch in chunks of 500 to stay within API limits
        for chunk_start in range(0, len(requests), 500):
            wb.batch_update({"requests": requests[chunk_start:chunk_start + 500]})


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to Google Sheets...")
    wb = get_workbook()

    # Remove all existing banded ranges first to avoid addBanding conflicts
    metadata = wb.fetch_sheet_metadata()
    remove_banding_requests = []
    for s in metadata.get("sheets", []):
        for br in s.get("bandedRanges", []):
            remove_banding_requests.append({
                "deleteBanding": {"bandedRangeId": br["bandedRangeId"]}
            })
    if remove_banding_requests:
        wb.batch_update({"requests": remove_banding_requests})
        print(f"  Cleared {len(remove_banding_requests)} existing banded range(s)")

    all_requests = []

    for tab_name, headers, manual_cols in TABS:
        try:
            sheet = wb.worksheet(tab_name)
        except Exception:
            print(f"  Skipped: {tab_name} (not found)")
            continue

        all_rows = sheet.get_all_values()
        if not all_rows:
            print(f"  Skipped: {tab_name} (empty)")
            continue

        n_data   = len(all_rows) - 1
        n_cols   = len(headers)
        data_end = max(n_data + 50, 100)

        style = TAB_STYLES.get(tab_name, {})
        week_colors = _compute_week_colors(all_rows)
        reqs = build_requests(sheet.id, n_cols, data_end, manual_cols,
                              header_bg=style.get("bg"),
                              header_fg=style.get("fg"),
                              week_colors=week_colors)

        # Set tab color
        if "tab" in style:
            reqs.append({"updateSheetProperties": {
                "properties": {
                    "sheetId": sheet.id,
                    "tabColorStyle": {"rgbColor": style["tab"]},
                },
                "fields": "tabColorStyle",
            }})

        # Auto-compute column widths and text alignment
        col_widths = compute_column_widths(headers, all_rows[1:])
        overrides = WIDTH_OVERRIDES.get(tab_name, {})
        fc = FORCE_CENTER_COLS.get(tab_name, set())
        reqs.extend(build_column_format_requests(sheet.id, data_end, col_widths, overrides,
                                                  force_center=fc))

        # Number formats for Garmin tab (thousands separators on Steps, Calories)
        if tab_name == "Garmin":
            for col_idx, pattern in _GARMIN_NUMBER_FORMATS.items():
                reqs.append({"repeatCell": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 1, "endRowIndex": data_end,
                        "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
                    },
                    "cell": {"userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": pattern},
                    }},
                    "fields": "userEnteredFormat.numberFormat",
                }})

        # Auto-resize rows to fit wrapped text on tabs with free-text columns
        if tab_name in ("Sleep", "Nutrition", "Daily Log", "Session Log", "Overall Analysis"):
            reqs.append({"autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet.id,
                    "dimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": n_data + 1,
                },
            }})

        all_requests.extend(reqs)
        print(f"  Queued: {tab_name} ({n_cols} cols, {n_data} data rows)")

    print(f"\nApplying {len(all_requests)} formatting requests in batches...")
    chunk = 500
    for i, start in enumerate(range(0, len(all_requests), chunk)):
        wb.batch_update({"requests": all_requests[start:start + chunk]})
        print(f"  Batch {i+1} done ({min(start+chunk, len(all_requests))}/{len(all_requests)})")

    # Apply Sleep tab color grading (conditional formatting)
    print("\nApplying Sleep color grading...")
    apply_sleep_color_grading(wb)

    # Apply Session Log activity-specific color grading
    print("Applying Session Log color grading...")
    apply_session_log_color_grading(wb)

    # Apply Sleep Analysis verdict + action rich text formatting
    print("Applying Sleep verdict formatting...")
    apply_sleep_verdict_formatting(wb)

    # Verify all conditional formatting is intact after full reformat
    try:
        from verify_formatting import verify_and_repair
        verify_and_repair(wb)
    except Exception as e:
        print(f"\n  Formatting verification skipped (non-fatal): {e}")

    print("\nDone. Style applied:")
    print("  Headers:    per-tab colors, 11pt bold, centered, 40px tall")
    print("  Data rows:  alternating white / #F3F4F6, 24px tall, 10pt")
    print("  Columns:    auto-sized widths, text=left+wrap, numeric=center")
    print("  Borders:    1px #DBDDE1 grid lines")
    print("  Sleep tab:  color grading on all measurable columns")
    print("  Tab colors: Garmin=blue, Sleep=purple, Nutrition=green, Session=orange, Daily=teal, Strength=red")


if __name__ == "__main__":
    main()
