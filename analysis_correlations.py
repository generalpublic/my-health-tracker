"""
analysis_correlations.py — Correlation analysis across all Garmin + Sleep data.

Pulls data from Google Sheets, merges by date, computes Pearson correlations,
and identifies the strongest predictors of HRV, Sleep Score, and Body Battery.

Usage:
    python analysis_correlations.py              # Full report + save heatmap PNG
    python analysis_correlations.py --no-charts  # Report only, no charts
"""

import argparse
import warnings
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # non-interactive backend — saves PNG without needing a display
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from dotenv import load_dotenv

from garmin_sync import get_workbook

load_dotenv(Path(__file__).parent / ".env")
warnings.filterwarnings("ignore")

OUTPUT_DIR = Path(__file__).parent / "analysis_output"


# ── Data Loading ──────────────────────────────────────────────────────────────

def load_sheet_as_df(wb, tab_name):
    sheet = wb.worksheet(tab_name)
    rows  = sheet.get_all_values()
    if len(rows) < 2:
        return pd.DataFrame()
    headers = rows[0]
    df = pd.DataFrame(rows[1:], columns=headers)
    df = df.replace("", np.nan)
    return df


def to_numeric_cols(df, exclude=None):
    """Convert all columns to numeric where possible."""
    exclude = exclude or []
    for col in df.columns:
        if col in exclude:
            continue
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")
    return df


def load_and_merge(wb):
    print("Loading Garmin tab...")
    garmin = load_sheet_as_df(wb, "Garmin")
    garmin = garmin.rename(columns={"Date": "date"})
    garmin = to_numeric_cols(garmin, exclude=["date", "Stress Qualifier", "Activity Name",
                                               "Activity Type", "Start Time", "Sleep Feedback"])

    print("Loading Sleep tab...")
    sleep = load_sheet_as_df(wb, "Sleep")
    sleep = sleep.rename(columns={"Date": "date"})
    sleep = to_numeric_cols(sleep, exclude=["date", "Sleep Feedback", "Notes",
                                              "Sleep Analysis", "Cognition Notes"])

    # Merge on date — inner join so we only use days with both records
    df = pd.merge(garmin, sleep, on="date", suffixes=("_garmin", "_sleep"))
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    print(f"  Merged dataset: {len(df)} days ({df['date'].min().date()} to {df['date'].max().date()})")
    return df


# ── Correlation Analysis ──────────────────────────────────────────────────────

OUTCOME_COLS = {
    "HRV (overnight avg)": "What drives better HRV?",
    "Sleep Score_sleep": "What drives better Sleep Score?",
    "Body Battery": "What drives higher Body Battery?",
    "Sleep Duration (hrs)_garmin": "What drives more total sleep?",
    "Resting HR": "What drives lower Resting HR? (lower = better)",
    "Cognition (1-10)": "What drives better Cognition?",
}

# Human-readable name mapping
RENAME = {
    "HRV (overnight avg)":           "HRV",
    "HRV 7-day avg":                 "HRV 7-day avg",
    "Resting HR":                    "Resting HR",
    "Sleep Duration (hrs)_garmin":   "Sleep Duration (hrs)",
    "Sleep Score_garmin":            "Sleep Score (Garmin tab)",
    "Sleep Score_sleep":             "Sleep Score",
    "Body Battery":                  "Body Battery",
    "Steps":                         "Steps",
    "Total Calories Burned":         "Total Calories Burned",
    "Active Calories Burned":        "Active Calories",
    "Avg Stress Level":              "Avg Stress",
    "Floors Ascended":               "Floors",
    "Moderate Intensity Min":        "Moderate Intensity (min)",
    "Vigorous Intensity Min":        "Vigorous Intensity (min)",
    "Body Battery at Wake":          "Body Battery at Wake",
    "Body Battery High":             "Body Battery High",
    "Body Battery Low":              "Body Battery Low",
    "Duration (min)":                "Workout Duration (min)",
    "Avg HR_garmin":                 "Workout Avg HR",
    "Aerobic Training Effect":       "Aerobic Training Effect",
    "Anaerobic Training Effect":     "Anaerobic Training Effect",
    "Bedtime":                       "Bedtime (decimal hrs)",
    "Wake Time":                     "Wake Time (decimal hrs)",
    "Time in Bed (hrs)":             "Time in Bed (hrs)",
    "Total Sleep (hrs)":             "Total Sleep (hrs)",
    "Deep Sleep (min)":              "Deep Sleep (min)",
    "Light Sleep (min)":             "Light Sleep (min)",
    "REM (min)":                     "REM (min)",
    "Awake During Sleep (min)":      "Awake During Sleep (min)",
    "Deep %":                        "Deep Sleep %",
    "REM %":                         "REM %",
    "Sleep Cycles":                  "Sleep Cycles",
    "Awakenings":                    "Awakenings",
    "Avg HR_sleep":                  "Sleep Avg HR",
    "Avg Respiration":               "Avg Respiration",
    "Overnight HRV (ms)":            "Overnight HRV",
    "Body Battery Gained":           "Body Battery Gained",
    "Cognition (1-10)":              "Cognition",
}

