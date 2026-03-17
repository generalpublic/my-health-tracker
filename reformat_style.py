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
from garmin_sync import (
    get_workbook, HEADERS, SLEEP_HEADERS, NUTRITION_HEADERS, STRENGTH_LOG_HEADERS,
    apply_sleep_color_grading, apply_sleep_verdict_formatting,
)
from setup_daily_log import DAILY_LOG_HEADERS
from verify_sheets import SESSION_LOG_HEADERS

load_dotenv(Path(__file__).parent / ".env")

# ── Design tokens ──────────────────────────────────────────────────────────────

# Shared colors
DEFAULT_BG = {"red": 0.235, "green": 0.286, "blue": 0.361}  # #3C495C slate (fallback)
WHITE_TEXT  = {"red": 1.0,   "green": 1.0,   "blue": 1.0  }
BLACK_TEXT  = {"red": 0.0,   "green": 0.0,   "blue": 0.0  }
BAND_ODD   = {"red": 1.0,   "green": 1.0,   "blue": 1.0  }  # white rows
BAND_EVEN  = {"red": 0.953, "green": 0.957, "blue": 0.965}  # #F3F4F6  alt rows
CREAM      = {"red": 1.0,   "green": 0.992, "blue": 0.929}  # #FFFDED  soft fill indicator
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
}

THIN = {"style": "SOLID", "width": 1, "color": BORDER_C}

HEADER_H = 40   # px — taller for visual weight
DATA_H   = 24   # px — slightly taller than default 21

# manual_cols: list of (start_col, end_col) 0-indexed ranges to highlight cream
TABS = [
    ("Garmin",           HEADERS,             []),
    ("Sleep",            SLEEP_HEADERS,       [(6, 9)]),                   # G: Notes, H: Cognition, I: Cognition Notes
    ("Nutrition",        NUTRITION_HEADERS,   [(5, 14), (15, 16)]),        # F-N, P
    ("Session Log",      SESSION_LOG_HEADERS, [(3, 6), (22, 23)]),         # D-F, W
    ("Daily Log",        DAILY_LOG_HEADERS,   [(2, 22)]),                  # C-V (all manual)
    ("Strength Log",     STRENGTH_LOG_HEADERS,[]),
]

# Explicit width overrides (tab_name -> {col_index: px}). Applied AFTER auto-sizing.
# Use for columns where analysis text or notes need a fixed wide column.
WIDTH_OVERRIDES = {
    "Sleep": {5: 350, 8: 250},  # F: Sleep Analysis, I: Cognition Notes — wide for free text
    "Garmin": {20: 200},        # U: Activity Name — longer text
}

# Columns that must always be CENTER-aligned regardless of auto-detection.
# {tab_name: set of col_indices}
FORCE_CENTER_COLS = {
    "Sleep": {7, 9, 10},         # H: Cognition (1-10), J: Bedtime, K: Wake Time
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
    """
    colors = []
    current_week = None
    week_parity = 0  # 0 = white, 1 = gray

    for row in all_rows[1:]:  # skip header
        date_str = row[1].strip() if len(row) > 1 else ""
        try:
            d = _date.fromisoformat(date_str)
            # Week number: days since a reference Sunday, integer-divided by 7
            # weekday(): Monday=0..Sunday=6, so Sunday = 6
            # We want Sunday-Saturday weeks, so use isocalendar or manual calc
            # days_since_epoch_sunday groups by Sun-Sat week
            days_since_ref = (d - _date(2000, 1, 2)).days  # 2000-01-02 was a Sunday
            week_num = days_since_ref // 7
        except (ValueError, TypeError):
            week_num = current_week  # keep same week for non-date rows

        if week_num is not None and week_num != current_week:
            if current_week is not None:
                week_parity = 1 - week_parity
            current_week = week_num

        colors.append(BAND_ODD if week_parity == 0 else BAND_EVEN)

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

    # 2. Clear explicit backgrounds on data rows so banding shows through
    requests.append({"repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 1, "endRowIndex": data_end,
            "startColumnIndex": 0, "endColumnIndex": n_cols,
        },
        "cell": {"userEnteredFormat": {"backgroundColor": {}}},
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

        # Sleep tab: auto-resize rows to fit long wrapped analysis text
        if tab_name == "Sleep":
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

    # Apply Sleep Analysis verdict + action rich text formatting
    print("Applying Sleep verdict formatting...")
    apply_sleep_verdict_formatting(wb)

    print("\nDone. Style applied:")
    print("  Headers:    per-tab colors, 11pt bold, centered, 40px tall")
    print("  Data rows:  alternating white / #F3F4F6, 24px tall, 10pt")
    print("  Columns:    auto-sized widths, text=left+wrap, numeric=center")
    print("  Borders:    1px #DBDDE1 grid lines")
    print("  Sleep tab:  color grading on all measurable columns")
    print("  Tab colors: Garmin=blue, Sleep=purple, Nutrition=green, Session=orange, Daily=teal, Strength=red")


if __name__ == "__main__":
    main()
