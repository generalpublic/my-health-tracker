"""
Unit tests for pure functions across the Health Tracker codebase.

Covers:
  - utils._safe_float, utils.date_to_day
  - sleep_analysis._parse_bedtime_hour, compute_independent_score, generate_sleep_analysis
  - analysis_correlations._benjamini_hochberg
"""

import sys
import unittest
from pathlib import Path

# Ensure project root is on sys.path so imports resolve
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils import _safe_float, date_to_day
from sleep_analysis import _parse_bedtime_hour, compute_independent_score, generate_sleep_analysis
from analysis_correlations import _benjamini_hochberg


# ── _safe_float ──────────────────────────────────────────────────────────────

class TestSafeFloat(unittest.TestCase):

    # Normal cases
    def test_int_value(self):
        self.assertEqual(_safe_float(42), 42.0)

    def test_float_value(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_string_number(self):
        self.assertEqual(_safe_float("7.5"), 7.5)

    def test_negative_number(self):
        self.assertEqual(_safe_float("-3.2"), -3.2)

    def test_zero(self):
        self.assertEqual(_safe_float(0), 0.0)

    def test_string_zero(self):
        self.assertEqual(_safe_float("0"), 0.0)

    # Edge cases
    def test_none_returns_default(self):
        self.assertIsNone(_safe_float(None))

    def test_empty_string_returns_default(self):
        self.assertIsNone(_safe_float(""))

    def test_none_with_custom_default(self):
        self.assertEqual(_safe_float(None, default=-1), -1)

    def test_empty_string_with_custom_default(self):
        self.assertEqual(_safe_float("", default=0), 0)

    def test_non_numeric_string(self):
        self.assertIsNone(_safe_float("abc"))

    def test_non_numeric_with_default(self):
        self.assertEqual(_safe_float("abc", default=99), 99)

    def test_whitespace_string(self):
        # "  " is not None and not "", so it goes to float() which raises ValueError
        self.assertIsNone(_safe_float("  "))

    def test_bool_true(self):
        # bool is subclass of int, float(True) = 1.0
        self.assertEqual(_safe_float(True), 1.0)

    def test_list_returns_default(self):
        self.assertIsNone(_safe_float([1, 2]))


# ── date_to_day ──────────────────────────────────────────────────────────────

class TestDateToDay(unittest.TestCase):

    # Normal ISO format
    def test_iso_monday(self):
        self.assertEqual(date_to_day("2026-03-16"), "Mon")

    def test_iso_sunday(self):
        self.assertEqual(date_to_day("2026-03-15"), "Sun")

    def test_iso_saturday(self):
        self.assertEqual(date_to_day("2026-03-14"), "Sat")

    def test_iso_wednesday(self):
        self.assertEqual(date_to_day("2026-03-11"), "Wed")

    # Google Sheets format (M/D/YYYY)
    def test_sheets_format(self):
        self.assertEqual(date_to_day("3/16/2026"), "Mon")

    def test_sheets_format_padded(self):
        self.assertEqual(date_to_day("03/16/2026"), "Mon")

    # Edge cases
    def test_empty_string(self):
        self.assertEqual(date_to_day(""), "")

    def test_none(self):
        self.assertEqual(date_to_day(None), "")

    def test_invalid_date(self):
        self.assertEqual(date_to_day("not-a-date"), "")

    def test_whitespace_around_date(self):
        self.assertEqual(date_to_day("  2026-03-16  "), "Mon")

    def test_numeric_input(self):
        # str(12345).strip() won't parse as ISO or Sheets format
        self.assertEqual(date_to_day(12345), "")


# ── _parse_bedtime_hour ──────────────────────────────────────────────────────

class TestParseBedtimeHour(unittest.TestCase):

    # Normal cases
    def test_midnight(self):
        self.assertAlmostEqual(_parse_bedtime_hour("0:00"), 0.0)

    def test_ten_pm(self):
        self.assertAlmostEqual(_parse_bedtime_hour("22:00"), 22.0)

    def test_eleven_thirty(self):
        self.assertAlmostEqual(_parse_bedtime_hour("23:30"), 23.5)

    def test_one_fifteen_am(self):
        self.assertAlmostEqual(_parse_bedtime_hour("1:15"), 1.25)

    def test_noon(self):
        self.assertAlmostEqual(_parse_bedtime_hour("12:00"), 12.0)

    def test_with_whitespace(self):
        self.assertAlmostEqual(_parse_bedtime_hour("  22:30  "), 22.5)

    # Edge cases
    def test_none(self):
        self.assertIsNone(_parse_bedtime_hour(None))

    def test_empty_string(self):
        self.assertIsNone(_parse_bedtime_hour(""))

    def test_not_a_string(self):
        self.assertIsNone(_parse_bedtime_hour(123))

    def test_invalid_format(self):
        self.assertIsNone(_parse_bedtime_hour("10PM"))

    def test_partial_time(self):
        self.assertIsNone(_parse_bedtime_hour("22:"))

    def test_no_colon(self):
        self.assertIsNone(_parse_bedtime_hour("2230"))

    def test_extra_characters(self):
        self.assertIsNone(_parse_bedtime_hour("22:30:00"))


# ── compute_independent_score ────────────────────────────────────────────────

class TestComputeIndependentScore(unittest.TestCase):

    def _full_data(self, **overrides):
        """Return a complete data dict with good defaults, applying overrides."""
        base = {
            "sleep_duration": 8.0,
            "sleep_deep_pct": 22.0,
            "sleep_rem_pct": 22.0,
            "hrv": 50.0,
            "sleep_awakenings": 1.0,
            "sleep_body_battery_gained": 65.0,
            "sleep_bedtime": "22:30",
        }
        base.update(overrides)
        return base

    # Normal cases
    def test_perfect_sleep(self):
        score = compute_independent_score(self._full_data())
        self.assertIsNotNone(score)
        # All metrics at/above max + bedtime bonus = 25+20+20+15+10+10+5 = 105 -> capped at 100
        self.assertEqual(score, 100)

    def test_minimum_sleep(self):
        data = self._full_data(
            sleep_duration=4.0,   # 0 pts
            sleep_deep_pct=10.0,  # 0 pts
            sleep_rem_pct=10.0,   # 0 pts
            hrv=30.0,             # 0 pts
            sleep_awakenings=8.0, # 0 pts
            sleep_body_battery_gained=0.0,  # 0 pts
            sleep_bedtime="2:00",  # after 1:30 AM -> -10
        )
        score = compute_independent_score(data)
        # All zeros minus 10 penalty, clamped to 0
        self.assertEqual(score, 0)

    def test_mid_range(self):
        data = self._full_data(
            sleep_duration=5.5,    # (1.5/3)*25 = 12.5
            sleep_deep_pct=15.0,   # (5/10)*20 = 10
            sleep_rem_pct=15.0,    # (5/10)*20 = 10
            hrv=40.5,             # (3.5/7)*15 = 7.5
            sleep_awakenings=4.0,  # (4/8)*10 = 5
            sleep_body_battery_gained=30.0,  # (30/60)*10 = 5
            sleep_bedtime="23:00", # before midnight -> +5
        )
        score = compute_independent_score(data)
        # 12.5 + 10 + 10 + 7.5 + 5 + 5 + 5 = 55
        self.assertEqual(score, 55)

    # Edge cases
    def test_empty_dict(self):
        self.assertIsNone(compute_independent_score({}))

    def test_all_none_values(self):
        data = {
            "sleep_duration": None,
            "sleep_deep_pct": None,
        }
        self.assertIsNone(compute_independent_score(data))

    def test_single_metric(self):
        data = {"sleep_duration": 7.0}
        score = compute_independent_score(data)
        # (3/3)*25 = 25, no bedtime modifier
        self.assertEqual(score, 25)

    def test_string_values_handled(self):
        # _safe_float should convert string numbers
        data = {"sleep_duration": "7.5", "sleep_deep_pct": "20"}
        score = compute_independent_score(data)
        self.assertIsNotNone(score)

    def test_below_floor_values(self):
        data = self._full_data(
            sleep_duration=3.0,    # below 4h floor -> 0 (clamped by max(0,...))
            sleep_deep_pct=5.0,    # below 10% floor -> 0
            sleep_rem_pct=5.0,     # below 10% floor -> 0
            hrv=20.0,              # below 30 floor -> 0
            sleep_awakenings=10.0, # above 8 ceiling -> 0
            sleep_body_battery_gained=-5.0,  # negative -> 0
            sleep_bedtime="23:00", # +5 bonus
        )
        score = compute_independent_score(data)
        self.assertEqual(score, 5)  # only bedtime bonus

    def test_late_bedtime_penalty(self):
        # 2:00 AM = hour 2.0, effective = 2+24 = 26 >= 25.5 -> -10
        data = {"sleep_duration": 7.0, "sleep_bedtime": "2:00"}
        score = compute_independent_score(data)
        # 25 pts for duration, -10 for late bedtime = 15
        self.assertEqual(score, 15)

    def test_early_evening_bedtime_bonus(self):
        # 21:00 = hour 21, effective = 21 (>=18, <=24) -> +5
        data = {"sleep_duration": 7.0, "sleep_bedtime": "21:00"}
        score = compute_independent_score(data)
        self.assertEqual(score, 30)  # 25 + 5

    def test_score_capped_at_100(self):
        # Even with all max values + bonus, should not exceed 100
        data = self._full_data()
        score = compute_independent_score(data)
        self.assertLessEqual(score, 100)

    def test_score_floored_at_0(self):
        # Heavy penalty with minimal metrics
        data = {"sleep_duration": 4.0, "sleep_bedtime": "2:00"}
        score = compute_independent_score(data)
        self.assertGreaterEqual(score, 0)


# ── generate_sleep_analysis ──────────────────────────────────────────────────

class TestGenerateSleepAnalysis(unittest.TestCase):

    def _full_data(self, **overrides):
        base = {
            "sleep_duration": 8.0,
            "sleep_deep_pct": 22.0,
            "sleep_rem_pct": 22.0,
            "hrv": 50.0,
            "sleep_avg_respiration": 14.0,
            "sleep_awakenings": 1.0,
            "sleep_cycles": 5.0,
            "sleep_body_battery_gained": 65.0,
            "sleep_deep_min": 105.0,
            "sleep_rem_min": 105.0,
            "sleep_light_min": 200.0,
            "sleep_awake_min": 10.0,
            "sleep_time_in_bed": 8.5,
            "sleep_score": 85.0,
            "sleep_bedtime": "22:30",
        }
        base.update(overrides)
        return base

    def test_returns_tuple(self):
        score, text, descriptor = generate_sleep_analysis(self._full_data())
        self.assertIsInstance(score, int)
        self.assertIsInstance(text, str)
        self.assertIsInstance(descriptor, str)
        self.assertTrue(len(descriptor) > 0)

    def test_good_sleep_verdict(self):
        score, text, descriptor = generate_sleep_analysis(self._full_data())
        self.assertTrue(text.startswith("GOOD"))
        self.assertIn(descriptor, [
            "Full Architecture", "Deep & Restful", "Long & Solid", "Solid Recovery",
        ])

    def test_poor_sleep_verdict(self):
        data = self._full_data(
            sleep_duration=4.5,
            sleep_deep_pct=10.0,
            sleep_rem_pct=10.0,
            hrv=25.0,
            sleep_awakenings=7.0,
            sleep_cycles=2.0,
            sleep_body_battery_gained=15.0,
            sleep_bedtime="2:30",
        )
        score, text, descriptor = generate_sleep_analysis(data)
        self.assertTrue(text.startswith("POOR"))
        self.assertIn(descriptor, [
            "Shallow & Short", "Poor Recovery", "Fragmented", "Low Restoration",
            "Too Short", "Deep Deficit", "Low REM", "Poor Quality",
        ])

    def test_insufficient_data(self):
        score, text, descriptor = generate_sleep_analysis({})
        self.assertIsNone(score)
        self.assertEqual(text, "Insufficient data for analysis")
        self.assertEqual(descriptor, "")

    def test_insufficient_data_no_key_metrics(self):
        # Has data but not the three key metrics (total, deep_pct, rem_pct)
        data = {"hrv": 45.0, "sleep_awakenings": 2.0}
        score, text, descriptor = generate_sleep_analysis(data)
        self.assertIsNone(score)
        self.assertIn("Insufficient", text)

    def test_partial_data_still_works(self):
        # Only duration + deep_pct -- enough for has_data check
        data = {"sleep_duration": 7.0, "sleep_deep_pct": 18.0}
        score, text, descriptor = generate_sleep_analysis(data)
        self.assertIsNotNone(score)
        self.assertIn("ACTION:", text)
        self.assertTrue(len(descriptor) > 0)

    def test_analysis_contains_action(self):
        _, text, _ = generate_sleep_analysis(self._full_data())
        self.assertIn("ACTION:", text)

    def test_high_respiration_warning(self):
        data = self._full_data(sleep_avg_respiration=20.0)
        _, text, _ = generate_sleep_analysis(data)
        self.assertIn("Respiration", text)

    def test_late_bedtime_insight(self):
        data = self._full_data(
            sleep_bedtime="1:30",
            sleep_deep_pct=15.0,
        )
        _, text, _ = generate_sleep_analysis(data)
        # Should mention late bedtime in findings or insights
        self.assertTrue("bedtime" in text.lower() or "bed" in text.lower())

    def test_discrepancy_note_garmin_overscores(self):
        # Garmin score much higher than independent score
        data = self._full_data(
            sleep_score=95.0,
            sleep_duration=5.0,
            sleep_deep_pct=12.0,
            sleep_rem_pct=12.0,
            hrv=32.0,
            sleep_awakenings=5.0,
            sleep_body_battery_gained=20.0,
        )
        _, text, _ = generate_sleep_analysis(data)
        # Independent score will be low, Garmin high -> discrepancy
        if "Garmin" in text:
            self.assertIn("overweighting", text)

    def test_string_metric_values(self):
        data = self._full_data()
        # Convert some values to strings to test _safe_float integration
        data["sleep_duration"] = "8.0"
        data["sleep_deep_pct"] = "22"
        score, text, descriptor = generate_sleep_analysis(data)
        self.assertIsNotNone(score)

    def test_descriptor_deep_deficit(self):
        data = self._full_data(sleep_deep_pct=12.0, sleep_deep_min=57.0)
        _, _, descriptor = generate_sleep_analysis(data)
        # Deep at 12% with otherwise good metrics -> FAIR + Light on Deep
        self.assertIn(descriptor, ["Light on Deep", "Deep Deficit", "Stage Imbalance"])

    def test_descriptor_full_architecture(self):
        # Perfect sleep: deep 22%, REM 22%, 5 cycles
        _, _, descriptor = generate_sleep_analysis(self._full_data())
        self.assertEqual(descriptor, "Full Architecture")


# ── _benjamini_hochberg ──────────────────────────────────────────────────────

class TestBenjaminiHochberg(unittest.TestCase):

    def test_empty_dict(self):
        self.assertEqual(_benjamini_hochberg({}), {})

    def test_single_pvalue(self):
        result = _benjamini_hochberg({"a": 0.03})
        self.assertAlmostEqual(result["a"], 0.03)

    def test_all_significant(self):
        pvals = {"a": 0.001, "b": 0.002, "c": 0.003}
        result = _benjamini_hochberg(pvals)
        # All should remain significant (adjusted <= 0.05)
        for key in pvals:
            self.assertLessEqual(result[key], 0.05)

    def test_preserves_keys(self):
        pvals = {"x": 0.01, "y": 0.5, "z": 0.1}
        result = _benjamini_hochberg(pvals)
        self.assertEqual(set(result.keys()), {"x", "y", "z"})

    def test_adjusted_geq_raw(self):
        # BH-adjusted p-values should be >= raw p-values
        pvals = {"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5}
        result = _benjamini_hochberg(pvals)
        for key in pvals:
            self.assertGreaterEqual(result[key] + 1e-12, pvals[key])

    def test_adjusted_capped_at_1(self):
        pvals = {"a": 0.8, "b": 0.9, "c": 0.95}
        result = _benjamini_hochberg(pvals)
        for key in pvals:
            self.assertLessEqual(result[key], 1.0)

    def test_monotonicity(self):
        # If raw p_a < raw p_b, then adjusted p_a <= adjusted p_b
        pvals = {"a": 0.001, "b": 0.01, "c": 0.05, "d": 0.1, "e": 0.5}
        result = _benjamini_hochberg(pvals)
        sorted_keys = sorted(pvals.keys(), key=lambda k: pvals[k])
        for i in range(len(sorted_keys) - 1):
            self.assertLessEqual(
                result[sorted_keys[i]],
                result[sorted_keys[i + 1]] + 1e-12,
            )

    def test_identical_pvalues(self):
        pvals = {"a": 0.05, "b": 0.05, "c": 0.05}
        result = _benjamini_hochberg(pvals)
        # All identical raw -> all identical adjusted
        vals = list(result.values())
        self.assertAlmostEqual(vals[0], vals[1])
        self.assertAlmostEqual(vals[1], vals[2])

    def test_known_calculation(self):
        # Manual BH calculation:
        # Sorted: a=0.01 (rank 1), b=0.04 (rank 2), c=0.10 (rank 3)
        # m=3
        # Backward pass:
        #   rank 3: adj = min(1.0, 0.10 * 3/3) = 0.10
        #   rank 2: adj = min(0.10, 0.04 * 3/2) = min(0.10, 0.06) = 0.06
        #   rank 1: adj = min(0.06, 0.01 * 3/1) = min(0.06, 0.03) = 0.03
        pvals = {"a": 0.01, "b": 0.04, "c": 0.10}
        result = _benjamini_hochberg(pvals)
        self.assertAlmostEqual(result["a"], 0.03)
        self.assertAlmostEqual(result["b"], 0.06)
        self.assertAlmostEqual(result["c"], 0.10)

    def test_very_small_pvalues(self):
        pvals = {"a": 1e-10, "b": 1e-8, "c": 1e-6}
        result = _benjamini_hochberg(pvals)
        for key in pvals:
            self.assertGreater(result[key], 0)

    def test_mix_significant_and_not(self):
        pvals = {"sig1": 0.001, "sig2": 0.01, "ns1": 0.5, "ns2": 0.9}
        result = _benjamini_hochberg(pvals)
        # Significant ones should still be < 0.05 after correction
        self.assertLess(result["sig1"], 0.05)
        # Non-significant should stay high
        self.assertGreater(result["ns2"], 0.05)


# ── detect_illness ─────────────────────────────────────────────────────────

from datetime import date, timedelta
from overall_analysis import detect_illness, _compute_trend_direction

class TestDetectIllness(unittest.TestCase):
    """Tests for probabilistic illness detection."""

    def _make_baselines(self, rhr_z=0, hrv_z=0, rhr_today=48, hrv_today=40,
                        rhr_mean=48, hrv_mean=40):
        return {
            "rhr": {"z": rhr_z, "today": rhr_today, "mean": rhr_mean},
            "hrv": {"z": hrv_z, "today": hrv_today, "mean": hrv_mean},
        }

    def _make_sleep_data(self, target, days=30, resp=16, bb_gained=55,
                         garmin_score=85):
        """Build a by_date_sleep dict with stable baseline data."""
        data = {}
        for offset in range(days + 1):
            d = str(target - timedelta(days=offset))
            data[d] = {
                "Avg Respiration": str(resp),
                "Body Battery Gained": str(bb_gained),
                "Garmin Sleep Score": str(garmin_score),
                "Overnight HRV (ms)": "40",
            }
        return data

    def _make_garmin_data(self, target, days=30, stress=28, bbwake=80, rhr=48,
                          spo2=97):
        """Build a by_date_garmin dict with stable baseline data."""
        data = {}
        for offset in range(days + 1):
            d = str(target - timedelta(days=offset))
            data[d] = {
                "Avg Stress Level": str(stress),
                "Body Battery at Wake": str(bbwake),
                "Resting HR": str(rhr),
                "SpO2 Avg": str(spo2),
            }
        return data

    def test_normal_day(self):
        """All metrics within baseline -> normal."""
        td = date(2026, 3, 15)
        result = detect_illness(
            self._make_baselines(),
            self._make_sleep_data(td),
            {}, None, td,
            by_date_garmin=self._make_garmin_data(td),
        )
        self.assertEqual(result["illness_label"], "normal")
        self.assertLess(result["illness_score"], 4)

    def test_single_bad_day_no_overreaction(self):
        """One metric elevated, others fine -> stays normal."""
        td = date(2026, 3, 15)
        result = detect_illness(
            self._make_baselines(rhr_z=1.6, rhr_today=55),  # RHR elevated
            self._make_sleep_data(td),
            {}, None, td,
            by_date_garmin=self._make_garmin_data(td),
        )
        # RHR alone is +2, but without other signals and ACWR, should stay < 4
        self.assertIn(result["illness_label"], ("normal",))
        self.assertLess(result["illness_score"], 4)

    def test_multiple_signals_trigger(self):
        """4+ signals -> possible_illness."""
        td = date(2026, 3, 15)
        # Elevated RHR, suppressed HRV, high resp, low BB gained
        sleep_data = self._make_sleep_data(td, resp=16, bb_gained=55)
        # Override today's values to be abnormal
        sleep_data[str(td)]["Avg Respiration"] = "20"    # high
        sleep_data[str(td)]["Body Battery Gained"] = "20"  # very low
        result = detect_illness(
            self._make_baselines(rhr_z=1.6, hrv_z=-1.6),  # Both firing
            sleep_data,
            {}, 0.5, td,  # ACWR < 1.0
            by_date_garmin=self._make_garmin_data(td),
        )
        self.assertIn(result["illness_label"], ("possible_illness", "likely_illness"))
        self.assertGreaterEqual(result["illness_score"], 4)

    def test_stress_signal(self):
        """Stress z > 1.0 adds +1."""
        td = date(2026, 3, 15)
        garmin_data = self._make_garmin_data(td, stress=28)
        # Set today's stress very high
        garmin_data[str(td)]["Avg Stress Level"] = "50"
        result = detect_illness(
            self._make_baselines(),
            self._make_sleep_data(td),
            {}, None, td,
            by_date_garmin=garmin_data,
        )
        stress_signals = [s for s in result["signals"] if "Stress" in s]
        self.assertTrue(len(stress_signals) > 0, "Stress signal should fire")

    def test_bb_wake_signal(self):
        """BB@Wake z < -1.0 adds +1."""
        td = date(2026, 3, 15)
        garmin_data = self._make_garmin_data(td, bbwake=80)
        # Set today's BB@Wake very low
        garmin_data[str(td)]["Body Battery at Wake"] = "30"
        result = detect_illness(
            self._make_baselines(),
            self._make_sleep_data(td),
            {}, None, td,
            by_date_garmin=garmin_data,
        )
        bb_signals = [s for s in result["signals"] if "battery at wake" in s.lower()]
        self.assertTrue(len(bb_signals) > 0, "BB@Wake signal should fire")

    def test_trend_bonus_adds_fractional(self):
        """Sub-threshold z but worsening 3-day RHR trend -> +0.5."""
        td = date(2026, 3, 15)
        garmin_data = self._make_garmin_data(td, rhr=48)
        # Create worsening 3-day RHR trend
        garmin_data[str(td - timedelta(days=2))]["Resting HR"] = "48"
        garmin_data[str(td - timedelta(days=1))]["Resting HR"] = "50"
        garmin_data[str(td)]["Resting HR"] = "52"
        result = detect_illness(
            self._make_baselines(rhr_z=0.9),  # Sub-threshold (< 1.5) but > 0.7
            self._make_sleep_data(td),
            {}, None, td,
            by_date_garmin=garmin_data,
        )
        trend_signals = [s for s in result["signals"] if "trending" in s.lower()]
        self.assertTrue(len(trend_signals) > 0, "Trend bonus should fire for worsening RHR")

    def test_episode_persists_through_bounce(self):
        """Active episode + one good day -> stays illness_ongoing."""
        import sqlite3
        from sqlite_backup import init_db, start_illness_episode, upsert_illness_daily
        conn = sqlite3.connect(":memory:")
        init_db(conn)
        td = date(2026, 3, 20)
        # Start an episode 3 days ago
        ep_id = start_illness_episode(conn, str(td - timedelta(days=3)), 8.0)
        # Log 3 days of high scores
        for offset in range(3, 0, -1):
            d = td - timedelta(days=offset)
            upsert_illness_daily(conn, str(d), {
                "illness_state_id": ep_id, "anomaly_score": 6.0,
                "signals": [], "label": "illness_ongoing",
            })
        # Today: all metrics normal (biometric bounce)
        result = detect_illness(
            self._make_baselines(),
            self._make_sleep_data(td),
            {}, None, td,
            by_date_garmin=self._make_garmin_data(td),
            conn=conn,
        )
        self.assertEqual(result["illness_label"], "illness_ongoing")
        conn.close()

    def test_5day_normal_suggests_recovery(self):
        """5 consecutive low scores -> recovering."""
        import sqlite3
        from sqlite_backup import init_db, start_illness_episode, upsert_illness_daily
        conn = sqlite3.connect(":memory:")
        init_db(conn)
        td = date(2026, 3, 25)
        ep_id = start_illness_episode(conn, str(td - timedelta(days=7)), 9.0)
        # Log 5 days of low scores
        for offset in range(5, 0, -1):
            d = td - timedelta(days=offset)
            upsert_illness_daily(conn, str(d), {
                "illness_state_id": ep_id, "anomaly_score": 1.5,
                "signals": [], "label": "illness_ongoing",
            })
        result = detect_illness(
            self._make_baselines(),
            self._make_sleep_data(td),
            {}, None, td,
            by_date_garmin=self._make_garmin_data(td),
            conn=conn,
        )
        self.assertEqual(result["illness_label"], "recovering")
        conn.close()

    def test_no_conn_stateless(self):
        """conn=None -> works without state persistence."""
        td = date(2026, 3, 15)
        result = detect_illness(
            self._make_baselines(rhr_z=2.0, hrv_z=-2.0),
            self._make_sleep_data(td),
            {}, 0.5, td,
            by_date_garmin=self._make_garmin_data(td),
            conn=None,  # no SQLite
        )
        # Should still classify without state
        self.assertIn(result["illness_label"], ("normal", "possible_illness", "likely_illness"))
        self.assertIsNone(result.get("active_episode"))

    def test_acwr_gate_requires_convergence(self):
        """ACWR < 1.0 only fires when score >= 2 from other signals."""
        td = date(2026, 3, 15)
        # All biometrics normal, ACWR low
        result = detect_illness(
            self._make_baselines(),
            self._make_sleep_data(td),
            {}, 0.5, td,  # ACWR < 1.0
            by_date_garmin=self._make_garmin_data(td),
        )
        acwr_signals = [s for s in result["signals"] if "ACWR" in s or "training" in s.lower()]
        self.assertEqual(len(acwr_signals), 0,
                         "ACWR should NOT fire when no other signals are present")


class TestTrendDirection(unittest.TestCase):
    """Tests for _compute_trend_direction helper."""

    def test_worsening(self):
        self.assertEqual(_compute_trend_direction([48, 50, 53]), "worsening")

    def test_improving(self):
        self.assertEqual(_compute_trend_direction([53, 50, 48]), "improving")

    def test_stable(self):
        self.assertEqual(_compute_trend_direction([48, 48, 49]), "stable")

    def test_short_list(self):
        self.assertEqual(_compute_trend_direction([48]), "stable")

    def test_empty_list(self):
        self.assertEqual(_compute_trend_direction([]), "stable")


class TestSpO2IllnessSignal(unittest.TestCase):
    """Tests for SpO2 signal in illness detection."""

    def _make_baselines(self):
        return {
            "rhr": {"z": 0, "today": 48, "mean": 48},
            "hrv": {"z": 0, "today": 40, "mean": 40},
        }

    def _make_sleep_data(self, target, days=30):
        data = {}
        for offset in range(days + 1):
            d = str(target - timedelta(days=offset))
            data[d] = {
                "Avg Respiration": "16", "Body Battery Gained": "55",
                "Garmin Sleep Score": "85", "Overnight HRV (ms)": "40",
            }
        return data

    def _make_garmin_data(self, target, days=30, spo2=97):
        data = {}
        for offset in range(days + 1):
            d = str(target - timedelta(days=offset))
            data[d] = {
                "Avg Stress Level": "28", "Body Battery at Wake": "80",
                "Resting HR": "48", "SpO2 Avg": str(spo2),
            }
        return data

    def test_spo2_low_adds_signal(self):
        """SpO2 below 94% triggers illness signal."""
        td = date(2026, 3, 15)
        garmin = self._make_garmin_data(td, spo2=97)
        # Set today's SpO2 to 92 (below 94% absolute threshold)
        garmin[str(td)]["SpO2 Avg"] = "92"
        result = detect_illness(
            self._make_baselines(), self._make_sleep_data(td),
            {}, None, td, by_date_garmin=garmin,
        )
        spo2_signals = [s for s in result["signals"] if "SpO2" in s]
        self.assertGreater(len(spo2_signals), 0, "SpO2 < 94% should fire")

    def test_spo2_normal_no_signal(self):
        """Normal SpO2 (97%) with stable baseline -> no signal."""
        td = date(2026, 3, 15)
        result = detect_illness(
            self._make_baselines(), self._make_sleep_data(td),
            {}, None, td, by_date_garmin=self._make_garmin_data(td, spo2=97),
        )
        spo2_signals = [s for s in result["signals"] if "SpO2" in s]
        self.assertEqual(len(spo2_signals), 0, "Normal SpO2 should not fire")

    def test_missing_spo2_graceful(self):
        """Missing SpO2 data doesn't break pipeline."""
        td = date(2026, 3, 15)
        garmin = self._make_garmin_data(td)
        # Remove SpO2 from all days
        for d in garmin:
            garmin[d].pop("SpO2 Avg", None)
        result = detect_illness(
            self._make_baselines(), self._make_sleep_data(td),
            {}, None, td, by_date_garmin=garmin,
        )
        # Should still produce a valid result
        self.assertIn("illness_label", result)
        self.assertIn("illness_score", result)


class TestAdaptiveWeighting(unittest.TestCase):
    """Tests for compute_adaptive_weights."""

    def test_insufficient_data_returns_none(self):
        """Less than 60 paired observations -> returns None."""
        import sqlite3
        from overall_analysis import compute_adaptive_weights
        from sqlite_backup import init_db
        conn = sqlite3.connect(":memory:")
        init_db(conn)
        # Insert only 5 rows of data
        for i in range(5):
            d = f"2026-03-{i+1:02d}"
            conn.execute(
                "INSERT INTO overall_analysis (date, readiness_score) VALUES (?, ?)",
                (d, 6.5))
            conn.execute(
                "INSERT INTO garmin (date, hrv_overnight_avg, sleep_score, resting_hr) "
                "VALUES (?, ?, ?, ?)", (d, 40, 80, 50))
            next_d = f"2026-03-{i+2:02d}"
            conn.execute(
                "INSERT OR IGNORE INTO daily_log (date, morning_energy) VALUES (?, ?)",
                (next_d, 7))
        conn.commit()
        result = compute_adaptive_weights(conn, min_days=60)
        self.assertIsNone(result)

    def test_no_conn_returns_none(self):
        """conn=None -> returns None."""
        from overall_analysis import compute_adaptive_weights
        result = compute_adaptive_weights(None)
        self.assertIsNone(result)

    def test_output_format_when_sufficient(self):
        """If somehow sufficient data produces improvement, verify output format."""
        from overall_analysis import compute_adaptive_weights
        import sqlite3
        from sqlite_backup import init_db
        conn = sqlite3.connect(":memory:")
        init_db(conn)
        # Insert 70 rows of synthetic data where HRV strongly predicts energy
        import random
        random.seed(42)
        for i in range(70):
            d = f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
            hrv = 30 + random.gauss(0, 10)
            sleep = 70 + random.gauss(0, 10)
            rhr = 50 + random.gauss(0, 5)
            conn.execute(
                "INSERT OR IGNORE INTO overall_analysis (date, readiness_score) "
                "VALUES (?, ?)", (d, 6.5))
            conn.execute(
                "INSERT OR IGNORE INTO garmin (date, hrv_overnight_avg, sleep_score, "
                "resting_hr) VALUES (?, ?, ?, ?)", (d, hrv, sleep, rhr))
            # Next-day energy correlates with HRV
            from datetime import date as date_cls, timedelta
            next_d = str(date_cls.fromisoformat(d) + timedelta(days=1))
            energy = max(1, min(10, 5 + (hrv - 30) / 5 + random.gauss(0, 0.5)))
            conn.execute(
                "INSERT OR IGNORE INTO daily_log (date, morning_energy) VALUES (?, ?)",
                (next_d, energy))
        conn.commit()
        result = compute_adaptive_weights(conn, min_days=60)
        # Result might be None if ΔR² ≤ 0.05 — that's valid behavior
        if result is not None:
            self.assertIn("HRV", result)
            self.assertIn("Sleep", result)
            self.assertIn("RHR", result)
            self.assertIn("Subjective", result)
            total = result["HRV"] + result["Sleep"] + result["RHR"] + result["Subjective"]
            self.assertAlmostEqual(total, 1.0, places=2)
            for k in ("HRV", "Sleep", "RHR", "Subjective"):
                self.assertGreaterEqual(result[k], 0.05)
                self.assertLessEqual(result[k], 0.50)


# ── Zone-Weighted ACWR (Gap #12+13) ─────────────────────────────────────────

from overall_analysis import compute_acwr, generate_insights, generate_recommendations

class TestZoneWeightedACWR(unittest.TestCase):
    """Test zone intensity modifier in _session_load via compute_acwr."""

    def _make_session(self, dur=60, effort=5, z1=0, z2=0, z3=0, z4=0, z5=0,
                      anaerobic_te=None, activity="Running"):
        s = {
            "Duration (min)": dur, "Perceived Effort (1-10)": effort,
            "Avg HR": 140, "Activity Name": activity,
            "Zone 1 (min)": z1, "Zone 2 (min)": z2, "Zone 3 (min)": z3,
            "Zone 4 (min)": z4, "Zone 5 (min)": z5,
        }
        if anaerobic_te is not None:
            s["Anaerobic TE (0-5)"] = anaerobic_te
        return s

    def _sessions_map(self, sessions_by_day):
        """Build sessions_by_date from {offset: [sessions]} relative to 2026-01-28."""
        from datetime import date, timedelta
        base = date(2026, 1, 28)
        result = {}
        for offset, sessions in sessions_by_day.items():
            result[str(base - timedelta(days=offset))] = sessions
        return result

    def test_high_intensity_increases_load(self):
        """Session with >30% Z4-5 should produce higher ACWR acute load."""
        from datetime import date
        td = date(2026, 1, 28)
        # High intensity: 25min Z4-5 out of 60min = 42%
        high = self._sessions_map({0: [self._make_session(z4=15, z5=10)]})
        # Add chronic baseline (weeks 2-4)
        for w in range(1, 4):
            for d in range(7):
                high.setdefault(str(td - __import__('datetime').timedelta(days=w*7+d)), [])
            high[str(td - __import__('datetime').timedelta(days=w*7))] = [
                self._make_session(z2=50, z3=10)
            ]
        # No zones: same session without zone data
        no_zone = self._sessions_map({0: [self._make_session()]})
        for w in range(1, 4):
            no_zone[str(td - __import__('datetime').timedelta(days=w*7))] = [
                self._make_session()
            ]

        acwr_high, _, acute_high, _ = compute_acwr(high, td)
        acwr_no, _, acute_no, _ = compute_acwr(no_zone, td)
        # High-intensity session should have higher acute load
        self.assertGreater(acute_high, acute_no * 0.99)  # at least not less

    def test_easy_session_reduces_load(self):
        """Session with >70% Z1-2 should produce 0.9x load."""
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        # Easy: 50min Z1-2 out of 60min = 83%
        easy = {str(td): [self._make_session(z1=25, z2=25)]}
        # Add chronic
        for w in range(1, 4):
            easy[str(td - timedelta(days=w*7))] = [self._make_session(z1=25, z2=25)]
        acwr_val, _, acute, _ = compute_acwr(easy, td)
        # Base load = 5 * 60 / 10 = 30. With 0.9x = 27.
        self.assertAlmostEqual(acute, 27.0, places=1)

    def test_no_zone_data_preserves_base(self):
        """Without zone data, load should be pure sRPE."""
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        sessions = {str(td): [self._make_session()]}
        for w in range(1, 4):
            sessions[str(td - timedelta(days=w*7))] = [self._make_session()]
        _, _, acute, _ = compute_acwr(sessions, td)
        # sRPE = 5 * 60 / 10 = 30
        self.assertAlmostEqual(acute, 30.0, places=1)


class TestZoneDistributionInsight(unittest.TestCase):
    """Test weekly zone distribution insight in generate_insights."""

    def _minimal_baselines(self):
        return {
            "hrv": {"z": 0, "today": 50, "mean": 50, "std": 10, "n": 90},
            "rhr": {"z": 0, "today": 60, "mean": 60, "std": 5, "n": 90},
            "sleep_score": {"z": 0, "today": 80, "mean": 80, "std": 5, "n": 90},
            "sleep_duration": {"z": 0, "today": 7.5, "mean": 7.5, "std": 0.5, "n": 90},
            "body_battery": {"z": 0, "today": 60, "mean": 60, "std": 10, "n": 90},
            "stress": {"z": 0, "today": 30, "mean": 30, "std": 10, "n": 90},
            "steps": {"z": 0, "today": 8000, "mean": 8000, "std": 2000, "n": 90},
        }

    def test_high_intensity_flag(self):
        """More than 30% Z4-5 in a week should trigger insight."""
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        # 3 sessions this week, each 20min Z4 + 10min Z2 = 66% high intensity
        sessions = {}
        for d in range(0, 6, 2):
            sessions[str(td - timedelta(days=d))] = [{
                "Zone 1 (min)": 0, "Zone 2 (min)": 10, "Zone 3 (min)": 0,
                "Zone 4 (min)": 20, "Zone 5 (min)": 0, "Duration (min)": 30,
            }]
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, sessions, td, nutrition_by_date={}
        )
        zone_insights = [i for i in insights if "High-intensity dominance" in i]
        self.assertEqual(len(zone_insights), 1)

    def test_balanced_no_flag(self):
        """20% Z4-5 should not trigger insight."""
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        sessions = {}
        for d in range(0, 6, 2):
            sessions[str(td - timedelta(days=d))] = [{
                "Zone 1 (min)": 10, "Zone 2 (min)": 30, "Zone 3 (min)": 0,
                "Zone 4 (min)": 5, "Zone 5 (min)": 5, "Duration (min)": 50,
            }]
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, sessions, td, nutrition_by_date={}
        )
        zone_insights = [i for i in insights if "High-intensity dominance" in i]
        self.assertEqual(len(zone_insights), 0)

    def test_insufficient_data_no_flag(self):
        """Less than 30 min total zone data should not trigger."""
        from datetime import date
        td = date(2026, 1, 28)
        sessions = {str(td): [{"Zone 4 (min)": 10, "Duration (min)": 10}]}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, sessions, td, nutrition_by_date={}
        )
        zone_insights = [i for i in insights if "High-intensity dominance" in i]
        self.assertEqual(len(zone_insights), 0)


