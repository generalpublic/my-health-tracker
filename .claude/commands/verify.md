Run the full verification suite for the Health Tracker spreadsheet:

1. Run `python verify_sheets.py` and report results for all tabs
2. Run `python verify_formatting.py` and report results for all tabs
3. If any tab reports FAIL, attempt auto-repair with `python verify_formatting.py --repair`
4. Re-run verification after any repair
5. Report final PASS/FAIL status for all tabs

Do not stop until all tabs pass or you've identified an issue that requires manual investigation.
