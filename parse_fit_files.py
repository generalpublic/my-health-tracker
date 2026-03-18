"""
parse_fit_files.py -- Parse Strava .fit.gz export files for activity data + HR zones.

Extracts session metrics and computes HR zone time from per-second heart rate
telemetry in FIT binary files. Optionally imports missing activities into the
Session Log (Google Sheets + SQLite).

Usage:
    python parse_fit_files.py                     # Report mode (default)
    python parse_fit_files.py --do-import         # Write missing activities to Session Log
    python parse_fit_files.py --dry-run           # Show what would be imported
    python parse_fit_files.py --year 2023         # Filter to specific year
    python parse_fit_files.py --type Run          # Filter to activity type
    python parse_fit_files.py --max-hr 194        # Override max HR for zone calc

Requires: fitparse (pip install fitparse)
"""

import argparse
import csv
import gzip
import sqlite3
import sys
import time as _time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import fitparse

from utils import get_workbook, date_to_day, _safe_float
from sqlite_backup import upsert_session_log_row

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).parent
STRAVA_CSV = PROJECT_DIR / "data" / "strava_export" / "activities.csv"
FIT_DIR = PROJECT_DIR / "data" / "strava_export"

# Strava CSV column indices (0-based, positional due to duplicate headers)
COL_ID = 0
COL_DATE = 1
COL_NAME = 2
COL_TYPE = 3
COL_FILENAME = 12
COL_ELAPSED = 15       # seconds (float, 2nd occurrence)
COL_DISTANCE = 17      # meters (2nd occurrence)
COL_AVG_HR = 31
COL_MAX_HR = 30        # 2nd occurrence
COL_CALORIES = 34

# Default HR zone boundaries (percentage of max HR)
# Tuned to match user's actual Garmin zones within 1 bpm
DEFAULT_MAX_HR = 194
ZONE_PCT = [
    (0.66, 0.80),   # Z1: 128-155
    (0.81, 0.90),   # Z2: 157-174
    (0.91, 0.97),   # Z3: 177-188
    (0.98, 0.995),  # Z4: 190-192
    (1.00, 1.10),   # Z5: 194+
]

# Strava activity type -> Session Log type
STRAVA_TYPE_MAP = {
    "Run": "Run",
    "Ride": "Cycle",
    "Virtual Ride": "Cycle",
    "Walk": "Other",
    "Hike": "Other",
    "Swim": "Swim",
    "Workout": "Other",
    "Weight Training": "Strength",
    "Stair-Stepper": "Other",
    "Snowboard": "Other",
}

# FIT sport field -> Session Log type
FIT_SPORT_MAP = {
    "running": "Run",
    "cycling": "Cycle",
    "swimming": "Swim",
    "training": "Strength",
}


# ---------------------------------------------------------------------------
# HR Zone Computation
# ---------------------------------------------------------------------------

def compute_zone_boundaries(max_hr):
    """Compute HR zone boundaries from max HR and percentage thresholds.

    Returns list of 5 (low, high) tuples in bpm.
    """
    boundaries = []
    for i, (lo_pct, hi_pct) in enumerate(ZONE_PCT):
        lo = int(max_hr * lo_pct)
        if i < len(ZONE_PCT) - 1:
            hi = int(max_hr * ZONE_PCT[i + 1][0]) - 1
        else:
            hi = max_hr + 20  # Z5 has no upper bound
        boundaries.append((lo, hi))
    return boundaries


def compute_hr_zones(hr_samples, max_hr):
    """Compute time-in-zone (minutes) from per-second HR samples.

    Returns dict with zone_1..zone_5 (float minutes) and zone_ranges (str).
    """
    boundaries = compute_zone_boundaries(max_hr)
    zone_seconds = [0] * 5

    for hr in hr_samples:
        if hr is None or hr <= 0:
            continue
        for i, (lo, hi) in enumerate(boundaries):
            if lo <= hr <= hi:
                zone_seconds[i] += 1
                break
        else:
            # Above Z5 upper bound (very rare)
            if hr > boundaries[-1][0]:
                zone_seconds[4] += 1

    result = {}
    for i in range(5):
        result[f"zone_{i+1}"] = round(zone_seconds[i] / 60, 1)

    # Build zone_ranges string matching Garmin format
    parts = []
    for i, (lo, _) in enumerate(boundaries):
        if i < 4:
            next_lo = boundaries[i + 1][0]
            parts.append(f"Z{i+1}:{lo}-{next_lo - 1}")
        else:
            parts.append(f"Z{i+1}:{lo}+")
    result["zone_ranges"] = ", ".join(parts)

    return result


