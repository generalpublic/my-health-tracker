# Database Migrations — Apply Order

Historical and active migration scripts. Supabase migrations must be applied
in order via the SQL Editor.

## Fresh Install

Run `supabase_schema.sql` in the Supabase SQL Editor. This creates all tables
at the current schema version (v3.2) with correct constraints, RLS, and defaults.
No migration files are needed for a fresh install.

## Existing Database — Migration Path

If you already have a running database, apply migrations in this order:

| Step | File | Version | What it does |
|------|------|---------|-------------|
| 1 | `supabase_schema_v3.sql` | 3.0 | Converts all tables to composite PKs `(user_id, date)` |
| 2 | `supabase_schema_v3_1_patch.sql` | 3.1 | Adds `set_id` to strength_log, UNIQUE on `(user_id, set_id)` |
| 3 | `supabase_schema_v3_2_patch.sql` | 3.2 | Makes `set_id NOT NULL DEFAULT`, enforces constraint |

## How to check current version

```sql
SELECT value FROM _meta WHERE key = 'schema_version';
```

## Superseded constraints (strength_log)

- `strength_log_owner_uq UNIQUE (user_id, date, exercise)` — dropped in v3.1.
  Blocked multiple sets of the same exercise per day.
- Replaced by `strength_log_set_uq UNIQUE (user_id, set_id)` — allows multi-set
  while deduplicating offline replays via client-generated UUIDs.

## Canonical schema source

`supabase_schema.sql` is the canonical reference for what the database should
look like. `setup_supabase.py` reads from its own embedded SQL (kept in sync).

## Historical scripts (this directory)

Legacy one-time migration scripts from the Google Sheets era. Not part of the
active Supabase migration path.
