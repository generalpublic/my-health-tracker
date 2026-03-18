"""POST /api/log — Write confirmed nutrition/workout data to Google Sheets."""

from http.server import BaseHTTPRequestHandler

from _shared import (
    authenticate, json_response, read_body, get_workbook, date_to_day, today_str,
    NUTRITION_HEADERS, STRENGTH_LOG_HEADERS,
    MEAL_TYPE_COLS, COL_TOTAL_CONSUMED, COL_PROTEIN, COL_CARBS, COL_FATS, COL_NOTES,
)


def _safe_float(val):
    """Convert a cell value to float, treating empty/non-numeric as 0."""
    if not val or val == "":
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _log_nutrition(wb, body):
    """Write nutrition data to the Nutrition tab with accumulation logic.

    Critical: this must ACCUMULATE, not overwrite.
    - Meal description appends with ' + ' separator if cell already has content
    - Macro totals (calories, protein, carbs, fat) are ADDED to existing values
    - Auto columns A-E are never touched (garmin_sync owns those)
    """
    date_str = body.get("date", today_str())
    meal_type = body.get("meal_type", "Snacks")
    meal_desc = body.get("meal_description", "")
    calories = body.get("calories", 0)
    protein = body.get("protein", 0)
    carbs = body.get("carbs", 0)
    fat = body.get("fat", 0)
    notes = body.get("notes", "")

    # Validate meal_type
    if meal_type not in MEAL_TYPE_COLS:
        return 400, {"error": f"Invalid meal_type: {meal_type}. Must be Breakfast/Lunch/Dinner/Snacks"}

    meal_col = MEAL_TYPE_COLS[meal_type]  # 0-based index

    # Open sheet
    try:
        sheet = wb.worksheet("Nutrition")
    except Exception:
        sheet = wb.add_worksheet(title="Nutrition", rows=1000, cols=len(NUTRITION_HEADERS))
        sheet.update(range_name="A1", values=[NUTRITION_HEADERS])

    # Find existing row for this date
    all_dates = sheet.col_values(2)  # Date column (B)
    row_index = None
    if date_str in all_dates:
        row_index = all_dates.index(date_str) + 1

    if row_index:
        # UPDATE existing row — accumulate macros, append meal description
        existing = sheet.row_values(row_index)

        def _get(i):
            return existing[i] if len(existing) > i else ""

        # Accumulate meal description
        current_meal = _get(meal_col)
        if current_meal:
            new_meal = f"{current_meal} + {meal_desc}"
        else:
            new_meal = meal_desc

        # Accumulate macros
        new_consumed = _safe_float(_get(COL_TOTAL_CONSUMED)) + calories
        new_protein = _safe_float(_get(COL_PROTEIN)) + protein
        new_carbs = _safe_float(_get(COL_CARBS)) + carbs
        new_fats = _safe_float(_get(COL_FATS)) + fat

        # Preserve everything garmin_sync wrote (A-E) and other manual cols
        row = [
            _get(0),             # A Day (preserve)
            _get(1),             # B Date (preserve)
            _get(2),             # C Total Cal Burned (preserve — garmin_sync)
            _get(3),             # D Active Cal Burned (preserve — garmin_sync)
            _get(4),             # E BMR Calories (preserve — garmin_sync)
            _get(5),             # F Breakfast
            _get(6),             # G Lunch
            _get(7),             # H Dinner
            _get(8),             # I Snacks
            new_consumed,        # J Total Consumed (accumulated)
            new_protein,         # K Protein (accumulated)
            new_carbs,           # L Carbs (accumulated)
            new_fats,            # M Fats (accumulated)
            _get(13),            # N Water (preserve)
            f'=IF(J{row_index}<>"",J{row_index}-C{row_index},"")',  # O Balance formula
            _get(COL_NOTES),     # P Notes (preserve)
        ]

        # Overwrite only the meal column we're updating
        row[meal_col] = new_meal

        # Append notes if provided
        if notes:
            existing_notes = _get(COL_NOTES)
            row[COL_NOTES] = f"{existing_notes}; {notes}" if existing_notes else notes

        sheet.update(
            range_name=f"A{row_index}",
            values=[row],
            value_input_option="USER_ENTERED",
        )

        return 200, {
            "message": f"Updated {meal_type} for {date_str}",
            "row_index": row_index,
            "totals": {
                "calories": new_consumed,
                "protein": new_protein,
                "carbs": new_carbs,
                "fat": new_fats,
            },
        }

    else:
        # INSERT new row — garmin_sync hasn't created this date yet
        day_str = date_to_day(date_str)
        row = [
            day_str,     # A Day
            date_str,    # B Date
            "",          # C Total Cal Burned (garmin_sync fills later)
            "",          # D Active Cal Burned
            "",          # E BMR Calories
            "",          # F Breakfast
            "",          # G Lunch
            "",          # H Dinner
            "",          # I Snacks
            calories,    # J Total Consumed
            protein,     # K Protein
            carbs,       # L Carbs
            fat,         # M Fats
            "",          # N Water
            "",          # O Balance (formula added after append)
            notes,       # P Notes
        ]

        # Set the specific meal column
        row[meal_col] = meal_desc

        sheet.append_row(row, value_input_option="USER_ENTERED")

        # Add the balance formula
        new_row_index = len(sheet.col_values(2))
        formula = f'=IF(J{new_row_index}<>"",J{new_row_index}-C{new_row_index},"")'
        sheet.update(
            range_name=f"O{new_row_index}",
            values=[[formula]],
            value_input_option="USER_ENTERED",
        )

        return 200, {
            "message": f"Logged {meal_type} for {date_str} (new row)",
            "row_index": new_row_index,
            "totals": {
                "calories": calories,
                "protein": protein,
                "carbs": carbs,
                "fat": fat,
            },
        }


