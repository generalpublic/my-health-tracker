# Health Tracker — Executive Brief

## What It Is

Health Tracker is a personal health analytics platform that automatically collects 50+ daily biometrics from a Garmin wearable, combines them with manual habit tracking, and produces a daily Readiness Score — a single number (1-10) that tells you how prepared your body and mind are for the day ahead.

Every morning, a push notification arrives on your phone with your score, a sleep summary, training load status, and 3-5 actionable recommendations grounded in peer-reviewed research. No dashboards to check, no apps to open. The insight comes to you.

The system was architected and engineered entirely with Claude (Anthropic) serving as both the development partner and the runtime analytical engine — a demonstration of what AI-augmented personal health infrastructure looks like when built with rigor.

---

## The Problem

Wearables collect enormous amounts of data. Garmin alone produces 50+ metrics per day across sleep, heart rate variability, training load, stress, and recovery. But the native apps present this data in isolation — sleep in one screen, HRV in another, training in a third. No synthesis. No context. No personalization for medical conditions.

The result: most people glance at a number, don't know what it means relative to *their* baseline, and move on. The data exists but never becomes insight.

Health Tracker solves this by building a personal analytical layer on top of raw wearable data — one that understands your physiology, tracks your research interests, and delivers concise, evidence-backed guidance every morning.

---

## How It Works

### Architecture Overview

```
INGESTION              STORAGE                 ANALYSIS                DELIVERY
-----------            -----------             -----------             -----------
Garmin API  ---------> Google Sheets --------> Readiness Engine -----> Push Notification
  (50+ metrics)        (source of truth)       (sigmoid z-scores)     (Pushover API)
                            |                       |
Voice Logger --------> SQLite Mirror           Knowledge Base -------> Color-Graded Sheets
  (nutrition/workout)  (offline backup)        (100+ research           (research-backed
   via Claude Haiku)    (retry queue)           entries, 8 domains)      thresholds)
                            |                       |
Garmin Export -------> Raw Data Archive        Health Profile -------> Weekly Validation
  (historical bulk)                            (conditions,             (predictions vs
                                                biomarkers,              outcomes)
                                                medications)
```

### Data Pipeline

A Python script runs nightly at 8 PM via the operating system's native scheduler (Task Scheduler on Windows, launchd on macOS, cron on Linux). It:

1. **Pulls yesterday's data from Garmin Connect** — sleep stages (deep, light, REM, awake), overnight HRV, resting heart rate, body battery, steps, stress, and any workout details including HR zones and training effect.

2. **Writes to Google Sheets first, SQLite second.** Google Sheets serves as the human-readable source of truth. SQLite provides fast local queries and acts as a resilience layer — if the Sheets API is unavailable, data queues locally and retries on the next run. No data is ever lost.

3. **Applies visual formatting automatically.** Every numeric column gets color-graded (red-yellow-green) based on research-backed thresholds. Manual-entry columns are highlighted yellow. Weeks are visually grouped with alternating row bands. Column widths, text wrapping, and alignment are computed and applied — the user never manually resizes anything.

4. **Triggers the analysis engine**, which computes the Readiness Score, generates insights, and optionally sends a morning notification.

For manual data entry (meals, workouts, subjective ratings), a **voice-enabled Progressive Web App** lets the user speak naturally — "had two eggs with spinach at 7am" — and Claude Haiku parses it into structured nutrition data, enriched by Nutritionix API lookups, and writes it directly to the correct spreadsheet tab.

---

## The Analysis Engine

### Readiness Score: Methodology

The Readiness Score is a composite metric (1-10) built from four evidence-based components:

| Component | Weight | Why This Weight |
|-----------|--------|-----------------|
| **HRV Status** | 35% | Strongest single predictor of next-day readiness (JAMA MESA 2020) |
| **Sleep Quality** | 30% | Second strongest; sleep architecture matters more than duration alone |
| **Resting Heart Rate** | 20% | Reliable but lagging indicator — downstream of HRV changes |
| **Subjective Wellness** | 15% | Self-reported energy + mood; downweighted when sleep debt detected (Van Dongen 2003) |

Each component is scored against the individual's own rolling baseline — not population averages. An HRV of 38ms might be excellent for one person and concerning for another. The system learns your normal.

**Why sigmoid scoring instead of linear?** Cognitive impairment doesn't scale linearly. Research shows it accelerates in the critical decision zone (the difference between "Fair" and "Good" matters more than the difference between "Good" and "Optimal"). The sigmoid curve captures this — it's the same mathematical approach used by WHOOP and Oura in their proprietary scoring.

