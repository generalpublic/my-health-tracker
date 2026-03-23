"""Shared type-conversion helpers.

Previously duplicated in sqlite_backup.py and supabase_sync.py.
Canonical home is here; those modules can import from this module.
"""


def to_num(val):
    """Convert empty strings and non-numeric values to None; preserve numbers."""
    if val is None or val == "":
        return None
    try:
        f = float(val)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return str(val)


def to_text(val):
    """Convert to text, returning None for empty strings."""
    if val is None or val == "":
        return None
    return str(val)


def day_from_date(date_str):
    """Convert YYYY-MM-DD to 3-letter day abbreviation."""
    from datetime import date as _d
    try:
        d = _d.fromisoformat(str(date_str))
        return d.strftime("%a")
    except (ValueError, TypeError):
        return None
