"""
check_threshold_sync.py — Verify threshold consistency across all locations.

Reads thresholds from 4 sources and reports any inconsistencies:
  1. thresholds.json (dashboard_metrics, scoring_params, bedtime_bands)
  2. calibrate_thresholds.py (CLINICAL_CLAMPS)
  3. dashboard/dashboard.html & dashboard_template.html (getBedtimeColor hardcoded)
  4. sleep_analysis.py (compute_independent_score default thresholds)

Usage:
  python check_threshold_sync.py          # check all
  python check_threshold_sync.py --fix    # report what needs manual fixing
"""

import json
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
THRESHOLDS_PATH = PROJECT_DIR / "thresholds.json"
CALIBRATE_PATH = PROJECT_DIR / "calibrate_thresholds.py"
DASHBOARD_HTML = PROJECT_DIR / "dashboard" / "dashboard.html"
DASHBOARD_TEMPLATE = PROJECT_DIR / "dashboard" / "dashboard_template.html"
SLEEP_ANALYSIS = PROJECT_DIR / "sleep_analysis.py"

issues = []
warnings = []


def load_thresholds_json():
    """Load and return thresholds.json."""
    with open(THRESHOLDS_PATH) as f:
        return json.load(f)


def check_higher_better_ordering(thresholds):
    """Verify red < yellow < green for higher_better, reversed for lower_better."""
    metrics = thresholds.get("dashboard_metrics", {})
    for key, m in metrics.items():
        mtype = m.get("type", "")
        red = m.get("red")
        yellow = m.get("yellow")
        green = m.get("green")

        if red is None or yellow is None or green is None:
            continue

        # Skip time-based metrics
        if mtype == "time_earlier_better":
            continue

        if mtype == "higher_better":
            if not (red <= yellow <= green):
                issues.append(
                    f"[thresholds.json] {key}: higher_better but "
                    f"red({red}) <= yellow({yellow}) <= green({green}) violated"
                )
        elif mtype == "lower_better":
            if not (green <= yellow <= red):
                issues.append(
                    f"[thresholds.json] {key}: lower_better but "
                    f"green({green}) <= yellow({yellow}) <= red({red}) violated"
                )


def check_scoring_params_vs_sleep_analysis(thresholds):
    """Compare thresholds.json scoring_params with sleep_analysis.py defaults."""
    sp = thresholds.get("scoring_params", {})
    if not SLEEP_ANALYSIS.exists():
        warnings.append("[sleep_analysis.py] File not found, skipping comparison")
        return

    content = SLEEP_ANALYSIS.read_text(encoding="utf-8")

    # Extract default thresholds from compute_independent_score
    defaults_match = re.search(
        r't = thresholds or \{([^}]+)\}', content, re.DOTALL
    )
    if not defaults_match:
        warnings.append("[sleep_analysis.py] Could not parse default thresholds")
        return

    defaults_text = defaults_match.group(1)

    # Parse key-value pairs from the defaults dict
    sa_defaults = {}
    for m in re.finditer(r'"(\w+)":\s*([0-9.]+|"[^"]+")', defaults_text):
        key = m.group(1)
        val = m.group(2).strip('"')
        sa_defaults[key] = val

    # Compare each scoring_param
    for key, sp_val in sp.items():
        if key.startswith("_"):
            continue
        sa_val = sa_defaults.get(key)
        if sa_val is None:
            continue

        # Normalize for comparison
        sp_str = str(sp_val)
        sa_str = str(sa_val)

        # Handle numeric comparison (avoid float string mismatch)
        try:
            if float(sp_str) != float(sa_str):
                issues.append(
                    f"[scoring_params vs sleep_analysis.py] {key}: "
                    f"thresholds.json={sp_str}, sleep_analysis.py default={sa_str}"
                )
        except ValueError:
            if sp_str != sa_str:
                issues.append(
                    f"[scoring_params vs sleep_analysis.py] {key}: "
                    f"thresholds.json={sp_str}, sleep_analysis.py default={sa_str}"
                )