```
z = (today - 30_day_mean) / 30_day_std_dev
score = 1 + 9 / (1 + e^(-1.5 * z))
```

### Sleep Analysis

Rather than relying on Garmin's proprietary sleep score, the system computes an independent Sleep Analysis Score (0-100) from seven metrics:

- **Total sleep duration** (25 pts) — scored 0 at 4 hours or less, full marks at 7+
- **Deep sleep %** (20 pts) — the restorative stage; research target is 15-20% of total sleep
- **REM sleep %** (20 pts) — critical for memory consolidation and emotional regulation
- **Overnight HRV** (15 pts) — parasympathetic recovery during sleep
- **Awakenings** (10 pts) — sleep fragmentation degrades quality regardless of duration
- **Body battery gained** (10 pts) — Garmin's proprietary recovery metric, used as a secondary signal
- **Bedtime modifier** (+5 to -10 pts) — earlier bedtimes correlate with better sleep architecture

**Sleep debt tracking** follows the Van Dongen 2003 model from UPenn — the landmark study showing that subjective sleepiness plateaus after 3 days while cognitive decline continues silently. The system uses a 5-day weighted average (recent nights weighted more heavily) compared against a 30-day baseline to detect accumulating debt before the user feels it.

### Training Load

Training load analysis implements the **Acute:Chronic Workload Ratio** (ACWR) from Gabbett 2016 — the framework used by professional sports teams to manage injury risk:

- **Sweet spot** (0.8-1.3): training matches fitness level
- **High zone** (1.3-1.5): elevated risk, monitor recovery closely
- **Spike zone** (>1.5): significantly elevated injury/illness risk
- **Detraining** (<0.8): insufficient stimulus

### Advanced Statistics (Built From Scratch)

Three analytical scripts provide deeper pattern analysis — all implemented using only Python's standard library (no NumPy, no SciPy):

- **Correlation analysis** — Pearson correlations across all data domains with false discovery rate correction
- **Multivariate regression** — OLS via the normal equation with variance inflation factor (VIF) for multicollinearity detection, plus leave-one-out cross-validation
- **Time-lagged correlation** — answers questions like "does a hard workout suppress HRV two days later?" with autocorrelation-adjusted significance testing (Bayley & Hammersley 1946)

Building these from scratch was a deliberate choice — it eliminates heavy dependencies, keeps the project portable, and demonstrates that the analytical depth doesn't require a data science stack.

---

## AI-Powered Knowledge System

### Four Claude Skills

The system extends Claude with four specialized skills that operate as domain-specific analytical tools:

**`/health-insight`** — Query-driven analysis that cross-references the research library with actual user data. Ask "why is my HRV dropping?" and it loads relevant domain knowledge, pulls your last 7-14 days of data, identifies the pattern, cites the research, and recommends specific actions. Every insight includes citations back to numbered entries in the research library.

**`/update-intel`** — Processes new health research material (podcast transcripts, journal articles, book excerpts) into a structured knowledge base. The system auto-classifies by domain, deduplicates against existing content, extracts quantifiable thresholds, and compiles findings into thematic Research Universe documents. No duplicate entries, no per-source silos — claims are merged into existing sections with consolidated citations.

**`/verify-intel`** — A fact-checking gate that evaluates health claims before they enter the library. Cross-references against a source hierarchy (meta-analyses > RCTs > clinical guidelines > expert consensus > podcast opinions). Flags distortion patterns like cherry-picking, dose extrapolation, and animal-to-human leaps. Only verified or partially-supported claims proceed to compilation.

**`/update-profile`** — Ingests personal medical documentation (lab results, diagnoses, provider notes) into a structured health profile. This profile drives personalized analysis — conditions inform readiness weight adjustments, biomarkers correlate with physiological trends, and accommodations shape how recommendations are formatted and prioritized.

### Three-Layer Knowledge Hierarchy

```
Layer 1: Research Universe Files (8 domains)
         Human-readable compilations with thematic organization
         Multi-source citations: "(Entries 3, 7, 13)"

Layer 2: Domain Briefs (<200 lines each)
         Token-efficient summaries for fast AI queries
         Key thresholds, consensus positions, open questions

Layer 3: Runtime Knowledge JSON (100+ entries)
         Structured triggers that auto-fire insights
         Pattern → Interpretation → Cognitive Impact → Recommendation
         Each entry includes confidence rating and citation
```

