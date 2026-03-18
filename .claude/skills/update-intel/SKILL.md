---
name: update-intel
description: Process new health reference material — detect new files, auto-classify by domain, compile into Research Universe docs, and optionally evaluate specific claims. Invoke with /update-intel followed by source material or no args to scan for new files.
---

# Health Intelligence Update — Research Library & Claim Evaluation

You manage the user's health research library. Your primary job is to compile new source material (transcripts, articles, journals, podcasts) into domain-specific Research Universe documents. Your secondary job (on request) is to evaluate specific claims against evidence and map them to codebase thresholds.

---

## Domains & Research Universe Files

| Domain | Scope | Universe File |
|---|---|---|
| Sleep | Architecture, stages, circadian rhythm, sleep hygiene, chronotype | `reference/Sleep Research Universe.md` |
| Nutrition | Meal timing, macros, micronutrients, gut health, supplements | `reference/Nutrition Research Universe.md` |
| Training | Exercise programming, load management, periodization, mobility | `reference/Training Research Universe.md` |
| Recovery | HRV, ANS regulation, body battery, deload, rest protocols | `reference/Recovery Research Universe.md` |
| Cardio | VO2max, zone training, endurance, cardiac adaptation | `reference/Cardio Research Universe.md` |
| Neurological | Cognition, focus, memory, executive function, brain health | `reference/Neurological Research Universe.md` |
| Metabolic | Hormones, glucose/blood sugar, body composition, thyroid, cortisol | `reference/Metabolic Research Universe.md` |
| Psychology | Stress management, behavioral patterns, habits, motivation | `reference/Psychology Research Universe.md` |

A single source can span multiple domains. If it does, classify it under its **primary** domain and add cross-reference notes in secondary domain files.

---

## Phase 0: Scan for Unprocessed Files

Before processing any specific source, scan the `reference/` folder against the ingestion manifest:

1. Read `reference/INGESTED.md` to get the list of already-processed files.
2. List all files in `reference/`, `reference/books/`, `reference/transcripts/`, and any other subdirectories.
3. Compare the two lists. Any file that is:
   - Not in the "Ingested Files" table, AND
   - Not in the "Excluded Files" table
   -> is **unprocessed**.
4. If the user invoked `/update-intel` without specifying a source, present the unprocessed file list grouped by likely domain and ask which to process.
5. If the user specified a source, proceed to Phase 1 — but still mention how many other unprocessed files remain.

To compute a file's MD5 hash (for the manifest): `md5sum "reference/path/to/file"` (bash).

---

## Phase 0.5: Verify-First Mode (`--verify`)

If the user invokes `/update-intel --verify [source]` or `/update-intel verify [source]`:

1. **Run the full `/verify-intel` pipeline first** — extract claims, cross-reference against peer-reviewed sources, rate each claim (Verified / Partially Supported / Contested / Unsupported / Misleading / Unverifiable).
2. **Present the verification report** to the user.
3. **Auto-filter**: only Verified and Partially Supported claims proceed to Phase 1-5 compilation. Unsupported/Misleading/Unverifiable claims are excluded from the Research Universe.
4. **Annotate**: Partially Supported claims get a caveat note in the compiled content (e.g., "[Partially supported — specific magnitude unconfirmed]").
5. **If all claims fail verification**, skip compilation entirely and report: "No verified claims to compile."

This mode combines both skills into a single workflow: verify first, then compile only what passes. Use this for sources from lower-reliability tiers (podcasts, social media, influencer content).

Without `--verify`, the default behavior is compile-first (Phases 1-5 below) — use this for sources you've already vetted or that come from high-reliability tiers (textbooks, meta-analyses, clinical guidelines).

---

## Phase 1: Ingest Source Material

**PHI Guard (Non-Negotiable):** Before processing ANY file, check the path. If it contains `profiles/`, `Priv`, or `health_doc`, REJECT immediately:
> "This looks like a personal medical document. Use `/update-profile` instead. This skill processes research material only."

Accept the source in one of these forms:

1. **File path** — Use Read to load the file (transcript, PDF, markdown, etc.).
2. **URL** — Use WebFetch to retrieve the page content. If it's a podcast/video, look for a transcript.
3. **Pasted text** — Use the text directly from the user's message.
4. **"all"** — Process all unprocessed files from Phase 0's scan, one at a time, prompting the user between each.

If the source is unclear or empty, ask the user to clarify before proceeding.

---

## Phase 2: Classify Domain

Determine which Research Universe file this source belongs to:

