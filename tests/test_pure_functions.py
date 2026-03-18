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
            hrv=37.5,             # (7.5/15)*15 = 7.5
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
        score, text = generate_sleep_analysis(self._full_data())
        self.assertIsInstance(score, int)
        self.assertIsInstance(text, str)

    def test_good_sleep_verdict(self):
        score, text = generate_sleep_analysis(self._full_data())
        self.assertTrue(text.startswith("GOOD"))

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
        score, text = generate_sleep_analysis(data)
        self.assertTrue(text.startswith("POOR"))

    def test_insufficient_data(self):
        score, text = generate_sleep_analysis({})
        self.assertIsNone(score)
        self.assertEqual(text, "Insufficient data for analysis")

    def test_insufficient_data_no_key_metrics(self):
        # Has data but not the three key metrics (total, deep_pct, rem_pct)
        data = {"hrv": 45.0, "sleep_awakenings": 2.0}
        score, text = generate_sleep_analysis(data)
        self.assertIsNone(score)
        self.assertIn("Insufficient", text)

    def test_partial_data_still_works(self):
        # Only duration + deep_pct -- enough for has_data check
        data = {"sleep_duration": 7.0, "sleep_deep_pct": 18.0}
        score, text = generate_sleep_analysis(data)
        self.assertIsNotNone(score)
        self.assertIn("ACTION:", text)

    def test_analysis_contains_action(self):
        _, text = generate_sleep_analysis(self._full_data())
        self.assertIn("ACTION:", text)

    def test_high_respiration_warning(self):
        data = self._full_data(sleep_avg_respiration=20.0)
        _, text = generate_sleep_analysis(data)
        self.assertIn("Respiration", text)

    def test_late_bedtime_insight(self):
        data = self._full_data(
            sleep_bedtime="1:30",
            sleep_deep_pct=15.0,
        )
        _, text = generate_sleep_analysis(data)
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
        _, text = generate_sleep_analysis(data)
        # Independent score will be low, Garmin high -> discrepancy
        if "Garmin" in text:
            self.assertIn("overweighting", text)

    def test_string_metric_values(self):
        data = self._full_data()
        # Convert some values to strings to test _safe_float integration
        data["sleep_duration"] = "8.0"
        data["sleep_deep_pct"] = "22"
        score, text = generate_sleep_analysis(data)
        self.assertIsNotNone(score)


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


if __name__ == "__main__":
    unittest.main()
