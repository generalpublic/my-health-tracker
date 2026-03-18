"""
analysis_regression.py -- Multiple regression models for health metrics.

Answers questions like:
  - Which combination of factors best predicts your cognition/energy?
  - How much variance in your Morning Energy is explained by sleep + HRV + training?
  - What are the top 3 levers you can pull to improve your day?

Methodology:
  - Ordinary Least Squares (OLS) regression via normal equation
  - Standardized coefficients (beta weights) for cross-variable comparison
  - R-squared and adjusted R-squared for model quality
  - Leave-one-out cross-validation for overfitting detection
  - Implemented from scratch — no numpy/scipy required

Usage:
    python analysis_regression.py                  # All models (default 90 days)
    python analysis_regression.py --days 180       # Larger window
    python analysis_regression.py --model energy    # Specific model
    python analysis_regression.py --output json     # Machine-readable

Models built:
  1. Morning Energy = f(sleep, HRV, training, stress, habits)
  2. Midday Focus   = f(sleep, HRV, energy, stress, training)
  3. Day Rating     = f(energy, focus, mood, sleep, HRV)
  4. Sleep Score    = f(stress, training, habits, prev sleep)
  5. HRV            = f(sleep, training, stress, alcohol, prev HRV)
"""

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from utils import get_workbook, _safe_float
from analysis_lag import read_all_data, build_time_series


# ---------------------------------------------------------------------------
# Matrix Operations (stdlib only)
# ---------------------------------------------------------------------------

def _mat_transpose(M):
    """Transpose a matrix (list of lists)."""
    if not M:
        return []
    rows, cols = len(M), len(M[0])
    return [[M[r][c] for r in range(rows)] for c in range(cols)]


def _mat_multiply(A, B):
    """Multiply two matrices."""
    rows_a, cols_a = len(A), len(A[0])
    rows_b, cols_b = len(B), len(B[0])
    if cols_a != rows_b:
        raise ValueError(f"Matrix dimension mismatch: {cols_a} != {rows_b}")
    result = [[0.0] * cols_b for _ in range(rows_a)]
    for i in range(rows_a):
        for j in range(cols_b):
            s = 0.0
            for k in range(cols_a):
                s += A[i][k] * B[k][j]
            result[i][j] = s
    return result


def _mat_inverse(M):
    """Invert a square matrix using Gauss-Jordan elimination.

    Returns None if matrix is singular.
    """
    n = len(M)
    # Augment with identity
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(M)]

    for col in range(n):
        # Partial pivoting
        max_row = col
        for row in range(col + 1, n):
            if abs(aug[row][col]) > abs(aug[max_row][col]):
                max_row = row
        aug[col], aug[max_row] = aug[max_row], aug[col]

        pivot = aug[col][col]
        if abs(pivot) < 1e-12:
            return None  # Singular

        # Scale pivot row
        for j in range(2 * n):
            aug[col][j] /= pivot

        # Eliminate column
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(2 * n):
                aug[row][j] -= factor * aug[col][j]

    return [row[n:] for row in aug]


# ---------------------------------------------------------------------------
# OLS Regression
# ---------------------------------------------------------------------------