def check_bedtime_bands_vs_dashboard(thresholds):
    """Compare bedtime_bands in thresholds.json with hardcoded dashboard values."""
    bands = thresholds.get("bedtime_bands", {})

    # thresholds.json bedtime bands: green_end=23:00, yellow_end=01:00, red_end=02:00(ish)
    green_end = bands.get("green_end", "23:00")  # 23:00 = 300 min past 6pm
    # Dashboard uses minutes past 6pm: green=300 (11pm), yellow=390 (12:30am), red=480 (2am)

    for html_path in [DASHBOARD_HTML, DASHBOARD_TEMPLATE]:
        if not html_path.exists():
            continue

        content = html_path.read_text(encoding="utf-8")
        match = re.search(
            r'const green\s*=\s*(\d+),\s*yellow\s*=\s*(\d+),\s*red\s*=\s*(\d+)',
            content
        )
        if not match:
            warnings.append(
                f"[{html_path.name}] Could not parse getBedtimeColor thresholds"
            )
            continue

        dash_green = int(match.group(1))   # minutes past 6pm
        dash_yellow = int(match.group(2))
        dash_red = int(match.group(3))

        # Convert thresholds.json times to minutes past 6pm (18:00)
        def time_to_min_past_6pm(t):
            h, m = map(int, t.split(":"))
            mins = h * 60 + m
            if mins < 360:   # before 6am = next day
                mins += 1440
            return mins - 1080  # 6pm = 18:00 = 1080min from midnight

        json_green = time_to_min_past_6pm(green_end)
        json_yellow_start = time_to_min_past_6pm(bands.get("yellow_start", "00:00"))
        json_red_start = time_to_min_past_6pm(bands.get("red_start", "02:00"))

        if dash_green != json_green:
            issues.append(
                f"[{html_path.name}] getBedtimeColor green={dash_green} "
                f"but thresholds.json green_end={green_end} ({json_green} min)"
            )
        # Dashboard yellow is the start of the yellow->red transition
        # thresholds.json yellow_start is when yellow begins
        # These may use different semantics — warn if significantly different
        if abs(dash_yellow - json_yellow_start) > 30:
            warnings.append(
                f"[{html_path.name}] getBedtimeColor yellow={dash_yellow} vs "
                f"thresholds.json yellow_start={json_yellow_start} min "
                f"(>30 min gap, may be intentional gradient vs discrete)"
            )
        if abs(dash_red - json_red_start) > 30:
            warnings.append(
                f"[{html_path.name}] getBedtimeColor red={dash_red} vs "
                f"thresholds.json red_start={json_red_start} min "
                f"(>30 min gap)"
            )


def check_clinical_clamps(thresholds):
    """Compare CLINICAL_CLAMPS in calibrate_thresholds.py with thresholds.json."""
    if not CALIBRATE_PATH.exists():
        warnings.append("[calibrate_thresholds.py] File not found, skipping")
        return

    content = CALIBRATE_PATH.read_text(encoding="utf-8")

    # Extract CLINICAL_CLAMPS dict
    clamp_match = re.search(
        r'CLINICAL_CLAMPS\s*=\s*\{(.+?)\n\}', content, re.DOTALL
    )
    if not clamp_match:
        warnings.append("[calibrate_thresholds.py] Could not parse CLINICAL_CLAMPS")
        return

    clamp_text = clamp_match.group(1)
    metrics = thresholds.get("dashboard_metrics", {})

    # Parse each metric's clamps
    for m in re.finditer(
        r'"(\w+)":\s*\{([^}]+)\}', clamp_text
    ):
        metric_key = m.group(1)
        clamp_body = m.group(2)

        clamps = {}
        for c in re.finditer(r'"(\w+)":\s*([0-9.]+)', clamp_body):
            clamps[c.group(1)] = float(c.group(2))

        # Find corresponding dashboard metric
        dash_key = metric_key
        if dash_key not in metrics:
            # Try common mappings
            mappings = {
                "overnight_hrv": "overnight_hrv_ms",
                "sleep_duration": "total_sleep_hrs",
                "avg_stress": "avg_stress_level",
            }
            dash_key = mappings.get(metric_key, metric_key)

        if dash_key not in metrics:
            continue

        dm = metrics[dash_key]

        # Check green_min: dashboard green should not be below clinical floor
        green_min = clamps.get("green_min")
        if green_min is not None and dm.get("green") is not None:
            if isinstance(dm["green"], (int, float)) and dm["green"] < green_min:
                issues.append(
                    f"[clinical clamp] {metric_key}: dashboard green={dm['green']} "
                    f"< clinical green_min={green_min}"
                )

        # Check green_max: for lower_better, green should not exceed clinical max
        green_max = clamps.get("green_max")
        if green_max is not None and dm.get("green") is not None:
            if isinstance(dm["green"], (int, float)) and dm["green"] > green_max:
                issues.append(
                    f"[clinical clamp] {metric_key}: dashboard green={dm['green']} "
                    f"> clinical green_max={green_max}"
                )


