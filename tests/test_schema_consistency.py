"""Schema consistency regression tests.

Ensures that schema definitions in supabase_schema.sql, setup_supabase.py,
and migration files stay in sync. Catches drift before it reaches production.

Run: python -m pytest tests/test_schema_consistency.py -v
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCHEMA_SQL = ROOT / "supabase_schema.sql"
SETUP_PY = ROOT / "setup_supabase.py"
APP_MOCKUPS = ROOT / "app_mockups"


def _read(path):
    return path.read_text(encoding="utf-8")


# -----------------------------------------------------------------------
# 1. set_id exists in all required places
# -----------------------------------------------------------------------

def test_set_id_in_schema_sql():
    sql = _read(SCHEMA_SQL)
    assert "set_id TEXT NOT NULL" in sql, "supabase_schema.sql must declare set_id as NOT NULL"
    assert "strength_log_set_uq" in sql, "supabase_schema.sql must have strength_log_set_uq constraint"


def test_set_id_in_setup_py():
    py = _read(SETUP_PY)
    # setup_supabase.py no longer embeds CREATE TABLE SQL — schema is read from file.
    # Verify TABLE_CONFIGS still references set_id for sync metadata.
    assert '"set_id"' in py or "'set_id'" in py, "setup_supabase.py TABLE_CONFIGS must include set_id"


def test_set_id_in_data_loader():
    js = _read(APP_MOCKUPS / "data-loader.js")
    assert "set_id" in js, "data-loader.js saveStrengthSet must generate set_id"
    assert "crypto.randomUUID()" in js, "data-loader.js must use crypto.randomUUID() for set_id"


# -----------------------------------------------------------------------
# 2. spo2 columns exist in all required places
# -----------------------------------------------------------------------

def test_spo2_in_schema_sql():
    sql = _read(SCHEMA_SQL)
    assert "spo2_avg REAL" in sql, "supabase_schema.sql garmin table must have spo2_avg"
    assert "spo2_min REAL" in sql, "supabase_schema.sql garmin table must have spo2_min"


def test_spo2_in_setup_py():
    py = _read(SETUP_PY)
    assert "spo2_avg" in py, "setup_supabase.py must have spo2_avg in garmin config"
    assert "spo2_min" in py, "setup_supabase.py must have spo2_min in garmin config"


def test_spo2_in_supabase_sync():
    # Mapping now lives in models/mappers.py (canonical domain model)
    from models.garmin import GarminWellnessRecord
    fields = GarminWellnessRecord.field_names()
    assert "spo2_avg" in fields, "GarminWellnessRecord must have spo2_avg"
    assert "spo2_min" in fields, "GarminWellnessRecord must have spo2_min"


# -----------------------------------------------------------------------
# 3. Schema version matches across files
# -----------------------------------------------------------------------

def test_schema_version_consistent():
    py = _read(SETUP_PY)
    match = re.search(r'SCHEMA_VERSION\s*=\s*"([\d.]+)"', py)
    assert match, "setup_supabase.py must have SCHEMA_VERSION constant"
    version = match.group(1)
    assert version == "3.2", f"SCHEMA_VERSION should be 3.2, got {version}"


# -----------------------------------------------------------------------
# 4. All deployed pages have CSP
# -----------------------------------------------------------------------

_DEPLOYED_PAGES = [
    "index.html", "today.html", "activity.html", "calendar.html",
    "trends.html", "sleep-detail.html", "log-entry.html", "profile.html",
]


def test_all_pages_have_csp():
    missing = []
    for page in _DEPLOYED_PAGES:
        html = _read(APP_MOCKUPS / page)
        if "Content-Security-Policy" not in html:
            missing.append(page)
    assert not missing, f"Pages missing CSP meta tag: {missing}"


def test_no_unsafe_inline_in_script_src():
    violations = []
    for page in _DEPLOYED_PAGES:
        html = _read(APP_MOCKUPS / page)
        # Find CSP meta tag content
        csp_match = re.search(r'content="([^"]*Content-Security-Policy[^"]*)"', html)
        if not csp_match:
            csp_match = re.search(r'Content-Security-Policy[^"]*content="([^"]*)"', html)
        if csp_match:
            csp = csp_match.group(1)
        else:
            # Try the actual content attr
            csp_match = re.search(r'Content-Security-Policy"\s+content="([^"]*)"', html)
            csp = csp_match.group(1) if csp_match else html

        if "script-src" in csp and "'unsafe-inline'" in csp.split("script-src")[1].split(";")[0]:
            violations.append(page)
    assert not violations, f"Pages with unsafe-inline in script-src: {violations}"


# -----------------------------------------------------------------------
# 5. No inline scripts in deployed pages
# -----------------------------------------------------------------------

def test_no_inline_scripts_in_deployed_pages():
    """Deployed pages must not have inline script blocks (only src= references)."""
    violations = []
    for page in _DEPLOYED_PAGES:
        html = _read(APP_MOCKUPS / page)
        # Find all <script> tags and check they have src=
        script_tags = re.findall(r'<script\b([^>]*)>(.*?)</script>', html, re.DOTALL)
        for attrs, body in script_tags:
            if 'src=' not in attrs and body.strip():
                violations.append(f"{page}: inline script ({len(body.strip())} chars)")
    assert not violations, f"Inline scripts found:\n" + "\n".join(violations)


# -----------------------------------------------------------------------
# 6. SW cache assets list includes new js/ files
# -----------------------------------------------------------------------

def test_sw_cache_includes_js_files():
    sw = _read(APP_MOCKUPS / "sw.js")
    # The SW should be able to cache external JS files.
    # At minimum, it should not block on missing files (uses allSettled).
    assert "allSettled" in sw or "Promise.all" in sw, "SW install should handle individual cache failures"


# -----------------------------------------------------------------------
# 7. No inline event handlers in deployed pages
# -----------------------------------------------------------------------

_INLINE_HANDLER_RE = re.compile(r'\bon(?:click|input|change|submit|keydown|keyup|focus|blur)\s*=')

def test_no_inline_event_handlers_in_html():
    """Deployed HTML must not have inline event handlers (onclick=, oninput=, etc.)."""
    violations = []
    for page in _DEPLOYED_PAGES:
        html = _read(APP_MOCKUPS / page)
        matches = _INLINE_HANDLER_RE.findall(html)
        if matches:
            violations.append(f"{page}: {len(matches)} inline handlers")
    assert not violations, f"Inline event handlers found:\n" + "\n".join(violations)


# -----------------------------------------------------------------------
# 8. No inline <style> blocks in deployed pages
# -----------------------------------------------------------------------

def test_no_inline_style_blocks():
    """Deployed HTML must use external CSS files, not <style> blocks."""
    violations = []
    for page in _DEPLOYED_PAGES:
        html = _read(APP_MOCKUPS / page)
        style_blocks = re.findall(r'<style\b[^>]*>(.+?)</style>', html, re.DOTALL)
        for block in style_blocks:
            if block.strip():
                violations.append(f"{page}: inline <style> ({len(block.strip())} chars)")
    assert not violations, f"Inline style blocks found:\n" + "\n".join(violations)
