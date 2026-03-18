"""POST /api/parse — Parse natural language food/workout descriptions via Claude Haiku."""

from http.server import BaseHTTPRequestHandler
import json
import requests
from datetime import datetime, timezone, timedelta

# Vercel resolves relative imports from the api/ directory
from _shared import authenticate, json_response, read_body, ANTHROPIC_API_KEY

# US Eastern timezone (UTC-5 / UTC-4 DST)
ET = timezone(timedelta(hours=-5))

NUTRITION_PROMPT = """You are a nutrition logging assistant. Parse the user's food description into structured data.

Current time: {current_time}

Rules:
- Determine meal_type from context and time of day:
  - Before 11 AM or user says "breakfast" -> "Breakfast"
  - 11 AM - 2 PM or user says "lunch" -> "Lunch"
  - 5 PM - 9 PM or user says "dinner" -> "Dinner"
  - Otherwise or user says "snack" -> "Snacks"
  - User's explicit keyword always overrides time-of-day inference
- Build a single natural language query string for Nutritionix that describes the FULL meal
  - If user mentions a restaurant, prefix each item with the restaurant name
  - Include quantities and specific ingredients/toppings
  - Example: "1 Chipotle chicken burrito with brown rice, fajita veggies, pinto beans, pico de gallo, corn salsa, cheese, lettuce"
- Write a brief human-readable meal_description for the spreadsheet cell (keep it under 80 chars)

Return ONLY valid JSON (no markdown, no explanation):
{{
  "meal_type": "Breakfast" | "Lunch" | "Dinner" | "Snacks",
  "meal_description": "brief summary for spreadsheet cell",
  "nutritionix_query": "full natural language query for Nutritionix API",
  "restaurant": "restaurant name or null if homemade/unknown",
  "notes": "any extra context the user mentioned (mood, feelings, etc.) or empty string"
}}

User said: {text}"""

WORKOUT_PROMPT = """You are a strength training logging assistant. Parse the user's workout description into structured exercise sets.

Rules:
- Each set becomes a separate entry
- Determine muscle_group from exercise name:
  - Bench Press, Push-ups, Chest Fly -> "Chest"
  - Rows, Pull-ups, Lat Pulldown -> "Back"
  - Overhead Press, Lateral Raise -> "Shoulders"
  - Curls, Tricep Extension, Dips -> "Arms"
  - Squats, Deadlift, Leg Press, Lunges -> "Legs"
  - Planks, Crunches, Ab Wheel -> "Core"
  - Burpees, Clean and Jerk -> "Full Body"
- Standardize exercise names (e.g., "bench" -> "Bench Press", "squats" -> "Barbell Squat")
- If user mentions "warm-up" or "warm up", set RPE to 3-4 for those sets
- For non-warmup sets, estimate RPE based on context:
  - Light/easy -> 5-6
  - Moderate/normal -> 7
  - Hard/heavy/grinding -> 8-9
  - Max effort/failure -> 10
- If user says "X sets of Y reps at Z lbs", expand into individual set entries
- Extract overall session notes (mood, energy, feelings) separately from per-set notes

Return ONLY valid JSON (no markdown, no explanation):
{{
  "exercises": [
    {{
      "muscle_group": "Chest",
      "exercise": "Bench Press",
      "weight_lbs": 20,
      "reps": 20,
      "rpe": 3,
      "notes": "warm-up"
    }}
  ],
  "session_notes": "overall mood/energy notes or empty string"
}}

User said: {text}"""


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        json_response(self, 204, "")

    def do_POST(self):
        # Authenticate
        success, msg, session_id = authenticate(self.headers)
        if not success:
            json_response(self, 401, {"error": msg})
            return

        # Parse request
        body = read_body(self)
        text = body.get("text", "").strip()
        mode = body.get("mode", "").strip()

        if not text:
            json_response(self, 400, {"error": "Missing 'text' field"})
            return
        if mode not in ("nutrition", "workout"):
            json_response(self, 400, {"error": "Mode must be 'nutrition' or 'workout'"})
            return

        if not ANTHROPIC_API_KEY:
            json_response(self, 500, {"error": "ANTHROPIC_API_KEY not configured"})
            return

        # Build prompt
        if mode == "nutrition":
            now_et = datetime.now(ET)
            current_time = now_et.strftime("%I:%M %p ET")
            prompt = NUTRITION_PROMPT.format(current_time=current_time, text=text)
        else:
            prompt = WORKOUT_PROMPT.format(text=text)

        # Call Claude Haiku via raw HTTP
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20241022",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            json_response(self, 502, {"error": f"Claude API error: {str(e)}"})
            return

        # Extract Claude's response text
        result = resp.json()
        content = result.get("content", [{}])
        raw_text = content[0].get("text", "") if content else ""

        # Parse JSON from Claude's response
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re
            match = re.search(r'\{[\s\S]*\}', raw_text)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    json_response(self, 502, {
                        "error": "Could not parse Claude response as JSON",
                        "raw": raw_text,
                    })
                    return
            else:
                json_response(self, 502, {
                    "error": "Could not parse Claude response as JSON",
                    "raw": raw_text,
                })
                return

        # Build confirmation text for the user
        if mode == "nutrition":
            meal = parsed.get("meal_type", "Meal")
            desc = parsed.get("meal_description", "")
            restaurant = parsed.get("restaurant", "")
            at = f" at {restaurant}" if restaurant else ""
            confirmation = f"{meal}{at}: {desc}"
        else:
            exercises = parsed.get("exercises", [])
            sets = len(exercises)
            names = list(dict.fromkeys(e.get("exercise", "") for e in exercises))
            confirmation = f"{sets} sets: {', '.join(names)}"
            notes = parsed.get("session_notes", "")
            if notes:
                confirmation += f" | {notes}"

        parsed["_confirmation"] = confirmation
        parsed["_mode"] = mode

        json_response(self, 200, parsed)

    def log_message(self, format, *args):
        pass  # Suppress default logging in Vercel
