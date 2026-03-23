"""Mappers between GarminWellnessRecord and the four store formats.

Each function is pure: dataclass in, store-specific format out.
Round-trip tests in test_domain_model.py verify these produce identical
output to the legacy inline mappings in writers.py, sqlite_backup.py,
and supabase_sync.py.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Optional

from .garmin import GarminWellnessRecord
from .converters import to_num, to_text


# ---------------------------------------------------------------------------
# Raw dict key -> dataclass field name
# (garmin_client.py returns these abbreviated keys)
# ---------------------------------------------------------------------------
_API_KEY_TO_FIELD = {
    "hrv":               "hrv_overnight_avg",
    "hrv_7day":          "hrv_7day_avg",
    "resting_hr":        "resting_hr",
    "sleep_score":       "sleep_score",
    "sleep_duration":    "sleep_duration_hrs",
    "body_battery":      "body_battery",
    "bb_at_wake":        "body_battery_at_wake",
    "bb_high":           "body_battery_high",
    "bb_low":            "body_battery_low",
    "steps":             "steps",
    "total_calories":    "total_calories_burned",
    "active_calories":   "active_calories_burned",
    "bmr_calories":      "bmr_calories",
    "avg_stress":        "avg_stress_level",
    "stress_qualifier":  "stress_qualifier",
    "floors_ascended":   "floors_ascended",
    "moderate_min":      "moderate_intensity_min",
    "vigorous_min":      "vigorous_intensity_min",
    "activity_name":     "activity_name",
    "activity_type":     "activity_type",
    "activity_start":    "start_time",
    "activity_distance": "distance_mi",
    "activity_duration": "duration_min",
    "activity_avg_hr":   "avg_hr",
    "activity_max_hr":   "max_hr",
    "activity_calories": "calories",
    "activity_elevation": "elevation_gain_m",
    "activity_avg_speed": "avg_speed_mph",
    "aerobic_te":        "aerobic_training_effect",
    "anaerobic_te":      "anaerobic_training_effect",
    "zone_1":            "zone_1_min",
    "zone_2":            "zone_2_min",
    "zone_3":            "zone_3_min",
    "zone_4":            "zone_4_min",
    "zone_5":            "zone_5_min",
    "spo2_avg":          "spo2_avg",
    "spo2_min":          "spo2_min",
}

# Reverse map: field name -> raw dict key
_FIELD_TO_API_KEY = {v: k for k, v in _API_KEY_TO_FIELD.items()}

# Text fields (use to_text); everything else uses to_num
_TEXT_FIELDS = {"stress_qualifier", "activity_name", "activity_type", "start_time"}


# ---------------------------------------------------------------------------
# Sheets column order — must match schema.py HEADERS exactly
# (Day and Date are positional; the rest map to dataclass fields)
# ---------------------------------------------------------------------------
_SHEETS_FIELD_ORDER = [
    # Day and Date are handled specially (index 0-1)
    "sleep_score",             # C
    "hrv_overnight_avg",       # D
    "hrv_7day_avg",            # E
    "resting_hr",              # F
    "sleep_duration_hrs",      # G
    "body_battery",            # H
    "steps",                   # I
    "total_calories_burned",   # J
    "active_calories_burned",  # K
    "bmr_calories",            # L
    "avg_stress_level",        # M
    "stress_qualifier",        # N
    "floors_ascended",         # O
    "moderate_intensity_min",  # P
    "vigorous_intensity_min",  # Q
    "body_battery_at_wake",    # R
    "body_battery_high",       # S
    "body_battery_low",        # T
    "activity_name",           # U
    "activity_type",           # V
    "start_time",              # W
    "distance_mi",             # X
    "duration_min",            # Y
    "avg_hr",                  # Z
    "max_hr",                  # AA
    "calories",                # AB
    "elevation_gain_m",        # AC
    "avg_speed_mph",           # AD
    "aerobic_training_effect", # AE
    "anaerobic_training_effect", # AF
    "zone_1_min",              # AG
    "zone_2_min",              # AH
    "zone_3_min",              # AI
    "zone_4_min",              # AJ
    "zone_5_min",              # AK
    "spo2_avg",                # AL
    "spo2_min",                # AM
]


# ---------------------------------------------------------------------------
# from_garmin_api: raw dict -> GarminWellnessRecord
# ---------------------------------------------------------------------------

def from_garmin_api(data: dict, target_date: Optional[_date] = None) -> GarminWellnessRecord:
    """Build a GarminWellnessRecord from the raw dict returned by garmin_client.

    Args:
        data: flat dict with abbreviated keys ("hrv", "bb_at_wake", etc.)
        target_date: the date for this record. If None, parsed from data.
    """
    if target_date is None:
        date_str = data.get("date", "")
        target_date = _date.fromisoformat(str(date_str))

    kwargs = {}
    for api_key, field_name in _API_KEY_TO_FIELD.items():
        raw = data.get(api_key)
        if field_name in _TEXT_FIELDS:
            kwargs[field_name] = to_text(raw)
        else:
            kwargs[field_name] = to_num(raw)

    return GarminWellnessRecord(date=target_date, **kwargs)


# ---------------------------------------------------------------------------
# to_sheets_row: GarminWellnessRecord -> list (matching schema.HEADERS order)
# ---------------------------------------------------------------------------

def _none_to_empty(val):
    """Convert None to empty string for Sheets compatibility."""
    return "" if val is None else val


def to_sheets_row(record: GarminWellnessRecord) -> list:
    """Produce a 39-element list matching schema.HEADERS column order.

    Produces a 39-element list matching schema.HEADERS column order.
    None values become "" for Sheets.
    """
    row = [
        record.day,                  # A: Day
        str(record.date),            # B: Date
    ]
    for field_name in _SHEETS_FIELD_ORDER:
        row.append(_none_to_empty(getattr(record, field_name)))
    return row


# ---------------------------------------------------------------------------
# to_sqlite_params: GarminWellnessRecord -> tuple (for INSERT OR REPLACE)
# ---------------------------------------------------------------------------

# SQLite column order — must match sqlite_backup.upsert_garmin() exactly
_SQLITE_FIELD_ORDER = [
    # date and day are positional (index 0-1)
    "sleep_score", "hrv_overnight_avg", "hrv_7day_avg", "resting_hr",
    "sleep_duration_hrs", "body_battery", "steps", "total_calories_burned",
    "active_calories_burned", "bmr_calories", "avg_stress_level", "stress_qualifier",
    "floors_ascended", "moderate_intensity_min", "vigorous_intensity_min",
    "body_battery_at_wake", "body_battery_high", "body_battery_low",
    "activity_name", "activity_type", "start_time", "distance_mi", "duration_min",
    "avg_hr", "max_hr", "calories", "elevation_gain_m", "avg_speed_mph",
    "aerobic_training_effect", "anaerobic_training_effect",
    "zone_1_min", "zone_2_min", "zone_3_min", "zone_4_min", "zone_5_min",
    "spo2_avg", "spo2_min",
]


def to_sqlite_params(record: GarminWellnessRecord) -> tuple:
    """Produce a tuple for the SQLite INSERT OR REPLACE statement.

    Equivalent to the inline tuple in sqlite_backup.upsert_garmin().
    Values are already in canonical types (None, int, float, str).
    """
    params = [
        str(record.date),   # date
        record.day,          # day
    ]
    for field_name in _SQLITE_FIELD_ORDER:
        params.append(getattr(record, field_name))
    return tuple(params)


# ---------------------------------------------------------------------------
# to_supabase_dict: GarminWellnessRecord -> dict (for Supabase upsert)
# ---------------------------------------------------------------------------

def to_supabase_dict(record: GarminWellnessRecord) -> dict:
    """Produce a dict for Supabase upsert.

    Equivalent to the inline dict in supabase_sync.upsert_garmin().
    Keys are Supabase column names; values are canonical types.
    """
    d = {
        "date": str(record.date),
        "day": record.day,
    }
    # All remaining fields: field name == supabase column name
    for field_name in _SQLITE_FIELD_ORDER:
        d[field_name] = getattr(record, field_name)
    return d


# ---------------------------------------------------------------------------
# to_raw_dict: GarminWellnessRecord -> dict (legacy format for backward compat)
# ---------------------------------------------------------------------------

def to_raw_dict(record: GarminWellnessRecord) -> dict:
    """Convert back to the legacy flat dict format (garmin_client keys).

    Useful during the transition period when some code still expects
    the raw dict format.
    """
    d = {}
    for api_key, field_name in _API_KEY_TO_FIELD.items():
        val = getattr(record, field_name)
        # Legacy code expects "" for missing values, not None
        d[api_key] = "" if val is None else val
    return d
