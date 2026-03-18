"""
Health Profile Loader — Single access point for personal health profile data.

All analysis scripts import from this module. No PHI is ever printed to stdout —
only counts and categories. The profile itself lives in a gitignored directory.

Usage:
    from profile_loader import load_profile, get_accommodations, format_recommendation
    profile = load_profile()  # returns {} if no profile exists
"""

import json
import os
import re
from datetime import datetime, date
from pathlib import Path

# ---------------------------------------------------------------------------
# Staleness thresholds by biomarker category (months)
# ---------------------------------------------------------------------------
STALENESS_THRESHOLDS = {
    "heavy_metals": 6,
    "glucose": 12,
    "hba1c": 12,
    "lipid_panel": 36,
    "thyroid": 12,
    "liver_function": 12,
    "kidney_function": 12,
    "inflammatory": 12,
    "vitamins": 12,
    "hormones": 12,
    "cbc": 12,
    "antibodies": 12,
    "genetic": None,       # never stale
    "brain_imaging": 24,
    "mycotoxin": 12,
    "vcs": 6,
}

# Default analysis constants (mirrored from overall_analysis.py)
DEFAULT_READINESS_WEIGHTS = {
    "HRV": 0.35,
    "Sleep": 0.30,
    "RHR": 0.20,
    "Subjective": 0.15,
}

DEFAULT_READINESS_LABELS = [
    (8.5, "Optimal"),
    (7.0, "Good"),
    (5.5, "Fair"),
    (4.0, "Low"),
    (0.0, "Poor"),
]

DEFAULT_BASELINE_WINDOW = 30  # days


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------

