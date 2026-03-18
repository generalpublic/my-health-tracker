"""
garmin_client.py — Garmin Connect API client.

Handles authentication, data fetching, and parsing of Garmin API responses.
No Google Sheets dependency.
"""

from garminconnect import Garmin
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path
import keyring
import os

from utils import _safe_float  # noqa: F401 — used by callers

load_dotenv(Path(__file__).parent / ".env")

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_PASSWORD = keyring.get_password("garmin_connect", GARMIN_EMAIL)

# --- Data key constants ---

_SLEEP_DATA_KEYS = [
    "sleep_duration", "sleep_score", "sleep_bedtime", "sleep_wake_time",
    "sleep_time_in_bed", "sleep_deep_min", "sleep_light_min", "sleep_rem_min",
    "sleep_awake_min", "sleep_deep_pct", "sleep_rem_pct", "sleep_cycles",
    "sleep_awakenings", "sleep_avg_hr", "sleep_avg_respiration",
    "sleep_body_battery_gained", "sleep_feedback",
]

_ACTIVITY_KEYS = [
    "activity_name", "activity_type", "activity_start",
    "activity_distance", "activity_duration", "activity_avg_hr",
    "activity_max_hr", "activity_calories", "activity_elevation",
    "activity_avg_speed", "aerobic_te", "anaerobic_te",
    "zone_1", "zone_2", "zone_3", "zone_4", "zone_5",
]

_STATS_KEYS = [
    "resting_hr", "steps", "total_calories", "active_calories", "bmr_calories",
    "avg_stress", "stress_qualifier", "floors_ascended", "moderate_min",
    "vigorous_min", "bb_at_wake", "bb_high", "bb_low",
]

_FEEDBACK_MAP = {
    "POSITIVE_LONG_AND_DEEP":  "Long & Deep",
    "POSITIVE_LATE_BED_TIME":  "Late Bedtime",
    "NEGATIVE_SHORT":          "Too Short",
    "NEGATIVE_FRAGMENTED":     "Fragmented",
    "NEGATIVE_POOR_QUALITY":   "Poor Quality",
    "NEGATIVE_LATE_BED_TIME":  "Late Bedtime",
}


def _fetch_sleep_data(client, date_iso):
    """Fetch and parse sleep data from Garmin API. Returns dict of sleep keys."""
    data = {}
    try:
        sleep = client.get_sleep_data(date_iso)
        if not (sleep and "dailySleepDTO" in sleep):
            return {k: "" for k in _SLEEP_DATA_KEYS}

        dto    = sleep["dailySleepDTO"]
        scores = dto.get("sleepScores") or {}

        secs = dto.get("sleepTimeSeconds", 0)
        data["sleep_duration"] = round(secs / 3600, 2) if secs else ""

        overall = scores.get("overall", {})
        data["sleep_score"] = overall.get("value", "") if isinstance(overall, dict) else ""

        start_local = dto.get("sleepStartTimestampLocal")
        end_local   = dto.get("sleepEndTimestampLocal")
        data["sleep_bedtime"]   = datetime.fromtimestamp(start_local / 1000, tz=timezone.utc).strftime("%H:%M") if start_local else ""
        data["sleep_wake_time"] = datetime.fromtimestamp(end_local / 1000, tz=timezone.utc).strftime("%H:%M") if end_local   else ""

        if start_local and end_local:
            data["sleep_time_in_bed"] = round((end_local - start_local) / 1000 / 3600, 2)
        else:
            data["sleep_time_in_bed"] = ""

        data["sleep_deep_min"]  = round(dto.get("deepSleepSeconds",  0) / 60, 1)
        data["sleep_light_min"] = round(dto.get("lightSleepSeconds", 0) / 60, 1)
        data["sleep_rem_min"]   = round(dto.get("remSleepSeconds",   0) / 60, 1)
        data["sleep_awake_min"] = round(dto.get("awakeSleepSeconds", 0) / 60, 1)

        def _pct(key):
            v = scores.get(key, {})
            return v.get("value", "") if isinstance(v, dict) else ""
        data["sleep_deep_pct"] = _pct("deepPercentage")
        data["sleep_rem_pct"]  = _pct("remPercentage")

        # Sleep cycles = transitions INTO REM (activityLevel 2.0)
        sleep_levels = sleep.get("sleepLevels", [])
        prev_level = None
        cycle_count = 0
        for s in sleep_levels:
            level = s.get("activityLevel")
            if level == 2.0 and prev_level != 2.0:
                cycle_count += 1
            prev_level = level
        data["sleep_cycles"] = cycle_count or ""

        data["sleep_awakenings"]          = dto.get("awakeCount", "")
        data["sleep_avg_hr"]              = dto.get("avgHeartRate", "")
        data["sleep_avg_respiration"]     = dto.get("averageRespirationValue", "")
        data["sleep_body_battery_gained"] = sleep.get("bodyBatteryChange", "")

        raw_fb = dto.get("sleepScoreFeedback", "")
        data["sleep_feedback"] = _FEEDBACK_MAP.get(raw_fb, raw_fb.replace("_", " ").title() if raw_fb else "")

        print(f"  Sleep: {data['sleep_bedtime']} -> {data['sleep_wake_time']} | "
              f"Deep {data['sleep_deep_min']}m  Light {data['sleep_light_min']}m  "
              f"REM {data['sleep_rem_min']}m  Cycles ~{data['sleep_cycles']}")
    except Exception as e:
        print(f"  Sleep data not available: {e}")
        return {k: "" for k in _SLEEP_DATA_KEYS}
    return data


