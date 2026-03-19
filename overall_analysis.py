"""
overall_analysis.py -- Scientifically-grounded daily health analysis engine.

Reads data from all Google Sheets tabs (Garmin, Sleep, Daily Log, Session Log,
Nutrition), computes a composite Readiness Score using individual rolling
baselines, and generates actionable insights with scientific citations.

Methodology:
  - Individual z-scores vs 30-day rolling baseline (not population norms)
  - 5-day weighted sleep average (Van Dongen et al. 2003)
  - ACWR training load ratio (Gabbett 2016)
  - Keyword-based diet/behavior flagging from free-text notes
  - Confidence rating based on data completeness

Usage:
    python overall_analysis.py                     # Analyze yesterday
    python overall_analysis.py --date 2026-03-15   # Analyze specific date
    python overall_analysis.py --today             # Analyze today
    python overall_analysis.py --week              # 7-day summary

See reference/METHODOLOGY.md for full scientific basis and citations.
"""

import re
import sys
import json
import math
import argparse
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from utils import get_workbook, _safe_float, date_to_day, load_thresholds
from schema import OVERALL_ANALYSIS_HEADERS
from profile_loader import (
    load_profile, get_accommodations, get_relevant_conditions,
    get_threshold_overrides, get_priority_concerns, check_biomarker_staleness,
    format_recommendation, sanitize_for_notification, merge_knowledge
)

# Load scoring thresholds from thresholds.json (falls back to hardcoded defaults)
_THRESHOLDS = load_thresholds()

# ---------------------------------------------------------------------------
# Health Knowledge Base Loader
# ---------------------------------------------------------------------------

def load_health_knowledge():
    """Load structured health knowledge from reference/health_knowledge.json.

    Returns dict keyed by entry 'id' for fast lookup.
    Falls back to empty dict if file missing or malformed.
    """
    kb_path = Path(__file__).parent / "reference" / "health_knowledge.json"
    if not kb_path.exists():
        print("  [knowledge] health_knowledge.json not found -- using hardcoded fallbacks.")
        return {}
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = {entry["id"]: entry for entry in data.get("knowledge", [])}
        pending = sum(1 for e in entries.values() if e.get("confidence") == "Pending")
        if pending:
            print(f"  [knowledge] Loaded {len(entries)} knowledge entries ({pending} pending evaluation).")
        else:
            print(f"  [knowledge] Loaded {len(entries)} knowledge entries.")
        return entries
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  [knowledge] Error loading health_knowledge.json: {e} -- using fallbacks.")
        return {}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Readiness label thresholds (from thresholds.json)
READINESS_LABELS = [
    (entry["min_score"], entry["label"])
    for entry in _THRESHOLDS["readiness_labels"]
]

# Diet/behavior keywords to flag in notes
ALCOHOL_KEYWORDS = ["alcohol", "beer", "wine", "drink", "drinks", "cocktail",
                    "whiskey", "vodka", "tequila", "bourbon", "sake", "soju"]
SUGAR_KEYWORDS = ["sugar", "candy", "ice cream", "cake", "cookies", "pastry",
                  "chocolate", "soda", "dessert", "sweets", "donut", "brownie"]
FAST_FOOD_KEYWORDS = ["fast food", "mcdonald", "burger king", "wendy", "taco bell",
                      "pizza", "fried", "takeout", "take out", "take-out"]
LATE_MEAL_KEYWORDS = ["late meal", "late dinner", "ate late", "midnight snack",
                      "late night eat", "eating late"]
CAFFEINE_LATE_KEYWORDS = ["coffee afternoon", "coffee evening", "late coffee",
                          "caffeine late", "energy drink"]

# ACWR thresholds (Gabbett 2016, from thresholds.json)
ACWR_HIGH = _THRESHOLDS["acwr"]["elevated"]        # elevated injury risk
ACWR_LOW = _THRESHOLDS["acwr"]["detraining"]       # detraining risk
ACWR_SWEET_LOW = _THRESHOLDS["acwr"]["sweet_low"]
ACWR_SWEET_HIGH = _THRESHOLDS["acwr"]["sweet_high"]


# ---------------------------------------------------------------------------
# Data Reading
# ---------------------------------------------------------------------------

def _read_tab_as_dicts(wb, tab_name):
    """Read a sheet tab and return list of dicts keyed by header names."""
    try:
        sheet = wb.worksheet(tab_name)
    except Exception:
        return []
    rows = sheet.get_all_values()
    if len(rows) < 2:
        return []
    headers = rows[0]
    result = []
    for row in rows[1:]:
        if not row or len(row) < 2 or not row[0]:
            continue
        d = {}
        for i, h in enumerate(headers):
            d[h] = row[i] if i < len(row) else ""
        result.append(d)
    return result


def _get_date_col(row_dict, tab_name):
    """Extract date string from a row dict. Date is col B for most tabs, col A for Overall Analysis."""
    if tab_name == "Overall Analysis":
        return row_dict.get("Date", "")
    return row_dict.get("Date", "")


def read_all_data(wb):
    """Read all tabs into a unified data structure keyed by tab name."""
    return {
        "garmin": _read_tab_as_dicts(wb, "Garmin"),
        "sleep": _read_tab_as_dicts(wb, "Sleep"),
        "daily_log": _read_tab_as_dicts(wb, "Daily Log"),
        "session_log": _read_tab_as_dicts(wb, "Session Log"),
        "nutrition": _read_tab_as_dicts(wb, "Nutrition"),
    }


def _rows_by_date(rows):
    """Index rows by date string for fast lookup."""
    by_date = {}
    for r in rows:
        d = r.get("Date", "")
        if d and d.startswith("20"):
            if d not in by_date:
                by_date[d] = r
            # For session log, multiple entries per date -- handled separately
    return by_date


def _sessions_by_date(rows):
    """Index session log: date -> list of sessions (multiple per day allowed)."""
    by_date = {}
    for r in rows:
        d = r.get("Date", "")
        if d and d.startswith("20"):
            by_date.setdefault(d, []).append(r)
    return by_date


# ---------------------------------------------------------------------------
# Baseline Computation (z-score methodology)
# ---------------------------------------------------------------------------

def _get_values_in_window(by_date, target_date, days_back, field):
    """Get numeric values for a field over a date window (excluding target_date)."""
    values = []
    for offset in range(1, days_back + 1):
        d = str(target_date - timedelta(days=offset))
        row = by_date.get(d)
        if row:
            v = _safe_float(row.get(field))
            if v is not None:
                values.append(v)
    return values


def _get_values_including_today(by_date, target_date, days_back, field):
    """Get numeric values for a field over a date window (including target_date)."""
    values = []
    for offset in range(0, days_back):
        d = str(target_date - timedelta(days=offset))
        row = by_date.get(d)
        if row:
            v = _safe_float(row.get(field))
            if v is not None:
                values.append(v)
    return values


def compute_baselines(by_date_garmin, by_date_sleep, target_date):
    """Compute rolling baselines for key metrics.

    Uses adaptive window: 60-90 days when available, falls back to 30 days
    for early-stage data. Minimum 7 data points for any baseline.

    Also computes HRV trend direction (5-day slope) to distinguish
    overtraining (declining) from detraining (flat-low) patterns.

    Returns dict with mean, std, today's value, z-score, n, outliers,
    and (for HRV) trend direction.
    """
    baselines = {}

    metrics = [
        ("hrv", by_date_garmin, "HRV (overnight avg)"),
        ("rhr", by_date_garmin, "Resting HR"),
        ("sleep_score", by_date_sleep, "Garmin Sleep Score"),
        ("sleep_duration", by_date_sleep, "Total Sleep (hrs)"),
        ("body_battery", by_date_garmin, "Body Battery"),
        ("steps", by_date_garmin, "Steps"),
        ("stress", by_date_garmin, "Avg Stress Level"),
    ]

    for key, source, field in metrics:
        # Adaptive window: try 90 days first, fall back to 60, then 30
        window_values = _get_values_in_window(source, target_date, 90, field)
        if len(window_values) < 30:
            window_values = _get_values_in_window(source, target_date, 60, field)
        if len(window_values) < 14:
            window_values = _get_values_in_window(source, target_date, 30, field)

        today_row = source.get(str(target_date), {})
        today_val = _safe_float(today_row.get(field))

        if len(window_values) >= 7:  # need at least 7 days for meaningful baseline
            mean = sum(window_values) / len(window_values)
            variance = sum((v - mean) ** 2 for v in window_values) / (len(window_values) - 1)
            std = variance ** 0.5 if variance > 0 else 1.0
            z = (today_val - mean) / std if today_val is not None and std > 0 else None
        else:
            mean, std, z = None, None, None

        # Flag outliers (>3 SD from mean) — don't exclude, just flag
        outliers = []
        if mean is not None and std is not None and std > 0:
            for v in window_values:
                if abs(v - mean) > 3 * std:
                    outliers.append(v)
            if today_val is not None and abs(today_val - mean) > 3 * std:
                outliers.append(today_val)

        entry = {
            "mean": mean,
            "std": std,
            "today": today_val,
            "z": z,
            "n": len(window_values),
            "outliers": outliers,
        }

        # HRV trend direction: 5-day slope to distinguish overtraining vs detraining
        if key == "hrv":
            recent_hrv = []
            for offset in range(5):
                d = str(target_date - timedelta(days=offset))
                row = source.get(d, {})
                v = _safe_float(row.get(field))
                if v is not None:
                    recent_hrv.append((offset, v))
            if len(recent_hrv) >= 3:
                # Simple linear regression slope (negative offset = recent first)
                n_pts = len(recent_hrv)
                x_mean = sum(x for x, _ in recent_hrv) / n_pts
                y_mean = sum(y for _, y in recent_hrv) / n_pts
                num = sum((x - x_mean) * (y - y_mean) for x, y in recent_hrv)
                den = sum((x - x_mean) ** 2 for x, _ in recent_hrv)
                slope = num / den if den > 0 else 0
                # Positive slope = recent values lower (declining, since offset 0 = today)
                # Negative slope = recent values higher (recovering)
                if slope > 1.0:
                    entry["trend"] = "declining"
                elif slope < -1.0:
                    entry["trend"] = "recovering"
                else:
                    entry["trend"] = "stable"
            else:
                entry["trend"] = None

        baselines[key] = entry

    return baselines


# ---------------------------------------------------------------------------
# Sleep Context (5-day weighted rolling average)
# ---------------------------------------------------------------------------

def analyze_sleep_context(by_date_sleep, by_date_garmin, target_date, baselines):
    """Analyze 5-day sleep trend with recent nights weighted 2x.

    Returns (context_text, sleep_debt_hours, trend_direction, deep_trend, rem_trend).
    Based on Van Dongen et al. 2003 -- cumulative sleep restriction model.
    """
    # Collect last 5 nights of sleep data
    scores = []
    durations = []
    for offset in range(0, 5):
        d = str(target_date - timedelta(days=offset))
        row = by_date_sleep.get(d)
        if row:
            s = _safe_float(row.get("Garmin Sleep Score"))
            dur = _safe_float(row.get("Total Sleep (hrs)"))
            weight = 2.0 if offset == 0 else 1.0  # most recent night weighted 2x
            if s is not None:
                scores.append((s, weight))
            if dur is not None:
                durations.append((dur, weight))

    if not scores:
        return "No sleep data available for analysis window.", None, None, None, None

    weighted_score = sum(s * w for s, w in scores) / sum(w for _, w in scores)
    weighted_duration = sum(d * w for d, w in durations) / sum(w for _, w in durations) if durations else None

    # Sleep debt: compare weighted avg to 30-day baseline
    baseline_duration = baselines.get("sleep_duration", {}).get("mean")
    sleep_debt = None
    if weighted_duration is not None and baseline_duration is not None:
        sleep_debt = baseline_duration - weighted_duration  # positive = debt

    # Trend direction: are last 3 nights improving or declining?
    recent_scores = []
    for offset in range(0, 3):
        d = str(target_date - timedelta(days=offset))
        row = by_date_sleep.get(d)
        if row:
            s = _safe_float(row.get("Garmin Sleep Score"))
            if s is not None:
                recent_scores.append(s)

    trend = None
    if len(recent_scores) >= 2:
        if recent_scores[0] > recent_scores[-1]:
            trend = "improving"
        elif recent_scores[0] < recent_scores[-1]:
            trend = "declining"
        else:
            trend = "stable"

    # Build context text
    parts = []
    parts.append(f"5-day weighted avg: {weighted_score:.0f} score")
    if weighted_duration is not None:
        parts.append(f"{weighted_duration:.1f}h duration")
    if sleep_debt is not None and sleep_debt > 0.5:
        parts.append(f"sleep debt: {sleep_debt:.1f}h below baseline")
    if trend:
        parts.append(f"trend: {trend}")

    # Today's specific data
    today = by_date_sleep.get(str(target_date))
    if today:
        today_score = _safe_float(today.get("Garmin Sleep Score"))
        today_dur = _safe_float(today.get("Total Sleep (hrs)"))
        today_deep = _safe_float(today.get("Deep %"))
        today_rem = _safe_float(today.get("REM %"))
        specifics = []
        if today_score is not None:
            specifics.append(f"last night: {today_score:.0f}")
        if today_dur is not None:
            specifics.append(f"{today_dur:.1f}h")
        if today_deep is not None:
            specifics.append(f"deep {today_deep:.0f}%")
        if today_rem is not None:
            specifics.append(f"REM {today_rem:.0f}%")
        if specifics:
            parts.append("(" + ", ".join(specifics) + ")")

    # --- Deep/REM 3-night trends (mirrors sleep score trend logic) ---
    deep_trend = None
    rem_trend = None
    recent_deep = []
    recent_rem = []
    for offset in range(0, 3):
        d = str(target_date - timedelta(days=offset))
        row = by_date_sleep.get(d)
        if row:
            dp = _safe_float(row.get("Deep %"))
            rp = _safe_float(row.get("REM %"))
            if dp is not None:
                recent_deep.append(dp)
            if rp is not None:
                recent_rem.append(rp)

    if len(recent_deep) >= 2:
        if recent_deep[0] > recent_deep[-1]:
            deep_trend = "improving"
        elif recent_deep[0] < recent_deep[-1]:
            deep_trend = "declining"
        else:
            deep_trend = "stable"

    if len(recent_rem) >= 2:
        if recent_rem[0] > recent_rem[-1]:
            rem_trend = "improving"
        elif recent_rem[0] < recent_rem[-1]:
            rem_trend = "declining"
        else:
            rem_trend = "stable"

    context_text = " | ".join(parts)
    return context_text, sleep_debt, trend, deep_trend, rem_trend