def ols_regression(X_raw, y_raw, feature_names):
    """Fit OLS regression: y = Xβ + ε.

    X_raw: list of lists (each inner list = one observation's features)
    y_raw: list of floats (outcome values)
    feature_names: list of str

    Returns dict with coefficients, stats, or None if insufficient data.
    """
    # Filter rows with no None values
    valid = []
    for i in range(len(y_raw)):
        if y_raw[i] is None:
            continue
        row = X_raw[i]
        if any(v is None for v in row):
            continue
        valid.append(i)

    n = len(valid)
    k = len(feature_names)

    if n < max(k * 10, 20):  # Need 10+ observations per predictor (minimum 20)
        return None

    # Build clean arrays
    X = [[1.0] + [X_raw[i][j] for j in range(k)] for i in valid]  # Add intercept
    y = [[y_raw[i]] for i in valid]

    # Standardize for beta weights (keep original for raw coefficients)
    x_means = [0.0] * (k + 1)
    x_stds = [1.0] * (k + 1)
    for j in range(1, k + 1):  # Skip intercept column
        vals = [X[i][j] for i in range(n)]
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n
        std = math.sqrt(var) if var > 0 else 1.0
        x_means[j] = mean
        x_stds[j] = std

    y_vals = [y[i][0] for i in range(n)]
    y_mean = sum(y_vals) / n
    y_var = sum((v - y_mean) ** 2 for v in y_vals) / n
    y_std = math.sqrt(y_var) if y_var > 0 else 1.0

    # OLS: β = (X'X)^(-1) X'y
    Xt = _mat_transpose(X)
    XtX = _mat_multiply(Xt, X)
    XtX_inv = _mat_inverse(XtX)

    if XtX_inv is None:
        return None  # Singular matrix — multicollinearity

    Xty = _mat_multiply(Xt, y)
    beta = _mat_multiply(XtX_inv, Xty)
    coefficients = [beta[i][0] for i in range(k + 1)]

    # Predictions and residuals
    y_pred = _mat_multiply(X, beta)
    residuals = [y[i][0] - y_pred[i][0] for i in range(n)]

    # R-squared
    ss_res = sum(r ** 2 for r in residuals)
    ss_tot = sum((y[i][0] - y_mean) ** 2 for i in range(n))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Adjusted R-squared
    adj_r_squared = 1.0 - ((1.0 - r_squared) * (n - 1) / (n - k - 1)) if n > k + 1 else 0.0

    # Standardized coefficients (beta weights)
    beta_weights = []
    for j in range(1, k + 1):
        bw = coefficients[j] * x_stds[j] / y_std if y_std > 0 else 0.0
        beta_weights.append(bw)

    # Standard error of coefficients
    mse = ss_res / (n - k - 1) if n > k + 1 else 0.0
    se_coefficients = []
    for j in range(k + 1):
        se = math.sqrt(mse * XtX_inv[j][j]) if mse > 0 and XtX_inv[j][j] > 0 else 0.0
        se_coefficients.append(se)

    # t-statistics and p-values for each coefficient
    t_stats = []
    p_values = []
    for j in range(k + 1):
        if se_coefficients[j] > 0:
            t = coefficients[j] / se_coefficients[j]
            p = _t_to_p_regression(abs(t), n - k - 1)
        else:
            t = 0.0
            p = 1.0
        t_stats.append(t)
        p_values.append(p)

    # Leave-one-out cross-validation R²
    loo_r2 = _loo_cv(X, y, n, k)

    # Feature importance: sorted by absolute beta weight
    features = []
    for j in range(k):
        features.append({
            "name": feature_names[j],
            "coefficient": round(coefficients[j + 1], 4),
            "beta_weight": round(beta_weights[j], 4),
            "abs_beta": round(abs(beta_weights[j]), 4),
            "se": round(se_coefficients[j + 1], 4),
            "t_stat": round(t_stats[j + 1], 3),
            "p_value": round(p_values[j + 1], 4),
            "significant": p_values[j + 1] < 0.05,
        })
    features.sort(key=lambda f: f["abs_beta"], reverse=True)

    return {
        "n": n,
        "k": k,
        "intercept": round(coefficients[0], 4),
        "r_squared": round(r_squared, 4),
        "adj_r_squared": round(adj_r_squared, 4),
        "loo_r_squared": round(loo_r2, 4) if loo_r2 is not None else None,
        "rmse": round(math.sqrt(mse), 4) if mse > 0 else 0.0,
        "features": features,
        "_X_matrix": X,  # Retained for VIF computation in print_results
        "_feature_names": feature_names,  # Original order matching X columns
    }


def _t_to_p_regression(t, df):
    """Two-tailed p-value from t-statistic."""
    if df <= 0:
        return 1.0
    if df > 30:
        z = t
    else:
        z = t * (1 - 1 / (4 * df))
    return 2 * (1 - _norm_cdf(abs(z)))


def _norm_cdf(z):
    """Standard normal CDF (Abramowitz & Stegun 26.2.17)."""
    if z < -8:
        return 0.0
    if z > 8:
        return 1.0
    b1, b2, b3, b4, b5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    p = 0.2316419
    t = 1.0 / (1.0 + p * abs(z))
    poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    cdf = 1.0 - pdf * poly
    if z < 0:
        cdf = 1.0 - cdf
    return cdf


