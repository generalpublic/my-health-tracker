"""
schema.py -- Centralized column definitions for all Google Sheets tabs.

All header lists, column indices, manual-entry column lists, and tab name
constants live here. Every script imports from this file instead of
defining its own copy.
"""

# --- Tab names ---
TAB_GARMIN = "Garmin"
TAB_SLEEP = "Sleep"
TAB_NUTRITION = "Nutrition"
TAB_SESSION_LOG = "Session Log"
TAB_DAILY_LOG = "Daily Log"
TAB_OVERALL_ANALYSIS = "Overall Analysis"
TAB_STRENGTH_LOG = "Strength Log"
TAB_ARCHIVE = "Raw Data Archive"

# --- Color constants ---
YELLOW = {"red": 1.0, "green": 1.0, "blue": 0.8}   # light yellow for manual-entry cells

# --- Garmin tab ---
HEADERS = [
    "Day",                           # A
    "Date",                          # B
    "Sleep Score",                   # C
    "HRV (overnight avg)",           # D
    "HRV 7-day avg",                 # E
    "Resting HR",                    # F
    "Sleep Duration (hrs)",          # G
    "Body Battery",                  # H
    "Steps",                         # I
    # Daily wellness
    "Total Calories Burned",         # J
    "Active Calories Burned",        # K
    "BMR Calories",                  # L
    "Avg Stress Level",              # M
    "Stress Qualifier",              # N
    "Floors Ascended",               # O
    "Moderate Intensity Min",        # P
    "Vigorous Intensity Min",        # Q
    "Body Battery at Wake",          # R
    "Body Battery High",             # S
    "Body Battery Low",              # T
    # Activity
    "Activity Name",                 # U
    "Activity Type",                 # V
    "Start Time",                    # W
    "Distance (mi)",                 # X
    "Duration (min)",                # Y
    "Avg HR",                        # Z
    "Max HR",                        # AA
    "Calories",                      # AB
    "Elevation Gain (m)",            # AC
    "Avg Speed (mph)",               # AD
    "Aerobic Training Effect",       # AE
    "Anaerobic Training Effect",     # AF
    # HR Zones (time in minutes)
    "Zone 1 - Warm Up (min)",        # AG
    "Zone 2 - Easy (min)",           # AH
    "Zone 3 - Aerobic (min)",        # AI
    "Zone 4 - Threshold (min)",      # AJ
    "Zone 5 - Max (min)",            # AK
    # Pulse Ox
    "SpO2 Avg",                      # AL
    "SpO2 Min",                      # AM
]

# --- Nutrition tab ---
NUTRITION_HEADERS = [
    "Day",                           # A
    "Date",                          # B - auto
    "Total Calories Burned",         # C - auto
    "Active Calories Burned",        # D - auto
    "BMR Calories",                  # E - auto
    "Breakfast",                     # F - manual
    "Lunch",                         # G - manual
    "Dinner",                        # H - manual
    "Snacks",                        # I - manual
    "Total Calories Consumed",       # J - manual
    "Protein (g)",                   # K - manual
    "Carbs (g)",                     # L - manual
    "Fats (g)",                      # M - manual
    "Water (L)",                     # N - manual
    "Calorie Balance",               # O - auto (consumed - burned)
    "Notes",                         # P - manual
]

# --- Sleep tab ---
SLEEP_HEADERS = [
    "Day",                           # A
    "Date",                          # B
    "Garmin Sleep Score",            # C
    "Sleep Analysis Score",          # D  auto-calculated independent score
    "Total Sleep (hrs)",             # E  moved up for visibility
    "Sleep Analysis",                # F  auto-generated text
    "Notes",                         # G  manual
    "Bedtime",                       # H
    "Wake Time",                     # I
    "Bedtime Variability (7d)",      # J  7-day rolling SD in minutes
    "Wake Variability (7d)",         # K  7-day rolling SD in minutes
    "Time in Bed (hrs)",             # L
    "Deep Sleep (min)",              # M
    "Light Sleep (min)",             # N
    "REM (min)",                     # O
    "Awake During Sleep (min)",      # P
    "Deep %",                        # Q
    "REM %",                         # R
    "Sleep Cycles",                  # S
    "Awakenings",                    # T
    "Avg HR",                        # U
    "Avg Respiration",               # V
    "Overnight HRV (ms)",            # W
    "Body Battery Gained",           # X
    "Sleep Descriptor",              # Y
]