# ---------------------------------------------------------------------------
# Strava CSV Index
# ---------------------------------------------------------------------------

def load_strava_index(csv_path):
    """Load activities.csv and build activity-to-FIT-file mapping."""
    activities = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) <= COL_FILENAME:
                continue
            date_str = row[COL_DATE].strip().strip('"')
            filename = row[COL_FILENAME].strip()
            if not date_str or not filename or not filename.endswith(".fit.gz"):
                continue
            try:
                dt = datetime.strptime(date_str, "%b %d, %Y, %I:%M:%S %p")
            except ValueError:
                continue

            strava_type = row[COL_TYPE].strip()
            activities.append({
                "id": row[COL_ID].strip(),
                "date": dt.strftime("%Y-%m-%d"),
                "datetime": dt,
                "name": row[COL_NAME].strip(),
                "type_raw": strava_type,
                "session_type": STRAVA_TYPE_MAP.get(strava_type, "Other"),
                "fit_file": filename,
                # CSV fallback metrics (used if FIT parse fails)
                "csv_elapsed": _safe_float(row[COL_ELAPSED]) if len(row) > COL_ELAPSED else None,
                "csv_distance": _safe_float(row[COL_DISTANCE]) if len(row) > COL_DISTANCE else None,
                "csv_avg_hr": _safe_float(row[COL_AVG_HR]) if len(row) > COL_AVG_HR else None,
                "csv_max_hr": _safe_float(row[COL_MAX_HR]) if len(row) > COL_MAX_HR else None,
                "csv_calories": _safe_float(row[COL_CALORIES]) if len(row) > COL_CALORIES else None,
            })
    return activities


# ---------------------------------------------------------------------------
# FIT File Parser
# ---------------------------------------------------------------------------

def parse_fit_file(fit_path, max_hr):
    """Parse a single .fit.gz file. Returns dict of metrics or None on failure."""
    try:
        with gzip.open(fit_path, "rb") as gz:
            raw = gz.read()
        fit = fitparse.FitFile(raw, check_crc=False)
    except Exception as e:
        print(f"  WARN: Failed to open {fit_path.name}: {e}", file=sys.stderr)
        return None

    result = {}

    # Extract session message
    try:
        for msg in fit.get_messages("session"):
            fields = {f.name: f.value for f in msg.fields}
            result["sport"] = fields.get("sport", "")
            result["total_timer_time"] = fields.get("total_timer_time")
            result["total_elapsed_time"] = fields.get("total_elapsed_time")
            result["total_distance"] = fields.get("total_distance")
            result["avg_heart_rate"] = fields.get("avg_heart_rate")
            result["max_heart_rate"] = fields.get("max_heart_rate")
            result["total_calories"] = fields.get("total_calories")
            result["total_ascent"] = fields.get("total_ascent")
            result["total_training_effect"] = fields.get("total_training_effect")
            result["total_anaerobic_training_effect"] = fields.get(
                "total_anaerobic_training_effect"
            )
            break  # Use first session message
    except Exception as e:
        if "dev_data_index" not in str(e):
            print(f"  WARN: Session parse failed for {fit_path.name}: {e}", file=sys.stderr)

    # Collect per-second HR samples
    hr_samples = []
    try:
        for msg in fit.get_messages("record"):
            for field in msg.fields:
                if field.name == "heart_rate" and field.value is not None:
                    hr_samples.append(int(field.value))
                    break
    except Exception as e:
        if "dev_data_index" not in str(e):
            print(f"  WARN: Record parse failed for {fit_path.name}: {e}", file=sys.stderr)

    result["hr_sample_count"] = len(hr_samples)

    # Compute avg/max HR from samples if session message didn't have them
    if hr_samples:
        if not result.get("avg_heart_rate"):
            result["avg_heart_rate"] = round(sum(hr_samples) / len(hr_samples))
        if not result.get("max_heart_rate"):
            result["max_heart_rate"] = max(hr_samples)

    # Compute zones from HR samples
    if hr_samples:
        zones = compute_hr_zones(hr_samples, max_hr)
        result.update(zones)
    else:
        for i in range(1, 6):
            result[f"zone_{i}"] = 0
        result["zone_ranges"] = ""

    return result