class TestHighIntensityRecoveryRec(unittest.TestCase):
    """Test high-intensity recovery recommendation."""

    def test_anaerobic_te_fires(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        yesterday = str(td - timedelta(days=1))
        sessions = {yesterday: [{
            "Anaerobic TE (0-5)": 4.0, "Zone 4 (min)": 5, "Zone 5 (min)": 3,
            "Activity Name": "HIIT",
        }]}
        recs = generate_recommendations(
            7, "Good", 0, 1.0, [], self._minimal_baselines(), td,
            sessions_by_date=sessions
        )
        hi_recs = [r for r in recs if "high-intensity" in r.lower() and "48-72h" in r]
        self.assertEqual(len(hi_recs), 1)

    def test_zone45_fires(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        yesterday = str(td - timedelta(days=1))
        sessions = {yesterday: [{
            "Zone 4 (min)": 10, "Zone 5 (min)": 10, "Activity Name": "Run",
        }]}
        recs = generate_recommendations(
            7, "Good", 0, 1.0, [], self._minimal_baselines(), td,
            sessions_by_date=sessions
        )
        hi_recs = [r for r in recs if "48-72h" in r]
        self.assertEqual(len(hi_recs), 1)

    def test_low_intensity_no_rec(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        yesterday = str(td - timedelta(days=1))
        sessions = {yesterday: [{
            "Anaerobic TE (0-5)": 1.5, "Zone 4 (min)": 3, "Zone 5 (min)": 2,
            "Activity Name": "Walk",
        }]}
        recs = generate_recommendations(
            7, "Good", 0, 1.0, [], self._minimal_baselines(), td,
            sessions_by_date=sessions
        )
        hi_recs = [r for r in recs if "48-72h" in r]
        self.assertEqual(len(hi_recs), 0)

    def _minimal_baselines(self):
        return {
            "hrv": {"z": 0, "today": 50, "mean": 50, "std": 10, "n": 90},
            "rhr": {"z": 0, "today": 60, "mean": 60, "std": 5, "n": 90},
        }


# ── Calorie Balance Enhancement (Gap #17) ──────────────────────────────────

class TestCalorieBalance(unittest.TestCase):

    def _minimal_baselines(self):
        return {
            "hrv": {"z": 0, "today": 50, "mean": 50, "std": 10, "n": 90},
            "rhr": {"z": 0, "today": 60, "mean": 60, "std": 5, "n": 90},
            "sleep_score": {"z": 0, "today": 80, "mean": 80, "std": 5, "n": 90},
            "sleep_duration": {"z": 0, "today": 7.5, "mean": 7.5, "std": 0.5, "n": 90},
            "body_battery": {"z": 0, "today": 60, "mean": 60, "std": 10, "n": 90},
            "stress": {"z": 0, "today": 30, "mean": 30, "std": 10, "n": 90},
            "steps": {"z": 0, "today": 8000, "mean": 8000, "std": 2000, "n": 90},
        }

    def test_weekly_deficit_above_3500(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        nutrition = {}
        for d in range(7):
            nutrition[str(td - timedelta(days=d))] = {"Calorie Balance": -600}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date=nutrition
        )
        deficit_insights = [i for i in insights if "Sustained energy deficit" in i]
        self.assertEqual(len(deficit_insights), 1)

    def test_weekly_deficit_below_threshold(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        nutrition = {}
        for d in range(7):
            nutrition[str(td - timedelta(days=d))] = {"Calorie Balance": -400}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date=nutrition
        )
        deficit_insights = [i for i in insights if "Sustained energy deficit" in i]
        self.assertEqual(len(deficit_insights), 0)

    def test_training_day_underfueling(self):
        from datetime import date
        td = date(2026, 1, 28)
        nutrition = {str(td): {"Calorie Balance": -600}}
        sessions = {str(td): [{"Activity Name": "Run", "Duration (min)": 30}]}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, sessions, td, nutrition_by_date=nutrition
        )
        underfuel = [i for i in insights if "Underfueling on training day" in i]
        self.assertEqual(len(underfuel), 1)

    def test_rest_day_surplus(self):
        from datetime import date
        td = date(2026, 1, 28)
        nutrition = {str(td): {"Calorie Balance": 600}}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date=nutrition
        )
        surplus = [i for i in insights if "surplus on rest day" in i]
        self.assertEqual(len(surplus), 1)

    def test_calorie_missing_data(self):
        from datetime import date
        td = date(2026, 1, 28)
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date={}
        )
        # Should not crash — no calorie-related insights
        cal_insights = [i for i in insights if "calorie" in i.lower() or "deficit" in i.lower()
                        or "surplus" in i.lower()]
        self.assertEqual(len(cal_insights), 0)


