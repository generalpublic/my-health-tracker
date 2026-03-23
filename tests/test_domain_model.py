"""Tests for the canonical domain model (Track 5).

Round-trip tests verify that GarminWellnessRecord + mappers produce
identical output to the legacy inline mappings in writers.py,
sqlite_backup.py, and supabase_sync.py.
"""

import sys
import os
from datetime import date

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.garmin import GarminWellnessRecord
from models.mappers import (
    from_garmin_api,
    to_sheets_row,
    to_sqlite_params,
    to_supabase_dict,
    to_raw_dict,
    _API_KEY_TO_FIELD,
    _SHEETS_FIELD_ORDER,
    _SQLITE_FIELD_ORDER,
)
from models.converters import to_num, to_text, day_from_date
import schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A realistic raw dict as returned by garmin_client.get_garmin_data()
SAMPLE_RAW = {
    "hrv": 42,
    "hrv_7day": 45.3,
    "resting_hr": 58,
    "sleep_score": 82,
    "sleep_duration": 7.25,
    "body_battery": 65,
    "bb_at_wake": 70,
    "bb_high": 95,
    "bb_low": 12,
    "steps": 8432,
    "total_calories": 2150,
    "active_calories": 650,
    "bmr_calories": 1500,
    "avg_stress": 32.5,
    "stress_qualifier": "low",
    "floors_ascended": 8,
    "moderate_min": 25,
    "vigorous_min": 15,
    "activity_name": "Morning Run",
    "activity_type": "running",
    "activity_start": "07:15",
    "activity_distance": 3.12,
    "activity_duration": 28.5,
    "activity_avg_hr": 145,
    "activity_max_hr": 172,
    "activity_calories": 320,
    "activity_elevation": 45.2,
    "activity_avg_speed": 6.57,
    "aerobic_te": 3.2,
    "anaerobic_te": 1.1,
    "zone_1": 2.5,
    "zone_2": 8.3,
    "zone_3": 12.1,
    "zone_4": 4.8,
    "zone_5": 0.8,
    "spo2_avg": 96.5,
    "spo2_min": 92.0,
}

SAMPLE_DATE = date(2026, 3, 23)  # a Monday


# A sparse dict (many missing fields) — tests None handling
SPARSE_RAW = {
    "hrv": 38,
    "resting_hr": 62,
    "sleep_score": "",
    "steps": 1200,
}

SPARSE_DATE = date(2026, 3, 22)  # a Sunday


# ---------------------------------------------------------------------------
# Converter tests
# ---------------------------------------------------------------------------

class TestConverters:
    def test_to_num_none(self):
        assert to_num(None) is None

    def test_to_num_empty_string(self):
        assert to_num("") is None

    def test_to_num_integer(self):
        assert to_num(42) == 42
        assert isinstance(to_num(42), int)

    def test_to_num_float(self):
        assert to_num(3.14) == 3.14
        assert isinstance(to_num(3.14), float)

    def test_to_num_string_integer(self):
        assert to_num("42") == 42
        assert isinstance(to_num("42"), int)

    def test_to_num_string_float(self):
        assert to_num("3.14") == 3.14

    def test_to_num_non_numeric_string(self):
        assert to_num("abc") == "abc"

    def test_to_text_none(self):
        assert to_text(None) is None

    def test_to_text_empty_string(self):
        assert to_text("") is None

    def test_to_text_value(self):
        assert to_text("hello") == "hello"

    def test_to_text_number(self):
        assert to_text(42) == "42"

    def test_day_from_date_valid(self):
        assert day_from_date("2026-03-23") == "Mon"

    def test_day_from_date_invalid(self):
        assert day_from_date("not-a-date") is None

    def test_day_from_date_none(self):
        assert day_from_date(None) is None


# ---------------------------------------------------------------------------
# GarminWellnessRecord tests
# ---------------------------------------------------------------------------

