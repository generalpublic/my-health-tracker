"""
verify_sheets.py — Post-edit integrity checker for all Google Sheets tabs.

Run after ANY edit to Google Sheets to catch misalignment, bad data types,
overwritten cells, and structural issues before they compound.

Usage:
    python verify_sheets.py              # Check all tabs
    python verify_sheets.py --tab Sleep  # Check one tab
"""

import re
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from utils import get_workbook
from schema import (
    HEADERS, SLEEP_HEADERS, NUTRITION_HEADERS, SESSION_LOG_HEADERS,
    DAILY_LOG_HEADERS, OVERALL_ANALYSIS_HEADERS, EXPECTED_HEADERS,
)

load_dotenv(Path(__file__).parent / ".env")

# ── Type rules ────────────────────────────────────────────────────────────────
# (tab, col_letter, rule_name, validator_fn, description)

def is_date(v):
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', v))

def is_numeric(v):
    try:
        float(str(v).replace(",", ""))
        return True
    except (ValueError, TypeError):
        return False

def is_time_hhmm(v):
    return bool(re.match(r'^\d{1,2}:\d{2}$', v))


def is_not_date_serial(v):
    """Detect Sheets date serials (4-5 digit numbers like 46084) in date columns."""
    if is_numeric(v):
        f = float(v)
        return not (40000 < f < 60000)
    return True

def is_plain_text_date(v):
    return is_date(v) and is_not_date_serial(v)

TYPE_RULES = {
    "Garmin": [
        ("B", "date format",     is_plain_text_date,  "Date must be YYYY-MM-DD text, not a serial"),
        ("C", "numeric or empty", lambda v: is_numeric(v),   "Sleep Score must be numeric"),
        ("F", "numeric or empty", lambda v: is_numeric(v),   "Resting HR must be numeric"),
        ("G", "numeric or empty", lambda v: is_numeric(v),   "Sleep Duration must be numeric"),
        ("H", "numeric or empty", lambda v: is_numeric(v),   "Body Battery must be numeric"),
        ("I", "numeric or empty", lambda v: is_numeric(v),   "Steps must be numeric"),
    ],
    "Sleep": [
        ("B", "date format",     is_plain_text_date,  "Date must be YYYY-MM-DD text"),
        ("C", "numeric or empty", lambda v: is_numeric(v),   "Garmin Sleep Score must be numeric"),
        ("D", "numeric or empty", lambda v: is_numeric(v),   "Sleep Analysis Score must be numeric"),
        ("E", "numeric or empty", lambda v: is_numeric(v),   "Total Sleep must be numeric"),
        ("H", "HH:MM or empty",  is_time_hhmm,        "Bedtime must be HH:MM — if decimal, USER_ENTERED was used"),
        ("I", "HH:MM or empty",  is_time_hhmm,        "Wake Time must be HH:MM"),
        ("J", "numeric or empty", lambda v: is_numeric(v),   "Time in Bed must be numeric"),
        ("U", "numeric or empty", lambda v: is_numeric(v),   "Overnight HRV must be numeric"),
        ("V", "numeric or empty", lambda v: is_numeric(v),   "Body Battery Gained must be numeric"),
    ],
    "Nutrition": [
        ("B", "date format",     is_plain_text_date,  "Date must be YYYY-MM-DD text"),
        ("C", "numeric or empty", lambda v: is_numeric(v),   "Total Calories Burned must be numeric"),
        ("D", "numeric or empty", lambda v: is_numeric(v),   "Active Calories must be numeric"),
        ("E", "numeric or empty", lambda v: is_numeric(v),   "BMR Calories must be numeric"),
    ],
    "Session Log": [
        ("B", "date format",     is_plain_text_date,  "Date must be YYYY-MM-DD text"),
        ("H", "numeric or empty", lambda v: is_numeric(v),   "Duration must be numeric"),
        ("I", "numeric or empty", lambda v: is_numeric(v),   "Distance must be numeric"),
        ("J", "numeric or empty", lambda v: is_numeric(v),   "Avg HR must be numeric"),
    ],
    "Overall Analysis": [
        ("B", "date format",     is_plain_text_date,  "Date must be YYYY-MM-DD text"),
        ("C", "numeric or empty", lambda v: is_numeric(v),   "Readiness Score must be numeric"),
        ("H", "numeric or empty", lambda v: is_numeric(v),   "Cognition must be numeric"),
    ],
}

# ── Checks ────────────────────────────────────────────────────────────────────

def col_letter_to_index(col):
    """Convert 'A'->0, 'B'->1, 'AA'->26, etc."""
    result = 0
    for c in col.upper():
        result = result * 26 + (ord(c) - ord('A') + 1)
    return result - 1

