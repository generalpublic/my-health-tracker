-- =============================================================================
-- Supabase RPC Functions — Dashboard Query Consolidation
-- Run this in Supabase SQL Editor (Dashboard > SQL Editor > New query)
--
-- Consolidates 14 HTTP round-trips into 2 RPC calls:
--   1. get_dashboard_today(target_date) — replaces 8 per-table queries
--   2. get_dashboard_history(start_date, recent_sessions_limit) — replaces 6 queries
--
-- Both use SECURITY INVOKER so RLS policies apply automatically.
-- =============================================================================

-- ---------- get_dashboard_today ----------
-- Returns all data for a single date as a JSON object.
-- Keys: garmin, sleep, overall_analysis, daily_log, session_log, nutrition,
--       strength_log, illness_state

CREATE OR REPLACE FUNCTION get_dashboard_today(target_date TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
STABLE
AS $$
BEGIN
  RETURN jsonb_build_object(
    'garmin', (
      SELECT row_to_json(t)::jsonb FROM (
        SELECT * FROM garmin WHERE date = target_date AND user_id = auth.uid() LIMIT 1
      ) t
    ),
    'sleep', (
      SELECT row_to_json(t)::jsonb FROM (
        SELECT * FROM sleep WHERE date = target_date AND user_id = auth.uid() LIMIT 1
      ) t
    ),
    'overall_analysis', (
      SELECT row_to_json(t)::jsonb FROM (
        SELECT * FROM overall_analysis WHERE date = target_date AND user_id = auth.uid() LIMIT 1
      ) t
    ),
    'daily_log', (
      SELECT row_to_json(t)::jsonb FROM (
        SELECT * FROM daily_log WHERE date = target_date AND user_id = auth.uid() LIMIT 1
      ) t
    ),
    'session_log', COALESCE((
      SELECT jsonb_agg(row_to_json(t)::jsonb ORDER BY t.activity_name) FROM (
        SELECT * FROM session_log WHERE date = target_date AND user_id = auth.uid()
      ) t
    ), '[]'::jsonb),
    'nutrition', (
      SELECT row_to_json(t)::jsonb FROM (
        SELECT * FROM nutrition WHERE date = target_date AND user_id = auth.uid() LIMIT 1
      ) t
    ),
    'strength_log', COALESCE((
      SELECT jsonb_agg(row_to_json(t)::jsonb ORDER BY t.id) FROM (
        SELECT * FROM strength_log WHERE date = target_date AND user_id = auth.uid()
      ) t
    ), '[]'::jsonb),
    'illness_state', (
      SELECT row_to_json(t)::jsonb FROM (
        SELECT * FROM illness_state
        WHERE user_id = auth.uid() AND resolved_date IS NULL
        ORDER BY onset_date DESC LIMIT 1
      ) t
    )
  );
END;
$$;


-- ---------- get_dashboard_history ----------
-- Returns history data for charts/trends plus recent sessions.
-- Only fetches the columns needed for rendering (not full rows).

CREATE OR REPLACE FUNCTION get_dashboard_history(
  start_date TEXT,
  recent_sessions_limit INT DEFAULT 5
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
STABLE
AS $$
BEGIN
  RETURN jsonb_build_object(
    'garmin', COALESCE((
      SELECT jsonb_agg(row_to_json(t)::jsonb) FROM (
        SELECT date, body_battery, steps, avg_stress_level, resting_hr, hrv_overnight_avg
        FROM garmin
        WHERE date >= start_date AND user_id = auth.uid()
        ORDER BY date ASC
      ) t
    ), '[]'::jsonb),
    'sleep', COALESCE((
      SELECT jsonb_agg(row_to_json(t)::jsonb) FROM (
        SELECT date, sleep_analysis_score, total_sleep_hrs, overnight_hrv_ms
        FROM sleep
        WHERE date >= start_date AND user_id = auth.uid()
        ORDER BY date ASC
      ) t
    ), '[]'::jsonb),
    'overall_analysis', COALESCE((
      SELECT jsonb_agg(row_to_json(t)::jsonb) FROM (
        SELECT date, readiness_score, cognition
        FROM overall_analysis
        WHERE date >= start_date AND user_id = auth.uid()
        ORDER BY date ASC
      ) t
    ), '[]'::jsonb),
    'daily_log', COALESCE((
      SELECT jsonb_agg(row_to_json(t)::jsonb) FROM (
        SELECT date, habits_total, day_rating, morning_energy
        FROM daily_log
        WHERE date >= start_date AND user_id = auth.uid()
        ORDER BY date ASC
      ) t
    ), '[]'::jsonb),
    'session_log', COALESCE((
      SELECT jsonb_agg(row_to_json(t)::jsonb) FROM (
        SELECT date, activity_name, session_type, duration_min, distance_mi, calories, avg_hr, max_hr
        FROM session_log
        WHERE date >= start_date AND user_id = auth.uid()
        ORDER BY date ASC
      ) t
    ), '[]'::jsonb),
    'recent_sessions', COALESCE((
      SELECT jsonb_agg(row_to_json(t)::jsonb) FROM (
        SELECT date, activity_name, session_type, duration_min, distance_mi, calories, avg_hr
        FROM session_log
        WHERE user_id = auth.uid()
        ORDER BY date DESC
        LIMIT recent_sessions_limit
      ) t
    ), '[]'::jsonb)
  );
END;
$$;