# ---------------------------------------------------------------------------
# Training Load (ACWR -- Acute:Chronic Workload Ratio)
# ---------------------------------------------------------------------------

def compute_acwr(sessions_by_date, target_date):
    """Compute Acute:Chronic Workload Ratio using session duration * avg HR as load proxy.

    Acute = 7-day load, Chronic = 28-day rolling average weekly load.
    Sweet spot: 0.8-1.3 (Gabbett 2016).

    Returns (acwr_value, status_text, acute_load, chronic_load).
    """
    def _session_load(session):
        """Compute load for a single session.

        Prefers sRPE (effort * duration / 10) when Perceived Effort is available
        (Foster 2001 gold standard). Falls back to TRIMP proxy (duration * HR / 100).
        """
        dur = _safe_float(session.get("Duration (min)"))
        effort = _safe_float(session.get("Perceived Effort (1-10)"))
        hr = _safe_float(session.get("Avg HR"))
        # sRPE is preferred when both effort and duration are available
        if effort and dur:
            return effort * dur / 10  # sRPE (session RPE)
        elif dur and hr:
            return dur * hr / 100  # TRIMP-like proxy
        elif dur:
            return dur  # fallback to duration only
        return 0

    # Calculate weekly loads for last 4 weeks
    weekly_loads = []
    for week in range(4):
        week_load = 0
        for day_offset in range(week * 7, (week + 1) * 7):
            d = str(target_date - timedelta(days=day_offset))
            sessions = sessions_by_date.get(d, [])
            for s in sessions:
                week_load += _session_load(s)
        weekly_loads.append(week_load)

    acute_load = weekly_loads[0]  # most recent 7 days
    chronic_load = sum(weekly_loads[1:]) / 3 if sum(weekly_loads[1:]) > 0 else 0

    if chronic_load == 0:
        if acute_load == 0:
            return None, "No training data in last 28 days.", 0, 0
        return None, f"Acute load {acute_load:.0f} but no chronic baseline (new to training?).", acute_load, 0

    acwr = acute_load / chronic_load

    # Status
    if acwr > 1.5:
        status = f"ACWR {acwr:.2f} -- SPIKE. Acute load {acute_load:.0f} is {acwr:.1f}x your 28-day average. Elevated injury/illness risk (Gabbett 2016)."
    elif acwr > ACWR_HIGH:
        status = f"ACWR {acwr:.2f} -- HIGH. Training this week exceeds your 28-day avg. Monitor recovery closely."
    elif acwr >= ACWR_LOW:
        status = f"ACWR {acwr:.2f} -- Sweet spot. Training load is well-matched to your fitness level."
    else:
        status = f"ACWR {acwr:.2f} -- LOW. You're training below your recent capacity. Consider increasing load if recovery allows."

    return acwr, status, acute_load, chronic_load


# ---------------------------------------------------------------------------
# Notes Parsing (keyword-based heuristics)
# ---------------------------------------------------------------------------

NEGATION_WORDS = {"no", "not", "didn't", "didnt", "didn't", "avoided", "skipped",
                  "without", "zero", "none", "never", "don't", "dont", "don't",
                  "wasn't", "wasnt", "wasn't", "isn't", "isnt", "isn't"}


def _search_notes(text, keywords):
    """Check if any keywords appear in text (case-insensitive), with negation detection.

    If a keyword appears within 3 words of a negation word (no, not, avoided, etc.),
    it is NOT flagged. This prevents "avoided alcohol" from triggering the alcohol flag.
    """
    if not text:
        return []
    text_lower = text.lower()
    words = text_lower.split()
    matched = []
    for kw in keywords:
        if kw not in text_lower:
            continue
        # Find position of keyword in word list
        negated = False
        kw_words = kw.split()
        for i, word in enumerate(words):
            if kw_words[0] in word:
                # Check 3 words before for negation
                start = max(0, i - 3)
                preceding = words[start:i]
                if any(neg in w for w in preceding for neg in NEGATION_WORDS):
                    negated = True
                    break
        if not negated:
            matched.append(kw)
    return matched


def parse_notes_for_flags(daily_log_by_date, nutrition_by_date, target_date,
                          days_back=2, sessions_by_date=None, sleep_by_date=None):
    """Scan free-text notes for diet/behavior flags over the lookback window.

    Scans Daily Log, Nutrition, Session Log, and Sleep notes for keyword matches.
    Returns list of (date, flag_type, matched_keywords) tuples.
    """
    flags = []

    for offset in range(0, days_back):
        d = str(target_date - timedelta(days=offset))

        # Collect all notes for this date
        notes_texts = []
        dl = daily_log_by_date.get(d, {})
        for field in ["Midday Notes", "Evening Notes"]:
            if dl.get(field):
                notes_texts.append(dl[field])

        nut = nutrition_by_date.get(d, {})
        for field in ["Breakfast", "Lunch", "Dinner", "Snacks", "Notes"]:
            if nut.get(field):
                notes_texts.append(nut[field])

        # Session Log notes (multiple sessions per day)
        if sessions_by_date:
            for session in sessions_by_date.get(d, []):
                note = session.get("Notes", "")
                if note:
                    notes_texts.append(note)

        # Sleep notes
        if sleep_by_date:
            sleep_row = sleep_by_date.get(d, {})
            sleep_note = sleep_row.get("Notes", "")
            if sleep_note:
                notes_texts.append(sleep_note)

        combined = " ".join(notes_texts)
        if not combined.strip():
            continue

        matches = _search_notes(combined, ALCOHOL_KEYWORDS)
        if matches:
            flags.append((d, "alcohol", matches))

        matches = _search_notes(combined, SUGAR_KEYWORDS)
        if matches:
            flags.append((d, "sugar/refined_carbs", matches))

        matches = _search_notes(combined, FAST_FOOD_KEYWORDS)
        if matches:
            flags.append((d, "fast_food", matches))

        matches = _search_notes(combined, LATE_MEAL_KEYWORDS)
        if matches:
            flags.append((d, "late_meal", matches))

        matches = _search_notes(combined, CAFFEINE_LATE_KEYWORDS)
        if matches:
            flags.append((d, "late_caffeine", matches))

    return flags


# ---------------------------------------------------------------------------
# Readiness Score Composite
# ---------------------------------------------------------------------------

def _z_to_score(z):
    """Map z-score to 1-10 using sigmoid curve (more sensitive in decision zone).

    Sigmoid: score = 1 + 9 / (1 + exp(-1.5 * z))
    Compared to linear (6 + z*2):
      - More sensitive in the 5-7 range where Fair/Good decisions happen
      - Compresses at extremes (±3 SD) instead of hard clipping
      - z=0 -> ~5.5, z=+1 -> ~7.7, z=+2 -> ~9.3, z=-1 -> ~3.3, z=-2 -> ~1.7
    Modeled after WHOOP/Oura approach (sigmoid/logistic scoring curves).
    """
    return 1 + 9 / (1 + math.exp(-1.5 * z))


def compute_readiness(baselines, sleep_context, daily_log_by_date, target_date,
                      profile=None):
    """Compute composite readiness score (1-10) from 4 evidence-weighted components.

    Evidence-based weights (JAMA MESA 2020, Frontiers HRV meta-review 2019):
      1. HRV status   — 35% (strongest single predictor of cognitive/physical readiness)
      2. Sleep quality — 30% (second strongest; architecture + debt matter most)
      3. RHR status   — 20% (lagging indicator, less predictive than HRV)
      4. Subjective    — 15% (unreliable after 3+ days restriction; Van Dongen 2003)

    When components are missing, remaining weights are re-normalized to sum to 1.0.

    Returns (score, label, components_detail, confidence).
    """
    # Evidence-based weights from thresholds.json: HRV > Sleep > RHR > Subjective
    COMPONENT_WEIGHTS = dict(_THRESHOLDS["component_weights"])  # copy so we can modify

    # Apply profile threshold overrides if available
    if profile:
        overrides = get_threshold_overrides(profile)
        weight_overrides = overrides.get("readiness_weights")
        if weight_overrides:
            COMPONENT_WEIGHTS.update(weight_overrides)

    # Extract sleep debt from sleep_context tuple (passed as (text, debt, trend, ...))
    sleep_debt = None
    if isinstance(sleep_context, tuple) and len(sleep_context) >= 2:
        sleep_debt = sleep_context[1]

    # Van Dongen subjective penalty: after 3+ days of sleep debt > 0.75h,
    # subjective ratings become unreliable (Van Dongen et al. 2003 showed
    # subjective sleepiness plateaus while cognitive impairment continues).
    # Reduce Subjective weight by 50% to prevent false confidence.
    van_dongen_penalty = False
    if sleep_debt is not None and sleep_debt > 0.75:
        COMPONENT_WEIGHTS["Subjective"] = COMPONENT_WEIGHTS.get("Subjective", 0.15) * 0.5
        van_dongen_penalty = True

    components = {}

    # 1. HRV Status (z-score -> 1-10 via sigmoid)
    hrv_z = baselines.get("hrv", {}).get("z")
    if hrv_z is not None:
        hrv_score = _z_to_score(hrv_z)
        components["HRV"] = (hrv_score, f"z={hrv_z:+.1f}")

    # 2. RHR Status (inverted z-score -> 1-10 via sigmoid; lower RHR is better)
    rhr_z = baselines.get("rhr", {}).get("z")
    if rhr_z is not None:
        rhr_score = _z_to_score(-rhr_z)  # invert: low RHR = positive
        components["RHR"] = (rhr_score, f"z={rhr_z:+.1f}")

    # 3. Sleep Quality (z-score -> 1-10 via sigmoid)
    sleep_score_z = baselines.get("sleep_score", {}).get("z")
    sleep_score_today = baselines.get("sleep_score", {}).get("today")
    if sleep_score_z is not None:
        sleep_component = _z_to_score(sleep_score_z)
        components["Sleep"] = (sleep_component, f"z={sleep_score_z:+.1f}")
    elif sleep_score_today is not None:
        sleep_component = max(1, min(10, sleep_score_today / 10))
        components["Sleep"] = (sleep_component, f"raw={sleep_score_today:.0f}")

    # 4. Subjective Wellness (Morning Energy + prev Day Rating + prev Midday Body Feel)
    today_dl = daily_log_by_date.get(str(target_date), {})
    morning_energy = _safe_float(today_dl.get("Morning Energy (1-10)"))
    prev_dl = daily_log_by_date.get(str(target_date - timedelta(days=1)), {})
    prev_day_rating = _safe_float(prev_dl.get("Day Rating (1-10)"))
    prev_body_feel = _safe_float(prev_dl.get("Midday Body Feel (1-10)"))

    subj_values = [v for v in [morning_energy, prev_day_rating, prev_body_feel]
                   if v is not None]
    if subj_values:
        subj_score = sum(subj_values) / len(subj_values)
        detail = []
        if morning_energy is not None:
            detail.append(f"morning={morning_energy:.0f}")
        if prev_day_rating is not None:
            detail.append(f"prev_day={prev_day_rating:.0f}")
        if prev_body_feel is not None:
            detail.append(f"body_feel={prev_body_feel:.0f}")
        if van_dongen_penalty:
            detail.append("VAN_DONGEN_PENALTY")
        components["Subjective"] = (subj_score, ", ".join(detail))

    # Composite score — weighted, re-normalized for missing components
    if not components:
        return None, "N/A", {}, "Low"

    weight_sum = sum(COMPONENT_WEIGHTS[k] for k in components)
    score = sum(components[k][0] * COMPONENT_WEIGHTS[k] for k in components) / weight_sum
    score = round(score, 1)

    # Label (use profile overrides if available, else global defaults)
    labels = READINESS_LABELS
    if profile:
        overrides = get_threshold_overrides(profile)
        label_overrides = overrides.get("readiness_labels")
        if label_overrides:
            labels = [(entry["min_score"], entry["label"]) for entry in label_overrides]
    label = "Poor"
    for threshold, lbl in labels:
        if score >= threshold:
            label = lbl
            break

    # Confidence — based on baseline depth + component availability
    # Thresholds: n>=90 for High, n>=60 for Medium-High, n>=30 for Medium
    available = len(components)
    n_hrv = baselines.get("hrv", {}).get("n", 0)
    conf_thresholds = _THRESHOLDS["confidence"]
    if available >= 4 and n_hrv >= conf_thresholds["high_min_n"]:
        confidence = "High"
    elif available >= 3 and n_hrv >= conf_thresholds["medium_high_min_n"]:
        confidence = "Medium-High"
    elif available >= 2 and n_hrv >= conf_thresholds["medium_min_n"]:
        confidence = "Medium"
    else:
        confidence = "Low"

    return score, label, components, confidence


# ---------------------------------------------------------------------------
# Insight Generation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Dynamic Knowledge Trigger Scanner
# ---------------------------------------------------------------------------

def _eval_simple_trigger(trigger, data_sources, sessions_by_date, target_date):
    """Evaluate a simple threshold trigger against actual data.

    trigger schema:
      {"tab": "garmin"|"sleep"|"daily_log"|"nutrition",
       "field": "column header",
       "op": "<"|">"|"<="|">=",
       "value": number,
       "agg": "any"|"avg"|"all",
       "lookback": int (days),
       "requires_session": bool (optional)}

    Returns (fired: bool, context_str: str) where context_str has the data
    that triggered it (e.g., "avg 6,234 steps over 7 days").
    """
    tab_data = data_sources.get(trigger["tab"], {})
    lookback = trigger.get("lookback", 3)
    field = trigger["field"]
    values = []

    for offset in range(0, lookback):
        d = str(target_date - timedelta(days=offset))
        row = tab_data.get(d)
        if row:
            v = _safe_float(row.get(field))
            if v is not None:
                values.append((d, v))

    if not values:
        return False, ""

    op = trigger["op"]
    threshold = trigger["value"]
    agg = trigger.get("agg", "any")

    def _compare(val, op_, thresh):
        if op_ == "<": return val < thresh
        if op_ == ">": return val > thresh
        if op_ == "<=": return val <= thresh
        if op_ == ">=": return val >= thresh
        return False

    # Check requires_session: only fire if there was a training session on a
    # day that also meets the threshold condition
    if trigger.get("requires_session"):
        for d, v in values:
            if _compare(v, op, threshold) and sessions_by_date.get(d):
                session_name = sessions_by_date[d][0].get("Activity Name", "workout")
                return True, f"{field} was {v:.1f} on {d} (training: {session_name})"
        return False, ""

    if agg == "any":
        for d, v in values:
            if _compare(v, op, threshold):
                return True, f"{field} was {v:.1f} on {d}"
        return False, ""
    elif agg == "avg":
        avg_val = sum(v for _, v in values) / len(values)
        if _compare(avg_val, op, threshold):
            return True, f"avg {field} {avg_val:.1f} over {len(values)} days"
        return False, ""
    elif agg == "all":
        if all(_compare(v, op, threshold) for _, v in values):
            return True, f"{field} {op} {threshold} all {len(values)} days"
        return False, ""

    return False, ""


