"""Frontend bootstrap sanity tests.

Validates that all deployed HTML pages reference their required JS files,
all referenced JS/CSS files exist on disk, and core JS files define
expected globals. Pure file-based — no browser or Node required.

Run: python -m pytest tests/test_frontend_bootstrap.py -v
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
APP = ROOT / "app_mockups"

_DEPLOYED_PAGES = [
    "index.html", "today.html", "activity.html", "calendar.html",
    "trends.html", "sleep-detail.html", "log-entry.html", "profile.html",
]


def _read(path):
    return path.read_text(encoding="utf-8")


# -----------------------------------------------------------------------
# 1. All referenced JS/CSS files exist on disk
# -----------------------------------------------------------------------

def test_all_script_src_files_exist():
    """Every <script src="..."> in deployed pages must point to an existing file."""
    missing = []
    for page in _DEPLOYED_PAGES:
        html = _read(APP / page)
        srcs = re.findall(r'<script\b[^>]+src="([^"]+)"', html)
        for src in srcs:
            if src.startswith("http://") or src.startswith("https://"):
                continue  # CDN — skip
            resolved = APP / src
            if not resolved.exists():
                missing.append(f"{page} -> {src}")
    assert not missing, f"Missing JS files:\n" + "\n".join(missing)


def test_all_stylesheet_files_exist():
    """Every <link rel="stylesheet" href="..."> must point to an existing file."""
    missing = []
    for page in _DEPLOYED_PAGES:
        html = _read(APP / page)
        hrefs = re.findall(r'<link\b[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)
        hrefs += re.findall(r'<link\b[^>]+href="([^"]+)"[^>]+rel="stylesheet"', html)
        for href in hrefs:
            if href.startswith("http"):
                continue
            resolved = APP / href
            if not resolved.exists():
                missing.append(f"{page} -> {href}")
    assert not missing, f"Missing CSS files:\n" + "\n".join(missing)


# -----------------------------------------------------------------------
# 2. Core JS files define expected globals/functions
# -----------------------------------------------------------------------

_EXPECTED_GLOBALS = {
    "config.js": ["SUPABASE_URL", "SUPABASE_ANON_KEY"],
    "auth.js": ["isAuthenticated", "checkAuth", "getCurrentUser", "requireAuth"],
    "data-loader.js": ["supabaseQuery", "initData", "SAMPLE_DATA"],
    "crypto-store.js": ["CryptoStore"],
    "js/sw-register.js": ["getSWVersion"],
}


def test_core_js_globals():
    """Core JS files must define their expected globals/functions."""
    missing = []
    for js_file, globals_list in _EXPECTED_GLOBALS.items():
        js = _read(APP / js_file)
        for g in globals_list:
            # Match: function name, const/let/var name, or name = (assignment)
            pattern = rf'(?:function\s+{g}|(?:const|let|var)\s+{g}|{g}\s*=)'
            if not re.search(pattern, js):
                missing.append(f"{js_file}: missing '{g}'")
    assert not missing, f"Missing globals:\n" + "\n".join(missing)


# -----------------------------------------------------------------------
# 3. SW cache asset list covers core files
# -----------------------------------------------------------------------

_CORE_ASSETS = [
    "config.js", "auth.js", "data-loader.js", "crypto-store.js",
    "design-system.css", "manifest.json",
]


def test_sw_caches_core_assets():
    """Service worker ASSETS list must include core files."""
    sw = _read(APP / "sw.js")
    missing = [a for a in _CORE_ASSETS if f"'{a}'" not in sw and f'"{a}"' not in sw]
    assert not missing, f"SW ASSETS missing: {missing}"


# -----------------------------------------------------------------------
# 4. Config.js has version constants (for diagnostics)
# -----------------------------------------------------------------------

def test_config_has_version_constants():
    """config.js must define APP_VERSION and SCHEMA_VERSION for diagnostics."""
    js = _read(APP / "config.js")
    assert "APP_VERSION" in js, "config.js must define APP_VERSION"
    assert "SCHEMA_VERSION" in js, "config.js must define SCHEMA_VERSION"


# -----------------------------------------------------------------------
# 5. Profile diagnostics does NOT query _meta table
# -----------------------------------------------------------------------

def test_profile_diagnostics_no_meta_query():
    """Diagnostics must not query _meta (RLS blocks browser reads)."""
    js = _read(APP / "js/profile.js")
    assert "supabaseQuery" not in js, \
        "profile.js must not call supabaseQuery — diagnostics should use config.js constants"
    assert "'_meta'" not in js and '"_meta"' not in js, \
        "profile.js must not reference _meta table"
