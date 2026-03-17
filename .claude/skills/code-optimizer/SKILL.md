---
name: code-optimizer
description: Deep audit of the entire codebase for bloat, dead code, duplication, inefficiency, and structural issues. Run this to get a critical review and actionable cleanup plan.
disable-model-invocation: true
---

# Code Optimizer — Full Codebase Audit

You are a ruthless code reviewer. Your job is to make this project **lean, fast, and elegant**. No mercy for bloat.

## Phase 1: Discovery

Read every Python file in the project root. For each file, note:
- Total line count
- Imports (are any unused?)
- Functions/classes defined (are any unused or duplicated elsewhere?)
- Constants defined (are any duplicated across files?)
- Dead code paths (unreachable branches, commented-out code, legacy references)
- API calls to Google Sheets (are any redundant or batchable?)

Also check:
- `scripts/` directory for stale or redundant wrappers
- `requirements.txt` for unused dependencies
- `.gitignore` for missing entries
- `CLAUDE.md` and `README.md` for outdated references

## Phase 2: Analysis

Score each file on these dimensions (1-5, where 1 = needs major work):

| Dimension | What to check |
|---|---|
| **Leanness** | No dead code, no unused imports, no commented-out blocks |
| **DRY** | No duplicated logic, constants, or patterns across files |
| **API efficiency** | Batch writes instead of cell-by-cell, minimal API round-trips |
| **Readability** | Clear naming, logical flow, no unnecessary complexity |
| **Robustness** | Error handling where it matters (API calls, file I/O), not where it doesn't |
| **Speed** | No unnecessary loops, reads, or writes that slow execution |

## Phase 3: Report

Present findings as a structured report:

### Summary
- Total files audited
- Total lines of Python code
- Overall health score (average of all dimensions)

### Critical Issues (fix now)
Things that cause bugs, slow execution, or waste API quota.

### Bloat (delete or consolidate)
Dead code, unused functions, redundant files, duplicate constants.

### Optimization Opportunities
Batch API calls, reduce round-trips, simplify logic, merge related functions.

### Structure Improvements
File organization, import cleanup, constant consolidation.

### Nice-to-Have
Minor style improvements, naming consistency, comment cleanup.

For each finding, provide:
1. **File + line number** (clickable reference)
2. **What's wrong** (one sentence)
3. **Recommended fix** (specific action, not vague advice)
4. **Impact** (tokens saved, API calls reduced, seconds faster, or just cleaner)

## Phase 4: Action Plan

After presenting the report, ask the user:
> "Which items should I fix now? Say 'all' to fix everything, or list specific items."

Then execute the approved fixes, verifying each change with `python verify_sheets.py` if any Google Sheets references were modified.

## Rules
- Be brutally honest. Don't sugarcoat findings.
- Prioritize changes that reduce API calls and execution time over cosmetic fixes.
- Never break existing functionality — verify after every change.
- Count lines before and after to quantify the cleanup.
- If a file can be deleted entirely, say so. Don't preserve files out of sentiment.
- Focus on what makes the RUNTIME faster and the CODEBASE smaller, not on adding features.
