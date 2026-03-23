"""
Frontend HTML Sink Scanner — prevents innerHTML XSS regressions.

Scans all JS files under app_mockups/ for .innerHTML and .insertAdjacentHTML
assignments. Every usage must be in the ALLOWLIST with file:line granularity.

New innerHTML usage triggers a test failure, forcing explicit review.
To approve a new usage: verify it's safe, then add file:line to ALLOWLIST.
"""

import os
import re

try:
    import pytest
except ImportError:
    pytest = None

PWA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app_mockups")

# Pattern matches: .innerHTML = or .insertAdjacentHTML( or .outerHTML =
SINK_PATTERN = re.compile(
    r"\.(innerHTML\s*=|insertAdjacentHTML\s*\(|outerHTML\s*=)"
)

# Each entry: "relative/path.js:line_number"
# Reviewed and approved usages. Line numbers are approximate —
# the test allows ±5 lines of drift from refactoring.
ALLOWLIST = {
    # --- dom.js (safe helpers themselves) ---
    "js/dom.js:45",   # _html attr in h() — trusted markup by design
    "js/dom.js:99",   # setTrustedHTML() — wrapper for trusted markup

    # --- auth.js (static modal templates, no data interpolation) ---
    "auth.js:50",     # login modal HTML
    "auth.js:111",    # connection error modal HTML

    # --- data-loader.js (static setup error, no data interpolation) ---
    "data-loader.js:28",  # "Setup Required" fallback

    # --- debug.html (dev-only page, uses textContent now) ---
    "debug.html:57",  # clearing results div

    # --- log-entry.js ---
    "js/log-entry.js:84",   # habit toggles (SVG icons from predefined array)

    # --- today.js ---
    "js/today.js:102",   # habit circle toggle (predefined icon/checkmark)
    "js/today.js:263",   # readiness gauge SVG (computed numeric values)
    "js/today.js:296",   # expect effects (escapeHtml on all text)
    "js/today.js:299",   # flags list (escapeHtml on all text)
    "js/today.js:304",   # do items list (escapeHtml on all text)
    "js/today.js:340",   # sleep stages bar (computed percentages, CSS vars)
    "js/today.js:359",   # sleep stages detail (computed values, predefined labels)
    "js/today.js:390",   # sleep context stats (escapeHtml on label and value)
    "js/today.js:406",   # body battery gauge SVG (computed numeric values)
    "js/today.js:445",   # habits row (predefined icons/labels, computed state)
    "js/today.js:471",   # activity sessions (escapeHtml on activity_name)
    "js/today.js:511",   # insights list (escapeHtml on all text)
    "js/today.js:518",   # recommendations section (escapeHtml on all text)
    "js/today.js:525",   # recommendations clear (empty string)
    "js/today.js:551",   # insertAdjacentHTML — preliminary badge (static markup)

    # --- activity.js ---
    "js/activity.js:40",    # session detail overlay (escapeHtml on activity_name)
    "js/activity.js:113",   # insertAdjacentHTML strength set (escapeHtml on all fields)
    "js/activity.js:140",   # "No sessions today" (static string)
    "js/activity.js:180",   # today session render (escapeHtml on name/notes, numeric stats)
    "js/activity.js:253",   # week sessions list (computed dates/numbers, getActivityIcon)
    "js/activity.js:283",   # strength list (escapeHtml on exercise/muscle_group)

    # --- calendar.js ---
    "js/calendar.js:75",    # metric pills (predefined labels)
    "js/calendar.js:160",   # calendar grid (computed colors/dates, no user strings)
    "js/calendar.js:214",   # detail content (predefined labels, computed values)

    # --- sleep-detail.js ---
    "js/sleep-detail.js:32",    # sleep score gauge SVG
    "js/sleep-detail.js:80",    # timeline bar (computed stage segments)
    "js/sleep-detail.js:95",    # stage rows (predefined labels)
    "js/sleep-detail.js:119",   # vitals grid (computed values, predefined labels)
    "js/sleep-detail.js:181",   # trend chart SVG
    "js/sleep-detail.js:184",   # trend labels (computed dates)

    # --- trends.js ---
    "js/trends.js:116",   # metric pills (predefined labels)
    "js/trends.js:131",   # "No data" SVG text (static)
    "js/trends.js:132",   # clear x-axis labels (empty string)
    "js/trends.js:198",   # trend chart SVG
    "js/trends.js:202",   # chart x-axis labels (computed dates)
    "js/trends.js:298",   # weekday row (predefined day names)
    "js/trends.js:335",   # calendar grid (computed colors/dates)

    # --- index.js (combined SPA — duplicates patterns from page-specific files) ---
    "js/index.js:281",    # session detail overlay (escapeHtml on activity_name)
    "js/index.js:352",    # insertAdjacentHTML strength set (escapeHtml on all fields)
    "js/index.js:444",    # habit toggles (SVG icons from predefined array)
    "js/index.js:483",    # render error display (escapeHtml on name/message/stack)
    "js/index.js:541",    # readiness gauge SVG
    "js/index.js:578",    # expect effects (escapeHtml)
    "js/index.js:585",    # flags list (escapeHtml)
    "js/index.js:592",    # do items list (escapeHtml)
    "js/index.js:630",    # sleep stages bar
    "js/index.js:650",    # sleep stages detail
    "js/index.js:689",    # sleep context stats (escapeHtml)
    "js/index.js:708",    # body battery gauge SVG
    "js/index.js:754",    # habits row
    "js/index.js:780",    # activity sessions (escapeHtml)
    "js/index.js:821",    # insights list (escapeHtml)
    "js/index.js:828",    # recommendations section (escapeHtml)
    "js/index.js:879",    # metric pills (predefined)
    "js/index.js:951",    # trend chart SVG
    "js/index.js:955",    # chart x-axis labels
    "js/index.js:1051",   # weekday row
    "js/index.js:1088",   # calendar grid
    "js/index.js:1140",   # "No sessions today" (static)
    "js/index.js:1180",   # today session render (escapeHtml)
    "js/index.js:1253",   # week sessions list
    "js/index.js:1283",   # strength list (escapeHtml)
    "js/index.js:1382",   # sleep score gauge SVG
    "js/index.js:1430",   # sleep timeline bar
    "js/index.js:1445",   # sleep stage rows
    "js/index.js:1469",   # vitals grid
    "js/index.js:1531",   # sleep trend SVG
    "js/index.js:1534",   # sleep trend labels
    "js/index.js:1574",   # calendar metric pills
    "js/index.js:1670",   # calendar grid
    "js/index.js:1767",   # detail content
}

