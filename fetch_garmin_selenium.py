"""
Fetch Garmin data using Selenium with an existing Chrome login session.
Connects to Chrome's debug port to reuse your active Garmin session.

Step 1: Close all Chrome windows
Step 2: Run this script — it will launch Chrome with debug mode,
        you log in once, then it fetches everything automatically.
"""

import json
import os
import sys
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

EXPORT_PATH = Path(__file__).parent / "garmin_browser_export.json"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_DEBUG_PORT = 9222
USER_DATA = os.path.expanduser("~") + r"\AppData\Local\Google\Chrome\User Data"


def launch_chrome_debug():
    """Launch Chrome with remote debugging enabled."""
    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={CHROME_DEBUG_PORT}",
        f"--user-data-dir={USER_DATA}",
        "--no-first-run",
    ]
    subprocess.Popen(cmd, creationflags=0x08000000)
    time.sleep(3)


def fetch_data():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    print("Connecting to Chrome debug session...")
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_DEBUG_PORT}")

    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as e:
        print(f"Could not connect to Chrome: {e}")
        print("\nMake sure:")
        print("1. ALL Chrome windows are closed")
        print("2. Run this script — it will relaunch Chrome with debug mode")
        print("\nRetrying with fresh Chrome launch...")
        launch_chrome_debug()
        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as e2:
            print(f"Still can't connect: {e2}")
            return

    # Navigate to Garmin Connect
    print("Navigating to Garmin Connect...")
    driver.get("https://connect.garmin.com/modern/daily-summary")
    time.sleep(3)

    # Check if we're logged in
    if "signin" in driver.current_url.lower() or "sso.garmin" in driver.current_url.lower():
        print("\n*** You need to log in! ***")
        print("Log into Garmin Connect in the Chrome window that just opened.")
        print("Press Enter here when you're logged in and can see your dashboard...")
        input()
        time.sleep(2)

    # Calculate dates to fetch
    dates = []
    for i in range(5):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        dates.append(d)
    dates.reverse()  # oldest first

    print(f"\nFetching data for: {dates}")

    # Use JavaScript to fetch data from the API (browser handles auth)
    js_script = """
    async function fetchAll(dates) {
        const results = {};
        for (const d of dates) {
            const endpoints = {
                wellness: `/proxy/usersummary-service/usersummary/daily/${d}`,
                sleep: `/proxy/wellness-service/wellness/dailySleepData/${d}`,
                activities: `/proxy/activitylist-service/activities/search/activities?startDate=${d}&endDate=${d}&limit=10`,
                hrv: `/proxy/hrv-service/hrv/${d}`,
                bodyBattery: `/proxy/device-service/deviceservice/body-battery/date/${d}`,
            };

            results[d] = {};
            for (const [key, url] of Object.entries(endpoints)) {
                try {
                    const resp = await fetch(url, {credentials: 'include'});
                    if (resp.ok) {
                        results[d][key] = await resp.json();
                    } else {
                        results[d][key] = null;
                    }
                } catch(e) {
                    results[d][key] = null;
                }
            }
        }
        return JSON.stringify(results);
    }
    return await fetchAll(arguments[0]);
    """

    print("Fetching wellness, sleep, activities, HRV, body battery...")
    try:
        result_json = driver.execute_script(js_script, dates)
        results = json.loads(result_json)

        # Summary
        for d, data in results.items():
            parts = []
            for key, val in data.items():
                parts.append(f"{key}={'YES' if val else 'no'}")
            print(f"  {d}: {', '.join(parts)}")

        # If all null, try alternate endpoints
        all_null = all(
            all(v is None for v in day.values())
            for day in results.values()
        )

        if all_null:
            print("\nProxy endpoints failed. Trying gc-api endpoints...")
            js_script2 = js_script.replace("/proxy/", "/gc-api/")
            result_json = driver.execute_script(js_script2, dates)
            results = json.loads(result_json)

            for d, data in results.items():
                parts = []
                for key, val in data.items():
                    parts.append(f"{key}={'YES' if val else 'no'}")
                print(f"  {d}: {', '.join(parts)}")

        # Save
        with open(EXPORT_PATH, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nData saved to {EXPORT_PATH}")

    except Exception as e:
        print(f"Error fetching data: {e}")
        # Try a simpler approach — just grab the page data
        print("\nTrying to extract data from page content...")
        try:
            # Navigate to each day and grab the page source
            for d in dates:
                driver.get(f"https://connect.garmin.com/modern/daily-summary/{d}")
                time.sleep(2)
                print(f"  Loaded {d}")
        except Exception as e2:
            print(f"  Failed: {e2}")

    print("\nDone! You can close Chrome or keep using it.")


if __name__ == "__main__":
    fetch_data()
