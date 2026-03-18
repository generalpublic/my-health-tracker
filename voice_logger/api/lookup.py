"""POST /api/lookup — Look up nutrition facts via Nutritionix API."""

from http.server import BaseHTTPRequestHandler
import requests

from _shared import (
    authenticate, json_response, read_body,
    NUTRITIONIX_APP_ID, NUTRITIONIX_APP_KEY,
)

NUTRITIONIX_URL = "https://trackapi.nutritionix.com/v2/natural/nutrients"


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
        if body is None:
            json_response(self, 400, {"error": "Invalid JSON"})
            return
        query = body.get("nutritionix_query", "").strip()

        if not query:
            json_response(self, 400, {"error": "Missing 'nutritionix_query' field"})
            return

        if not NUTRITIONIX_APP_ID or not NUTRITIONIX_APP_KEY:
            json_response(self, 500, {"error": "Nutritionix API credentials not configured"})
            return

        # Call Nutritionix natural language API
        # This handles multi-item queries like "1 chicken burrito and 1 side of chips"
        try:
            resp = requests.post(
                NUTRITIONIX_URL,
                headers={
                    "x-app-id": NUTRITIONIX_APP_ID,
                    "x-app-key": NUTRITIONIX_APP_KEY,
                    "Content-Type": "application/json",
                },
                json={"query": query},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            json_response(self, 502, {
                "error": f"Nutritionix API error: {str(e)}",
                "fallback": True,
            })
            return

        data = resp.json()
        foods = data.get("foods", [])

        if not foods:
            json_response(self, 404, {
                "error": "Nutritionix could not identify any foods in your query",
                "query": query,
                "fallback": True,
            })
            return

        # Extract per-item nutrition
        items = []
        total_cal = 0
        total_protein = 0
        total_carbs = 0
        total_fat = 0

        for food in foods:
            cal = round(food.get("nf_calories", 0) or 0)
            protein = round(food.get("nf_protein", 0) or 0, 1)
            carbs = round(food.get("nf_total_carbohydrate", 0) or 0, 1)
            fat = round(food.get("nf_total_fat", 0) or 0, 1)

            items.append({
                "name": food.get("food_name", "Unknown"),
                "serving_qty": food.get("serving_qty", 1),
                "serving_unit": food.get("serving_unit", "serving"),
                "calories": cal,
                "protein": protein,
                "carbs": carbs,
                "fat": fat,
            })

            total_cal += cal
            total_protein += protein
            total_carbs += carbs
            total_fat += fat

        json_response(self, 200, {
            "items": items,
            "totals": {
                "calories": round(total_cal),
                "protein": round(total_protein, 1),
                "carbs": round(total_carbs, 1),
                "fat": round(total_fat, 1),
            },
        })

    def log_message(self, format, *args):
        pass
