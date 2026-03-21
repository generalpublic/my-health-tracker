# Health Tracker — To-Do List

> **Claude: Read this file at the start of every session and summarize what's pending.**

---

## Priority

- [ ] **Review product strategy conversation** — Revisit the 2026-03-20 strategy discussion saved in `.claude/projects/.../memory/project_product_strategy_conversation.md`. Key decisions: core loop (habits -> sleep -> readiness), "See how last night affects today" positioning, what to cut vs keep for a product.

---

## In Progress

- [ ] **Voice Logger PWA** — Voice-to-log system for nutrition + workouts from phone
  - Code is built (`voice_logger/` directory), not yet deployed
  - **Blocked on user action**: Need Anthropic API key, Nutritionix API key, Vercel account
  - Next: Set up API keys → run `setup_totp.py` → deploy to Vercel → test from phone
  - Plan file: `.claude/plans/flickering-hopping-pizza.md`

---

## Pending

- [ ] **Daily prompt system** — Mobile-friendly form that prompts Daily Log fields at the right times (morning energy after waking, midday focus/mood at lunch, evening rating before bed), with phone notifications so there's no need to manually open the spreadsheet. Highest-leverage item — unlocks adaptive weighting, behavioral correlations, and validation study.

---

## Completed

- [x] Project restructured and cleaned up (2026-03-11)
- [x] Garmin tab: Sleep Score moved to column B (2026-03-11)
- [x] Auto-backfill added to `garmin_sync.py` (2026-03-11)
- [x] Spreadsheet styling: tab-colored headers, alternating row banding (2026-03-12)
- [x] SQLite parallel database + migration script (2026-03-12)
- [x] Dashboard HTML created (2026-03-12)
- [x] Voice Logger code built — `voice_logger/` directory (2026-03-16)
- [x] Analysis scripts: lag correlation + multiple regression (2026-03-16)
- [x] Cognition columns migrated from Sleep to Overall Analysis (2026-03-17)
- [x] Overall Analysis restructured: Day col, Readiness Label next to Score, 12 cols (2026-03-17)
- [x] Design Ruleset codified in CLAUDE.md (2026-03-17)
- [x] Dashboard sleep score thresholds unified (2026-03-17)
- [x] `garmin_sync.py` auto-append to Daily Log (2026-03-17)
- [x] Fix Windows Task Scheduler path (2026-03-17)
- [x] Renamed project from "NS Habit Tracker" to "Health Tracker" (2026-03-17)
- [x] Delete migration scripts (2026-03-17)
- [x] Dashboard-Sheets color grading alignment — all 5 divergent metrics fixed (2026-03-18)
- [x] Removed Garmin Sleep Score from dashboard (2026-03-18)
- [x] Workout activity markers + 3 workout metrics added to dashboard (2026-03-18)
- [x] Mobile Dashboard PWA — 4 versions: mockups -> UI polish -> glassmorphism -> Supabase live data (2026-03-19)
- [x] Methodology reassessment — 10 improvements: sigmoid scoring, evidence-based weights, autocorrelation adjustment, validation loop (2026-03-17)
- [x] SpO2 pipeline + adaptive weighting infrastructure (2026-03-21)
- [x] Methodology gaps #12-17: zone ACWR, calorie balance, macro analysis, post-workout energy, orthosomnia safeguard (2026-03-21)
- [x] `reformat_style.py` audit — SpO2 formats, width overrides, FORCE_CENTER_COLS for all 7 tabs (2026-03-21)
- [x] Executive Brief Word doc — generator script `create_brief_docx.py` (2026-03-18)
