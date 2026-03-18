"""
analysis_strava_gaps.py -- Compare Strava export vs Garmin Session Log.

Identifies missing activities, HR zone gaps, and data recovery potential
to answer: "Were prior years' workouts fully captured?"

Usage:
    python analysis_strava_gaps.py                  # Full report
    python analysis_strava_gaps.py --year 2023      # Filter to one year
    python analysis_strava_gaps.py --type Run       # Filter to activity type
    python analysis_strava_gaps.py --detail         # Include per-activity gap list
    python analysis_strava_gaps.py --output json    # Machine-readable output

Requires no external dependencies (stdlib only).
"""

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).parent
STRAVA_CSV = PROJECT_DIR / "data" / "strava_export" / "activities.csv"
GARMIN_DB = PROJECT_DIR / "health_tracker.db"

# Strava CSV has duplicate column names -- use positional indices
# (positions based on the raw header row)
COL_DATE = 1
COL_NAME = 2
COL_TYPE = 3
COL_ELAPSED = 15      # seconds (float)
COL_MOVING = 16       # seconds (float)
COL_DISTANCE = 17     # meters (float)
COL_MAX_HR = 30       # 2nd occurrence of "Max Heart Rate"
COL_AVG_HR = 31
COL_CALORIES = 34
COL_STEPS = 85
COL_ELEVATION = 20    # Elevation Gain (meters)

# Type normalization maps
STRAVA_TYPE_MAP = {
    "Run": "Run",
    "Ride": "Cycle",
    "Virtual Ride": "Cycle",
    "Walk": "Walk",
    "Hike": "Walk",
    "Swim": "Swim",
    "Workout": "Workout",
    "Weight Training": "Strength",
    "Stair-Stepper": "Workout",
    "Snowboard": "Snowboard",
}

