"""
sleep_analysis.py — Independent sleep quality scoring and analysis.

Pure functions: no Google Sheets or Garmin API dependency.
Uses research-based thresholds from Perfecting Sleep 2.md.
"""

import re

from utils import _safe_float


def _parse_bedtime_hour(bedtime_str):
    """Parse HH:MM bedtime string into a float hour (0-24). Returns None if invalid."""
    if not bedtime_str or not isinstance(bedtime_str, str):
        return None
    m = re.match(r'^(\d{1,2}):(\d{2})$', bedtime_str.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h + mi / 60.0


def compute_independent_score(data):
    """Compute a 0-100 independent sleep quality score from raw metrics.

    Weighted composite:
      Total sleep:       25 pts (0 at <=4h, max at >=7h)
      Deep %:            20 pts (0 at <=10%, max at >=20%)
      REM %:             20 pts (0 at <=10%, max at >=20%)
      HRV:               15 pts (0 at <=30ms, max at >=45ms)
      Awakenings:        10 pts (max at 0, 0 at >=8)
      Body battery:      10 pts (0 at 0, max at >=60)
      Bedtime modifier:  +5 before midnight, -10 after 1:30 AM
    """
    score = 0.0
    metrics_found = 0

    # Total sleep (25 pts)
    total = _safe_float(data.get("sleep_duration"))
    if total is not None:
        score += min(25, max(0, (total - 4) / (7 - 4) * 25))
        metrics_found += 1

    # Deep % (20 pts)
    deep = _safe_float(data.get("sleep_deep_pct"))
    if deep is not None:
        score += min(20, max(0, (deep - 10) / (20 - 10) * 20))
        metrics_found += 1

    # REM % (20 pts)
    rem = _safe_float(data.get("sleep_rem_pct"))
    if rem is not None:
        score += min(20, max(0, (rem - 10) / (20 - 10) * 20))
        metrics_found += 1

    # HRV (15 pts)
    hrv = _safe_float(data.get("hrv"))
    if hrv is not None:
        score += min(15, max(0, (hrv - 30) / (45 - 30) * 15))
        metrics_found += 1

    # Awakenings (10 pts) — fewer is better
    awake = _safe_float(data.get("sleep_awakenings"))
    if awake is not None:
        score += min(10, max(0, (8 - awake) / 8 * 10))
        metrics_found += 1

    # Body battery gained (10 pts)
    bb = _safe_float(data.get("sleep_body_battery_gained"))
    if bb is not None:
        score += min(10, max(0, bb / 60 * 10))
        metrics_found += 1

    # Bedtime modifier
    bedtime_str = data.get("sleep_bedtime")
    bt_hour = _parse_bedtime_hour(bedtime_str)
    if bt_hour is not None:
        if bt_hour < 24:
            effective = bt_hour if bt_hour >= 18 else bt_hour + 24
            if effective <= 24:      # before midnight
                score += 5
            elif effective >= 25.5:  # after 1:30 AM
                score -= 10

    if metrics_found == 0:
        return None

    return round(max(0, min(100, score)))


def generate_sleep_analysis(data):
    """Generate an interpretive sleep analysis from Garmin metrics.

    Uses research-based thresholds to evaluate sleep architecture and produce
    cross-metric pattern analysis with specific, actionable guidance.

    Returns (independent_score, analysis_text).
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
        return None, "Insufficient data for analysis"

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

    # 1. Total sleep duration
    if total is not None:
        if total < 5:
            findings.append(("poor", f"{total:.1f}h sleep - severely short, body cannot complete enough 90-min cycles for proper restoration"))
        elif total < 6:
            findings.append(("poor", f"{total:.1f}h sleep - too short for adequate deep+REM; need 7-9h"))
        elif total < 7:
            findings.append(("fair", f"{total:.1f}h - slightly under the 7h minimum; last cycles (REM-heavy) likely cut short"))
        elif total >= 8:
            findings.append(("good", f"{total:.1f}h total - solid duration, enough time for full sleep architecture"))
        else:
            findings.append(("good", f"{total:.1f}h total - adequate"))

    # 2. Deep sleep
    if eff_deep_pct is not None:
        deep_min_val = deep_min if deep_min is not None else (eff_deep_pct / 100 * (total or 0) * 60)
        if eff_deep_pct >= 20:
            findings.append(("good", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - target met, strong glymphatic clearing and physical recovery"))
        elif eff_deep_pct >= 17:
            findings.append(("fair", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - slightly under the 20-25% target; memory consolidation may be reduced"))
        elif eff_deep_pct >= 15:
            findings.append(("poor", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - below threshold; impaired waste clearance and growth hormone release"))
        else:
            findings.append(("poor", f"Deep {eff_deep_pct:.0f}% ({deep_min_val:.0f}min) - critically low; brain waste clearing and physical repair significantly compromised"))

    # 3. REM sleep
    if eff_rem_pct is not None:
        rem_min_val = rem_min if rem_min is not None else (eff_rem_pct / 100 * (total or 0) * 60)
        if eff_rem_pct >= 20:
            findings.append(("good", f"REM {eff_rem_pct:.0f}% ({rem_min_val:.0f}min) - target met, emotional processing and creative problem-solving supported"))
        elif eff_rem_pct >= 15:
            findings.append(("fair", f"REM {eff_rem_pct:.0f}% ({rem_min_val:.0f}min) - under 20% target; some emotional processing left incomplete"))
        else:
            findings.append(("poor", f"REM {eff_rem_pct:.0f}% ({rem_min_val:.0f}min) - low; expect reduced emotional regulation and learning consolidation"))

    # 4. HRV
    if hrv is not None:
        if hrv < 30:
            findings.append(("poor", f"HRV {hrv:.0f}ms - very low; body under significant stress or not recovered"))
        elif hrv < 38:
            findings.append(("fair", f"HRV {hrv:.0f}ms - below your 38ms baseline; autonomic recovery incomplete"))
        elif hrv >= 48:
            findings.append(("good", f"HRV {hrv:.0f}ms - excellent parasympathetic recovery"))
        elif hrv >= 42:
            findings.append(("good", f"HRV {hrv:.0f}ms - above target, strong nervous system recovery"))

    # 5. Respiration
    if resp is not None and resp > 18:
        findings.append(("warning", f"Respiration {resp:.0f} breaths/min - elevated (normal 12-16); may indicate stress, congestion, or sleep-disordered breathing"))

    # 6. Bedtime
    if effective_bt is not None:
        if is_very_late:
            findings.append(("poor", f"Bedtime {bedtime_str} - deep sleep concentrates in the first third of the night (10PM-2AM window); sleeping past this window means less time in the deep sleep zone even if total hours are adequate"))
            actions.append(f"aim for bed before midnight to capture the deep sleep window")
        elif effective_bt >= 24.5:  # 12:30-1:00 AM
            findings.append(("fair", f"Bedtime {bedtime_str} - slightly late; you may lose some early-night deep sleep but most architecture intact"))
            actions.append("shift bedtime 30-60min earlier for better deep sleep")
        elif effective_bt <= 23.5:
            findings.append(("good", f"Bedtime {bedtime_str} - well-aligned with circadian deep sleep window"))

    # 7. Sleep cycles
    if cycles is not None:
        if cycles < 3:
            findings.append(("poor", f"Only {cycles:.0f} sleep cycles (target 4-5) - each cycle is ~90min; not enough cycles means incomplete rotation through all sleep stages"))
        elif cycles >= 5:
            findings.append(("good", f"{cycles:.0f} sleep cycles - full architecture completion"))
        elif cycles >= 4:
            findings.append(("good", f"{cycles:.0f} sleep cycles - adequate"))

    # 8. Awakenings
    if awakenings is not None:
        if awakenings > 5:
            findings.append(("poor", f"{awakenings:.0f} awakenings - highly fragmented; each waking resets the cycle, so deep and REM stages keep getting interrupted"))
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

    # Late bedtime + adequate hours but low deep%
    if is_late_bed and total is not None and total >= 7 and eff_deep_pct is not None and eff_deep_pct < 20:
        insights.append(f"Despite {total:.1f}h in bed, deep sleep was only {eff_deep_pct:.0f}% because the late bedtime ({bedtime_str}) missed the circadian deep sleep window - the body's strongest deep sleep drive is 10PM-2AM regardless of when you fall asleep")

    # Enough hours but few cycles = restlessness / fragmentation
    if total is not None and total >= 7 and cycles is not None and cycles < 3:
        if awakenings is not None and awakenings > 3:
            insights.append(f"Slept {total:.1f}h but only completed {cycles:.0f} cycles due to {awakenings:.0f} awakenings - frequent wake-ups keep resetting the 90-min cycle, preventing progression to deep/REM stages")
        elif light_min is not None and total > 0 and (light_min / (total * 60) * 100) > 55:
            light_pct = light_min / (total * 60) * 100
            insights.append(f"Slept {total:.1f}h but only {cycles:.0f} cycles with unusually high light sleep ({light_pct:.0f}%) - likely restlessness preventing descent into deeper stages; possible causes: caffeine, stress, room temperature, or alcohol")
        else:
            insights.append(f"Slept {total:.1f}h but only {cycles:.0f} cycles - poor sleep architecture despite adequate time; the body struggled to transition between sleep stages")

    # Short sleep + late bedtime = compounding problem
    if total is not None and total < 6 and is_late_bed:
        insights.append(f"Late bedtime + short duration is a double hit: missed the deep sleep window AND cut REM-heavy later cycles")

    # Good deep but low REM (or vice versa) = architectural imbalance
    if eff_deep_pct is not None and eff_rem_pct is not None:
        if eff_deep_pct >= 20 and eff_rem_pct < 15:
            if total is not None and total < 7:
                insights.append(f"Deep sleep is strong but REM is low - likely woke too early and cut the REM-heavy final cycles (REM concentrates in the last third of sleep)")
            else:
                insights.append(f"Deep sleep is strong but REM is low despite adequate hours - unusual pattern; possible early morning light exposure or alarm disruption during REM")
        elif eff_rem_pct >= 20 and eff_deep_pct < 15:
            insights.append(f"REM is healthy but deep sleep is critically low - late bedtime or alcohol consumption can suppress N3 slow-wave sleep specifically while leaving REM intact")

    # High awake time but few recorded awakenings = tossing/turning
    if awake_min is not None and awake_min > 30 and awakenings is not None and awakenings <= 2:
        insights.append(f"{awake_min:.0f}min awake during the night with only {awakenings:.0f} recorded awakenings - likely prolonged restlessness rather than brief wake-ups")

    # Low sleep efficiency
    if sleep_efficiency is not None and sleep_efficiency < 85:
        insights.append(f"Sleep efficiency {sleep_efficiency:.0f}% (spent {time_in_bed:.1f}h in bed but only slept {total:.1f}h) - significant time lost to wakefulness")

    # Low HRV + poor deep = overtraining / stress signal
    if hrv is not None and hrv < 33 and eff_deep_pct is not None and eff_deep_pct < 17:
        insights.append(f"Low HRV ({hrv:.0f}ms) combined with low deep sleep ({eff_deep_pct:.0f}%) suggests the body is under significant physiological stress - possible overtraining, illness, or accumulated sleep debt")

    # --- Compute independent score and discrepancy ---
    ind_score = compute_independent_score(data)
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

    return ind_score, analysis
