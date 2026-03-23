"""
Tests for analysis engine changes: baseline window, Van Dongen penalty,
sleep score blending, circadian scoring, validation statistics, confidence.
"""

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from overall_analysis import (
    _get_values_in_window,
    compute_baselines,
    _norm_cdf,
    _z_to_score,
)
from sleep_analysis import circadian_bedtime_score


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_garmin_data(dates_and_values, field="HRV (overnight avg)"):
    """Build a by_date dict for testing baselines."""
    return {str(d): {field: v} for d, v in dates_and_values}


def _make_sleep_data(dates_and_durations):
    """Build a by_date_sleep dict with Total Sleep (hrs) field."""
    return {str(d): {"Total Sleep (hrs)": v} for d, v in dates_and_durations}


# ── Baseline Window ──────────────────────────────────────────────────────────

class TestBaselineWindow(unittest.TestCase):
    """Verify the single 180-day window never loses observations."""

    def test_sparse_data_uses_full_window(self):
        """Sparse dates within 180 days should all be found."""
        target = date(2026, 3, 23)
        # 10 observations spread across 150 days
        dates_values = [
            (target - timedelta(days=i * 15), 50.0 + i)
            for i in range(1, 11)
        ]
        by_date = _make_garmin_data(dates_values)
        values = _get_values_in_window(by_date, target, 180, "HRV (overnight avg)")
        self.assertEqual(len(values), 10)

    def test_old_data_outside_window_excluded(self):
        """Data older than 180 days should not appear."""
        target = date(2026, 3, 23)
        dates_values = [
            (target - timedelta(days=200), 40.0),  # outside window
            (target - timedelta(days=5), 50.0),     # inside window
        ]
        by_date = _make_garmin_data(dates_values)
        values = _get_values_in_window(by_date, target, 180, "HRV (overnight avg)")
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0], 50.0)

    def test_baselines_compute_with_sparse_data(self):
        """compute_baselines should produce a baseline from 10 sparse points."""
        target = date(2026, 3, 23)
        dates_values = [
            (target - timedelta(days=i * 15), 50.0 + i)
            for i in range(1, 11)
        ]
        by_date_garmin = _make_garmin_data(dates_values)
        by_date_sleep = {}
        baselines = compute_baselines(by_date_garmin, by_date_sleep, target)
        self.assertIsNotNone(baselines["hrv"]["mean"])
        self.assertEqual(baselines["hrv"]["n"], 10)

    def test_n_monotonic_with_lookback(self):
        """Wider lookback should always return >= observations than narrower."""
        target = date(2026, 3, 23)
        dates_values = [
            (target - timedelta(days=i * 10), 50.0)
            for i in range(1, 20)
        ]
        by_date = _make_garmin_data(dates_values)
        n_30 = len(_get_values_in_window(by_date, target, 30, "HRV (overnight avg)"))
        n_60 = len(_get_values_in_window(by_date, target, 60, "HRV (overnight avg)"))
        n_90 = len(_get_values_in_window(by_date, target, 90, "HRV (overnight avg)"))
        n_180 = len(_get_values_in_window(by_date, target, 180, "HRV (overnight avg)"))
        self.assertLessEqual(n_30, n_60)
        self.assertLessEqual(n_60, n_90)
        self.assertLessEqual(n_90, n_180)


# ── Van Dongen Penalty ───────────────────────────────────────────────────────

class TestVanDongenPenalty(unittest.TestCase):
    """Verify the subjective penalty requires 3+ debt nights."""

    def _build_sleep_context_tuple(self, debt_night_count):
        """Build the sleep_context tuple as compute_readiness expects it."""
        return ("context text", 1.0, "declining", debt_night_count)

    def test_one_bad_night_no_penalty(self):
        """A single debt night should NOT trigger the Van Dongen penalty."""
        from overall_analysis import compute_readiness
        target = date(2026, 3, 23)
        baselines = {
            "hrv": {"mean": 50, "std": 10, "today": 50, "z": 0.0, "n": 30, "outliers": []},
            "rhr": {"mean": 60, "std": 5, "today": 60, "z": 0.0, "n": 30, "outliers": []},
            "sleep_score": {"mean": 80, "std": 10, "today": 80, "z": 0.0, "n": 30, "outliers": []},
        }
        daily_log = {
            str(target): {"Morning Energy (1-10)": "7"},
            str(target - timedelta(days=1)): {"Day Rating (1-10)": "7"},
        }
        sleep_ctx = self._build_sleep_context_tuple(debt_night_count=1)
        score, label, components, conf = compute_readiness(
            baselines, sleep_ctx, daily_log, target
        )
        # With no penalty, subjective should be at full weight
        self.assertIn("Subjective", components)
        self.assertNotIn("VAN_DONGEN_PENALTY", components["Subjective"][1])

    def test_three_debt_nights_triggers_penalty(self):
        """Three debt nights should trigger the Van Dongen penalty."""
        from overall_analysis import compute_readiness
        target = date(2026, 3, 23)
        baselines = {
            "hrv": {"mean": 50, "std": 10, "today": 50, "z": 0.0, "n": 30, "outliers": []},
            "rhr": {"mean": 60, "std": 5, "today": 60, "z": 0.0, "n": 30, "outliers": []},
            "sleep_score": {"mean": 80, "std": 10, "today": 80, "z": 0.0, "n": 30, "outliers": []},
        }
        daily_log = {
            str(target): {"Morning Energy (1-10)": "7"},
            str(target - timedelta(days=1)): {"Day Rating (1-10)": "7"},
        }
        sleep_ctx = self._build_sleep_context_tuple(debt_night_count=3)
        score, label, components, conf = compute_readiness(
            baselines, sleep_ctx, daily_log, target
        )
        self.assertIn("VAN_DONGEN_PENALTY", components["Subjective"][1])