def check_sheets_vs_dashboard(thresholds):
    """Compare sheets_formatting thresholds with dashboard_metrics."""
    sheets = thresholds.get("sheets_formatting", {})
    metrics = thresholds.get("dashboard_metrics", {})

    # Build a lookup from Sheets gradient headers to their thresholds
    sheet_lookup = {}
    for tab_name, tab_cfg in sheets.items():
        for grad in tab_cfg.get("gradient", []):
            header = grad["header"]
            sheet_lookup[header] = {
                "min": grad["min"], "mid": grad.get("mid"), "max": grad["max"],
                "direction": grad["direction"], "tab": tab_name
            }

    # Map dashboard metric keys to Sheets headers
    dash_to_sheet = {
        "sleep_analysis_score": "Sleep Analysis Score",
        "total_sleep_hrs": "Total Sleep (hrs)",
        "overnight_hrv_ms": "Overnight HRV (ms)",
        "deep_pct": "Deep %",
        "rem_pct": "REM %",
        "body_battery_gained": "Body Battery Gained",
        "bedtime_variability_7d": "Bedtime Variability (7d)",
        "wake_variability_7d": "Wake Variability (7d)",
    }

    for dash_key, sheet_header in dash_to_sheet.items():
        dm = metrics.get(dash_key)
        sg = sheet_lookup.get(sheet_header)

        if dm is None or sg is None:
            continue

        # For higher_better: dashboard red=min, yellow=mid, green=max
        # For lower_better: dashboard green=min, yellow=mid, red=max
        if dm.get("type") == "higher_better":
            if dm.get("red") != sg["min"]:
                issues.append(
                    f"[sheets vs dashboard] {dash_key}: dashboard red={dm['red']} "
                    f"!= sheets min={sg['min']} ({sheet_header})"
                )
            if sg["mid"] is not None and dm.get("yellow") != sg["mid"]:
                issues.append(
                    f"[sheets vs dashboard] {dash_key}: dashboard yellow={dm['yellow']} "
                    f"!= sheets mid={sg['mid']} ({sheet_header})"
                )
            if dm.get("green") != sg["max"]:
                issues.append(
                    f"[sheets vs dashboard] {dash_key}: dashboard green={dm['green']} "
                    f"!= sheets max={sg['max']} ({sheet_header})"
                )
        elif dm.get("type") == "lower_better":
            if dm.get("green") != sg["min"]:
                issues.append(
                    f"[sheets vs dashboard] {dash_key}: dashboard green={dm['green']} "
                    f"!= sheets min={sg['min']} ({sheet_header})"
                )
            if sg["mid"] is not None and dm.get("yellow") != sg["mid"]:
                issues.append(
                    f"[sheets vs dashboard] {dash_key}: dashboard yellow={dm['yellow']} "
                    f"!= sheets mid={sg['mid']} ({sheet_header})"
                )
            if dm.get("red") != sg["max"]:
                issues.append(
                    f"[sheets vs dashboard] {dash_key}: dashboard red={dm['red']} "
                    f"!= sheets max={sg['max']} ({sheet_header})"
                )


def main():
    print("=" * 60)
    print("Threshold Sync Check")
    print("=" * 60)

    thresholds = load_thresholds_json()

    print("\n[1/5] Checking threshold ordering (red/yellow/green)...")
    check_higher_better_ordering(thresholds)

    print("[2/5] Checking scoring_params vs sleep_analysis.py defaults...")
    check_scoring_params_vs_sleep_analysis(thresholds)

    print("[3/5] Checking bedtime bands vs dashboard hardcoded values...")
    check_bedtime_bands_vs_dashboard(thresholds)

    print("[4/5] Checking clinical clamps vs dashboard thresholds...")
    check_clinical_clamps(thresholds)

    print("[5/5] Checking Sheets formatting vs dashboard thresholds...")
    check_sheets_vs_dashboard(thresholds)

    print()
    if issues:
        print(f"ISSUES FOUND: {len(issues)}")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("No threshold inconsistencies found.")

    if warnings:
        print(f"\nWARNINGS: {len(warnings)}")
        for i, w in enumerate(warnings, 1):
            print(f"  {i}. {w}")

    print()
    if issues:
        print("FAIL")
        return 1
    else:
        print("PASS")
        return 0


if __name__ == "__main__":
    sys.exit(main())
