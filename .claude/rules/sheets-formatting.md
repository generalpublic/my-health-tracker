# Spreadsheet Formatting & Design Rules (Non-Negotiable)

These rules govern all Google Sheets visual formatting for the Health Tracker project. Every cell in every tab must be fully readable without manual resizing. This is not cosmetic — it is a functional requirement and the #1 priority for any spreadsheet work.

---

## Column Widths
- Set explicit widths for EVERY column when creating or modifying any tab
- Short numbers/scores: 60-80px | Labels: 80-120px | Dates: 100px
- Short text (names, meals): 200px min | Notes/sentences: 250-350px | Long analysis: 350-500px
- Add to `WIDTH_OVERRIDES` in `reformat_style.py` when auto-sizing is insufficient

## Row Heights
- Any tab with free-text or wrapped columns MUST use `autoResizeDimensions` on data rows
- Add the tab to the auto-resize list in `reformat_style.py` (currently: Sleep, Nutrition)
- Fixed 24px height is ONLY acceptable for purely numeric/short-label tabs

## Alignment (Three-Tier Rule)
- **Short labels/categorical** (Day, Date, single-word values like "Good"/"High"/"Optimal"): CENTER — these are lookup values, not prose
- **Long-form text** (Notes, Analysis, Descriptions, Assessments, Recommendations): LEFT + TOP + WRAP — prose needs left alignment to read naturally
- **Numeric/scores**: CENTER
- **Checkboxes** (Daily Log D-J): CENTER — boolean toggles must be visually centered in their cells
- Always set explicitly — never rely on Sheets defaults
- Enforce via `FORCE_CENTER_COLS` in `reformat_style.py` for any text column that should stay centered despite auto-detection

## Process
1. When creating a new tab: set column widths in the setup script for every column
2. When adding columns: add width overrides if auto-sizing won't fit the content
3. When running reformat: verify the tab is in the auto-resize list if it has text columns
4. After any structural change: verify all content is readable at the set widths
5. The user must NEVER have to ask for resizing — anticipate it

---

## Tab Order (Non-Negotiable)
Tabs must always appear in this exact order. Enforce after any tab creation or restore operation.

1. **Daily Log** — primary daily input
2. **Overall Analysis** — daily readiness assessment
3. **Sleep** — sleep metrics and notes
4. **Garmin** — raw Garmin wellness data
5. **Nutrition** — meal tracking and macros
6. **Session Log** — workout sessions
7. **Strength Log** — weight training sets
8. **Analysis** — aggregate formulas and correlations
9. **Charts** — embedded trend charts (HRV, sleep, body battery, etc.)
10. **Raw Data Archive** — full Garmin export mirror
11. **Key** — color legend and reference (always last)

---

## Cell Background Color Hierarchy (in priority order)
1. **Color-graded cells** — cells with conditional formatting gradients or discrete color rules (e.g., Readiness Score red-green, Readiness Label Optimal=green/Poor=red, Sleep Analysis Score, Bedtime bands). These take highest priority — no other background color overrides them.
2. **Yellow manual-entry cells** — any column where the user types data manually gets light yellow background `{"red": 1.0, "green": 1.0, "blue": 0.8}`. This includes: Notes, Cognition (1-10), Cognition Notes, Perceived Effort, Post-Workout Energy, all Nutrition meal columns, all Daily Log subjective columns. When columns move between tabs, the yellow follows them.
3. **Weekly row banding** — all remaining cells (not color-graded, not yellow) alternate between white and light grey on a weekly basis (Sunday–Saturday). One week is white, the next is light grey `{"red": 0.95, "green": 0.95, "blue": 0.95}`. This groups data visually by week.
4. **Header row** — tab-colored background with bold text. Never overridden by banding. Text color per tab: **Daily Log** and **Overall Analysis** use WHITE text (dark backgrounds). All other tabs use BLACK text (light backgrounds). Any function that touches header formatting (e.g., `bold_headers()`) must NOT reset the foreground color — use narrow field masks (`textFormat.bold,textFormat.fontSize`) instead of broad `textFormat`.

## Weekly Banding Rules
- Weeks run Sunday–Saturday (ISO week starting Sunday)
- The most recent week is white, the previous week is grey, alternating backwards
- Banding applies to ALL data cells that don't have a higher-priority color (color grade or yellow)
- Banding is applied/refreshed whenever data is written or structural changes are made
- Implementation: calculate week number from date column, apply alternating colors

---

## Design Audit Checklist (run after EVERY structural change)
After any column add/remove/move, tab creation, or row builder change:
1. **Yellow check**: every manual-entry column has yellow background applied
2. **Gradient check**: every numeric score/metric column has appropriate color grading
3. **Banding check**: weekly alternating white/grey is applied to non-graded, non-yellow cells
4. **No yellow on auto columns**: auto-populated columns must NOT have yellow background
5. **Column width check**: all columns have explicit widths set
6. **Wrap check**: text-heavy columns have WRAP enabled
7. **Alignment check**: short labels/categorical=CENTER, long text=LEFT+TOP+WRAP, numeric=CENTER

---

## Current Color-Graded Columns (update when adding new ones)
- **Sleep tab**: Sleep Analysis Score, Total Sleep, Time in Bed, Deep/Light/REM/Awake min, Deep%/REM%, Sleep Cycles, Awakenings, Avg HR, Avg Respiration, Overnight HRV, Body Battery Gained, Bedtime (discrete bands)
- **Overall Analysis tab**: Readiness Score (C, gradient 1-10), Readiness Label (D, discrete Optimal/Good/Fair/Low/Poor), Confidence (E, discrete High/Medium-High/Medium/Low), Cognition (H, gradient 1-10)
- **Session Log**: (none currently — add if needed)

## Current Manual-Entry (Yellow) Columns
- **Sleep**: G (Notes)
- **Overall Analysis**: H (Cognition 1-10), I (Cognition Notes)
- **Nutrition**: F-N (meal columns), P (Notes)
- **Session Log**: D (Perceived Effort), E (Post-Workout Energy), F (Notes)
- **Daily Log**: C-V (all subjective columns)
