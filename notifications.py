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


def _briefing_expect(cognitive_assessment):
    """Build the EXPECT line from cognitive assessment."""
    if not cognitive_assessment:
        return "EXPECT: Baseline capacity expected."
    if cognitive_assessment.lower().startswith("no notable"):
        return "EXPECT: Baseline capacity -- good day for demanding work or hard training."
    first = cognitive_assessment.split(". ")[0]
    if len(first) > 130:
        first = first[:127] + "..."
    return f"EXPECT: {first}."


def _briefing_sleep(sleep_data, sleep_verdict):
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


def _briefing_flags(insights):
    """Extract actionable flags from insights, compressed for notification."""
    flags = []
    skip_patterns = ["well above baseline", "strong parasympathetic", "LAST NIGHT:",
                     "target met", "exceeds target", "well-recovered", "good day for",
                     "habit avg"]

    for insight in insights:
        if any(p in insight for p in skip_patterns):
            continue

        compressed = _strip_citations(insight)
        compressed = re.sub(r'Cognitive impact:.*?(?=Energy:|$)', '', compressed, flags=re.DOTALL).strip()
        compressed = re.sub(r'Energy:.*', '', compressed, flags=re.DOTALL).strip()
        compressed = re.sub(r'  +', ' ', compressed).strip().rstrip(".")

        if len(compressed) > 100:
            sentences = [s.strip() for s in compressed.split(". ") if s.strip()]
            compressed = ". ".join(sentences[:2])
            if len(compressed) > 100:
                compressed = sentences[0]

        if compressed and len(compressed) > 10:
            flags.append(compressed)

        if len(flags) >= 3:
            break

    return flags


def _briefing_actions(recommendations):
    """Extract top 1-2 concrete actions from recommendations."""
    actions = []
    for rec in recommendations[:2]:
        clean = _strip_citations(rec)
        clean = re.sub(r'Cognitive impact:.*', '', clean, flags=re.DOTALL).strip()
        clean = re.sub(r'Energy:.*', '', clean, flags=re.DOTALL).strip()
        clean = re.sub(r'^Today \([A-Za-z]+\):\s*', '', clean)

        sentences = [s.strip().rstrip(".") for s in clean.split(". ") if s.strip()]
        first = ". ".join(sentences[:2])
        if first and not first.endswith("."):
            first += "."
        if first:
            first = first[0].upper() + first[1:]
        if len(first) > 120:
            first = first[:117] + "..."
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

    expect = _briefing_expect(result.get("cognitive_assessment", ""))
    body_parts.append(expect)

    sleep_line = _briefing_sleep(sleep_data, sleep_verdict)
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

    # Sanitize PHI before sending through third-party service
    profile = load_profile()
    if profile:
        title = sanitize_for_notification(title, profile)
        body = sanitize_for_notification(body, profile)

    # Safety: trim flags if body exceeds 1024 chars
    while len(body) > 1000 and flags:
        flags.pop()
        body_parts_rebuild = [expect, "", sleep_line]
        if flags:
            body_parts_rebuild += ["", "FLAGS:"] + [f"- {f}" for f in flags]
        if actions:
            body_parts_rebuild += ["", "DO:"] + [f"- {a}" for a in actions]
        body = "\n".join(body_parts_rebuild)

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
