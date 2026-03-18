"""
analysis_lag.py -- Lag correlation analysis for health metrics.

Answers questions like:
  - Does a hard workout suppress HRV 1-2 days later?
  - Does alcohol tonight predict lower sleep score tomorrow?
  - Does deep sleep predict next-day subjective energy?

Methodology:
  - Pearson correlation at each lag offset (0 to max_lag days)
  - Spearman rank correlation for non-linear relationships
  - Significance testing via t-distribution approximation
  - Outputs ranked findings sorted by effect size

Usage:
    python analysis_lag.py                  # Full analysis (default 90 days)
    python analysis_lag.py --days 180       # Last 180 days
    python analysis_lag.py --pair "HRV -> Cognition"  # Specific pair
    python analysis_lag.py --output json    # Machine-readable output

Requires no dependencies beyond what garmin_sync.py already uses.
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


# ---------------------------------------------------------------------------
# Statistics (stdlib only — no numpy/scipy)
# ---------------------------------------------------------------------------

def _lag1_autocorrelation(values):
    """Compute lag-1 autocorrelation for a time series.

    Used to adjust effective sample size for temporally correlated data.
    Health metrics (HRV, sleep, HR) typically have acf1 of 0.4-0.7.
    """
    n = len(values)
    if n < 5:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values)
    if var == 0:
        return 0.0
    cov = sum((values[i] - mean) * (values[i + 1] - mean) for i in range(n - 1))
    return cov / var


def _effective_n(n, acf1):
    """Compute effective sample size adjusting for temporal autocorrelation.

    Formula: n_eff = n * (1 - acf1) / (1 + acf1)
    Source: Bayley & Hammersley 1946; standard in time-series analysis.
    """
    if acf1 <= 0 or acf1 >= 1:
        return n  # no positive autocorrelation or invalid
    n_eff = n * (1 - acf1) / (1 + acf1)
    return max(3, n_eff)  # floor at 3 to avoid division issues


def _pearson(x, y):
    """Pearson correlation coefficient and p-value for two lists.

    Adjusts p-values for temporal autocorrelation using effective sample size.
    Returns (r, p, n) or (None, None, n) if insufficient data.
    """
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(pairs)
    if n < 5:
        return None, None, n

    xs, ys = zip(*pairs)
    mx = sum(xs) / n
    my = sum(ys) / n

    sx = sum((xi - mx) ** 2 for xi in xs)
    sy = sum((yi - my) ** 2 for yi in ys)
    sxy = sum((xi - mx) * (yi - my) for xi, yi in pairs)

    if sx == 0 or sy == 0:
        return None, None, n

    r = sxy / math.sqrt(sx * sy)

    # Adjust for temporal autocorrelation
    acf1_x = _lag1_autocorrelation(list(xs))
    acf1_y = _lag1_autocorrelation(list(ys))
    acf1_avg = (acf1_x + acf1_y) / 2  # average autocorrelation of both series
    n_eff = _effective_n(n, acf1_avg)

    # t-statistic for significance using effective n
    if abs(r) >= 1.0:
        p = 0.0
    else:
        df_eff = max(1, n_eff - 2)
        t_stat = r * math.sqrt(df_eff / (1 - r * r))
        p = _t_to_p(abs(t_stat), df_eff)

    return r, p, n


def _rank(values):
    """Assign ranks to values, handling ties with average rank."""
    indexed = [(v, i) for i, v in enumerate(values)]
    indexed.sort(key=lambda x: x[0])
    ranks = [0.0] * len(values)

    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][0] == indexed[i][0]:
            j += 1
        avg_rank = (i + j - 1) / 2.0 + 1
        for k in range(i, j):
            ranks[indexed[k][1]] = avg_rank
        i = j

    return ranks


def _spearman(x, y):
    """Spearman rank correlation and p-value.

    Returns (rho, p, n) or (None, None, n).
    """
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(pairs)
    if n < 5:
        return None, None, n

    xs, ys = zip(*pairs)
    rx = _rank(xs)
    ry = _rank(ys)
    return _pearson(rx, ry)


def _t_to_p(t, df):
    """Approximate two-tailed p-value from t-statistic using normal approx for large df."""
    if df <= 0:
        return 1.0
    # For df > 30, t-distribution is close to normal
    # Use the approximation: p ≈ 2 * (1 - Φ(|t|)) where Φ is standard normal CDF
    # For smaller df, use a rougher approximation
    if df > 30:
        z = t
    else:
        # Adjusted for df: z = t * (1 - 1/(4*df))
        z = t * (1 - 1 / (4 * df))

    # Standard normal CDF approximation (Abramowitz & Stegun)
    return 2 * (1 - _norm_cdf(abs(z)))


def _norm_cdf(z):
    """Standard normal CDF approximation (Abramowitz & Stegun 26.2.17)."""
    if z < -8:
        return 0.0
    if z > 8:
        return 1.0
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429
    p = 0.2316419
    t = 1.0 / (1.0 + p * abs(z))
    poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    cdf = 1.0 - pdf * poly
    if z < 0:
        cdf = 1.0 - cdf
    return cdf


# ---------------------------------------------------------------------------
# Data Reading
# ---------------------------------------------------------------------------

def read_all_data(wb):
    """Read all tabs into lists of dicts keyed by header names."""
    result = {}
    for tab_name in ["Garmin", "Sleep", "Daily Log", "Session Log", "Nutrition",
                      "Overall Analysis"]:
        try:
            sheet = wb.worksheet(tab_name)
            rows = sheet.get_all_values()
            if len(rows) < 2:
                result[tab_name] = []
                continue
            headers = rows[0]
            tab_data = []
            for row in rows[1:]:
                if not row or len(row) < 2 or not row[0]:
                    continue
                d = {}
                for i, h in enumerate(headers):
                    d[h] = row[i] if i < len(row) else ""
                tab_data.append(d)
            result[tab_name] = tab_data
        except Exception:
            result[tab_name] = []
    return result


def build_time_series(data, days_back, end_date=None):
    """Build aligned time series for all metrics, keyed by date string.

    Returns dict of {metric_name: {date_str: float_value}}.
    """
    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    start_date = end_date - timedelta(days=days_back)
    date_range = [str(start_date + timedelta(days=i)) for i in range(days_back + 1)]

    # Index data by date
    garmin_by_date = {}
    for r in data.get("Garmin", []):
        d = r.get("Date", "")
        if d:
            garmin_by_date[d] = r

    sleep_by_date = {}
    for r in data.get("Sleep", []):
        d = r.get("Date", "")
        if d:
            sleep_by_date[d] = r

    daily_by_date = {}
    for r in data.get("Daily Log", []):
        d = r.get("Date", "")
        if d:
            daily_by_date[d] = r

    nutrition_by_date = {}
    for r in data.get("Nutrition", []):
        d = r.get("Date", "")
        if d:
            nutrition_by_date[d] = r

    # Sessions: aggregate daily load + subjective session metrics
    session_load_by_date = {}
    session_effort_by_date = {}   # list of (effort, duration) per date
    session_energy_by_date = {}   # list of post-workout energy per date
    for r in data.get("Session Log", []):
        d = r.get("Date", "")
        if not d:
            continue
        dur = _safe_float(r.get("Duration (min)"))
        hr = _safe_float(r.get("Avg HR"))
        te = _safe_float(r.get("Anaerobic TE (0-5)"))
        effort = _safe_float(r.get("Perceived Effort (1-10)"))
        post_energy = _safe_float(r.get("Post-Workout Energy (1-10)"))
        load = 0
        if dur and hr:
            load = dur * hr / 100
        elif dur:
            load = dur
        session_load_by_date[d] = session_load_by_date.get(d, 0) + load
        # Track max anaerobic TE for the day
        if te is not None:
            prev_te = session_load_by_date.get(f"{d}_max_te", 0)
            session_load_by_date[f"{d}_max_te"] = max(prev_te, te)
        # Collect session subjective data for daily aggregation
        if effort is not None:
            session_effort_by_date.setdefault(d, []).append((effort, dur))
        if post_energy is not None:
            session_energy_by_date.setdefault(d, []).append(post_energy)

    # Build time series
    series = {}

    # -- Garmin metrics --
    garmin_fields = {
        "HRV": "HRV (overnight avg)",
        "RHR": "Resting HR",
        "Body Battery": "Body Battery",
        "Steps": "Steps",
        "Stress": "Avg Stress Level",
        "Avg HR": "Daily Avg HR",
    }
    for name, field in garmin_fields.items():
        s = {}
        for d in date_range:
            row = garmin_by_date.get(d)
            s[d] = _safe_float(row.get(field)) if row else None
        series[name] = s

    # -- Sleep metrics --
    sleep_fields = {
        "Sleep Score": "Garmin Sleep Score",
        "Sleep Duration": "Total Sleep (hrs)",
        "Deep %": "Deep %",
        "REM %": "REM %",
        "Light %": "Light %",
        "Awakenings": "Awakenings",
        "Sleep Respiration": "Avg Respiration (sleep)",
    }
    for name, field in sleep_fields.items():
        s = {}
        for d in date_range:
            row = sleep_by_date.get(d)
            s[d] = _safe_float(row.get(field)) if row else None
        series[name] = s

    # -- Daily Log subjective metrics --
    daily_fields = {
        "Morning Energy": "Morning Energy (1-10)",
        "Midday Energy": "Midday Energy (1-10)",
        "Midday Focus": "Midday Focus (1-10)",
        "Midday Mood": "Midday Mood (1-10)",
        "Midday Body Feel": "Midday Body Feel (1-10)",
        "Evening Energy": "Evening Energy (1-10)",
        "Evening Focus": "Evening Focus (1-10)",
        "Evening Mood": "Evening Mood (1-10)",
        "Perceived Stress": "Perceived Stress (1-10)",
        "Day Rating": "Day Rating (1-10)",
        "Habits Total": "Habits Total (0-7)",
    }
    for name, field in daily_fields.items():
        s = {}
        for d in date_range:
            row = daily_by_date.get(d)
            s[d] = _safe_float(row.get(field)) if row else None
        series[name] = s

    # -- Daily Log individual habits (binary: TRUE/FALSE -> 1.0/0.0) --
    habit_fields = {
        "Habit: Wake 9:30":        "Wake at 9:30 AM",
        "Habit: No AM Screens":    "No Morning Screens",
        "Habit: Creatine Hydrate": "Creatine & Hydrate",
        "Habit: Walk Breathing":   "20 Min Walk + Breathing",
        "Habit: Physical Activity": "Physical Activity",
        "Habit: No PM Screens":    "No Screens Before Bed",
        "Habit: Bed 10 PM":        "Bed at 10 PM",
    }
    for name, field in habit_fields.items():
        s = {}
        for d in date_range:
            row = daily_by_date.get(d)
            if row:
                val = row.get(field, "")
                if val.upper() == "TRUE":
                    s[d] = 1.0
                elif val.upper() == "FALSE":
                    s[d] = 0.0
                else:
                    s[d] = None
            else:
                s[d] = None
        series[name] = s

    # -- Nutrition numeric fields --
    nutrition_fields = {
        "Calories Consumed": "Total Calories Consumed",
        "Protein":           "Protein (g)",
        "Water":             "Water (L)",
        "Calorie Balance":   "Calorie Balance",
    }
    for name, field in nutrition_fields.items():
        s = {}
        for d in date_range:
            row = nutrition_by_date.get(d)
            s[d] = _safe_float(row.get(field)) if row else None
        series[name] = s

    # -- Overall Analysis: Cognition (1-10) --
    oa_by_date = {}
    for r in data.get("Overall Analysis", []):
        d = r.get("Date", "")
        if d:
            oa_by_date[d] = r
    cog_series = {}
    for d in date_range:
        row = oa_by_date.get(d)
        cog_series[d] = _safe_float(row.get("Cognition (1-10)")) if row else None
    series["Cognition"] = cog_series

    # -- Training load (computed) --
    training_series = {}
    training_te_series = {}
    for d in date_range:
        training_series[d] = session_load_by_date.get(d, 0) if d in session_load_by_date else None
        te_val = session_load_by_date.get(f"{d}_max_te")
        training_te_series[d] = te_val
    series["Training Load"] = training_series
    series["Max Anaerobic TE"] = training_te_series

    # -- Session subjective: Perceived Effort, Post-Workout Energy, Session RPE --
    effort_series = {}
    energy_series = {}
    srpe_series = {}
    for d in date_range:
        # Perceived Effort: duration-weighted avg across sessions, or max if no duration
        efforts = session_effort_by_date.get(d)
        if efforts:
            with_dur = [(e, du) for e, du in efforts if du]
            if with_dur:
                total_dur = sum(du for _, du in with_dur)
                effort_series[d] = sum(e * du for e, du in with_dur) / total_dur
                srpe_series[d] = sum(e * du / 10 for e, du in with_dur)
            else:
                effort_series[d] = max(e for e, _ in efforts)
                srpe_series[d] = None  # can't compute sRPE without duration
        else:
            effort_series[d] = None
            srpe_series[d] = None
        # Post-Workout Energy: min (worst session = recovery signal)
        energies = session_energy_by_date.get(d)
        energy_series[d] = min(energies) if energies else None
    series["Perceived Effort"] = effort_series
    series["Post-Workout Energy"] = energy_series
    series["Session RPE"] = srpe_series

    # -- Alcohol flag (binary) --
    alcohol_kw = ["alcohol", "beer", "wine", "drink", "drinks", "cocktail",
                  "whiskey", "vodka", "tequila", "bourbon", "sake", "soju"]
    alcohol_series = {}
    for d in date_range:
        texts = []
        dl = daily_by_date.get(d, {})
        for f in ["Midday Notes", "Evening Notes"]:
            if dl.get(f):
                texts.append(dl[f].lower())
        nut = nutrition_by_date.get(d, {})
        for f in ["Breakfast", "Lunch", "Dinner", "Snacks", "Notes"]:
            if nut.get(f):
                texts.append(nut[f].lower())
        combined = " ".join(texts)
        if combined.strip():
            alcohol_series[d] = 1.0 if any(kw in combined for kw in alcohol_kw) else 0.0
        else:
            alcohol_series[d] = None
    series["Alcohol"] = alcohol_series

    # -- Sugar flag (binary) --
    sugar_kw = ["sugar", "candy", "ice cream", "cake", "cookies", "pastry",
                "chocolate", "soda", "dessert", "sweets", "donut", "brownie"]
    sugar_series = {}
    for d in date_range:
        texts = []
        dl = daily_by_date.get(d, {})
        for f in ["Midday Notes", "Evening Notes"]:
            if dl.get(f):
                texts.append(dl[f].lower())
        nut = nutrition_by_date.get(d, {})
        for f in ["Breakfast", "Lunch", "Dinner", "Snacks", "Notes"]:
            if nut.get(f):
                texts.append(nut[f].lower())
        combined = " ".join(texts)
        if combined.strip():
            sugar_series[d] = 1.0 if any(kw in combined for kw in sugar_kw) else 0.0
        else:
            sugar_series[d] = None
    series["Sugar Flag"] = sugar_series

    # -- Caffeine flag (binary) --
    caffeine_kw = ["coffee", "caffeine", "espresso", "energy drink", "pre-workout",
                   "preworkout", "cold brew", "latte", "cappuccino", "matcha"]
    caffeine_series = {}
    for d in date_range:
        texts = []
        dl = daily_by_date.get(d, {})
        for f in ["Midday Notes", "Evening Notes"]:
            if dl.get(f):
                texts.append(dl[f].lower())
        nut = nutrition_by_date.get(d, {})
        for f in ["Breakfast", "Lunch", "Dinner", "Snacks", "Notes"]:
            if nut.get(f):
                texts.append(nut[f].lower())
        combined = " ".join(texts)
        if combined.strip():
            caffeine_series[d] = 1.0 if any(kw in combined for kw in caffeine_kw) else 0.0
        else:
            caffeine_series[d] = None
    series["Caffeine Flag"] = caffeine_series

    # -- Late meal flag (binary) --
    late_meal_kw = ["late meal", "late dinner", "ate late", "midnight snack",
                    "late night eat", "eating late", "late snack"]
    late_meal_series = {}
    for d in date_range:
        texts = []
        dl = daily_by_date.get(d, {})
        for f in ["Midday Notes", "Evening Notes"]:
            if dl.get(f):
                texts.append(dl[f].lower())
        nut = nutrition_by_date.get(d, {})
        for f in ["Breakfast", "Lunch", "Dinner", "Snacks", "Notes"]:
            if nut.get(f):
                texts.append(nut[f].lower())
        combined = " ".join(texts)
        if combined.strip():
            late_meal_series[d] = 1.0 if any(kw in combined for kw in late_meal_kw) else 0.0
        else:
            late_meal_series[d] = None
    series["Late Meal Flag"] = late_meal_series

    return series, date_range


# ---------------------------------------------------------------------------
# Lag Correlation Analysis
# ---------------------------------------------------------------------------

# Predictor -> Outcome pairs to test, with max lag days and expected direction
LAG_PAIRS = [
    # Training -> Recovery
    ("Training Load", "HRV", 5, "negative", "Does training suppress HRV?"),
    ("Training Load", "RHR", 5, "positive", "Does training elevate RHR?"),
    ("Training Load", "Body Battery", 5, "negative", "Does training drain body battery?"),
    ("Training Load", "Sleep Score", 3, "negative", "Does training affect sleep?"),
    ("Max Anaerobic TE", "HRV", 5, "negative", "Does high-intensity suppress HRV?"),
    ("Max Anaerobic TE", "Morning Energy", 4, "negative", "Does intensity reduce next-day energy?"),

    # Sleep -> Cognition & Energy
    ("Sleep Score", "Morning Energy", 2, "positive", "Does sleep quality predict energy?"),
    ("Sleep Score", "Midday Focus", 2, "positive", "Does sleep predict focus?"),
    ("Sleep Score", "Day Rating", 2, "positive", "Does sleep predict day quality?"),
    ("Sleep Duration", "Morning Energy", 2, "positive", "Does sleep duration predict energy?"),
    ("Sleep Duration", "Midday Focus", 2, "positive", "Does duration predict focus?"),
    ("Deep %", "Morning Energy", 2, "positive", "Does deep sleep predict energy?"),
    ("Deep %", "Midday Focus", 2, "positive", "Does deep sleep predict focus?"),
    ("REM %", "Midday Mood", 2, "positive", "Does REM predict mood?"),
    ("REM %", "Evening Mood", 2, "positive", "Does REM predict evening mood?"),

    # HRV -> Subjective
    ("HRV", "Morning Energy", 2, "positive", "Does HRV predict energy?"),
    ("HRV", "Midday Focus", 2, "positive", "Does HRV predict focus?"),
    ("HRV", "Day Rating", 2, "positive", "Does HRV predict day quality?"),

    # Stress -> Everything
    ("Stress", "HRV", 3, "negative", "Does stress suppress HRV?"),
    ("Stress", "Sleep Score", 3, "negative", "Does stress hurt sleep?"),
    ("Stress", "Morning Energy", 2, "negative", "Does stress reduce energy?"),
    ("Stress", "Midday Focus", 2, "negative", "Does stress reduce focus?"),

    # Alcohol -> Recovery
    ("Alcohol", "Sleep Score", 2, "negative", "Does alcohol hurt sleep?"),
    ("Alcohol", "HRV", 3, "negative", "Does alcohol suppress HRV?"),
    ("Alcohol", "REM %", 2, "negative", "Does alcohol suppress REM?"),
    ("Alcohol", "Morning Energy", 2, "negative", "Does alcohol reduce next-day energy?"),
    ("Alcohol", "Midday Focus", 3, "negative", "Does alcohol affect focus?"),

    # Body Battery -> Subjective
    ("Body Battery", "Morning Energy", 1, "positive", "Does body battery predict energy?"),
    ("Body Battery", "Midday Focus", 1, "positive", "Does body battery predict focus?"),

    # Steps/Activity -> Sleep
    ("Steps", "Sleep Score", 2, "positive", "Do steps improve sleep?"),
    ("Steps", "Sleep Duration", 2, "positive", "Do steps improve sleep duration?"),

    # Habits -> Outcomes
    ("Habits Total", "Sleep Score", 2, "positive", "Do habits improve sleep?"),
    ("Habits Total", "Morning Energy", 2, "positive", "Do habits improve energy?"),
    ("Habits Total", "Day Rating", 2, "positive", "Do habits improve day quality?"),

    # -- Individual Habits -> Outcomes --
    ("Habit: Bed 10 PM",        "Sleep Score",     2, "positive", "Does bedtime habit improve sleep?"),
    ("Habit: Bed 10 PM",        "HRV",             2, "positive", "Does bedtime habit improve HRV?"),
    ("Habit: Bed 10 PM",        "Deep %",          1, "positive", "Does bedtime habit improve deep sleep?"),
    ("Habit: No PM Screens",    "Deep %",          1, "positive", "Do screen-free evenings improve deep sleep?"),
    ("Habit: No PM Screens",    "Sleep Score",     1, "positive", "Do screen-free evenings improve sleep?"),
    ("Habit: No AM Screens",    "Morning Energy",  1, "positive", "Do screen-free mornings improve energy?"),
    ("Habit: Walk Breathing",   "Stress",          1, "negative", "Does morning walk reduce stress?"),
    ("Habit: Walk Breathing",   "HRV",             2, "positive", "Does morning walk improve HRV?"),
    ("Habit: Walk Breathing",   "Morning Energy",  1, "positive", "Does morning walk improve energy?"),
    ("Habit: Creatine Hydrate", "Midday Focus",    1, "positive", "Does creatine/hydration improve focus?"),
    ("Habit: Creatine Hydrate", "Midday Energy",   1, "positive", "Does creatine/hydration improve energy?"),
    ("Habit: Wake 9:30",        "Morning Energy",  0, "positive", "Does waking on time improve energy?"),
    ("Habit: Physical Activity", "Sleep Score",    1, "positive", "Does physical activity improve sleep?"),
    ("Habit: Physical Activity", "HRV",            2, "positive", "Does physical activity improve HRV?"),

    # -- Nutrition -> Recovery & Cognition --
    ("Protein",            "Morning Energy",   1, "positive", "Does protein predict next-day energy?"),
    ("Protein",            "Midday Body Feel", 1, "positive", "Does protein predict physical recovery?"),
    ("Protein",            "HRV",              1, "positive", "Does protein predict HRV?"),
    ("Calories Consumed",  "Morning Energy",   1, "positive", "Do calories predict next-day energy?"),
    ("Calorie Balance",    "Morning Energy",   1, "positive", "Does calorie surplus predict energy?"),
    ("Calorie Balance",    "Midday Focus",     1, "positive", "Does calorie balance predict focus?"),
    ("Water",              "HRV",              1, "positive", "Does hydration predict HRV?"),
    ("Water",              "Morning Energy",   1, "positive", "Does hydration predict energy?"),
    ("Water",              "Midday Focus",     1, "positive", "Does hydration predict focus?"),
    ("Sugar Flag",         "Sleep Score",      1, "negative", "Does sugar hurt sleep?"),
    ("Sugar Flag",         "Morning Energy",   1, "negative", "Does sugar reduce next-day energy?"),
    ("Caffeine Flag",      "Sleep Score",      1, "negative", "Does caffeine hurt sleep?"),
    ("Caffeine Flag",      "Deep %",           1, "negative", "Does caffeine reduce deep sleep?"),
    ("Late Meal Flag",     "Sleep Score",      1, "negative", "Do late meals hurt sleep?"),

    # -- Session Subjective -> Recovery --
    ("Session RPE",         "HRV",             3, "negative", "Does perceived exertion suppress HRV?"),
    ("Session RPE",         "Morning Energy",  2, "negative", "Does perceived exertion reduce energy?"),
    ("Session RPE",         "Body Battery",    2, "negative", "Does perceived exertion drain body battery?"),
    ("Perceived Effort",    "Midday Body Feel", 2, "negative", "Does high effort reduce body feel?"),
    ("Post-Workout Energy", "Morning Energy",  1, "positive", "Does post-workout energy predict next-day?"),
    ("Post-Workout Energy", "HRV",             2, "positive", "Does post-workout energy predict HRV?"),

    # -- Body Feel as outcome --
    ("Training Load",       "Midday Body Feel", 2, "negative", "Does training load reduce body feel?"),
    ("Sleep Score",         "Midday Body Feel", 1, "positive", "Does sleep quality predict body feel?"),
    ("HRV",                 "Midday Body Feel", 1, "positive", "Does HRV predict body feel?"),

    # -- Cognition (from Overall Analysis) --
    ("Sleep Score",         "Cognition",       1, "positive", "Does sleep predict cognition?"),
    ("HRV",                 "Cognition",       1, "positive", "Does HRV predict cognition?"),
    ("Deep %",              "Cognition",       1, "positive", "Does deep sleep predict cognition?"),
    ("Protein",             "Cognition",       1, "positive", "Does protein predict cognition?"),
    ("Water",               "Cognition",       1, "positive", "Does hydration predict cognition?"),
    ("Alcohol",             "Cognition",       2, "negative", "Does alcohol hurt cognition?"),
]


def compute_lag_correlation(series, date_range, predictor, outcome, max_lag):
    """Compute correlation between predictor on day D and outcome on day D+lag.

    Returns list of (lag, pearson_r, pearson_p, spearman_rho, spearman_p, n) tuples.
    """
    pred_series = series.get(predictor, {})
    out_series = series.get(outcome, {})

    results = []
    for lag in range(0, max_lag + 1):
        pred_vals = []
        out_vals = []
        for i, d in enumerate(date_range):
            if i + lag >= len(date_range):
                break
            outcome_date = date_range[i + lag]
            pv = pred_series.get(d)
            ov = out_series.get(outcome_date)
            pred_vals.append(pv)
            out_vals.append(ov)

        pr, pp, pn = _pearson(pred_vals, out_vals)
        sr, sp, sn = _spearman(pred_vals, out_vals)
        results.append((lag, pr, pp, sr, sp, pn))

    return results


def run_lag_analysis(series, date_range, pairs=None, significance=0.05):
    """Run lag correlation analysis for all defined pairs.

    Returns list of findings sorted by effect size.
    """
    if pairs is None:
        pairs = LAG_PAIRS

    findings = []

    for predictor, outcome, max_lag, expected_dir, question in pairs:
        if predictor not in series or outcome not in series:
            continue

        lag_results = compute_lag_correlation(series, date_range, predictor, outcome, max_lag)

        # Find the strongest significant correlation
        best_lag = None
        best_r = 0
        best_p = 1.0
        best_rho = None
        best_sp = 1.0
        best_n = 0

        for lag, pr, pp, sr, sp, n in lag_results:
            if pr is not None and pp is not None and pp < significance:
                if abs(pr) > abs(best_r):
                    best_lag = lag
                    best_r = pr
                    best_p = pp
                    best_rho = sr
                    best_sp = sp if sp is not None else 1.0
                    best_n = n

        if best_lag is not None:
            # Check if direction matches expectation
            if expected_dir == "negative":
                direction_match = best_r < 0
            elif expected_dir == "positive":
                direction_match = best_r > 0
            else:
                direction_match = True

            findings.append({
                "predictor": predictor,
                "outcome": outcome,
                "question": question,
                "best_lag": best_lag,
                "pearson_r": round(best_r, 3),
                "pearson_p": round(best_p, 4),
                "spearman_rho": round(best_rho, 3) if best_rho is not None else None,
                "spearman_p": round(best_sp, 4) if best_sp is not None else None,
                "n": best_n,
                "expected_direction": expected_dir,
                "direction_match": direction_match,
                "effect_size": abs(best_r),
                "all_lags": [
                    {"lag": lag, "r": round(pr, 3) if pr else None,
                     "p": round(pp, 4) if pp else None, "n": n}
                    for lag, pr, pp, sr, sp, n in lag_results
                ],
            })

    # Sort by effect size descending
    findings.sort(key=lambda f: f["effect_size"], reverse=True)
    return findings


# ---------------------------------------------------------------------------
# Output Formatting
# ---------------------------------------------------------------------------

def _effect_label(r):
    """Classify correlation strength."""
    ar = abs(r)
    if ar >= 0.7:
        return "STRONG"
    elif ar >= 0.5:
        return "MODERATE"
    elif ar >= 0.3:
        return "WEAK-MOD"
    elif ar >= 0.1:
        return "WEAK"
    return "NEGLIGIBLE"


def _stars(p):
    """Significance stars."""
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    return ""


def print_findings(findings, verbose=False):
    """Print human-readable findings summary."""
    if not findings:
        print("\nNo significant lag correlations found.")
        print("This usually means insufficient data. Try --days 180 or more.")
        return

    print(f"\n{'='*78}")
    print(f"  LAG CORRELATION ANALYSIS — {len(findings)} significant findings")
    print(f"{'='*78}")

    for i, f in enumerate(findings, 1):
        direction = "+" if f["pearson_r"] > 0 else "-"
        match_icon = "v" if f["direction_match"] else "X"
        lag_text = f"same day" if f["best_lag"] == 0 else f"+{f['best_lag']}d lag"

        print(f"\n  {i}. {f['question']}")
        print(f"     {f['predictor']} -> {f['outcome']} ({lag_text})")
        print(f"     r = {direction}{abs(f['pearson_r']):.3f}{_stars(f['pearson_p'])}  "
              f"p = {f['pearson_p']:.4f}  n = {f['n']}  "
              f"[{_effect_label(f['pearson_r'])}]  "
              f"direction: {match_icon}")

        if f["spearman_rho"] is not None:
            print(f"     rho = {f['spearman_rho']:.3f}  p = {f['spearman_p']:.4f}  (rank)")

        if verbose:
            print(f"     All lags:")
            for lag_data in f["all_lags"]:
                if lag_data["r"] is not None:
                    sig = _stars(lag_data["p"]) if lag_data["p"] else ""
                    print(f"       lag {lag_data['lag']}d: r={lag_data['r']:.3f}{sig}  "
                          f"p={lag_data['p']:.4f}  n={lag_data['n']}")

    # Summary
    strong = [f for f in findings if f["effect_size"] >= 0.5]
    moderate = [f for f in findings if 0.3 <= f["effect_size"] < 0.5]
    unexpected = [f for f in findings if not f["direction_match"]]

    print(f"\n{'='*78}")
    print(f"  SUMMARY")
    print(f"{'='*78}")
    print(f"  Total significant: {len(findings)}")
    print(f"  Strong (|r| >= 0.5): {len(strong)}")
    print(f"  Moderate (|r| 0.3-0.5): {len(moderate)}")
    if unexpected:
        print(f"\n  UNEXPECTED DIRECTIONS ({len(unexpected)}):")
        for f in unexpected:
            print(f"    - {f['predictor']} -> {f['outcome']}: expected {f['expected_direction']}, "
                  f"got r={f['pearson_r']:+.3f}")

    # Actionable insights
    print(f"\n  KEY INSIGHTS FOR YOUR DATA:")
    for f in findings[:5]:
        lag_text = "same day" if f["best_lag"] == 0 else f"{f['best_lag']} day(s) later"
        if f["direction_match"]:
            if f["pearson_r"] > 0:
                print(f"    - Higher {f['predictor']} predicts higher {f['outcome']} {lag_text} "
                      f"(r={f['pearson_r']:.2f})")
            else:
                print(f"    - Higher {f['predictor']} predicts lower {f['outcome']} {lag_text} "
                      f"(r={f['pearson_r']:.2f})")
        else:
            print(f"    - SURPRISING: {f['predictor']} and {f['outcome']} have "
                  f"{'positive' if f['pearson_r'] > 0 else 'negative'} relationship "
                  f"(expected {f['expected_direction']}, r={f['pearson_r']:.2f})")


def save_json(findings, output_path):
    """Save findings as JSON for programmatic use."""
    output = {
        "generated": str(date.today()),
        "methodology": "Pearson + Spearman lag correlation",
        "significance_threshold": 0.05,
        "findings": findings,
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"\nJSON output saved to: {output_path}")


# ---------------------------------------------------------------------------
# Data Quality Report
# ---------------------------------------------------------------------------

def print_data_quality(series, date_range):
    """Print data completeness for each metric."""
    print(f"\n  DATA QUALITY ({len(date_range)} days in window)")
    print(f"  {'Metric':<25} {'Non-null':>8} {'Coverage':>8}")
    print(f"  {'-'*25} {'-'*8} {'-'*8}")

    for name in sorted(series.keys()):
        s = series[name]
        non_null = sum(1 for d in date_range if s.get(d) is not None)
        pct = non_null / len(date_range) * 100 if date_range else 0
        flag = "  <-- sparse" if pct < 30 else ""
        print(f"  {name:<25} {non_null:>8} {pct:>7.0f}%{flag}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Lag correlation analysis for health metrics.")
    parser.add_argument("--days", type=int, default=90, help="Number of days to analyze (default: 90)")
    parser.add_argument("--pair", help='Specific pair to analyze, e.g. "HRV -> Cognition"')
    parser.add_argument("--output", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all lag values")
    parser.add_argument("--significance", type=float, default=0.05, help="P-value threshold (default: 0.05)")
    parser.add_argument("--date", help="End date for analysis window (YYYY-MM-DD, default: yesterday)")
    args = parser.parse_args()

    end_date = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)

    print(f"Lag Correlation Analysis")
    print(f"  Window: {end_date - timedelta(days=args.days)} to {end_date} ({args.days} days)")
    print(f"  Significance: p < {args.significance}")

    wb = get_workbook()
    print("  Reading data from Google Sheets...")
    data = read_all_data(wb)

    print("  Building time series...")
    series, date_range = build_time_series(data, args.days, end_date)

    # Data quality report
    print_data_quality(series, date_range)

    # Filter pairs if specific pair requested
    pairs = LAG_PAIRS
    if args.pair:
        search = args.pair.lower()
        pairs = [p for p in LAG_PAIRS
                 if search in p[0].lower() or search in p[1].lower() or search in p[4].lower()]
        if not pairs:
            print(f"\nNo matching pairs for '{args.pair}'. Available metrics:")
            for name in sorted(series.keys()):
                print(f"  - {name}")
            sys.exit(1)

    print(f"\n  Analyzing {len(pairs)} predictor-outcome pairs...")
    findings = run_lag_analysis(series, date_range, pairs, args.significance)

    if args.output == "json":
        output_path = Path(__file__).parent / "analysis_output" / "lag_correlations.json"
        output_path.parent.mkdir(exist_ok=True)
        save_json(findings, output_path)
    else:
        print_findings(findings, verbose=args.verbose)

    print("\nDone.")


if __name__ == "__main__":
    main()
