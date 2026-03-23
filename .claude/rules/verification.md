# Verification Rules (Non-Negotiable)

Verification is mandatory after every change. Never declare done without passing all checks.

---

## Spreadsheet Edit Rules

After **every** write, update, or structural change to any Google Sheets tab:
1. Run `python verify_sheets.py` (or `python verify_sheets.py --tab <TabName>` for a single tab)
2. All tabs must report PASS before the task is considered complete
3. If any tab reports FAIL or WARNING — stop, diagnose, and fix before telling the user the task is done

---

## Formatting Verification

After **every** script that applies or could affect conditional formatting:
1. Run `python verify_formatting.py` (or call `verify_and_repair(wb)` in code)
2. All tabs must report PASS for conditional formatting rules AND numeric data types
3. If any tab reports FAIL — auto-repair fixes numeric types AND re-applies rules, then re-verifies
4. After auto-repair, if still FAIL — stop and investigate manually

### What It Checks (Two Layers)
1. **Rules exist** — all expected conditional format rules are present on the correct columns with correct thresholds
2. **Data types are numeric** — spot-checks graded columns to verify values are actual numbers, not text strings. Gradient formatting silently ignores text cells even if the text looks like "82". This is the #1 cause of "rules exist but colors don't show."

### What Auto-Repair Does
1. Converts all text-as-number cells to actual numbers (batch write with USER_ENTERED)
2. Re-applies conditional format rules for the failing tab

### Already Integrated (Runs Automatically)
- `garmin_sync.py` — calls `verify_and_repair(wb)` at end of main(); also calls `fix_sleep_numeric_types()` before color grading
- `reformat_style.py` — calls `verify_and_repair(wb)` at end of main()
- `overall_analysis.py` — calls `verify_tab_formatting` + repair after weekly banding
- `setup_overall_analysis.py` — calls `verify_tab_formatting` in verify()

### When Adding New Color-Graded Columns
1. Add the grading logic in the relevant setup/apply function
2. Add the column to `EXPECTED_RULES` in `verify_formatting.py`
3. Ensure the write function stores values as numbers (not RAW text)
4. Run `python verify_formatting.py --repair` to confirm it passes
5. Never skip this step, even for "small" changes — misalignment compounds silently

---

## Self-Verification Rules

After every action, verify the outcome matches what was claimed:

### For Script Changes
- Run the script and confirm the output matches the expected result
- Do not tell the user something is done until the output proves it

### For Google Sheets Changes
- Query the sheet directly to confirm headers, data, or structure match what was described
- Never assume a write succeeded — verify by reading back the result

### For File Edits
- After editing, confirm the specific change is present in the file
- Never tell the user a file was updated without verifying the change took effect

### General Rule
- If what I said I did does not match what actually happened, flag it immediately and fix it before moving on
- Do not rely on the user to catch my mistakes — catch them myself first

---

## Post-Change Verification (Mandatory After Structural Changes)

After any structural change — renames, file/folder restructuring, schema migrations, column reordering, major refactors, dependency changes, or any change that touches multiple files for the same logical operation — the plan MUST include a full verification cycle as the final step. Do not wait for the user to ask for this.

### Structural Changes That Trigger Mandatory Verification
- Project or file renames (names, paths, references)
- Database schema changes (columns added/removed/reordered)
- Google Sheets tab structure changes (headers, column order)
- File or folder moves/reorganization
- Configuration key renames
- Dependency upgrades that change APIs
- Any multi-file find-and-replace operation

### The Verification Cycle (6 Steps)
1. **Import/load check** — `python -c "import garmin_sync; import sqlite_backup"` — all modules load without errors
2. **Reference sweep** — grep the entire codebase for stale references to old names/paths/values (zero results required)
3. **Sheets verification** — `python verify_sheets.py` — all tabs must report PASS
4. **Functional test** — `python garmin_sync.py --today` — full pipeline runs end-to-end (Garmin API -> Sheets -> SQLite -> Overall Analysis -> Dashboard)
5. **Automated systems check** — `python garmin_sync.py --sleep-notify` — notification pipeline works, user confirms receipt on phone
6. **Scheduler check** — confirm Task Scheduler tasks exist, point to correct paths, and use **full python path** (never bare `python`). After registering tasks, trigger `schtasks /run /tn "Health Tracker - Garmin Sync"` and verify `garmin_sync.log` shows a successful run. "Ready" status alone is not proof of working — a task can show Ready but fail on every execution.

### Rules
- Never declare a structural change "done" without completing the verification cycle
- If verification reveals additional issues, fix them and re-run the cycle
- Include verification as an explicit step in every plan that involves structural changes
- The cost of verifying is always lower than the cost of silent breakage discovered later