def parse_all_fit_files(strava_index, max_hr):
    """Parse all FIT files. Returns enriched activity list."""
    total = len(strava_index)
    parsed = 0
    failed = 0
    missing = 0

    start = _time.time()
    for i, activity in enumerate(strava_index):
        fit_path = FIT_DIR / activity["fit_file"]
        if not fit_path.exists():
            activity["has_fit"] = False
            activity["fit_data"] = None
            missing += 1
            continue

        fit_data = parse_fit_file(fit_path, max_hr)
        if fit_data is None:
            activity["has_fit"] = False
            activity["fit_data"] = None
            failed += 1
        else:
            activity["has_fit"] = True
            activity["fit_data"] = fit_data
            # Use FIT sport only if Strava type was "Other" (unclassified)
            if activity["session_type"] == "Other":
                sport = str(fit_data.get("sport", "")).lower()
                if sport in FIT_SPORT_MAP:
                    activity["session_type"] = FIT_SPORT_MAP[sport]
            parsed += 1

        if (i + 1) % 50 == 0:
            elapsed = _time.time() - start
            print(f"  Parsed {i+1}/{total} files ({elapsed:.1f}s)...")

    elapsed = _time.time() - start
    print(f"  Done: {parsed} parsed, {missing} missing, {failed} failed ({elapsed:.1f}s)")
    return strava_index


# ---------------------------------------------------------------------------
# Session Log Row Builder
# ---------------------------------------------------------------------------

def build_session_log_row(activity):
    """Build a 22-column Session Log row from a parsed activity dict."""
    fd = activity.get("fit_data") or {}
    date_str = activity["date"]

    # Duration: prefer FIT timer_time, fallback to elapsed, fallback to CSV
    duration_sec = fd.get("total_timer_time") or fd.get("total_elapsed_time")
    if duration_sec:
        duration_min = round(float(duration_sec) / 60, 1)
    elif activity.get("csv_elapsed"):
        duration_min = round(activity["csv_elapsed"] / 60, 1)
    else:
        duration_min = ""

    # Distance: FIT meters -> miles, fallback to CSV
    dist_m = fd.get("total_distance")
    if dist_m is not None and dist_m > 0:
        distance_mi = round(float(dist_m) / 1609.344, 2)
    elif activity.get("csv_distance") and activity["csv_distance"] > 0:
        distance_mi = round(activity["csv_distance"] / 1609.344, 2)
    else:
        distance_mi = ""

    # HR: FIT preferred, CSV fallback
    avg_hr = fd.get("avg_heart_rate") or activity.get("csv_avg_hr") or ""
    max_hr = fd.get("max_heart_rate") or activity.get("csv_max_hr") or ""

    # Calories
    calories = fd.get("total_calories") or activity.get("csv_calories") or ""

    # Training effects
    aerobic_te = fd.get("total_training_effect")
    if aerobic_te is not None:
        aerobic_te = round(float(aerobic_te), 1)
    else:
        aerobic_te = ""
    anaerobic_te = fd.get("total_anaerobic_training_effect")
    if anaerobic_te is not None:
        anaerobic_te = round(float(anaerobic_te), 1)
    else:
        anaerobic_te = ""

    # Elevation
    elevation = fd.get("total_ascent")
    if elevation is not None:
        elevation = round(float(elevation), 1)
    else:
        elevation = ""

    return [
        date_to_day(date_str),                          # 0  Day (A)
        date_str,                                       # 1  Date (B)
        activity["session_type"],                       # 2  Session Type (C)
        "",                                             # 3  Perceived Effort (D) - manual
        "",                                             # 4  Post-Workout Energy (E) - manual
        "",                                             # 5  Notes (F) - manual
        activity["name"],                               # 6  Activity Name (G)
        duration_min,                                   # 7  Duration (min) (H)
        distance_mi,                                    # 8  Distance (mi) (I)
        avg_hr if avg_hr else "",                       # 9  Avg HR (J)
        max_hr if max_hr else "",                       # 10 Max HR (K)
        calories if calories else "",                   # 11 Calories (L)
        aerobic_te,                                     # 12 Aerobic TE (M)
        anaerobic_te,                                   # 13 Anaerobic TE (N)
        fd.get("zone_1", ""),                           # 14 Zone 1 (O)
        fd.get("zone_2", ""),                           # 15 Zone 2 (P)
        fd.get("zone_3", ""),                           # 16 Zone 3 (Q)
        fd.get("zone_4", ""),                           # 17 Zone 4 (R)
        fd.get("zone_5", ""),                           # 18 Zone 5 (S)
        fd.get("zone_ranges", ""),                      # 19 Zone Ranges (T)
        "Strava FIT",                                   # 20 Source (U)
        elevation,                                      # 21 Elevation (m) (V)
    ]