PREDICTOR_COLS = [
    "Steps", "Total Calories Burned", "Active Calories Burned",
    "Avg Stress Level", "Floors Ascended", "Moderate Intensity Min", "Vigorous Intensity Min",
    "Body Battery at Wake", "Body Battery High", "Body Battery Low",
    "Duration (min)", "Avg HR_garmin", "Aerobic Training Effect", "Anaerobic Training Effect",
    "Time in Bed (hrs)", "Total Sleep (hrs)",
    "Deep Sleep (min)", "Light Sleep (min)", "REM (min)", "Awake During Sleep (min)",
    "Deep %", "REM %", "Sleep Cycles", "Awakenings",
    "Avg HR_sleep", "Avg Respiration", "Overnight HRV (ms)", "Body Battery Gained",
]


def compute_correlations(df, outcome_col):
    """Return a sorted Series of Pearson correlations between predictors and outcome."""
    results = {}
    for col in PREDICTOR_COLS:
        if col not in df.columns or col == outcome_col:
            continue
        paired = df[[outcome_col, col]].dropna()
        if len(paired) < 30:
            continue
        r = paired[outcome_col].corr(paired[col])
        results[col] = (r, len(paired))
    series = pd.Series({k: v[0] for k, v in results.items()})
    counts = {k: v[1] for k, v in results.items()}
    return series.sort_values(key=abs, ascending=False), counts


def print_correlations(df, save_charts=True):
    print("\n" + "="*70)
    print("CORRELATION ANALYSIS — NS Habit Tracker")
    print("="*70)
    print("Pearson r: +1.0 = perfect positive, -1.0 = perfect negative, 0 = none")
    print("Strength guide: |r| >= 0.5 strong, 0.3-0.5 moderate, 0.1-0.3 weak\n")

    all_results = {}

    for outcome_col, question in OUTCOME_COLS.items():
        if outcome_col not in df.columns:
            continue

        corrs, counts = compute_correlations(df, outcome_col)
        if corrs.empty:
            continue

        display_name = RENAME.get(outcome_col, outcome_col)
        print(f"\n{'-'*70}")
        print(f"  {question}")
        print(f"  Target: {display_name}  (n available per predictor varies)")
        print(f"{'-'*70}")

        # Top 10 positive + top 5 negative
        top_pos = corrs[corrs > 0].head(8)
        top_neg = corrs[corrs < 0].head(5)

        if not top_pos.empty:
            print(f"\n  POSITIVELY correlated (higher X -> higher {display_name}):")
            for col, r in top_pos.items():
                n = counts[col]
                bar = "#" * int(abs(r) * 20)
                strength = "STRONG" if abs(r) >= 0.5 else "moderate" if abs(r) >= 0.3 else "weak"
                label = RENAME.get(col, col)
                print(f"    {bar:<20}  r={r:+.3f}  ({strength}, n={n})  {label}")

        if not top_neg.empty:
            print(f"\n  NEGATIVELY correlated (higher X -> lower {display_name}):")
            for col, r in top_neg.items():
                n = counts[col]
                bar = "#" * int(abs(r) * 20)
                strength = "STRONG" if abs(r) >= 0.5 else "moderate" if abs(r) >= 0.3 else "weak"
                label = RENAME.get(col, col)
                print(f"    {bar:<20}  r={r:+.3f}  ({strength}, n={n})  {label}")

        all_results[outcome_col] = corrs

    return all_results


