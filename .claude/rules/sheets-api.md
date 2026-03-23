# Google Sheets API Technical Rules (Non-Negotiable)

These rules were learned from real bugs. Apply them whenever touching Google Sheets data.

---

## Data Types: RAW vs USER_ENTERED
- NEVER use `value_input_option="USER_ENTERED"` for time strings ("HH:MM") — Sheets parses them as decimal fractions (e.g., 0.3854)
- NEVER use `USER_ENTERED` for date strings ("YYYY-MM-DD") — Sheets parses them as date serials (e.g., 46084)
- Use `value_input_option="RAW"` for all text/time/date strings that must remain plain text
- Use `value_input_option="USER_ENTERED"` only for numbers that need formula evaluation
- Apply `"type": "TIME"` format in reformat_sheets so HH:MM text displays correctly in time columns

## Critical Data Type Rule (Mixed Rows)
- When writing rows with BOTH text (dates, times) AND numbers: write full row with `RAW`, then re-write numeric columns with `USER_ENTERED`
- NEVER use `USER_ENTERED` for an entire row containing dates ("YYYY-MM-DD") or times ("HH:MM") — Sheets converts them to serials
- NEVER leave numeric columns as `RAW` — gradient conditional formatting won't render on text

## Sorting with Mixed Types
- Mixed column (some cells = number serial, some = "YYYY-MM-DD" text) will NOT sort correctly — numbers and text sort in separate groups
- Before every sort: normalize the entire Date column to plain text using `RAW` mode
- Sort only after normalization is confirmed complete
- Pattern in `sort_sheet_by_date_desc()`: read column with FORMATTED_VALUE -> rewrite with RAW -> then sort

## Batch Writes (Quota)
- NEVER use per-cell `update_cell()` in a loop — hits 60-req/min quota after ~60 cells
- Always batch: read entire column -> modify list -> write entire column in ONE `sheet.update(range, values)` call
- For mixed cell types in same write: use `update_cells(cell_list, value_input_option=...)` with a Cell object list

## Column Alignment Discipline
- Every tab's row-build function must include ALL columns in exact header order, including empty placeholder columns ("" for manual-entry fields)
- If a placeholder column is missing from the write, every column after it shifts left — data lands in wrong column
- After any column structure change: verify column count matches header count before writing
- Session Log specific: Zone Ranges (col S) is manual — always write `""` as placeholder, then "Garmin Export" for Source (col T), then elevation for Elevation (col U)

## Datetime Serial Conversion
- Sheets epoch: December 30, 1899
- Convert serial to datetime: `base + timedelta(days=int(serial)) + timedelta(seconds=round(frac*86400))`
- Where `frac = serial - int(serial)` and `base = datetime(1899, 12, 30)`
- Always store datetime as plain text "YYYY-MM-DD HH:MM" using RAW mode — never let Sheets re-parse it

## Windows Terminal Compatibility
- Windows console (cp1252) cannot encode Unicode arrows like `->` (U+2192) — use ASCII `->` instead
- Interactive `input()` prompts fail when piped: use `echo "" | python script.py` or add `--no-prompt` flag
- Always test scripts in terminal before assuming they work