def check_tab(sheet, tab_name):
    issues = []
    warnings = []

    all_rows = sheet.get_all_values()
    if not all_rows:
        issues.append("Tab is completely empty")
        return issues, warnings

    headers = all_rows[0]
    # Date column index: col B (1) for all tabs
    date_col_idx = 1
    # Only count rows that have an actual date — ignores blank/checkbox-only rows
    data_rows = [r for r in all_rows[1:] if r and len(r) > date_col_idx and r[date_col_idx] and str(r[date_col_idx]).startswith("20")]

    # 1. Header check
    expected = EXPECTED_HEADERS.get(tab_name)
    if expected:
        # For tabs with legend columns beyond the main headers (e.g. Overall Analysis),
        # only compare the main header columns
        check_headers = headers[:len(expected)] if len(headers) > len(expected) else headers
        if check_headers != expected:
            missing = [h for h in expected if h not in check_headers]
            extra   = [h for h in check_headers if h not in expected]
            wrong_order = check_headers != expected and set(check_headers) == set(expected)
            if missing:
                issues.append(f"MISSING headers: {missing}")
            if extra:
                issues.append(f"UNEXPECTED headers: {extra}")
            if wrong_order:
                issues.append(f"Headers exist but are in wrong order")
            if not missing and not extra and not wrong_order:
                issues.append(f"Header mismatch (unknown cause). Got: {headers}")
        else:
            pass  # headers OK

    # 2. Row count
    if len(data_rows) == 0:
        warnings.append("No data rows (only headers)")
        return issues, warnings

    # 3. Column count consistency
    col_count = len(headers)
    short_rows = [(i+2, len(r)) for i, r in enumerate(data_rows) if len(r) < col_count and any(r)]
    if short_rows:
        warnings.append(f"{len(short_rows)} rows have fewer columns than header ({col_count}): rows {[r for r,_ in short_rows[:5]]}")

    # 4. Type checks
    rules = TYPE_RULES.get(tab_name, [])
    for col_letter, rule_name, validator, description in rules:
        col_idx = col_letter_to_index(col_letter)
        bad_rows = []
        for i, row in enumerate(data_rows):
            val = row[col_idx] if col_idx < len(row) else ""
            if val == "":
                continue  # empty is always OK
            if not validator(val):
                bad_rows.append((i + 2, val))
        if bad_rows:
            sample = bad_rows[:3]
            issues.append(
                f"Col {col_letter} ({rule_name}) — {len(bad_rows)} bad values. "
                f"Description: {description}. "
                f"Sample: {[(r, repr(v)) for r,v in sample]}"
            )

    # 5. Duplicate dates
    dates = [row[date_col_idx] for row in data_rows if row and len(row) > date_col_idx and row[date_col_idx]]
    if tab_name != "Session Log":  # Session Log allows multiple rows per date
        seen = {}
        for i, d in enumerate(dates):
            if d in seen:
                issues.append(f"Duplicate date {d!r} at rows {seen[d]+2} and {i+2}")
            seen[d] = i

    # 6. Date ordering (should be descending)
    valid_dates = [d for d in dates if is_date(d)]
    if len(valid_dates) > 1:
        out_of_order = sum(1 for a, b in zip(valid_dates, valid_dates[1:]) if a < b)
        if out_of_order > 0:
            warnings.append(f"Date column not fully sorted descending ({out_of_order} out-of-order pairs)")

    # 7. Blank rows in the middle of data
    blank_rows = [i+2 for i, row in enumerate(data_rows) if not any(row)]
    if blank_rows:
        warnings.append(f"Blank rows found: {blank_rows[:10]}")

    return issues, warnings


def run_verify(tabs_to_check=None):
    print("Connecting to Google Sheets...")
    wb = get_workbook()

    check_tabs = tabs_to_check or list(EXPECTED_HEADERS.keys())
    all_pass = True

    for tab_name in check_tabs:
        try:
            sheet = wb.worksheet(tab_name)
        except Exception as e:
            print(f"\n[{tab_name}] ERROR — tab not found: {e}")
            all_pass = False
            continue

        all_rows = sheet.get_all_values()
        dcol = 1  # Date is col B for all tabs
        row_count = sum(1 for r in all_rows[1:] if r and len(r) > dcol and r[dcol] and str(r[dcol]).startswith("20"))

        issues, warnings = check_tab(sheet, tab_name)

        status = "PASS" if not issues else "FAIL"
        if status == "FAIL":
            all_pass = False

        print(f"\n[{tab_name}] {status} — {row_count} data rows")

        if issues:
            for issue in issues:
                print(f"  ERROR:   {issue}")
        if warnings:
            for w in warnings:
                print(f"  WARNING: {w}")
        if not issues and not warnings:
            print(f"  All checks passed.")

    print()
    if all_pass:
        print("OVERALL: PASS — no issues found")
    else:
        print("OVERALL: FAIL — see errors above")

    return all_pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify Google Sheets integrity after edits.")
    parser.add_argument("--tab", help="Check a single tab by name (e.g. Sleep)")
    args = parser.parse_args()

    tabs = [args.tab] if args.tab else None
    passed = run_verify(tabs)
    sys.exit(0 if passed else 1)