1. Read the source content and identify the primary health domain.
2. If the source spans multiple domains, pick the **primary** domain (where 60%+ of the content lives).
3. Present the classification to the user — they can override before you write.

---

## Phase 3: Compile into Research Universe Document

### If the Universe file already exists (thematic format):

Universe files use **thematic sections** — each topic appears once with multi-source citations (e.g., "(Entries 3, 7, 13)"). New sources are **merged into existing sections**, not appended as separate blocks.

1. Read the existing file to understand the current thematic structure and SOURCE INDEX.
2. Add a new row to the SOURCE INDEX table with the next entry number.
3. **Run the Deduplication & Merge process (Phase 3A).**

### If the Universe file doesn't exist yet:

Create it using this template:

```markdown
# [Domain] Research Universe
**Master Reference Document — [Source types: Transcripts, Articles, Journals, etc.]**
Last Updated: [Month Year]

> This document compiles [domain] research extracted from transcripts, articles, journals, and other sources. Raw source files are stored in `reference/transcripts/` and `reference/books/`. Content is organized thematically — each topic appears once with all supporting sources cited.

---

## HOW TO ADD NEW ENTRIES

1. New source material goes into `reference/transcripts/` (or appropriate subfolder).
2. Run `/update-intel` to auto-detect and process it.
3. The source gets logged in the SOURCE INDEX and its **unique** findings are merged into the relevant thematic sections below.
4. Duplicate content is consolidated — each data point appears once with all supporting sources cited.

---

## SOURCE INDEX

| # | File | Source | Topics | Est. Words |
|---|------|--------|--------|------------|

---

## THEMATIC CONTENT

---
```

For a **brand new** Universe file with its first source, create initial thematic sections grouped by topic. As more sources are added, content merges into these sections.

### Cleaning rules (apply to source material before merging):
- Remove sponsor segments, subscribe/like requests, and off-topic filler
- Remove repeated phrases and verbal tics from transcripts
- Preserve all substantive claims, data points, study references, and actionable advice
- Keep the original voice — don't rewrite, just clean
- For very long sources (>15,000 words), summarize with key excerpts rather than including the full text

### Update the SOURCE INDEX table with the new entry.

---

## Phase 3A: Deduplication & Merge (MANDATORY for existing Universe files)

**This phase prevents Universe files from bloating with repeated information. Every new source MUST go through this process before its content is written.**

### Step 1: Extract all claims/data points from the new source
Parse the cleaned source material and create a list of every discrete claim, data point, threshold, protocol, or finding. Each item should be a single assertable statement.

### Step 2: Cross-reference against existing content
For each extracted item, search the existing Universe file for:
- **Exact duplicates** — same fact stated with the same or similar numbers (e.g., "caffeine half-life 5-6 hours" already present)
- **Overlapping claims** — same topic covered but with different specificity or framing (e.g., existing says "cool room helps sleep" and new source adds "65-68°F optimal")
- **Contradictions** — new source states something that conflicts with existing content

### Step 3: Classify each item

| Classification | Action |
|---|---|
| **Exact duplicate** | SKIP — do not add. The existing entry already covers this. |
| **Overlapping — new source adds specificity** | MERGE — add the specific data point, study reference, or threshold to the existing section. Append the new entry number to the citation list. |
| **Overlapping — new source adds a different angle** | MERGE — add the new angle as a sub-point within the existing section with the new citation. |
| **Contradiction** | FLAG prominently in the section with both positions cited. Do NOT silently replace. |
| **Genuinely novel** | ADD — create a new sub-point in the most relevant existing thematic section, or create a new section if no existing section fits. |

### Step 4: Merge into thematic sections
- Add new content to the **existing thematic section** where it belongs (e.g., caffeine findings go into the Caffeine section).
- Update citation lists: add the new entry number to any existing point that the new source also supports (e.g., "(Entries 3, 7)" becomes "(Entries 3, 7, 26)").
- If a genuinely new theme emerges that doesn't fit any existing section, create a new thematic section.
- **Never create a per-source content block.** The SOURCE INDEX tracks which sources exist; the thematic sections organize the knowledge.

### Step 5: Report deduplication results
In the Phase 5 summary, include:
```
Deduplication results:
- Items extracted from source: [N]
- Exact duplicates skipped: [N]
- Merged into existing sections: [N]
- Genuinely novel additions: [N]
- Contradictions flagged: [N]
```

