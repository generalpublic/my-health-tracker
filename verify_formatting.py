"""Verify and auto-repair conditional formatting rules on all Google Sheets tabs.

Declarative spec defines what rules should exist. Verification reads actual rules
from the Sheets API and compares. Auto-repair re-runs the relevant apply functions
for any tab that fails.

Usage:
    python verify_formatting.py              # Verify all tabs
    python verify_formatting.py --tab Sleep  # Verify one tab
    python verify_formatting.py --repair     # Verify and auto-repair failures
"""

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Expected Formatting Spec — loaded from thresholds.json (single source of truth)
# ---------------------------------------------------------------------------
# Fallback hardcoded rules exist only as a safety net if JSON is missing/corrupt.

_THRESHOLDS_PATH = Path(__file__).parent / "thresholds.json"


def _load_expected_rules():
    """Load expected formatting rules from thresholds.json.

    Converts the JSON structure to the tuple-based format used by verification:
      gradient: (header, direction, min_val, mid_val, max_val)
      boolean:  (header, rule_count)
    """
    try:
        with open(_THRESHOLDS_PATH) as f:
            data = json.load(f)
        raw = data.get("sheets_formatting", {})
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        print("  WARNING: Could not load thresholds.json — using hardcoded fallback rules")
        return _FALLBACK_RULES

    rules = {}
    for tab_name, spec in raw.items():
        rules[tab_name] = {
            "gradient": [
                (g["header"], g["direction"], g["min"], g.get("mid"), g["max"])
                for g in spec.get("gradient", [])
            ],
            "boolean": [
                (b["header"], b["rule_count"])
                for b in spec.get("boolean", [])
            ],
            "total_rule_count": spec.get("total_rule_count", 0),
            "repair_fn": spec.get("repair_fn", ""),
        }
    return rules


# Hardcoded fallback — kept in sync manually, used only if thresholds.json is missing
_FALLBACK_RULES = {
    "Sleep": {
        "gradient": [
            ("Sleep Analysis Score", "higher_better", 50, 65, 80),
            ("Total Sleep (hrs)", "higher_better", 5, 7, 8),
            ("Time in Bed (hrs)", "higher_better", 6, 7.5, 8.5),
            ("Deep Sleep (min)", "higher_better", 45, 75, 100),
            ("Light Sleep (min)", "higher_better", 120, 180, 240),
            ("REM (min)", "higher_better", 60, 90, 120),
            ("Deep %", "higher_better", 12, 18, 22),
            ("REM %", "higher_better", 15, 20, 25),
            ("Sleep Cycles", "higher_better", 2, 4, 5),
            ("Overnight HRV (ms)", "higher_better", 30, 40, 48),
            ("Body Battery Gained", "higher_better", 15, 40, 65),
            ("Awake During Sleep (min)", "lower_better", 15, 30, 60),
            ("Awakenings", "lower_better", 1, 3, 6),
            ("Avg HR", "lower_better", 52, 58, 68),
            ("Avg Respiration", "lower_better", 15, 17, 20),
            ("Bedtime Variability (7d)", "lower_better", 30, 60, 90),
            ("Wake Variability (7d)", "lower_better", 30, 60, 90),
        ],
        "boolean": [("Bedtime", 5)],
        "total_rule_count": 22,
        "repair_fn": "sleep",
    },
    "Overall Analysis": {
        "gradient": [("Cognition (1-10)", "higher_better", 1, 5, 10)],
        "boolean": [("Readiness Score (1-10)", 5), ("Readiness Label", 5), ("Confidence", 4)],
        "total_rule_count": 15,
        "repair_fn": "overall_analysis",
    },
    "Daily Log": {
        "gradient": [
            ("Morning Energy (1-10)", "higher_better", 1, None, 10),
            ("Midday Energy (1-10)", "higher_better", 1, None, 10),
            ("Midday Focus (1-10)", "higher_better", 1, None, 10),
            ("Midday Mood (1-10)", "higher_better", 1, None, 10),
            ("Midday Body Feel (1-10)", "higher_better", 1, None, 10),
            ("Evening Energy (1-10)", "higher_better", 1, None, 10),
            ("Evening Focus (1-10)", "higher_better", 1, None, 10),
            ("Evening Mood (1-10)", "higher_better", 1, None, 10),
            ("Perceived Stress (1-10)", "lower_better", 1, None, 10),
            ("Day Rating (1-10)", "higher_better", 1, None, 10),
        ],
        "boolean": [],
        "total_rule_count": 10,
        "repair_fn": "daily_log",
    },
    "Session Log": {
        "gradient": [
            ("Duration (min)", "higher_better", 15, 35, 60),
            ("Distance (mi)", "higher_better", 1, 5, 15),
            ("Calories", "higher_better", 100, 400, 900),
        ],
        "boolean": [],
        "total_rule_count": 3,
        "repair_fn": "session_log",
    },
}