def _eval_compound_trigger(trigger, data_sources, sessions_by_date, target_date):
    """Evaluate a compound trigger (all conditions must be true)."""
    contexts = []
    for condition in trigger.get("conditions", []):
        fired, ctx = _eval_simple_trigger(condition, data_sources, sessions_by_date, target_date)
        if not fired:
            return False, ""
        contexts.append(ctx)
    return True, " + ".join(contexts)


def _eval_divergence_trigger(trigger, data_sources, target_date):
    """Evaluate a divergence trigger (subjective vs objective metrics disagree)."""
    lookback = trigger.get("lookback", 3)
    subj = trigger["subjective"]
    obj = trigger["objective"]

    subj_data = data_sources.get(subj["tab"], {})
    obj_data = data_sources.get(obj["tab"], {})

    divergence_days = 0
    for offset in range(0, lookback):
        d = str(target_date - timedelta(days=offset))
        sv = _safe_float(subj_data.get(d, {}).get(subj["field"]))
        ov = _safe_float(obj_data.get(d, {}).get(obj["field"]))

        if sv is None or ov is None:
            continue

        subj_ok = (sv >= subj["value"]) if subj["op"] == ">=" else (sv <= subj["value"])
        obj_bad = (ov < obj["value"]) if obj["op"] == "<" else (ov > obj["value"])

        if subj_ok and obj_bad:
            divergence_days += 1

    if divergence_days >= 2:
        return True, f"subjective energy OK but sleep score low for {divergence_days} days"
    return False, ""


def _eval_variance_trigger(trigger, data_sources, target_date):
    """Evaluate a variance trigger (e.g., wake time inconsistency)."""
    tab_data = data_sources.get(trigger["tab"], {})
    field = trigger["field"]
    lookback = trigger.get("lookback", 7)
    max_std = trigger.get("max_std_minutes", 30)

    times_minutes = []
    for offset in range(0, lookback):
        d = str(target_date - timedelta(days=offset))
        row = tab_data.get(d, {})
        time_str = row.get(field, "")
        if time_str and ":" in time_str:
            try:
                parts = time_str.split(":")
                minutes = int(parts[0]) * 60 + int(parts[1].split()[0])
                # Handle AM/PM if present
                if "PM" in time_str.upper() and int(parts[0]) != 12:
                    minutes += 720
                elif "AM" in time_str.upper() and int(parts[0]) == 12:
                    minutes -= 720
                times_minutes.append(minutes)
            except (ValueError, IndexError):
                continue

    if len(times_minutes) < 3:
        return False, ""

    mean_t = sum(times_minutes) / len(times_minutes)
    variance = sum((t - mean_t) ** 2 for t in times_minutes) / len(times_minutes)
    std_minutes = variance ** 0.5

    if std_minutes > max_std:
        return True, f"wake time std dev {std_minutes:.0f} min over {len(times_minutes)} days (threshold: {max_std} min)"
    return False, ""


def scan_knowledge_triggers(knowledge, data_sources, sessions_by_date, target_date):
    """Scan all knowledge entries with triggers and generate insights.

    This is the automatic bridge between health_knowledge.json and the analysis
    engine. When /update-intel adds new entries with trigger fields, they
    automatically fire here without any code changes.

    Returns list of insight strings for entries whose triggers matched.
    """
    insights = []
    fired_ids = set()

    for kb_id, entry in knowledge.items():
        trigger = entry.get("trigger")
        if not trigger:
            continue

        # Skip entries already covered by hardcoded insights (dedup)
        if kb_id in _hardcoded_kb_ids:
            continue

        trigger_type = trigger.get("type", "simple")
        fired = False
        context = ""

        if trigger_type == "simple" or "tab" in trigger:
            fired, context = _eval_simple_trigger(
                trigger, data_sources, sessions_by_date, target_date)
        elif trigger_type == "compound":
            fired, context = _eval_compound_trigger(
                trigger, data_sources, sessions_by_date, target_date)
        elif trigger_type == "divergence":
            fired, context = _eval_divergence_trigger(
                trigger, data_sources, target_date)
        elif trigger_type == "variance":
            fired, context = _eval_variance_trigger(
                trigger, data_sources, target_date)

        if fired:
            fired_ids.add(kb_id)
            # Build insight from knowledge entry
            parts = [f"[{entry['domain']}] {context}. "]
            parts.append(entry["interpretation"][:200])
            if entry.get("cognitive_impact"):
                parts.append(f" Cognitive: {entry['cognitive_impact'][:150]}")
            if entry.get("recommendation"):
                parts.append(f" Action: {entry['recommendation'][:150]}")
            conf = entry.get("confidence", "Pending")
            parts.append(f" [{entry['citation']} -- {conf}]")
            insights.append("".join(parts))

    if fired_ids:
        print(f"  [knowledge] Dynamic triggers fired: {', '.join(sorted(fired_ids))}")

    return insights


# Registry of kb_ids used by hardcoded insights in the current analysis run.
# Populated by _kb_insight(), consumed by scan_knowledge_triggers() to avoid duplicates.
_hardcoded_kb_ids = set()


def _kb_insight(knowledge, kb_id, data_prefix, fallback):
    """Build an insight string from knowledge base entry, with fallback.

    Returns: data_prefix + cognitive_impact + citation, or fallback if kb_id not found.
    Entries with confidence="Pending" are used but flagged as not-yet-evaluated.
    """
    _hardcoded_kb_ids.add(kb_id)
    k = knowledge.get(kb_id)
    if not k:
        return fallback
    parts = [data_prefix]
    parts.append(k["interpretation"])
    parts.append(f"Cognitive impact: {k['cognitive_impact']}")
    if k.get("energy_impact"):
        parts.append(f"Energy: {k['energy_impact']}")
    citation = k['citation']
    if k.get("confidence") == "Pending":
        parts.append(f"[{citation} — pending evaluation]")
    else:
        parts.append(f"[{citation}]")
    return " ".join(parts)


def condense_sleep_analysis(sleep_analysis_text):
    """Condense the full sleep analysis from the Sleep tab into a brief insight.

    Fixed output order: Rating -> Bedtime -> Duration -> Deep/REM -> HRV -> Interpretation.
    Returns a single string suitable as the leading Key Insights bullet.
    """
    if not sleep_analysis_text or sleep_analysis_text == "Insufficient data for analysis":
        return None

    text = sleep_analysis_text.strip()

    # Extract verdict (first word before " - ")
    verdict = ""
    body = text
    if " - " in text:
        verdict = text.split(" - ", 1)[0].strip()
        body = text.split(" - ", 1)[1].strip()

    # Extract ACTION section
    action = ""
    if "ACTION:" in body:
        parts = body.split("ACTION:", 1)
        body = parts[0].strip().rstrip(".")
        action = parts[1].strip().rstrip(".")

    # Split body into sentences for metric extraction
    sentences = [s.strip() for s in body.split(". ") if s.strip()]

    # Extract metrics into fixed-order slots by pattern matching
    bedtime = ""
    duration = ""
    deep = ""
    rem = ""
    hrv = ""
    cycles = ""
    other = []

    for s in sentences:
        sl = s.lower()
        # Strip trailing interpretation after " - " for metric lines
        metric_short = s.split(" - ")[0].strip() if " - " in s else s
        if sl.startswith("bedtime"):
            bedtime = metric_short
        elif re.match(r'^\d+\.?\d*h\b', sl) or "total" in sl and ("h " in sl or "hr" in sl):
            duration = metric_short
        elif "severely short" in sl or "too short" in sl:
            duration = metric_short
        elif sl.startswith("deep") or "deep sleep" in sl[:20]:
            deep = metric_short
        elif sl.startswith("rem") or "rem " in sl[:10]:
            rem = metric_short
        elif "hrv" in sl[:15]:
            hrv = metric_short
        elif "sleep cycle" in sl or ("only" in sl[:8] and "cycle" in sl):
            cycles = metric_short
        else:
            other.append(metric_short)

    # Build output in fixed order: Rating | Bedtime | Duration | Deep/REM | HRV | Cycles -> Action
    parts = []
    if verdict:
        parts.append(f"Sleep Review: {verdict}")

    metrics = []
    if bedtime:
        metrics.append(bedtime)
    if duration:
        metrics.append(duration)
    if deep:
        metrics.append(deep)
    if rem:
        metrics.append(rem)
    if hrv:
        metrics.append(hrv)
    if cycles:
        metrics.append(cycles)

    if metrics:
        parts.append(". ".join(metrics))

    if action:
        first_action = action.split(". ")[0] if ". " in action else action
        parts.append(f"-> {first_action}")

    return " -- ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Profile-aware helpers (PHI-safe — never output condition names)
# ---------------------------------------------------------------------------

def _compute_stress_budget(baselines, profile):
    """Compute personalized stress budget based on profile sensitivity.

    Returns insight string if stress exceeds 70% of adjusted capacity, else None.
    """
    if not profile:
        return None
    stress_conditions = get_relevant_conditions(profile, "stress")
    if not stress_conditions:
        return None

    stress_data = baselines.get("stress", {})
    today_stress = stress_data.get("today")
    stress_mean = stress_data.get("mean")
    if today_stress is None or stress_mean is None:
        return None

    # Condition-adjusted ceiling (lower for stress-sensitive profiles)
    accommodations = get_accommodations(profile)
    adj = accommodations.get("analysis_adjustments", {})
    if adj.get("stress_sensitivity_high"):
        ceiling = stress_mean * 1.1  # tighter ceiling for sensitive profiles
    else:
        ceiling = stress_mean * 1.3  # default: 30% above baseline

    pct = (today_stress / ceiling) * 100 if ceiling > 0 else 0
    if pct > 70:
        return (f"Stress budget at {pct:.0f}% of your adjusted capacity. "
                f"Protect remaining recovery time -- avoid stacking cognitive demands.")
    return None


def analyze_good_day_factors(baselines, by_date_sleep, daily_log_by_date,
                             by_date_garmin, target_date, profile=None):
    """When cognition >= 7, analyze what was different in preceding 24-48h.

    Returns insight string describing what predicted the good day, or None.
    """
    if not profile:
        return None
    memory_conditions = get_relevant_conditions(profile, "cognition")
    if not memory_conditions:
        return None

    today_log = daily_log_by_date.get(str(target_date), {})
    cognition = _safe_float(today_log.get("Cognition (1-10)"))
    if cognition is None or cognition < 7:
        return None

    # Analyze preceding night
    sleep = by_date_sleep.get(str(target_date), {})
    garmin = by_date_garmin.get(str(target_date), {})
    factors = []

    deep = _safe_float(sleep.get("Deep Sleep (min)"))
    if deep is not None and deep > 55:
        factors.append(f"deep sleep {deep:.0f}min (above 55min threshold)")

    hrv = _safe_float(garmin.get("HRV (overnight avg)"))
    if hrv is None:
        hrv = _safe_float(sleep.get("Overnight HRV (ms)"))
    hrv_baseline = baselines.get("hrv", {}).get("mean")
    if hrv is not None and hrv_baseline and hrv > hrv_baseline * 1.1:
        factors.append(f"HRV {hrv:.0f}ms ({((hrv/hrv_baseline)-1)*100:.0f}% above baseline)")

    rhr = _safe_float(garmin.get("Resting HR"))
    rhr_baseline = baselines.get("rhr", {}).get("mean")
    if rhr is not None and rhr_baseline and rhr < rhr_baseline * 0.95:
        factors.append(f"RHR {rhr:.0f} ({((rhr_baseline-rhr)/rhr_baseline)*100:.0f}% below baseline)")

    bb = _safe_float(garmin.get("Body Battery (at wake)"))
    if bb is not None and bb >= 80:
        factors.append(f"body battery at wake {bb:.0f}")

    if factors:
        return (f"GOOD DAY FORENSICS (cognition {cognition:.0f}/10): "
                f"preceding night had {', '.join(factors)}. "
                f"These conditions predict your best cognitive days.")
    return None


def analyze_food_cognition_lag(nutrition_by_date, daily_log_by_date,
                               target_date, profile=None):
    """Check if specific food categories predict next-day cognition drops.

    Scans 30 days for sugar/refined carb keywords in meals vs next-day cognition.
    Returns insight string if consistent pattern found, else None.
    """
    if not profile:
        return None
    memory_conditions = get_relevant_conditions(profile, "cognition")
    if not memory_conditions:
        return None

    sugar_cog = []  # (has_sugar_bool, next_day_cognition)
    for offset in range(1, 31):
        d = target_date - timedelta(days=offset)
        d_str = str(d)
        next_d_str = str(d + timedelta(days=1))

        nut = nutrition_by_date.get(d_str, {})
        next_log = daily_log_by_date.get(next_d_str, {})
        cog = _safe_float(next_log.get("Cognition (1-10)"))
        if cog is None:
            continue

        # Check meal columns for sugar keywords
        meal_text = " ".join(
            str(nut.get(col, "")) for col in
            ["Breakfast", "Lunch", "Dinner", "Snacks"]
        ).lower()

        has_sugar = any(kw in meal_text for kw in SUGAR_KEYWORDS)
        sugar_cog.append((has_sugar, cog))

    if len(sugar_cog) < 10:
        return None

    sugar_days = [c for flag, c in sugar_cog if flag]
    clean_days = [c for flag, c in sugar_cog if not flag]
    if not sugar_days or not clean_days:
        return None

    sugar_avg = sum(sugar_days) / len(sugar_days)
    clean_avg = sum(clean_days) / len(clean_days)
    diff = clean_avg - sugar_avg

    if diff > 0.5:
        return (f"Food-cognition pattern: days after sugar/refined carbs, "
                f"your cognition averages {sugar_avg:.1f}/10 "
                f"vs {clean_avg:.1f}/10 on clean days "
                f"({diff:.1f} point difference, n={len(sugar_cog)}).")
    return None


