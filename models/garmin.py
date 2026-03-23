"""Canonical Garmin wellness record — one day's data from the Garmin tab."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date as _date
from typing import Optional


@dataclass
class GarminWellnessRecord:
    """One day of Garmin wellness + activity data.

    Field names match SQLite/Supabase column names (the most descriptive).
    The raw garmin_client dict uses abbreviated keys like "hrv", "bb_at_wake" —
    the mapper in mappers.py translates between the two.

    None means "no data". Mappers convert to/from "" for Sheets compatibility.
    """

    date: _date

    # HRV
    hrv_overnight_avg: Optional[float] = None
    hrv_7day_avg: Optional[float] = None

    # Heart
    resting_hr: Optional[int] = None

    # Sleep summary (as surfaced on the Garmin tab)
    sleep_score: Optional[int] = None
    sleep_duration_hrs: Optional[float] = None

    # Body battery
    body_battery: Optional[int] = None
    body_battery_at_wake: Optional[int] = None
    body_battery_high: Optional[int] = None
    body_battery_low: Optional[int] = None

    # Daily stats
    steps: Optional[int] = None
    total_calories_burned: Optional[int] = None
    active_calories_burned: Optional[int] = None
    bmr_calories: Optional[int] = None
    avg_stress_level: Optional[float] = None
    stress_qualifier: Optional[str] = None
    floors_ascended: Optional[int] = None
    moderate_intensity_min: Optional[int] = None
    vigorous_intensity_min: Optional[int] = None

    # Activity (first activity of the day)
    activity_name: Optional[str] = None
    activity_type: Optional[str] = None
    start_time: Optional[str] = None
    distance_mi: Optional[float] = None
    duration_min: Optional[float] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    calories: Optional[int] = None
    elevation_gain_m: Optional[float] = None
    avg_speed_mph: Optional[float] = None
    aerobic_training_effect: Optional[float] = None
    anaerobic_training_effect: Optional[float] = None

    # HR zones
    zone_1_min: Optional[float] = None
    zone_2_min: Optional[float] = None
    zone_3_min: Optional[float] = None
    zone_4_min: Optional[float] = None
    zone_5_min: Optional[float] = None

    # SpO2
    spo2_avg: Optional[float] = None
    spo2_min: Optional[float] = None

    @property
    def day(self) -> str:
        """3-letter day abbreviation, derived from date."""
        return self.date.strftime("%a")

    @classmethod
    def field_names(cls) -> list[str]:
        """All field names (excluding computed properties)."""
        return [f.name for f in fields(cls)]