def _compute_vif(X, col_names):
    """Compute Variance Inflation Factor for each predictor.

    X: design matrix with intercept column (col 0). Predictors are cols 1..k.
    col_names: list of predictor names (length k, matching cols 1..k).

    Returns list of (name, vif) tuples for each predictor.
    VIF = 1 / (1 - R2_j) where R2_j is from regressing X_j on all other X's.
    """
    n = len(X)
    k = len(col_names)
    if k < 2 or n < k + 2:
        return []  # VIF meaningless with < 2 predictors or too few rows

    results = []
    for j in range(k):
        col_idx = j + 1  # skip intercept

        # y_j = column j (the predictor we're checking)
        y_j = [X[i][col_idx] for i in range(n)]

        # X_other = intercept + all other predictor columns
        other_cols = [0] + [c + 1 for c in range(k) if c != j]
        X_other = [[X[i][c] for c in other_cols] for i in range(n)]

        # Compute R2 for this auxiliary regression via normal equation
        Xt = _mat_transpose(X_other)
        XtX = _mat_multiply(Xt, X_other)
        XtX_inv = _mat_inverse(XtX)

        if XtX_inv is None:
            results.append((col_names[j], float("inf")))
            continue

        y_col = [[v] for v in y_j]
        Xty = _mat_multiply(Xt, y_col)
        beta = _mat_multiply(XtX_inv, Xty)
        y_pred = _mat_multiply(X_other, beta)

        y_mean = sum(y_j) / n
        ss_tot = sum((v - y_mean) ** 2 for v in y_j)
        ss_res = sum((y_j[i] - y_pred[i][0]) ** 2 for i in range(n))

        if ss_tot < 1e-12:
            results.append((col_names[j], float("inf")))
            continue

        r2_j = 1.0 - (ss_res / ss_tot)
        vif = 1.0 / (1.0 - r2_j) if r2_j < 1.0 else float("inf")
        results.append((col_names[j], round(vif, 1)))

    return results


def _loo_cv(X, y, n, k):
    """Leave-one-out cross-validation R².

    For each observation, fit the model without it and predict.
    Returns cross-validated R², or None if computation fails.
    """
    if n < k + 5:  # Need enough data for LOO to be meaningful
        return None

    y_vals = [y[i][0] for i in range(n)]
    y_mean = sum(y_vals) / n
    ss_tot = sum((v - y_mean) ** 2 for v in y_vals)
    if ss_tot == 0:
        return None

    # Use the Sherman-Morrison-Woodbury shortcut:
    # LOO residual_i = residual_i / (1 - h_ii)
    # where h_ii = X_i' (X'X)^-1 X_i (leverage)
    Xt = _mat_transpose(X)
    XtX = _mat_multiply(Xt, X)
    XtX_inv = _mat_inverse(XtX)
    if XtX_inv is None:
        return None

    Xty = _mat_multiply(Xt, y)
    beta = _mat_multiply(XtX_inv, Xty)
    y_pred = _mat_multiply(X, beta)

    ss_loo = 0.0
    for i in range(n):
        # Compute leverage h_ii = X_i' (X'X)^-1 X_i
        xi = X[i]
        h_ii = 0.0
        for a in range(len(xi)):
            for b in range(len(xi)):
                h_ii += xi[a] * XtX_inv[a][b] * xi[b]

        residual = y[i][0] - y_pred[i][0]
        denom = 1.0 - h_ii
        if abs(denom) < 1e-10:
            return None  # High-leverage point
        loo_residual = residual / denom
        ss_loo += loo_residual ** 2

    return 1.0 - (ss_loo / ss_tot)


# ---------------------------------------------------------------------------
# Model Definitions
# ---------------------------------------------------------------------------

# Each model: (name, outcome_metric, [predictor_metrics], description)
MODELS = [
    (
        "energy",
        "Morning Energy",
        ["Sleep Score", "Sleep Duration", "Deep %", "HRV", "Body Battery",
         "Stress", "Training Load", "Habits Total",
         "Protein", "Calorie Balance", "Water"],
        "What predicts your morning energy?"
    ),
    (
        "focus",
        "Midday Focus",
        ["Sleep Score", "Sleep Duration", "Deep %", "REM %", "HRV",
         "Morning Energy", "Stress", "Training Load",
         "Protein", "Water", "Midday Body Feel"],
        "What predicts your midday focus/cognition?"
    ),
    (
        "day_rating",
        "Day Rating",
        ["Morning Energy", "Midday Focus", "Midday Mood", "Midday Body Feel",
         "Sleep Score", "HRV", "Body Battery", "Stress", "Habits Total"],
        "What predicts your overall day quality?"
    ),
    (
        "sleep",
        "Sleep Score",
        ["Stress", "Training Load", "Steps", "Habits Total",
         "Body Battery", "RHR",
         "Habit: Bed 10 PM", "Habit: No PM Screens", "Calorie Balance"],
        "What predicts your sleep quality?"
    ),
    (
        "hrv",
        "HRV",
        ["Sleep Score", "Sleep Duration", "Deep %", "Training Load",
         "Stress", "RHR", "Body Battery",
         "Session RPE", "Water", "Habit: Bed 10 PM"],
        "What predicts your HRV?"
    ),
    (
        "recovery",
        "Midday Body Feel",
        ["Training Load", "Session RPE", "Sleep Score", "HRV",
         "Protein", "Water", "Perceived Effort"],
        "What predicts your physical recovery?"
    ),
    (
        "cognition",
        "Cognition",
        ["Sleep Score", "Sleep Duration", "Deep %", "REM %", "HRV",
         "Stress", "Protein", "Water", "Habits Total"],
        "What predicts your cognition?"
    ),
]