def generate_if_then_rules(baselines, by_date_sleep, daily_log_by_date,
                            by_date_garmin, target_date, profile=None):
    """Build personalized decision rules from historical correlations.

    When today matches a pattern (e.g. HRV suppressed + deep sleep < 50min),
    validates against 60-day history to compute predicted cognition.
    Returns insight string if pattern matches, else None.
    """
    if not profile:
        return None
    memory_conditions = get_relevant_conditions(profile, "cognition")
    if not memory_conditions:
        return None

    hrv_z = baselines.get("hrv", {}).get("z")
    today_sleep = by_date_sleep.get(str(target_date), {})
    deep_min = _safe_float(today_sleep.get("Deep Sleep (min)"))

    # Rule: HRV below baseline AND deep sleep low -> predict bad cognition day
    if hrv_z is None or hrv_z >= -0.5 or deep_min is None or deep_min >= 50:
        return None

    # Validate against historical data
    hrv_mean = baselines.get("hrv", {}).get("mean")
    if not hrv_mean:
        return None

    bad_day_cogs = []
    for offset in range(1, 61):
        d = target_date - timedelta(days=offset)
        d_str = str(d)

        sleep = by_date_sleep.get(d_str, {})
        garmin = by_date_garmin.get(d_str, {})
        log = daily_log_by_date.get(d_str, {})

        d_hrv = _safe_float(garmin.get("HRV (overnight avg)"))
        if d_hrv is None:
            d_hrv = _safe_float(sleep.get("Overnight HRV (ms)"))
        d_deep = _safe_float(sleep.get("Deep Sleep (min)"))
        d_cog = _safe_float(log.get("Cognition (1-10)"))

        if d_hrv and d_deep and d_cog:
            if d_hrv < hrv_mean * 0.9 and d_deep < 50:
                bad_day_cogs.append(d_cog)

    if len(bad_day_cogs) >= 5:
        avg_cog = sum(bad_day_cogs) / len(bad_day_cogs)
        return (f"PATTERN MATCH: When HRV is suppressed AND deep sleep < 50min, "
                f"your cognition averages {avg_cog:.1f}/10 (n={len(bad_day_cogs)}). "
                f"Today matches this pattern. Defer complex tasks, focus on "
                f"administrative work.")
    return None


# ---------------------------------------------------------------------------
# Profile-aware insight reframing (PHI-safe — never outputs condition names)
# ---------------------------------------------------------------------------

# Domain keyword -> condition-context suffix mapping
# Keys are substrings to match in insight text; values are (tracking_domain, suffix)
_REFRAME_RULES = [
    (["hrv", "autonomic", "heart rate variability"],
     "hrv",
     "With your neurological profile, HRV suppression may reflect neuroinflammatory activity. Monitor for cognitive symptoms today."),
    (["deep sleep"],
     "deep_sleep",
     "Reduced deep sleep directly impacts your primary concern: memory consolidation."),
    (["rem"],
     "rem_sleep",
     "REM below baseline affects emotional regulation and procedural memory processing."),
    (["stress level", "stress budget"],
     "stress",
     "With your stress-sensitive profile, protect remaining recovery time."),
    (["zone 4", "zone 5", "high-intensity", "training load"],
     "training",
     "Given your cardiac profile, sustained high-intensity carries elevated risk."),
    (["cognitive", "executive function", "attention"],
     "cognition",
     "Executive function factors compounding -- expect increased difficulty with planning and working memory today."),
]


def _reframe_insights_with_profile(insights, profile):
    """Post-process insights to add condition-aware context.

    Never outputs condition names (PHI safety). Uses generic phrases like
    'your neurological profile' instead.

    Returns new list of insights with condition context appended where relevant.
    """
    if not profile:
        return insights

    reframed = []
    for insight in insights:
        # Skip reframing on condensed sleep review — it's already a summary
        if insight.upper().startswith("SLEEP REVIEW:") or insight.upper().startswith("LAST NIGHT:"):
            reframed.append(insight)
            continue
        insight_lower = insight.lower()
        suffix_added = False
        for keywords, domain, suffix in _REFRAME_RULES:
            if any(kw in insight_lower for kw in keywords):
                # Only add suffix if profile has relevant conditions for this domain
                relevant = get_relevant_conditions(profile, domain)
                if relevant and not suffix_added:
                    reframed.append(f"{insight} {suffix}")
                    suffix_added = True
                    break
        if not suffix_added:
            reframed.append(insight)
    return reframed