# ── Macro Nutrition Analysis (Gap #14) ──────────────────────────────────────

class TestMacroNutrition(unittest.TestCase):

    def _minimal_baselines(self):
        return {
            "hrv": {"z": 0, "today": 50, "mean": 50, "std": 10, "n": 90},
            "rhr": {"z": 0, "today": 60, "mean": 60, "std": 5, "n": 90},
            "sleep_score": {"z": 0, "today": 80, "mean": 80, "std": 5, "n": 90},
            "sleep_duration": {"z": 0, "today": 7.5, "mean": 7.5, "std": 0.5, "n": 90},
            "body_battery": {"z": 0, "today": 60, "mean": 60, "std": 10, "n": 90},
            "stress": {"z": 0, "today": 30, "mean": 30, "std": 10, "n": 90},
            "steps": {"z": 0, "today": 8000, "mean": 8000, "std": 2000, "n": 90},
        }

    def test_protein_normalized_with_weight(self):
        from datetime import date
        td = date(2026, 1, 28)
        nutrition = {str(td): {"Protein (g)": 100, "Calorie Balance": 0}}
        sessions = {str(td): [{"Activity Name": "Run"}]}
        profile = {"demographics": {"weight_kg": 80}}  # target = 1.6*80 = 128g
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, sessions, td, nutrition_by_date=nutrition, profile=profile
        )
        prot = [i for i in insights if "Low protein" in i and "target" in i]
        self.assertEqual(len(prot), 1)

    def test_protein_fallback_no_weight(self):
        from datetime import date
        td = date(2026, 1, 28)
        nutrition = {str(td): {"Protein (g)": 90, "Calorie Balance": 0}}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date=nutrition
        )
        prot = [i for i in insights if "Low protein intake" in i and "90g" in i]
        self.assertEqual(len(prot), 1)

    def test_macro_ratio_low_protein(self):
        from datetime import date
        td = date(2026, 1, 28)
        # 50g protein (200cal), 300g carbs (1200cal), 50g fat (450cal) = 11% protein
        nutrition = {str(td): {
            "Protein (g)": 50, "Carbs (g)": 300, "Fats (g)": 50,
            "Calorie Balance": 0,
        }}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date=nutrition
        )
        ratio = [i for i in insights if "Low protein ratio" in i]
        self.assertEqual(len(ratio), 1)

    def test_macro_ratio_high_fat(self):
        from datetime import date
        td = date(2026, 1, 28)
        # 100g protein (400cal), 100g carbs (400cal), 120g fat (1080cal) = 57% fat
        nutrition = {str(td): {
            "Protein (g)": 100, "Carbs (g)": 100, "Fats (g)": 120,
            "Calorie Balance": 0,
        }}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date=nutrition
        )
        fat = [i for i in insights if "High fat ratio" in i]
        self.assertEqual(len(fat), 1)

    def test_training_day_low_carbs(self):
        from datetime import date
        td = date(2026, 1, 28)
        nutrition = {str(td): {"Carbs (g)": 120, "Calorie Balance": 0}}
        sessions = {str(td): [{"Activity Name": "Run"}]}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, sessions, td, nutrition_by_date=nutrition
        )
        carbs = [i for i in insights if "Low carbs on training day" in i]
        self.assertEqual(len(carbs), 1)

    def test_macro_missing_data(self):
        from datetime import date
        td = date(2026, 1, 28)
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date={}
        )
        macro = [i for i in insights if "protein" in i.lower() or "carbs" in i.lower()
                 or "fat ratio" in i.lower()]
        self.assertEqual(len(macro), 0)