def build_model_data(series, date_range, outcome_name, predictor_names, lag=0):
    """Extract aligned predictor matrix and outcome vector.

    lag > 0 means predictors from day D predict outcome on day D+lag.
    """
    X = []
    y = []

    out_series = series.get(outcome_name, {})
    pred_series_list = [series.get(p, {}) for p in predictor_names]

    for i, d in enumerate(date_range):
        if i + lag >= len(date_range):
            break

        outcome_date = date_range[i + lag]
        outcome_val = out_series.get(outcome_date)

        pred_row = []
        for ps in pred_series_list:
            pred_row.append(ps.get(d))

        X.append(pred_row)
        y.append(outcome_val)

    return X, y


def run_models(series, date_range, model_filter=None):
    """Run all regression models and return results."""
    results = []

    for model_id, outcome, predictors, description in MODELS:
        if model_filter and model_filter != model_id:
            continue

        # Filter to predictors that have data
        available_predictors = [p for p in predictors if p in series]
        if not available_predictors:
            continue

        # Try lag=0 first (same-day), then lag=1 (next-day prediction)
        for lag in [0, 1]:
            X, y = build_model_data(series, date_range, outcome, available_predictors, lag)

            result = ols_regression(X, y, available_predictors)
            if result is None:
                continue

            result["model_id"] = model_id
            result["outcome"] = outcome
            result["description"] = description
            result["lag"] = lag
            result["lag_label"] = "same-day" if lag == 0 else "next-day"
            results.append(result)

    return results


# ---------------------------------------------------------------------------
# Output Formatting
# ---------------------------------------------------------------------------

def _r2_quality(r2):
    """Interpret R-squared value."""
    if r2 >= 0.7:
        return "STRONG"
    elif r2 >= 0.5:
        return "MODERATE"
    elif r2 >= 0.3:
        return "WEAK-MOD"
    elif r2 >= 0.1:
        return "WEAK"
    return "NEGLIGIBLE"


def _stars(p):
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    return ""