EXPECTED_RULES = _load_expected_rules()


# ---------------------------------------------------------------------------
# Core verification functions
# ---------------------------------------------------------------------------

def get_sheet_rules(wb, tab_name):
    """Fetch conditional format rules for a specific tab from Sheets API.

    Returns (sheet_id, rules_list) where rules_list is the raw conditionalFormats
    array from the API, or an empty list if no rules exist.
    """
    try:
        sheet = wb.worksheet(tab_name)
    except Exception:
        return None, []

    sid = sheet.id
    metadata = wb.fetch_sheet_metadata()
    for s in metadata.get("sheets", []):
        if s["properties"]["sheetId"] == sid:
            return sid, s.get("conditionalFormats", [])
    return sid, []


def _get_header_map(wb, tab_name):
    """Read header row and return {header_name: column_index} map."""
    try:
        sheet = wb.worksheet(tab_name)
        headers = sheet.row_values(1)
        return {h: i for i, h in enumerate(headers)}
    except Exception:
        return {}


def _rule_covers_column(rule, col_idx):
    """Check if a conditional format rule covers a specific column index."""
    for r in rule.get("ranges", []):
        start = r.get("startColumnIndex", 0)
        end = r.get("endColumnIndex", start + 1)
        if start <= col_idx < end:
            return True
    return False


def _is_gradient_rule(rule):
    """Check if a rule is a gradient rule."""
    return "gradientRule" in rule


def _is_boolean_rule(rule):
    """Check if a rule is a boolean rule."""
    return "booleanRule" in rule


def _check_gradient(rules, col_idx, direction, min_val, mid_val, max_val):
    """Check if a gradient rule exists on the given column with matching thresholds.

    Returns (found, detail_message).
    """
    for rule in rules:
        if not _is_gradient_rule(rule):
            continue
        if not _rule_covers_column(rule, col_idx):
            continue

        grad = rule["gradientRule"]
        minpt = grad.get("minpoint", {})
        maxpt = grad.get("maxpoint", {})

        # Check threshold values match (with tolerance)
        try:
            actual_min = float(minpt.get("value", 0))
            actual_max = float(maxpt.get("value", 0))
        except (ValueError, TypeError):
            continue

        if abs(actual_min - min_val) > 0.1 or abs(actual_max - max_val) > 0.1:
            continue

        # If midpoint specified, check it too
        if mid_val is not None:
            midpt = grad.get("midpoint", {})
            if midpt:
                try:
                    actual_mid = float(midpt.get("value", 0))
                    if abs(actual_mid - mid_val) > 0.1:
                        continue
                except (ValueError, TypeError):
                    continue

        return True, "OK"

    return False, f"col {col_idx}: no matching gradient (expected {min_val}/{mid_val}/{max_val})"


def _count_boolean_rules_on_column(rules, col_idx):
    """Count how many boolean rules cover a specific column."""
    count = 0
    for rule in rules:
        if _is_boolean_rule(rule) and _rule_covers_column(rule, col_idx):
            count += 1
    return count


def _spot_check_numeric_types(wb, tab_name, spec, hmap, sample_size=5):
    """Check that graded columns contain actual numbers, not text strings.

    Gradient conditional formatting silently ignores text cells even if the text
    looks like a number (e.g., "82" vs 82). This catches the most common cause
    of "rules exist but colors don't render."

    Uses ONE API call to read a sample block of all columns, then checks each
    graded column from the cached data.

    Returns a list of column names where text-as-number was found, or empty list if OK.
    """
    try:
        sheet = wb.worksheet(tab_name)
    except Exception:
        return []

    # Read a sample block (rows 2-6) of ALL columns in one API call
    try:
        result = sheet.spreadsheet.values_get(
            f"'{tab_name}'!A2:{sample_size + 1}",
            params={"valueRenderOption": "UNFORMATTED_VALUE"}
        )
    except Exception:
        return []

    sample_rows = result.get("values", [])
    if not sample_rows:
        return []

    text_columns = []
    for header, *_ in spec.get("gradient", []):
        col_idx = hmap.get(header)
        if col_idx is None:
            continue

        text_count = 0
        for row in sample_rows:
            if col_idx >= len(row):
                continue
            val = row[col_idx]
            if val == "" or val is None:
                continue
            if isinstance(val, str):
                try:
                    float(val)
                    text_count += 1
                except (ValueError, TypeError):
                    pass

        if text_count > 0:
            text_columns.append(header)

    return text_columns