# How many lines of drift to tolerate before flagging
LINE_DRIFT = 5


def _scan_sinks():
    """Scan all JS/HTML files and return list of (rel_path, line_no, line_text)."""
    sinks = []
    for root, _, files in os.walk(PWA_DIR):
        for fname in sorted(files):
            if not fname.endswith(('.js', '.html')):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, PWA_DIR).replace("\\", "/")
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f, 1):
                    if SINK_PATTERN.search(line):
                        sinks.append((rel, i, line.strip()))
    return sinks


def _is_allowlisted(rel_path, line_no):
    """Check if a sink is in the allowlist (with ±LINE_DRIFT tolerance)."""
    for entry in ALLOWLIST:
        parts = entry.rsplit(":", 1)
        allowed_path = parts[0]
        allowed_line = int(parts[1])
        if rel_path == allowed_path and abs(line_no - allowed_line) <= LINE_DRIFT:
            return True
    return False


def test_no_new_html_sinks():
    """Every .innerHTML/.insertAdjacentHTML/.outerHTML must be in the allowlist."""
    sinks = _scan_sinks()
    violations = []
    for rel_path, line_no, line_text in sinks:
        if not _is_allowlisted(rel_path, line_no):
            violations.append(f"  {rel_path}:{line_no}  {line_text}")

    if violations:
        msg = (
            f"\n\nFound {len(violations)} innerHTML/insertAdjacentHTML usage(s) "
            f"not in the allowlist.\n"
            f"Review each for XSS safety, then add to ALLOWLIST in "
            f"tests/test_frontend_html_sinks.py:\n\n"
            + "\n".join(violations)
        )
        pytest.fail(msg)


def test_allowlist_entries_still_exist():
    """Verify allowlist entries haven't become stale (file deleted or line drifted too far)."""
    sinks = _scan_sinks()
    sink_set = {(rel, ln) for rel, ln, _ in sinks}

    stale = []
    for entry in sorted(ALLOWLIST):
        parts = entry.rsplit(":", 1)
        allowed_path = parts[0]
        allowed_line = int(parts[1])

        # Check if the file exists
        fpath = os.path.join(PWA_DIR, allowed_path)
        if not os.path.exists(fpath):
            stale.append(f"  {entry}  (file not found)")
            continue

        # Check if any sink is near this allowlist line
        found = any(
            rel == allowed_path and abs(ln - allowed_line) <= LINE_DRIFT
            for rel, ln in sink_set
        )
        if not found:
            stale.append(f"  {entry}  (no innerHTML found near this line)")

    if stale:
        msg = (
            f"\n\n{len(stale)} allowlist entries are stale (no matching "
            f"innerHTML found). Remove them:\n\n"
            + "\n".join(stale)
        )
        pytest.fail(msg)


if __name__ == "__main__":
    print("Scanning for HTML sinks in", PWA_DIR)
    sinks = _scan_sinks()
    print(f"Found {len(sinks)} innerHTML/insertAdjacentHTML usages\n")

    violations = []
    for rel_path, line_no, line_text in sinks:
        status = "ALLOWED" if _is_allowlisted(rel_path, line_no) else "NEW"
        marker = "  " if status == "ALLOWED" else ">>"
        print(f"  {marker} {rel_path}:{line_no}  [{status}]  {line_text[:80]}")
        if status == "NEW":
            violations.append((rel_path, line_no, line_text))

    print(f"\n{'PASS' if not violations else 'FAIL'}: "
          f"{len(sinks)} total, {len(violations)} not in allowlist")