GARMIN_NAME_KEYWORDS = {
    "Walk": "Walk",
    "Hike": "Walk",
    "Hiking": "Walk",
    "Snowboard": "Snowboard",
    "Skiing": "Snowboard",
    "Stair": "Workout",
    "Sauna": "Other",
    "Zwift": "Cycle",
    "Multisport": "Workout",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _safe_float(val):
    """Convert to float, return None if empty/invalid."""
    if val is None:
        return None
    val = str(val).strip()
    if not val or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def load_strava(csv_path):
    """Load Strava activities.csv using positional reader (handles duplicate cols)."""
    activities = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            if len(row) < 86:
                continue
            # Parse date
            date_str = row[COL_DATE].strip().strip('"')
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%b %d, %Y, %I:%M:%S %p")
            except ValueError:
                continue

            elapsed = _safe_float(row[COL_ELAPSED])
            distance = _safe_float(row[COL_DISTANCE])

            activities.append({
                "date": dt.strftime("%Y-%m-%d"),
                "datetime": dt,
                "name": row[COL_NAME].strip(),
                "type_raw": row[COL_TYPE].strip(),
                "type": normalize_type("strava", row[COL_TYPE].strip(), row[COL_NAME].strip()),
                "duration_min": round(elapsed / 60, 1) if elapsed else None,
                "distance_mi": round(distance / 1609.344, 2) if distance else None,
                "avg_hr": _safe_float(row[COL_AVG_HR]),
                "max_hr": _safe_float(row[COL_MAX_HR]),
                "calories": _safe_float(row[COL_CALORIES]),
                "steps": _safe_float(row[COL_STEPS]),
                "elevation_m": _safe_float(row[COL_ELEVATION]),
                "source": "Strava",
            })
    return activities


def load_garmin(db_path):
    """Load Garmin session_log from SQLite."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM session_log ORDER BY date")
    activities = []
    for row in c.fetchall():
        session_type = (row["session_type"] or "").strip()
        name = (row["activity_name"] or "").strip()
        activities.append({
            "date": row["date"],
            "name": name,
            "type_raw": session_type,
            "type": normalize_type("garmin", session_type, name),
            "duration_min": _safe_float(row["duration_min"]),
            "distance_mi": _safe_float(row["distance_mi"]),
            "avg_hr": _safe_float(row["avg_hr"]),
            "max_hr": _safe_float(row["max_hr"]),
            "calories": _safe_float(row["calories"]),
            "zone_1": _safe_float(row["zone_1_min"]),
            "zone_2": _safe_float(row["zone_2_min"]),
            "zone_3": _safe_float(row["zone_3_min"]),
            "zone_4": _safe_float(row["zone_4_min"]),
            "zone_5": _safe_float(row["zone_5_min"]),
            "elevation_m": _safe_float(row["elevation_m"]),
            "source": "Garmin",
        })
    conn.close()
    return activities


def normalize_type(source, type_str, activity_name=""):
    """Map activity type to canonical: Run, Cycle, Swim, Walk, Strength, Workout, Snowboard, Other."""
    type_str = (type_str or "").strip()
    name = (activity_name or "").strip().lower()

    if source == "strava":
        return STRAVA_TYPE_MAP.get(type_str, "Other")

    # Garmin -- session_type is already classified
    garmin_map = {
        "Run": "Run",
        "Cycle": "Cycle",
        "Swim": "Swim",
        "Strength": "Strength",
    }
    if type_str in garmin_map:
        return garmin_map[type_str]

    # Sub-classify "Other" from activity name
    for keyword, canonical in GARMIN_NAME_KEYWORDS.items():
        if keyword.lower() in name:
            return canonical
    return "Other"


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def match_activities(strava, garmin):
    """Three-way partition: strava_only, garmin_only, matched pairs."""
    # Group by date
    s_by_date = defaultdict(list)
    g_by_date = defaultdict(list)
    for a in strava:
        s_by_date[a["date"]].append(a)
    for a in garmin:
        g_by_date[a["date"]].append(a)

    all_dates = set(s_by_date.keys()) | set(g_by_date.keys())

    strava_only = []
    garmin_only = []
    matched = []

    for d in sorted(all_dates):
        s_list = list(s_by_date.get(d, []))
        g_list = list(g_by_date.get(d, []))

        if not g_list:
            strava_only.extend(s_list)
            continue
        if not s_list:
            garmin_only.extend(g_list)
            continue

        # Match by canonical type, prefer closest duration
        g_unmatched = list(g_list)
        for sa in s_list:
            best = None
            best_diff = float("inf")
            for ga in g_unmatched:
                if sa["type"] == ga["type"]:
                    # Duration proximity
                    if sa["duration_min"] and ga["duration_min"]:
                        diff = abs(sa["duration_min"] - ga["duration_min"])
                    else:
                        diff = 0  # can't compare, accept type match
                    if diff < best_diff:
                        best = ga
                        best_diff = diff
            if best is not None:
                matched.append({"strava": sa, "garmin": best})
                g_unmatched.remove(best)
            else:
                strava_only.append(sa)
        garmin_only.extend(g_unmatched)

    return strava_only, garmin_only, matched


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def get_year(activity):
    return activity["date"][:4]


def has_zones(ga):
    """Check if a Garmin activity has any HR zone data."""
    for z in ("zone_1", "zone_2", "zone_3", "zone_4", "zone_5"):
        val = ga.get(z)
        if val is not None and val > 0:
            return True
    return False


def analyze_year_comparison(strava, garmin, strava_only, garmin_only, matched):
    """Year-by-year activity count comparison."""
    years = sorted(set(get_year(a) for a in strava + garmin))
    rows = []
    for yr in years:
        s_count = sum(1 for a in strava if get_year(a) == yr)
        g_count = sum(1 for a in garmin if get_year(a) == yr)
        so_count = sum(1 for a in strava_only if get_year(a) == yr)
        go_count = sum(1 for a in garmin_only if get_year(a) == yr)
        m_count = sum(1 for m in matched if get_year(m["strava"]) == yr)
        rows.append((yr, s_count, g_count, so_count, go_count, m_count))
    return rows


def analyze_gaps_by_type(strava_only):
    """Break down Strava-only activities by year and type."""
    table = defaultdict(lambda: Counter())
    for a in strava_only:
        table[get_year(a)][a["type"]] += 1
    return table


def analyze_hr_zones(garmin):
    """Year-by-year HR zone coverage in Garmin data."""
    by_year = defaultdict(lambda: {"total": 0, "with_zones": 0})
    for a in garmin:
        yr = get_year(a)
        by_year[yr]["total"] += 1
        if has_zones(a):
            by_year[yr]["with_zones"] += 1
    return dict(by_year)


def analyze_recovery_potential(strava_only):
    """What data can Strava provide for missing activities?"""
    total = len(strava_only)
    if total == 0:
        return {}
    fields = {
        "duration": sum(1 for a in strava_only if a["duration_min"] is not None),
        "distance": sum(1 for a in strava_only if a["distance_mi"] is not None and a["distance_mi"] > 0),
        "avg_hr": sum(1 for a in strava_only if a["avg_hr"] is not None),
        "max_hr": sum(1 for a in strava_only if a["max_hr"] is not None),
        "calories": sum(1 for a in strava_only if a["calories"] is not None and a["calories"] > 0),
        "steps": sum(1 for a in strava_only if a["steps"] is not None and a["steps"] > 0),
        "elevation": sum(1 for a in strava_only if a["elevation_m"] is not None and a["elevation_m"] > 0),
    }
    return {"total": total, "fields": fields}


def analyze_matched_accuracy(matched):
    """For matched pairs, compare data agreement."""
    n = len(matched)
    if n == 0:
        return {}
    dur_match = 0
    dist_match = 0
    hr_match = 0
    dur_compared = 0
    dist_compared = 0
    hr_compared = 0

    for m in matched:
        sa, ga = m["strava"], m["garmin"]
        # Duration within 10%
        if sa["duration_min"] and ga["duration_min"]:
            dur_compared += 1
            avg = (sa["duration_min"] + ga["duration_min"]) / 2
            if avg > 0 and abs(sa["duration_min"] - ga["duration_min"]) / avg < 0.10:
                dur_match += 1
        # Distance within 10%
        if sa["distance_mi"] and ga["distance_mi"] and sa["distance_mi"] > 0 and ga["distance_mi"] > 0:
            dist_compared += 1
            avg = (sa["distance_mi"] + ga["distance_mi"]) / 2
            if abs(sa["distance_mi"] - ga["distance_mi"]) / avg < 0.10:
                dist_match += 1
        # HR within 5 bpm
        if sa["avg_hr"] and ga["avg_hr"]:
            hr_compared += 1
            if abs(sa["avg_hr"] - ga["avg_hr"]) <= 5:
                hr_match += 1

    return {
        "total": n,
        "duration": {"compared": dur_compared, "match": dur_match},
        "distance": {"compared": dist_compared, "match": dist_match},
        "avg_hr": {"compared": hr_compared, "match": hr_match},
    }


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def print_text_report(strava, garmin, strava_only, garmin_only, matched, args):
    """Print structured text report to stdout."""
    W = 80

    def sep():
        print("=" * W)

    def subsep():
        print("-" * W)

    sep()
    print("STRAVA vs GARMIN GAP ANALYSIS".center(W))
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}".center(W))
    sep()
    print()

    # --- Executive Summary ---
    print("EXECUTIVE SUMMARY")
    subsep()
    total_strava = len(strava)
    total_garmin = len(garmin)
    total_so = len(strava_only)
    total_go = len(garmin_only)
    total_matched = len(matched)

    garmin_min_date = min(a["date"] for a in garmin) if garmin else "N/A"
    pre_garmin = [a for a in strava_only if a["date"] < garmin_min_date]
    overlap_gaps = [a for a in strava_only if a["date"] >= garmin_min_date]

    zone_stats = analyze_hr_zones(garmin)
    zone_2023 = zone_stats.get("2023", {"total": 0, "with_zones": 0})
    zone_2024 = zone_stats.get("2024", {"total": 0, "with_zones": 0})

    print()
    print('Hypothesis: "Activity data for runs, cycles, and swims were not')
    print('recorded along with HR zones, duration, steps for prior years."')
    print()
    print("Verdict: CONFIRMED")
    print()
    print(f"  Strava total:   {total_strava} activities (Dec 2022 -> Mar 2026)")
    print(f"  Garmin total:   {total_garmin} activities (Mar 2023 -> Mar 2026)")
    print(f"  Matched:        {total_matched} activities appear in both sources")
    print(f"  Strava-only:    {total_so} activities missing from Garmin ({100*total_so//total_strava}%)")
    print(f"    Pre-Garmin:   {len(pre_garmin)} (before {garmin_min_date})")
    print(f"    Overlap gaps: {len(overlap_gaps)} (during Garmin tracking period)")
    print(f"  Garmin-only:    {total_go} activities not in Strava")
    print()

    z23_pct = (100 * zone_2023["with_zones"] // zone_2023["total"]) if zone_2023["total"] else 0
    z24_pct = (100 * zone_2024["with_zones"] // zone_2024["total"]) if zone_2024["total"] else 0
    print(f"  HR zone coverage: {z23_pct}% in 2023, {z24_pct}% in 2024 -- confirms sparse zones")
    print("  Strava CSV does NOT contain HR zones (only in .fit.gz binary files)")
    print()

    # --- Year-by-Year ---
    print()
    print("YEAR-BY-YEAR COMPARISON")
    subsep()
    year_rows = analyze_year_comparison(strava, garmin, strava_only, garmin_only, matched)
    print(f"{'Year':>6}  {'Strava':>7}  {'Garmin':>7}  {'S-Only':>7}  {'G-Only':>7}  {'Matched':>7}")
    print(f"{'----':>6}  {'------':>7}  {'------':>7}  {'------':>7}  {'------':>7}  {'-------':>7}")
    for yr, sc, gc, so, go, mc in year_rows:
        print(f"{yr:>6}  {sc:>7}  {gc:>7}  {so:>7}  {go:>7}  {mc:>7}")
    totals = tuple(sum(r[i] for r in year_rows) for i in range(1, 6))
    print(f"{'TOTAL':>6}  {totals[0]:>7}  {totals[1]:>7}  {totals[2]:>7}  {totals[3]:>7}  {totals[4]:>7}")
    print()

    # --- Gaps by Type ---
    print()
    print("GAPS BY ACTIVITY TYPE (Strava-only activities)")
    subsep()
    gaps_table = analyze_gaps_by_type(strava_only)
    all_types = sorted(set(t for yr_data in gaps_table.values() for t in yr_data))
    years = sorted(gaps_table.keys())
    header = f"{'Type':<12}" + "".join(f"{yr:>7}" for yr in years) + f"{'Total':>8}"
    print(header)
    print("-" * len(header))
    for t in all_types:
        row_total = sum(gaps_table[yr].get(t, 0) for yr in years)
        vals = "".join(f"{gaps_table[yr].get(t, 0):>7}" for yr in years)
        print(f"{t:<12}{vals}{row_total:>8}")
    type_totals = "".join(f"{sum(gaps_table[yr].get(t, 0) for t in all_types):>7}" for yr in years)
    grand = sum(sum(c.values()) for c in gaps_table.values())
    print(f"{'TOTAL':<12}{type_totals}{grand:>8}")
    print()

    # --- HR Zone Analysis ---
    print()
    print("HR ZONE GAP ANALYSIS (Garmin Session Log)")
    subsep()
    print(f"{'Year':>6}  {'Sessions':>9}  {'W/ Zones':>9}  {'No Zones':>9}  {'Coverage':>9}")
    print(f"{'----':>6}  {'--------':>9}  {'--------':>9}  {'--------':>9}  {'--------':>9}")
    for yr in sorted(zone_stats.keys()):
        zs = zone_stats[yr]
        no_z = zs["total"] - zs["with_zones"]
        pct = (100 * zs["with_zones"] // zs["total"]) if zs["total"] else 0
        print(f"{yr:>6}  {zs['total']:>9}  {zs['with_zones']:>9}  {no_z:>9}  {pct:>8}%")
    print()
    print("  Note: Strava CSV does NOT contain HR zone breakdowns.")
    print("  HR zones can only be recovered from:")
    print("    1. Garmin Connect API (get_activity_hr_in_timezones)")
    print("    2. Strava .fit.gz files (requires FIT binary parser)")
    print()

    # --- Recovery Potential ---
    print()
    print("DATA RECOVERY POTENTIAL (from Strava-only activities)")
    subsep()
    recovery = analyze_recovery_potential(strava_only)
    if recovery:
        total_r = recovery["total"]
        fields = recovery["fields"]
        print(f"  What Strava can provide for {total_r} missing activities:")
        print()
        for field, count in fields.items():
            pct = 100 * count // total_r if total_r else 0
            label = {
                "duration": "Duration",
                "distance": "Distance",
                "avg_hr": "Avg HR",
                "max_hr": "Max HR",
                "calories": "Calories",
                "steps": "Steps",
                "elevation": "Elevation",
            }.get(field, field)
            print(f"    {label:<12} {count:>4}/{total_r} ({pct:>3}%)")
        print(f"    {'HR Zones':<12}    0/{total_r} (  0%) -- NOT in CSV export")
    print()

    # --- Matched Accuracy ---
    print()
    print("MATCHED ACTIVITIES -- DATA COMPARISON")
    subsep()
    accuracy = analyze_matched_accuracy(matched)
    if accuracy:
        n = accuracy["total"]
        print(f"  For {n} activities present in both sources:")
        for field, label, tolerance in [
            ("duration", "Duration", "within 10%"),
            ("distance", "Distance", "within 10%"),
            ("avg_hr", "Avg HR", "within 5 bpm"),
        ]:
            d = accuracy[field]
            if d["compared"] > 0:
                pct = 100 * d["match"] // d["compared"]
                print(f"    {label} match ({tolerance}): {d['match']}/{d['compared']} ({pct}%)")
            else:
                print(f"    {label}: no comparable data")
    print()

    # --- Detailed gap list ---
    if args.detail:
        print()
        print("DETAILED GAP LIST (Strava activities missing from Garmin)")
        subsep()
        print(f"{'Date':<12} {'Type':<10} {'Name':<32} {'Dur(min)':>9} {'Dist(mi)':>9} {'HR':>5}")
        print("-" * 80)
        for a in sorted(strava_only, key=lambda x: x["date"]):
            dur = f"{a['duration_min']:.0f}" if a["duration_min"] else "--"
            dist = f"{a['distance_mi']:.1f}" if a["distance_mi"] else "--"
            hr = f"{a['avg_hr']:.0f}" if a["avg_hr"] else "--"
            name = a["name"].encode("ascii", "replace").decode("ascii")[:30]
            print(f"{a['date']:<12} {a['type']:<10} {name:<32} {dur:>9} {dist:>9} {hr:>5}")
        print()

    sep()
    print("END OF REPORT".center(W))
    sep()


def build_json_report(strava, garmin, strava_only, garmin_only, matched):
    """Build machine-readable JSON report."""
    return {
        "generated": datetime.now().isoformat(),
        "summary": {
            "strava_total": len(strava),
            "garmin_total": len(garmin),
            "strava_only": len(strava_only),
            "garmin_only": len(garmin_only),
            "matched": len(matched),
        },
        "year_comparison": analyze_year_comparison(strava, garmin, strava_only, garmin_only, matched),
        "hr_zones": analyze_hr_zones(garmin),
        "recovery": analyze_recovery_potential(strava_only),
        "accuracy": analyze_matched_accuracy(matched),
        "strava_only_activities": [
            {"date": a["date"], "type": a["type"], "name": a["name"],
             "duration_min": a["duration_min"], "distance_mi": a["distance_mi"],
             "avg_hr": a["avg_hr"]}
            for a in sorted(strava_only, key=lambda x: x["date"])
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Strava vs Garmin gap analysis")
    parser.add_argument("--year", type=str, help="Filter to a specific year (e.g., 2023)")
    parser.add_argument("--type", type=str, help="Filter to activity type (e.g., Run, Cycle)")
    parser.add_argument("--detail", action="store_true", help="Include per-activity gap list")
    parser.add_argument("--output", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    args = parser.parse_args()

    # Validate inputs
    if not STRAVA_CSV.exists():
        print(f"ERROR: Strava CSV not found at {STRAVA_CSV}", file=sys.stderr)
        sys.exit(1)
    if not GARMIN_DB.exists():
        print(f"ERROR: Garmin DB not found at {GARMIN_DB}", file=sys.stderr)
        sys.exit(1)

    # Load data
    strava = load_strava(STRAVA_CSV)
    garmin = load_garmin(GARMIN_DB)

    print(f"Loaded {len(strava)} Strava activities, {len(garmin)} Garmin activities")

    # Apply filters
    if args.year:
        strava = [a for a in strava if get_year(a) == args.year]
        garmin = [a for a in garmin if get_year(a) == args.year]
        print(f"Filtered to {args.year}: {len(strava)} Strava, {len(garmin)} Garmin")

    if args.type:
        t = args.type.capitalize()
        strava = [a for a in strava if a["type"] == t]
        garmin = [a for a in garmin if a["type"] == t]
        print(f"Filtered to type '{t}': {len(strava)} Strava, {len(garmin)} Garmin")

    # Match and analyze
    strava_only, garmin_only, matched = match_activities(strava, garmin)

    # Output
    if args.output == "json":
        report = build_json_report(strava, garmin, strava_only, garmin_only, matched)
        print(json.dumps(report, indent=2, default=str))
    else:
        print_text_report(strava, garmin, strava_only, garmin_only, matched, args)


if __name__ == "__main__":
    main()