### Rules for Deduplication
- **When in doubt, skip.** If a data point is substantially covered by existing content, do not add it again with slightly different wording.
- **Specificity upgrades are valuable.** "Sleep is important" → already covered. "6 days of 4h sleep produces pre-diabetic glucose response" → this is a specific threshold worth adding.
- **Study references are valuable even for known topics.** If a new source cites a specific study that isn't already referenced, add the citation even if the conclusion is already present.
- **Citation lists must stay accurate.** Only add an entry number to a citation if that source genuinely supports the claim. Do not pad citations.
- **The goal is consolidation, not compression.** Keep all unique information. Remove only true redundancy.

---

## Phase 3.5: Auto-Extract Actionable Thresholds

After compiling a source into the Research Universe file, automatically extract quantifiable health assertions and add them to `reference/health_knowledge.json`. This bridges the Research Universe (human-readable library) to the analysis engine (runtime JSON).

### What to Extract

Scan the newly compiled content for assertions that meet ALL of these criteria:
1. **Quantifiable** — contains a specific number, threshold, percentage, or measurable range (e.g., "REM below 20%", "caffeine half-life 5-7 hours", "ACWR >1.3")
2. **Mechanistic** — explains WHY the threshold matters (not just "X is good")
3. **Actionable** — could influence a readiness score, insight, or recommendation
4. **Relevant to tracked data** — maps to a metric the user actually collects (Garmin data, sleep stages, subjective ratings, nutrition notes, training logs)

**Skip:** vague advice ("sleep is important"), claims without thresholds ("exercise improves mood"), product recommendations, and claims about metrics not tracked in this system.

### Entry Format

For each extracted threshold, create a `health_knowledge.json` entry:

```json
{
  "id": "{domain}_{short_descriptor}",
  "domain": "{Domain}",
  "pattern": "{pattern_descriptor}",
  "lookback_days": {number},
  "interpretation": "{What this pattern means and why it matters}",
  "cognitive_impact": "{How this affects cognition — attention, memory, executive function, processing speed}",
  "energy_impact": "{How this affects energy — perceived energy, recovery capacity, physical performance}",
  "citation": "{Source author/study — from the compiled content}",
  "recommendation": "{Specific actionable step when this pattern is detected}",
  "confidence": "Pending",
  "source_claim_id": null,
  "source_file": "{relative path to the Research Universe file}",
  "date_extracted": "{YYYY-MM-DD}"
}
```

### Auto-Trigger Generation (MANDATORY for trackable thresholds)

If the extracted threshold maps to a metric the system actually tracks, add a `"trigger"` field so the analysis engine (`overall_analysis.py`) automatically fires an insight when the condition is detected. **This is what makes new knowledge automatically actionable without code changes.**

#### Available data tabs and fields for triggers:
- **garmin**: Steps, HRV (overnight avg), Resting HR, Avg Stress Level, Body Battery, Intensity Minutes
- **sleep**: Total Sleep (hrs), Garmin Sleep Score, Deep Sleep (min), Deep %, REM (min), REM %, Avg HR, Awakenings, Body Battery Gained, Wake Time, Bedtime
- **daily_log**: Morning Energy (1-10), Midday Energy (1-10), Evening Energy (1-10), Midday Focus (1-10), Perceived Stress (1-10), Day Rating (1-10), Habits Total (0-7)
- **nutrition**: Protein (g), Water (L), Calorie Balance
- **session_log**: (indexed by date, multiple per day) — Duration (min), Avg HR, Anaerobic TE (0-5)

#### Trigger schemas:

**Simple threshold** (single metric crosses a value):
```json
"trigger": {"tab": "garmin", "field": "Steps", "op": "<", "value": 7500, "agg": "avg", "lookback": 7}
```
- `op`: `<`, `>`, `<=`, `>=`
- `agg`: `"any"` (any single day), `"avg"` (average over lookback), `"all"` (every day)
- `requires_session`: set `true` if the insight only applies on training days

**Compound** (multiple conditions must ALL be true):
```json
"trigger": {"type": "compound", "conditions": [
  {"tab": "sleep", "field": "Total Sleep (hrs)", "op": "<", "value": 7, "agg": "avg", "lookback": 7},
  {"tab": "garmin", "field": "Avg Stress Level", "op": ">", "value": 35, "agg": "avg", "lookback": 7}
]}
```

**Divergence** (subjective vs objective metrics disagree):
```json
"trigger": {"type": "divergence",
  "subjective": {"tab": "daily_log", "field": "Morning Energy (1-10)", "op": ">=", "value": 6},
  "objective": {"tab": "sleep", "field": "Garmin Sleep Score", "op": "<", "value": 65},
  "lookback": 3}
```