def print_results(results, verbose=False):
    """Print human-readable regression results."""
    if not results:
        print("\nNo models could be fit. Insufficient data for regression.")
        print("Most models need at least 10-15 days of complete data across all predictors.")
        print("Tip: Fill in your Daily Log consistently to enable these models.")
        return

    print(f"\n{'='*78}")
    print(f"  REGRESSION ANALYSIS — {len(results)} models fit")
    print(f"{'='*78}")

    # Group by model_id, show best lag
    seen = {}
    for r in results:
        key = r["model_id"]
        if key not in seen or r["adj_r_squared"] > seen[key]["adj_r_squared"]:
            seen[key] = r

    best_models = sorted(seen.values(), key=lambda r: r["adj_r_squared"], reverse=True)

    for r in best_models:
        overfit = ""
        if r["loo_r_squared"] is not None:
            gap = r["r_squared"] - r["loo_r_squared"]
            if gap > 0.2:
                overfit = "  !! LIKELY OVERFIT"
            elif gap > 0.1:
                overfit = "  ! possible overfit"

        print(f"\n  MODEL: {r['description']}")
        print(f"  {r['outcome']} ({r['lag_label']} prediction)")
        print(f"  R² = {r['r_squared']:.3f}  Adj R² = {r['adj_r_squared']:.3f}  "
              f"[{_r2_quality(r['adj_r_squared'])}]  "
              f"n = {r['n']}  RMSE = {r['rmse']:.2f}{overfit}")
        if r["loo_r_squared"] is not None:
            print(f"  LOO-CV R² = {r['loo_r_squared']:.3f}")

        print(f"\n  {'Feature':<25} {'Beta':>7} {'Coeff':>8} {'p-value':>8} {'Sig':>5}")
        print(f"  {'-'*25} {'-'*7} {'-'*8} {'-'*8} {'-'*5}")

        for feat in r["features"]:
            sig = _stars(feat["p_value"])
            direction = "+" if feat["beta_weight"] > 0 else "-"
            bar = "|" * min(20, int(abs(feat["beta_weight"]) * 20))
            print(f"  {feat['name']:<25} {feat['beta_weight']:>+7.3f} {feat['coefficient']:>+8.4f} "
                  f"{feat['p_value']:>8.4f} {sig:>5}")
            if verbose:
                print(f"  {'':25} t={feat['t_stat']:.2f}  SE={feat['se']:.4f}  "
                      f"{bar}")

        # VIF multicollinearity check
        if "_X_matrix" in r and "_feature_names" in r:
            vif_results = _compute_vif(r["_X_matrix"], r["_feature_names"])
            high_vif = [(name, vif) for name, vif in vif_results if vif > 5]
            if high_vif:
                print(f"\n  !! Multicollinearity Warning (VIF > 5):")
                for name, vif in sorted(high_vif, key=lambda x: x[1], reverse=True):
                    vif_str = "Inf" if math.isinf(vif) else f"{vif:.1f}"
                    print(f"     {name:<25} VIF={vif_str}  -- coefficients may be unreliable")

    # Cross-model feature importance
    print(f"\n{'='*78}")
    print(f"  CROSS-MODEL FEATURE IMPORTANCE")
    print(f"{'='*78}")

    feature_scores = {}
    for r in best_models:
        for feat in r["features"]:
            name = feat["name"]
            if name not in feature_scores:
                feature_scores[name] = {"total_abs_beta": 0, "count": 0,
                                        "significant_count": 0, "models": []}
            feature_scores[name]["total_abs_beta"] += feat["abs_beta"]
            feature_scores[name]["count"] += 1
            if feat["significant"]:
                feature_scores[name]["significant_count"] += 1
            feature_scores[name]["models"].append(r["outcome"])

    ranked = sorted(feature_scores.items(),
                    key=lambda x: x[1]["total_abs_beta"] / x[1]["count"],
                    reverse=True)

    print(f"\n  {'Feature':<25} {'Avg |Beta|':>10} {'Models':>7} {'Sig':>5}  Predicts")
    print(f"  {'-'*25} {'-'*10} {'-'*7} {'-'*5}  {'-'*30}")
    for name, stats in ranked:
        avg_beta = stats["total_abs_beta"] / stats["count"]
        models_str = ", ".join(stats["models"][:3])
        print(f"  {name:<25} {avg_beta:>10.3f} {stats['count']:>7} "
              f"{stats['significant_count']:>5}  {models_str}")

    # Actionable summary
    print(f"\n{'='*78}")
    print(f"  ACTIONABLE LEVERS (ranked by cross-model impact)")
    print(f"{'='*78}")

    for i, (name, stats) in enumerate(ranked[:5], 1):
        avg_beta = stats["total_abs_beta"] / stats["count"]
        if stats["significant_count"] > 0:
            print(f"  {i}. {name} (avg |beta| = {avg_beta:.3f}, "
                  f"significant in {stats['significant_count']}/{stats['count']} models)")
        else:
            print(f"  {i}. {name} (avg |beta| = {avg_beta:.3f}, "
                  f"not yet significant — needs more data)")


def save_json(results, output_path):
    """Save results as JSON."""
    # Strip internal keys not suitable for serialization
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    output = {
        "generated": str(date.today()),
        "methodology": "OLS multiple regression with LOO cross-validation",
        "models": clean,
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"\nJSON output saved to: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Multiple regression analysis for health metrics.")
    parser.add_argument("--days", type=int, default=90, help="Days to analyze (default: 90)")
    parser.add_argument("--model", help="Specific model: energy, focus, day_rating, sleep, hrv")
    parser.add_argument("--output", choices=["text", "json"], default="text")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--date", help="End date (YYYY-MM-DD, default: yesterday)")
    args = parser.parse_args()

    end_date = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)

    print(f"Regression Analysis")
    print(f"  Window: {end_date - timedelta(days=args.days)} to {end_date} ({args.days} days)")

    wb = get_workbook()
    print("  Reading data from Google Sheets...")
    data = read_all_data(wb)

    print("  Building time series...")
    series, date_range = build_time_series(data, args.days, end_date)

    print(f"  Fitting regression models...")
    results = run_models(series, date_range, model_filter=args.model)

    if args.output == "json":
        output_path = Path(__file__).parent / "analysis_output" / "regression_models.json"
        output_path.parent.mkdir(exist_ok=True)
        save_json(results, output_path)
    else:
        print_results(results, verbose=args.verbose)

    print("\nDone.")


if __name__ == "__main__":
    main()