class TestGarminWellnessRecord:
    def test_create_minimal(self):
        r = GarminWellnessRecord(date=SAMPLE_DATE)
        assert r.date == SAMPLE_DATE
        assert r.hrv_overnight_avg is None
        assert r.steps is None

    def test_day_property(self):
        r = GarminWellnessRecord(date=SAMPLE_DATE)
        assert r.day == "Mon"

    def test_field_names_count(self):
        names = GarminWellnessRecord.field_names()
        # date + 37 data fields = 38 total
        assert len(names) == 38
        assert names[0] == "date"

    def test_field_names_match_sheets_minus_day_date(self):
        """Model fields (minus date) should cover all Sheets columns minus Day/Date."""
        model_fields = set(GarminWellnessRecord.field_names()) - {"date"}
        sheets_fields = set(_SHEETS_FIELD_ORDER)
        assert model_fields == sheets_fields


# ---------------------------------------------------------------------------
# from_garmin_api tests
# ---------------------------------------------------------------------------

class TestFromGarminApi:
    def test_full_record(self):
        r = from_garmin_api(SAMPLE_RAW, SAMPLE_DATE)
        assert r.date == SAMPLE_DATE
        assert r.hrv_overnight_avg == 42
        assert r.hrv_7day_avg == 45.3
        assert r.resting_hr == 58
        assert r.sleep_score == 82
        assert r.activity_name == "Morning Run"
        assert r.start_time == "07:15"
        assert r.spo2_avg == 96.5

    def test_sparse_record(self):
        r = from_garmin_api(SPARSE_RAW, SPARSE_DATE)
        assert r.hrv_overnight_avg == 38
        assert r.resting_hr == 62
        assert r.sleep_score is None  # "" -> None via to_num
        assert r.steps == 1200
        assert r.activity_name is None
        assert r.zone_1_min is None

    def test_date_from_data(self):
        data = {**SAMPLE_RAW, "date": "2026-03-23"}
        r = from_garmin_api(data)
        assert r.date == date(2026, 3, 23)


# ---------------------------------------------------------------------------
# Round-trip: from_garmin_api -> to_sheets_row vs legacy build_garmin_row
# ---------------------------------------------------------------------------

class TestSheetsRoundTrip:
    def test_row_length_matches_headers(self):
        r = from_garmin_api(SAMPLE_RAW, SAMPLE_DATE)
        row = to_sheets_row(r)
        assert len(row) == len(schema.HEADERS), (
            f"Row has {len(row)} elements but HEADERS has {len(schema.HEADERS)}"
        )

    def test_full_record_matches_legacy(self):
        """Model row must match what build_garmin_row() would produce."""
        from writers import build_garmin_row

        legacy_row = build_garmin_row(SAMPLE_DATE, SAMPLE_RAW)
        r = from_garmin_api(SAMPLE_RAW, SAMPLE_DATE)
        model_row = to_sheets_row(r)

        for i, (legacy_val, model_val) in enumerate(zip(legacy_row, model_row)):
            assert model_val == legacy_val, (
                f"Column {i} ({schema.HEADERS[i]}): "
                f"legacy={legacy_val!r} vs model={model_val!r}"
            )

    def test_sparse_record_matches_legacy(self):
        from writers import build_garmin_row

        legacy_row = build_garmin_row(SPARSE_DATE, SPARSE_RAW)
        r = from_garmin_api(SPARSE_RAW, SPARSE_DATE)
        model_row = to_sheets_row(r)

        for i, (legacy_val, model_val) in enumerate(zip(legacy_row, model_row)):
            assert model_val == legacy_val, (
                f"Column {i} ({schema.HEADERS[i]}): "
                f"legacy={legacy_val!r} vs model={model_val!r}"
            )

    def test_none_becomes_empty_string(self):
        r = from_garmin_api(SPARSE_RAW, SPARSE_DATE)
        row = to_sheets_row(r)
        # activity_name is None -> should be "" in row
        activity_name_idx = schema.HEADERS.index("Activity Name")
        assert row[activity_name_idx] == ""


# ---------------------------------------------------------------------------
# Round-trip: from_garmin_api -> to_sqlite_params vs legacy upsert_garmin
# ---------------------------------------------------------------------------