**Variance** (metric inconsistency over time):
```json
"trigger": {"type": "variance", "tab": "sleep", "field": "Wake Time", "max_std_minutes": 30, "lookback": 7}
```

#### Rules for trigger generation:
- Only add triggers for metrics that ARE tracked (see available fields above)
- If the threshold references a metric NOT tracked (blood pressure, grip strength, VO2max, meditation time, etc.), do NOT add a trigger — the entry remains as reference knowledge for `/health-insight`
- Do not duplicate triggers that overlap with existing hardcoded insights in `generate_insights()` (sleep debt, HRV z-scores, ACWR, diet flags, deep/REM %, etc.)
- When in doubt, omit the trigger — a knowledge entry without a trigger still has value for `/health-insight` queries

### Rules for Auto-Extraction
- Set `"confidence": "Pending"` — these entries are used by the analysis engine but flagged as not-yet-evaluated
- Do NOT duplicate existing entries. Before adding, check if `health_knowledge.json` already has an entry with the same `pattern` or overlapping threshold. If it does, skip unless the new source provides a meaningfully different threshold or mechanism
- Extract conservatively — 2-5 entries per source is typical. A 10,000-word transcript might yield 3-4 actionable thresholds
- The `id` must be unique across the entire JSON file. Use format: `{domain}_{short_snake_case_descriptor}`
- If the source doesn't contain any quantifiable, actionable thresholds, skip this phase entirely and note "No actionable thresholds extracted" in the Phase 5 summary
- After adding entries, validate the JSON file is still parseable (no trailing commas, valid structure)

### Upgrading Pending Entries
When the user later runs explicit claim evaluation (Phase 5 optional), and a claim matches a Pending entry:
- Update `"confidence"` from `"Pending"` to the evaluated level (High/Medium/Low)
- Add `"source_claim_id"` linking to the evaluated claim in `reference/knowledge/{domain}.md`
- Update `interpretation`, `cognitive_impact`, and `energy_impact` if the evaluation reveals more specific information

---

## Phase 3.6: Regenerate Domain Brief

After compiling a source and extracting thresholds, regenerate the domain brief to keep it current:

1. Read the full Research Universe doc for this domain (e.g., `reference/Sleep Research Universe.md`)
2. Compress into `reference/knowledge/summaries/{domain}_brief.md` (target: under 200 lines)
3. Brief structure — each point cites an Entry # from the Universe file:
   - **Consensus Positions** — what most sources agree on (core facts, not opinions)
   - **Key Thresholds** — specific numbers/ranges with citations (table format)
   - **Open Questions** — where sources disagree or evidence is thin
   - **Actionable Protocols** — concrete recommendations backed by multiple sources, organized by priority
4. Include a "Key Interactions with Other Domains" section at the bottom linking to related domains
5. Update the header with the current date and source count

The brief is what `/health-insight` reads for token-efficient queries. It must be accurate and current.

---

## Phase 4: Update Ingestion Manifest

After compiling, log the processed source in `reference/INGESTED.md`:

1. Compute the file's MD5 hash: `md5sum "reference/path/to/file"` (for files; skip for URLs/pasted text).
2. Add a row to the "Ingested Files" table:
   - **File**: relative path from `reference/` (e.g., `transcripts/DOAC x matt walker.txt`)
   - **Date Ingested**: today's date (YYYY-MM-DD)
   - **Domain**: which Research Universe file it was compiled into
   - **MD5 Hash**: the computed hash (or `N/A` for URLs/pasted text)
   - **Notes**: source type (transcript, book, article, URL, etc.)
3. For URLs or pasted text (no file): add to the manifest with the URL or "pasted text" as the File column.

---

## Phase 5: Present Summary

```
--- Research Library Update ---
Source: [source name]
Domain: [domain] -> [Universe file]
Entry #: [number in the Universe file]
Key topics: [topic list]
Est. words added: [count of genuinely new content]

Deduplication results:
- Items extracted from source: [N]
- Exact duplicates skipped: [N]
- Merged into existing sections: [N]
- Genuinely novel additions: [N]
- Contradictions flagged: [N]

Compiled into: reference/[Domain] Research Universe.md
Manifest updated: reference/INGESTED.md
Thresholds extracted: [count] new entries added to health_knowledge.json (confidence: Pending)
Domain brief updated: reference/knowledge/summaries/[domain]_brief.md

Unprocessed files remaining: [count]
```

---

## Optional: Deep Claim Evaluation (on request)

When the user asks to **evaluate claims** from a source (e.g., `/update-intel evaluate [file]` or "evaluate the claims in this"), run the full claim evaluation pipeline:

