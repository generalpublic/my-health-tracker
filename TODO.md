# Health Tracker — To-Do List

> **Claude: Read this file at the start of every session and summarize what's pending.**

---

## Priority

- [ ] **Mobile Dashboard (PWA)** — Redesign dashboard as a mobile-first Progressive Web App for iPhone
  - Responsive phone layout: home (today's scores), sleep, activity, trends screens
  - PWA manifest + service worker for home screen install (full-screen, no Safari chrome)
  - Build directly in code with mobile-first CSS (Tailwind) — no Figma needed
  - Data source: existing SQLite → exported JSON (no pipeline changes)

---

## In Progress

- [ ] **Voice Logger PWA** — Voice-to-log system for nutrition + workouts from phone
  - Code is built (`voice_logger/` directory), not yet deployed
  - **Blocked on user action**: Need Anthropic API key, Nutritionix API key, Vercel account
  - Next: Set up API keys → run `setup_totp.py` → deploy to Vercel → test from phone
  - Plan file: `.claude/plans/flickering-hopping-pizza.md`

---

## Pending — Infrastructure

- [x] **Fix Windows Task Scheduler path** (completed 2026-03-17)

---

## Pending — Analysis Scripts

- [x] **Build `analysis_lag.py`** — Lag correlation analysis (completed 2026-03-16)
- [x] **Build `analysis_regression.py`** — Multiple regression models (completed 2026-03-16)

---

## Pending — Daily Workflow

- [ ] **Start filling in Daily Log daily** — User needs to begin entering subjective data (mood, energy, focus)
  - [ ] **Build a daily prompt system** — Create a popup, Google Form, or simple mobile-friendly form that prompts all Daily Log fields at the right times (e.g., morning energy after waking, midday focus/mood at lunch, evening rating before bed), with phone alerts/notifications so there's no need to manually open the spreadsheet
- [x] **`garmin_sync.py` auto-append to Daily Log** — Auto-creates a row with Day + Date when syncing, skips if row already exists (completed 2026-03-17)

---

## Pending — Documentation

- [ ] **Polish Executive Brief Word doc** — `Health Tracker - Executive Brief.docx` needs refinement
  - Review content, styling, and formatting for executive presentation readiness
  - Generator script: `create_brief_docx.py`

---

## Pending — Styling / Maintenance

- [ ] **Update `reformat_style.py`** — Codify final design (tab-colored headers + amber manual cols)
- [x] **Renamed project from "NS Habit Tracker" to "Health Tracker"** — Google Sheet, all code, docs, scheduler scripts (completed 2026-03-17)
- [x] **Delete migration scripts** — `migrate_cognition.py` and `migrate_oa_layout.py` (completed 2026-03-17)

---

## Completed

- [x] Project restructured and cleaned up (2026-03-11)
- [x] Garmin tab: Sleep Score moved to column B (2026-03-11)
- [x] Auto-backfill added to `garmin_sync.py` (2026-03-11)
- [x] Spreadsheet styling: tab-colored headers, alternating row banding (2026-03-12)
- [x] SQLite parallel database + migration script (2026-03-12)
- [x] Dashboard HTML created (2026-03-12)
- [x] Voice Logger code built — `voice_logger/` directory (2026-03-16)
- [x] Cognition columns migrated from Sleep to Overall Analysis (2026-03-17)
- [x] Overall Analysis restructured: Day col, Readiness Label next to Score, 12 cols (2026-03-17)
- [x] Design Ruleset codified in CLAUDE.md (2026-03-17)
- [x] Dashboard sleep score thresholds unified (2026-03-17)
- [x] `garmin_sync.py` auto-append to Daily Log (2026-03-17)
- [x] Dashboard-Sheets color grading alignment — all 5 divergent metrics fixed (2026-03-18)
- [x] Removed Garmin Sleep Score from dashboard (2026-03-18)
- [x] Workout activity markers + 3 workout metrics added to dashboard (2026-03-18)