def verify_tab_formatting(wb, tab_name):
    """Verify all expected conditional format rules exist for one tab.

    Returns (passed: bool, issues: list[str]).
    """
    spec = EXPECTED_RULES.get(tab_name)
    if spec is None:
        return True, []  # No spec = nothing to verify

    issues = []
    sid, rules = get_sheet_rules(wb, tab_name)

    if sid is None:
        issues.append(f"{tab_name}: tab not found")
        return False, issues

    # Get header map to resolve column names to indices
    hmap = _get_header_map(wb, tab_name)
    if not hmap:
        issues.append(f"{tab_name}: could not read headers")
        return False, issues

    # Check total rule count
    actual_count = len(rules)
    expected_count = spec["total_rule_count"]
    if actual_count < expected_count:
        issues.append(f"{tab_name}: expected {expected_count} rules, found {actual_count}")

    # Check each gradient rule
    for header, direction, min_val, mid_val, max_val in spec["gradient"]:
        col_idx = hmap.get(header)
        if col_idx is None:
            issues.append(f"{tab_name}: header '{header}' not found in row 1")
            continue
        found, detail = _check_gradient(rules, col_idx, direction, min_val, mid_val, max_val)
        if not found:
            issues.append(f"{tab_name}: missing gradient on '{header}' ({detail})")

    # Check boolean rule groups
    for header, expected_bool_count in spec["boolean"]:
        col_idx = hmap.get(header)
        if col_idx is None:
            issues.append(f"{tab_name}: header '{header}' not found in row 1")
            continue
        actual_bool = _count_boolean_rules_on_column(rules, col_idx)
        if actual_bool < expected_bool_count:
            issues.append(
                f"{tab_name}: '{header}' has {actual_bool}/{expected_bool_count} boolean rules"
            )

    # Spot-check data types: gradient rules only work on actual numbers.
    # Sample a few rows and verify numeric columns contain numbers, not text strings.
    text_cols = _spot_check_numeric_types(wb, tab_name, spec, hmap)
    if text_cols:
        issues.append(
            f"{tab_name}: numeric values stored as text in columns: {text_cols} "
            f"(gradients won't render)"
        )

    passed = len(issues) == 0
    return passed, issues


def verify_all_formatting(wb):
    """Verify formatting on all tabs in EXPECTED_RULES. Print PASS/FAIL per tab.

    Returns True if all tabs pass.
    """
    all_passed = True
    print("\n--- Formatting Verification ---")

    for tab_name in EXPECTED_RULES:
        passed, issues = verify_tab_formatting(wb, tab_name)
        if passed:
            print(f"  PASS  {tab_name}: all {EXPECTED_RULES[tab_name]['total_rule_count']} rules intact")
        else:
            all_passed = False
            print(f"  FAIL  {tab_name}:")
            for issue in issues:
                print(f"        - {issue}")

    if all_passed:
        print("  All tabs PASS.\n")
    else:
        print("")

    return all_passed


# ---------------------------------------------------------------------------
# Repair functions
# ---------------------------------------------------------------------------

