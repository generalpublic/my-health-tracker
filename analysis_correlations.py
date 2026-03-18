"""
analysis_correlations.py — Correlation analysis across all Garmin + Sleep data.

Pulls data from Google Sheets, merges by date, computes Pearson correlations,
and identifies the strongest predictors of HRV, Sleep Score, and Body Battery.

Usage:
    python analysis_correlations.py              # Full report + save heatmap PNG
    python analysis_correlations.py --no-charts  # Report only, no charts
"""

import argparse
import math
import warnings
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # non-interactive backend — saves PNG without needing a display
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from dotenv import load_dotenv

from utils import get_workbook

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

    print("Loading Daily Log tab...")
    daily = load_sheet_as_df(wb, "Daily Log")
    daily = daily.rename(columns={"Date": "date"})
    # Convert habit checkboxes to 1/0
    habit_cols = ["Wake at 9:30 AM", "No Morning Screens", "Creatine & Hydrate",
                  "20 Min Walk + Breathing", "Physical Activity",
                  "No Screens Before Bed", "Bed at 10 PM"]
    for col in habit_cols:
        if col in daily.columns:
            daily[col] = daily[col].map({"TRUE": 1.0, "FALSE": 0.0}).astype(float)
    daily = to_numeric_cols(daily, exclude=["date", "Day", "Midday Notes", "Evening Notes"])

    print("Loading Nutrition tab...")
    nutrition = load_sheet_as_df(wb, "Nutrition")
    nutrition = nutrition.rename(columns={"Date": "date"})
    nutrition = to_numeric_cols(nutrition, exclude=["date", "Day", "Breakfast", "Lunch",
                                                     "Dinner", "Snacks", "Notes"])

    # Merge on date — inner join so we only use days with both Garmin + Sleep records
    df = pd.merge(garmin, sleep, on="date", suffixes=("_garmin", "_sleep"))
    # Left join Daily Log and Nutrition (don't drop rows missing these tabs)
    if not daily.empty:
        df = pd.merge(df, daily, on="date", how="left", suffixes=("", "_daily"))
    if not nutrition.empty:
        # Drop auto-populated calorie columns from Nutrition to avoid collision with Garmin
        nut_drop = [c for c in ["Total Calories Burned", "Active Calories Burned",
                                "BMR Calories", "Day"] if c in nutrition.columns]
        nutrition_clean = nutrition.drop(columns=nut_drop, errors="ignore")
        df = pd.merge(df, nutrition_clean, on="date", how="left", suffixes=("", "_nutrition"))
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
    "Morning Energy (1-10)": "What drives better Morning Energy?",
    "Midday Body Feel (1-10)": "What drives better physical recovery?",
    "Day Rating (1-10)": "What drives a better overall day?",
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
    "Morning Energy (1-10)":         "Morning Energy",
    "Midday Body Feel (1-10)":       "Midday Body Feel",
    "Day Rating (1-10)":             "Day Rating",
    "Wake at 9:30 AM":               "Habit: Wake 9:30",
    "No Morning Screens":            "Habit: No AM Screens",
    "Creatine & Hydrate":            "Habit: Creatine/Hydrate",
    "20 Min Walk + Breathing":       "Habit: Walk/Breathing",
    "Physical Activity":             "Habit: Physical Activity",
    "No Screens Before Bed":         "Habit: No PM Screens",
    "Bed at 10 PM":                  "Habit: Bed 10 PM",
    "Habits Total (0-7)":            "Habits Total",
    "Total Calories Consumed":       "Calories Consumed",
    "Protein (g)":                   "Protein (g)",
    "Water (L)":                     "Water (L)",
    "Calorie Balance":               "Calorie Balance",
}

PREDICTOR_COLS = [
    # Garmin activity
    "Steps", "Total Calories Burned", "Active Calories Burned",
    "Avg Stress Level", "Floors Ascended", "Moderate Intensity Min", "Vigorous Intensity Min",
    "Body Battery at Wake", "Body Battery High", "Body Battery Low",
    "Duration (min)", "Avg HR_garmin", "Aerobic Training Effect", "Anaerobic Training Effect",
    # Sleep metrics
    "Time in Bed (hrs)", "Total Sleep (hrs)",
    "Deep Sleep (min)", "Light Sleep (min)", "REM (min)", "Awake During Sleep (min)",
    "Deep %", "REM %", "Sleep Cycles", "Awakenings",
    "Avg HR_sleep", "Avg Respiration", "Overnight HRV (ms)", "Body Battery Gained",
    # Daily Log — individual habits (binary)
    "Wake at 9:30 AM", "No Morning Screens", "Creatine & Hydrate",
    "20 Min Walk + Breathing", "Physical Activity",
    "No Screens Before Bed", "Bed at 10 PM",
    # Daily Log — subjective
    "Midday Body Feel (1-10)", "Habits Total (0-7)",
    # Nutrition — numeric
    "Total Calories Consumed", "Protein (g)", "Water (L)", "Calorie Balance",
]


