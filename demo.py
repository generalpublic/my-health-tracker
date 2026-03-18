"""
demo.py -- Run the Health Tracker analysis pipeline with sample data.

No Garmin account, Google Sheets, or credentials required.
Generates 30 days of realistic health data and shows what the system produces.

Usage:
    python demo.py              # Full demo with sample analysis
    python demo.py --sleep      # Sleep analysis only
    python demo.py --readiness  # Readiness score breakdown only
"""

import random
import sys
from datetime import date, timedelta

from sleep_analysis import generate_sleep_analysis, compute_independent_score


def _generate_sample_day(target_date, base_hrv=42, base_rhr=58):
    """Generate one day of realistic Garmin-like health data."""
    rng = random.Random(target_date.toordinal())

    # Add some natural variation + weekly pattern (worse sleep on weekends)
    weekend = target_date.weekday() >= 4
    sleep_penalty = rng.uniform(-0.5, 0) if weekend else 0

    hrv = round(base_hrv + rng.gauss(0, 8), 0)
    rhr = round(base_rhr + rng.gauss(0, 3), 0)
    sleep_hrs = round(max(4.5, min(9.5, 7.2 + rng.gauss(0, 0.8) + sleep_penalty)), 2)
    deep_pct = round(max(8, min(30, 18 + rng.gauss(0, 4))), 0)
    rem_pct = round(max(8, min(30, 21 + rng.gauss(0, 4))), 0)
    sleep_score = round(max(40, min(100, 72 + rng.gauss(0, 12))), 0)

    deep_min = round(sleep_hrs * 60 * deep_pct / 100, 1)
    rem_min = round(sleep_hrs * 60 * rem_pct / 100, 1)
    light_min = round(sleep_hrs * 60 * (100 - deep_pct - rem_pct - 8) / 100, 1)
    awake_min = round(sleep_hrs * 60 * 8 / 100, 1)

    bedtime_h = rng.choice([22, 22, 23, 23, 23, 0, 0, 1]) if weekend else rng.choice([22, 22, 22, 23, 23])
    bedtime_m = rng.randint(0, 59)
    bedtime = f"{bedtime_h:02d}:{bedtime_m:02d}"

    wake_h = rng.choice([6, 7, 7, 8]) if not weekend else rng.choice([8, 9, 9, 10])
    wake_m = rng.randint(0, 59)
    wake_time = f"{wake_h:02d}:{wake_m:02d}"

    has_activity = rng.random() > 0.4
    activity_types = ["Running", "Cycling", "Strength Training", "Walking", "Swimming", "HIIT"]

    data = {
        "hrv": hrv,
        "hrv_7day": round(base_hrv + rng.gauss(0, 3), 0),
        "resting_hr": rhr,
        "sleep_score": sleep_score,
        "sleep_duration": sleep_hrs,
        "sleep_deep_pct": deep_pct,
        "sleep_rem_pct": rem_pct,
        "sleep_deep_min": deep_min,
        "sleep_light_min": light_min,
        "sleep_rem_min": rem_min,
        "sleep_awake_min": awake_min,
        "sleep_bedtime": bedtime,
        "sleep_wake_time": wake_time,
        "sleep_time_in_bed": round(sleep_hrs + awake_min / 60, 2),
        "sleep_cycles": rng.randint(3, 6),
        "sleep_awakenings": rng.randint(0, 5),
        "sleep_avg_hr": round(rhr - 5 + rng.gauss(0, 2), 0),
        "sleep_avg_respiration": round(16 + rng.gauss(0, 1.5), 1),
        "sleep_body_battery_gained": rng.randint(20, 70),
        "sleep_feedback": rng.choice(["Long & Deep", "Late Bedtime", "Too Short", ""]),
        "body_battery": rng.randint(30, 90),
        "bb_at_wake": rng.randint(40, 85),
        "bb_high": rng.randint(60, 95),
        "bb_low": rng.randint(5, 30),
        "steps": rng.randint(3000, 15000),
        "total_calories": rng.randint(1800, 3200),
        "active_calories": rng.randint(200, 1200),
        "bmr_calories": rng.randint(1500, 1800),
        "avg_stress": rng.randint(20, 50),
        "stress_qualifier": rng.choice(["Low", "Medium", "Medium", ""]),
        "floors_ascended": rng.randint(0, 20),
        "moderate_min": rng.randint(0, 60),
        "vigorous_min": rng.randint(0, 40),
    }

    if has_activity:
        act_type = rng.choice(activity_types)
        data.update({
            "activity_name": f"Morning {act_type}",
            "activity_type": act_type.lower().replace(" ", "_"),
            "activity_start": f"{target_date} {rng.randint(6, 10):02d}:{rng.randint(0, 59):02d}",
            "activity_distance": round(rng.uniform(1.5, 8.0), 2) if "run" in act_type.lower() or "cycl" in act_type.lower() else "",
            "activity_duration": round(rng.uniform(20, 75), 1),
            "activity_avg_hr": rng.randint(120, 165),
            "activity_max_hr": rng.randint(155, 190),
            "activity_calories": rng.randint(150, 700),
            "activity_elevation": round(rng.uniform(0, 200), 1),
            "activity_avg_speed": round(rng.uniform(4, 15), 2),
            "aerobic_te": round(rng.uniform(2.0, 4.5), 1),
            "anaerobic_te": round(rng.uniform(0.0, 3.0), 1),
            "zone_1": round(rng.uniform(0, 10), 1),
            "zone_2": round(rng.uniform(5, 20), 1),
            "zone_3": round(rng.uniform(5, 15), 1),
            "zone_4": round(rng.uniform(2, 10), 1),
            "zone_5": round(rng.uniform(0, 5), 1),
        })

    return data