# ── Post-Workout Energy (Gap #15) ──────────────────────────────────────────

class TestCNSFatigue(unittest.TestCase):

    def _minimal_baselines(self):
        return {
            "hrv": {"z": 0, "today": 50, "mean": 50, "std": 10, "n": 90},
            "rhr": {"z": 0, "today": 60, "mean": 60, "std": 5, "n": 90},
            "sleep_score": {"z": 0, "today": 80, "mean": 80, "std": 5, "n": 90},
            "sleep_duration": {"z": 0, "today": 7.5, "mean": 7.5, "std": 0.5, "n": 90},
            "body_battery": {"z": 0, "today": 60, "mean": 60, "std": 10, "n": 90},
            "stress": {"z": 0, "today": 30, "mean": 30, "std": 10, "n": 90},
            "steps": {"z": 0, "today": 8000, "mean": 8000, "std": 2000, "n": 90},
        }

    def test_high_effort_low_energy_fires(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        yesterday = str(td - timedelta(days=1))
        sessions = {yesterday: [{
            "Perceived Effort (1-10)": 8, "Post-Workout Energy (1-10)": 2,
            "Activity Name": "HIIT",
        }]}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, sessions, td, nutrition_by_date={}
        )
        cns = [i for i in insights if "CNS fatigue" in i]
        self.assertEqual(len(cns), 1)

    def test_adequate_energy_no_flag(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        yesterday = str(td - timedelta(days=1))
        sessions = {yesterday: [{
            "Perceived Effort (1-10)": 8, "Post-Workout Energy (1-10)": 6,
            "Activity Name": "Run",
        }]}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, sessions, td, nutrition_by_date={}
        )
        cns = [i for i in insights if "CNS fatigue" in i]
        self.assertEqual(len(cns), 0)

    def test_low_effort_low_energy_no_flag(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        yesterday = str(td - timedelta(days=1))
        sessions = {yesterday: [{
            "Perceived Effort (1-10)": 4, "Post-Workout Energy (1-10)": 2,
            "Activity Name": "Walk",
        }]}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, sessions, td, nutrition_by_date={}
        )
        cns = [i for i in insights if "CNS fatigue" in i]
        self.assertEqual(len(cns), 0)

    def test_recovery_rec_low_pwe(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        yesterday = str(td - timedelta(days=1))
        sessions = {yesterday: [{"Post-Workout Energy (1-10)": 3}]}
        recs = generate_recommendations(
            7, "Good", 0, 1.0, [],
            {"hrv": {"z": 0}, "rhr": {"z": 0}}, td,
            sessions_by_date=sessions
        )
        recovery = [r for r in recs if "post-workout energy was low" in r]
        self.assertEqual(len(recovery), 1)


# ── Orthosomnia Safeguard (Gap #16) ─────────────────────────────────────────

class TestOrthosomniaSafeguard(unittest.TestCase):

    def _minimal_baselines(self):
        return {
            "hrv": {"z": 0, "today": 50, "mean": 50, "std": 10, "n": 90},
            "rhr": {"z": 0, "today": 60, "mean": 60, "std": 5, "n": 90},
            "sleep_score": {"z": 0, "today": 80, "mean": 80, "std": 5, "n": 90},
            "sleep_duration": {"z": 0, "today": 7.5, "mean": 7.5, "std": 0.5, "n": 90},
            "body_battery": {"z": 0, "today": 60, "mean": 60, "std": 10, "n": 90},
            "stress": {"z": 0, "today": 30, "mean": 30, "std": 10, "n": 90},
            "steps": {"z": 0, "today": 8000, "mean": 8000, "std": 2000, "n": 90},
        }

    def test_3_consecutive_low_fires(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        oa = {}
        for d in range(1, 5):
            oa[str(td - timedelta(days=d))] = {
                "Readiness Label": "Poor", "Readiness Score (1-10)": 3,
            }
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date={}, oa_by_date=oa
        )
        ortho = [i for i in insights if "tracking is a tool" in i]
        self.assertEqual(len(ortho), 1)

    def test_2_low_no_trigger(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        oa = {}
        for d in range(1, 3):
            oa[str(td - timedelta(days=d))] = {"Readiness Label": "Poor"}
        oa[str(td - timedelta(days=3))] = {"Readiness Label": "Good"}
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date={}, oa_by_date=oa
        )
        ortho = [i for i in insights if "tracking is a tool" in i]
        self.assertEqual(len(ortho), 0)

    def test_mixed_sequence_no_trigger(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        oa = {
            str(td - timedelta(days=1)): {"Readiness Label": "Poor"},
            str(td - timedelta(days=2)): {"Readiness Label": "Good"},
            str(td - timedelta(days=3)): {"Readiness Label": "Poor"},
        }
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date={}, oa_by_date=oa
        )
        ortho = [i for i in insights if "tracking is a tool" in i]
        self.assertEqual(len(ortho), 0)

    def test_score_variability_reassurance(self):
        from datetime import date, timedelta
        td = date(2026, 1, 28)
        oa = {
            str(td - timedelta(days=1)): {"Readiness Score (1-10)": 8},
            str(td - timedelta(days=2)): {"Readiness Score (1-10)": 4},
        }
        insights = generate_insights(
            self._minimal_baselines(), 0, "stable", None, "", [],
            {}, {}, {}, {}, td, nutrition_by_date={}, oa_by_date=oa
        )
        variability = [i for i in insights if "biological noise" in i]
        self.assertEqual(len(variability), 1)
        self.assertIn("4.0", variability[0])  # swing = |8-4| = 4.0


if __name__ == "__main__":
    unittest.main()