def _log_workout(wb, body):
    """Write workout data to the Strength Log tab.

    Each set is appended as a separate row. No upsert/dedup — multiple
    entries for the same exercise are valid (different sets).
    """
    date_str = body.get("date", today_str())
    exercises = body.get("exercises", [])
    session_notes = body.get("session_notes", "")

    if not exercises:
        return 400, {"error": "No exercises to log"}

    # Open sheet
    try:
        sheet = wb.worksheet("Strength Log")
    except Exception:
        sheet = wb.add_worksheet(title="Strength Log", rows=1000, cols=len(STRENGTH_LOG_HEADERS))
        sheet.update(range_name="A1", values=[STRENGTH_LOG_HEADERS])

    day_str = date_to_day(date_str)
    rows = []

    for i, ex in enumerate(exercises):
        # Session notes go on the first set only
        notes = ex.get("notes", "")
        if i == 0 and session_notes:
            notes = f"{session_notes}; {notes}" if notes else session_notes

        rows.append([
            day_str,
            date_str,
            ex.get("muscle_group", ""),
            ex.get("exercise", ""),
            ex.get("weight_lbs", ""),
            ex.get("reps", ""),
            ex.get("rpe", ""),
            notes,
        ])

    # Append all rows at once (batch write)
    sheet.append_rows(rows, value_input_option="RAW")

    return 200, {
        "message": f"Logged {len(rows)} sets for {date_str}",
        "sets_logged": len(rows),
    }


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        json_response(self, 204, "")

    def do_POST(self):
        # Authenticate
        success, msg, session_id = authenticate(self.headers)
        if not success:
            json_response(self, 401, {"error": msg})
            return

        body = read_body(self)
        mode = body.get("mode", "")

        if mode not in ("nutrition", "workout"):
            json_response(self, 400, {"error": "Mode must be 'nutrition' or 'workout'"})
            return

        try:
            wb = get_workbook()
        except Exception as e:
            json_response(self, 500, {"error": f"Could not open Google Sheet: {str(e)}"})
            return

        if mode == "nutrition":
            status, result = _log_nutrition(wb, body)
        else:
            status, result = _log_workout(wb, body)

        json_response(self, status, result)

    def log_message(self, format, *args):
        pass