### Extract Discrete Claims
Parse the source and extract every **specific, testable health claim**:
- Must make a quantitative or mechanistic assertion
- Must be confirmable or refutable with evidence
- Must be actionable for health tracking or analysis

**Skip:** vague statements, pure opinions, marketing language, product claims without mechanism.

### Evaluate Each Claim

**Rate Evidence Quality:**

| Source Type | Default Confidence | Can upgrade if... |
|---|---|---|
| Peer-reviewed meta-analysis / systematic review | High | — |
| Single peer-reviewed RCT or large cohort study | High | Replicated |
| Clinician/researcher citing specific studies | Medium | Studies are findable and solid |
| Podcast host interpreting research | Low-Medium | Cites primary source you can verify |
| Social media / influencer | Low | — |
| No source cited | Unverifiable | — |

**Cross-Reference:** Use WebSearch to find the original study, supporting/contradicting evidence, and whether the claim is mainstream or fringe.

**Render Verdict:**
- **Confirmed** — aligns with current evidence, codebase already correct
- **Update Recommended** — well-supported, codebase should change
- **Novel** — valid but not currently modeled
- **Contradicts** — conflicts with current assumption, needs deeper research
- **Insufficient Evidence** — not well-supported, log but don't act

### Map to Codebase Impact
For claims that would change the analysis engine, grep across:
1. `overall_analysis.py` — readiness scoring, thresholds
2. `garmin_sync.py` — sleep analysis, color grading
3. `dashboard/export_dashboard_data.py` — metric color thresholds
4. `reference/METHODOLOGY.md` — cited research
5. `reference/sleep_color_grading_guide.md` — threshold boundaries

### Write Evaluated Claims
Write to `reference/knowledge/{domain}.md` using this format:

```
### Claim #[N] — [Short descriptive title]

- **Source:** [Full source reference]
- **Date evaluated:** [YYYY-MM-DD]
- **Confidence:** [High / Medium / Low / Unverifiable]
- **Verdict:** [verdict]
- **Evidence:** [3-5 sentence evaluation]
- **Actionable Threshold:** [specific number/range, or "N/A"]

#### Impact Assessment
| File | Location | Current Value | Proposed Change | Risk |
|------|----------|---------------|-----------------|------|

#### Resolution
*Pending user review.*
```

Update the index in `reference/HEALTH_INTEL.md` and regenerate the domain brief in `reference/knowledge/summaries/{domain}_brief.md`.

**Important:** After evaluation, check `reference/health_knowledge.json` for any Pending entries that match the evaluated claims. Upgrade their `"confidence"` field from `"Pending"` to the evaluated level, and set `"source_claim_id"` to link the entry to the full claim evaluation.

---

## Regenerate All Briefs (`--regen-briefs`)

When the user invokes `/update-intel --regen-briefs` or `/update-intel regenerate briefs`:

1. Scan `reference/` for all `*Research Universe.md` files.
2. For each domain file found, regenerate `reference/knowledge/summaries/{domain}_brief.md` using the Phase 3.6 process above.
3. Process domains in alphabetical order. Report progress as each brief is regenerated.
4. Summary at the end: "Regenerated N domain briefs. [list of domains updated]."

Use this when:
- Multiple sources were compiled in quick succession without brief updates
- Briefs have drifted out of sync with their universe files
- After bulk imports or major universe file reorganizations

---

## Rules

- **Compile first, extract thresholds, regenerate brief, evaluate later.** The default action is to compile source material into the Research Universe, auto-extract actionable thresholds (Phase 3.5), and regenerate the domain brief (Phase 3.6). Full claim evaluation only happens when explicitly requested.
- **Never auto-apply code changes.** Claim evaluation recommends. The user decides what to change.
- **Always update the manifest.** Every processed source must be logged in `reference/INGESTED.md`.
- **Detect modified files.** If a file's current MD5 differs from the stored hash, flag it as modified.
- **Keep exclusions current.** When new non-ingestible files appear (images, system docs), add them to the Excluded Files table.
- **Match the existing format.** When adding to an existing Universe file, follow its established structure exactly.
- **Clean, don't rewrite.** Preserve the source's voice and substance. Remove only filler, sponsors, and noise.
- **Be honest about uncertainty.** When evaluating claims, if you can't verify it, say so.
- **Weight evidence hierarchy strictly.** A podcast host's opinion does not outweigh a meta-analysis.
- **Flag contradictions prominently.** When a new claim contradicts an existing assumption, make it impossible to miss.
