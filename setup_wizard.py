"""
NS Habit Tracker — Setup Wizard
Cross-platform interactive setup for non-technical users.
"""

import sys
import os
import json
import subprocess
import webbrowser
import getpass
import platform
import re
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent
ENV_FILE = PROJECT_DIR / ".env"
REQUIREMENTS_FILE = PROJECT_DIR / "requirements.txt"
GARMIN_SCRIPT = PROJECT_DIR / "garmin_sync.py"
BACKFILL_SCRIPT = PROJECT_DIR / "backfill_history.py"

# ── ANSI Colors ───────────────────────────────────────────────────────────────
# Enable on Windows 10+
if platform.system() == "Windows":
    os.system("color")

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def print_success(msg):
    print(f"{GREEN}  ✓ {msg}{RESET}")

def print_error(msg):
    print(f"{RED}  ✗ {msg}{RESET}")

def print_warning(msg):
    print(f"{YELLOW}  ⚠ {msg}{RESET}")

def print_info(msg):
    print(f"{WHITE}    {msg}{RESET}")

def print_prompt(msg):
    return input(f"{CYAN}  → {msg}{RESET}")

def print_header(step_num, total, title):
    width = 46
    bar = "═" * width
    label = f" STEP {step_num} of {total} — {title}"
    print(f"\n{BOLD}{CYAN}{bar}{RESET}")
    print(f"{BOLD}{CYAN}{label}{RESET}")
    print(f"{BOLD}{CYAN}{bar}{RESET}\n")

def print_banner():
    print(f"""
{BOLD}{CYAN}
  ╔══════════════════════════════════════════════╗
  ║         NS HABIT TRACKER SETUP WIZARD        ║
  ║                                              ║
  ║  This wizard will set up everything for you  ║
  ║  step by step. It takes about 10 minutes.    ║
  ╚══════════════════════════════════════════════╝
{RESET}""")

def print_completion_summary(config: dict):
    print(f"""
{BOLD}{GREEN}
  ╔══════════════════════════════════════════════╗
  ║           SETUP COMPLETE!                    ║
  ╚══════════════════════════════════════════════╝
{RESET}""")

    print(f"{BOLD}  Configuration Summary:{RESET}")
    print(f"  {'─'*44}")
    print_info(f"Garmin email    : {config.get('garmin_email', 'N/A')}")
    print_info(f"Sheet ID        : {config.get('sheet_id', 'N/A')}")
    print_info(f"Service account : {config.get('client_email', 'N/A')}")
    print_info(f"JSON key file   : {config.get('json_filename', 'N/A')}")
    print_info(f"Auto-sync       : {'Enabled (8 PM daily)' if config.get('scheduler_set') else 'Not configured'}")
    print(f"  {'─'*44}")

    print(f"\n{BOLD}  Daily Commands:{RESET}")
    print(f"  {'─'*44}")
    print_info("python garmin_sync.py                    — sync yesterday")
    print_info("python garmin_sync.py --today            — sync today")
    print_info("python garmin_sync.py --date YYYY-MM-DD  — sync a specific date")
    print_info("python backfill_history.py               — pull full history (~28 min)")
    print(f"  {'─'*44}")

    print(f"\n{BOLD}  If you move to a new computer, you will need to:{RESET}")
    print_info("1. Copy this entire project folder to the new computer")
    print_info("2. Install Python 3.10+ (https://python.org/downloads)")
    print_info("3. Run this wizard again (Setup Wizard.bat / .command)")
    print_info("4. Re-enter your Garmin password when prompted")
    print_info("   (The JSON key file travels with the folder — no re-download needed)")
    print()


