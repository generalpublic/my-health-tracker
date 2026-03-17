---
name: code-optimizer
description: Run a comprehensive codebase optimization audit — dead code, duplication, performance, file structure, security
tools:
  - Read
  - Glob
  - Grep
  - Agent
---

# Code Optimizer

Read-only codebase audit. Launch 3 Explore agents in parallel, compile findings.

## 1 — Agent Dispatch

| ID | Rule | Context | File |
|----|------|---------|------|
| 1a | Launch 3 Explore agents in parallel (one per section 2/3/4) | on skill invocation | all .py files |
| 1b | Each agent returns findings as a table, not prose | agent prompt format | — |
| 1c | Do NOT make any edits — read-only analysis only | entire skill | — |

## 2 — Dead Code & Duplication (Agent 1)

| ID | Rule | Context | File |
|----|------|---------|------|
| 2a | Find functions defined but never called | grep `def fn_name`, then grep `fn_name(` — def-only = dead | *.py |
| 2b | Find duplicate function names across files | same `def` name in 2+ .py files | *.py |
| 2c | Find unused imports | import at top not referenced in file body | *.py |
| 2d | Find commented-out code blocks | 3+ consecutive `#` lines that look like code, not docs | *.py |
| 2e | Report as table: File, Item, Type, Lines, Action | agent output format | — |

## 3 — Performance & Efficiency (Agent 2)

| ID | Rule | Context | File |
|----|------|---------|------|
| 3a | Find HTTP requests missing `timeout=` | `requests.get(` or `requests.post(` without timeout | *.py |
| 3b | Find API calls inside loops without rate limiting | loops containing `requests.*` or `client.messages.create` with no `sleep` | *.py |
| 3c | Find large strings concatenated into every API call | same context/prompt appended to each message instead of using `system=` | *.py |
| 3d | Find cache dirs with no cleanup mechanism | dirs that `.mkdir()` but never prune old files | *.py |
| 3e | Find duplicate data processing | same data sorted/filtered/mapped in 2+ places | *.py |
| 3f | Find functions longer than 100 lines | candidate for extraction | *.py |
| 3g | Report as table: File:Line, Issue, Impact, Fix | agent output format | — |

## 4 — Structure & Security (Agent 3)

| ID | Rule | Context | File |
|----|------|---------|------|
| 4a | Find one-time scripts that already ran | setup/migration/generator scripts with no recurring use | *.py |
| 4b | Check .gitignore covers all secret files | config.json, *.env, service_account.json, credentials | .gitignore |
| 4c | Find empty directories or placeholder files | dirs with no meaningful content | project root |
| 4d | Find orphaned data files not referenced by any code | .json/.csv/.txt files no .py imports or opens | project root |
| 4e | Check for import cycles or fragile chains | circular imports, imports that break if file order changes | *.py |
| 4f | Report as table: Item, Issue, Recommendation | agent output format | — |

## 5 — Compile Report

| ID | Rule | Context | File |
|----|------|---------|------|
| 5a | Group all findings by severity: Critical > High > Medium > Low | after all 3 agents return | — |
| 5b | Critical = security issues, exposed secrets | severity classification | — |
| 5c | High = dead code, duplication, performance bottlenecks | severity classification | — |
| 5d | Medium = structural cleanup, unused files | severity classification | — |
| 5e | Low = style issues, minor improvements | severity classification | — |
| 5f | End with summary table: Python files, total lines, duplicated fns, dead fns, missing timeouts, security issues | final output | — |

Notes:
- 4b: Do NOT read config.json or any secrets file — only verify .gitignore covers them
- 5f: If codebase is clean, say so — do not invent issues to fill the report
