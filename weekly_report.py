"""
weekly_report.py — Sleep Intelligence Engine for NS Habit Tracker.

Generates a plain-English weekly report analyzing sleep quality, trends,
anomalies, and cognition correlations from Google Sheets data.

Usage:
    python weekly_report.py              # Report for last 7 days
    python weekly_report.py --weeks 2    # Report for last 2 weeks
    python weekly_report.py --save       # Save report to analysis_output/
"""

import argparse
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from garmin_sync import get_workbook

load_dotenv(Path(__file__).parent / ".env")
warnings.filterwarnings("ignore")

OUTPUT_DIR = Path(__file__).parent / "analysis_output"


# ── Data Loading ──────────────────────────────────────────────────────────────

def load_tab(wb, tab_name):
    """Load a sheet tab into a DataFrame."""
    sheet = wb.worksheet(tab_name)
    rows = sheet.get_all_values()
    if len(rows) < 2:
        return pd.DataFrame()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df.replace("", np.nan)
    return df


def prepare_sleep_df(wb):
    """Load and prepare Sleep tab with proper types."""
    df = load_tab(wb, "Sleep")
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    numeric_cols = [
        "Garmin Sleep Score", "Sleep Analysis Score", "Total Sleep (hrs)",
        "Time in Bed (hrs)", "Deep Sleep (min)", "Light Sleep (min)",
        "REM (min)", "Awake During Sleep (min)", "Deep %", "REM %",
        "Sleep Cycles", "Awakenings", "Avg HR", "Avg Respiration",
        "Overnight HRV (ms)", "Body Battery Gained", "Cognition (1-10)",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def prepare_garmin_df(wb):
    """Load and prepare Garmin tab with proper types."""
    df = load_tab(wb, "Garmin")
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    numeric_cols = [
        "HRV (overnight avg)", "HRV 7-day avg", "Resting HR",
        "Sleep Duration (hrs)", "Body Battery", "Steps",
        "Avg Stress Level", "Body Battery at Wake",
        "Aerobic Training Effect", "Vigorous Intensity Min",
        "Duration (min)",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# ── Analysis Functions ────────────────────────────────────────────────────────

def bedtime_to_hours(bt_str):
    """Convert HH:MM bedtime string to float hours past midnight.

    Returns hours where times before 18:00 are treated as after-midnight
    (e.g., 1:30 -> 25.5 for sorting/averaging purposes).
    """
    if pd.isna(bt_str) or not isinstance(bt_str, str):
        return np.nan
    import re
    m = re.match(r'^(\d{1,2}):(\d{2})$', bt_str.strip())
    if not m:
        return np.nan
    h, mi = int(m.group(1)), int(m.group(2))
    val = h + mi / 60.0
    if val < 18:  # after midnight
        val += 24
    return val


def hours_to_time_str(h):
    """Convert float hours (possibly >24) back to HH:MM string."""
    if pd.isna(h):
        return "N/A"
    h = h % 24
    hours = int(h)
    minutes = int((h - hours) * 60)
    return f"{hours}:{minutes:02d}"


def weekly_summary(sleep_week, garmin_week):
    """Generate Section 1: This Week's Sleep Summary."""
    lines = []
    lines.append("=" * 60)
    lines.append("SECTION 1: THIS WEEK'S SLEEP SUMMARY")
    lines.append("=" * 60)

    n_days = len(sleep_week)
    lines.append(f"  Days with data: {n_days}")

    if n_days == 0:
        lines.append("  No sleep data for this period.")
        return "\n".join(lines)

    # Key averages
    metrics = {
        "Sleep Score": ("Sleep Analysis Score", ".0f"),
        "Garmin Score": ("Garmin Sleep Score", ".0f"),
        "Total Sleep": ("Total Sleep (hrs)", ".1f", "hrs"),
        "Deep Sleep": ("Deep Sleep (min)", ".0f", "min"),
        "REM Sleep": ("REM (min)", ".0f", "min"),
        "Deep %": ("Deep %", ".0f", "%"),
        "REM %": ("REM %", ".0f", "%"),
        "HRV": ("Overnight HRV (ms)", ".0f", "ms"),
        "Awakenings": ("Awakenings", ".1f"),
        "Body Battery Gained": ("Body Battery Gained", ".0f"),
    }

    lines.append("")
    for label, spec in metrics.items():
        col = spec[0]
        fmt = spec[1]
        unit = spec[2] if len(spec) > 2 else ""
        if col in sleep_week.columns:
            vals = sleep_week[col].dropna()
            if len(vals) > 0:
                avg = vals.mean()
                lines.append(f"  {label:.<30} {avg:{fmt}} {unit}  (range: {vals.min():{fmt}} - {vals.max():{fmt}})")

    # Bedtime consistency
    if "Bedtime" in sleep_week.columns:
        bt_hours = sleep_week["Bedtime"].apply(bedtime_to_hours).dropna()
        if len(bt_hours) > 0:
            avg_bt = hours_to_time_str(bt_hours.mean())
            std_bt = bt_hours.std() * 60  # in minutes
            lines.append(f"  {'Avg Bedtime':.<30} {avg_bt}  (spread: +/-{std_bt:.0f} min)")

    # Best and worst nights
    if "Sleep Analysis Score" in sleep_week.columns:
        scored = sleep_week.dropna(subset=["Sleep Analysis Score"])
        if len(scored) >= 2:
            best = scored.loc[scored["Sleep Analysis Score"].idxmax()]
            worst = scored.loc[scored["Sleep Analysis Score"].idxmin()]
            lines.append("")
            lines.append(f"  Best night:  {best['date'].strftime('%a %m/%d')} — score {best['Sleep Analysis Score']:.0f}"
                         f"  ({best.get('Total Sleep (hrs)', 0):.1f}h, Deep {best.get('Deep %', 0):.0f}%, HRV {best.get('Overnight HRV (ms)', 0):.0f}ms)")
            lines.append(f"  Worst night: {worst['date'].strftime('%a %m/%d')} — score {worst['Sleep Analysis Score']:.0f}"
                         f"  ({worst.get('Total Sleep (hrs)', 0):.1f}h, Deep {worst.get('Deep %', 0):.0f}%, HRV {worst.get('Overnight HRV (ms)', 0):.0f}ms)")

    # Cognition summary
    if "Cognition (1-10)" in sleep_week.columns:
        cog = sleep_week["Cognition (1-10)"].dropna()
        if len(cog) > 0:
            lines.append("")
            lines.append(f"  {'Avg Cognition':.<30} {cog.mean():.1f}/10  (range: {cog.min():.0f} - {cog.max():.0f}, n={len(cog)} days rated)")

    return "\n".join(lines)


def patterns_detected(sleep_week, garmin_week):
    """Generate Section 2: Patterns Detected."""
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append("SECTION 2: PATTERNS DETECTED")
    lines.append("=" * 60)

    findings = []

    # Pattern: Bedtime vs Deep Sleep
    if "Bedtime" in sleep_week.columns and "Deep Sleep (min)" in sleep_week.columns:
        bt_hours = sleep_week["Bedtime"].apply(bedtime_to_hours)
        valid = sleep_week[["Deep Sleep (min)"]].copy()
        valid["bt_hours"] = bt_hours
        valid = valid.dropna()

        if len(valid) >= 4:
            early = valid[valid["bt_hours"] <= 23.5]  # before 11:30 PM
            late = valid[valid["bt_hours"] > 23.5]
            if len(early) >= 2 and len(late) >= 2:
                early_avg = early["Deep Sleep (min)"].mean()
                late_avg = late["Deep Sleep (min)"].mean()
                diff_pct = ((early_avg - late_avg) / late_avg * 100) if late_avg > 0 else 0
                if abs(diff_pct) > 10:
                    direction = "more" if diff_pct > 0 else "less"
                    findings.append(
                        f"Deep sleep averaged {early_avg:.0f}min on early bedtime nights (before 11:30pm) "
                        f"vs {late_avg:.0f}min on late nights — {abs(diff_pct):.0f}% {direction} deep sleep with earlier bedtime"
                    )

    # Pattern: Bedtime vs Sleep Score
    if "Bedtime" in sleep_week.columns and "Sleep Analysis Score" in sleep_week.columns:
        bt_hours = sleep_week["Bedtime"].apply(bedtime_to_hours)
        valid = sleep_week[["Sleep Analysis Score"]].copy()
        valid["bt_hours"] = bt_hours
        valid = valid.dropna()

        if len(valid) >= 4:
            early = valid[valid["bt_hours"] <= 24.0]  # before midnight
            late = valid[valid["bt_hours"] > 24.0]
            if len(early) >= 2 and len(late) >= 2:
                early_score = early["Sleep Analysis Score"].mean()
                late_score = late["Sleep Analysis Score"].mean()
                diff = early_score - late_score
                if abs(diff) > 3:
                    findings.append(
                        f"Sleep score averaged {early_score:.0f} on pre-midnight bedtimes "
                        f"vs {late_score:.0f} after midnight (difference: {diff:+.0f} points)"
                    )

    # Pattern: HRV vs previous day workout
    if not garmin_week.empty and "Overnight HRV (ms)" in sleep_week.columns:
        merged = pd.merge(
            sleep_week[["date", "Overnight HRV (ms)"]],
            garmin_week[["date", "Duration (min)"]],
            on="date", how="inner"
        ).dropna()

        if len(merged) >= 4:
            workout_days = merged[merged["Duration (min)"] > 0]
            rest_days = merged[merged["Duration (min)"].isna() | (merged["Duration (min)"] == 0)]
            if len(workout_days) >= 2 and len(rest_days) >= 1:
                w_hrv = workout_days["Overnight HRV (ms)"].mean()
                r_hrv = rest_days["Overnight HRV (ms)"].mean()
                diff_pct = ((r_hrv - w_hrv) / w_hrv * 100) if w_hrv > 0 else 0
                if abs(diff_pct) > 5:
                    findings.append(
                        f"HRV averaged {w_hrv:.0f}ms on workout days vs {r_hrv:.0f}ms on rest days "
                        f"({abs(diff_pct):.0f}% {'higher' if diff_pct > 0 else 'lower'} on rest days)"
                    )

    # Pattern: Cognition vs sleep metrics
    if "Cognition (1-10)" in sleep_week.columns:
        cog = sleep_week[["Cognition (1-10)", "Deep Sleep (min)", "REM (min)",
                          "Total Sleep (hrs)", "Overnight HRV (ms)"]].dropna(
            subset=["Cognition (1-10)"])

        if len(cog) >= 4:
            # Find strongest correlation with cognition this week
            best_r = 0
            best_metric = ""
            best_label = ""
            for col, label in [("Deep Sleep (min)", "deep sleep"),
                               ("REM (min)", "REM sleep"),
                               ("Total Sleep (hrs)", "total sleep"),
                               ("Overnight HRV (ms)", "HRV")]:
                if col in cog.columns:
                    pair = cog[["Cognition (1-10)", col]].dropna()
                    if len(pair) >= 3:
                        r = pair["Cognition (1-10)"].corr(pair[col])
                        if abs(r) > abs(best_r):
                            best_r = r
                            best_metric = col
                            best_label = label

            if abs(best_r) > 0.3 and best_metric:
                high_cog = cog[cog["Cognition (1-10)"] >= cog["Cognition (1-10)"].median()]
                low_cog = cog[cog["Cognition (1-10)"] < cog["Cognition (1-10)"].median()]
                if len(high_cog) > 0 and len(low_cog) > 0:
                    h_avg = high_cog[best_metric].mean()
                    l_avg = low_cog[best_metric].mean()
                    findings.append(
                        f"Cognition tracked strongest with {best_label} (r={best_r:.2f}): "
                        f"sharp days averaged {h_avg:.0f} vs foggy days {l_avg:.0f}"
                    )

    # Pattern: Awakenings vs Sleep Score
    if "Awakenings" in sleep_week.columns and "Sleep Analysis Score" in sleep_week.columns:
        valid = sleep_week[["Awakenings", "Sleep Analysis Score"]].dropna()
        if len(valid) >= 4:
            r = valid["Awakenings"].corr(valid["Sleep Analysis Score"])
            if r < -0.3:
                low_wake = valid[valid["Awakenings"] <= valid["Awakenings"].median()]
                high_wake = valid[valid["Awakenings"] > valid["Awakenings"].median()]
                if len(low_wake) > 0 and len(high_wake) > 0:
                    findings.append(
                        f"Fewer awakenings = better sleep: score averaged {low_wake['Sleep Analysis Score'].mean():.0f} "
                        f"with {low_wake['Awakenings'].mean():.1f} awakenings vs {high_wake['Sleep Analysis Score'].mean():.0f} "
                        f"with {high_wake['Awakenings'].mean():.1f} awakenings"
                    )

    if findings:
        for i, f in enumerate(findings, 1):
            lines.append(f"  {i}. {f}")
    else:
        lines.append("  Not enough variation this week to detect clear patterns.")
        lines.append("  (Need at least 4 days with varied bedtimes/activities for pattern detection)")

    return "\n".join(lines)


def trend_analysis(sleep_week, sleep_prior, garmin_week, garmin_prior):
    """Generate Section 3: Trends vs Prior Period."""
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append("SECTION 3: TRENDS (vs prior period)")
    lines.append("=" * 60)

    if sleep_prior.empty or len(sleep_prior) < 3:
        lines.append("  Not enough prior data for trend comparison.")
        return "\n".join(lines)

    trend_metrics = [
        ("Sleep Analysis Score", "Sleep Score", ".0f", "higher"),
        ("Overnight HRV (ms)", "HRV", ".0f", "ms", "higher"),
        ("Total Sleep (hrs)", "Total Sleep", ".1f", "hrs", "higher"),
        ("Deep %", "Deep Sleep %", ".0f", "%", "higher"),
        ("REM %", "REM %", ".0f", "%", "higher"),
        ("Awakenings", "Awakenings", ".1f", "", "lower"),
        ("Body Battery Gained", "BB Gained", ".0f", "", "higher"),
    ]

    for spec in trend_metrics:
        col = spec[0]
        label = spec[1]
        fmt = spec[2]
        better = spec[-1]

        if col not in sleep_week.columns:
            continue

        curr = sleep_week[col].dropna()
        prev = sleep_prior[col].dropna()

        if len(curr) < 2 or len(prev) < 2:
            continue

        curr_avg = curr.mean()
        prev_avg = prev.mean()
        diff = curr_avg - prev_avg
        pct = (diff / prev_avg * 100) if prev_avg != 0 else 0

        if abs(pct) < 2:
            arrow = "--"
            verdict = "flat"
        elif (better == "higher" and diff > 0) or (better == "lower" and diff < 0):
            arrow = "^^" if abs(pct) > 10 else "^"
            verdict = "improving"
        else:
            arrow = "vv" if abs(pct) > 10 else "v"
            verdict = "declining"

        lines.append(f"  {arrow} {label:.<25} {curr_avg:{fmt}} (was {prev_avg:{fmt}}, {pct:+.0f}%) — {verdict}")

    # Bedtime trend
    if "Bedtime" in sleep_week.columns and "Bedtime" in sleep_prior.columns:
        curr_bt = sleep_week["Bedtime"].apply(bedtime_to_hours).dropna()
        prev_bt = sleep_prior["Bedtime"].apply(bedtime_to_hours).dropna()
        if len(curr_bt) >= 2 and len(prev_bt) >= 2:
            curr_avg = curr_bt.mean()
            prev_avg = prev_bt.mean()
            diff_min = (curr_avg - prev_avg) * 60
            if abs(diff_min) > 10:
                direction = "later" if diff_min > 0 else "earlier"
                lines.append(f"  {'>' if diff_min > 0 else '<'} {'Avg Bedtime':.<25} {hours_to_time_str(curr_avg)} (was {hours_to_time_str(prev_avg)}, {abs(diff_min):.0f}min {direction})")

    # Cognition trend
    if "Cognition (1-10)" in sleep_week.columns and "Cognition (1-10)" in sleep_prior.columns:
        curr_cog = sleep_week["Cognition (1-10)"].dropna()
        prev_cog = sleep_prior["Cognition (1-10)"].dropna()
        if len(curr_cog) >= 2 and len(prev_cog) >= 2:
            diff = curr_cog.mean() - prev_cog.mean()
            if abs(diff) > 0.3:
                arrow = "^" if diff > 0 else "v"
                lines.append(f"  {arrow} {'Cognition':.<25} {curr_cog.mean():.1f}/10 (was {prev_cog.mean():.1f}/10)")

    return "\n".join(lines)


def anomaly_detection(sleep_all, sleep_week):
    """Generate Section 4: Anomaly Alerts."""
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append("SECTION 4: ANOMALY ALERTS")
    lines.append("=" * 60)

    alerts = []

    # Need at least 30 days of history for meaningful baselines
    if len(sleep_all) < 14:
        lines.append("  Need at least 14 days of data to establish baselines.")
        return "\n".join(lines)

    # Use last 30 days (excluding this week) as baseline
    baseline = sleep_all[~sleep_all["date"].isin(sleep_week["date"])]
    if len(baseline) < 7:
        baseline = sleep_all  # fallback to all data

    check_metrics = [
        ("Overnight HRV (ms)", "HRV", "ms", "low", "Check: illness, alcohol, stress, overtraining"),
        ("Deep Sleep (min)", "Deep Sleep", "min", "low", "Check: late bedtime, alcohol, caffeine, room temperature"),
        ("Body Battery Gained", "BB Gained", "", "low", "Check: accumulated stress, poor sleep quality, illness"),
        ("Sleep Analysis Score", "Sleep Score", "", "low", "Check: multiple sleep factors may be degrading simultaneously"),
        ("Awakenings", "Awakenings", "", "high", "Check: noise, light, stress, bladder, room temperature"),
    ]

    for col, label, unit, bad_direction, advice in check_metrics:
        if col not in sleep_week.columns or col not in baseline.columns:
            continue

        base_vals = baseline[col].dropna()
        week_vals = sleep_week[col].dropna()

        if len(base_vals) < 7 or len(week_vals) < 1:
            continue

        base_mean = base_vals.mean()
        base_std = base_vals.std()
        week_mean = week_vals.mean()

        if base_std == 0:
            continue

        z_score = (week_mean - base_mean) / base_std

        # Alert if this week is >1.5 std devs in the bad direction
        if bad_direction == "low" and z_score < -1.5:
            alerts.append(
                f"LOW {label}: This week averaged {week_mean:.0f}{unit} vs your baseline "
                f"of {base_mean:.0f}{unit} ({abs(z_score):.1f} std devs below normal). {advice}."
            )
        elif bad_direction == "high" and z_score > 1.5:
            alerts.append(
                f"HIGH {label}: This week averaged {week_mean:.0f}{unit} vs your baseline "
                f"of {base_mean:.0f}{unit} ({z_score:.1f} std devs above normal). {advice}."
            )

    # Consecutive bad nights check
    if "Sleep Analysis Score" in sleep_week.columns:
        scores = sleep_week.sort_values("date")["Sleep Analysis Score"].dropna()
        consecutive_bad = 0
        max_consecutive = 0
        for s in scores:
            if s < 65:
                consecutive_bad += 1
                max_consecutive = max(max_consecutive, consecutive_bad)
            else:
                consecutive_bad = 0
        if max_consecutive >= 3:
            alerts.append(
                f"STREAK: {max_consecutive} consecutive nights with sleep score below 65. "
                f"Sleep debt is likely accumulating — prioritize recovery."
            )

    # Bedtime drift check
    if "Bedtime" in sleep_week.columns:
        bt_hours = sleep_week.sort_values("date")["Bedtime"].apply(bedtime_to_hours).dropna()
        if len(bt_hours) >= 4:
            first_half = bt_hours.iloc[:len(bt_hours)//2].mean()
            second_half = bt_hours.iloc[len(bt_hours)//2:].mean()
            drift_min = (second_half - first_half) * 60
            if drift_min > 30:
                alerts.append(
                    f"BEDTIME DRIFT: Your bedtime shifted {drift_min:.0f} minutes later over the week "
                    f"(from ~{hours_to_time_str(first_half)} to ~{hours_to_time_str(second_half)}). "
                    f"Circadian consistency matters — try to hold a stable bedtime."
                )

    if alerts:
        for i, a in enumerate(alerts, 1):
            lines.append(f"  {i}. {a}")
    else:
        lines.append("  No anomalies detected. All metrics within normal range.")

    return "\n".join(lines)


def actionable_recommendation(sleep_week, sleep_all):
    """Generate Section 5: One Actionable Recommendation."""
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append("SECTION 5: THIS WEEK'S RECOMMENDATION")
    lines.append("=" * 60)

    if len(sleep_week) < 3:
        lines.append("  Not enough data this week for a specific recommendation.")
        return "\n".join(lines)

    # Score each potential recommendation by evidence strength
    recs = []

    # Check bedtime consistency
    if "Bedtime" in sleep_week.columns:
        bt_hours = sleep_week["Bedtime"].apply(bedtime_to_hours).dropna()
        if len(bt_hours) >= 3:
            std_min = bt_hours.std() * 60
            if std_min > 45:
                recs.append((std_min / 30, f"Your bedtime varied by +/-{std_min:.0f} minutes this week. "
                             f"Circadian rhythm depends on consistency — aim for the same bedtime "
                             f"within a 30-minute window every night."))

    # Check late bedtimes
    if "Bedtime" in sleep_week.columns and "Deep %" in sleep_week.columns:
        bt_hours = sleep_week["Bedtime"].apply(bedtime_to_hours)
        valid = sleep_week[["Deep %"]].copy()
        valid["bt_hours"] = bt_hours
        valid = valid.dropna()

        late_nights = valid[valid["bt_hours"] > 24.5]  # after 12:30 AM
        if len(late_nights) >= 2:
            avg_deep = late_nights["Deep %"].mean()
            if avg_deep < 18:
                recs.append((3.0, f"You went to bed after 12:30 AM on {len(late_nights)} nights this week, "
                             f"averaging only {avg_deep:.0f}% deep sleep on those nights. "
                             f"The deepest sleep window is 10PM-2AM — shift bedtime earlier to recapture it."))

    # Check awakenings
    if "Awakenings" in sleep_week.columns:
        avg_wake = sleep_week["Awakenings"].dropna().mean()
        if avg_wake > 4:
            recs.append((avg_wake / 2, f"You averaged {avg_wake:.1f} awakenings per night. "
                         f"High fragmentation prevents deep/REM completion. "
                         f"Check: room temperature (65-68F), light exposure, late caffeine, screen time before bed."))

    # Check low HRV trend
    if "Overnight HRV (ms)" in sleep_week.columns:
        hrv_vals = sleep_week["Overnight HRV (ms)"].dropna()
        if len(hrv_vals) >= 3 and len(sleep_all) >= 14:
            week_avg = hrv_vals.mean()
            baseline_avg = sleep_all["Overnight HRV (ms)"].dropna().mean()
            if week_avg < baseline_avg * 0.85:
                recs.append((2.5, f"Your HRV this week ({week_avg:.0f}ms) is {((baseline_avg - week_avg) / baseline_avg * 100):.0f}% below "
                             f"your baseline ({baseline_avg:.0f}ms). Your body isn't recovering fully. "
                             f"Consider: lighter workouts, earlier bedtime, or stress management this week."))

    # Check cognition correlation if available
    if "Cognition (1-10)" in sleep_week.columns:
        cog = sleep_week["Cognition (1-10)"].dropna()
        if len(cog) >= 3 and cog.mean() < 6:
            recs.append((2.0, f"Your average cognition was {cog.mean():.1f}/10 this week. "
                         f"Focus on the sleep fundamentals: consistent bedtime before midnight, "
                         f"7+ hours, and minimize awakenings. Your brain needs deep + REM to function."))

    if recs:
        # Pick the strongest recommendation
        recs.sort(key=lambda x: x[0], reverse=True)
        lines.append(f"  -> {recs[0][1]}")
    else:
        lines.append("  Your sleep this week looks solid. Maintain your current routine.")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_report(wb, weeks=1):
    """Generate the full weekly sleep intelligence report."""
    print("Loading data...")
    sleep_all = prepare_sleep_df(wb)
    garmin_all = prepare_garmin_df(wb)

    if sleep_all.empty:
        return "ERROR: No sleep data found in Google Sheets."

    today = pd.Timestamp(date.today())
    week_start = today - pd.Timedelta(days=7 * weeks)
    prior_start = week_start - pd.Timedelta(days=7 * weeks)

    sleep_week = sleep_all[sleep_all["date"] > week_start].copy()
    sleep_prior = sleep_all[(sleep_all["date"] > prior_start) & (sleep_all["date"] <= week_start)].copy()
    garmin_week = garmin_all[garmin_all["date"] > week_start].copy() if not garmin_all.empty else pd.DataFrame()
    garmin_prior = garmin_all[(garmin_all["date"] > prior_start) & (garmin_all["date"] <= week_start)].copy() if not garmin_all.empty else pd.DataFrame()

    period_label = f"Last {7 * weeks} days" if weeks == 1 else f"Last {weeks} weeks"

    report_parts = []
    report_parts.append("")
    report_parts.append("#" * 60)
    report_parts.append(f"  NS HABIT TRACKER — WEEKLY SLEEP REPORT")
    report_parts.append(f"  Generated: {date.today().isoformat()}")
    report_parts.append(f"  Period: {period_label} ({week_start.strftime('%m/%d')} - {today.strftime('%m/%d')})")
    report_parts.append("#" * 60)

    report_parts.append(weekly_summary(sleep_week, garmin_week))
    report_parts.append(patterns_detected(sleep_week, garmin_week))
    report_parts.append(trend_analysis(sleep_week, sleep_prior, garmin_week, garmin_prior))
    report_parts.append(anomaly_detection(sleep_all, sleep_week))
    report_parts.append(actionable_recommendation(sleep_week, sleep_all))

    report_parts.append("")
    report_parts.append("=" * 60)
    report_parts.append(f"  Data: {len(sleep_all)} total days in Sleep tab")
    report_parts.append(f"  Cognition entries: {sleep_all['Cognition (1-10)'].dropna().shape[0]}" if "Cognition (1-10)" in sleep_all.columns else "  Cognition: no entries yet")
    report_parts.append("=" * 60)

    return "\n".join(report_parts)


def main():
    parser = argparse.ArgumentParser(description="Weekly Sleep Intelligence Report")
    parser.add_argument("--weeks", type=int, default=1, help="Number of weeks to analyze (default: 1)")
    parser.add_argument("--save", action="store_true", help="Save report to analysis_output/")
    args = parser.parse_args()

    print("Connecting to Google Sheets...")
    wb = get_workbook()
    report = generate_report(wb, weeks=args.weeks)

    print(report)

    if args.save:
        OUTPUT_DIR.mkdir(exist_ok=True)
        out_path = OUTPUT_DIR / f"weekly_report_{date.today().isoformat()}.txt"
        out_path.write_text(report, encoding="utf-8")
        print(f"\nReport saved -> {out_path}")


if __name__ == "__main__":
    main()