def generate_insights(baselines, sleep_debt, sleep_trend, acwr, acwr_status,
                      note_flags, daily_log_by_date, by_date_garmin,
                      by_date_sleep, sessions_by_date, target_date,
                      knowledge=None, sleep_analysis_text=None,
                      deep_trend=None, rem_trend=None, profile=None,
                      nutrition_by_date=None):
    """Generate priority-ordered insight text based on all computed data.

    Uses health_knowledge.json entries for scientifically-grounded cognitive/energy
    framing when available, with hardcoded fallbacks for backward compatibility.

    Returns list of insight strings, ordered by severity/relevance.
    """
    if knowledge is None:
        knowledge = {}
    if nutrition_by_date is None:
        nutrition_by_date = {}
    insights = []

    # --- Outlier warnings (data quality flags) ---
    METRIC_DISPLAY = {"hrv": "HRV", "rhr": "Resting HR", "sleep_score": "Sleep Score",
                      "sleep_duration": "Sleep Duration", "body_battery": "Body Battery",
                      "steps": "Steps", "stress": "Stress"}
    for key, info in baselines.items():
        if info.get("outliers"):
            name = METRIC_DISPLAY.get(key, key)
            vals = ", ".join(f"{v:.0f}" for v in info["outliers"])
            insights.append(
                f"Note: {name} has extreme value(s) ({vals}) in the baseline window "
                f"(>3 SD from mean). This may affect baseline accuracy."
            )

    # --- Last night's sleep analysis (condensed from Sleep tab) ---
    condensed = condense_sleep_analysis(sleep_analysis_text)
    if condensed:
        insights.append(condensed)

    # --- Sleep debt ---
    if sleep_debt is not None and sleep_debt > 0.75:
        if sleep_debt > 1.5:
            insights.append(_kb_insight(
                knowledge, "sleep_debt_major",
                f"CUMULATIVE SLEEP DEBT: {sleep_debt:.1f}h below your baseline over the past 5 days. ",
                f"CUMULATIVE SLEEP DEBT: {sleep_debt:.1f}h below your baseline over the past 5 days. "
                f"Research shows this level of restriction impairs reaction time, word recall, and "
                f"executive function comparably to partial sleep deprivation (Van Dongen et al. 2003). "
                f"You may experience difficulty finding words, poor focus, and increased sugar/carb cravings."
            ))
        else:
            insights.append(_kb_insight(
                knowledge, "sleep_debt_mild",
                f"Mild sleep debt: {sleep_debt:.1f}h below baseline over 5 days. ",
                f"Mild sleep debt: {sleep_debt:.1f}h below baseline over 5 days. "
                f"Not yet critical, but if this trend continues, cognitive effects compound "
                f"non-linearly -- day 5+ of restriction shows accelerating impairment."
            ))

    # --- HRV status ---
    hrv_data = baselines.get("hrv", {})
    if hrv_data.get("z") is not None:
        z = hrv_data["z"]
        hrv_trend = hrv_data.get("trend")  # "declining", "recovering", "stable", or None
        if z < -1.5:
            # Trend-aware messaging for significantly low HRV
            if hrv_trend == "declining":
                trend_msg = (
                    "5-day trend is declining -- this pattern suggests overtraining or accumulated fatigue. "
                    "Prioritize rest and active recovery."
                )
            elif hrv_trend == "recovering":
                trend_msg = (
                    "However, 5-day trend shows recovery in progress. "
                    "Maintain current approach -- HRV is rebounding."
                )
            else:
                trend_msg = (
                    "Your autonomic nervous system is under strain. "
                    "Common causes: accumulated training load, poor sleep, illness onset, or high stress."
                )
            insights.append(_kb_insight(
                knowledge, "hrv_critical_low",
                f"HRV significantly below baseline (z={z:+.1f}, today: {hrv_data['today']:.0f}ms vs "
                f"avg: {hrv_data['mean']:.0f}ms). ",
                f"HRV significantly below baseline (z={z:+.1f}, today: {hrv_data['today']:.0f}ms vs "
                f"avg: {hrv_data['mean']:.0f}ms). {trend_msg}"
            ))
        elif z < -1.0:
            if hrv_trend == "declining":
                trend_msg = (
                    "5-day trend is declining -- if this continues, consider reducing training intensity."
                )
            elif hrv_trend == "recovering":
                trend_msg = (
                    "5-day trend shows recovery underway -- current approach is working."
                )
            else:
                trend_msg = (
                    "Recovery may be incomplete. "
                    "Monitor over the next 1-2 days -- if HRV doesn't rebound, consider reducing training intensity."
                )
            insights.append(_kb_insight(
                knowledge, "hrv_below_baseline",
                f"HRV below baseline (z={z:+.1f}). ",
                f"HRV below baseline (z={z:+.1f}). {trend_msg}"
            ))
        elif z > 1.5:
            insights.append(_kb_insight(
                knowledge, "hrv_above_baseline",
                f"HRV well above baseline (z={z:+.1f}, {hrv_data['today']:.0f}ms). ",
                f"HRV well above baseline (z={z:+.1f}, {hrv_data['today']:.0f}ms). "
                f"Strong parasympathetic recovery -- your body is well-recovered and can handle higher intensity today."
            ))
        elif z < -0.5 and hrv_trend == "declining":
            # Mild dip but declining trend -- early warning
            insights.append(
                f"HRV slightly below baseline (z={z:+.1f}) with a declining 5-day trend. "
                f"Not yet concerning, but watch for continued decline over the next 2 days."
            )

    # --- RHR status ---
    rhr_data = baselines.get("rhr", {})
    if rhr_data.get("z") is not None and rhr_data["z"] > 1.5:
        insights.append(_kb_insight(
            knowledge, "rhr_elevated",
            f"Resting HR elevated (z={rhr_data['z']:+.1f}, today: {rhr_data['today']:.0f}bpm vs "
            f"avg: {rhr_data['mean']:.0f}bpm). ",
            f"Resting HR elevated (z={rhr_data['z']:+.1f}, today: {rhr_data['today']:.0f}bpm vs "
            f"avg: {rhr_data['mean']:.0f}bpm). Combined with HRV trends, this may indicate "
            f"accumulated fatigue, dehydration, or early illness."
        ))

    # --- Training load ---
    if acwr is not None:
        if acwr > 1.5:
            insights.append(_kb_insight(
                knowledge, "training_load_spike",
                f"TRAINING LOAD SPIKE: {acwr_status} ",
                f"TRAINING LOAD SPIKE: {acwr_status} "
                f"Research (Gabbett 2016) shows ACWR >1.5 significantly increases "
                f"injury and illness risk. Prioritize active recovery this week."
            ))
        elif acwr > ACWR_HIGH:
            insights.append(acwr_status)

    # --- HRV suppression after workout (check if HRV still suppressed >72h post-workout) ---
    hrv_z = hrv_data.get("z")
    if hrv_z is not None and hrv_z < -0.5:
        for offset in range(1, 4):
            d = str(target_date - timedelta(days=offset))
            sessions = sessions_by_date.get(d, [])
            for s in sessions:
                te = _safe_float(s.get("Anaerobic TE (0-5)"))
                dur = _safe_float(s.get("Duration (min)"))
                if (te and te >= 3.5) or (dur and dur >= 60):
                    if offset >= 3:
                        insights.append(_kb_insight(
                            knowledge, "hrv_suppressed_post_workout",
                            f"HRV still suppressed {offset} days after heavy session on {d} "
                            f"({s.get('Activity Name', 'workout')}). ",
                            f"HRV still suppressed {offset} days after heavy session on {d} "
                            f"({s.get('Activity Name', 'workout')}). "
                            f"Recovery typically takes 48-72h for high-intensity work; "
                            f"extended suppression suggests incomplete recovery."
                        ))
                    break

    # --- Diet/behavior flags ---
    flag_kb_map = {
        "alcohol": "alcohol_sleep_disruption",
        "sugar/refined_carbs": "sugar_sleep_disruption",
        "late_meal": "late_meal_thermoregulation",
        "late_caffeine": "late_caffeine_sleep",
    }
    flag_fallbacks = {
        "alcohol": (
            "Research (Ebrahim et al. 2013) shows alcohol increases initial deep sleep "
            "but suppresses REM in the second half of the night, fragmenting sleep "
            "architecture. HRV may remain suppressed the following morning."
        ),
        "sugar/refined_carbs": (
            "High glycemic load is associated with less slow-wave (deep) sleep and "
            "more fragmented sleep (St-Onge et al. 2016). Effect is modest but "
            "compounds with other sleep disruptors."
        ),
        "late_meal": (
            "Eating within 2-3 hours of bedtime can elevate core body temperature and "
            "delay sleep onset. The thermoregulation disruption can reduce deep sleep "
            "in the first half of the night."
        ),
        "late_caffeine": (
            "Caffeine has a half-life of 5-7 hours (Huberman). Afternoon/evening caffeine "
            "can reduce total sleep time by up to 1 hour and decrease deep sleep even "
            "when you fall asleep on time."
        ),
    }

    for flag_date, flag_type, matched in note_flags:
        days_ago = (target_date - date.fromisoformat(flag_date)).days
        time_ref = "yesterday" if days_ago == 1 else f"{days_ago} days ago" if days_ago > 0 else "today"

        kb_id = flag_kb_map.get(flag_type)
        if flag_type == "alcohol":
            prefix = f"Alcohol noted {time_ref} ({', '.join(matched)}). "
        elif flag_type == "sugar/refined_carbs":
            prefix = f"High sugar/refined carbs noted {time_ref} ({', '.join(matched)}). "
        elif flag_type == "late_meal":
            prefix = f"Late meal noted {time_ref}. "
        elif flag_type == "late_caffeine":
            prefix = f"Late caffeine noted {time_ref}. "
        else:
            continue

        fallback_text = prefix + flag_fallbacks.get(flag_type, "")
        if kb_id:
            insights.append(_kb_insight(knowledge, kb_id, prefix, fallback_text))
        else:
            insights.append(fallback_text)

    # --- Deep sleep and REM assessment (new: cognitive-relevant sleep architecture) ---
    today_sleep = by_date_sleep.get(str(target_date), {})
    deep_pct = _safe_float(today_sleep.get("Deep %"))
    rem_pct = _safe_float(today_sleep.get("REM %"))
    if deep_pct is not None and deep_pct < 15:
        insights.append(_kb_insight(
            knowledge, "deep_sleep_deficit",
            f"Deep sleep was only {deep_pct:.0f}% last night (target: 20-25%). ",
            f"Deep sleep was only {deep_pct:.0f}% last night. Reduced deep sleep impairs "
            f"declarative memory consolidation and physical recovery."
        ))
    if rem_pct is not None and rem_pct < 15:
        insights.append(_kb_insight(
            knowledge, "rem_sleep_deficit",
            f"REM sleep was only {rem_pct:.0f}% last night (target: 20-25%). ",
            f"REM sleep was only {rem_pct:.0f}% last night. Reduced REM impairs "
            f"emotional regulation and procedural memory consolidation."
        ))

    # --- Deep/REM 3-night trends (catches slow architectural degradation) ---
    if deep_trend == "declining" and deep_pct is not None and deep_pct < 20:
        insights.append(_kb_insight(
            knowledge, "deep_sleep_deficit",
            f"Deep sleep trending down over last 3 nights (latest: {deep_pct:.0f}%). ",
            f"Deep sleep has been declining over 3 nights (latest: {deep_pct:.0f}%). "
            f"Sustained deep sleep decline impairs declarative memory consolidation "
            f"and glymphatic clearance. Avoid alcohol, keep room cool (18-19C)."
        ))
    if rem_trend == "declining" and rem_pct is not None and rem_pct < 20:
        insights.append(_kb_insight(
            knowledge, "rem_sleep_deficit",
            f"REM sleep trending down over last 3 nights (latest: {rem_pct:.0f}%). ",
            f"REM sleep has been declining over 3 nights (latest: {rem_pct:.0f}%). "
            f"Sustained REM decline impairs emotional regulation and procedural memory. "
            f"Check for late caffeine, alcohol, or truncated sleep from late bedtimes."
        ))

    # --- Sleep trend ---
    if sleep_trend == "declining":
        sleep_score_data = baselines.get("sleep_score", {})
        if sleep_score_data.get("z") is not None and sleep_score_data["z"] < -0.5:
            insights.append(_kb_insight(
                knowledge, "sleep_trend_declining",
                "Sleep quality has been declining over the last 3 nights. ",
                "Sleep quality has been declining over the last 3 nights. "
                "If this continues, expect compounding cognitive effects by day 4-5 "
                "(Van Dongen cumulative restriction model)."
            ))

    # --- Habit patterns ---
    habit_totals = []
    screen_broken = 0
    bedtime_broken = 0
    for offset in range(0, 3):
        d = str(target_date - timedelta(days=offset))
        dl = daily_log_by_date.get(d, {})
        ht = _safe_float(dl.get("Habits Total (0-7)"))
        if ht is not None:
            habit_totals.append(ht)
        if dl.get("No Screens Before Bed") in ("FALSE", "0", ""):
            screen_broken += 1
        if dl.get("Bed at 10 PM") in ("FALSE", "0", ""):
            bedtime_broken += 1

    if habit_totals and sum(habit_totals) / len(habit_totals) >= 6:
        avg = sum(habit_totals) / len(habit_totals)
        insights.append(_kb_insight(
            knowledge, "habit_consistency_positive",
            f"Strong habit consistency ({avg:.1f}/7 avg over last {len(habit_totals)} days). ",
            f"Strong habit consistency ({avg:.1f}/7 avg over last {len(habit_totals)} days). "
            f"Research on habit stacking shows this level of consistency builds automaticity "
            f"within 2-3 weeks."
        ))
    elif screen_broken >= 2:
        insights.append(_kb_insight(
            knowledge, "screen_time_before_bed",
            f"Screen time before bed broken {screen_broken} of last 3 days. ",
            f"Screen time before bed broken {screen_broken} of last 3 days. "
            f"Blue light suppresses melatonin onset by 30-60 minutes (Huberman). "
            f"This may be contributing to any sleep onset delay or reduced deep sleep."
        ))
    if bedtime_broken >= 3:
        insights.append(_kb_insight(
            knowledge, "bedtime_irregularity",
            "Bedtime target missed 3 consecutive days. ",
            "Bedtime target missed 3 consecutive days. Circadian rhythm relies on "
            "consistent sleep/wake timing (Walker). Irregular bedtimes reduce sleep "
            "efficiency and can shift your circadian clock."
        ))

    # --- Extended individual habit analysis ---
    # Check each habit over last 3 days for patterns beyond screens/bedtime
    habit_check = {
        "Wake at 9:30 AM":          ("wake_consistency", "wake-up time"),
        "No Morning Screens":       ("morning_screen_free", "screen-free mornings"),
        "Creatine & Hydrate":       ("creatine_hydrate", "creatine & hydration"),
        "20 Min Walk + Breathing":  ("morning_walk", "morning walk/breathing"),
        "Physical Activity":        ("physical_activity", "physical activity"),
    }
    for habit_col, (kb_key, label_text) in habit_check.items():
        missed = 0
        total = 0
        for offset in range(0, 3):
            d = str(target_date - timedelta(days=offset))
            dl = daily_log_by_date.get(d, {})
            val = dl.get(habit_col, "")
            if val.upper() in ("TRUE", "FALSE"):
                total += 1
                if val.upper() == "FALSE":
                    missed += 1
        if total >= 2 and missed >= 2:
            insights.append(_kb_insight(
                knowledge, kb_key,
                f"{label_text.capitalize()} missed {missed}/{total} recent days. ",
                f"{label_text.capitalize()} missed {missed}/{total} recent days. "
                f"Consistency with this habit may be affecting your recovery and readiness."
            ))

    # --- Calorie deficit flagging ---
    for offset in range(0, 2):
        d = str(target_date - timedelta(days=offset))
        nut = nutrition_by_date.get(d, {})
        cal_balance = _safe_float(nut.get("Calorie Balance"))
        if cal_balance is not None and cal_balance < -500:
            insights.append(_kb_insight(
                knowledge, "calorie_deficit",
                f"Large calorie deficit on {d} ({cal_balance:+.0f} kcal). ",
                f"Large calorie deficit on {d} ({cal_balance:+.0f} kcal). "
                f"Deficits >500 kcal can impair next-day energy, cognitive function, "
                f"and recovery. Consider whether this was intentional."
            ))
            break  # Only flag once

    # --- Low protein flagging ---
    for offset in range(0, 2):
        d = str(target_date - timedelta(days=offset))
        nut = nutrition_by_date.get(d, {})
        protein = _safe_float(nut.get("Protein (g)"))
        if protein is not None and protein < 100:
            insights.append(_kb_insight(
                knowledge, "low_protein",
                f"Low protein intake on {d} ({protein:.0f}g). ",
                f"Low protein intake on {d} ({protein:.0f}g). "
                f"Protein below 100g may impair muscle recovery and sleep quality "
                f"(tryptophan pathway). Aim for 1.6-2.2g/kg bodyweight."
            ))
            break  # Only flag once

    # --- Low hydration flagging ---
    for offset in range(0, 2):
        d = str(target_date - timedelta(days=offset))
        nut = nutrition_by_date.get(d, {})
        water = _safe_float(nut.get("Water (L)"))
        if water is not None and water < 2.0:
            insights.append(_kb_insight(
                knowledge, "low_hydration",
                f"Low water intake on {d} ({water:.1f}L). ",
                f"Low water intake on {d} ({water:.1f}L). "
                f"Even mild dehydration (1-2%) reduces HRV by 5-15% and impairs "
                f"cognitive performance. Aim for 2.5-3.5L daily."
            ))
            break  # Only flag once

    # --- Stress ---
    stress_data = baselines.get("stress", {})
    if stress_data.get("z") is not None and stress_data["z"] > 1.0:
        insights.append(_kb_insight(
            knowledge, "stress_elevated",
            f"Garmin stress level elevated (z={stress_data['z']:+.1f}, today: "
            f"{stress_data['today']:.0f} vs avg: {stress_data['mean']:.0f}). ",
            f"Garmin stress level elevated (z={stress_data['z']:+.1f}, today: "
            f"{stress_data['today']:.0f} vs avg: {stress_data['mean']:.0f}). "
            f"Sustained high stress activates the sympathetic nervous system, "
            f"suppressing HRV and impairing sleep quality."
        ))

    # --- Profile-aware insights (Steps 3-5, 6, 11) ---
    if profile:
        # Step 3: Reframe existing insights with condition context
        insights = _reframe_insights_with_profile(insights, profile)

        # Step 4: Sleep architecture -> memory pipeline
        memory_conditions = get_relevant_conditions(profile, "deep_sleep")
        if memory_conditions:
            today_sleep = by_date_sleep.get(str(target_date), {})
            deep_min = _safe_float(today_sleep.get("Deep Sleep (min)"))
            rem_min = _safe_float(today_sleep.get("REM (min)"))
            if deep_min is not None and deep_min < 50:
                insights.append(
                    f"Deep sleep {deep_min:.0f}min (below 50min threshold). "
                    f"Your primary concern is memory consolidation, which requires "
                    f"sustained deep sleep. Tonight: prioritize earlier bedtime."
                )
            if rem_min is not None and rem_min < 60:
                insights.append(
                    f"REM {rem_min:.0f}min -- emotional regulation and procedural "
                    f"memory processing reduced. This directly impacts your cognitive "
                    f"recovery pipeline."
                )

        # Step 5: ARVC exercise guardrails
        cardiac_conditions = get_relevant_conditions(profile, "training")
        arvc_active = any(c.get("id") == "cond_008" for c in cardiac_conditions)
        if arvc_active:
            today_sessions = sessions_by_date.get(str(target_date), [])
            if isinstance(today_sessions, dict):
                today_sessions = [today_sessions]
            for s in today_sessions:
                z4 = _safe_float(s.get("Zone 4 (min)")) or 0
                z5 = _safe_float(s.get("Zone 5 (min)")) or 0
                max_hr = _safe_float(s.get("Max HR"))
                if z4 + z5 > 5:
                    insights.append(
                        f"Today's workout included {z4+z5:.0f}min in Zone 4-5. "
                        f"With your cardiac profile, sustained high-intensity "
                        f"carries elevated risk. Consider Zone 2-3 focus."
                    )
                if max_hr and max_hr > 170:
                    insights.append(
                        f"Max HR reached {max_hr:.0f} BPM today. Monitor for "
                        f"exercise-induced palpitations per your cardiac management plan."
                    )

        # Step 6: Stress budget
        stress_budget_insight = _compute_stress_budget(baselines, profile)
        if stress_budget_insight:
            insights.append(stress_budget_insight)

        # Step 11: Biomarker staleness alerts (high urgency only)
        stale_warnings = check_biomarker_staleness(profile)
        relevant_stale = [w for w in stale_warnings
                          if w["urgency"] == "high"
                          and w["category"] in ("cardiac", "antibodies", "brain_imaging")]
        if relevant_stale:
            categories = sorted(set(w["category"] for w in relevant_stale))
            oldest = max(w["months_old"] for w in relevant_stale)
            insights.append(
                f"Note: {len(relevant_stale)} biomarker(s) in {', '.join(categories)} "
                f"past recommended retest interval (oldest: {oldest:.0f} months). "
                f"Consider follow-up testing."
            )

        # Step 9: Good Day Forensics
        good_day = analyze_good_day_factors(
            baselines, by_date_sleep, daily_log_by_date,
            by_date_garmin, target_date, profile
        )
        if good_day:
            insights.append(good_day)

        # Step 14: Food -> brain fog lag analysis
        food_lag = analyze_food_cognition_lag(
            nutrition_by_date, daily_log_by_date, target_date, profile
        )
        if food_lag:
            insights.append(food_lag)

        # Step 15: If-Then decision rules
        if_then = generate_if_then_rules(
            baselines, by_date_sleep, daily_log_by_date,
            by_date_garmin, target_date, profile
        )
        if if_then:
            insights.append(if_then)

    return insights


# ---------------------------------------------------------------------------
# Recommendation Generation
# ---------------------------------------------------------------------------

def generate_recommendations(score, label, sleep_debt, acwr, note_flags,
                             baselines, target_date, knowledge=None,
                             profile=None):
    """Generate actionable recommendations based on readiness state.

    Uses knowledge base for scientifically-grounded cognitive/energy framing.
    Returns list of recommendation strings.
    """
    if knowledge is None:
        knowledge = {}
    recs = []
    day_name = target_date.strftime("%A")

    if label in ("Poor", "Low"):
        recs.append(
            f"Today ({day_name}): prioritize rest and recovery. Light walking or NSDR "
            f"(non-sleep deep rest) only -- avoid high-intensity training. "
            f"Cognitive capacity is likely reduced; defer important decisions if possible."
        )
        recs.append(
            "Plan to be off screens by 8 PM and in bed by 9-9:30 PM tonight to "
            "begin recovering sleep debt."
        )
        if sleep_debt and sleep_debt > 1.0:
            k = knowledge.get("sleep_debt_major")
            if k:
                recs.append(
                    f"You have {sleep_debt:.1f}h of accumulated sleep debt. "
                    f"{k['recommendation']} [{k['citation']}]"
                )
            else:
                recs.append(
                    f"You have {sleep_debt:.1f}h of accumulated sleep debt. "
                    f"Aim for 8.5-9h sleep tonight. Full recovery from sustained restriction "
                    f"can take 2-3 weeks of consistent sleep (Van Dongen et al. 2003)."
                )
    elif label == "Fair":
        recs.append(
            f"Today ({day_name}): moderate activity is fine, but avoid maximal efforts. "
            f"Monitor how you feel mid-workout -- if perceived effort exceeds expected, "
            f"scale back. Cognitive endurance may be reduced; plan demanding mental work "
            f"for your peak hours."
        )
        if sleep_debt and sleep_debt > 0.5:
            recs.append(
                "Prioritize an earlier bedtime tonight -- even 30 minutes earlier helps "
                "accumulate recovery and restore cognitive function."
            )
    elif label in ("Good", "Optimal"):
        k = knowledge.get("hrv_above_baseline")
        cognitive_note = k["cognitive_impact"] if k else (
            "Good day for complex cognitive work, learning, or skill acquisition."
        )
        recs.append(
            f"Today ({day_name}): you're well-recovered. This is a good day for high-intensity "
            f"training, skill work, or challenging cognitive tasks. {cognitive_note}"
        )
        if acwr is not None and acwr < ACWR_LOW:
            recs.append(
                "Your training load is below your recent capacity. Consider increasing "
                "intensity or volume if goals support it."
            )

    # Diet-specific recommendations
    alcohol_flags = [f for f in note_flags if f[1] == "alcohol" and f[0] == str(target_date)]
    if alcohol_flags:
        k = knowledge.get("alcohol_sleep_disruption")
        if k:
            recs.append(f"If drinking tonight: {k['recommendation']}")
        else:
            recs.append(
                "If drinking tonight: stop 3-4 hours before bed to minimize REM suppression. "
                "Hydrate before sleep (alcohol is a diuretic and dehydration further fragments sleep)."
            )

    # Training load warnings
    if acwr is not None and acwr > ACWR_HIGH:
        k = knowledge.get("training_load_spike")
        if k:
            recs.append(k["recommendation"])
        else:
            recs.append(
                "Training load is elevated this week. Consider replacing one planned session "
                "with active recovery (Zone 1-2 cardio, mobility work, or yoga)."
            )

    # HRV-specific
    hrv_z = baselines.get("hrv", {}).get("z")
    if hrv_z is not None and hrv_z < -1.0:
        k = knowledge.get("nsdr_recovery")
        if k:
            recs.append(
                f"HRV is significantly suppressed. {k['recommendation']} "
                f"{k['cognitive_impact']} [{k['citation']}]"
            )
        else:
            recs.append(
                "HRV is significantly suppressed. Consider: 10-20 min NSDR/yoga nidra "
                "(shown to restore dopamine and reduce cortisol -- Huberman), extend sleep "
                "by 30-60 min, and avoid alcohol/caffeine today."
            )

    # --- Profile-aware filtering (3 layers) ---
    if profile:
        accommodations = get_accommodations(profile)

        # Layer 1: Contraindication filter — remove recs matching blocked keywords
        contraindications = accommodations.get("contraindications", [])
        if contraindications:
            filtered = []
            for rec in recs:
                rec_lower = rec.lower()
                blocked = any(c.lower() in rec_lower for c in contraindications)
                if not blocked:
                    filtered.append(rec)
            recs = filtered if filtered else recs[:1]  # never return empty

        # Layer 2: Treatment non-response filter — suppress recs for already-failed treatments
        failed_treatments = set()
        for note in profile.get("provider_notes", []):
            summary = (note.get("summary", "") + " ".join(note.get("action_items", []))).lower()
            if "no improvement" in summary or "no cognitive effect" in summary or "no cognitive improvement" in summary:
                for term in ["nad+", "nad ", "nac", "glutathione", "hbot",
                             "hyperbaric", "cryotherapy", "niagen"]:
                    if term in summary:
                        failed_treatments.add(term.strip())
        if failed_treatments:
            filtered = []
            for rec in recs:
                rec_lower = rec.lower()
                blocked = any(ft in rec_lower for ft in failed_treatments)
                if not blocked:
                    filtered.append(rec)
            recs = filtered if filtered else recs[:1]

        # Layer 3: Accommodation formatting — numbered steps, bold verbs, cap count
        if recs and (accommodations.get("output_format") or accommodations.get("analysis_adjustments")):
            recs_text = "\n".join(f"- {r}" for r in recs)
            recs_text = format_recommendation(recs_text, accommodations)
            # Split back into list, preserving formatted lines
            recs = [line for line in recs_text.split("\n") if line.strip()]

    return recs