def save_heatmap(df):
    """Save a correlation heatmap of all key metrics."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    cols_to_use = [c for c in ([
        "HRV (overnight avg)", "Sleep Score_sleep", "Body Battery",
        "Resting HR", "Sleep Duration (hrs)_garmin",
        "Deep Sleep (min)", "REM (min)", "Deep %", "REM %",
        "Awakenings", "Sleep Cycles", "Body Battery Gained",
        "Avg Stress Level", "Steps", "Active Calories Burned",
        "Vigorous Intensity Min", "Aerobic Training Effect",
        "Body Battery at Wake",
    ]) if c in df.columns]

    sub = df[cols_to_use].dropna(thresh=int(len(cols_to_use) * 0.5))
    corr_matrix = sub.corr()

    # Rename for display
    corr_matrix.index   = [RENAME.get(c, c) for c in corr_matrix.index]
    corr_matrix.columns = [RENAME.get(c, c) for c in corr_matrix.columns]

    fig, ax = plt.subplots(figsize=(14, 11))
    mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
    sns.heatmap(
        corr_matrix, mask=mask, annot=True, fmt=".2f",
        cmap="RdYlGn", center=0, vmin=-1, vmax=1,
        square=True, linewidths=0.3, ax=ax,
        annot_kws={"size": 7},
    )
    ax.set_title("NS Habit Tracker — Health Metrics Correlation Matrix", fontsize=13, pad=15)
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.yticks(rotation=0, fontsize=8)
    plt.tight_layout()

    out_path = OUTPUT_DIR / "correlation_heatmap.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n  Heatmap saved -> {out_path}")
    return out_path


def print_top_findings(df, cached_results=None):
    """Print the 5 most actionable findings in plain English.

    If cached_results is provided (dict of outcome_col -> corr Series from
    print_correlations), lookup correlations there instead of recomputing.
    """
    print("\n" + "="*70)
    print("TOP ACTIONABLE FINDINGS (strongest relationships in your data)")
    print("="*70)

    findings = []

    def _lookup_corr(a, b):
        """Try cached results first, fall back to direct computation."""
        if cached_results and a in cached_results:
            corrs = cached_results[a]
            if b in corrs.index:
                paired = df[[a, b]].dropna()
                return corrs[b], len(paired)
        if a not in df.columns or b not in df.columns:
            return None, 0
        paired = df[[a, b]].dropna()
        if len(paired) < 30:
            return None, len(paired)
        return paired[a].corr(paired[b]), len(paired)

    checks = [
        ("HRV (overnight avg)",        "Avg Stress Level",         "Higher stress -> lower HRV"),
        ("HRV (overnight avg)",        "Total Sleep (hrs)",         "More sleep -> higher HRV"),
        ("HRV (overnight avg)",        "Deep Sleep (min)",          "More deep sleep -> higher HRV"),
        ("HRV (overnight avg)",        "Body Battery Gained",       "More BB gained -> higher HRV"),
        ("HRV (overnight avg)",        "Aerobic Training Effect",   "Higher aerobic TE -> higher HRV"),
        ("HRV (overnight avg)",        "Awakenings",                "More awakenings -> lower HRV"),
        ("Sleep Score_sleep",          "Awakenings",                "More awakenings -> lower sleep score"),
        ("Sleep Score_sleep",          "Total Sleep (hrs)",         "More sleep -> higher sleep score"),
        ("Sleep Score_sleep",          "Deep %",                    "More deep sleep % -> higher sleep score"),
        ("Sleep Score_sleep",          "Avg Stress Level",          "Higher stress -> lower sleep score"),
        ("Body Battery",               "HRV (overnight avg)",       "Higher HRV -> higher body battery"),
        ("Body Battery",               "Body Battery Gained",       "More gained during sleep -> higher battery"),
        ("Resting HR",                 "HRV (overnight avg)",       "Higher HRV -> lower resting HR"),
        ("Resting HR",                 "Avg Stress Level",          "Higher stress -> higher resting HR"),
        ("Cognition (1-10)",           "Deep Sleep (min)",          "More deep sleep -> better cognition"),
        ("Cognition (1-10)",           "REM (min)",                 "More REM -> better cognition"),
        ("Cognition (1-10)",           "Total Sleep (hrs)",         "More sleep -> better cognition"),
        ("Cognition (1-10)",           "Overnight HRV (ms)",        "Higher HRV -> better cognition"),
        ("Cognition (1-10)",           "Body Battery Gained",       "More BB gained -> better cognition"),
        ("Cognition (1-10)",           "Awakenings",                "More awakenings -> worse cognition"),
        ("Cognition (1-10)",           "Avg Stress Level",          "Higher stress -> worse cognition"),
    ]

    for a, b, label in checks:
        r, n = _lookup_corr(a, b)
        if r is not None:
            findings.append((abs(r), r, a, b, label, n))

    findings.sort(reverse=True)

    for i, (abs_r, r, a, b, label, n) in enumerate(findings[:8], 1):
        strength = "STRONG" if abs_r >= 0.5 else "moderate" if abs_r >= 0.3 else "weak"
        direction = "positive" if r > 0 else "negative"
        a_label = RENAME.get(a, a)
        b_label = RENAME.get(b, b)
        print(f"\n  {i}. {label}")
        print(f"     r={r:+.3f} ({strength} {direction} correlation, n={n} days)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-charts", action="store_true", help="Skip saving chart PNG files")
    args = parser.parse_args()

    print("Connecting to Google Sheets...")
    wb = get_workbook()
    df = load_and_merge(wb)

    if len(df) < 30:
        print(f"Not enough data ({len(df)} rows). Need at least 30 days.")
        return

    all_results = print_correlations(df, save_charts=not args.no_charts)
    print_top_findings(df, cached_results=all_results)

    if not args.no_charts:
        print("\nGenerating heatmap...")
        save_heatmap(df)

    print("\n" + "="*70)
    print("Done. Results above are based on YOUR data.")
    print("Update ANALYSIS.md with key findings as you discover them.")
    print("="*70)


if __name__ == "__main__":
    main()