def load_profile(profile_dir=None):
    """Load the active health profile.

    Resolution order:
        1. Explicit profile_dir argument
        2. HEALTH_PROFILE_DIR in .env (relative to project root)
        3. profiles/ with single subdirectory
        4. Returns empty dict (graceful degradation)

    Returns dict (profile data) or empty dict.
    Never prints PHI — only counts and categories.
    """
    project_root = Path(__file__).parent

    # 1. Explicit argument
    if profile_dir:
        p = Path(profile_dir)
        if not p.is_absolute():
            p = project_root / p
    else:
        # 2. Environment variable
        env_dir = os.environ.get("HEALTH_PROFILE_DIR")
        if not env_dir:
            # Try loading from .env file
            env_file = project_root / ".env"
            if env_file.exists():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("HEALTH_PROFILE_DIR="):
                        env_dir = line.split("=", 1)[1].strip()
                        break

        if env_dir:
            p = Path(env_dir)
            if not p.is_absolute():
                p = project_root / p
        else:
            # 3. Fallback: profiles/ with single subdirectory
            profiles_root = project_root / "profiles"
            if profiles_root.exists():
                subdirs = [d for d in profiles_root.iterdir() if d.is_dir()]
                if len(subdirs) == 1:
                    p = subdirs[0]
                else:
                    return {}
            else:
                return {}

    profile_file = p / "profile.json"
    if not profile_file.exists():
        return {}

    try:
        with open(profile_file, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [profile] Warning: could not load profile: {e}")
        return {}

    # Compute staleness for biomarkers
    _compute_staleness(profile)

    # Compute priority scores
    _compute_priority_scores(profile)

    # Print safe summary (counts only, never values)
    _print_summary(profile)

    return profile


def _compute_staleness(profile):
    """Compute staleness_months for each biomarker based on test_date."""
    today = date.today()
    for bio in profile.get("biomarkers", []):
        test_date_str = bio.get("test_date")
        if not test_date_str:
            bio["staleness_months"] = None
            bio["is_stale"] = True
            continue
        try:
            test_date = datetime.strptime(test_date_str, "%Y-%m-%d").date()
            delta = (today - test_date).days / 30.44  # average month
            bio["staleness_months"] = round(delta, 1)

            category = bio.get("category", "")
            threshold = STALENESS_THRESHOLDS.get(category)
            bio["is_stale"] = threshold is not None and delta > threshold
        except ValueError:
            bio["staleness_months"] = None
            bio["is_stale"] = True


def _compute_priority_scores(profile):
    """Compute priority_score for each health priority.

    Formula: severity * 0.4 + recency * 0.3 + data_availability * 0.3
    Recency decays: 10=this month, 7=3mo, 4=6mo, 1=>1yr
    """
    for pri in profile.get("health_priorities", []):
        severity = pri.get("severity", 5)
        recency = pri.get("recency", 5)
        data_avail = pri.get("data_availability", 5)
        pri["priority_score"] = round(severity * 0.4 + recency * 0.3 + data_avail * 0.3, 2)

    # Sort by priority_score descending
    profile.get("health_priorities", []).sort(
        key=lambda x: x.get("priority_score", 0), reverse=True
    )


def _print_summary(profile):
    """Print safe profile summary — counts only, never PHI."""
    pid = profile.get("profile_id", "unknown")
    n_conditions = len([c for c in profile.get("conditions", [])
                        if c.get("status") == "active"])
    n_biomarkers = len(profile.get("biomarkers", []))
    n_priorities = len(profile.get("health_priorities", []))
    n_stale = len([b for b in profile.get("biomarkers", []) if b.get("is_stale")])
    n_meds = len(profile.get("medications", []))
    n_supps = len(profile.get("supplements", []))

    print(f"  [profile] Loaded: {pid} "
          f"({n_conditions} conditions, {n_biomarkers} biomarkers, "
          f"{n_priorities} priorities, {n_meds} meds, {n_supps} supplements)")
    if n_stale > 0:
        print(f"  [profile] Warning: {n_stale} biomarker(s) past staleness threshold")

    # Print accommodation status
    accoms = get_accommodations(profile)
    if accoms.get("output_format") or accoms.get("analysis_adjustments"):
        categories = list(dict.fromkeys(
            c.get("category", "unknown")
            for c in profile.get("conditions", [])
            if c.get("status") == "active" and c.get("accommodations")
        ))
        if categories:
            print(f"  [profile] Accommodations active: {', '.join(categories)} adjustments")


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def get_threshold_overrides(profile):
    """Extract threshold overrides from profile.

    Returns dict with optional keys:
        readiness_weights: {"HRV": 0.40, ...}
        readiness_labels: [(8.5, "Optimal"), ...]
        baseline_windows: {"hrv": 14, "sleep_duration": 30, ...}
        acwr_sweet_spot: {"low": 0.8, "high": 1.3}
    """
    if not profile:
        return {}
    return profile.get("threshold_overrides", {})


def get_accommodations(profile):
    """Extract all active accommodation rules from active conditions.

    Returns:
        {
            "output_format": {merged rules from all active conditions},
            "analysis_adjustments": {merged rules from all active conditions},
            "contraindications": [merged list from all active conditions]
        }
    """
    if not profile:
        return {}

    output_format = {}
    analysis_adjustments = {}
    contraindications = []

    for condition in profile.get("conditions", []):
        if condition.get("status") != "active":
            continue
        accoms = condition.get("accommodations", {})
        output_format.update(accoms.get("output_format", {}))
        analysis_adjustments.update(accoms.get("analysis_adjustments", {}))
        contraindications.extend(condition.get("contraindications", []))

    return {
        "output_format": output_format,
        "analysis_adjustments": analysis_adjustments,
        "contraindications": list(set(contraindications)),
    }


def get_relevant_conditions(profile, domain):
    """Filter active conditions relevant to a specific analysis domain.

    Args:
        profile: loaded profile dict
        domain: string like "sleep", "cognition", "hrv", "training"

    Returns list of condition dicts where domain is in tracking_relevance.
    """
    if not profile:
        return []
    domain_lower = domain.lower()
    return [
        c for c in profile.get("conditions", [])
        if c.get("status") == "active"
        and domain_lower in [r.lower() for r in c.get("tracking_relevance", [])]
    ]


def get_priority_concerns(profile, top_n=3):
    """Return top-N health priorities by priority_score.

    Returns list of priority dicts, sorted by score descending.
    """
    if not profile:
        return []
    priorities = profile.get("health_priorities", [])
    return priorities[:top_n]


def get_relevant_biomarkers(profile, domain):
    """Filter biomarkers relevant to a specific domain.

    Args:
        profile: loaded profile dict
        domain: string like "cognition", "hrv", "sleep"

    Returns list of biomarker dicts where domain is in tracking_relevance.
    """
    if not profile:
        return []
    domain_lower = domain.lower()
    return [
        b for b in profile.get("biomarkers", [])
        if domain_lower in [r.lower() for r in b.get("tracking_relevance", [])]
    ]


# ---------------------------------------------------------------------------
# Biomarker staleness check
# ---------------------------------------------------------------------------

def check_biomarker_staleness(profile):
    """Return list of staleness warnings for biomarkers past threshold.

    Returns list of dicts: {"name": ..., "category": ..., "months_old": ..., "threshold": ..., "urgency": ...}
    """
    if not profile:
        return []
    warnings = []
    for bio in profile.get("biomarkers", []):
        if not bio.get("is_stale"):
            continue
        category = bio.get("category", "")
        threshold = STALENESS_THRESHOLDS.get(category)
        if threshold is None:
            continue
        months = bio.get("staleness_months", 0)
        urgency = "high" if months > threshold * 1.5 else "medium"
        warnings.append({
            "name": bio.get("name", "Unknown"),
            "category": category,
            "months_old": months,
            "threshold_months": threshold,
            "urgency": urgency,
        })
    return warnings


# ---------------------------------------------------------------------------
# Recommendation formatting (accommodation-aware)
# ---------------------------------------------------------------------------

def format_recommendation(text, accommodations):
    """Apply accommodation output formatting rules to recommendation text.

    Rules applied (from output_format):
        max_recommendations: cap number of recommendations
        use_numbered_steps: convert bullets to numbers
        bold_action_verbs: bold the first verb in each line
        single_priority_focus: add DO THIS FIRST marker
        avoid_wall_of_text: break long paragraphs

    Args:
        text: recommendation string (may contain newlines)
        accommodations: dict from get_accommodations()

    Returns formatted string.
    """
    if not accommodations:
        return text

    fmt = accommodations.get("output_format", {})
    if not fmt:
        return text

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    # Cap recommendations count
    max_recs = fmt.get("max_recommendations")
    if max_recs and len(lines) > max_recs:
        lines = lines[:max_recs]

    # Number instead of bullets
    if fmt.get("use_numbered_steps"):
        numbered = []
        for i, line in enumerate(lines, 1):
            # Strip existing bullet markers
            clean = re.sub(r"^[-*]\s*", "", line)
            clean = re.sub(r"^\d+[.)]\s*", "", clean)
            numbered.append(f"{i}. {clean}")
        lines = numbered

    # Bold action verbs (first word of each line after number/bullet)
    if fmt.get("bold_action_verbs"):
        bolded = []
        for line in lines:
            match = re.match(r"^(\d+\.\s*)(.*)", line)
            if match:
                prefix, rest = match.groups()
                words = rest.split(" ", 1)
                if len(words) >= 1:
                    words[0] = f"**{words[0]}**"
                bolded.append(prefix + " ".join(words))
            else:
                words = line.split(" ", 1)
                if len(words) >= 1:
                    words[0] = f"**{words[0]}**"
                bolded.append(" ".join(words))
        lines = bolded

    # Single priority focus — mark first item
    if fmt.get("single_priority_focus") and lines:
        lines[0] = "DO THIS FIRST: " + lines[0]

    result = "\n".join(lines)

    # Avoid wall of text — ensure line breaks between items
    if fmt.get("avoid_wall_of_text"):
        result = re.sub(r"\n(\d+\.)", r"\n\n\1", result)

    return result


# ---------------------------------------------------------------------------
# Notification sanitization (PHI removal for Pushover)
# ---------------------------------------------------------------------------

def sanitize_for_notification(text, profile=None):
    """Strip PHI from text before sending via Pushover or other third-party.

    Removes:
        - Condition names from profile
        - Medication/supplement names from profile
        - Biomarker values and specific test names
        - Common diagnostic terms

    Replaces with generic language that keeps the insight actionable.
    """
    if not text:
        return text

    # Build blocklist from profile
    blocklist = set()
    if profile:
        for c in profile.get("conditions", []):
            name = c.get("name", "")
            if name:
                blocklist.add(name.lower())
                # Also block common abbreviations/variants
                blocklist.add(name.lower().replace("-", " "))
                blocklist.add(name.lower().replace(" ", "-"))

        for m in profile.get("medications", []):
            name = m.get("name", "")
            if name:
                blocklist.add(name.lower())

        # Supplements are NOT blocked — they're not PHI
        # (e.g., "Take magnesium" is common advice, not a medical secret)

        for b in profile.get("biomarkers", []):
            name = b.get("name", "")
            if name:
                blocklist.add(name.lower())

    # Common diagnostic terms to strip regardless of profile
    diagnostic_terms = {
        "diagnosed", "diagnosis", "condition", "disorder", "syndrome",
        "deficit", "dysfunction", "impairment", "disability",
    }

    sanitized = text
    for term in blocklist:
        if len(term) >= 3:  # avoid replacing very short strings
            # Handle "Your <term>" → "Your profile factors" (avoid "Your your")
            pattern_with_your = re.compile(
                r"\byour\s+" + re.escape(term), re.IGNORECASE
            )
            sanitized = pattern_with_your.sub("your profile factors", sanitized)
            # Handle standalone occurrences
            pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
            sanitized = pattern.sub("profile factors", sanitized)

    # Strip specific biomarker values (patterns like "2.1 ug/dL", "45 ms")
    sanitized = re.sub(
        r"\d+\.?\d*\s*(ug/dL|mg/dL|ng/mL|pmol/L|umol/L|IU/L|U/L|mmol/L|g/dL|%)\b",
        "[value]",
        sanitized,
        flags=re.IGNORECASE,
    )

    return sanitized


# ---------------------------------------------------------------------------
# Knowledge merge (three-layer hierarchy)
# ---------------------------------------------------------------------------

def merge_knowledge(knowledge, profile):
    """Merge population-level knowledge with profile-specific overrides.

    Layer 1: Population baseline (health_knowledge.json entries)
    Layer 2: Profile threshold_overrides override specific values
    Layer 3: Runtime merge returns combined dict

    Profile overrides can specify:
        knowledge_overrides: {
            "sleep_debt_major": {"threshold": 1.25},  # override 1.5h default
            "hrv_critical_low": {"z_threshold": -2.0}  # override -1.5 default
        }

    Returns new knowledge dict with overrides applied.
    """
    if not profile or not knowledge:
        return knowledge or {}

    overrides = profile.get("threshold_overrides", {}).get("knowledge_overrides", {})
    if not overrides:
        return knowledge

    # Deep copy to avoid mutating the original
    merged = {}
    if isinstance(knowledge, dict):
        merged = {k: dict(v) if isinstance(v, dict) else v
                  for k, v in knowledge.items()}
    elif isinstance(knowledge, list):
        merged = [dict(entry) if isinstance(entry, dict) else entry
                  for entry in knowledge]
        # Apply overrides by matching entry id
        for entry in merged:
            entry_id = entry.get("id", "")
            if entry_id in overrides:
                entry.update(overrides[entry_id])
        return merged

    # Dict-keyed knowledge
    for entry_id, override_vals in overrides.items():
        if entry_id in merged and isinstance(merged[entry_id], dict):
            merged[entry_id].update(override_vals)

    return merged


# ---------------------------------------------------------------------------
# Convenience: check if profile is loaded and has conditions
# ---------------------------------------------------------------------------

def has_profile():
    """Quick check: does a profile exist and have at least one condition?
    Does NOT load the full profile — just checks file existence.
    """
    project_root = Path(__file__).parent
    env_file = project_root / ".env"
    profile_dir = None

    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("HEALTH_PROFILE_DIR="):
                profile_dir = line.split("=", 1)[1].strip()
                break

    if not profile_dir:
        return False

    p = Path(profile_dir)
    if not p.is_absolute():
        p = project_root / p

    return (p / "profile.json").exists()


# ---------------------------------------------------------------------------
# Main (standalone test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Health Profile Loader Test ===\n")
    profile = load_profile()

    if not profile:
        print("\nNo profile found. Create profiles/<name>/profile.json to get started.")
    else:
        print(f"\nProfile ID: {profile.get('profile_id', 'unknown')}")

        # Test accommodations
        accoms = get_accommodations(profile)
        if accoms.get("output_format"):
            print(f"Output format rules: {list(accoms['output_format'].keys())}")
        if accoms.get("contraindications"):
            print(f"Contraindications: {len(accoms['contraindications'])} rules")

        # Test priority concerns
        priorities = get_priority_concerns(profile)
        if priorities:
            print(f"\nTop {len(priorities)} health priorities:")
            for i, pri in enumerate(priorities, 1):
                print(f"  {i}. {pri.get('concern', '?')} "
                      f"(score: {pri.get('priority_score', '?')})")

        # Test staleness
        stale = check_biomarker_staleness(profile)
        if stale:
            print(f"\nStaleness warnings ({len(stale)}):")
            for w in stale:
                print(f"  - {w['name']}: {w['months_old']:.0f} months old "
                      f"(threshold: {w['threshold_months']}mo, "
                      f"urgency: {w['urgency']})")

        # Test recommendation formatting
        test_rec = ("- Prioritize 8.5h sleep tonight\n"
                    "- Take magnesium 30min before bed\n"
                    "- No screens after 9 PM\n"
                    "- Do 10min yoga nidra before sleep\n"
                    "- Set alarm for 9:30 AM")
        formatted = format_recommendation(test_rec, accoms)
        print(f"\nFormatted recommendation:\n{formatted}")

        # Test sanitization
        test_text = "Your ADHD means executive function drops when HRV is below 35 ms"
        sanitized = sanitize_for_notification(test_text, profile)
        print(f"\nSanitized for notification:\n  Before: {test_text}\n  After:  {sanitized}")