# ---------------------------------------------------------------------------
# Cognitive & Energy Assessment
# ---------------------------------------------------------------------------

def assess_cognitive_state(baselines, sleep_debt, note_flags, by_date_sleep,
                           sessions_by_date, target_date, knowledge=None,
                           profile=None):
    """Build a concise cognitive/energy summary.

    Format: "{Level}. {top factors}." — one sentence, scannable.
    Full mechanism details available on-demand via /health-insight.
    """
    if knowledge is None:
        knowledge = {}

    factors = []  # (severity 0-3, short_factor_text)

    # --- Sleep debt (7-day lookback) ---
    if sleep_debt is not None:
        if sleep_debt > 1.5:
            factors.append((3, f"sleep debt {sleep_debt:.1f}h"))
        elif sleep_debt > 0.75:
            factors.append((2, f"mild sleep debt {sleep_debt:.1f}h"))

    # --- HRV trend (5-day) ---
    hrv_data = baselines.get("hrv", {})
    hrv_z = hrv_data.get("z")
    hrv_trend = hrv_data.get("trend")
    if hrv_z is not None:
        if hrv_z < -1.5:
            trend_tag = ""
            if hrv_trend == "declining":
                trend_tag = ", declining"
            elif hrv_trend == "recovering":
                trend_tag = ", recovering"
            factors.append((3, f"HRV suppressed{trend_tag}"))
        elif hrv_z < -1.0:
            trend_tag = ""
            if hrv_trend == "declining":
                trend_tag = ", declining"
            elif hrv_trend == "recovering":
                trend_tag = ", recovering"
            factors.append((2, f"HRV below baseline{trend_tag}"))
        elif hrv_z > 1.5:
            factors.append((-1, "HRV well above baseline"))

    # --- RHR elevated ---
    rhr_z = baselines.get("rhr", {}).get("z")
    if rhr_z is not None and rhr_z > 1.5:
        factors.append((2, "RHR elevated"))

    # --- Stress (14-day trend) ---
    stress_z = baselines.get("stress", {}).get("z")
    if stress_z is not None and stress_z > 1.0:
        factors.append((2, "stress elevated"))

    # --- Sleep architecture (3-day lookback) ---
    today_sleep = by_date_sleep.get(str(target_date), {})
    deep_pct = _safe_float(today_sleep.get("Deep %"))
    rem_pct = _safe_float(today_sleep.get("REM %"))
    if deep_pct is not None and deep_pct < 15:
        factors.append((2, f"low deep sleep {deep_pct:.0f}%"))
    if rem_pct is not None and rem_pct < 15:
        factors.append((2, f"low REM {rem_pct:.0f}%"))

    # --- Alcohol (3-day lookback) ---
    for flag_date, flag_type, _ in note_flags:
        days_ago = (target_date - date.fromisoformat(flag_date)).days
        if flag_type == "alcohol":
            if days_ago == 0:
                factors.append((2, "alcohol today"))
            elif days_ago <= 2:
                factors.append((1, f"alcohol {days_ago}d ago"))
        elif flag_type == "late_caffeine" and days_ago == 0:
            factors.append((1, "late caffeine"))

    # --- Heavy training (3-day lookback) ---
    for offset in range(1, 4):
        d = str(target_date - timedelta(days=offset))
        sessions = sessions_by_date.get(d, [])
        for s in sessions:
            te = _safe_float(s.get("Anaerobic TE (0-5)"))
            dur = _safe_float(s.get("Duration (min)"))
            if (te and te >= 3.5) or (dur and dur >= 60):
                if hrv_z is not None and hrv_z < -0.5:
                    factors.append((1, f"heavy session {offset}d ago + HRV suppressed"))
                break

    # --- Body battery trend (5-day) ---
    bb_data = baselines.get("body_battery", {})
    bb_today = bb_data.get("today")
    if bb_today is not None and bb_today < 40:
        factors.append((2, f"body battery low ({bb_today:.0f})"))

    # --- Profile-aware cognitive factors ---
    if profile:
        neuro_conditions = get_relevant_conditions(profile, "cognition")
        negative_count = len([s for s, _ in factors if s >= 2])
        if neuro_conditions and negative_count >= 2:
            factors.append((3, "compounding stressors on sensitive profile"))

        accommodations = get_accommodations(profile)
        adj = accommodations.get("analysis_adjustments", {})
        cog_adj = adj.get("cognitive_baseline_adjustment", 0)
        ef_adj = adj.get("executive_function_baseline_adjustment", 0)
        total_adj = cog_adj + ef_adj
        if total_adj != 0:
            factors.append((1, f"profile baseline adj {total_adj:+.1f}"))

    # --- Build assessment ---
    if not factors:
        return "Baseline capacity expected."

    negative = [(sev, txt) for sev, txt in factors if sev > 0]
    positive = [(sev, txt) for sev, txt in factors if sev < 0]

    negative.sort(key=lambda x: x[0], reverse=True)

    if not negative and positive:
        pos_text = ", ".join(txt for _, txt in positive)
        return f"Above baseline. {pos_text}."

    max_severity = max(sev for sev, _ in negative) if negative else 0

    if max_severity >= 3:
        level = "Significant reduction"
    elif max_severity >= 2:
        level = "Moderate reduction"
    else:
        level = "Mildly affected"

    factor_list = ", ".join(txt for _, txt in negative[:3])

    return f"{level}. {factor_list}."


# ---------------------------------------------------------------------------
# Distillers — compress verbose analysis into scannable spreadsheet text
# ---------------------------------------------------------------------------

def _strip_citations(text):
    """Remove [citation] blocks and collapse whitespace."""
    text = re.sub(r'\[.*?\]', '', text)
    return re.sub(r'\s{2,}', ' ', text).strip()


def _format_insight(text):
    """Restructure a verbose insight into a scannable format.

    Keeps the causal chain (trigger -> mechanism -> consequence) but strips
    citations, redundant labels, and excessive detail.

    Target: ~150-300 chars with clear structure.
    Format: "TRIGGER. Mechanism. -> Consequence."
    """
    text = _strip_citations(text)

    # Extract trigger (first sentence — the "what happened")
    # Split on double space or ". " followed by uppercase (explanation start)
    parts = re.split(r'(?<=\.)\s{2,}|(?<=\.)\s+(?=[A-Z][a-z])', text, maxsplit=1)
    trigger = parts[0].strip()
    body = parts[1].strip() if len(parts) > 1 else ""

    if not body:
        # No explanation body — return trigger as-is (already concise)
        return trigger

    # Extract cognitive/energy consequence sections
    cog_match = re.search(r'Cognitive(?:\s+impact)?:\s*(.+?)(?=Energy:|Action:|$)', body, re.IGNORECASE)
    energy_match = re.search(r'Energy:\s*(.+?)(?=Cognitive|Action:|$)', body, re.IGNORECASE)
    # Extract mechanism (everything before Cognitive/Energy/Action labels)
    mechanism = body
    for label in (r'Cognitive(?:\s+impact)?:', r'Energy:', r'Action:'):
        mechanism = re.split(label, mechanism, maxsplit=1, flags=re.IGNORECASE)[0]
    mechanism = mechanism.strip().rstrip('.')

    # Compress mechanism to ~150 chars max
    # Split on sentence boundaries (periods, semicolons)
    mech_sentences = re.split(r'(?<!\d)\.\s+|;\s*', mechanism)
    mechanism = '. '.join(s.strip() for s in mech_sentences[:2] if s.strip())
    if len(mechanism) > 150:
        mechanism = mech_sentences[0].strip() if mech_sentences else ""
    if len(mechanism) > 150:
        # Hard truncate on word boundary
        mechanism = mechanism[:147].rsplit(' ', 1)[0] + '...'
    if mechanism and not mechanism.endswith('.') and not mechanism.endswith('...'):
        mechanism += '.'

    # Build consequence from cognitive + energy impacts (pick the most relevant one)
    consequences = []
    if cog_match:
        cog = cog_match.group(1).strip().rstrip('.')
        cog_first = re.split(r'(?<!\d)\.\s+', cog)[0].strip()
        consequences.append(cog_first)
    if energy_match and not consequences:
        # Only add energy if no cognitive consequence (avoid doubling up)
        eng = energy_match.group(1).strip().rstrip('.')
        eng_first = re.split(r'(?<!\d)\.\s+', eng)[0].strip()
        consequences.append(eng_first)

    # Assemble: TRIGGER. Mechanism. -> Consequence.
    result = trigger
    if mechanism:
        result += f" {mechanism}"
    if consequences:
        effect = '. '.join(consequences)
        result += f" -> {effect}."

    return result


def _distill_insights(raw_insights, max_items=6):
    """Restructure verbose insights into scannable spreadsheet format.

    Priority: sleep verdict > training alerts > habits > nutrition > anomalies.
    Drops data quality noise. Merges related habit items.
    """
    if not raw_insights:
        return []

    # Priority buckets
    buckets = {
        0: [],  # sleep verdict (Sleep Review)
        1: [],  # training/safety alerts
        2: [],  # habit patterns
        3: [],  # nutrition flags
        4: [],  # metric anomalies
        5: [],  # knowledge-base triggers
    }

    # Collect habit-miss items separately for merging
    habit_misses = []

    for raw in raw_insights:
        text = raw.lstrip("- ").strip()
        upper = text.upper()

        # Skip data quality noise (baseline accuracy warnings)
        if any(k in upper for k in ("NOTE:", "EXTREME VALUE", "BASELINE ACCURACY")):
            continue

        if "SLEEP REVIEW" in upper or "LAST NIGHT" in upper:
            # Restructure: VERDICT -- key metrics -- ACTION
            parts = text.split(" -- ")
            verdict = parts[0] if parts else text  # "Sleep Review: FAIR"
            action = ""
            body_parts = []
            for p in parts[1:]:
                ps = p.strip()
                if ps.upper().startswith("ACTION:"):
                    action = ps
                else:
                    body_parts.append(ps)

            # Compress body: split all sentences, keep short metric summaries
            body_text = " ".join(body_parts)
            sentences = re.split(r'(?<!\d)\.\s+', body_text)
            # Keep sentences that are short metric observations (< 80 chars)
            # or that contain key terms (bedtime, duration, deep, REM)
            key_findings = []
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if len(s) < 80 or any(k in s.lower() for k in
                        ("total", "deep", "rem", "bedtime", "adequate", "target")):
                    # Compress to first clause if still long
                    if len(s) > 80:
                        s = s.split(';')[0].split(' - ')[0].strip()
                    key_findings.append(s)
                if len(key_findings) >= 3:
                    break

            result = verdict
            if key_findings:
                result += " -- " + ". ".join(key_findings) + "."
            if action:
                # Take just the directive, strip trailing mechanism/profile text
                action_text = re.sub(r'^ACTION:\s*', '', action, flags=re.IGNORECASE)
                # Split on proper sentence boundaries first
                action_sents = re.split(r'(?<!\d)\.\s+', action_text)
                action_short = action_sents[0].strip()
                # Also split on profile-context phrases that leak through
                # (e.g., "...window Reduced deep sleep directly impacts...")
                action_short = re.split(
                    r'\s+(?:Reduced|With your|Monitor for|This is|Your neurological|Given your)',
                    action_short)[0].strip()
                if len(action_short) > 100:
                    action_short = action_short[:97].rsplit(' ', 1)[0] + '...'
                if not action_short.endswith('.') and not action_short.endswith('...'):
                    action_short += '.'
                result += f" -> {action_short}"
            buckets[0].append(result)
        elif any(k in upper for k in ("SPIKE", "TRAINING LOAD", "ACWR", "CARDIAC", "ARVC")):
            buckets[1].append(_format_insight(text))
        elif re.search(r'MISSED \d+/\d+ RECENT DAYS', upper):
            # Collect habit-miss items for merging
            label_match = re.match(r'^(.+?)\s+missed\s+(\d+/\d+)', text, re.IGNORECASE)
            if label_match:
                habit_misses.append(label_match.group(1).strip())
            else:
                buckets[2].append(_format_insight(text))
        elif any(k in upper for k in ("SCREEN TIME", "BEDTIME", "BROKEN", "CONSISTENCY",
                                       "CONSECUTIVE")):
            buckets[2].append(_format_insight(text))
        elif any(k in upper for k in ("CALORIE", "PROTEIN", "WATER", "DEHYDR", "DEFICIT")):
            buckets[3].append(_format_insight(text))
        elif any(k in upper for k in ("HRV", "RHR", "RESTING HR", "STRESS", "BODY BATTERY",
                                       "SLEEP DEBT", "CUMULATIVE", "DEEP SLEEP", "REM SLEEP",
                                       "SLEEP TREND")):
            buckets[4].append(_format_insight(text))
        else:
            buckets[5].append(_format_insight(text))

    # Merge habit misses into one line if multiple
    if habit_misses:
        if len(habit_misses) >= 3:
            names = ", ".join(habit_misses)
            buckets[2].insert(0,
                f"HABITS: {names} all missed 2/3+ days. "
                "Consistency compounds -- each broken habit reduces recovery capacity.")
        else:
            for h in habit_misses:
                buckets[2].append(
                    f"{h} missed 2/3+ recent days. Consistency with this habit affects recovery.")

    # Build final list in priority order
    distilled = []
    for priority in sorted(buckets.keys()):
        for text in buckets[priority]:
            if len(distilled) >= max_items:
                break
            distilled.append(text)
        if len(distilled) >= max_items:
            break

    return distilled