# --- Session Log tab ---
SESSION_LOG_HEADERS = [
    "Day", "Date", "Session Type", "Perceived Effort", "Post-Workout Energy (1-10)",
    "Notes", "Activity Name", "Duration (min)", "Distance (mi)", "Avg HR",
    "Max HR", "Calories", "Aerobic TE (0-5)", "Anaerobic TE (0-5)",
    "Zone 1 (min)", "Zone 2 (min)", "Zone 3 (min)", "Zone 4 (min)", "Zone 5 (min)",
    "Zone Ranges", "Source", "Elevation (m)",
]

# --- Daily Log tab ---
# Static default for backward compatibility (used when no user_config.json exists)
DAILY_LOG_HEADERS = [
    # Manual entry zone
    "Day",                            # A
    "Date",                           # B
    "Morning Energy (1-10)",          # C
    "Wake at 9:30 AM",                # D  checkbox
    "No Morning Screens",             # E  checkbox
    "Creatine & Hydrate",             # F  checkbox
    "20 Min Walk + Breathing",        # G  checkbox
    "Physical Activity",              # H  checkbox
    "No Screens Before Bed",          # I  checkbox
    "Bed at 10 PM",                   # J  checkbox
    "Habits Total (0-7)",             # K  formula
    "Midday Energy (1-10)",           # L
    "Midday Focus (1-10)",            # M  brain fog = low score
    "Midday Mood (1-10)",             # N
    "Midday Body Feel (1-10)",        # O
    "Midday Notes",                   # P  free text
    "Evening Energy (1-10)",          # Q
    "Evening Focus (1-10)",           # R
    "Evening Mood (1-10)",            # S
    "Perceived Stress (1-10)",        # T
    "Day Rating (1-10)",              # U
    "Evening Notes",                  # V  free text
]

# Subjective columns that follow habits (always the same regardless of habit count)
_DAILY_LOG_SUFFIX = [
    "Midday Energy (1-10)",
    "Midday Focus (1-10)",
    "Midday Mood (1-10)",
    "Midday Body Feel (1-10)",
    "Midday Notes",
    "Evening Energy (1-10)",
    "Evening Focus (1-10)",
    "Evening Mood (1-10)",
    "Perceived Stress (1-10)",
    "Day Rating (1-10)",
    "Evening Notes",
]


def get_daily_log_headers(config=None):
    """Build Daily Log headers with dynamic habit columns from config.

    When config is None and no user_config.json exists, returns the same
    headers as the static DAILY_LOG_HEADERS constant (backward compatible).
    """
    from utils import load_user_config, get_habit_labels
    cfg = config or load_user_config()
    habits = get_habit_labels(cfg)
    n = len(habits)
    return (
        ["Day", "Date", "Morning Energy (1-10)"]
        + habits
        + [f"Habits Total (0-{n})"]
        + _DAILY_LOG_SUFFIX
    )


def get_habit_columns(config=None):
    """Return list of habit label strings from the active config."""
    from utils import load_user_config, get_habit_labels
    cfg = config or load_user_config()
    return get_habit_labels(cfg)


def get_daily_log_manual_cols(config=None):
    """Return 0-based manual column indices for Daily Log.

    All columns from C (index 2) through the last column are manual-entry.
    """
    headers = get_daily_log_headers(config)
    return list(range(2, len(headers)))