def _fix_numeric_types_for_tab(wb, tab_name, spec, hmap):
    """Convert text-number strings to actual numbers in graded columns.

    This is the fix for the most common formatting failure: gradient rules exist
    but don't render because cell values are stored as text strings.

    Uses ONE API call to read all data, then batch-writes fixes.
    """
    try:
        sheet = wb.worksheet(tab_name)
    except Exception:
        return 0

    # Collect which column indices need numeric enforcement
    graded_col_indices = set()
    for header, *_ in spec.get("gradient", []):
        col_idx = hmap.get(header)
        if col_idx is not None:
            graded_col_indices.add(col_idx)

    if not graded_col_indices:
        return 0

    # Read ALL data in one API call with UNFORMATTED_VALUE
    try:
        result = sheet.spreadsheet.values_get(
            f"'{tab_name}'!A2:5000",
            params={"valueRenderOption": "UNFORMATTED_VALUE"}
        )
    except Exception:
        return 0

    all_rows = result.get("values", [])
    if not all_rows:
        return 0

    import gspread as _gs
    all_cells_to_fix = []

    for row_offset, row in enumerate(all_rows):
        for col_idx in graded_col_indices:
            if col_idx >= len(row):
                continue
            val = row[col_idx]
            if val == "" or val is None:
                continue
            if isinstance(val, str):
                try:
                    num_val = float(val)
                    all_cells_to_fix.append(
                        _gs.Cell(row=row_offset + 2, col=col_idx + 1, value=num_val)
                    )
                except (ValueError, TypeError):
                    pass

    if all_cells_to_fix:
        # Batch update in chunks of 500 to stay within API limits
        for start in range(0, len(all_cells_to_fix), 500):
            chunk = all_cells_to_fix[start:start + 500]
            sheet.update_cells(chunk, value_input_option="USER_ENTERED")
        print(f"  {tab_name}: fixed {len(all_cells_to_fix)} text-as-number cells")

    return len(all_cells_to_fix)


def repair_tab_formatting(wb, tab_name):
    """Re-apply conditional formatting and fix numeric types for a single tab."""
    spec = EXPECTED_RULES.get(tab_name)
    if spec is None:
        print(f"  No repair spec for '{tab_name}'")
        return

    repair_key = spec["repair_fn"]
    print(f"  Repairing {tab_name}...")

    # Step 1: Fix numeric types (text-as-number -> actual numbers)
    hmap = _get_header_map(wb, tab_name)
    if hmap:
        _fix_numeric_types_for_tab(wb, tab_name, spec, hmap)

    # Step 2: Re-apply conditional format rules
    if repair_key == "sleep":
        from sheets_formatting import apply_sleep_color_grading
        apply_sleep_color_grading(wb)

    elif repair_key == "overall_analysis":
        from setup_overall_analysis import setup_overall_analysis
        setup_overall_analysis(wb)

    elif repair_key == "daily_log":
        from setup_daily_log import setup_daily_log
        setup_daily_log(wb)

    elif repair_key == "session_log":
        from sheets_formatting import apply_session_log_color_grading
        apply_session_log_color_grading(wb)

    else:
        print(f"  Unknown repair function: {repair_key}")


def repair_formatting(wb, tab_name=None):
    """Re-apply formatting for one or all tabs that fail verification."""
    if tab_name:
        repair_tab_formatting(wb, tab_name)
    else:
        for tn in EXPECTED_RULES:
            passed, _ = verify_tab_formatting(wb, tn)
            if not passed:
                repair_tab_formatting(wb, tn)


def verify_and_repair(wb):
    """Run verification. If any tab fails, auto-repair then verify again.

    Returns True if all tabs pass after repair.
    """
    if verify_all_formatting(wb):
        return True

    print("  Auto-repairing failed tabs...")
    repair_formatting(wb)

    # Verify again after repair
    print("\n--- Post-Repair Verification ---")
    result = verify_all_formatting(wb)
    if not result:
        print("  WARNING: Some tabs still failing after repair. Manual investigation needed.")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Verify conditional formatting on Google Sheets tabs")
    parser.add_argument("--tab", type=str, help="Verify a single tab (e.g., --tab Sleep)")
    parser.add_argument("--repair", action="store_true", help="Auto-repair any failures")
    args = parser.parse_args()

    from utils import get_workbook
    wb = get_workbook()

    if args.tab:
        passed, issues = verify_tab_formatting(wb, args.tab)
        if passed:
            spec = EXPECTED_RULES.get(args.tab, {})
            print(f"  PASS  {args.tab}: all {spec.get('total_rule_count', '?')} rules intact")
        else:
            print(f"  FAIL  {args.tab}:")
            for issue in issues:
                print(f"        - {issue}")
            if args.repair:
                repair_tab_formatting(wb, args.tab)
                passed, issues = verify_tab_formatting(wb, args.tab)
                if passed:
                    print(f"  PASS  {args.tab}: repaired successfully")
                else:
                    print(f"  FAIL  {args.tab}: still failing after repair")
                    for issue in issues:
                        print(f"        - {issue}")
    elif args.repair:
        verify_and_repair(wb)
    else:
        verify_all_formatting(wb)


if __name__ == "__main__":
    main()
