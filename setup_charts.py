"""
setup_charts.py — Create embedded Google Sheets charts in the Charts tab.

Uses schema-based column lookups so charts stay correct when columns move.
Idempotent — deletes and recreates all charts on every run.

Usage:
    python setup_charts.py
"""
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
import os

from schema import HEADERS, SLEEP_HEADERS, OVERALL_ANALYSIS_HEADERS

load_dotenv(Path(__file__).parent / ".env")

SHEET_ID      = os.getenv("SHEET_ID")
JSON_KEY_FILE = str(Path(__file__).parent / os.getenv("JSON_KEY_FILE"))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def _col(headers, name):
    """Resolve column index by header name. Fails loudly if missing."""
    return headers.index(name)


def get_sheet_ids(service):
    result = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    ids = {}
    for s in result["sheets"]:
        ids[s["properties"]["title"]] = s["properties"]["sheetId"]
    return ids


def add_chart(charts_sheet_id, title, series_col_indices, x_col_index,
              source_sheet_id, anchor_row=0, anchor_col=0, end_row=1000,
              chart_type="LINE"):
    """Build an addChart request for the Charts sheet."""
    series = []
    for col in series_col_indices:
        series.append({
            "series": {
                "sourceRange": {
                    "sources": [{
                        "sheetId": source_sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": end_row,
                        "startColumnIndex": col,
                        "endColumnIndex": col + 1
                    }]
                }
            },
            "targetAxis": "LEFT_AXIS"
        })

    return {
        "addChart": {
            "chart": {
                "spec": {
                    "title": title,
                    "basicChart": {
                        "chartType": chart_type,
                        "legendPosition": "BOTTOM_LEGEND",
                        "axis": [
                            {"position": "BOTTOM_AXIS", "title": "Date"},
                            {"position": "LEFT_AXIS", "title": "Value"}
                        ],
                        "domains": [{
                            "domain": {
                                "sourceRange": {
                                    "sources": [{
                                        "sheetId": source_sheet_id,
                                        "startRowIndex": 1,
                                        "endRowIndex": end_row,
                                        "startColumnIndex": x_col_index,
                                        "endColumnIndex": x_col_index + 1
                                    }]
                                }
                            }
                        }],
                        "series": series,
                        "headerCount": 0
                    }
                },
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": charts_sheet_id,
                            "rowIndex": anchor_row,
                            "columnIndex": anchor_col
                        }
                    }
                }
            }
        }
    }


def delete_existing_charts(service, charts_sheet_id):
    """Delete all charts currently on the Charts sheet."""
    result = service.spreadsheets().get(
        spreadsheetId=SHEET_ID,
        includeGridData=False
    ).execute()

    delete_requests = []
    for sheet in result["sheets"]:
        if sheet["properties"]["sheetId"] == charts_sheet_id:
            for chart in sheet.get("charts", []):
                delete_requests.append({
                    "deleteEmbeddedObject": {
                        "objectId": chart["chartId"]
                    }
                })

    if delete_requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"requests": delete_requests}
        ).execute()
        print(f"  Deleted {len(delete_requests)} existing chart(s).")