# --- Overall Analysis tab ---
OVERALL_ANALYSIS_HEADERS = [
    "Day",                           # A
    "Date",                          # B
    "Readiness Score (1-10)",        # C
    "Readiness Label",               # D
    "Confidence",                    # E
    "Cognitive/Energy Assessment",   # F
    "Sleep Context",                 # G
    "Cognition (1-10)",              # H  manual -- next-day mental sharpness
    "Cognition Notes",               # I  manual -- optional free text
    "Key Insights",                  # J
    "Recommendations",               # K
    "Training Load Status",          # L
]

# --- Strength Log tab ---
STRENGTH_LOG_HEADERS = [
    "Day", "Date", "Muscle Group", "Exercise", "Weight (lbs)", "Reps", "RPE (1-10)", "Notes",
]

# --- Raw Data Archive ---
ARCHIVE_KEYS = [
    # Core daily
    "hrv", "hrv_7day", "resting_hr", "body_battery", "steps",
    "total_calories", "active_calories", "bmr_calories",
    "avg_stress", "stress_qualifier", "floors_ascended",
    "moderate_min", "vigorous_min",
    "bb_at_wake", "bb_high", "bb_low",
    # Sleep
    "sleep_duration", "sleep_score", "sleep_bedtime", "sleep_wake_time",
    "sleep_time_in_bed", "sleep_deep_min", "sleep_light_min", "sleep_rem_min",
    "sleep_awake_min", "sleep_deep_pct", "sleep_rem_pct", "sleep_cycles",
    "sleep_awakenings", "sleep_avg_hr", "sleep_avg_respiration",
    "sleep_body_battery_gained", "sleep_feedback",
    # Activity
    "activity_name", "activity_type", "activity_start",
    "activity_distance", "activity_duration", "activity_avg_hr", "activity_max_hr",
    "activity_calories", "activity_elevation", "activity_avg_speed",
    "aerobic_te", "anaerobic_te",
    "zone_1", "zone_2", "zone_3", "zone_4", "zone_5",
]
ARCHIVE_HEADERS = ["Day", "Date"] + ARCHIVE_KEYS

# --- Manual-entry column indices (0-based) for yellow highlighting ---
NUTRITION_MANUAL_COLS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 15]   # F,G,H,I,J,K,L,M,N,P
SESSION_MANUAL_COLS = [3, 4, 5]                                  # D,E,F
SLEEP_MANUAL_COLS = [6]                                          # G (Notes)
DAILY_LOG_MANUAL_COLS = list(range(2, 22))                       # C-V (default 7 habits, use get_daily_log_manual_cols() for dynamic)

# --- Session Log column indices (0-based) ---
SL_EFFORT = 3    # D  Perceived Effort (manual)
SL_ENERGY = 4    # E  Post-Workout Energy (manual)
SL_NOTES = 5     # F  Notes (manual)
SL_ACTIVITY = 6  # G  Activity Name (auto)

# --- All tabs with expected headers (for verify_sheets.py) ---
def get_expected_headers():
    """Return expected headers dict with dynamic Daily Log headers."""
    return {
        TAB_GARMIN:            HEADERS,
        TAB_SLEEP:             SLEEP_HEADERS,
        TAB_NUTRITION:         NUTRITION_HEADERS,
        TAB_SESSION_LOG:       SESSION_LOG_HEADERS,
        TAB_DAILY_LOG:         get_daily_log_headers(),
        TAB_OVERALL_ANALYSIS:  OVERALL_ANALYSIS_HEADERS,
    }

# Static version for backward compatibility (uses default 7 habits)
EXPECTED_HEADERS = {
    TAB_GARMIN:            HEADERS,
    TAB_SLEEP:             SLEEP_HEADERS,
    TAB_NUTRITION:         NUTRITION_HEADERS,
    TAB_SESSION_LOG:       SESSION_LOG_HEADERS,
    TAB_DAILY_LOG:         DAILY_LOG_HEADERS,
    TAB_OVERALL_ANALYSIS:  OVERALL_ANALYSIS_HEADERS,
}
