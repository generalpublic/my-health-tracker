#!/bin/bash
# Health Tracker — Setup Wizard (macOS launcher)
#
# To use this file on macOS:
#   1. Open Terminal
#   2. Run: chmod +x "/path/to/Health Tracker/scripts/Setup Wizard.command"
#   3. Then double-click this file in Finder to launch it
#      (If macOS says it can't be opened, right-click > Open > Open)

# Change to the project root (one level up from scripts/)
cd "$(dirname "$0")/.."

echo ""
echo " =========================================="
echo "  Health Tracker — Setup Wizard"
echo " =========================================="
echo ""

# Check for Python 3
if ! command -v python3 &>/dev/null; then
    echo " [!] Python 3 is not installed."
    echo ""
    echo " =========================================="
    echo "  HOW TO INSTALL PYTHON ON MAC"
    echo " =========================================="
    echo ""
    echo " 1. Your browser will now open the Python download page."
    echo " 2. Click the big button that says 'Download Python 3.x.x'"
    echo " 3. Open the downloaded .pkg file and follow the installer."
    echo " 4. When the installer finishes, close it."
    echo " 5. Come back to this window and press Enter to continue."
    echo ""
    echo " NOTE: On macOS, Python is added to your PATH automatically"
    echo " by the installer -- you do not need to check any boxes."
    echo ""
    open "https://www.python.org/downloads/"
    read -p " Press Enter after finishing the Python installation... "
    echo ""
    if ! command -v python3 &>/dev/null; then
        echo " [ERROR] Python 3 still not found."
        echo ""
        echo " Please make sure the installer finished successfully."
        echo " Then close this window and double-click 'Setup Wizard.command' again."
        echo ""
        read -p " Press Enter to close... "
        exit 1
    fi
fi

echo ""
python3 --version
echo " Python 3 found. Starting the setup wizard..."
echo ""

# Run the Python wizard
python3 setup_wizard.py

echo ""
read -p " Press Enter to close... "
