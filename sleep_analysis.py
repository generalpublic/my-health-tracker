"""
sleep_analysis.py — Independent sleep quality scoring and analysis.

Pure functions: no Google Sheets or Garmin API dependency.
Uses research-based thresholds from primary sources: Ohayon 2004 (sleep architecture),
Van Dongen 2003 (sleep restriction), Li 2017 (respiratory rate), Bonnet & Arand 2007
(awakenings), Nikbakhtian 2021 (bedtime/CVD), Shaffer 2017 (HRV norms).
"""

import re
import sqlite3
from pathlib import Path

from utils import _safe_float

_DB_PATH = Path(__file__).parent / "health_tracker.db"

# Module-level cache for circadian profile (computed once per process)
_circadian_cache = {"profile": None, "loaded": False}


def _parse_bedtime_hour(bedtime_str):
    """Parse HH:MM bedtime string into a float hour (0-24). Returns None if invalid."""
    if not bedtime_str or not isinstance(bedtime_str, str):
        return None
    m = re.match(r'^(\d{1,2}):(\d{2})$', bedtime_str.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h + mi / 60.0


def _bedtime_target_hour(thresholds):
    """Parse bedtime_target from thresholds into float hour (18-30 range)."""
    target_str = thresholds.get("bedtime_target", "23:00")
    target = _parse_bedtime_hour(target_str)
    if target is None:
        return 23.0
    return target if target >= 18 else target + 24


def _to_effective_hour(h):
    """Convert hour (0-24) to effective hour (18-42 range) for sleep math."""
    return h if h >= 18 else h + 24


# ---------------------------------------------------------------------------
# Knowledge-base and profile helpers for enriched sleep analysis
# ---------------------------------------------------------------------------

def _kb_sleep_text(knowledge, kb_id, fallback):
    """Return KB interpretation text for a sleep finding, or fallback if missing.

    Unlike _kb_insight() in overall_analysis.py, this returns just the
    interpretation (no cognitive_impact/citation) to keep sleep analysis concise.
    Citations are appended at the finding level, not embedded in every sentence.
    """
    if not knowledge:
        return fallback
    entry = knowledge.get(kb_id)
    if not entry:
        return fallback
    # Use first 1-2 sentences of interpretation for conciseness
    interp = entry.get("interpretation", fallback)
    sentences = interp.split(". ")
    return ". ".join(sentences[:2]) + ("." if not sentences[0].endswith(".") else "")


def _get_behavior_flag(behavior_flags, flag_type, target_date_str=None):
    """Check if a specific behavior flag is present in the flags list.

    Args:
        behavior_flags: list of (date_str, flag_type, keywords) or
                        (date_str, flag_type, keywords, detail) tuples
        flag_type: e.g. "alcohol", "late_caffeine", "late_meal", "sugar"
        target_date_str: if provided, only match flags for this date

    Returns: True if flag is present, False otherwise.
    """
    if not behavior_flags:
        return False
    for flag in behavior_flags:
        if flag[1] == flag_type:
            if target_date_str is None or flag[0] == target_date_str:
                return True
    return False


def _get_profile_frame(profile, domains):
    """Get condition-specific framing text for a sleep finding.

    Args:
        profile: user health profile dict
        domains: list of tracking_relevance domains to match
                 (e.g., ["deep_sleep", "cognition"])

    Returns: condition frame string, or empty string if no match.
    """
    if not profile:
        return ""
    conditions = profile.get("conditions", [])
    frames = []
    for cond in conditions:
        if cond.get("status") != "active":
            continue
        relevance = cond.get("tracking_relevance", [])
        if any(d in relevance for d in domains):
            cond_id = cond.get("id", "")
            # Condition-specific frames (concise, 1 sentence each)
            if cond_id == "cond_007":  # Cognitive-Memory Dysfunction
                if "deep_sleep" in domains:
                    frames.append("This directly affects your memory consolidation pipeline.")
                elif "rem_sleep" in domains:
                    frames.append("REM deficit impairs your emotional memory processing and procedural learning.")
                elif "cognition" in domains:
                    frames.append("With your cognitive profile, this deficit is higher priority.")
            elif cond_id == "cond_005":  # CIRS
                recovery_mult = (cond.get("accommodations", {})
                                 .get("analysis_adjustments", {})
                                 .get("recovery_time_multiplier"))
                if recovery_mult:
                    frames.append(f"With CIRS, recovery takes ~{recovery_mult:.0f}x longer than baseline.")
                else:
                    frames.append("CIRS means recovery from this deficit is slower than typical.")
            elif cond_id == "cond_001":  # ADHD
                if any(d in domains for d in ("sleep", "executive_function", "focus")):
                    frames.append("Sleep deficit amplifies executive dysfunction.")
            elif cond_id == "cond_003":  # Chronic Stress
                if any(d in domains for d in ("stress", "hrv", "recovery")):
                    frames.append("Your stress physiology makes this more impactful on recovery.")
            elif cond_id == "cond_006":  # Neuroimmune
                if any(d in domains for d in ("hrv", "recovery")):
                    frames.append("Some HRV variability is expected with neuroimmune activation -- focus on trends.")
    # Return first match only (avoid wall of text)
    return frames[0] if frames else ""


def _get_trend_context(sleep_context, metric):
    """Get multi-night trend annotation for a sleep metric.

    Args:
        sleep_context: dict from analyze_sleep_context()
        metric: "deep" or "rem"

    Returns: trend annotation string, or empty string if no trend data.
    """
    if not sleep_context:
        return ""
    trend_key = f"{metric}_trend"
    trend = sleep_context.get(trend_key)
    debt_nights = sleep_context.get("debt_night_count")

    parts = []
    if trend == "declining":
        parts.append(f"3-night declining trend -- this is a pattern, not a one-off")
    elif trend == "improving":
        parts.append(f"trend is improving -- recovering from lower values")

    if metric == "deep" and debt_nights is not None and debt_nights >= 3:
        parts.append(f"night {debt_nights} of below-baseline sleep")

    return ". ".join(parts)


def compute_circadian_profile(sleep_history, min_days=30):
    """Compute empirical chronotype from observed bedtime/wake history.

    Analyzes the user's actual sleep timing over the last 60 days to determine
    their personal circadian window, rather than using a fixed target.

    Args:
        sleep_history: list of dicts with "Bedtime" and "Wake Time" keys (HH:MM)
        min_days: minimum nights needed for reliable estimation (default 30)

    Returns dict:
        chronotype: "early" | "intermediate" | "late"
        median_bedtime_hr: float (effective hour, 18-30 range)
        median_wake_hr: float
        sleep_midpoint_hr: float
        bedtime_std_min: float (variability in minutes)
        optimal_window_center: float (effective hour)
        n_nights: int
    Returns None if insufficient data.

    Chronotype classification (Roenneberg et al. 2003, MSFsc):
        Early:        sleep midpoint < 2:30 AM (26.5 effective)
        Intermediate: sleep midpoint 2:30-3:30 AM (26.5-27.5)
        Late:         sleep midpoint > 3:30 AM (27.5+)
    """
    bedtimes = []
    waketimes = []

    for row in sleep_history:
        bt = _parse_bedtime_hour(row.get("Bedtime") or row.get("sleep_bedtime", ""))
        wk = _parse_bedtime_hour(row.get("Wake Time") or row.get("sleep_wake_time", ""))
        if bt is not None and wk is not None:
            bedtimes.append(_to_effective_hour(bt))
            waketimes.append(_to_effective_hour(wk))

    if len(bedtimes) < min_days:
        return None

    # Median bedtime and wake time (robust to outliers)
    bedtimes_sorted = sorted(bedtimes)
    waketimes_sorted = sorted(waketimes)
    n = len(bedtimes_sorted)
    median_bt = (bedtimes_sorted[n // 2] + bedtimes_sorted[(n - 1) // 2]) / 2
    median_wk = (waketimes_sorted[n // 2] + waketimes_sorted[(n - 1) // 2]) / 2

    # Sleep midpoint = (bedtime + wake) / 2
    sleep_midpoint = (median_bt + median_wk) / 2

    # Chronotype classification
    if sleep_midpoint < 26.5:      # midpoint before 2:30 AM
        chronotype = "early"
    elif sleep_midpoint <= 27.5:   # midpoint 2:30-3:30 AM
        chronotype = "intermediate"
    else:                          # midpoint after 3:30 AM
        chronotype = "late"

    # Bedtime variability (SD in minutes)
    bt_mean = sum(bedtimes) / len(bedtimes)
    bt_variance = sum((b - bt_mean) ** 2 for b in bedtimes) / (len(bedtimes) - 1)
    bt_std_min = (bt_variance ** 0.5) * 60  # convert hours to minutes

    return {
        "chronotype": chronotype,
        "median_bedtime_hr": round(median_bt, 2),
        "median_wake_hr": round(median_wk, 2),
        "sleep_midpoint_hr": round(sleep_midpoint, 2),
        "bedtime_std_min": round(bt_std_min, 1),
        "regularity_center": round(median_bt, 2),
        "optimal_window_center": round(median_bt, 2),  # kept for backward compat
        "n_nights": len(bedtimes),
    }


def circadian_bedtime_score(bt_hour, circadian_profile, thresholds=None):
    """Score tonight's bedtime on two independent axes: regularity and lateness.

    Regularity (60% weight): how close tonight's bedtime is to the user's
    personal median. Rewards consistency regardless of the absolute time.

    Lateness penalty (40% weight): soft penalty for bedtimes past a clinical
    threshold (default 00:30). A consistently-2AM sleeper scores well on
    regularity but still gets penalized for lateness. This prevents the
    system from treating habitual late sleep as fully optimal.

    Consistency bonus/penalty unchanged: ±2-3 pts based on variability.

    Falls back to fixed-target scoring if no circadian profile available.
    """
    t = thresholds or {}

    if circadian_profile is None:
        # Fallback: use fixed target (backward compatible)
        effective = _to_effective_hour(bt_hour)
        target_effective = _bedtime_target_hour(t)
        offset_min = (effective - target_effective) * 60
        if offset_min <= 0:
            return t.get("bedtime_bonus_before_target", 5)
        elif offset_min >= t.get("bedtime_penalty_offset_min", 90):
            return t.get("bedtime_penalty_points", -10)
        return 0

    effective = _to_effective_hour(bt_hour)

    # --- Regularity score (60% of timing): closeness to personal median ---
    median = circadian_profile["optimal_window_center"]
    deviation_min = abs(effective - median) * 60

    if deviation_min <= 15:
        regularity_score = 5.0
    elif deviation_min <= 45:
        regularity_score = 5.0 * (1.0 - (deviation_min - 15) / 30.0)
    elif deviation_min <= 90:
        regularity_score = -5.0 * ((deviation_min - 45) / 45.0)
    else:
        regularity_score = -5.0 - min(5.0, 5.0 * ((deviation_min - 90) / 90.0))

    # --- Lateness penalty (40% of timing): soft penalty past clinical threshold ---
    # Clinical threshold: bedtimes past 00:30 (24.5 in effective hours) start
    # getting penalized regardless of personal regularity.
    late_threshold = t.get("circadian_late_threshold", 24.5)  # 00:30 AM
    late_penalty_cap = t.get("circadian_late_penalty_cap", -8.0)

    if effective <= late_threshold:
        lateness_score = 0.0  # no penalty for bedtimes before threshold
    else:
        # Linear penalty: 0 at threshold, caps at late_penalty_cap at threshold + 2h
        hours_past = effective - late_threshold
        lateness_score = max(late_penalty_cap, late_penalty_cap * (hours_past / 2.0))

    # Blend: 60% regularity + 40% lateness
    timing_score = 0.6 * regularity_score + 0.4 * lateness_score

    # Consistency bonus/penalty
    consistency_score = 0.0
    variability = circadian_profile.get("bedtime_std_min", 0)
    if variability < 30:
        consistency_score = 2.0
    elif variability > 60:
        consistency_score = -3.0

    return round(timing_score + consistency_score, 1)


def load_circadian_profile():
    """Load circadian profile from SQLite sleep history (cached per process).

    Queries the last 90 days of bedtime/wake time data from SQLite and
    computes the user's empirical chronotype. Returns None if insufficient
    data (< 30 nights) or database unavailable.
    """
    if _circadian_cache["loaded"]:
        return _circadian_cache["profile"]

    _circadian_cache["loaded"] = True

    if not _DB_PATH.exists():
        return None

    try:
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            "SELECT bedtime, wake_time FROM sleep "
            "WHERE bedtime IS NOT NULL AND wake_time IS NOT NULL "
            "AND bedtime != '' AND wake_time != '' "
            "ORDER BY date DESC LIMIT 90"
        ).fetchall()
        conn.close()

        history = [{"Bedtime": r[0], "Wake Time": r[1]} for r in rows]
        profile = compute_circadian_profile(history)
        _circadian_cache["profile"] = profile
        if profile:
            print(f"  Circadian profile: {profile['chronotype']} chronotype "
                  f"(midpoint {profile['sleep_midpoint_hr']:.1f}h, "
                  f"variability {profile['bedtime_std_min']:.0f}min, "
                  f"n={profile['n_nights']})")
        return profile
    except Exception as e:
        print(f"  Circadian profile warning: {e}")
        return None


def compute_independent_score(data, thresholds=None, circadian_profile=None):
    """Compute a 0-100 independent sleep quality score from raw metrics.

    Args:
        data: dict of sleep metrics (from Garmin API or data dict)
        thresholds: optional dict from get_scoring_thresholds() for personalized
                    floors/ceilings. When None, uses hardcoded population defaults.
        circadian_profile: optional dict from compute_circadian_profile() for
                    personalized bedtime scoring. When None, falls back to fixed target.

    Weighted composite:
      Total sleep:       25 pts (floor -> ceiling)
      Deep %:            20 pts (floor -> ceiling)
      REM %:             20 pts (floor -> ceiling)
      HRV:               15 pts (floor -> ceiling)
      Awakenings:        10 pts (max at 0, 0 at >=awakenings_max)
      Body battery:      10 pts (0 at 0, max at >=ceiling)
      Bedtime modifier:  circadian-aware scoring (personalized) or fixed target (fallback)
    """
    # Default thresholds (synced with thresholds.json scoring_params 2026-03-23)
    t = thresholds or {
        "sleep_duration_floor": 4.0, "sleep_duration_ceiling": 8.0,
        "deep_pct_floor": 10.0, "deep_pct_ceiling": 22.0,
        "rem_pct_floor": 12.0, "rem_pct_ceiling": 22.0,
        "hrv_floor": 37.0, "hrv_ceiling": 44.0,
        "awakenings_max": 8.0,
        "body_battery_ceiling": 60.0,
        "bedtime_target": "23:00",
        "bedtime_bonus_before_target": 5,
        "bedtime_penalty_offset_min": 90,
        "bedtime_penalty_points": -10,
    }

    score = 0.0
    metrics_found = 0

    # Total sleep (25 pts)
    total = _safe_float(data.get("sleep_duration"))
    slp_floor = t["sleep_duration_floor"]
    slp_ceil = t["sleep_duration_ceiling"]
    if total is not None and slp_ceil > slp_floor:
        score += min(25, max(0, (total - slp_floor) / (slp_ceil - slp_floor) * 25))
        metrics_found += 1

    # Deep % (20 pts)
    deep = _safe_float(data.get("sleep_deep_pct"))
    d_floor = t["deep_pct_floor"]
    d_ceil = t["deep_pct_ceiling"]
    if deep is not None and d_ceil > d_floor:
        score += min(20, max(0, (deep - d_floor) / (d_ceil - d_floor) * 20))
        metrics_found += 1

    # REM % (20 pts)
    rem = _safe_float(data.get("sleep_rem_pct"))
    r_floor = t["rem_pct_floor"]
    r_ceil = t["rem_pct_ceiling"]
    if rem is not None and r_ceil > r_floor:
        score += min(20, max(0, (rem - r_floor) / (r_ceil - r_floor) * 20))
        metrics_found += 1

    # HRV (15 pts)
    hrv = _safe_float(data.get("hrv"))
    h_floor = t["hrv_floor"]
    h_ceil = t["hrv_ceiling"]
    if hrv is not None and h_ceil > h_floor:
        score += min(15, max(0, (hrv - h_floor) / (h_ceil - h_floor) * 15))
        metrics_found += 1

    # Awakenings (10 pts) — fewer is better
    awake = _safe_float(data.get("sleep_awakenings"))
    awk_max = t["awakenings_max"]
    if awake is not None and awk_max > 0:
        score += min(10, max(0, (awk_max - awake) / awk_max * 10))
        metrics_found += 1

    # Body battery gained (10 pts)
    bb = _safe_float(data.get("sleep_body_battery_gained"))
    bb_ceil = t["body_battery_ceiling"]
    if bb is not None and bb_ceil > 0:
        score += min(10, max(0, bb / bb_ceil * 10))
        metrics_found += 1

    # Bedtime modifier — circadian-aware (personalized) or fixed target (fallback)
    bedtime_str = data.get("sleep_bedtime")
    bt_hour = _parse_bedtime_hour(bedtime_str)
    if bt_hour is not None:
        score += circadian_bedtime_score(bt_hour, circadian_profile, t)

    if metrics_found == 0:
        return None

    return round(max(0, min(100, score)))


def generate_sleep_analysis(data, thresholds=None, circadian_profile=None,
                            knowledge=None, profile=None, sleep_context=None,
                            behavior_flags=None):
    """Generate an interpretive sleep analysis from Garmin metrics.

    Args:
        data: dict of sleep metrics (from Garmin API or data dict)
        thresholds: optional dict from get_scoring_thresholds() for personalized
                    floors/ceilings. When None, uses hardcoded population defaults.
        circadian_profile: optional dict from compute_circadian_profile() for
                    personalized bedtime scoring. When None, falls back to fixed target.
        knowledge: optional dict from health_knowledge.json keyed by entry id.
                    Enables evidence-backed explanation text. When None, uses hardcoded text.
        profile: optional user health profile dict for condition-aware framing.
                    When None, no profile reframing is applied.
        sleep_context: optional dict from analyze_sleep_context() with keys:
                    {sleep_debt, deep_trend, rem_trend, weighted_score,
                     weighted_duration, debt_night_count}. Enables multi-night trend context.
        behavior_flags: optional list of (date_str, flag_type, keywords) tuples from
                    parse_notes_for_flags(). Enables causal attribution (e.g., alcohol -> low REM).

    Uses research-based thresholds to evaluate sleep architecture and produce
    cross-metric pattern analysis with specific, actionable guidance.

    Returns (independent_score, analysis_text, descriptor).
    """
    findings = []      # (severity, short_text)
    insights = []      # cross-metric interpretations
    actions = []       # specific actionable recommendations

    total = _safe_float(data.get("sleep_duration"))
    deep_pct = _safe_float(data.get("sleep_deep_pct"))
    rem_pct = _safe_float(data.get("sleep_rem_pct"))
    hrv = _safe_float(data.get("hrv"))
    resp = _safe_float(data.get("sleep_avg_respiration"))
    awakenings = _safe_float(data.get("sleep_awakenings"))
    cycles = _safe_float(data.get("sleep_cycles"))
    bb_gained = _safe_float(data.get("sleep_body_battery_gained"))
    deep_min = _safe_float(data.get("sleep_deep_min"))
    rem_min = _safe_float(data.get("sleep_rem_min"))
    light_min = _safe_float(data.get("sleep_light_min"))
    awake_min = _safe_float(data.get("sleep_awake_min"))
    time_in_bed = _safe_float(data.get("sleep_time_in_bed"))
    garmin_score = _safe_float(data.get("sleep_score"))
    bedtime_str = data.get("sleep_bedtime", "")

    has_data = any(v is not None for v in [total, deep_pct, rem_pct])
    if not has_data:
        return None, "Insufficient data for analysis", ""

    # Derive effective deep/rem percentages (prefer reported, compute from minutes)
    eff_deep_pct = deep_pct
    if eff_deep_pct is None and deep_min is not None and total and total > 0:
        eff_deep_pct = (deep_min / (total * 60)) * 100
    eff_rem_pct = rem_pct
    if eff_rem_pct is None and rem_min is not None and total and total > 0:
        eff_rem_pct = (rem_min / (total * 60)) * 100

    # Parse bedtime
    bt_hour = _parse_bedtime_hour(bedtime_str)
    effective_bt = None
    if bt_hour is not None:
        effective_bt = bt_hour if bt_hour >= 18 else bt_hour + 24
    is_late_bed = effective_bt is not None and effective_bt >= 25.0  # after 1 AM
    is_very_late = effective_bt is not None and effective_bt >= 25.5  # after 1:30 AM

    # Sleep efficiency (time asleep / time in bed)
    sleep_efficiency = None
    if total is not None and time_in_bed is not None and time_in_bed > 0:
        sleep_efficiency = (total / time_in_bed) * 100

    # --- Evaluate each metric with interpretive context ---
    # KB-enriched: uses health_knowledge.json for evidence-backed explanations
    # when available, falls back to hardcoded text when knowledge=None.

    # 1. Total sleep duration
    if total is not None:
        short_kb = _kb_sleep_text(knowledge, "sleep_debt_major",
                                  "body cannot complete enough 90-min cycles for proper restoration")
        if total < 5:
            findings.append(("poor", f"{total:.1f}h sleep - severely short; {short_kb}"))
        elif total < 6:
            findings.append(("poor", f"{total:.1f}h sleep - too short for adequate deep+REM; need 7-9h"))
        elif total < 7:
            motor_kb = _kb_sleep_text(knowledge, "sleep_motor_consolidation_window",
                                      "last cycles (REM-heavy) likely cut short")
            findings.append(("fair", f"{total:.1f}h - slightly under the 7h minimum; {motor_kb}"))
        elif total >= 8:
            findings.append(("good", f"{total:.1f}h total - solid duration, enough time for full sleep architecture"))
        else:
            findings.append(("good", f"{total:.1f}h total - adequate"))

    # 2. Deep sleep
    if eff_deep_pct is not None:
        deep_min_val = deep_min if deep_min is not None else (eff_deep_pct / 100 * (total or 0) * 60)
        deep_kb = _kb_sleep_text(knowledge, "sleep_architecture_deep_norms",
                                 "impaired waste clearance and growth hormone release")
        deep_trend_ctx = _get_trend_context(sleep_context, "deep")
        deep_profile = _get_profile_frame(profile, ["deep_sleep", "cognition"])
        # Build enrichment suffix (trend + profile, if available)
        enrichments = [s for s in [deep_trend_ctx, deep_profile] if s]
        enrich_suffix = ". " + ". ".join(enrichments) if enrichments else ""

        if eff_deep_pct >= 20:
            findings.append(("good", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - target met, strong glymphatic clearing and physical recovery"))
        elif eff_deep_pct >= 17:
            findings.append(("fair", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - slightly under the 20-25% target; memory consolidation may be reduced{enrich_suffix}"))
        elif eff_deep_pct >= 15:
            findings.append(("poor", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - below threshold; {deep_kb}{enrich_suffix}"))
        else:
            findings.append(("poor", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - critically low; {deep_kb}{enrich_suffix}"))

    # 3. REM sleep
    if eff_rem_pct is not None:
        rem_min_val = rem_min if rem_min is not None else (eff_rem_pct / 100 * (total or 0) * 60)
        rem_kb = _kb_sleep_text(knowledge, "sleep_architecture_rem_norms",
                                "reduced emotional regulation and learning consolidation")
        rem_trend_ctx = _get_trend_context(sleep_context, "rem")
        rem_profile = _get_profile_frame(profile, ["rem_sleep", "cognition"])
        enrichments = [s for s in [rem_trend_ctx, rem_profile] if s]
        enrich_suffix = ". " + ". ".join(enrichments) if enrichments else ""

        if eff_rem_pct >= 20:
            findings.append(("good", f"REM {eff_rem_pct:.0f}% ({rem_min_val:.0f}min) - target met, emotional processing and creative problem-solving supported"))
        elif eff_rem_pct >= 15:
            findings.append(("fair", f"REM {eff_rem_pct:.0f}% ({rem_min_val:.0f}min) - under 20% target; some emotional processing left incomplete{enrich_suffix}"))
        else:
            findings.append(("poor", f"REM {eff_rem_pct:.0f}% ({rem_min_val:.0f}min) - low; {rem_kb}{enrich_suffix}"))

    # 4. HRV
    if hrv is not None:
        hrv_profile = _get_profile_frame(profile, ["hrv", "recovery"])
        hrv_enrich = f". {hrv_profile}" if hrv_profile else ""
        if hrv < 37:
            findings.append(("poor", f"HRV {hrv:.0f}ms - below your baseline; autonomic recovery incomplete{hrv_enrich}"))
        elif hrv >= 44:
            findings.append(("good", f"HRV {hrv:.0f}ms - strong parasympathetic recovery"))
        elif hrv >= 41:
            findings.append(("good", f"HRV {hrv:.0f}ms - normal range, solid recovery"))

    # 5. Respiration
    if resp is not None and resp > 16:
        findings.append(("warning", f"Respiration {resp:.0f} breaths/min - elevated (normal sleep 10-16, Li 2017); may indicate stress, congestion, or sleep-disordered breathing"))

    # 6. Bedtime
    if effective_bt is not None:
        bed_kb = _kb_sleep_text(knowledge, "sleep_wake_time_melatonin_14h",
                                "deep sleep concentrates in the first third of the night (10PM-2AM window)")
        if is_very_late:
            findings.append(("poor", f"Bedtime {bedtime_str} - {bed_kb}; sleeping past this window means less time in the deep sleep zone even if total hours are adequate"))
            actions.append("aim for bed before midnight to capture the deep sleep window")
        elif effective_bt >= 24.5:  # 12:30-1:00 AM
            findings.append(("fair", f"Bedtime {bedtime_str} - slightly late; you may lose some early-night deep sleep but most architecture intact"))
            actions.append("shift bedtime 30-60min earlier for better deep sleep")
        elif effective_bt <= 23.5:
            findings.append(("good", f"Bedtime {bedtime_str} - well-aligned with circadian deep sleep window"))

    # 7. Sleep cycles
    if cycles is not None:
        cycle_kb = _kb_sleep_text(knowledge, "sleep_motor_consolidation_window",
                                  "each cycle is ~90min; not enough cycles means incomplete rotation through all sleep stages")
        if cycles < 3:
            findings.append(("poor", f"Only {cycles:.0f} sleep cycles (target 4-5) - {cycle_kb}"))
        elif cycles >= 5:
            findings.append(("good", f"{cycles:.0f} sleep cycles - full architecture completion"))
        elif cycles >= 4:
            findings.append(("good", f"{cycles:.0f} sleep cycles - adequate"))

    # 8. Awakenings
    if awakenings is not None:
        awaken_kb = _kb_sleep_text(knowledge, "sleep_awakenings_fragmentation",
                                   "each waking resets the cycle, so deep and REM stages keep getting interrupted")
        if awakenings > 5:
            findings.append(("poor", f"{awakenings:.0f} awakenings - highly fragmented; {awaken_kb}"))
        elif awakenings > 3:
            findings.append(("fair", f"{awakenings:.0f} awakenings - moderate fragmentation; may have prevented some cycles from completing"))
        elif awakenings <= 1:
            findings.append(("good", f"{awakenings:.0f} awakenings - excellent continuity"))

    # 9. Body battery
    if bb_gained is not None:
        if bb_gained < 20:
            findings.append(("poor", f"BB gained only {bb_gained:.0f} - body barely recovered despite time in bed"))
        elif bb_gained >= 65:
            findings.append(("good", f"BB +{bb_gained:.0f} - strong recovery"))

    # --- Cross-metric pattern detection (the interpretive layer) ---
    # Enriched with causal attribution from behavior_flags and multi-night context.

    # Late bedtime + adequate hours but low deep%
    if is_late_bed and total is not None and total >= 7 and eff_deep_pct is not None and eff_deep_pct < 20:
        insights.append(f"Despite {total:.1f}h in bed, deep sleep was only {eff_deep_pct:.0f}% - possibly because the late bedtime ({bedtime_str}) reduced time in the circadian deep sleep window (the body's strongest deep sleep drive is typically 10PM-2AM)")

    # Enough hours but few cycles = restlessness / fragmentation
    if total is not None and total >= 7 and cycles is not None and cycles < 3:
        # Check for causal attribution
        frag_cause = ""
        if _get_behavior_flag(behavior_flags, "late_caffeine"):
            frag_cause = " Late caffeine (half-life 5-7h) may be fragmenting sleep."
        elif _get_behavior_flag(behavior_flags, "alcohol"):
            frag_cause = " Alcohol fragments sleep in the second half of the night."
        elif _get_behavior_flag(behavior_flags, "late_meal"):
            frag_cause = " Late meals raise core body temp, disrupting sleep continuity."

        if awakenings is not None and awakenings > 3:
            frag_kb = _kb_sleep_text(knowledge, "sleep_awakenings_fragmentation",
                                     "frequent wake-ups keep resetting the 90-min cycle, preventing progression to deep/REM stages")
            insights.append(f"Slept {total:.1f}h but only completed {cycles:.0f} cycles due to {awakenings:.0f} awakenings - {frag_kb}{frag_cause}")
        elif light_min is not None and total > 0 and (light_min / (total * 60) * 100) > 55:
            light_pct = light_min / (total * 60) * 100
            insights.append(f"Slept {total:.1f}h but only {cycles:.0f} cycles with unusually high light sleep ({light_pct:.0f}%) - may indicate restlessness preventing descent into deeper stages.{frag_cause}" if frag_cause else
                            f"Slept {total:.1f}h but only {cycles:.0f} cycles with unusually high light sleep ({light_pct:.0f}%) - may indicate restlessness preventing descent into deeper stages; possible causes: caffeine, stress, room temperature, or alcohol")
        else:
            insights.append(f"Slept {total:.1f}h but only {cycles:.0f} cycles - poor sleep architecture despite adequate time; may reflect difficulty transitioning between sleep stages{frag_cause}")

    # Short sleep + late bedtime = compounding problem
    if total is not None and total < 6 and is_late_bed:
        insights.append("Late bedtime + short duration compounds: likely reduced time in the deep sleep window AND cut REM-heavy later cycles")

    # Good deep but low REM (or vice versa) = architectural imbalance
    if eff_deep_pct is not None and eff_rem_pct is not None:
        if eff_deep_pct >= 20 and eff_rem_pct < 15:
            if total is not None and total < 7:
                insights.append(f"Deep sleep is strong but REM is low - may reflect waking too early and cutting the REM-heavy final cycles (REM concentrates in the last third of sleep)")
            else:
                insights.append("Deep sleep is strong but REM is low despite adequate hours - unusual pattern; possible early morning light exposure or alarm disruption during REM")
        elif eff_rem_pct >= 20 and eff_deep_pct < 15:
            # Causal attribution: alcohol specifically suppresses deep while sparing REM
            if _get_behavior_flag(behavior_flags, "alcohol"):
                insights.append(f"REM is healthy but deep sleep is critically low - alcohol suppresses slow-wave sleep through GABAergic disruption while leaving REM relatively intact")
            else:
                insights.append("REM is healthy but deep sleep is critically low - one possibility is late bedtime or alcohol-related N3 suppression, which can reduce slow-wave sleep while leaving REM intact")

    # High awake time but few recorded awakenings = tossing/turning
    if awake_min is not None and awake_min > 30 and awakenings is not None and awakenings <= 2:
        insights.append(f"{awake_min:.0f}min awake during the night with only {awakenings:.0f} recorded awakenings - suggests prolonged restlessness rather than brief wake-ups")

    # Low sleep efficiency
    if sleep_efficiency is not None and sleep_efficiency < 85:
        eff_kb = _kb_sleep_text(knowledge, "sleep_efficiency_norms",
                                "significant time lost to wakefulness")
        insights.append(f"Sleep efficiency {sleep_efficiency:.0f}% (spent {time_in_bed:.1f}h in bed but only slept {total:.1f}h) - {eff_kb}")

    # Low HRV + poor deep = overtraining / stress signal
    if hrv is not None and hrv < 33 and eff_deep_pct is not None and eff_deep_pct < 17:
        insights.append(f"Low HRV ({hrv:.0f}ms) combined with low deep sleep ({eff_deep_pct:.0f}%) may indicate physiological stress - possible overtraining, illness, or accumulated sleep debt")

    # --- Sleep debt context (multi-night awareness) ---
    if sleep_context:
        debt = sleep_context.get("sleep_debt")
        debt_nights = sleep_context.get("debt_night_count")
        if debt is not None and debt > 0.75:
            debt_kb = _kb_sleep_text(knowledge, "sleep_debt_mild" if debt <= 1.5 else "sleep_debt_major",
                                     "cognitive effects compound non-linearly after day 3 of restriction")
            night_ctx = f" (night {debt_nights} of below-baseline sleep)" if debt_nights and debt_nights >= 2 else ""
            insights.append(f"Cumulative sleep debt: {debt:.1f}h below baseline{night_ctx}. {debt_kb}")

    # --- Compute independent score and discrepancy ---
    ind_score = compute_independent_score(data, thresholds=thresholds,
                                          circadian_profile=circadian_profile)
    discrepancy_note = ""
    if ind_score is not None and garmin_score is not None:
        diff = garmin_score - ind_score
        if diff > 20:
            discrepancy_note = f"Garmin scored this {garmin_score:.0f} but architecture suggests ~{ind_score:.0f} - Garmin may be overweighting duration while underweighting stage quality"
        elif diff < -20:
            discrepancy_note = f"Garmin scored this only {garmin_score:.0f} but metrics suggest ~{ind_score:.0f} - the sleep stages were better than Garmin's score implies"

    # --- Determine verdict ---
    severity_counts = {"good": 0, "fair": 0, "poor": 0, "warning": 0}
    for sev, _ in findings:
        if sev in severity_counts:
            severity_counts[sev] += 1

    if severity_counts["poor"] >= 3:
        verdict = "POOR"
    elif severity_counts["poor"] >= 1 and severity_counts["good"] <= severity_counts["poor"]:
        verdict = "POOR"
    elif severity_counts["poor"] == 0 and severity_counts["fair"] <= 1:
        verdict = "GOOD"
    else:
        verdict = "FAIR"

    # --- Generate short descriptor (2-4 words) congruent with analysis ---
    descriptor = ""
    if verdict == "POOR":
        if total is not None and total < 6 and eff_deep_pct is not None and eff_deep_pct < 15:
            descriptor = "Shallow & Short"
        elif hrv is not None and hrv < 33 and eff_deep_pct is not None and eff_deep_pct < 17:
            descriptor = "Poor Recovery"
        elif awakenings is not None and awakenings > 5:
            descriptor = "Fragmented"
        elif bb_gained is not None and bb_gained < 20:
            descriptor = "Low Restoration"
        elif total is not None and total < 6:
            descriptor = "Too Short"
        elif eff_deep_pct is not None and eff_deep_pct < 15:
            descriptor = "Deep Deficit"
        elif eff_rem_pct is not None and eff_rem_pct < 15:
            descriptor = "Low REM"
        else:
            descriptor = "Poor Quality"
    elif verdict == "FAIR":
        if is_late_bed and eff_deep_pct is not None and eff_deep_pct < 20:
            descriptor = "Late Bedtime"
        elif eff_deep_pct is not None and eff_deep_pct < 17:
            descriptor = "Light on Deep"
        elif eff_rem_pct is not None and eff_rem_pct < 15:
            descriptor = "Low REM"
        elif total is not None and total < 7:
            descriptor = "Slightly Short"
        elif awakenings is not None and awakenings >= 4:
            descriptor = "Restless Night"
        elif ((eff_deep_pct is not None and eff_deep_pct >= 20 and eff_rem_pct is not None and eff_rem_pct < 15)
              or (eff_rem_pct is not None and eff_rem_pct >= 20 and eff_deep_pct is not None and eff_deep_pct < 17)):
            descriptor = "Stage Imbalance"
        else:
            descriptor = "Adequate Rest"
    else:  # GOOD
        if (eff_deep_pct is not None and eff_deep_pct >= 20
                and eff_rem_pct is not None and eff_rem_pct >= 20
                and cycles is not None and cycles >= 4):
            descriptor = "Full Architecture"
        elif eff_deep_pct is not None and eff_deep_pct >= 20 and awakenings is not None and awakenings <= 1:
            descriptor = "Deep & Restful"
        elif total is not None and total >= 8:
            descriptor = "Long & Solid"
        else:
            descriptor = "Solid Recovery"

    # --- Generate specific actions based on what went wrong ---
    if not actions:
        if verdict == "POOR" and total is not None and total < 6:
            actions.append("prioritize getting 7+ hours tonight - sleep debt compounds")
        elif verdict == "POOR":
            actions.append("favor light activity today; avoid hard training until recovery improves")
        elif verdict == "FAIR":
            actions.append("functional day - save high-stakes cognitive work for when you feel most alert")
        else:
            actions.append("well-rested - good day for demanding work or hard training")

    if hrv is not None and hrv < 33 and verdict != "GOOD":
        actions.append("skip intense exercise today; walk or light stretching instead")

    # --- Build output string ---
    parts = []

    # Include discrepancy if present
    if discrepancy_note:
        parts.append(discrepancy_note)

    # Key metric findings - prioritize poor, then fair, then good (limit good to 2)
    key_findings = []
    for sev, text in findings:
        if sev in ("poor", "warning"):
            key_findings.append(text)
    for sev, text in findings:
        if sev == "fair":
            key_findings.append(text)
    good_count = 0
    for sev, text in findings:
        if sev == "good" and good_count < 2:
            key_findings.append(text)
            good_count += 1
    parts.extend(key_findings[:4])

    # Cross-metric insights (the most valuable part - limit to 2)
    parts.extend(insights[:2])

    # Actionable recommendation
    parts.append("ACTION: " + "; ".join(actions[:2]))

    body = ". ".join(parts) + "."
    body = body.replace("..", ".").replace("  ", " ").strip()
    analysis = f"{verdict} - {body}"

    return ind_score, analysis, descriptor