The trigger system is particularly elegant — knowledge entries can include data conditions that fire automatically when met:

```json
{
  "pattern": "sleep_debt_above_1_5h",
  "trigger": {"tab": "sleep", "field": "Total Sleep", "op": "<", "value": 6.5, "agg": "avg", "lookback": 5},
  "recommendation": "Prioritize 8.5-9h sleep for 3-4 nights (Van Dongen et al. 2003)"
}
```

New research can be added to the knowledge base and immediately influence daily analysis — no code changes required.

---

## Delivery: Raw Data to Phone Notification

### Morning Briefing

Every morning, a push notification arrives via Pushover:

```
READINESS: 7.8 (Good) | Confidence: High

SLEEP: 7.2h | Deep 18% | REM 21% | HRV 42ms | Bed 11:15pm
  7d avg: Bed +/-32min | Wake +/-28min | Debt: 0.2h

EXPECT: Above-baseline attention. Stable mood. Strong fatigue resistance.

FLAGS:
  - HRV above baseline (z=+1.2) — autonomic ready
  - ACWR 0.95 — sweet spot training load
  - Habits: 6/7 completed

DO:
  - Morning: prioritize high-intensity or skill work
  - Consider extra strength session if energy > 8/10
```

All personal health information (condition names, medications, specific biomarker values) is automatically stripped before sending through the third-party notification service. The sanitization function ensures PHI never leaves the local environment.

### Color-Graded Spreadsheets

Every numeric column in Google Sheets is conditionally formatted with research-backed thresholds:

- **Sleep metrics**: deep sleep below 12% shows red (below clinical minimum for restorative sleep); above 20% shows green (research target range)
- **HRV**: thresholds calibrated to individual baseline deviations, not population norms
- **Bedtime**: discrete color bands — before 11 PM (green), 11 PM-1 AM (yellow), after 1 AM (red)
- **Training metrics**: duration, distance, and calorie thresholds derived from ACSM guidelines and Harvard calorie burn research

The color system follows a strict 4-tier priority hierarchy: conditional formatting gradients take precedence over manual-entry highlighting, which takes precedence over weekly banding, which takes precedence over header styling. This prevents visual conflicts when multiple rules apply to the same cell.

### Weekly Validation Loop

The system doesn't just predict — it validates. Every week, it automatically correlates its readiness predictions against actual next-day outcomes (self-reported morning energy and day rating). It computes Pearson correlations and reports:

- **Strong** (r > 0.7): model is well-calibrated
- **Moderate** (0.4-0.7): acceptable, monitor for drift
- **Weak** (0.2-0.4): consider weight recalibration

This closes the loop between prediction and reality — the system knows when its own model is drifting.

---

## Engineering Quality

### Self-Verifying, Self-Healing

Every write to Google Sheets triggers two verification passes:

1. **Structural verification** — confirms all tabs have correct headers, data types are valid (dates are text, not serials; numbers are numbers, not strings), no blank rows in the middle of data, dates are properly ordered.

2. **Formatting verification** — confirms all conditional formatting rules exist on the correct columns with correct thresholds, AND spot-checks that graded columns contain actual numbers. This second check catches a subtle bug: Google Sheets gradient formatting silently ignores text cells even when they contain "82" — the number must be stored as a numeric type.

If either check fails, the system auto-repairs: converts text-as-number cells to actual floats, re-applies formatting rules, and re-verifies. All repair logic is idempotent — safe to run repeatedly.

### Dual-Storage Resilience

The dual-write strategy (Google Sheets + SQLite) with a retry queue means the system handles API outages gracefully:

- SQLite writes always succeed locally
- Failed Sheets writes are queued in `pending_sync.json`
- Next sync retries all pending dates before processing new data
- Google Sheets remains the source of truth; SQLite is the safety net

### Cross-Platform Portability

The entire system runs identically on Windows, macOS, and Linux:

- Credentials use the OS-native keyring (Windows Credential Manager / macOS Keychain / libsecret) — same API call, different backend
- All file paths are dynamic (`Path(__file__).parent`) — no hardcoded paths
- The only platform-specific component is the scheduler configuration
- Migration to a new machine is an 8-step checklist, most of which is "copy folder, install dependencies, store password"

### Zero Credential Exposure

- Garmin password lives only in the OS keyring — never in any file
- Google service account key is gitignored and never read by the AI assistant
- Pushover tokens are in `.env` (gitignored)
- Protected health information stays in a gitignored `profiles/` directory
- Notifications are sanitized before leaving the local environment
- Work logs, commit messages, and session files never contain medical details

