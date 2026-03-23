"""Migration consistency smoke tests.

Validates that the fresh-install schema, migration patches, and setup script
stay aligned. Pure file-based — no database connection required.

Run: python -m pytest tests/test_migration_consistency.py -v
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCHEMA_SQL = ROOT / "supabase_schema.sql"
SETUP_PY = ROOT / "setup_supabase.py"
V3_MIGRATION = ROOT / "supabase_schema_v3.sql"
V3_1_PATCH = ROOT / "supabase_schema_v3_1_patch.sql"
V3_2_PATCH = ROOT / "supabase_schema_v3_2_patch.sql"


def _read(path):
    return path.read_text(encoding="utf-8")


# -----------------------------------------------------------------------
# 1. Fresh schema has all expected tables
# -----------------------------------------------------------------------

_EXPECTED_TABLES = [
    "garmin", "sleep", "overall_analysis", "daily_log", "session_log",
    "nutrition", "strength_log", "raw_data_archive", "_meta",
    "illness_state", "illness_daily_log",
]


def test_fresh_schema_has_all_tables():
    sql = _read(SCHEMA_SQL)
    tables = re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', sql)
    for t in _EXPECTED_TABLES:
        assert t in tables, f"Table '{t}' missing from supabase_schema.sql"


def test_fresh_schema_version_is_current():
    sql = _read(SCHEMA_SQL)
    assert "_meta" in sql, "Fresh schema must have _meta table for version tracking"


# -----------------------------------------------------------------------
# 2. v3 migration adds user_id and composite PKs
# -----------------------------------------------------------------------

def test_v3_migration_adds_user_id():
    sql = _read(V3_MIGRATION)
    assert "user_id" in sql, "v3 migration must add user_id column"
    assert "PRIMARY KEY" in sql or "primary key" in sql.lower(), \
        "v3 migration must define composite primary keys"


# -----------------------------------------------------------------------
# 3. v3.1 patch adds set_id
# -----------------------------------------------------------------------

def test_v3_1_adds_set_id():
    sql = _read(V3_1_PATCH)
    assert "set_id" in sql, "v3.1 patch must add set_id column"
    assert "strength_log_set_uq" in sql, \
        "v3.1 patch must create strength_log_set_uq constraint"


# -----------------------------------------------------------------------
# 4. v3.2 patch makes set_id NOT NULL
# -----------------------------------------------------------------------

def test_v3_2_makes_set_id_not_null():
    sql = _read(V3_2_PATCH)
    assert "NOT NULL" in sql or "not null" in sql.lower(), \
        "v3.2 patch must make set_id NOT NULL"
    assert "DEFAULT" in sql or "default" in sql.lower(), \
        "v3.2 patch must add server default for set_id"


# -----------------------------------------------------------------------
# 5. set_id consistent across files
# -----------------------------------------------------------------------

def test_set_id_consistent_across_files():
    schema = _read(SCHEMA_SQL)
    assert "set_id TEXT NOT NULL" in schema, \
        "Fresh schema must have set_id TEXT NOT NULL"

    v31 = _read(V3_1_PATCH)
    assert "set_id" in v31, "v3.1 patch must reference set_id"

    v32 = _read(V3_2_PATCH)
    assert "NOT NULL" in v32, "v3.2 patch must enforce NOT NULL on set_id"


def test_strength_log_set_uq_in_schema_and_patches():
    schema = _read(SCHEMA_SQL)
    v31 = _read(V3_1_PATCH)
    assert "strength_log_set_uq" in schema, \
        "Fresh schema must have strength_log_set_uq constraint"
    assert "strength_log_set_uq" in v31, \
        "v3.1 patch must create strength_log_set_uq constraint"


# -----------------------------------------------------------------------
# 6. Schema version sequence
# -----------------------------------------------------------------------

def test_schema_version_sequence():
    v3 = _read(V3_MIGRATION)
    v31 = _read(V3_1_PATCH)
    v32 = _read(V3_2_PATCH)
    py = _read(SETUP_PY)

    assert "'3'" in v3 or '"3"' in v3, "v3 migration must set version 3"
    assert "'3.1'" in v31 or '"3.1"' in v31, "v3.1 patch must set version 3.1"
    assert "'3.2'" in v32 or '"3.2"' in v32, "v3.2 patch must set version 3.2"

    match = re.search(r'SCHEMA_VERSION\s*=\s*"([\d.]+)"', py)
    assert match, "setup_supabase.py must have SCHEMA_VERSION constant"
    assert match.group(1) == "3.2", f"SCHEMA_VERSION should be 3.2, got {match.group(1)}"


# -----------------------------------------------------------------------
# 7. setup_supabase.py reads schema from file (no embedded SQL)
# -----------------------------------------------------------------------

def test_setup_supabase_reads_schema_file():
    py = _read(SETUP_PY)
    assert "_load_ddl_from_schema_file" in py, \
        "setup_supabase.py must use _load_ddl_from_schema_file()"
    # Should NOT have the old embedded CREATE TABLE SQL
    assert "CREATE_TABLES_SQL" not in py, \
        "setup_supabase.py must not have embedded CREATE_TABLES_SQL"
