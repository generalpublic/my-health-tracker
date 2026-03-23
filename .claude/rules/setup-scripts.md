# Setup Script Rules (Non-Negotiable)

All setup scripts (setup_analysis.py, setup_charts.py, etc.) must be **idempotent** — running them multiple times must always produce the correct end state regardless of current state.

---

## Never Write "Skip If Exists" Logic for Tabs or Headers
- If a tab exists -> update its headers in place, do not skip
- If a header row exists -> overwrite it with the full correct header list
- If a tab doesn't exist -> create it with the correct headers

## Before Writing Any Setup or Migration Code
1. State explicitly what the current state of the system is (which tabs exist, what headers they have)
2. Confirm the code handles both the "first run" case AND the "already exists" case
3. Never assume a tab is new — always write update logic for existing tabs

## When Adding New Columns to an Existing Tab
- The setup function must update the full header row in place, not skip because the tab exists
- Data rows are never touched — only the header row (row 1) is updated

## Every Setup Script Must Include a verify_setup() Function
- Runs automatically at the end of main()
- Independently reads back each tab's actual headers from the sheet
- Compares them to the expected headers and prints PASS or FAIL for each tab
- If any tab fails, the script must report exactly what is missing or wrong
- The script is not considered complete until all tabs print PASS
