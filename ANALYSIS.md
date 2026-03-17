# NS Habit Tracker — Analytics & Insights Hub

This document is the living record of all analytics work: what we've found, what we're investigating, and what statistical models are in progress or planned.

---

## Data Inventory (what we have to work with)

| Source | Tab | Rows | Key Signals |
|---|---|---|---|
| Garmin (auto) | Garmin | ~1030 days | HRV, Resting HR, Sleep Score, Body Battery, Steps, Stress, Calories, Activity |
| Garmin (auto) | Sleep | ~870 days | Sleep stages (deep/light/REM), bedtime, wake time, HRV overnight, BB gained, score |
| Garmin (auto) | Session Log | ~374 sessions | Workout type, duration, HR zones, training effect, fatigue ratings |
| Manual | Habits | — | 7 daily habits, morning energy score, notes |
| Manual | Nutrition | ~1030 days | Calories burned (auto) + consumed, macros, water |
| **NEW** | Daily Ratings | — | Midday + evening subjective check-ins (see below) |

**Total: ~3 years of data. More than enough for regression.**

---

## Subjective Check-in Schedule

Two check-ins per day. Times chosen based on your goals:

| Check-in | Time | Why |
|---|---|---|
| **Midday** | 12:00 – 1:00 PM | After morning habits are done, before afternoon energy dip. Captures morning clarity and physical feel. |
| **Evening** | 9:00 – 9:30 PM | 30 min before 10 PM bedtime target. Captures full-day reflection without cutting into wind-down. |

### What each rating means

**Midday ratings (all 1-10, 10 = best):**
- `Midday Energy` — Physical energy level. 1 = exhausted, can barely function. 10 = fully charged.
- `Midday Focus` — Mental clarity, memory, cognitive sharpness. Low = brain fog, forgetting things, can't concentrate.
- `Midday Mood` — Emotional tone. 1 = depressed/irritable. 10 = positive, motivated.
- `Midday Body Feel` — Physical wellness. Soreness, heaviness, illness. 10 = feel great physically.
- `Midday Notes` — Free text. e.g. "couldn't remember anything this morning", "felt wired after coffee", "really tired after waking up"

**Evening ratings (all 1-10, 10 = best):**
- `Evening Energy` — Did you have enough energy throughout the day?
- `Evening Focus` — How was mental performance today overall?
- `Evening Mood` — How did you feel emotionally across the whole day?
- `Perceived Stress` — Subjective stress level. 1 = no stress, 10 = maxed out.
- `Day Rating` — One number for the whole day. "Overall, how was today?"
- `Evening Notes` — Free text. e.g. "bad day — argument with someone", "felt amazing, very productive", "mind was totally off today"

---

## Questions We're Investigating

### Sleep Quality Drivers
- What predicts a high Sleep Score the most? (bedtime? previous stress? workout timing? HRV?)
- Does skipping "No screens 1hr before bed" measurably hurt sleep score?
- Does going to bed at 10 PM vs later actually improve sleep stage composition?
- What's the threshold: how many hours of sleep before REM starts improving meaningfully?

### HRV Drivers
- Which habits have the strongest correlation with next-morning HRV?
- Does workout intensity (training effect) suppress HRV the next day, and by how much?
- Does subjective stress (Evening Perceived Stress) predict lower HRV the next morning?
- Is there a "recovery lag" — e.g., does a hard workout hurt HRV for 1–2 days, not just the next day?

### Cognitive Clarity & Brain Fog
- What predicts high Midday Focus scores?
- Does poor sleep (low score or low deep sleep %) directly correlate with brain fog the next morning?
- Does HRV on waking predict same-day cognitive performance (Midday Focus)?
- Does Body Battery at wake predict focus better than sleep score?

### Wellbeing & Mood
- What objective metrics best predict high Day Rating?
- Is there a lag effect — does yesterday's HRV predict today's mood?
- Does more physical activity correlate with higher Evening Mood?

### Body Battery
- What recovers Body Battery most — sleep duration, sleep score, or sleep stage composition?
- Does stress level the previous day suppress Body Battery gained during sleep?

---

## Statistical Methods Planned

### Phase 1 — Correlation Matrix (can do now)
Run a full Pearson/Spearman correlation matrix across all numeric variables to find the strongest relationships. Outputs a heatmap showing what correlates with what.

**Script:** `analysis_correlations.py` (to be built)

### Phase 2 — Multiple Linear Regression
Predict a target outcome from multiple input variables simultaneously.

**Planned models:**
| Target (Y) | Predictors (X) |
|---|---|
| Next-morning HRV | Bedtime, sleep duration, deep sleep %, workout training effect, evening stress, day rating |
| Sleep Score | Bedtime, steps, evening stress, screen time habit, workout timing |
| Midday Focus (1-10) | Previous night HRV, sleep score, deep sleep %, body battery at wake |
| Day Rating (1-10) | HRV, sleep score, steps, workout done (Y/N), habit completion count |
| Body Battery gained | Sleep duration, sleep score, evening stress, previous day activity calories |

**Script:** `analysis_regression.py` (to be built)

### Phase 3 — Lag Analysis
Test whether effects are delayed. E.g., does a hard workout hurt HRV for 1 day or 2?

**Script:** `analysis_lag.py` (to be built)

### Phase 4 — Pattern Detection
- Weekly cycles: are certain days of the week consistently worse for HRV or mood?
- Seasonal patterns: does sleep duration/HRV change across months?
- Habit streaks: does completing all 7 habits for 3+ consecutive days show a measurable HRV boost?

---

## Key Findings (updated as we discover them)

*Nothing yet — Daily Ratings tab just created. Will begin populating findings once 30+ days of subjective data exist.*

---

## Prerequisites for Regression Scripts

```
pip install pandas scipy scikit-learn matplotlib seaborn
```

All scripts will read from Google Sheets via the same `get_workbook()` function used in `garmin_sync.py`. No local files needed.

---

## Notes on Data Quality

- **Minimum for regression:** 30 paired observations. We have 870+ for objective data.
- **Subjective data:** Will take 30–60 days to accumulate enough for meaningful regression.
- **Missing values:** Many older rows lack some fields. Scripts will drop NaN rows per model, not globally.
- **Confounders:** Multiple things change at once (e.g., started exercising more AND sleeping more). Regression will surface this — we'll note confounders in findings.
- **Correlation ≠ causation:** Findings will be framed as associations, not proof of cause.