# ── Sleep Wording ────────────────────────────────────────────────────────────

class TestSleepWording(unittest.TestCase):
    """Verify no deterministic causal language in sleep insights."""

    def test_late_bedtime_insight_uses_probabilistic_language(self):
        from sleep_analysis import generate_sleep_analysis
        data = {
            "sleep_total_hrs": 7.5,
            "sleep_deep_pct": 15.0,
            "sleep_rem_pct": 22.0,
            "sleep_light_min": 200,
            "sleep_awake_min": 10,
            "sleep_bedtime": "1:30 AM",
            "sleep_cycles": 4,
            "sleep_awakenings": 2,
            "garmin_sleep_score": 70,
            "sleep_avg_hr": 55,
            "sleep_avg_respiration": 14,
            "sleep_overnight_hrv": 45,
            "sleep_bb_gained": 50,
            "sleep_time_in_bed": 8.0,
        }
        result = generate_sleep_analysis(data)
        # Returns (ind_score, analysis_text, descriptor)
        analysis_text = result[1]
        # Should not contain "because the late bedtime missed"
        self.assertNotIn("because the late bedtime missed", analysis_text)
        # Should use probabilistic framing
        if "deep sleep" in analysis_text and "late bedtime" in analysis_text.lower():
            self.assertTrue(
                "possibly" in analysis_text or "may" in analysis_text,
                f"Expected probabilistic language, got: {analysis_text}"
            )


# ── Circadian Scoring ────────────────────────────────────────────────────────

class TestCircadianScoring(unittest.TestCase):
    """Verify regularity and lateness are scored independently."""

    def _make_profile(self, median_bt, variability_min=20):
        return {
            "chronotype": "intermediate",
            "median_bedtime_hr": median_bt,
            "median_wake_hr": median_bt + 8,
            "sleep_midpoint_hr": median_bt + 4,
            "bedtime_std_min": variability_min,
            "regularity_center": median_bt,
            "optimal_window_center": median_bt,
            "n_nights": 30,
        }

    def test_regular_2am_not_fully_optimal(self):
        """A regular 2AM sleeper should score lower than a regular 11PM sleeper."""
        profile_2am = self._make_profile(median_bt=26.0)  # 2:00 AM
        profile_11pm = self._make_profile(median_bt=23.0)  # 11:00 PM

        # Both hit their median exactly (perfect regularity)
        score_2am = circadian_bedtime_score(2.0, profile_2am)    # 2:00 AM = 26.0 effective
        score_11pm = circadian_bedtime_score(23.0, profile_11pm)  # 11:00 PM

        self.assertGreater(score_11pm, score_2am,
                           "11 PM regular should score higher than 2 AM regular")

    def test_regular_11pm_gets_full_bonus(self):
        """11 PM regular bedtime: no lateness penalty, full regularity bonus."""
        profile = self._make_profile(median_bt=23.0)
        score = circadian_bedtime_score(23.0, profile)
        self.assertGreater(score, 0, "Regular 11PM bedtime should be positive")

    def test_irregular_bedtime_scores_lower(self):
        """High variability should reduce the score."""
        profile_regular = self._make_profile(median_bt=23.0, variability_min=20)
        profile_irregular = self._make_profile(median_bt=23.0, variability_min=70)

        score_regular = circadian_bedtime_score(23.0, profile_regular)
        score_irregular = circadian_bedtime_score(23.0, profile_irregular)

        self.assertGreater(score_regular, score_irregular,
                           "Regular bedtime should score higher than irregular")


# ── Norm CDF ─────────────────────────────────────────────────────────────────

class TestNormCDF(unittest.TestCase):
    """Verify the stdlib normal CDF approximation."""

    def test_zero(self):
        self.assertAlmostEqual(_norm_cdf(0), 0.5, places=5)

    def test_large_positive(self):
        self.assertAlmostEqual(_norm_cdf(3.0), 0.99865, places=4)

    def test_large_negative(self):
        self.assertAlmostEqual(_norm_cdf(-3.0), 0.00135, places=4)

    def test_one_sigma(self):
        self.assertAlmostEqual(_norm_cdf(1.0), 0.8413, places=3)


