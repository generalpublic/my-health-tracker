"""
format_all_headers.py — Apply uniform header formatting across all Google Sheets tabs.

Applies to every tab:
  - Font size 11, bold, centered
  - Column widths sized to show the full header text
  - Background color preserved (not overwritten)

Usage:
    python format_all_headers.py
"""

from pathlib import Path
from dotenv import load_dotenv
from utils import get_workbook
from schema import (
    HEADERS, SLEEP_HEADERS, NUTRITION_HEADERS, ARCHIVE_HEADERS,
    STRENGTH_LOG_HEADERS, DAILY_LOG_HEADERS, SESSION_LOG_HEADERS,
)

load_dotenv(Path(__file__).parent / ".env")

# ── Tab definitions ────────────────────────────────────────────────────────────
# (tab_name, header_list)

TABS = [
    ("Garmin",            HEADERS),
    ("Sleep",             SLEEP_HEADERS),
    ("Nutrition",         NUTRITION_HEADERS),
    ("Session Log",       SESSION_LOG_HEADERS),
    ("Daily Log",         DAILY_LOG_HEADERS),
    ("Strength Log",      STRENGTH_LOG_HEADERS),
    ("Raw Data Archive",  ARCHIVE_HEADERS),
]

# ── Helpers ────────────────────────────────────────────────────────────────────

# Approximate pixels per character at 11pt font
PIXELS_PER_CHAR = 8.5
MIN_COL_WIDTH   = 75


def header_pixel_width(text):
    """Return a pixel width that shows the full header text at 11pt."""
    return max(MIN_COL_WIDTH, int(len(text) * PIXELS_PER_CHAR) + 16)


def build_header_requests(sheet_id, headers):
    """Return the batch_update request list for one tab."""
    n_cols = len(headers)
    requests = []

    # 1. Font size 11, bold, centered — preserve background
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": n_cols,
            },
            "cell": {
                "userEnteredFormat": {
                    "horizontalAlignment": "CENTER",
                    "textFormat": {
                        "bold": True,
                        "fontSize": 11,
                    },
                }
            },
            # Only update alignment + textFormat — background color is NOT in fields
            "fields": "userEnteredFormat(horizontalAlignment,textFormat)",
        }
    })

    # 2. Column widths — one request per column
    for i, header in enumerate(headers):
        px = header_pixel_width(header)
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": i,
                    "endIndex": i + 1,
                },
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        })

    return requests


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to Google Sheets...")
    wb = get_workbook()

    all_requests = []
    skipped = []

    for tab_name, headers in TABS:
        try:
            sheet = wb.worksheet(tab_name)
        except Exception:
            skipped.append(tab_name)
            continue

        requests = build_header_requests(sheet.id, headers)
        all_requests.extend(requests)
        print(f"  Queued: {tab_name} ({len(headers)} columns)")

    if all_requests:
        print(f"\nApplying {len(all_requests)} formatting requests...")
        # Batch in chunks of 1000 to stay within API limits
        chunk_size = 1000
        for start in range(0, len(all_requests), chunk_size):
            wb.batch_update({"requests": all_requests[start:start + chunk_size]})
        print("Done.")
    else:
        print("No requests to apply.")

    if skipped:
        print(f"\nSkipped (tab not found): {skipped}")

    print("\nHeader formatting applied:")
    print("  Font: 11pt, bold, centered")
    print("  Column widths: sized to fit header text")
    print("  Background colors: unchanged")


if __name__ == "__main__":
    main()