# ---------------------------------------------------------------------------
# Dedup & Import
# ---------------------------------------------------------------------------

def get_existing_entries(source="sqlite"):
    """Get existing Session Log entries for smart dedup.

    Returns dict: {date_str: [(activity_name, session_type, duration_min), ...]}
    """
    entries = defaultdict(list)
    if source == "sheets":
        wb = get_workbook()
        try:
            sheet = wb.worksheet("Session Log")
        except Exception:
            return entries
        rows = sheet.get_all_values()
        for row in rows[1:]:
            if len(row) > 7 and row[1]:
                dur = _safe_float(row[7])
                entries[row[1]].append((row[6], row[2], dur))
    else:
        db_path = PROJECT_DIR / "health_tracker.db"
        if not db_path.exists():
            return entries
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT date, activity_name, session_type, duration_min FROM session_log")
        for date, name, stype, dur in c.fetchall():
            entries[date].append((name, stype or "", dur))
        conn.close()
    return entries


def is_duplicate(activity, existing_entries):
    """Smart duplicate detection: exact name match OR same type + similar duration.

    Catches cases where Strava says "Afternoon Run" and Garmin says "Los Angeles Running"
    for the same workout.
    """
    date = activity["date"]
    if date not in existing_entries:
        return False

    name = activity["name"]
    session_type = activity["session_type"]
    fd = activity.get("fit_data") or {}
    dur_sec = fd.get("total_timer_time") or fd.get("total_elapsed_time")
    dur_min = dur_sec / 60 if dur_sec else (activity.get("csv_elapsed") or 0) / 60

    for existing_name, existing_type, existing_dur in existing_entries[date]:
        # Exact name match
        if existing_name == name:
            return True
        # Same type + similar duration (within 20%)
        if existing_type == session_type and dur_min > 0 and existing_dur:
            avg = (dur_min + existing_dur) / 2
            if avg > 0 and abs(dur_min - existing_dur) / avg < 0.20:
                return True
    return False