def demo_sleep_analysis(days=7):
    """Show sleep analysis for recent sample days."""
    print("=" * 60)
    print("SLEEP ANALYSIS DEMO")
    print("=" * 60)

    today = date.today()
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        data = _generate_sample_day(d)
        ind_score, analysis = generate_sleep_analysis(data)

        print(f"\n--- {d} ({d.strftime('%A')}) ---")
        print(f"  Sleep: {data['sleep_duration']}h | Bed: {data['sleep_bedtime']} | Wake: {data['sleep_wake_time']}")
        print(f"  Deep: {data['sleep_deep_pct']}% ({data['sleep_deep_min']}m) | REM: {data['sleep_rem_pct']}% ({data['sleep_rem_min']}m)")
        print(f"  HRV: {data['hrv']}ms | Score: {data['sleep_score']} | Cycles: {data['sleep_cycles']}")
        if ind_score is not None:
            print(f"  Analysis Score: {ind_score}")
        if analysis:
            # Wrap long analysis text
            words = analysis.split()
            line = "  Analysis: "
            for w in words:
                if len(line) + len(w) > 80:
                    print(line)
                    line = "    "
                line += w + " "
            if line.strip():
                print(line)


def demo_readiness(days=30):
    """Show what a readiness score breakdown looks like with sample data."""
    print("=" * 60)
    print("READINESS SCORE DEMO (simulated)")
    print("=" * 60)

    today = date.today()

    # Generate 30 days of data for baselines
    all_data = {}
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        all_data[d] = _generate_sample_day(d)

    # Show the last 7 days with readiness-like scoring
    print("\nNote: This is a simplified demo. The full pipeline uses sigmoid-mapped")
    print("z-scores against rolling baselines. See reference/METHODOLOGY.md.\n")

    # Compute simple baselines from 30 days
    hrvs = [d["hrv"] for d in all_data.values() if d.get("hrv")]
    rhrs = [d["resting_hr"] for d in all_data.values() if d.get("resting_hr")]
    sleeps = [d["sleep_duration"] for d in all_data.values() if d.get("sleep_duration")]

    hrv_mean = sum(hrvs) / len(hrvs)
    hrv_std = (sum((x - hrv_mean) ** 2 for x in hrvs) / len(hrvs)) ** 0.5
    rhr_mean = sum(rhrs) / len(rhrs)
    rhr_std = (sum((x - rhr_mean) ** 2 for x in rhrs) / len(rhrs)) ** 0.5
    sleep_mean = sum(sleeps) / len(sleeps)

    print(f"30-day baselines: HRV {hrv_mean:.0f}ms (SD {hrv_std:.1f}) | RHR {rhr_mean:.0f}bpm (SD {rhr_std:.1f}) | Sleep {sleep_mean:.1f}h\n")

    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        data = all_data[d]

        # Simple z-scores
        hrv_z = (data["hrv"] - hrv_mean) / hrv_std if hrv_std > 0 else 0
        rhr_z = -(data["resting_hr"] - rhr_mean) / rhr_std if rhr_std > 0 else 0  # inverted
        sleep_z = (data["sleep_duration"] - sleep_mean) / 0.8

        # Simplified composite (real version uses sigmoid mapping)
        composite = 5.0 + (hrv_z * 0.35 + sleep_z * 0.30 + rhr_z * 0.20) * 1.5
        composite = max(1.0, min(10.0, composite))

        label = "Optimal" if composite >= 8.5 else "Good" if composite >= 7.0 else "Fair" if composite >= 5.5 else "Low" if composite >= 4.0 else "Poor"

        print(f"  {d} ({d.strftime('%a')}): {composite:.1f}/10 [{label}]")
        print(f"    HRV: {data['hrv']:.0f}ms (z={hrv_z:+.1f}) | RHR: {data['resting_hr']:.0f} (z={rhr_z:+.1f}) | Sleep: {data['sleep_duration']:.1f}h (z={sleep_z:+.1f})")


def demo_full():
    """Run the complete demo."""
    print("\n" + "=" * 60)
    print("  HEALTH TRACKER DEMO")
    print("  Running with generated sample data (no credentials needed)")
    print("=" * 60)

    today = date.today()
    data = _generate_sample_day(today)

    print(f"\n--- Sample data for {today} ---")
    categories = {
        "Sleep": ["sleep_score", "sleep_duration", "sleep_bedtime", "sleep_wake_time",
                   "sleep_deep_pct", "sleep_rem_pct", "sleep_cycles"],
        "Recovery": ["hrv", "hrv_7day", "resting_hr", "body_battery", "bb_at_wake"],
        "Activity": ["steps", "total_calories", "active_calories", "avg_stress"],
    }
    for cat, keys in categories.items():
        vals = " | ".join(f"{k}: {data.get(k, 'N/A')}" for k in keys)
        print(f"  {cat}: {vals}")

    if data.get("activity_name"):
        print(f"  Workout: {data['activity_name']} | {data.get('activity_duration', '')}min | "
              f"Avg HR {data.get('activity_avg_hr', '')} | TE {data.get('aerobic_te', '')}")

    print()
    demo_sleep_analysis(7)
    print()
    demo_readiness(30)

    print("\n" + "=" * 60)
    print("  Demo complete. To run with real data:")
    print("  1. Set up .env (see .env.example)")
    print("  2. Store Garmin password in keyring")
    print("  3. Run: python garmin_sync.py --today")
    print("=" * 60)


if __name__ == "__main__":
    if "--sleep" in sys.argv:
        demo_sleep_analysis()
    elif "--readiness" in sys.argv:
        demo_readiness()
    else:
        demo_full()