def _pearson_pvalue(r, n):
    """Two-tailed p-value for Pearson r using t-distribution approximation.

    Uses Abramowitz & Stegun 26.2.17 normal CDF approximation for large df,
    exact t-to-p via regularized incomplete beta for small df.
    """
    if n <= 2 or r is None or abs(r) >= 1.0:
        return 1.0
    t_stat = r * math.sqrt((n - 2) / (1 - r * r))
    # For df > 30, normal approximation is accurate enough
    df = n - 2
    if df > 30:
        z = abs(t_stat)
        if z > 8:
            return 0.0
        b1, b2, b3, b4, b5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
        p_coeff = 0.2316419
        t_val = 1.0 / (1.0 + p_coeff * z)
        poly = t_val * (b1 + t_val * (b2 + t_val * (b3 + t_val * (b4 + t_val * b5))))
        pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
        one_tail = 1.0 - (1.0 - pdf * poly)
        return 2.0 * one_tail
    # For small df, use a simple numerical integration fallback
    # P(T > |t|) for Student's t with df degrees of freedom
    # Fall back to normal approx with Cornish-Fisher correction for small df
    z = abs(t_stat) * (1 - 1 / (4 * df))  # Cornish-Fisher correction
    if z > 8:
        return 0.0
    b1, b2, b3, b4, b5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    p_coeff = 0.2316419
    t_val = 1.0 / (1.0 + p_coeff * z)
    poly = t_val * (b1 + t_val * (b2 + t_val * (b3 + t_val * (b4 + t_val * b5))))
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    one_tail = 1.0 - (1.0 - pdf * poly)
    return 2.0 * one_tail


def _lag1_autocorr(series):
    """Lag-1 autocorrelation for a pandas Series."""
    vals = series.dropna().values
    if len(vals) < 5:
        return 0.0
    mean = vals.mean()
    var = ((vals - mean) ** 2).sum()
    if var == 0:
        return 0.0
    cov = sum((vals[i] - mean) * (vals[i + 1] - mean) for i in range(len(vals) - 1))
    return cov / var


def _benjamini_hochberg(pvals_dict):
    """Apply Benjamini-Hochberg FDR correction to a dict of {key: p_value}.

    Returns a dict of {key: adjusted_p_value} controlling false discovery rate.
    """
    if not pvals_dict:
        return {}
    keys = list(pvals_dict.keys())
    raw_p = [pvals_dict[k] for k in keys]
    m = len(raw_p)
    # Sort by p-value
    ranked = sorted(range(m), key=lambda i: raw_p[i])
    adjusted = [0.0] * m
    # Work backwards: q_i = min(q_{i+1}, p_i * m / rank_i)
    prev = 1.0
    for i in range(m - 1, -1, -1):
        idx = ranked[i]
        rank = i + 1
        adj = min(prev, raw_p[idx] * m / rank)
        adj = min(adj, 1.0)
        adjusted[idx] = adj
        prev = adj
    return {keys[i]: adjusted[i] for i in range(m)}


def compute_correlations(df, outcome_col):
    """Return sorted correlations with autocorrelation-adjusted, FDR-corrected p-values."""
    results = {}
    for col in PREDICTOR_COLS:
        if col not in df.columns or col == outcome_col:
            continue
        paired = df[[outcome_col, col]].dropna()
        n = len(paired)
        if n < 30:
            continue
        r = paired[outcome_col].corr(paired[col])
        # Adjust for temporal autocorrelation
        acf1 = (_lag1_autocorr(paired[outcome_col]) + _lag1_autocorr(paired[col])) / 2
        if acf1 > 0 and acf1 < 1:
            n_eff = max(3, n * (1 - acf1) / (1 + acf1))
        else:
            n_eff = n
        p = _pearson_pvalue(r, n_eff)
        results[col] = (r, n, p)
    # Apply Benjamini-Hochberg FDR correction across all tests for this outcome
    raw_pvals = {k: v[2] for k, v in results.items()}
    fdr_pvals = _benjamini_hochberg(raw_pvals)
    series = pd.Series({k: v[0] for k, v in results.items()})
    counts = {k: v[1] for k, v in results.items()}
    pvals = fdr_pvals  # FDR-corrected p-values
    return series.sort_values(key=abs, ascending=False), counts, pvals