# ── State (in-memory, shared across steps) ───────────────────────────────────
config = {
    "garmin_email": None,
    "sheet_id": None,
    "json_filename": None,
    "client_email": None,
    "scheduler_set": False,
}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — System Check
# ─────────────────────────────────────────────────────────────────────────────
def step1_system_check():
    print_header(1, 9, "System Check")
    try:
        ver = sys.version_info
        os_name = platform.system()
        print_info(f"Operating system : {os_name} {platform.release()}")
        print_info(f"Python version   : {ver.major}.{ver.minor}.{ver.micro}")

        if ver < (3, 10):
            print_error(
                f"Python 3.10 or newer is required. "
                f"You have {ver.major}.{ver.minor}. "
                f"Please download a newer version from https://python.org/downloads"
            )
            return False

        print_success("System check passed.")
        return True
    except Exception as e:
        print_error(f"Unexpected error during system check: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Install Dependencies
# ─────────────────────────────────────────────────────────────────────────────
def _packages_already_installed() -> bool:
    """Return True if all required packages can be imported."""
    required = ["garminconnect", "gspread", "google.oauth2", "dotenv", "keyring"]
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            return False
    return True

def step2_install_dependencies():
    print_header(2, 9, "Install Dependencies")

    if _packages_already_installed():
        print_success("All required packages are already installed. Skipping.")
        return True

    if not REQUIREMENTS_FILE.exists():
        print_warning(
            f"requirements.txt not found at {REQUIREMENTS_FILE}. "
            "Skipping automatic install."
        )
        return True

    print_info("Installing required packages — this may take a minute...")
    print()

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            print_success("All packages installed successfully.")
            # Show what was installed
            for line in result.stdout.splitlines():
                if line.startswith("Successfully installed"):
                    pkgs = line.replace("Successfully installed", "").strip()
                    for pkg in pkgs.split():
                        print_info(f"  + {pkg}")
            return True
        else:
            print_error("pip encountered an error:")
            for line in result.stderr.splitlines():
                print_info(line)
            print()
            print_warning(
                "You can try installing manually by running this command in your terminal:"
            )
            print_info(f"  pip install -r requirements.txt")
            # Don't block the wizard — user may fix and re-run
            return False
    except subprocess.TimeoutExpired:
        print_error("Installation timed out after 5 minutes.")
        return False
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Google Cloud / Service Account
# ─────────────────────────────────────────────────────────────────────────────
def _find_json_files() -> list:
    """Find candidate service account JSON files in the project folder."""
    skip = {"package.json", "package-lock.json"}
    found = []
    for f in PROJECT_DIR.glob("*.json"):
        if f.name in skip:
            continue
        # Check if it looks like a service account key
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if "client_email" in data and "type" in data:
                found.append(f)
        except Exception:
            pass
    return found

def step3_google_cloud():
    print_header(3, 9, "Google Cloud — Service Account Setup")

    # Check if already done
    existing_jsons = _find_json_files()
    if existing_jsons and config.get("json_filename"):
        print_success(f"Service account JSON already configured: {config['json_filename']}")
        return True

    print_info("We need to give this tool permission to write to your Google Sheet.")
    print_info("Google requires a special 'service account key' file for this.")
    print_info("This sounds technical, but the steps below walk you through it exactly.")
    print()

    print(f"{BOLD}  Follow these steps:{RESET}")
    print()
    print_info(" 1. Your browser will open Google Cloud Console.")
    print_info(" 2. Sign in with your Google account if prompted.")
    print_info(" 3. Click 'Select a project' at the top, then 'New Project'.")
    print_info(" 4. Name it anything (e.g. 'Habit Tracker') and click Create.")
    print_info(" 5. Make sure your new project is selected (shown at the top).")
    print_info(" 6. In the left menu: APIs & Services → Library.")
    print_info(" 7. Search 'Google Sheets API', click it, click Enable.")
    print_info(" 8. Search 'Google Drive API', click it, click Enable.")
    print_info(" 9. In the left menu: APIs & Services → Credentials.")
    print_info("10. Click '+ Create Credentials' → 'Service Account'.")
    print_info("11. Enter any name (e.g. 'habit-tracker'), click Create and Continue.")
    print_info("12. For Role, select 'Editor', click Continue, then Done.")
    print_info("13. Click on the service account email that appears in the list.")
    print_info("14. Go to the 'Keys' tab → 'Add Key' → 'Create new key' → JSON → Create.")
    print_info("15. A JSON file will download automatically.")
    print()
    print(f"{YELLOW}  Move that downloaded JSON file into this folder:{RESET}")
    print(f"{BOLD}{CYAN}    {PROJECT_DIR}{RESET}")
    print()

    input(f"{CYAN}  → Press Enter when your browser is ready and I'll open Google Cloud...{RESET}")
    webbrowser.open("https://console.cloud.google.com")
    print()

    while True:
        input(f"{CYAN}  → Press Enter once you have moved the JSON file into the folder above...{RESET}")
        print()

        json_files = _find_json_files()

        if not json_files:
            print_error(
                "No service account JSON files found in the project folder. "
                "Make sure the file ends in .json and is in:"
            )
            print_info(str(PROJECT_DIR))
            retry = print_prompt("Try again? (y/n): ").strip().lower()
            if retry != "y":
                return False
            continue

        if len(json_files) == 1:
            chosen = json_files[0]
        else:
            print_info("Multiple JSON files found. Which one is your service account key?")
            for i, f in enumerate(json_files, 1):
                print_info(f"  {i}. {f.name}")
            while True:
                choice = print_prompt(f"Enter number (1–{len(json_files)}): ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(json_files):
                    chosen = json_files[int(choice) - 1]
                    break
                print_error("Invalid choice. Please enter a number from the list.")

        # Read only client_email
        try:
            data = json.loads(chosen.read_text(encoding="utf-8"))
            client_email = data.get("client_email", "")
            if not client_email:
                print_error("This JSON file does not contain a 'client_email' field. It may not be a service account key.")
                retry = print_prompt("Try again with a different file? (y/n): ").strip().lower()
                if retry != "y":
                    return False
                continue

            config["json_filename"] = chosen.name
            config["client_email"] = client_email
            print_success(f"Service account key found: {chosen.name}")
            print_success(f"Service account email    : {client_email}")
            print()
            print_info(f"{YELLOW}Save this email — you'll need it in the next step:{RESET}")
            print(f"\n  {BOLD}{CYAN}{client_email}{RESET}\n")
            return True

        except Exception as e:
            print_error(f"Could not read the JSON file: {e}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Google Sheets Setup
# ─────────────────────────────────────────────────────────────────────────────
def _looks_like_sheet_id(s: str) -> bool:
    """Basic validation: Sheet IDs are 40–50 char alphanumeric strings."""
    return bool(re.match(r'^[A-Za-z0-9_\-]{30,60}$', s))

def step4_google_sheets():
    print_header(4, 9, "Google Sheets Setup")

    print_info("Now we'll create your Google Sheet and give the tool access to it.")
    print()
    print(f"{BOLD}  Follow these steps:{RESET}")
    print()
    print_info(" 1. Your browser will open Google Sheets.")
    print_info(" 2. Click the big '+' button to create a blank spreadsheet.")
    print_info(" 3. Give it a name like 'NS Habit Tracker'.")
    print_info(" 4. Look at the URL in your browser — it looks like:")
    print_info("      docs.google.com/spreadsheets/d/[COPY THIS PART]/edit")
    print_info("    Copy that long ID from the URL.")
    print()
    print_info(" 5. Click the 'Share' button (top right of Google Sheets).")

    client_email = config.get("client_email", "<your-service-account@...>")
    print_info(f"    Paste this email address into the Share box:")
    print(f"\n  {BOLD}{CYAN}    {client_email}{RESET}\n")
    print_info("    Set the role to 'Editor', then click Send.")
    print()

    input(f"{CYAN}  → Press Enter when your browser is ready and I'll open Google Sheets...{RESET}")
    webbrowser.open("https://sheets.google.com")
    print()

    while True:
        sheet_id = print_prompt("Paste the Sheet ID here: ").strip()
        # Strip the full URL if user pasted it by mistake
        url_match = re.search(r'/spreadsheets/d/([A-Za-z0-9_\-]+)', sheet_id)
        if url_match:
            sheet_id = url_match.group(1)
            print_info(f"Extracted Sheet ID from URL: {sheet_id}")

        if _looks_like_sheet_id(sheet_id):
            config["sheet_id"] = sheet_id
            print_success(f"Sheet ID saved: {sheet_id}")
            return True
        else:
            print_error(
                "That doesn't look like a valid Sheet ID. "
                "It should be the long code in the URL, not the full URL itself."
            )
            print_info("Example URL: docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit")
            print_info("Example ID : 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Configure .env File
# ─────────────────────────────────────────────────────────────────────────────
def _read_env() -> dict:
    """Parse the .env file into a dict."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

def step5_configure_env():
    print_header(5, 9, "Configure Settings File (.env)")

    existing_env = _read_env()

    print_info("This step creates the configuration file for the tracker.")
    print_info("None of the values in this file are passwords or secrets —")
    print_info("it's just your email address, sheet ID, and the name of your key file.")
    print()

    # Garmin email
    default_email = existing_env.get("GARMIN_EMAIL", config.get("garmin_email", ""))
    if default_email:
        garmin_email = print_prompt(f"Garmin email address [{default_email}]: ").strip()
        if not garmin_email:
            garmin_email = default_email
    else:
        garmin_email = print_prompt("Garmin email address: ").strip()

    if not garmin_email:
        print_error("Email address is required.")
        return False

    config["garmin_email"] = garmin_email

    # Sheet ID (from step 4 or existing .env)
    sheet_id = config.get("sheet_id") or existing_env.get("SHEET_ID", "")
    if not sheet_id:
        sheet_id = print_prompt("Google Sheet ID (from Step 4): ").strip()
    config["sheet_id"] = sheet_id

    # JSON filename (from step 3 or existing .env)
    json_filename = config.get("json_filename") or existing_env.get("GOOGLE_KEY_FILE", "")
    if not json_filename:
        json_filename = print_prompt("Service account JSON filename (e.g. habit-tracker-key.json): ").strip()
    config["json_filename"] = json_filename

    env_contents = (
        f"# NS Habit Tracker — Configuration\n"
        f"# This file is NOT sensitive — no passwords are stored here.\n"
        f"\n"
        f"GARMIN_EMAIL={garmin_email}\n"
        f"SHEET_ID={sheet_id}\n"
        f"GOOGLE_KEY_FILE={json_filename}\n"
    )

    print()
    print_info("The following will be written to .env:")
    print(f"  {'─'*44}")
    for line in env_contents.splitlines():
        print_info(line)
    print(f"  {'─'*44}")
    print()

    try:
        ENV_FILE.write_text(env_contents, encoding="utf-8")
        print_success(f".env file written to {ENV_FILE}")
        return True
    except Exception as e:
        print_error(f"Could not write .env file: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Store Garmin Password
# ─────────────────────────────────────────────────────────────────────────────
def _keyring_has_password(email: str) -> bool:
    try:
        import keyring
        val = keyring.get_password("garmin_connect", email)
        return val is not None and val != ""
    except Exception:
        return False

def step6_store_password():
    print_header(6, 9, "Store Garmin Password Securely")

    email = config.get("garmin_email")
    if not email:
        print_error("No Garmin email found. Please re-run Step 5 first.")
        return False

    if _keyring_has_password(email):
        print_success(f"A password for {email} is already stored in your system keychain.")
        change = print_prompt("Would you like to update it? (y/n): ").strip().lower()
        if change != "y":
            return True

    print()
    print_info("Your Garmin password will be stored in your computer's secure password")
    print_info("manager (Windows Credential Manager on PC, Keychain on Mac).")
    print_info("It will NEVER be saved to any file.")
    print()
    print_info("This wizard runs entirely on your computer. Your password will never")
    print_info("be sent anywhere except to Garmin's login server.")
    print()
    print_info("You'll type your password now. It won't show on screen as you type —")
    print_info("that's normal and intentional.")
    print()

    try:
        import keyring
    except ImportError:
        print_error("The 'keyring' package is not installed. Please run Step 2 first.")
        return False

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            password = getpass.getpass(f"{CYAN}  → Enter your Garmin password (hidden): {RESET}")
            confirm  = getpass.getpass(f"{CYAN}  → Confirm your Garmin password (hidden): {RESET}")
        except (KeyboardInterrupt, EOFError):
            print()
            print_warning("Password entry cancelled.")
            return False

        if password == confirm:
            break
        else:
            print_error(f"Passwords do not match. Attempt {attempt} of {max_attempts}.")
            if attempt == max_attempts:
                print_error("Too many failed attempts. Please re-run this step.")
                password = None
                confirm = None
                return False

    try:
        keyring.set_password("garmin_connect", email, password)
    except Exception as e:
        password = None
        confirm = None
        print_error(f"Could not store password in keychain: {e}")
        return False

    # Immediately clear from memory
    password = None
    confirm = None

    print()
    print_success("Password stored securely in your system keychain.")
    print_success("This program no longer has access to it.")
    print()
    print_info("If you ever need to change your Garmin password, re-run this wizard")
    print_info("or run this command in your terminal:")
    print()
    print_info(f"  python -c \"import keyring; keyring.set_password('garmin_connect', '{email}', 'newpassword')\"")
    print()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Test the Connection
# ─────────────────────────────────────────────────────────────────────────────
def step7_test_connection():
    print_header(7, 9, "Test the Connection")

    if not GARMIN_SCRIPT.exists():
        print_error(f"garmin_sync.py not found at {GARMIN_SCRIPT}")
        print_info("Make sure this wizard is in the same folder as garmin_sync.py.")
        return False

    print_info("Running garmin_sync.py --today to test the full connection...")
    print_info("This may take 30–60 seconds.")
    print()

    try:
        result = subprocess.run(
            [sys.executable, str(GARMIN_SCRIPT), "--today"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_DIR),
        )

        output = result.stdout + result.stderr
        print_info("─" * 44)
        for line in output.splitlines():
            print_info(line)
        print_info("─" * 44)
        print()

        if result.returncode == 0 and ("Done" in output or "done" in output or "success" in output.lower()):
            print_success("Connection test passed! Data synced to your Google Sheet.")
            return True
        else:
            print_error("The sync script did not complete successfully.")
            print()

            output_lower = output.lower()

            if "login" in output_lower or "invalid credentials" in output_lower or "unauthorized" in output_lower:
                print_warning("This looks like a Garmin login failure.")
                print_info("Your Garmin email or password may be incorrect.")
                retry = print_prompt("Would you like to re-enter your Garmin password? (y/n): ").strip().lower()
                if retry == "y":
                    return step6_store_password() and step7_test_connection()

            elif "permission" in output_lower or "forbidden" in output_lower or "403" in output_lower:
                client_email = config.get("client_email", "<service account email>")
                print_warning("This looks like a Google Sheets permission error.")
                print_info("Make sure you shared your Google Sheet with:")
                print(f"\n  {BOLD}{CYAN}  {client_email}{RESET}\n")
                print_info("Open Google Sheets → Share → paste the email above → Editor → Send")
                sheet_id = config.get("sheet_id", "")
                if sheet_id:
                    print_info(f"Sheet link: https://docs.google.com/spreadsheets/d/{sheet_id}")

            elif "json" in output_lower or "no such file" in output_lower or "key" in output_lower:
                print_warning("This looks like a problem with the service account JSON file.")
                retry = print_prompt("Would you like to re-run the Google Cloud setup (Step 3)? (y/n): ").strip().lower()
                if retry == "y":
                    return step3_google_cloud() and step7_test_connection()

            else:
                print_info("Please review the error output above and check:")
                print_info("  • Garmin email and password (Step 6)")
                print_info("  • Sheet shared with service account email (Step 4)")
                print_info("  • JSON key file is in the project folder (Step 3)")

            return False

    except subprocess.TimeoutExpired:
        print_error("The test timed out after 2 minutes.")
        print_info("This can happen with slow internet. Try running the test manually:")
        print_info(f"  python garmin_sync.py --today")
        return False
    except Exception as e:
        print_error(f"Unexpected error while running test: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Automatic Daily Sync
# ─────────────────────────────────────────────────────────────────────────────
def step8_schedule():
    print_header(8, 9, "Automatic Daily Sync")

    os_name = platform.system()

    print_info("This step sets up your computer to automatically sync your Garmin data")
    print_info("every day at 8:00 PM — no action required from you each day.")
    print()

    if os_name == "Windows":
        return _schedule_windows()
    elif os_name == "Darwin":
        return _schedule_macos()
    else:
        return _schedule_linux()

def _schedule_windows():
    script_path = str(GARMIN_SCRIPT)
    python_path = sys.executable
    task_name = "NS Habit Tracker - Daily Sync"
    cmd = (
        f'schtasks /create /tn "{task_name}" '
        f'/tr "\\"{python_path}\\" \\"{script_path}\\"" '
        f'/sc daily /st 20:00 /f'
    )

    print_info("Creating a Windows Scheduled Task to run garmin_sync.py at 8 PM daily...")
    print()

    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print_success(f"Scheduled task created: '{task_name}'")
            print_success("Your data will sync automatically every day at 8 PM.")
            config["scheduler_set"] = True
            return True
        else:
            print_error("Could not create the scheduled task automatically.")
            print_info("Error details:")
            for line in (result.stdout + result.stderr).splitlines():
                print_info(f"  {line}")
            print()
            print_info("You can create it manually by running this command in Command Prompt (as Administrator):")
            print()
            print_info(f'  schtasks /create /tn "{task_name}" /tr "\\"{python_path}\\" \\"{script_path}\\"" /sc daily /st 20:00 /f')
            return False
    except Exception as e:
        print_error(f"Error creating scheduled task: {e}")
        return False

def _schedule_macos():
    plist_label = "com.nshabit.garmin_sync"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{plist_label}.plist"
    python_path = sys.executable
    script_path = str(GARMIN_SCRIPT)

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{plist_label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>20</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>{str(PROJECT_DIR)}</string>
    <key>StandardOutPath</key>
    <string>{str(PROJECT_DIR / 'garmin_sync.log')}</string>
    <key>StandardErrorPath</key>
    <string>{str(PROJECT_DIR / 'garmin_sync_error.log')}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""
    print_info("Creating launchd agent to run garmin_sync.py at 8 PM daily...")
    try:
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(plist_content, encoding="utf-8")
        print_success(f"plist written to {plist_path}")

        result = subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            print_success("launchd agent loaded. Your data will sync every day at 8 PM.")
            config["scheduler_set"] = True
            return True
        else:
            print_warning("plist file created but launchctl load failed:")
            print_info(result.stderr)
            print_info(f"You can load it manually with: launchctl load {plist_path}")
            return False
    except Exception as e:
        print_error(f"Error setting up launchd agent: {e}")
        return False

def _schedule_linux():
    cron_line = f"0 20 * * * cd {PROJECT_DIR} && {sys.executable} {GARMIN_SCRIPT} >> {PROJECT_DIR}/garmin_sync.log 2>&1"
    print_info("To set up automatic daily sync on Linux, run:")
    print()
    print_info("  crontab -e")
    print()
    print_info("Then add this line at the bottom of the file:")
    print()
    print(f"  {BOLD}{CYAN}{cron_line}{RESET}")
    print()
    print_info("Save and exit (Ctrl+O, Enter, Ctrl+X in nano).")
    print_info("The sync will run automatically at 8:00 PM every day.")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — Optional Backfill
# ─────────────────────────────────────────────────────────────────────────────
def step9_backfill():
    print_header(9, 9, "Historical Data Backfill (Optional)")

    print_info("We can pull up to 2 years of your historical Garmin data right now.")
    print_info("This takes about 28 minutes and you'll see a live progress bar.")
    print()

    if not BACKFILL_SCRIPT.exists():
        print_warning(f"backfill_history.py not found at {BACKFILL_SCRIPT}")
        print_info("You can run the backfill later once that file is available:")
        print_info(f"  python backfill_history.py")
        return True

    answer = print_prompt("Would you like to run the historical backfill now? (y/n): ").strip().lower()
    if answer != "y":
        print()
        print_info("Skipped. You can run the backfill any time with:")
        print_info(f"  python backfill_history.py")
        print_info(f"  (Run from: {PROJECT_DIR})")
        return True

    print()
    print_info("Starting backfill — you'll see a progress bar below.")
    print_info("This will take about 28 minutes. You can let it run in the background.")
    print()

    try:
        # os.system so output streams live to terminal
        ret = os.system(f'"{sys.executable}" "{BACKFILL_SCRIPT}"')
        if ret == 0:
            print_success("Historical backfill complete!")
        else:
            print_warning("Backfill exited with an error. Check the output above for details.")
    except Exception as e:
        print_error(f"Could not start backfill: {e}")

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Resume detection
# ─────────────────────────────────────────────────────────────────────────────
def load_existing_config():
    """Pre-populate config from .env and any JSON files if setup was partly done."""
    env = _read_env()
    if env.get("GARMIN_EMAIL"):
        config["garmin_email"] = env["GARMIN_EMAIL"]
    if env.get("SHEET_ID"):
        config["sheet_id"] = env["SHEET_ID"]
    if env.get("GOOGLE_KEY_FILE"):
        config["json_filename"] = env["GOOGLE_KEY_FILE"]
        # Try to read client_email from the saved JSON file
        json_path = PROJECT_DIR / env["GOOGLE_KEY_FILE"]
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                config["client_email"] = data.get("client_email", "")
            except Exception:
                pass


def should_skip_step(step_num: int) -> tuple[bool, str]:
    """
    Return (should_skip, reason) based on what is already configured.
    Only skip if everything needed for that step is confirmed present.
    """
    if step_num == 1:
        return False, ""

    if step_num == 2:
        if _packages_already_installed():
            return True, "All required packages already installed."
        return False, ""

    if step_num == 3:
        jsons = _find_json_files()
        if jsons and config.get("json_filename") and config.get("client_email"):
            return True, f"Service account JSON already configured: {config['json_filename']}"
        return False, ""

    if step_num == 4:
        if config.get("sheet_id"):
            return True, f"Sheet ID already configured: {config['sheet_id']}"
        return False, ""

    if step_num == 5:
        if ENV_FILE.exists() and config.get("garmin_email") and config.get("sheet_id") and config.get("json_filename"):
            return True, ".env file already configured."
        return False, ""

    if step_num == 6:
        email = config.get("garmin_email", "")
        if email and _keyring_has_password(email):
            return True, f"Password already stored for {email}."
        return False, ""

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print_banner()

    # Load any existing config
    load_existing_config()

    if any([config["garmin_email"], config["sheet_id"], config["json_filename"]]):
        print_info("Detected partial or complete previous setup. Checking what's already done...")
        print()

    steps = [
        (1, "System Check",                  step1_system_check),
        (2, "Install Dependencies",          step2_install_dependencies),
        (3, "Google Cloud Setup",            step3_google_cloud),
        (4, "Google Sheets Setup",           step4_google_sheets),
        (5, "Configure .env File",           step5_configure_env),
        (6, "Store Garmin Password",         step6_store_password),
        (7, "Test the Connection",           step7_test_connection),
        (8, "Automatic Daily Sync",          step8_schedule),
        (9, "Historical Backfill (Optional)",step9_backfill),
    ]

    for step_num, step_name, step_fn in steps:
        skip, reason = should_skip_step(step_num)
        if skip:
            print(f"\n{GREEN}  ✓ Step {step_num} already complete — skipping.{RESET}")
            print(f"{GREEN}    ({reason}){RESET}")
            continue

        try:
            ok = step_fn()
        except KeyboardInterrupt:
            print()
            print_warning("Step cancelled by user (Ctrl+C).")
            ok = False
        except Exception as e:
            print_error(f"Unexpected error in Step {step_num}: {e}")
            ok = False

        if not ok and step_num in (1, 5, 6):
            # Critical steps — abort
            print()
            print_error(f"Step {step_num} ({step_name}) failed. Cannot continue.")
            print_info("Fix the issue above and re-run the wizard.")
            print()
            return

        if not ok:
            print()
            print_warning(f"Step {step_num} ({step_name}) did not complete successfully.")
            cont = print_prompt("Continue to the next step anyway? (y/n): ").strip().lower()
            if cont != "y":
                print()
                print_info("Setup paused. Re-run the wizard any time to pick up where you left off.")
                print()
                return

    print_completion_summary(config)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print_warning("Setup cancelled. Re-run the wizard any time to continue.")
        print()