class TestSqliteRoundTrip:
    def test_params_length(self):
        r = from_garmin_api(SAMPLE_RAW, SAMPLE_DATE)
        params = to_sqlite_params(r)
        # 2 (date, day) + 37 data fields = 39
        assert len(params) == 39

    def test_full_record_matches_legacy(self):
        """Model params must match what sqlite_backup.upsert_garmin() would build."""
        from sqlite_backup import _to_num as sb_to_num, _to_text as sb_to_text, _day_from_date

        # Build legacy tuple manually (same logic as sqlite_backup.upsert_garmin)
        data = SAMPLE_RAW
        date_str = str(SAMPLE_DATE)
        legacy = (
            date_str,
            _day_from_date(date_str),
            sb_to_num(data.get("sleep_score")),
            sb_to_num(data.get("hrv")),
            sb_to_num(data.get("hrv_7day")),
            sb_to_num(data.get("resting_hr")),
            sb_to_num(data.get("sleep_duration")),
            sb_to_num(data.get("body_battery")),
            sb_to_num(data.get("steps")),
            sb_to_num(data.get("total_calories")),
            sb_to_num(data.get("active_calories")),
            sb_to_num(data.get("bmr_calories")),
            sb_to_num(data.get("avg_stress")),
            sb_to_text(data.get("stress_qualifier")),
            sb_to_num(data.get("floors_ascended")),
            sb_to_num(data.get("moderate_min")),
            sb_to_num(data.get("vigorous_min")),
            sb_to_num(data.get("bb_at_wake")),
            sb_to_num(data.get("bb_high")),
            sb_to_num(data.get("bb_low")),
            sb_to_text(data.get("activity_name")),
            sb_to_text(data.get("activity_type")),
            sb_to_text(data.get("activity_start")),
            sb_to_num(data.get("activity_distance")),
            sb_to_num(data.get("activity_duration")),
            sb_to_num(data.get("activity_avg_hr")),
            sb_to_num(data.get("activity_max_hr")),
            sb_to_num(data.get("activity_calories")),
            sb_to_num(data.get("activity_elevation")),
            sb_to_num(data.get("activity_avg_speed")),
            sb_to_num(data.get("aerobic_te")),
            sb_to_num(data.get("anaerobic_te")),
            sb_to_num(data.get("zone_1")),
            sb_to_num(data.get("zone_2")),
            sb_to_num(data.get("zone_3")),
            sb_to_num(data.get("zone_4")),
            sb_to_num(data.get("zone_5")),
            sb_to_num(data.get("spo2_avg")),
            sb_to_num(data.get("spo2_min")),
        )

        r = from_garmin_api(SAMPLE_RAW, SAMPLE_DATE)
        model = to_sqlite_params(r)

        for i, (legacy_val, model_val) in enumerate(zip(legacy, model)):
            assert model_val == legacy_val, (
                f"SQLite param {i}: legacy={legacy_val!r} vs model={model_val!r}"
            )


# ---------------------------------------------------------------------------
# Round-trip: from_garmin_api -> to_supabase_dict vs legacy upsert_garmin
# ---------------------------------------------------------------------------