def _distill_for_phone(raw_insights, max_items=4):
    """Distill raw insights into 3-4 high-priority actionable items for the phone app.

    Priority order (what changes your day):
      1. Recovery/stress overload signals (stress budget, cumulative load)
      2. Physiological signals (HRV suppressed, RHR elevated)
      3. Sleep quality summary (one consolidated line)
      4. Habit patterns that compound with current state
      5. Training load status

    Rules:
      - DROP all "Note:", "extreme value", baseline accuracy noise
      - DEDUPLICATE related items (deep sleep % + deep sleep trending = one item)
      - CONDENSE each item to one sentence with the key number + consequence
      - Max 4 items for phone display
    """
    if not raw_insights:
        return []

    # Clean and categorize
    candidates = {
        "stress": [],      # stress budget, overload
        "physio": [],       # HRV, RHR
        "sleep_verdict": [],  # Sleep Review line
        "sleep_quality": [],  # deep/REM/trends/declining
        "habits": [],       # screen time, bedtime, activity
        "training": [],     # ACWR, steps, training load
    }

    for raw in raw_insights:
        text = raw.lstrip("- ").strip()
        upper = text.upper()

        # DROP noise
        if any(k in upper for k in ("NOTE:", "EXTREME VALUE", "BASELINE ACCURACY")):
            continue

        if "STRESS BUDGET" in upper or "STRESS CAPACITY" in upper:
            candidates["stress"].append(text)
        elif "SLEEP REVIEW" in upper:
            candidates["sleep_verdict"].append(text)
        elif any(k in upper for k in ("HRV", "HEART RATE VARIABILITY")):
            candidates["physio"].append(text)
        elif any(k in upper for k in ("RESTING HR", "RHR")):
            candidates["physio"].append(text)
        elif "GARMIN STRESS" in upper or "STRESS LEVEL" in upper:
            candidates["stress"].append(text)
        elif any(k in upper for k in ("DEEP SLEEP", "REM SLEEP", "REM ", "SLEEP QUALITY",
                                       "SLEEP TREND", "SLEEP DEBT", "DECLINING")):
            candidates["sleep_quality"].append(text)
        elif any(k in upper for k in ("SCREEN TIME", "BEDTIME TARGET", "BEDTIME MISSED",
                                       "CONSECUTIVE", "BROKEN", "MISSED")):
            candidates["habits"].append(text)
        elif any(k in upper for k in ("TRAINING", "ACWR", "STEPS")):
            candidates["training"].append(text)
        else:
            # Catch-all — try to fit into most relevant bucket
            if any(k in upper for k in ("COGNITIVE", "MEMORY", "EMOTIONAL REGULATION")):
                candidates["sleep_quality"].append(text)
            else:
                candidates["training"].append(text)

    distilled = []

    # 1. Stress/recovery — prefer "stress budget" over generic Garmin stress
    if candidates["stress"]:
        budget_item = next((t for t in candidates["stress"] if "BUDGET" in t.upper()), None)
        text = budget_item or candidates["stress"][0]
        distilled.append(_phone_condense(text))

    # 2. Physiological signals — merge HRV + RHR into one line if both present
    if candidates["physio"]:
        hrv_item = next((t for t in candidates["physio"] if "HRV" in t.upper()), None)
        rhr_item = next((t for t in candidates["physio"] if "RESTING HR" in t.upper() or "RHR" in t.upper()), None)
        if hrv_item and rhr_item:
            # Extract key numbers
            hrv_num = re.search(r'today:\s*(\d+)\s*ms', hrv_item)
            rhr_num = re.search(r'today:\s*(\d+)\s*bpm', rhr_item)
            hrv_str = f"HRV {hrv_num.group(1)}ms" if hrv_num else "HRV suppressed"
            rhr_str = f"RHR {rhr_num.group(1)}bpm" if rhr_num else "RHR elevated"
            distilled.append(f"{hrv_str} (below baseline), {rhr_str} (above baseline) — autonomic system under strain, recovery impaired.")
        elif hrv_item:
            distilled.append(_phone_condense(hrv_item))
        elif rhr_item:
            distilled.append(_phone_condense(rhr_item))

    # 3. Sleep — consolidate all sleep items into one summary line
    if candidates["sleep_verdict"]:
        # Use the sleep review line, condensed
        distilled.append(_phone_condense(candidates["sleep_verdict"][0]))
    elif candidates["sleep_quality"]:
        # No verdict — pick the most informative sleep item
        distilled.append(_phone_condense(candidates["sleep_quality"][0]))

    # 4. Habits — merge into one line
    if candidates["habits"] and len(distilled) < max_items:
        habit_names = []
        for h in candidates["habits"]:
            if "SCREEN" in h.upper():
                habit_names.append("screen time before bed")
            elif "BEDTIME" in h.upper():
                habit_names.append("bedtime consistency")
            elif "PHYSICAL" in h.upper() or "ACTIVITY" in h.upper():
                habit_names.append("physical activity")
            else:
                # Extract first few words as label
                label = h.split(" missed")[0].split(" broken")[0][:30].strip()
                if label and label not in habit_names:
                    habit_names.append(label)
        if habit_names:
            names = ", ".join(dict.fromkeys(habit_names))  # dedupe preserving order
            days = re.search(r'(\d+)\s+(?:of last\s+)?(\d+)\s+(?:recent\s+)?days', candidates["habits"][0])
            if days:
                distilled.append(f"Habits broken recently: {names}. These compound with poor sleep to reduce recovery.")
            else:
                distilled.append(f"Habits broken recently: {names}. Consistency compounds with recovery.")

    # 5. Training — if room
    if candidates["training"] and len(distilled) < max_items:
        distilled.append(_phone_condense(candidates["training"][0]))

    return distilled[:max_items]


def _phone_condense(text):
    """Condense a verbose insight to 1-2 sentences for phone display.

    Keeps: the trigger (what happened + key number) and the consequence.
    Drops: mechanism details, citations, profile-specific elaboration.
    """
    text = _strip_citations(text)

    # For Sleep Review lines, restructure
    if "Sleep Review:" in text:
        parts = text.split(" -- ")
        verdict = parts[0].strip()  # "Sleep Review: POOR"
        metrics = []
        action = ""
        for p in parts[1:]:
            p = p.strip()
            if p.startswith("->") or p.startswith("ACTION"):
                action = re.sub(r'^(->|ACTION:)\s*', '', p).strip()
            else:
                metrics.append(p)
        result = verdict
        if metrics:
            result += ". " + ". ".join(m.strip() for m in metrics if m.strip())
        if action:
            # First sentence of action only
            action_first = re.split(r'(?<!\d)\.\s+', action)[0].strip()
            if not action_first.endswith('.'):
                action_first += '.'
            result += " " + action_first
        return result

    # For [Training] lines, clean the bracket prefix
    text = re.sub(r'^\[Training\]\s*', '', text)

    # Split into trigger (first sentence) and body
    sentences = re.split(r'(?<!\d)\.\s{1,2}(?=[A-Z])', text, maxsplit=1)
    trigger = sentences[0].strip()

    if len(sentences) < 2:
        # Already concise
        if not trigger.endswith('.'):
            trigger += '.'
        return trigger

    body = sentences[1].strip()

    # Extract consequence: look for "-> " or "Cognitive impact:" or "Energy:"
    consequence = ""
    arrow_match = re.search(r'->\s*(.+?)(?:\.|$)', body)
    cog_match = re.search(r'Cognitive(?:\s+impact)?:\s*(.+?)(?=Energy:|Action:|$)', body, re.IGNORECASE)
    energy_match = re.search(r'Energy:\s*(.+?)(?=Cognitive|Action:|$)', body, re.IGNORECASE)

    if arrow_match:
        consequence = arrow_match.group(1).strip()
    elif cog_match:
        consequence = re.split(r'(?<!\d)\.\s+', cog_match.group(1).strip())[0]
    elif energy_match:
        consequence = re.split(r'(?<!\d)\.\s+', energy_match.group(1).strip())[0]

    result = trigger
    if not result.endswith('.'):
        result += '.'
    if consequence:
        consequence = consequence.strip().rstrip('.')
        result += f" Impact: {consequence}."

    # Hard cap at 200 chars
    if len(result) > 200:
        result = result[:197].rsplit(' ', 1)[0] + '...'

    return result


def _distill_recommendations(raw_recs, max_items=3):
    """Restructure recommendations: clean presentation, keep substance.

    Strips citations, markdown formatting, and redundant labels.
    Keeps the full actionable content with reasoning.
    """
    if not raw_recs:
        return []

    prioritized = []
    rest = []
    for raw in raw_recs:
        text = raw.lstrip("- ").strip()
        text = _strip_citations(text)
        # Strip markdown bold
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        # Strip numbered list prefixes
        text = re.sub(r'^\d+\.\s+', '', text)
        # Strip "Cognitive impact:" / "Energy:" labels, fold into flow
        text = re.sub(r'Cognitive(?:\s+impact)?:\s*', '', text)
        text = re.sub(r'Energy:\s*', '', text)
        # Compress to 2-3 sentences
        sentences = re.split(r'(?<!\d)\.\s+', text)
        text = '. '.join(s.strip() for s in sentences[:3] if s.strip())
        if text and not text.endswith('.'):
            text += '.'

        if "DO THIS FIRST" in raw.upper():
            # Clean up "DO THIS FIRST: 1. Today (Day):" -> "TODAY (Day):"
            text = re.sub(r'DO THIS FIRST:\s*\d*\.?\s*', '', text, flags=re.IGNORECASE)
            # Remove leading "Today (Day): " and replace with "TODAY:"
            text = re.sub(r'^Today\s*\([^)]+\):\s*', 'TODAY: ', text, flags=re.IGNORECASE)
            prioritized.append(text)
        else:
            rest.append(text)

    ordered = prioritized + rest
    return ordered[:max_items]


# ---------------------------------------------------------------------------
# Write to Google Sheets
# ---------------------------------------------------------------------------

def write_analysis(wb, target_date, score, label, sleep_context, training_status,
                   insights, recommendations, confidence, cognitive_assessment=""):
    """Upsert one row to the Overall Analysis tab."""
    import gspread
    try:
        sheet = wb.worksheet("Overall Analysis")
    except gspread.exceptions.WorksheetNotFound:
        # Auto-create if missing
        from setup_overall_analysis import setup_overall_analysis
        sheet = setup_overall_analysis(wb)

    date_str = str(target_date)
    day_str = date_to_day(date_str)

    # Distill verbose analysis into scannable spreadsheet text
    short_insights = _distill_insights(insights)
    short_recs = _distill_recommendations(recommendations)
    insights_text = "\n".join(f"- {i}" for i in short_insights) if short_insights else "No notable findings."
    recs_text = "\n".join(f"- {r}" for r in short_recs) if short_recs else "Maintain current routine."

    # Columns A-G (auto) — skip H-I (Cognition manual) — columns J-L (auto)
    left_part = [
        day_str,                                     # A  Day
        date_str,                                    # B  Date
        score if score is not None else "",           # C  Readiness Score
        label,                                       # D  Readiness Label
        confidence,                                   # E  Confidence
        cognitive_assessment,                         # F  Cognitive/Energy Assessment
        sleep_context,                                # G  Sleep Context
    ]
    right_part = [
        insights_text,                                # J  Key Insights
        recs_text,                                    # K  Recommendations
        training_status,                              # L  Training Load Status
    ]

    # Upsert by date
    all_dates = sheet.col_values(2)  # Date is column B
    if date_str in all_dates:
        row_index = all_dates.index(date_str) + 1
        # Write A-G and J-L separately to preserve manual H-I (Cognition)
        # Use RAW for text (dates, strings) so Sheets doesn't parse them
        sheet.update(range_name=f"A{row_index}:G{row_index}", values=[left_part], value_input_option="RAW")
        sheet.update(range_name=f"J{row_index}:L{row_index}", values=[right_part], value_input_option="RAW")
        # Rewrite score as number (RAW stores it as text, gradient needs number)
        if score is not None:
            sheet.update(range_name=f"C{row_index}", values=[[score]], value_input_option="USER_ENTERED")
        print(f"  Overall Analysis: updated {date_str}.")
    else:
        # New row: include empty placeholders for H-I
        full_row = left_part + ["", ""] + right_part
        sheet.append_row(full_row, value_input_option="RAW")
        # Fix score to be numeric (append_row with RAW stores as text)
        new_row_idx = len(sheet.col_values(2))
        if score is not None:
            sheet.update(range_name=f"C{new_row_idx}", values=[[score]], value_input_option="USER_ENTERED")
        print(f"  Overall Analysis: logged {date_str}.")

    # Sort data rows by date descending
    _sort_analysis_tab(sheet)

    # Refresh weekly banding after data change
    from setup_overall_analysis import apply_weekly_banding
    apply_weekly_banding(wb, sheet)

    # Verify conditional format rules survived banding; repair if lost
    try:
        from verify_formatting import verify_tab_formatting, repair_tab_formatting
        passed, _ = verify_tab_formatting(wb, "Overall Analysis")
        if not passed:
            repair_tab_formatting(wb, "Overall Analysis")
    except Exception:
        pass

    # Auto-resize rows to fit analysis text
    from sheets_formatting import auto_resize_rows
    auto_resize_rows(wb, "Overall Analysis")

    # Mirror to SQLite
    try:
        from sqlite_backup import get_db, upsert_overall_analysis
        db = get_db()
        upsert_overall_analysis(db, str(target_date), {
            "readiness_score": score,
            "readiness_label": label,
            "confidence": confidence,
            "cognitive_energy_assessment": cognitive_assessment,
            "sleep_context": sleep_context,
            "key_insights": insights_text,
            "recommendations": recs_text,
            "training_load_status": training_status,
        })
        db.commit()
    except Exception as e:
        print(f"  SQLite mirror (overall_analysis): {e}")