def import_to_session_log(activities, dry_run=False):
    """Write parsed activities to Session Log (Sheets + SQLite).

    Uses batch writes to minimize API calls:
    - Batch append rows with RAW (1 API call per chunk)
    - Batch re-write numeric cells with USER_ENTERED (1 API call per chunk)
    - ~2 API calls per chunk of 25 rows = ~10 calls per minute

    Returns (imported, skipped, errors).
    """
    # Get existing entries for smart dedup
    if not dry_run:
        print("  Connecting to Google Sheets...")
        wb = get_workbook()
        existing = get_existing_entries("sheets")
        sheet = wb.worksheet("Session Log")
        db_path = PROJECT_DIR / "health_tracker.db"
        conn = sqlite3.connect(db_path) if db_path.exists() else None
        # Get current row count once (avoid per-row get_all_values)
        current_row_count = len(sheet.get_all_values())
    else:
        existing = get_existing_entries("sqlite")
        conn = None
        current_row_count = 0

    imported = 0
    skipped = 0
    errors = 0

    # Filter: skip duplicates (exact name OR same type + similar duration)
    to_import = []
    for a in activities:
        if is_duplicate(a, existing):
            skipped += 1
            continue
        to_import.append(a)

    print(f"  {len(to_import)} new activities to import, {skipped} already exist")

    if dry_run:
        for a in to_import:
            row = build_session_log_row(a)
            name_safe = a["name"].encode("ascii", "replace").decode("ascii")
            fd = a.get("fit_data") or {}
            zones_str = ""
            if fd.get("zone_1", 0) > 0 or fd.get("zone_2", 0) > 0:
                zones_str = (
                    f" Z1:{fd.get('zone_1',0)} Z2:{fd.get('zone_2',0)} "
                    f"Z3:{fd.get('zone_3',0)} Z4:{fd.get('zone_4',0)} Z5:{fd.get('zone_5',0)}"
                )
            print(
                f"  [DRY RUN] {a['date']} {a['session_type']:<8} "
                f"{name_safe[:30]:<32} dur:{row[7] or '--':>6} "
                f"HR:{row[9] or '--':>4}{zones_str}"
            )
            imported += 1
        return imported, skipped, errors

    # Build all rows
    all_rows = []
    for a in to_import:
        row = build_session_log_row(a)
        all_rows.append((a, row))

    # Batch write in chunks
    CHUNK_SIZE = 25
    NUMERIC_INDICES = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 21]

    for chunk_start in range(0, len(all_rows), CHUNK_SIZE):
        chunk = all_rows[chunk_start:chunk_start + CHUNK_SIZE]
        chunk_num = chunk_start // CHUNK_SIZE + 1
        total_chunks = (len(all_rows) + CHUNK_SIZE - 1) // CHUNK_SIZE
        print(f"  Writing chunk {chunk_num}/{total_chunks} ({len(chunk)} rows)...")

        try:
            # Step 1: Batch append all rows with RAW (1 API call)
            raw_rows = [row for _, row in chunk]
            sheet.append_rows(raw_rows, value_input_option="RAW")
            _time.sleep(1)

            # Step 2: Batch re-write numeric cells with USER_ENTERED (1 API call)
            import gspread as _gspread
            cells = []
            for j, (_, row) in enumerate(chunk):
                sheet_row = current_row_count + chunk_start + j + 1
                for idx in NUMERIC_INDICES:
                    val = row[idx]
                    if val != "" and val is not None:
                        cells.append(_gspread.Cell(sheet_row, idx + 1, val))
            if cells:
                sheet.update_cells(cells, value_input_option="USER_ENTERED")

            # Step 3: Write to SQLite
            for a, row in chunk:
                if conn:
                    upsert_session_log_row(conn, row)

            imported += len(chunk)
            for a, _ in chunk:
                name_safe = a["name"].encode("ascii", "replace").decode("ascii")
                print(f"    {a['date']} {a['session_type']:<8} {name_safe[:40]}")

            # Rate limit: 2 API calls per chunk, allow 6s between chunks
            _time.sleep(6)

        except Exception as e:
            errors += len(chunk)
            print(f"  ERROR on chunk {chunk_num}: {e}", file=sys.stderr)
            if "Quota exceeded" in str(e) or "429" in str(e):
                print("  Rate limited -- waiting 65s before retry...")
                _time.sleep(65)
                # Retry this chunk once
                try:
                    raw_rows = [row for _, row in chunk]
                    sheet.append_rows(raw_rows, value_input_option="RAW")
                    _time.sleep(1)
                    import gspread as _gspread2
                    cells = []
                    for j, (_, row) in enumerate(chunk):
                        sheet_row = current_row_count + chunk_start + j + 1
                        for idx in NUMERIC_INDICES:
                            val = row[idx]
                            if val != "" and val is not None:
                                cells.append(_gspread2.Cell(sheet_row, idx + 1, val))
                    if cells:
                        sheet.update_cells(cells, value_input_option="USER_ENTERED")
                    for a, row in chunk:
                        if conn:
                            upsert_session_log_row(conn, row)
                    errors -= len(chunk)
                    imported += len(chunk)
                    print(f"  Retry succeeded for chunk {chunk_num}")
                    _time.sleep(6)
                except Exception as e2:
                    print(f"  Retry also failed: {e2}", file=sys.stderr)

    if conn:
        conn.commit()
        conn.close()

    return imported, skipped, errors


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(activities, max_hr):
    """Print analysis report of parsed FIT file data."""
    W = 80

    def sep():
        print("=" * W)

    def subsep():
        print("-" * W)

    total = len(activities)
    with_fit = [a for a in activities if a.get("has_fit")]
    without_fit = [a for a in activities if not a.get("has_fit")]

    sep()
    print("FIT FILE PARSE REPORT".center(W))
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}".center(W))
    sep()
    print()

    # --- Parse Summary ---
    print("PARSE SUMMARY")
    subsep()
    print(f"  Total Strava activities:  {total}")
    print(f"  FIT files parsed:         {len(with_fit)}")
    print(f"  FIT files missing/failed: {len(without_fit)}")
    print()

    # Zone boundaries
    boundaries = compute_zone_boundaries(max_hr)
    print(f"  Max HR: {max_hr}")
    print(f"  Zone boundaries: ", end="")
    for i, (lo, _) in enumerate(boundaries):
        if i < 4:
            next_lo = boundaries[i + 1][0]
            print(f"Z{i+1}:{lo}-{next_lo-1}", end="  ")
        else:
            print(f"Z{i+1}:{lo}+")
    print()

    # --- Data Completeness ---
    print()
    print("DATA COMPLETENESS (from FIT files)")
    subsep()
    if with_fit:
        n = len(with_fit)
        fields = [
            ("Duration", lambda a: (a["fit_data"] or {}).get("total_timer_time") is not None),
            ("Distance", lambda a: (a["fit_data"] or {}).get("total_distance") is not None
             and (a["fit_data"] or {}).get("total_distance", 0) > 0),
            ("Avg HR", lambda a: (a["fit_data"] or {}).get("avg_heart_rate") is not None),
            ("Max HR", lambda a: (a["fit_data"] or {}).get("max_heart_rate") is not None),
            ("Calories", lambda a: (a["fit_data"] or {}).get("total_calories") is not None),
            ("Elevation", lambda a: (a["fit_data"] or {}).get("total_ascent") is not None),
            ("Aerobic TE", lambda a: (a["fit_data"] or {}).get("total_training_effect") is not None),
            ("HR Samples", lambda a: (a["fit_data"] or {}).get("hr_sample_count", 0) > 0),
            ("HR Zones", lambda a: sum(
                (a["fit_data"] or {}).get(f"zone_{z}", 0) for z in range(1, 6)) > 0),
        ]
        for label, test in fields:
            count = sum(1 for a in with_fit if test(a))
            pct = 100 * count // n
            print(f"  {label:<14} {count:>4}/{n} ({pct:>3}%)")
    print()

    # --- HR Zone Coverage by Year ---
    print()
    print("HR ZONE COVERAGE BY YEAR (from FIT files)")
    subsep()
    by_year = defaultdict(lambda: {"total": 0, "with_zones": 0})
    for a in with_fit:
        yr = a["date"][:4]
        by_year[yr]["total"] += 1
        zone_total = sum((a["fit_data"] or {}).get(f"zone_{z}", 0) for z in range(1, 6))
        if zone_total > 0:
            by_year[yr]["with_zones"] += 1

    print(f"{'Year':>6}  {'Parsed':>7}  {'W/ Zones':>9}  {'Coverage':>9}")
    print(f"{'----':>6}  {'------':>7}  {'--------':>9}  {'--------':>9}")
    for yr in sorted(by_year):
        d = by_year[yr]
        pct = 100 * d["with_zones"] // d["total"] if d["total"] else 0
        print(f"{yr:>6}  {d['total']:>7}  {d['with_zones']:>9}  {pct:>8}%")
    print()

    # --- Type Breakdown ---
    print()
    print("ACTIVITY TYPE BREAKDOWN")
    subsep()
    type_year = defaultdict(lambda: Counter())
    for a in activities:
        yr = a["date"][:4]
        type_year[yr][a["session_type"]] += 1

    all_types = sorted(set(t for yr_data in type_year.values() for t in yr_data))
    years = sorted(type_year.keys())
    header = f"{'Type':<12}" + "".join(f"{yr:>7}" for yr in years) + f"{'Total':>8}"
    print(header)
    print("-" * len(header))
    for t in all_types:
        vals = "".join(f"{type_year[yr].get(t, 0):>7}" for yr in years)
        row_total = sum(type_year[yr].get(t, 0) for yr in years)
        print(f"{t:<12}{vals}{row_total:>8}")
    print()

    # --- Sample Output ---
    print()
    print("SAMPLE SESSION LOG ROWS (first 10 with HR zones)")
    subsep()
    samples = [a for a in with_fit
               if sum((a["fit_data"] or {}).get(f"zone_{z}", 0) for z in range(1, 6)) > 0][:10]
    print(f"{'Date':<12} {'Type':<8} {'Name':<24} {'Dur':>6} {'Dist':>6} {'HR':>4} "
          f"{'Z1':>5} {'Z2':>5} {'Z3':>5} {'Z4':>5} {'Z5':>5}")
    print("-" * 96)
    for a in samples:
        fd = a["fit_data"]
        dur_sec = fd.get("total_timer_time") or fd.get("total_elapsed_time") or 0
        dur = f"{dur_sec/60:.0f}" if dur_sec else "--"
        dist_m = fd.get("total_distance") or 0
        dist = f"{dist_m/1609.344:.1f}" if dist_m > 0 else "--"
        hr_val = fd.get("avg_heart_rate")
        hr = f"{hr_val}" if hr_val else "--"
        name = a["name"].encode("ascii", "replace").decode("ascii")[:22]
        z1 = f"{fd.get('zone_1', 0):.1f}"
        z2 = f"{fd.get('zone_2', 0):.1f}"
        z3 = f"{fd.get('zone_3', 0):.1f}"
        z4 = f"{fd.get('zone_4', 0):.1f}"
        z5 = f"{fd.get('zone_5', 0):.1f}"
        print(f"{a['date']:<12} {a['session_type']:<8} {name:<24} {dur:>6} {dist:>6} {hr:>4} "
              f"{z1:>5} {z2:>5} {z3:>5} {z4:>5} {z5:>5}")
    print()

    sep()
    print("END OF REPORT".center(W))
    sep()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parse Strava .fit.gz files for HR zones")
    parser.add_argument("--do-import", action="store_true",
                        help="Import missing activities to Session Log (Sheets + SQLite)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be imported without writing")
    parser.add_argument("--year", type=str, help="Filter to specific year")
    parser.add_argument("--type", type=str, help="Filter to activity type (Run, Cycle, etc.)")
    parser.add_argument("--max-hr", type=int, default=DEFAULT_MAX_HR,
                        help=f"Max HR for zone calculation (default: {DEFAULT_MAX_HR})")
    args = parser.parse_args()

    # Validate
    if not STRAVA_CSV.exists():
        print(f"ERROR: Strava CSV not found at {STRAVA_CSV}", file=sys.stderr)
        sys.exit(1)

    # Load Strava index
    print("Loading Strava activity index...")
    index = load_strava_index(STRAVA_CSV)
    print(f"  {len(index)} activities with FIT file references")

    # Apply filters
    if args.year:
        index = [a for a in index if a["date"][:4] == args.year]
        print(f"  Filtered to {args.year}: {len(index)} activities")
    if args.type:
        t = args.type.capitalize()
        index = [a for a in index if a["session_type"] == t]
        print(f"  Filtered to type '{t}': {len(index)} activities")

    # Parse all FIT files
    print(f"\nParsing {len(index)} FIT files (max HR={args.max_hr})...")
    index = parse_all_fit_files(index, args.max_hr)

    # Report or Import
    if args.do_import or args.dry_run:
        print(f"\n{'DRY RUN' if args.dry_run else 'IMPORTING'} to Session Log...")
        imported, skipped, errors = import_to_session_log(index, dry_run=args.dry_run)
        print(f"\nResult: {imported} imported, {skipped} skipped (existing), {errors} errors")
    else:
        print_report(index, args.max_hr)


if __name__ == "__main__":
    main()