class TestSupabaseRoundTrip:
    def test_dict_keys(self):
        r = from_garmin_api(SAMPLE_RAW, SAMPLE_DATE)
        d = to_supabase_dict(r)
        assert "date" in d
        assert "day" in d
        assert "hrv_overnight_avg" in d
        assert "spo2_min" in d

    def test_full_record_matches_legacy(self):
        """Model dict must match what supabase_sync.upsert_garmin() would build."""
        from supabase_sync import _to_num as sp_to_num, _to_text as sp_to_text, _day_from_date

        data = SAMPLE_RAW
        date_str = str(SAMPLE_DATE)
        legacy = {
            "date": date_str,
            "day": _day_from_date(date_str),
            "sleep_score": sp_to_num(data.get("sleep_score")),
            "hrv_overnight_avg": sp_to_num(data.get("hrv")),
            "hrv_7day_avg": sp_to_num(data.get("hrv_7day")),
            "resting_hr": sp_to_num(data.get("resting_hr")),
            "sleep_duration_hrs": sp_to_num(data.get("sleep_duration")),
            "body_battery": sp_to_num(data.get("body_battery")),
            "steps": sp_to_num(data.get("steps")),
            "total_calories_burned": sp_to_num(data.get("total_calories")),
            "active_calories_burned": sp_to_num(data.get("active_calories")),
            "bmr_calories": sp_to_num(data.get("bmr_calories")),
            "avg_stress_level": sp_to_num(data.get("avg_stress")),
            "stress_qualifier": sp_to_text(data.get("stress_qualifier")),
            "floors_ascended": sp_to_num(data.get("floors_ascended")),
            "moderate_intensity_min": sp_to_num(data.get("moderate_min")),
            "vigorous_intensity_min": sp_to_num(data.get("vigorous_min")),
            "body_battery_at_wake": sp_to_num(data.get("bb_at_wake")),
            "body_battery_high": sp_to_num(data.get("bb_high")),
            "body_battery_low": sp_to_num(data.get("bb_low")),
            "activity_name": sp_to_text(data.get("activity_name")),
            "activity_type": sp_to_text(data.get("activity_type")),
            "start_time": sp_to_text(data.get("activity_start")),
            "distance_mi": sp_to_num(data.get("activity_distance")),
            "duration_min": sp_to_num(data.get("activity_duration")),
            "avg_hr": sp_to_num(data.get("activity_avg_hr")),
            "max_hr": sp_to_num(data.get("activity_max_hr")),
            "calories": sp_to_num(data.get("activity_calories")),
            "elevation_gain_m": sp_to_num(data.get("activity_elevation")),
            "avg_speed_mph": sp_to_num(data.get("activity_avg_speed")),
            "aerobic_training_effect": sp_to_num(data.get("aerobic_te")),
            "anaerobic_training_effect": sp_to_num(data.get("anaerobic_te")),
            "zone_1_min": sp_to_num(data.get("zone_1")),
            "zone_2_min": sp_to_num(data.get("zone_2")),
            "zone_3_min": sp_to_num(data.get("zone_3")),
            "zone_4_min": sp_to_num(data.get("zone_4")),
            "zone_5_min": sp_to_num(data.get("zone_5")),
            "spo2_avg": sp_to_num(data.get("spo2_avg")),
            "spo2_min": sp_to_num(data.get("spo2_min")),
        }

        r = from_garmin_api(SAMPLE_RAW, SAMPLE_DATE)
        model = to_supabase_dict(r)

        assert model == legacy


# ---------------------------------------------------------------------------
# to_raw_dict round-trip
# ---------------------------------------------------------------------------

class TestRawDictRoundTrip:
    def test_full_round_trip(self):
        """from_garmin_api -> to_raw_dict should reproduce the input (with type normalization)."""
        r = from_garmin_api(SAMPLE_RAW, SAMPLE_DATE)
        d = to_raw_dict(r)

        for key in SAMPLE_RAW:
            if key not in _API_KEY_TO_FIELD:
                continue  # skip keys not in the model (e.g., "zone_ranges")
            expected = SAMPLE_RAW[key]
            actual = d[key]
            # to_num normalizes: 42.0 -> 42 (int), so compare values not types
            assert actual == expected, f"Key {key}: expected={expected!r} got={actual!r}"

    def test_sparse_round_trip_empty_strings(self):
        """Missing fields should become "" in raw dict (legacy compat)."""
        r = from_garmin_api(SPARSE_RAW, SPARSE_DATE)
        d = to_raw_dict(r)
        assert d["activity_name"] == ""
        assert d["zone_1"] == ""
        assert d["spo2_avg"] == ""


# ---------------------------------------------------------------------------
# Consistency: field order arrays match
# ---------------------------------------------------------------------------

class TestFieldOrderConsistency:
    def test_sheets_order_length(self):
        """_SHEETS_FIELD_ORDER + Day + Date must equal HEADERS length."""
        assert len(_SHEETS_FIELD_ORDER) + 2 == len(schema.HEADERS)

    def test_sqlite_order_matches_sheets(self):
        """SQLite and Sheets field orders should contain the same fields."""
        assert set(_SQLITE_FIELD_ORDER) == set(_SHEETS_FIELD_ORDER)

    def test_api_key_map_covers_all_data_fields(self):
        """Every data field in the model should have an API key mapping."""
        model_data_fields = set(GarminWellnessRecord.field_names()) - {"date"}
        mapped_fields = set(_API_KEY_TO_FIELD.values())
        assert model_data_fields == mapped_fields, (
            f"Unmapped fields: {model_data_fields - mapped_fields}, "
            f"Extra mappings: {mapped_fields - model_data_fields}"
        )
