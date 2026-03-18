"""
notifications.py — Pushover push notification functions.

Handles sleep analysis notifications and morning health briefings.
"""

import os
import re
from datetime import date

import requests

from utils import _safe_float
from sleep_analysis import _parse_bedtime_hour
from profile_loader import load_profile, sanitize_for_notification


def send_pushover_notification(date_str, ind_score, analysis):
    """Send sleep analysis as a push notification via Pushover (optional)."""
    user_key = os.getenv("PUSHOVER_USER_KEY")
    api_token = os.getenv("PUSHOVER_API_TOKEN")
    if not user_key or not api_token:
        return

    # Extract verdict from "GOOD - body text..." format
    verdict = analysis.split(" - ", 1)[0] if " - " in analysis else ""
    score_str = f" ({ind_score})" if ind_score is not None else ""

    date_nice = _format_date_nice(date_str)
    title = f"Sleep: {date_nice} -- {verdict}{score_str}"

    # Split analysis body into readable lines
    body = analysis.split(" - ", 1)[1] if " - " in analysis else analysis
    body = body.replace(". ", ".\n")

    # Sanitize PHI before sending through third-party service
    profile = load_profile()
    if profile:
        title = sanitize_for_notification(title, profile)
        body = sanitize_for_notification(body, profile)

    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": api_token,
                "user": user_key,
                "title": title,
                "message": body,
                "priority": 0,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"  Pushover: notification sent for {date_str}.")
        else:
            print(f"  Pushover: failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"  Pushover: could not send notification: {e}")


def _strip_citations(text):
    """Remove [citation] blocks and verbose cognitive/energy prefixes for notification brevity."""
    text = re.sub(r'\[.*?\]', '', text).strip()
    text = re.sub(r'Cognitive impact:\s*', '', text)
    text = re.sub(r'Energy:\s*', '', text)
    text = re.sub(r'  +', ' ', text).strip()
    return text


def _format_date_nice(date_str):
    """Format ISO date to 'Mar 17' style."""
    try:
        d = date.fromisoformat(date_str)
        return d.strftime("%b %-d")
    except (ValueError, OSError):
        try:
            d = date.fromisoformat(date_str)
            return d.strftime("%b %d").replace(" 0", " ")
        except Exception:
            return date_str


def _briefing_expect(cognitive_assessment, sleep_data=None):
    """Build the EXPECT block from cognitive assessment + downstream effects.

    Maps physiological factors to what you'll actually feel:
    cognition, emotional regulation, and energy.
    """
    if not cognitive_assessment:
        return "EXPECT: Baseline capacity expected."
    if cognitive_assessment.lower().startswith("no notable") or \
       cognitive_assessment.lower().startswith("above baseline"):
        return "EXPECT: Baseline capacity -- good day for demanding work or hard training."

    # Parse the assessment: "Level. factor1, factor2, factor3."
    parts = cognitive_assessment.split(". ", 1)
    level = parts[0].strip()  # e.g. "Mildly affected", "Significant reduction"
    factors_text = parts[1].strip().rstrip(".") if len(parts) > 1 else ""
    factors = [f.strip() for f in factors_text.split(", ")] if factors_text else []

    # Map factors to downstream effects on cognition, emotion, energy
    cognition_effects = []
    emotion_effects = []
    energy_effects = []

    for f in factors:
        fl = f.lower()
        if "sleep debt" in fl:
            cognition_effects.append("attention and word recall reduced")
            energy_effects.append("fatigue compounds through the day")
        elif "hrv suppressed" in fl or "hrv below baseline" in fl:
            energy_effects.append("autonomic recovery incomplete")
            if "declining" in fl:
                emotion_effects.append("stress resilience lower than usual")
        elif "low deep sleep" in fl:
            cognition_effects.append("memory consolidation impaired overnight")
        elif "low rem" in fl:
            emotion_effects.append("emotional reactivity higher than usual")
        elif "stress elevated" in fl:
            cognition_effects.append("executive function taxed")
            emotion_effects.append("lower frustration tolerance")
        elif "compounding stressors" in fl:
            cognition_effects.append("multiple stressors stacking")
        elif "body battery low" in fl:
            energy_effects.append("physical reserves depleted")
        elif "alcohol" in fl:
            cognition_effects.append("processing speed reduced")
            energy_effects.append("recovery disrupted")
        elif "heavy session" in fl:
            energy_effects.append("still recovering from hard training")

    # Also check sleep architecture from raw data if available
    if sleep_data:
        deep_pct = _safe_float(sleep_data.get("sleep_deep_pct"))
        rem_pct = _safe_float(sleep_data.get("sleep_rem_pct"))
        duration = _safe_float(sleep_data.get("sleep_duration"))
        if deep_pct is not None and deep_pct < 15 and \
                "memory consolidation" not in " ".join(cognition_effects):
            cognition_effects.append("low deep sleep -> memory consolidation impaired")
        if rem_pct is not None and rem_pct < 15 and \
                "emotional" not in " ".join(emotion_effects):
            emotion_effects.append("low REM -> emotional processing incomplete")
        if duration is not None and duration < 6 and \
                not energy_effects:
            energy_effects.append("short sleep -> energy drops likely by afternoon")

    # Build the EXPECT block
    lines = [f"EXPECT: {level}."]

    if cognition_effects:
        lines.append(f"  Mind: {'; '.join(cognition_effects[:2])}")
    if emotion_effects:
        lines.append(f"  Mood: {'; '.join(emotion_effects[:2])}")
    if energy_effects:
        lines.append(f"  Energy: {'; '.join(energy_effects[:2])}")

    # If no specific effects mapped, just show the factors
    if not cognition_effects and not emotion_effects and not energy_effects and factors:
        lines[0] = f"EXPECT: {level}. {', '.join(factors[:2])}."

    return "\n".join(lines)


def _briefing_sleep(sleep_data, sleep_verdict, sleep_debt=None,
                    bed_var=None, wake_var=None):
    """Build the SLEEP summary from raw Garmin metrics."""
    duration = _safe_float(sleep_data.get("sleep_duration"))
    deep_pct = _safe_float(sleep_data.get("sleep_deep_pct"))
    rem_pct = _safe_float(sleep_data.get("sleep_rem_pct"))
    bedtime = sleep_data.get("sleep_bedtime", "")
    hrv = _safe_float(sleep_data.get("hrv"))

    parts = []
    if sleep_verdict:
        parts.append(sleep_verdict)
    if duration is not None:
        parts.append(f"{duration:.1f}h")
    if deep_pct is not None:
        parts.append(f"Deep {deep_pct:.0f}%")
    if rem_pct is not None:
        parts.append(f"REM {rem_pct:.0f}%")
    if hrv is not None:
        parts.append(f"HRV {hrv:.0f}ms")
    if bedtime:
        bt = bedtime.strip()
        try:
            h, m = int(bt.split(":")[0]), int(bt.split(":")[1])
            suffix = "am" if h < 12 else "pm"
            h12 = h if h <= 12 else h - 12
            if h12 == 0:
                h12 = 12
            parts.append(f"Bed {h12}:{m:02d}{suffix}")
        except (ValueError, IndexError):
            parts.append(f"Bed {bt}")

    line = "SLEEP: " + " | ".join(parts)

    # Sleep consistency (7-day variability) and debt
    extras = []
    bed_v = _safe_float(bed_var)
    wake_v = _safe_float(wake_var)
    if bed_v is not None or wake_v is not None:
        var_parts = []
        if bed_v is not None:
            var_parts.append(f"Bed +-{bed_v:.0f}min")
        if wake_v is not None:
            var_parts.append(f"Wake +-{wake_v:.0f}min")
        extras.append("7d: " + " | ".join(var_parts))
    if sleep_debt is not None and sleep_debt > 0.5:
        extras.append(f"debt {sleep_debt:.1f}h")
    if extras:
        line += "\n" + " | ".join(extras)

    # Add 1-line interpretation with downstream consequences
    notes = []
    bt_hour = _parse_bedtime_hour(bedtime)
    effective_bt = None
    if bt_hour is not None:
        effective_bt = bt_hour if bt_hour >= 18 else bt_hour + 24

    if effective_bt is not None and effective_bt >= 25.0:
        if deep_pct is not None and deep_pct < 20:
            notes.append("Late bed cut deep sleep window -> incomplete glymphatic drainage, expect brain fog")
        else:
            notes.append("Late bed but deep% held up -> architecture resilient despite timing")

    if duration is not None and duration < 6:
        notes.append("Too short for full cycles -> REM-heavy later cycles lost, reduced emotional recharge")
    elif duration is not None and duration < 7:
        notes.append("Under 7h -> last REM cycles likely cut short, creative thinking reduced")

    if deep_pct is not None and deep_pct < 15:
        notes.append("Deep critically low -> impaired waste clearance and memory consolidation")
    elif deep_pct is not None and deep_pct < 17:
        notes.append("Deep slightly low -> memory consolidation may be reduced")

    if rem_pct is not None and rem_pct < 15:
        notes.append("Low REM -> incomplete emotional processing, expect irritability or reactivity")

    if hrv is not None and hrv < 30:
        notes.append(f"HRV very low -> autonomic strain, skip intense exercise")
    elif hrv is not None and hrv < 38:
        notes.append(f"HRV below baseline -> recovery incomplete")

    if notes:
        line += "\n" + ". ".join(notes[:2]) + "."

    return line


def _compress_insight(text):
    """Compress a single insight to notification-friendly length."""
    compressed = _strip_citations(text)
    compressed = re.sub(r'Cognitive impact:.*?(?=Energy:|$)', '', compressed, flags=re.DOTALL).strip()
    compressed = re.sub(r'Energy:.*', '', compressed, flags=re.DOTALL).strip()
    compressed = re.sub(r'  +', ' ', compressed).strip().rstrip(".")

    if len(compressed) > 120:
        sentences = [s.strip() for s in compressed.split(". ") if s.strip()]
        compressed = ". ".join(sentences[:2])
        if len(compressed) > 120:
            compressed = sentences[0]

    return compressed


def _briefing_flags(insights):
    """Extract actionable flags from insights, prioritizing profile-driven ones.

    Priority order:
      1. Profile-driven (pattern match, good day forensics, food-cognition,
         stress budget, cardiac guardrails, deep/REM thresholds)
      2. Safety (training spikes, cardiac HR alerts)
      3. Generic (habit misses, screen time, bedtime, steps, etc.)

    Profile insights are picked first, then remaining slots filled with generic.
    Max 4 items total.
    """
    skip_patterns = ["well above baseline", "strong parasympathetic",
                     "Sleep Review:", "LAST NIGHT:",
                     "target met", "exceeds target", "habit avg",
                     "Note: ", "EXTREME VALUE", "BASELINE ACCURACY"]

    # Profile-driven insight markers (generated by profile-aware helpers)
    profile_markers = [
        "PATTERN MATCH",            # if-then decision rules
        "GOOD DAY FORENSICS",       # what predicted a sharp day
        "Food-cognition pattern",   # sugar/carb -> next-day fog
        "Stress budget",            # personalized stress ceiling
        "cardiac profile",          # ARVC exercise guardrails
        "cardiac management",       # max HR alerts
        "primary concern",          # deep sleep memory threshold
        "cognitive recovery",       # REM emotional pipeline
        "neurological profile",     # HRV reframe
        "stress-sensitive profile", # stress reframe
    ]

    # Safety markers
    safety_markers = ["SPIKE", "ACWR", "Max HR"]

    # Knowledge-base triggered insights (from health_knowledge.json)
    knowledge_markers = ["[Training]", "[Sleep]", "[Nutrition]", "[Recovery]",
                         "depression", "dementia"]

    profile_flags = []
    safety_flags = []
    knowledge_flags = []
    generic_flags = []

    # Merge consecutive habit misses into one line
    habit_misses = []

    for insight in insights:
        if any(p in insight for p in skip_patterns):
            continue

        # Collect habit misses for merging
        miss_match = re.match(r'^(.+?)\s+missed\s+(\d+/\d+)', insight)
        if miss_match and "Consistency with this habit" in insight:
            habit_misses.append(miss_match.group(1).strip())
            continue

        compressed = _compress_insight(insight)
        if not compressed or len(compressed) <= 10:
            continue

        if any(m in insight for m in profile_markers):
            profile_flags.append(compressed)
        elif any(m in insight for m in safety_markers):
            safety_flags.append(compressed)
        elif any(m in insight for m in knowledge_markers):
            knowledge_flags.append(compressed)
        else:
            generic_flags.append(compressed)

    # Merge habit misses into one flag if any
    if habit_misses:
        if len(habit_misses) >= 3:
            habit_line = f"Habits missed: {', '.join(habit_misses[:5])}"
        else:
            habit_line = " / ".join(f"{h} missed" for h in habit_misses)
        generic_flags.append(habit_line)

    # Assemble: profile first, then safety, knowledge, generic. Max 4 total.
    flags = []
    for pool in (profile_flags, safety_flags, knowledge_flags, generic_flags):
        for f in pool:
            if len(flags) >= 4:
                break
            flags.append(f)

    return flags


def _briefing_actions(recommendations):
    """Extract top 1-2 concrete actions from recommendations."""
    actions = []
    for rec in recommendations[:2]:
        clean = _strip_citations(rec)
        clean = re.sub(r'Cognitive impact:.*', '', clean, flags=re.DOTALL).strip()
        clean = re.sub(r'Energy:.*', '', clean, flags=re.DOTALL).strip()
        # Strip markdown bold and numbered list prefixes
        clean = re.sub(r'\*\*(.+?)\*\*', r'\1', clean)
        clean = re.sub(r'^DO THIS FIRST:\s*', '', clean)
        clean = re.sub(r'^\d+\.\s*', '', clean)
        clean = re.sub(r'^Today \([A-Za-z]+\):\s*', '', clean)

        sentences = [s.strip().rstrip(".") for s in clean.split(". ") if s.strip()]
        first = ". ".join(sentences[:2])
        if first and not first.endswith("."):
            first += "."
        if first:
            first = first[0].upper() + first[1:]
        if len(first) > 150:
            first = first[:147] + "..."
        if first:
            actions.append(first)

    return actions


def compose_briefing_notification(date_str, result, sleep_data):
    """Compose a morning health briefing and send via Pushover.

    Generates notification-native copy from raw analysis data.
    Structured as: Title | EXPECT | SLEEP | FLAGS | DO
    """
    user_key = os.getenv("PUSHOVER_USER_KEY")
    api_token = os.getenv("PUSHOVER_API_TOKEN")
    if not user_key or not api_token:
        return

    score = result.get("score")
    label = result.get("label", "")
    sleep_verdict = result.get("sleep_verdict", "")

    date_nice = _format_date_nice(date_str)
    score_str = f"{score}/10" if score is not None else "N/A"
    title = f"{date_nice} | {label} {score_str}"
    if sleep_verdict:
        title += f" | Sleep: {sleep_verdict}"

    body_parts = []

    expect = _briefing_expect(result.get("cognitive_assessment", ""), sleep_data)
    body_parts.append(expect)

    sleep_debt = result.get("sleep_debt")
    bed_var = result.get("bed_variability")
    wake_var = result.get("wake_variability")
    sleep_line = _briefing_sleep(sleep_data, sleep_verdict, sleep_debt,
                                 bed_var=bed_var, wake_var=wake_var)
    body_parts.append("")
    body_parts.append(sleep_line)

    flags = _briefing_flags(result.get("insights", []))
    if flags:
        body_parts.append("")
        body_parts.append("FLAGS:")
        for f in flags:
            body_parts.append(f"- {f}")

    actions = _briefing_actions(result.get("recommendations", []))
    if actions:
        body_parts.append("")
        body_parts.append("DO:")
        for a in actions:
            body_parts.append(f"- {a}")

    body = "\n".join(body_parts)

    # Safety: trim flags if body exceeds 1024 chars (before sanitization)
    while len(body) > 1000 and flags:
        flags.pop()
        body_parts_rebuild = [expect, "", sleep_line]
        if flags:
            body_parts_rebuild += ["", "FLAGS:"] + [f"- {f}" for f in flags]
        if actions:
            body_parts_rebuild += ["", "DO:"] + [f"- {a}" for a in actions]
        body = "\n".join(body_parts_rebuild)

    # Sanitize PHI before sending through third-party service
    profile = load_profile()
    if profile:
        title = sanitize_for_notification(title, profile)
        body = sanitize_for_notification(body, profile)
    else:
        print("  WARNING: No health profile loaded — PHI sanitization skipped")

    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": api_token,
                "user": user_key,
                "title": title,
                "message": body,
                "priority": 0,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"  Pushover: morning briefing sent for {date_str}.")
        else:
            print(f"  Pushover: failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"  Pushover: could not send briefing: {e}")