def main():
    creds = Credentials.from_service_account_file(JSON_KEY_FILE, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)

    sheet_ids = get_sheet_ids(service)

    # Resolve source tab IDs
    garmin_id = sheet_ids.get("Garmin")
    sleep_id  = sheet_ids.get("Sleep")
    oa_id     = sheet_ids.get("Overall Analysis")

    if garmin_id is None:
        print("ERROR: Garmin tab not found.")
        return

    # Create Charts tab if it doesn't exist
    if "Charts" not in sheet_ids:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": "Charts"}}}]}
        ).execute()
        sheet_ids = get_sheet_ids(service)
        print("  Charts tab created.")

    charts_id = sheet_ids["Charts"]

    # Remove any previously created charts before recreating
    delete_existing_charts(service, charts_id)

    # --- Resolve column indices from schema (never hardcode) ---
    g_date    = _col(HEADERS, "Date")
    g_hrv_on  = _col(HEADERS, "HRV (overnight avg)")
    g_hrv_7d  = _col(HEADERS, "HRV 7-day avg")
    g_sleep_s = _col(HEADERS, "Sleep Score")
    g_sleep_d = _col(HEADERS, "Sleep Duration (hrs)")
    g_bb      = _col(HEADERS, "Body Battery")
    g_steps   = _col(HEADERS, "Steps")

    s_date    = _col(SLEEP_HEADERS, "Date")
    s_score   = _col(SLEEP_HEADERS, "Sleep Analysis Score")
    s_deep    = _col(SLEEP_HEADERS, "Deep Sleep (min)")
    s_light   = _col(SLEEP_HEADERS, "Light Sleep (min)")
    s_rem     = _col(SLEEP_HEADERS, "REM (min)")
    s_bed_var = _col(SLEEP_HEADERS, "Bedtime Variability (7d)")
    s_wk_var  = _col(SLEEP_HEADERS, "Wake Variability (7d)")

    requests = []

    # === Row 0: HRV charts ===
    # Chart 1: HRV 7-Day Average
    requests.append(add_chart(
        charts_id, "HRV 7-Day Average",
        [g_hrv_7d], g_date, garmin_id,
        anchor_row=0, anchor_col=0
    ))
    # Chart 2: HRV Overnight vs 7-Day Avg
    requests.append(add_chart(
        charts_id, "HRV: Overnight vs 7-Day Avg",
        [g_hrv_on, g_hrv_7d], g_date, garmin_id,
        anchor_row=0, anchor_col=6
    ))

    # === Row 20: Sleep + Body Battery ===
    # Chart 3: Sleep Quality (Score + Duration from Garmin tab)
    requests.append(add_chart(
        charts_id, "Sleep Quality",
        [g_sleep_s, g_sleep_d], g_date, garmin_id,
        anchor_row=20, anchor_col=0
    ))
    # Chart 4: Body Battery
    requests.append(add_chart(
        charts_id, "Body Battery",
        [g_bb], g_date, garmin_id,
        anchor_row=20, anchor_col=6
    ))

    # === Row 40: Steps + Sleep Analysis Score ===
    # Chart 5: Daily Steps
    requests.append(add_chart(
        charts_id, "Daily Steps",
        [g_steps], g_date, garmin_id,
        anchor_row=40, anchor_col=0
    ))
    # Chart 6: Sleep Analysis Score Trend (from Sleep tab)
    if sleep_id:
        requests.append(add_chart(
            charts_id, "Sleep Analysis Score",
            [s_score], s_date, sleep_id,
            anchor_row=40, anchor_col=6
        ))

    # === Row 60: Sleep Stages + Bedtime Consistency ===
    if sleep_id:
        # Chart 7: Sleep Stage Breakdown (Deep/Light/REM)
        requests.append(add_chart(
            charts_id, "Sleep Stages (min)",
            [s_deep, s_light, s_rem], s_date, sleep_id,
            anchor_row=60, anchor_col=0
        ))
        # Chart 8: Bedtime Consistency (Variability)
        requests.append(add_chart(
            charts_id, "Bedtime & Wake Consistency",
            [s_bed_var, s_wk_var], s_date, sleep_id,
            anchor_row=60, anchor_col=6
        ))

    # === Row 80: Readiness Trend ===
    if oa_id:
        oa_date  = _col(OVERALL_ANALYSIS_HEADERS, "Date")
        oa_score = _col(OVERALL_ANALYSIS_HEADERS, "Readiness Score (1-10)")
        # Chart 9: Readiness Score Trend
        requests.append(add_chart(
            charts_id, "Readiness Score Trend",
            [oa_score], oa_date, oa_id,
            anchor_row=80, anchor_col=0
        ))

    service.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": requests}
    ).execute()

    print(f"Done! {len(requests)} charts created in the Charts tab:")
    print("  1. HRV 7-Day Average")
    print("  2. HRV: Overnight vs 7-Day Avg")
    print("  3. Sleep Quality (Score + Duration)")
    print("  4. Body Battery")
    print("  5. Daily Steps")
    if sleep_id:
        print("  6. Sleep Analysis Score")
        print("  7. Sleep Stages (Deep/Light/REM)")
        print("  8. Bedtime & Wake Consistency")
    if oa_id:
        print("  9. Readiness Score Trend")


if __name__ == "__main__":
    main()