### Batch Write Optimization

Google Sheets enforces a 60-request-per-minute quota. The system respects this by reading entire columns, modifying the list in memory, and writing back in a single batch call — never per-cell updates in a loop. Mixed data types in the same row are handled with a split strategy: `RAW` mode for dates/times (prevents Sheets from converting "2024-03-17" into a serial number), `USER_ENTERED` for numeric columns (enables formula evaluation and gradient formatting).

---

## Built With Claude

Claude (Anthropic) served three roles in this project:

### 1. Architect
Claude designed the system architecture from the ground up — the 4-layer pipeline, the dual-storage strategy, the sigmoid scoring methodology, the knowledge hierarchy, and the PHI boundary model. Every architectural decision was discussed, debated, and justified before implementation.

### 2. Engineer
Claude wrote every line of Python in the project. The codebase includes:
- 15+ production scripts with full error handling
- Custom implementations of OLS regression, Pearson correlation, and lag analysis without external math libraries
- A serverless voice logger PWA with TOTP authentication
- A database migration system
- Cross-platform scheduler setup scripts
- Comprehensive verification and self-repair systems

### 3. Runtime Analytical Engine
Claude operates as the analytical brain at runtime through the skills system. When the user asks `/health-insight why is my energy low?`, Claude loads domain knowledge, pulls real data from Google Sheets, computes trends and anomalies, cross-references against the research library, and synthesizes a personalized answer with citations. This isn't a chatbot answering health questions — it's an AI analyst with access to your actual biometric data and a curated research library.

The skills system also serves as a quality gate for the knowledge base. New research material passes through `/verify-intel` (fact-checking) before `/update-intel` (compilation) files it into the library. Claims are rated on an evidence hierarchy, distortion patterns are flagged, and only verified findings enter the system. The knowledge base improves over time without accumulating misinformation.

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Data Source | Garmin Connect API | 50+ daily biometrics |
| Data Source | Nutritionix API | Nutrition lookup for voice logger |
| Storage (Primary) | Google Sheets API (gspread) | Human-readable source of truth |
| Storage (Backup) | SQLite | Local mirror, offline queries, resilience |
| Analysis | Python 3.14 (stdlib only for stats) | Readiness scoring, correlation, regression |
| Knowledge | Claude AI (skills system) | Research curation, insight generation |
| NLP | Claude Haiku | Voice-to-structured-data parsing |
| Notifications | Pushover API | Morning briefing delivery |
| Voice Input | Web Speech API + Vercel serverless | PWA for nutrition/workout logging |
| Auth | TOTP (HMAC-based) | Voice logger authentication |
| Credentials | OS keyring (cross-platform) | Zero-file credential storage |
| Scheduling | Task Scheduler / launchd / cron | Nightly automated sync |

---

## What Makes This Impressive

**It's not a dashboard — it's an analyst.** Most health platforms show you charts. This one tells you what the charts mean, why they matter today, and what to do about it — backed by cited research, calibrated to your personal baseline, and aware of your medical context.

**The knowledge system learns without code changes.** New research is ingested, fact-checked, compiled into thematic documents, and converted into auto-firing triggers — all through the AI skill system. The analytical engine gets smarter over time without touching a single line of Python.

**It validates its own predictions.** The weekly correlation between readiness scores and actual next-day outcomes creates a feedback loop that most commercial platforms lack entirely. The system knows when it's wrong.

**The statistics are built from scratch.** Pearson correlation with FDR correction, OLS regression with VIF multicollinearity detection, time-lagged correlation with autocorrelation-adjusted significance testing — all implemented in pure Python. No NumPy, no SciPy, no heavy dependencies. The project stays portable and lightweight while delivering graduate-level statistical analysis.

**PHI handling is enterprise-grade.** Medical data stays in a gitignored directory. Notifications are sanitized. Work logs are generic. Commit messages reveal nothing. The system was designed as if it would be audited — because personal health data deserves that standard even in a personal project.

**Every write is verified.** Not "we hope the formatting applied correctly" — every single write triggers structural and formatting verification, with auto-repair if anything fails. The user has never had to manually fix a spreadsheet formatting issue. That level of operational reliability is unusual in any project, let alone a personal one.

---

*This project represents approximately 15,000+ lines of production Python, a curated research library spanning 8 health domains, and an AI-powered analytical engine — all orchestrated by Claude as architect, engineer, and runtime intelligence.*
