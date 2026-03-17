from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")

SHEET_ID      = os.getenv("SHEET_ID")
JSON_KEY_FILE = str(Path(__file__).parent / os.getenv("JSON_KEY_FILE"))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_sheet_ids(service):
    result = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    ids = {}
    for s in result["sheets"]:
        ids[s["properties"]["title"]] = s["properties"]["sheetId"]
    return ids

def add_chart(sheet_id, title, series_col_indices, x_col_index, source_sheet_id, anchor_row=0, anchor_col=0, end_row=1000):
    """Add a line chart to the Charts sheet."""
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

    chart = {
        "addChart": {
            "chart": {
                "spec": {
                    "title": title,
                    "basicChart": {
                        "chartType": "LINE",
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
                            "sheetId": sheet_id,
                            "rowIndex": anchor_row,
                            "columnIndex": anchor_col
                        }
                    }
                }
            }
        }
    }
    return chart

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
    garmin_id = sheet_ids.get("Garmin")

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

    requests = [
        # Chart 1: HRV 7-day average — row 0, left column
        add_chart(charts_id, "HRV 7-Day Average", [3], 0, garmin_id, anchor_row=0, anchor_col=0),

        # Chart 2: HRV overnight vs 7-day avg — row 0, right column
        add_chart(charts_id, "HRV: Overnight vs 7-Day Avg", [2, 3], 0, garmin_id, anchor_row=0, anchor_col=6),

        # Chart 3: Sleep quality — row 20, left column
        add_chart(charts_id, "Sleep Quality", [5, 1], 0, garmin_id, anchor_row=20, anchor_col=0),

        # Chart 4: Body Battery — row 20, right column (col 6)
        add_chart(charts_id, "Body Battery", [6], 0, garmin_id, anchor_row=20, anchor_col=6),

        # Chart 5: Daily Steps — row 40, left column
        add_chart(charts_id, "Daily Steps", [7], 0, garmin_id, anchor_row=40, anchor_col=0),
    ]

    service.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": requests}
    ).execute()

    print("Done! 5 charts created in the Charts tab:")
    print("  1. HRV 7-Day Average (primary trend)")
    print("  2. HRV: Overnight vs 7-Day Avg (comparison)")
    print("  3. Sleep Quality (duration + score)")
    print("  4. Body Battery")
    print("  5. Daily Steps")

if __name__ == "__main__":
    main()
