---
name: update-profile
description: Process personal health documentation — lab results, diagnoses, provider notes, medical imaging — into a structured health profile. Ingest new documents, add conditions/medications manually, or view profile status. Invoke with /update-profile followed by a mode or no args to scan for new documents.
---

# Health Profile Update — Personal Medical Data Ingestion

You manage the user's personal health profile. Your job is to process medical documents (lab results, imaging, clinical notes, test results, prescriptions) into a structured `profile.json` that the analysis pipeline uses for personalized insights.

**CRITICAL: This skill handles Protected Health Information (PHI). All output goes ONLY to the gitignored `profiles/` directory. Never write PHI to any committed file.**

---

## PHI Security Rules (Non-Negotiable)

1. **All writes go to `profiles/` ONLY** — never to `reference/`, `CLAUDE.md`, memory files, or any committed file
2. **Work logs use generic descriptions** — "Updated profile with lab results" not "Added lead 2.1 ug/dL"
3. **Terminal output shows counts only** — "3 biomarkers added" not biomarker names or values
4. **Never confuse with `/update-intel`** — this skill processes PERSONAL medical data; `/update-intel` processes RESEARCH material
5. **If the user provides a file from `reference/transcripts/` or `reference/books/`**, reject it: "This looks like research material. Use `/update-intel` instead."

---

## Profile Location

The active profile directory is determined by:
1. `HEALTH_PROFILE_DIR` in `.env` (relative to project root)
2. Single subdirectory under `profiles/`
3. Explicit path provided by user

Profile structure:
```
profiles/<profile_id>/
  profile.json          # master structured profile
  profile_summary.md    # token-efficient summary (<200 lines)
  ingested_docs.md      # manifest of processed documents
  documents/            # raw source documents
  extractions/          # structured extractions per document
  changelog.json        # append-only change log
```

---

## Modes

### `/update-profile` (no args) — Scan for unprocessed documents

1. Read `profiles/<active>/ingested_docs.md` (create if missing)
2. List all files in `profiles/<active>/documents/`
3. Compare lists — identify unprocessed files
4. Present unprocessed files grouped by likely type (lab results, imaging, clinical notes, etc.)
5. Ask which to process, or offer "all" to process sequentially

### `/update-profile add-condition <name>` — Manually add a condition

1. Ask the user for: severity (1-10), category (neurological/metabolic/hormonal/musculoskeletal/autoimmune/other), and any notes
2. Generate a condition entry with appropriate accommodations based on the condition type
3. Suggest tracking_relevance fields based on the condition's known effects
4. Add to `profile.json` conditions array
5. Run Phase 6 (reprioritize)

### `/update-profile add-labs` — Process lab results

1. User provides file path (image/PDF) or types values directly
2. If file: read with multimodal capabilities, extract all values
3. For each biomarker: name, value, unit, reference range, flag (normal/elevated/low)
4. Map category (heavy_metals, glucose, lipid_panel, etc.)
5. Check for existing biomarkers — if same test exists with older date, update trending
6. Add to `profile.json` biomarkers array
7. Write raw extraction to `extractions/` with timestamped filename
8. Run Phase 6 (reprioritize)

### `/update-profile add-note` — Add provider notes

1. User provides typed summary or file path
2. Extract: date, provider specialty, summary, action items
3. Add to `profile.json` provider_notes array
4. If action items reference new conditions or biomarkers, offer to add those too

### `/update-profile add-med <name>` — Add medication or supplement

1. Ask: type (medication/supplement), dose, frequency, purpose, start_date
2. Determine tracking_relevance based on the medication's known effects
3. Add to medications or supplements array in `profile.json`
4. Note: supplements are NOT considered PHI for notification purposes

### `/update-profile status` — Show profile summary

1. Load profile via `profile_loader.load_profile()`
2. Display:
   - Active conditions (count + categories, no names in logs)
   - Biomarker count + staleness warnings
   - Current health priorities (ranked by priority_score)
   - Supplements and medications count
   - Last updated date
3. Run `check_biomarker_staleness()` and display any retest recommendations

---

## Phase 0: Scan for Unprocessed Documents

1. Read `profiles/<active>/ingested_docs.md` — get already-processed files
2. List all files in `profiles/<active>/documents/`
3. Identify unprocessed files (not in manifest)
4. If invoked without args, present the list and ask which to process
5. If user specified a file, proceed to Phase 1

---

## Phase 1: Ingest Document

Accept the source in one of these forms:

1. **File path** — Read the file (image for lab screenshots, PDF for reports)
2. **Typed description** — User describes a diagnosis, test result, or provider note verbally
3. **"I was diagnosed with X"** — Shortcut to add-condition mode

**Guard:** If the file path contains `reference/transcripts/` or `reference/books/`, reject:
> "This looks like research material, not personal medical data. Use `/update-intel` instead."

---

## Phase 2: Classify Document Type

Determine the document type:

| Type | Examples | Profile Sections Affected |
|------|----------|--------------------------|
| `lab_results` | Blood work, urine tests, metabolic panels | biomarkers[] |
| `imaging` | Brain scans, DEXA, X-rays | conditions[], provider_notes[] |
| `clinical_notes` | Doctor visit summaries, discharge notes | provider_notes[], conditions[] |
| `test_results` | VCS, OAT, mycotoxin panels, genetic tests | biomarkers[], conditions[] |
| `prescription` | Medication orders | medications[] |
| `provider_summary` | Treatment plans, healing roadmaps | provider_notes[], health_priorities[] |

Present classification to user before proceeding.

---

## Phase 3: Extract Structured Data

### For lab results (biomarkers):
```json
{
  "id": "bio_NNN",
  "name": "Lead (Blood)",
  "category": "heavy_metals",
  "value": 2.1,
  "unit": "ug/dL",
  "reference_range": {"low": 0, "high": 5.0},
  "status": "normal",
  "test_date": "2025-05-22",
  "lab": "Quest Diagnostics",
  "source_doc": "05222025 - lead blood.png",
  "tracking_relevance": ["cognition", "hrv", "recovery"]
}
```

### For conditions:
```json
{
  "id": "cond_NNN",
  "name": "Condition Name",
  "category": "neurological",
  "status": "active",
  "severity": "moderate",
  "description": "...",
  "tracking_relevance": ["cognition", "sleep", "..."],
  "accommodations": {
    "output_format": {},
    "analysis_adjustments": {}
  },
  "contraindications": [],
  "source_doc": "filename.pdf"
}
```

### Rules:
- **Never overwrite existing entries** — append new, update existing (match by `id`)
- **Flag conflicts** — same biomarker with different values at different dates → update trending: "Lead: 3.2 (2025-01) → 2.1 (2025-05) — TRENDING DOWN"
- **Auto-compute tracking_relevance** — map biomarker categories to tracked Garmin/Sheets metrics
- **Assign next available ID** — scan existing entries, increment

### Tracking relevance mapping:
| Biomarker Category | Relevant Metrics |
|-------------------|-----------------|
| heavy_metals | cognition, hrv, recovery, deep_sleep |
| glucose/hba1c | energy, cognition, sleep |
| lipid_panel | recovery, energy |
| thyroid | energy, metabolism, sleep |
| liver_function | recovery, detox |
| inflammatory | recovery, hrv, sleep |
| vitamins | cognition, energy |
| hormones | energy, recovery, training |
| cbc | energy, recovery |
| brain_imaging | cognition, executive_function |
| mycotoxin | cognition, hrv, recovery, detox |
| vcs | cognition, neurological |

---

## Phase 4: Regenerate Profile Summary

After any profile change, regenerate `profile_summary.md` — a token-efficient reference file (<200 lines) for use by `/health-insight` and cross-project access.

**Structure (reference/structural only, NOT a narrative):**

```markdown
# Health Profile Summary — [profile_id]
Last updated: YYYY-MM-DD

## Active Conditions
- [count] active conditions across [categories]
- Accommodation rules: [list active output_format + analysis_adjustment keys]

## Biomarker Status
- [count] total, [count] current, [count] stale
- Categories tested: [list]
- Staleness alerts: [list any past threshold]

## Health Priorities (ranked)
1. [concern] — score [X.X] (severity/recency/data)
2. ...

## Supplements & Medications
- [count] supplements, [count] medications

## Lifestyle Targets
- Sleep: [target]h, bedtime [time], wake [time]
- Key routines: [morning/evening summary]

## Threshold Overrides
- [list any active overrides, or "None — using population defaults"]

## Key Tracking Relevance
- Metrics with profile context: [list all unique tracking_relevance values]
```

**This file contains NO raw biomarker values, condition names, or medication names — only counts, categories, and scores.**

---

## Phase 5: Update Manifest

Log the processed document in `profiles/<active>/ingested_docs.md`:

```markdown
| File | Date Processed | Type | Items Extracted | MD5 |
|------|---------------|------|-----------------|-----|
| 05222025 - lead blood.png | 2026-03-17 | lab_results | 1 biomarker | abc123... |
```

Compute MD5: `md5sum "profiles/<active>/documents/filename"`

---

## Phase 6: Reprioritize

After any profile change:

1. Recalculate `priority_score` for all health priorities:
   `priority_score = severity * 0.4 + recency * 0.3 + data_availability * 0.3`

2. Check if priority order changed — if so, flag it:
   > "Priority order changed: 'Stress regulation' moved from #2 to #1 (recency increased after new HRV data)"

3. Run `check_biomarker_staleness()` — flag any biomarkers past threshold:
   > "Lead levels last tested 10 months ago (threshold: 6 months). Consider retesting."

4. If new biomarkers were added, check if they should create or modify health_priorities entries

---

## Rules

- **All output to gitignored `profiles/` directory ONLY** — this is the #1 rule
- **Guard against research material** — reject files from `reference/` directories
- **Append, never overwrite** — existing data is preserved; new data extends the profile
- **Auto-classify tracking_relevance** — map biomarker categories to tracked metrics
- **Regenerate summary after every change** — keep `profile_summary.md` current
- **Flag staleness** — biomarkers past their threshold get explicit warnings
- **Profile is the user's truth** — if they say "I have ADHD", add it. Don't require documentation.
- **Work logs stay generic** — "Processed 3 lab result images" not "Added lead, mercury, zinc results"