# ── Confidence ───────────────────────────────────────────────────────────────

class TestConfidence(unittest.TestCase):
    """Verify confidence reflects minimum baseline depth, not just HRV."""

    def test_deep_hrv_but_shallow_sleep_not_high(self):
        """Deep HRV + shallow sleep baseline should not produce High confidence."""
        from overall_analysis import compute_readiness
        target = date(2026, 3, 23)
        baselines = {
            "hrv": {"mean": 50, "std": 10, "today": 50, "z": 0.0, "n": 100, "outliers": []},
            "rhr": {"mean": 60, "std": 5, "today": 60, "z": 0.0, "n": 100, "outliers": []},
            "sleep_score": {"mean": 80, "std": 10, "today": 80, "z": 0.0, "n": 15, "outliers": []},
        }
        daily_log = {
            str(target): {"Morning Energy (1-10)": "7"},
            str(target - timedelta(days=1)): {"Day Rating (1-10)": "7"},
        }
        sleep_ctx = ("context", 0.0, "stable", 0)
        _, _, _, confidence = compute_readiness(
            baselines, sleep_ctx, daily_log, target
        )
        self.assertNotEqual(confidence, "High",
                            "Shallow sleep baseline should prevent High confidence")


# ── Sleep Score Blending ─────────────────────────────────────────────────────

class TestSleepBlending(unittest.TestCase):
    """Verify sleep component blends Garmin and analysis scores."""

    def test_blended_when_both_available(self):
        """When both sleep scores exist, the component detail shows both z-scores."""
        from overall_analysis import compute_readiness
        target = date(2026, 3, 23)
        baselines = {
            "hrv": {"mean": 50, "std": 10, "today": 50, "z": 0.0, "n": 90, "outliers": []},
            "rhr": {"mean": 60, "std": 5, "today": 60, "z": 0.0, "n": 90, "outliers": []},
            "sleep_score": {"mean": 80, "std": 10, "today": 80, "z": 0.0, "n": 90, "outliers": []},
            "sleep_analysis_score": {"mean": 75, "std": 8, "today": 60, "z": -1.875, "n": 90, "outliers": []},
        }
        daily_log = {
            str(target): {"Morning Energy (1-10)": "7"},
            str(target - timedelta(days=1)): {"Day Rating (1-10)": "7"},
        }
        sleep_ctx = ("context", 0.0, "stable", 0)
        _, _, components, _ = compute_readiness(
            baselines, sleep_ctx, daily_log, target
        )
        self.assertIn("Sleep", components)
        detail = components["Sleep"][1]
        self.assertIn("garmin_z", detail)
        self.assertIn("analysis_z", detail)

    def test_garmin_only_fallback(self):
        """When only Garmin sleep score exists, use it alone."""
        from overall_analysis import compute_readiness
        target = date(2026, 3, 23)
        baselines = {
            "hrv": {"mean": 50, "std": 10, "today": 50, "z": 0.0, "n": 90, "outliers": []},
            "sleep_score": {"mean": 80, "std": 10, "today": 80, "z": 0.0, "n": 90, "outliers": []},
        }
        daily_log = {}
        sleep_ctx = ("context", 0.0, "stable", 0)
        _, _, components, _ = compute_readiness(
            baselines, sleep_ctx, daily_log, target
        )
        self.assertIn("Sleep", components)
        detail = components["Sleep"][1]
        self.assertIn("garmin_z", detail)
        self.assertNotIn("analysis_z", detail)

    def test_disagreement_produces_moderated_score(self):
        """When Garmin is high and analysis is low, blended score is between them."""
        from overall_analysis import compute_readiness
        target = date(2026, 3, 23)
        baselines = {
            "hrv": {"mean": 50, "std": 10, "today": 50, "z": 0.0, "n": 90, "outliers": []},
            "sleep_score": {"mean": 80, "std": 10, "today": 90, "z": 1.0, "n": 90, "outliers": []},
            "sleep_analysis_score": {"mean": 75, "std": 8, "today": 55, "z": -2.5, "n": 90, "outliers": []},
        }
        daily_log = {}
        sleep_ctx = ("context", 0.0, "stable", 0)
        _, _, components, _ = compute_readiness(
            baselines, sleep_ctx, daily_log, target
        )
        garmin_only = _z_to_score(1.0)
        analysis_only = _z_to_score(-2.5)
        blended = components["Sleep"][0]
        # Blended should be between the two individual scores
        self.assertGreater(blended, analysis_only)
        self.assertLess(blended, garmin_only)


if __name__ == "__main__":
    unittest.main()