def _sort_analysis_tab(sheet):
    """Sort Overall Analysis data rows by date descending, preserving legend."""
    rows = sheet.get_all_values()
    if len(rows) < 3:
        return  # nothing to sort
    header = rows[0]
    data = [r for r in rows[1:] if r and len(r) > 1 and r[1] and str(r[1]).startswith("20")]
    non_data = [r for r in rows[1:] if not (r and len(r) > 1 and r[1] and str(r[1]).startswith("20"))]
    data.sort(key=lambda r: r[1], reverse=True)
    all_sorted = [header] + data + non_data
    max_cols = max(len(r) for r in all_sorted)
    for r in all_sorted:
        while len(r) < max_cols:
            r.append("")
    from gspread.utils import rowcol_to_a1
    end_col = rowcol_to_a1(1, max_cols).rstrip("1")
    sheet.update(range_name=f"A1:{end_col}{len(all_sorted)}", values=all_sorted,
                 value_input_option="RAW")

    # RAW write converts Column C (Readiness Score) to text strings, which breaks
    # numeric conditional formatting. Re-write score column as numbers.
    score_values = []
    for r in all_sorted[1:]:  # skip header
        val = r[2] if len(r) > 2 else ""  # Column C = index 2
        try:
            score_values.append([float(val)])
        except (ValueError, TypeError):
            score_values.append([val])  # keep blanks/text as-is
    if score_values:
        sheet.update(range_name=f"C2:C{len(all_sorted)}", values=score_values,
                     value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# Main Analysis Pipeline
# ---------------------------------------------------------------------------

def _maybe_run_validation(wb, target_date):
    """Run validation if it hasn't been run in the last 7 days."""
    log_path = Path(__file__).parent / "reference" / "validation_log.json"
    try:
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                log = json.load(f)
            if log:
                last_date = date.fromisoformat(log[-1]["date"])
                if (target_date - last_date).days < 7:
                    return  # Already ran this week
    except Exception:
        pass  # If log is corrupted, run validation anyway
    print("\n  [Auto-validation: weekly check triggered]")
    try:
        run_validation(wb, target_date)
    except Exception as e:
        print(f"  Warning: auto-validation failed: {e}")


def run_analysis(wb, target_date):
    """Run the full analysis pipeline for a given date."""
    print(f"\n--- Overall Analysis for {target_date} ---")

    # Clear dedup registry for this run
    _hardcoded_kb_ids.clear()

    # Load health knowledge base
    knowledge = load_health_knowledge()

    # Load personal health profile (empty dict if none exists — zero regression)
    profile = load_profile()
    accommodations = get_accommodations(profile)
    knowledge = merge_knowledge(knowledge, profile)

    # Read all data
    data = read_all_data(wb)
    by_date_garmin = _rows_by_date(data["garmin"])
    by_date_sleep = _rows_by_date(data["sleep"])
    daily_log_by_date = _rows_by_date(data["daily_log"])
    nutrition_by_date = _rows_by_date(data["nutrition"])
    sessions_by_date_map = _sessions_by_date(data["session_log"])

    # Compute baselines
    baselines = compute_baselines(by_date_garmin, by_date_sleep, target_date)

    # Sleep context
    sleep_context, sleep_debt, sleep_trend, deep_trend, rem_trend = analyze_sleep_context(
        by_date_sleep, by_date_garmin, target_date, baselines
    )

    # Training load
    acwr, training_status, acute_load, chronic_load = compute_acwr(
        sessions_by_date_map, target_date
    )

    # Notes flags (expand lookback to 3 days for alcohol cognitive window)
    # Includes Session Log notes and Sleep notes alongside Daily Log and Nutrition
    note_flags = parse_notes_for_flags(daily_log_by_date, nutrition_by_date,
                                       target_date, days_back=3,
                                       sessions_by_date=sessions_by_date_map,
                                       sleep_by_date=by_date_sleep)

    # Readiness score
    score, label, components, confidence = compute_readiness(
        baselines, (sleep_context, sleep_debt, sleep_trend),
        daily_log_by_date, target_date, profile=profile
    )

    # Extract sleep analysis text and verdict from Sleep tab
    sleep_row = by_date_sleep.get(str(target_date))
    sleep_analysis_text = sleep_row.get("Sleep Analysis", "") if sleep_row else ""
    sleep_verdict = ""
    if sleep_analysis_text and " - " in sleep_analysis_text:
        sleep_verdict = sleep_analysis_text.split(" - ", 1)[0].strip()  # GOOD/FAIR/POOR

    # Insights (with knowledge base + condensed sleep analysis)
    insights = generate_insights(
        baselines, sleep_debt, sleep_trend, acwr, training_status,
        note_flags, daily_log_by_date, by_date_garmin,
        by_date_sleep, sessions_by_date_map, target_date,
        knowledge=knowledge, sleep_analysis_text=sleep_analysis_text,
        deep_trend=deep_trend, rem_trend=rem_trend, profile=profile,
        nutrition_by_date=nutrition_by_date
    )

    # Dynamic knowledge triggers — auto-fires insights for any knowledge entry
    # with a "trigger" field. New entries added by /update-intel automatically
    # participate without code changes.
    data_sources = {
        "garmin": by_date_garmin,
        "sleep": by_date_sleep,
        "daily_log": daily_log_by_date,
        "nutrition": nutrition_by_date,
    }
    # Collect IDs already used by hardcoded insights to avoid duplicates
    kb_triggered = scan_knowledge_triggers(
        knowledge, data_sources, sessions_by_date_map, target_date
    )
    insights.extend(kb_triggered)

    # Recommendations (with knowledge base + profile filtering)
    recommendations = generate_recommendations(
        score, label, sleep_debt, acwr, note_flags, baselines, target_date,
        knowledge=knowledge, profile=profile
    )

    # Cognitive/Energy Assessment
    cognitive_assessment = assess_cognitive_state(
        baselines, sleep_debt, note_flags, by_date_sleep,
        sessions_by_date_map, target_date, knowledge=knowledge,
        profile=profile
    )

    # Print summary to terminal
    print(f"  Readiness: {score}/10 ({label}) | Confidence: {confidence}")
    if components:
        comp_parts = [f"{k}: {v:.1f} ({d})" for k, (v, d) in components.items()]
        print(f"  Components: {' | '.join(comp_parts)}")
    print(f"  Sleep: {sleep_context}")
    print(f"  Training: {training_status}")
    print(f"  Cognitive: {cognitive_assessment[:150]}{'...' if len(cognitive_assessment) > 150 else ''}")
    if insights:
        print(f"  Insights ({len(insights)}):")
        for i in insights[:3]:
            print(f"    - {i[:120]}{'...' if len(i) > 120 else ''}")
    if recommendations:
        print(f"  Recommendations ({len(recommendations)}):")
        for r in recommendations[:2]:
            print(f"    - {r[:120]}{'...' if len(r) > 120 else ''}")

    # Write to Sheets
    write_analysis(wb, target_date, score, label, sleep_context, training_status,
                   insights, recommendations, confidence, cognitive_assessment)

    # Auto-validation: run weekly (every Sunday) to check prediction accuracy
    if target_date.weekday() == 6:  # Sunday
        _maybe_run_validation(wb, target_date)

    # Distill for phone app (separate from Sheets distillation)
    phone_insights = _distill_for_phone(insights)
    phone_recs = _distill_recommendations(recommendations)

    return {
        "score": score,
        "label": label,
        "confidence": confidence,
        "insights": insights,
        "phone_insights": phone_insights,
        "phone_recommendations": phone_recs,
        "recommendations": recommendations,
        "cognitive_assessment": cognitive_assessment,
        "sleep_context": sleep_context,
        "sleep_verdict": sleep_verdict,
        "sleep_trend": sleep_trend,
        "sleep_debt": sleep_debt,
        "bed_variability": sleep_row.get("Bedtime Variability (7d)", "") if sleep_row else "",
        "wake_variability": sleep_row.get("Wake Variability (7d)", "") if sleep_row else "",
    }


def run_week_summary(wb, target_date):
    """Generate a 7-day summary analysis."""
    print(f"\n=== WEEKLY SUMMARY (ending {target_date}) ===\n")

    scores = []
    for offset in range(7):
        d = target_date - timedelta(days=offset)
        try:
            result = run_analysis(wb, d)
            score, label = result["score"], result["label"]
            if score is not None:
                scores.append((d, score, label))
        except Exception as e:
            print(f"  Skipping {d}: {e}")

    if scores:
        avg_score = sum(s for _, s, _ in scores) / len(scores)
        avg_label = "Poor"
        for threshold, lbl in READINESS_LABELS:
            if avg_score >= threshold:
                avg_label = lbl
                break
        print(f"\n  7-day average readiness: {avg_score:.1f}/10 ({avg_label})")
        print(f"  Days analyzed: {len(scores)}")
        best = max(scores, key=lambda x: x[1])
        worst = min(scores, key=lambda x: x[1])
        print(f"  Best day: {best[0]} ({best[1]}/10 {best[2]})")
        print(f"  Worst day: {worst[0]} ({worst[1]}/10 {worst[2]})")


def run_validation(wb, target_date):
    """Validate readiness predictions against actual next-day outcomes.

    Correlates readiness scores with next-day Morning Energy and Day Rating
    over the past 28 days. Logs results and flags if predictions aren't tracking.

    This is the system's self-calibration check — every wearable company does this.
    """
    print(f"\n=== VALIDATION CHECK (28 days ending {target_date}) ===\n")

    data = read_all_data(wb)
    daily_log_by_date = _rows_by_date(data.get("daily_log", []))

    # Read Overall Analysis tab for readiness scores (not in read_all_data)
    analysis_rows = []
    try:
        sheet = wb.worksheet("Overall Analysis")
        all_vals = sheet.get_all_values()
        if len(all_vals) > 1:
            headers = all_vals[0]
            analysis_rows = [dict(zip(headers, row)) for row in all_vals[1:]]
    except Exception:
        pass

    analysis_by_date = {}
    for row in analysis_rows:
        d = row.get("Date", "")
        if d:
            analysis_by_date[d] = row

    # Collect (readiness_score, next_day_energy, next_day_rating) triplets
    pairs_energy = []
    pairs_rating = []

    for offset in range(1, 29):  # 28 days back
        d = target_date - timedelta(days=offset)
        d_str = str(d)
        next_d_str = str(d + timedelta(days=1))

        analysis = analysis_by_date.get(d_str, {})
        score = _safe_float(analysis.get("Readiness Score"))
        if score is None:
            continue

        next_dl = daily_log_by_date.get(next_d_str, {})
        energy = _safe_float(next_dl.get("Morning Energy (1-10)"))
        rating = _safe_float(next_dl.get("Day Rating (1-10)"))

        if energy is not None:
            pairs_energy.append((score, energy))
        if rating is not None:
            pairs_rating.append((score, rating))

    def _simple_correlation(pairs):
        """Compute Pearson r for a list of (x, y) tuples."""
        n = len(pairs)
        if n < 7:
            return None, n
        xs, ys = zip(*pairs)
        mx = sum(xs) / n
        my = sum(ys) / n
        sx = sum((x - mx) ** 2 for x in xs)
        sy = sum((y - my) ** 2 for y in ys)
        sxy = sum((x - mx) * (y - my) for x, y in pairs)
        if sx == 0 or sy == 0:
            return None, n
        return sxy / (sx * sy) ** 0.5, n

    r_energy, n_energy = _simple_correlation(pairs_energy)
    r_rating, n_rating = _simple_correlation(pairs_rating)

    print(f"  Readiness vs next-day Morning Energy: ", end="")
    if r_energy is not None:
        print(f"r={r_energy:+.3f} (n={n_energy})")
    else:
        print(f"insufficient data (n={n_energy}, need 7+)")

    print(f"  Readiness vs next-day Day Rating:     ", end="")
    if r_rating is not None:
        print(f"r={r_rating:+.3f} (n={n_rating})")
    else:
        print(f"insufficient data (n={n_rating}, need 7+)")

    # Interpretation
    correlations = [r for r in [r_energy, r_rating] if r is not None]
    if correlations:
        avg_r = sum(correlations) / len(correlations)
        print(f"\n  Average predictive correlation: r={avg_r:+.3f}")
        if avg_r >= 0.5:
            print("  STRONG — readiness scores are tracking your outcomes well.")
        elif avg_r >= 0.3:
            print("  MODERATE — readiness predictions are useful but imperfect.")
        elif avg_r >= 0.15:
            print("  WEAK — readiness has some predictive value. Consider recalibrating weights.")
        else:
            print("  LOW — readiness scores are not tracking your outcomes.")
            print("  Consider: (a) logging Morning Energy more consistently,")
            print("  (b) recalibrating component weights based on your data.")

    # Save validation log
    log_path = Path(__file__).parent / "reference" / "validation_log.json"
    log_entry = {
        "date": str(target_date),
        "r_energy": round(r_energy, 4) if r_energy is not None else None,
        "n_energy": n_energy,
        "r_rating": round(r_rating, 4) if r_rating is not None else None,
        "n_rating": n_rating,
        "window_days": 28,
    }
    try:
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                log = json.load(f)
        else:
            log = []
        log.append(log_entry)
        # Keep last 52 entries (1 year of weekly checks)
        log = log[-52:]
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        print(f"\n  Validation logged -> {log_path}")
    except Exception as e:
        print(f"\n  Warning: could not write validation log: {e}")


def main():
    parser = argparse.ArgumentParser(description="Overall health analysis engine.")
    parser.add_argument("--date", help="Analyze specific date (YYYY-MM-DD)")
    parser.add_argument("--today", action="store_true", help="Analyze today")
    parser.add_argument("--week", action="store_true", help="7-day summary")
    parser.add_argument("--validate", action="store_true",
                        help="Run prediction validation (28-day check)")
    args = parser.parse_args()

    today = date.today()
    if args.date:
        target_date = date.fromisoformat(args.date)
    elif args.today:
        target_date = today
    else:
        target_date = today - timedelta(days=1)  # default: yesterday

    wb = get_workbook()

    if args.validate:
        run_validation(wb, target_date)
    elif args.week:
        run_week_summary(wb, target_date)
    else:
        run_analysis(wb, target_date)

    print("\nDone.")


if __name__ == "__main__":
    main()