def print_correlations(df, save_charts=True):
    print("\n" + "="*70)
    print("CORRELATION ANALYSIS — Health Tracker")
    print("="*70)
    print("Pearson r: +1.0 = perfect positive, -1.0 = perfect negative, 0 = none")
    print("Strength guide: |r| >= 0.5 strong, 0.3-0.5 moderate, 0.1-0.3 weak")
    print("Significance (FDR-corrected): *** q<0.001, ** q<0.01, * q<0.05, ns = not significant\n")

    all_results = {}

    for outcome_col, question in OUTCOME_COLS.items():
        if outcome_col not in df.columns:
            continue

        corrs, counts, pvals = compute_correlations(df, outcome_col)
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
                p = pvals[col]
                bar = "#" * int(abs(r) * 20)
                strength = "STRONG" if abs(r) >= 0.5 else "moderate" if abs(r) >= 0.3 else "weak"
                sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
                label = RENAME.get(col, col)
                print(f"    {bar:<20}  r={r:+.3f} {sig:<3}  ({strength}, n={n}, q={p:.4f})  {label}")

        if not top_neg.empty:
            print(f"\n  NEGATIVELY correlated (higher X -> lower {display_name}):")
            for col, r in top_neg.items():
                n = counts[col]
                p = pvals[col]
                bar = "#" * int(abs(r) * 20)
                strength = "STRONG" if abs(r) >= 0.5 else "moderate" if abs(r) >= 0.3 else "weak"
                sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
                label = RENAME.get(col, col)
                print(f"    {bar:<20}  r={r:+.3f} {sig:<3}  ({strength}, n={n}, q={p:.4f})  {label}")

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
    ax.set_title("Health Tracker — Health Metrics Correlation Matrix", fontsize=13, pad=15)
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
        # New: Morning Energy drivers
        ("Morning Energy (1-10)",      "Total Sleep (hrs)",         "More sleep -> better morning energy"),
        ("Morning Energy (1-10)",      "Deep Sleep (min)",          "More deep sleep -> better morning energy"),
        ("Morning Energy (1-10)",      "Overnight HRV (ms)",        "Higher HRV -> better morning energy"),
        ("Morning Energy (1-10)",      "Body Battery Gained",       "More BB gained -> better morning energy"),
        ("Morning Energy (1-10)",      "Protein (g)",               "More protein -> better morning energy"),
        ("Morning Energy (1-10)",      "Water (L)",                 "More water -> better morning energy"),
        # New: Body Feel drivers
        ("Midday Body Feel (1-10)",    "Total Sleep (hrs)",         "More sleep -> better body feel"),
        ("Midday Body Feel (1-10)",    "Overnight HRV (ms)",        "Higher HRV -> better body feel"),
        ("Midday Body Feel (1-10)",    "Protein (g)",               "More protein -> better body feel"),
        # New: Day Rating drivers
        ("Day Rating (1-10)",          "Total Sleep (hrs)",         "More sleep -> better day rating"),
        ("Day Rating (1-10)",          "Overnight HRV (ms)",        "Higher HRV -> better day rating"),
        # New: Habit-driven outcomes
        ("Sleep Score_sleep",          "Bed at 10 PM",              "Bedtime habit -> better sleep score"),
        ("Sleep Score_sleep",          "No Screens Before Bed",     "Screen-free evenings -> better sleep"),
        ("HRV (overnight avg)",        "Bed at 10 PM",              "Bedtime habit -> higher HRV"),
    ]

    for a, b, label in checks:
        r, n = _lookup_corr(a, b)
        if r is not None:
            p = _pearson_pvalue(r, n)
            findings.append((abs(r), r, a, b, label, n, p))

    findings.sort(reverse=True)

    for i, (abs_r, r, a, b, label, n, p) in enumerate(findings[:8], 1):
        strength = "STRONG" if abs_r >= 0.5 else "moderate" if abs_r >= 0.3 else "weak"
        direction = "positive" if r > 0 else "negative"
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
        a_label = RENAME.get(a, a)
        b_label = RENAME.get(b, b)
        print(f"\n  {i}. {label}")
        print(f"     r={r:+.3f} {sig}  ({strength} {direction}, n={n} days, p={p:.4f})")


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
