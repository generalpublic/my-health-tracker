"""
setup_analysis.py — Create and configure the Analysis tab in Google Sheets.

Populates the Analysis tab with live formulas for habit tracking analysis,
correlating Daily Log habits with Garmin health metrics.

Usage:
    python setup_analysis.py
"""

from garmin_sync import get_workbook


def setup_analysis_tab(wb):
    try:
        sheet = wb.worksheet("Analysis")
        sheet.clear()
        print("  Analysis tab cleared and rebuilding.")
    except Exception:
        sheet = wb.add_worksheet(title="Analysis", rows=100, cols=6)
        print("  Analysis tab created.")

    # Section: Overall Averages
    # Garmin cols shifted +1: B=Date, C=Sleep Score, D=HRV, E=HRV 7d, F=Resting HR, G=Sleep Dur, I=Steps
    sheet.update("A1", [["OVERALL AVERAGES"]])
    sheet.update("A2", [
        ["Metric", "Value"],
        ["Avg Sleep Score", '=IFERROR(AVERAGE(Garmin!C2:C1000),"No data yet")'],
        ["Avg HRV (overnight)", '=IFERROR(AVERAGE(Garmin!D2:D1000),"No data yet")'],
        ["Avg HRV 7-day", '=IFERROR(AVERAGE(Garmin!E2:E1000),"No data yet")'],
        ["Avg Resting HR", '=IFERROR(AVERAGE(Garmin!F2:F1000),"No data yet")'],
        ["Avg Sleep Duration (hrs)", '=IFERROR(AVERAGE(Garmin!G2:G1000),"No data yet")'],
        ["Avg Steps", '=IFERROR(AVERAGE(Garmin!I2:I1000),"No data yet")'],
    ])

    # Section: HRV Extremes
    sheet.update("A11", [["HRV EXTREMES"]])
    sheet.update("A12", [
        ["Metric", "Value"],
        ["Best HRV night", '=IFERROR(MAX(Garmin!D2:D1000),"No data yet")'],
        ["Worst HRV night", '=IFERROR(MIN(Garmin!D2:D1000),"No data yet")'],
        ["Best sleep (hrs)", '=IFERROR(MAX(Garmin!G2:G1000),"No data yet")'],
        ["Worst sleep (hrs)", '=IFERROR(MIN(Garmin!G2:G1000),"No data yet")'],
    ])

    # Section: Habit Averages
    # Daily Log cols shifted +1: A=Day, B=Date, C=Morning Energy, D=Wake 9:30, E=No Screens,
    # F=Creatine, G=Walk, H=Physical Activity, I=No Screens Bed, J=Bed 10PM, K=Habits Total
    sheet.update("A19", [["HABIT COMPLETION"]])
    sheet.update("A20", [
        ["Metric", "Value"],
        ["Avg habits completed per day", '=IFERROR(AVERAGE(\'Daily Log\'!K2:K1000),"No data yet")'],
        ["Days with all 7 habits", '=IFERROR(COUNTIF(\'Daily Log\'!K2:K1000,7),"No data yet")'],
        ["Days with 0 habits", '=IFERROR(COUNTIF(\'Daily Log\'!K2:K1000,0),"No data yet")'],
        ["Wake up 9:30 hit rate", '=IFERROR(COUNTIF(\'Daily Log\'!D2:D1000,TRUE)/COUNTA(\'Daily Log\'!D2:D1000),"No data yet")'],
        ["No screens morning hit rate", '=IFERROR(COUNTIF(\'Daily Log\'!E2:E1000,TRUE)/COUNTA(\'Daily Log\'!E2:E1000),"No data yet")'],
        ["Creatine & Hydrate hit rate", '=IFERROR(COUNTIF(\'Daily Log\'!F2:F1000,TRUE)/COUNTA(\'Daily Log\'!F2:F1000),"No data yet")'],
        ["20 min walk hit rate", '=IFERROR(COUNTIF(\'Daily Log\'!G2:G1000,TRUE)/COUNTA(\'Daily Log\'!G2:G1000),"No data yet")'],
        ["Physical activity hit rate", '=IFERROR(COUNTIF(\'Daily Log\'!H2:H1000,TRUE)/COUNTA(\'Daily Log\'!H2:H1000),"No data yet")'],
        ["No screens before bed hit rate", '=IFERROR(COUNTIF(\'Daily Log\'!I2:I1000,TRUE)/COUNTA(\'Daily Log\'!I2:I1000),"No data yet")'],
        ["Bed at 10 PM hit rate", '=IFERROR(COUNTIF(\'Daily Log\'!J2:J1000,TRUE)/COUNTA(\'Daily Log\'!J2:J1000),"No data yet")'],
    ])

    # Section: Habit-HRV Correlations
    # VLOOKUP keys: Daily Log B (Date) -> Garmin {B (Date), D (HRV)}
    sheet.update("A33", [["HABIT vs HRV CORRELATIONS (overnight avg ms)"]])
    sheet.update("A34", [
        ["Metric", "Avg HRV (ms)"],
        ["Full habit day (7/7) -> HRV next morning",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Daily Log\'!K2:K1000=7,IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["Incomplete day (<7 habits) -> HRV next morning",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF((\'Daily Log\'!K2:K1000<7)*(\'Daily Log\'!K2:K1000<>""),IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["Bed at 10 PM -> HRV next morning",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Daily Log\'!J2:J1000=TRUE,IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["Bed at 10 PM missed -> HRV next morning",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Daily Log\'!J2:J1000=FALSE,IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["No screens before bed -> HRV next morning",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Daily Log\'!I2:I1000=TRUE,IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["No screens before bed missed -> HRV next morning",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Daily Log\'!I2:I1000=FALSE,IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["Physical activity -> HRV next morning",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Daily Log\'!H2:H1000=TRUE,IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["Physical activity missed -> HRV next morning",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Daily Log\'!H2:H1000=FALSE,IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
    ])

    # Section: Morning Energy Score
    # Daily Log C = Morning Energy
    sheet.update("A45", [["MORNING ENERGY SCORE"]])
    sheet.update("A46", [
        ["Metric", "Value"],
        ["Avg morning energy score", '=IFERROR(AVERAGE(\'Daily Log\'!C2:C1000),"No data yet")'],
        ["High energy days (score >= 7)", '=IFERROR(COUNTIF(\'Daily Log\'!C2:C1000,">="&7),"No data yet")'],
        ["Low energy days (score <= 4)", '=IFERROR(COUNTIF(\'Daily Log\'!C2:C1000,"<="&4),"No data yet")'],
        ["Avg HRV on high energy days (>=7)",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Daily Log\'!C2:C1000>=7,IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["Avg HRV on low energy days (<=4)",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF((\'Daily Log\'!C2:C1000<=4)*(\'Daily Log\'!C2:C1000<>""),IFERROR(VLOOKUP(\'Daily Log\'!B2:B1000,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
    ])

    # Section: Workout vs Recovery
    # Session Log cols shifted +1: B=Date, C=Session Type, E=Post-Workout Energy,
    # N=Anaerobic TE, M=Aerobic TE, L=Calories, W=Next Morning Feel
    sheet.update("A55", [["WORKOUT vs RECOVERY (next-morning HRV)"]])
    sheet.update("A56", [
        ["Metric", "Avg HRV (ms)"],
        ["After Strength session -> next morning HRV",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Session Log\'!C2:C1000="Strength",IFERROR(VLOOKUP(\'Session Log\'!B2:B1000+1,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["After Cardio session (Run/Cycle/Swim) -> next morning HRV",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF((\'Session Log\'!C2:C1000="Run")+(\'Session Log\'!C2:C1000="Cycle")+(\'Session Log\'!C2:C1000="Swim"),IFERROR(VLOOKUP(\'Session Log\'!B2:B1000+1,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["High Anaerobic TE (>=3) -> next morning HRV",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Session Log\'!N2:N1000>=3,IFERROR(VLOOKUP(\'Session Log\'!B2:B1000+1,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["Low Anaerobic TE (<3) -> next morning HRV",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF((\'Session Log\'!N2:N1000<3)*(\'Session Log\'!L2:L1000<>""),IFERROR(VLOOKUP(\'Session Log\'!B2:B1000+1,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["High Aerobic TE (>=3) -> next morning HRV",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Session Log\'!M2:M1000>=3,IFERROR(VLOOKUP(\'Session Log\'!B2:B1000+1,{Garmin!B2:B1000,Garmin!D2:D1000},2,0),""),""))),"No data yet")'],
        ["Avg post-workout fatigue -> Strength",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Session Log\'!C2:C1000="Strength",\'Session Log\'!E2:E1000,""))),"No data yet")'],
        ["Avg post-workout fatigue -> Cardio",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF((\'Session Log\'!C2:C1000="Run")+(\'Session Log\'!C2:C1000="Cycle")+(\'Session Log\'!C2:C1000="Swim"),\'Session Log\'!E2:E1000,""))),"No data yet")'],
        ["Avg next morning feel -> Strength",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF(\'Session Log\'!C2:C1000="Strength",\'Session Log\'!W2:W1000,""))),"No data yet")'],
        ["Avg next morning feel -> Cardio",
         '=IFERROR(AVERAGE(ARRAYFORMULA(IF((\'Session Log\'!C2:C1000="Run")+(\'Session Log\'!C2:C1000="Cycle")+(\'Session Log\'!C2:C1000="Swim"),\'Session Log\'!W2:W1000,""))),"No data yet")'],
    ])

    # Format headers bold
    for cell in ["A1", "A11", "A19", "A33", "A45", "A55"]:
        sheet.format(cell, {"textFormat": {"bold": True}})
    for rng in ["A2:B2", "A12:B12", "A20:B20", "A34:B34", "A46:B46", "A56:B56"]:
        sheet.format(rng, {"textFormat": {"bold": True}})

    print("  Analysis tab populated with formulas.")


def setup_session_log_tab(wb):
    try:
        sheet = wb.worksheet("Session Log")
    except Exception:
        sheet = wb.add_worksheet(title="Session Log", rows=1000, cols=23)

    headers = [
        "Day",                         # A
        "Date",                        # B
        "Session Type",                # C
        "Perceived Effort",            # D
        "Post-Workout Energy (1-10)", # E
        "Notes",                       # F
        "Activity Name",               # G
        "Duration (min)",              # H
        "Distance (mi)",               # I
        "Avg HR",                      # J
        "Max HR",                      # K
        "Calories",                    # L
        "Aerobic TE (0-5)",            # M
        "Anaerobic TE (0-5)",          # N
        "Zone 1 (min)",                # O
        "Zone 2 (min)",                # P
        "Zone 3 (min)",                # Q
        "Zone 4 (min)",                # R
        "Zone 5 (min)",                # S
        "Zone Ranges",                 # T
        "Source",                      # U
        "Elevation (m)",               # V
        "Next Morning Feel (1-10)",    # W
    ]
    sheet.update(range_name="A1", values=[headers])
    sheet.format("A1:W1", {"textFormat": {"bold": True}})

    # Add Perceived Effort dropdown to column D (rows 2-1000)
    wb.batch_update({"requests": [{
        "setDataValidation": {
            "range": {
                "sheetId": sheet.id,
                "startRowIndex": 1,
                "endRowIndex": 1000,
                "startColumnIndex": 3,
                "endColumnIndex": 4,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [
                        {"userEnteredValue": "Easy"},
                        {"userEnteredValue": "Somewhat Moderate"},
                        {"userEnteredValue": "Moderate"},
                        {"userEnteredValue": "Moderately Hard"},
                        {"userEnteredValue": "Hard"},
                    ]
                },
                "showCustomUi": True,
                "strict": False,
            }
        }
    }]})
    print("  Session Log tab headers updated + Perceived Effort dropdown set.")


def setup_strength_log_tab(wb):
    try:
        sheet = wb.worksheet("Strength Log")
    except Exception:
        sheet = wb.add_worksheet(title="Strength Log", rows=2000, cols=8)

    headers = ["Day", "Date", "Muscle Group", "Exercise", "Weight (lbs)", "Reps", "RPE (1-10)", "Notes"]
    sheet.update("A1", [headers])
    sheet.format("A1:H1", {"textFormat": {"bold": True}})
    print("  Strength Log tab headers updated.")


def setup_sleep_tab(wb):
    try:
        sheet = wb.worksheet("Sleep")
    except Exception:
        sheet = wb.add_worksheet(title="Sleep", rows=1000, cols=25)

    from garmin_sync import SLEEP_HEADERS
    sheet.update(range_name="A1", values=[SLEEP_HEADERS])
    sheet.format(f"A1:{chr(64+len(SLEEP_HEADERS))}1", {"textFormat": {"bold": True}})
    print("  Sleep tab headers updated.")


def main():
    print("Setting up Google Sheets analysis tabs...")
    wb = get_workbook()

    setup_sleep_tab(wb)
    setup_session_log_tab(wb)
    setup_strength_log_tab(wb)
    setup_analysis_tab(wb)
    print("\nSetup complete. Run 'python verify_sheets.py' to verify all tabs.")

if __name__ == "__main__":
    main()
