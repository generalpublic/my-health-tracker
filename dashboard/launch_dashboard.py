"""One-command launcher: export data + open dashboard in browser."""

import webbrowser
from pathlib import Path
from export_dashboard_data import export

DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"


def main():
    print("Exporting data from SQLite...")
    if not export():
        return

    url = DASHBOARD_HTML.as_uri()
    print(f"Opening dashboard in browser...")
    webbrowser.open(url)
    print("Done.")


if __name__ == "__main__":
    main()