def _fetch_activity_data(client, date_iso):
    """Fetch and parse activity data from Garmin API. Returns dict of activity keys."""
    data = {}
    try:
        raw = client.get_activities_fordate(date_iso)
        if isinstance(raw, dict):
            activities = raw.get("ActivitiesForDay", {}).get("payload", [])
        else:
            activities = raw or []

        if not activities:
            print("  No activities logged.")
            return {k: "" for k in _ACTIVITY_KEYS}

        act = activities[0]
        activity_id = act.get("activityId")
        detail  = client.get_activity(activity_id)
        summary = detail.get("summaryDTO", {})

        dist  = summary.get("distance", 0)
        dur   = summary.get("duration", 0)
        speed = summary.get("averageSpeed", 0)
        elev  = summary.get("elevationGain", "")

        data["activity_name"]      = act.get("activityName", "")
        data["activity_type"]      = act.get("activityType", {}).get("typeKey", "")
        data["activity_start"]     = act.get("startTimeLocal", "")
        data["activity_distance"]  = round(dist / 1609.344, 2) if dist else ""
        data["activity_duration"]  = round(dur / 60, 1) if dur else ""
        data["activity_avg_hr"]    = summary.get("averageHR", "")
        data["activity_max_hr"]    = summary.get("maxHR", "")
        data["activity_calories"]  = summary.get("calories", "")
        data["activity_elevation"] = round(elev, 1) if elev else ""
        data["activity_avg_speed"] = round(speed * 2.23694, 2) if speed else ""
        data["aerobic_te"]         = summary.get("trainingEffect", "")
        data["anaerobic_te"]       = summary.get("anaerobicTrainingEffect", "")

        # HR Zones + dynamic boundaries
        try:
            zones = client.get_activity_hr_in_timezones(activity_id)
            boundaries = []
            for i in range(5):
                zone_secs = zones[i].get("secsInZone", 0) if i < len(zones) else 0
                data[f"zone_{i+1}"] = round(zone_secs / 60, 1) if zone_secs else 0
                low = int(zones[i].get("zoneLowBoundary", 0)) if i < len(zones) else "?"
                next_low = zones[i+1].get("zoneLowBoundary") if i + 1 < len(zones) else None
                if next_low is not None:
                    boundaries.append(f"Z{i+1}:{low}-{int(next_low) - 1}")
                else:
                    boundaries.append(f"Z{i+1}:{low}+")
            data["zone_ranges"] = ", ".join(boundaries)
        except Exception as ze:
            print(f"  HR zones not available: {ze}")
            for i in range(1, 6):
                data[f"zone_{i}"] = 0
            data["zone_ranges"] = ""

        print(f"  Activity: {data['activity_name']} | {data['activity_duration']} min | "
              f"Avg HR: {data['activity_avg_hr']} | Max HR: {data['activity_max_hr']}")
    except Exception as e:
        print(f"  Activities not available: {e}")
        return {k: "" for k in _ACTIVITY_KEYS}
    return data


def get_garmin_data(today, yesterday):
    """Fetch all health data from Garmin Connect API.

    Authenticates, then fetches HRV, sleep, daily stats, body battery, and activities.
    Returns a flat dict with all metrics.
    """
    print("Connecting to Garmin Connect...")
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()
    print("Connected successfully.")

    t = today.isoformat()
    y = yesterday.isoformat()
    data = {}

    # HRV -- from last night (yesterday)
    try:
        hrv = client.get_hrv_data(y)
        if hrv and "hrvSummary" in hrv:
            s = hrv["hrvSummary"]
            data["hrv"]      = s.get("lastNightAvg", "")
            data["hrv_7day"] = s.get("weeklyAvg", "")
        else:
            data["hrv"] = data["hrv_7day"] = ""
    except Exception as e:
        print(f"  HRV not available: {e}")
        data["hrv"] = data["hrv_7day"] = ""

    # Sleep -- from last night (yesterday)
    data.update(_fetch_sleep_data(client, y))

    # Daily stats -- yesterday
    try:
        stats = client.get_stats(y)
        data["resting_hr"]       = stats.get("restingHeartRate", "")
        data["steps"]            = stats.get("totalSteps", "")
        data["total_calories"]   = stats.get("totalKilocalories", "")
        data["active_calories"]  = stats.get("activeKilocalories", "")
        data["bmr_calories"]     = stats.get("bmrKilocalories", "")
        data["avg_stress"]       = stats.get("averageStressLevel", "")
        raw_sq = stats.get("stressQualifier", "") or ""
        data["stress_qualifier"] = raw_sq.replace("_", " ").title() if raw_sq and raw_sq.upper() != "UNKNOWN" else ""
        data["floors_ascended"]  = round(stats.get("floorsAscended", 0) or 0)
        data["moderate_min"]     = stats.get("moderateIntensityMinutes", "")
        data["vigorous_min"]     = stats.get("vigorousIntensityMinutes", "")
        data["bb_at_wake"]       = stats.get("bodyBatteryAtWakeTime", "")
        data["bb_high"]          = stats.get("bodyBatteryHighestValue", "")
        data["bb_low"]           = stats.get("bodyBatteryLowestValue", "")
    except Exception as e:
        print(f"  Stats not available: {e}")
        for k in _STATS_KEYS:
            data[k] = ""

    # Body battery -- today
    try:
        bb = client.get_body_battery(t)
        data["body_battery"] = bb[0].get("charged", "") if bb else ""
    except Exception as e:
        print(f"  Body battery not available: {e}")
        data["body_battery"] = ""

    # Activities -- today
    data.update(_fetch_activity_data(client, t))

    return data
