@echo off
title Health Tracker — Setup Wizard
color 0A
echo.
echo  ==========================================
echo   Health Tracker — Setup Wizard
echo  ==========================================
echo.

:: Change to the project root (one level up from scripts/)
cd /d "%~dp0.."

:CHECK_PYTHON
echo  Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [!] Python is not installed or not in PATH.
    echo.
    echo  ==========================================
    echo   HOW TO INSTALL PYTHON
    echo  ==========================================
    echo.
    echo  1. Your browser will now open the Python download page.
    echo  2. Click the big YELLOW button that says "Download Python"
    echo  3. Run the installer.
    echo  4. IMPORTANT: On the FIRST screen of the installer,
    echo     check the box that says:
    echo.
    echo       [x] Add Python to PATH
    echo.
    echo     (It is near the bottom of the installer window.)
    echo     Do this BEFORE clicking Install Now.
    echo  5. Finish the installation.
    echo  6. Come back to this window and press any key to continue.
    echo.
    start https://www.python.org/downloads/
    pause
    echo.
    echo  Checking for Python again...
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo  [ERROR] Python still not found.
        echo.
        echo  Please make sure you:
        echo    - Finished the Python installation
        echo    - Checked "Add Python to PATH" during install
        echo    - Closed and re-opened this window after installing
        echo.
        echo  If the problem persists, restart your computer and
        echo  double-click "Setup Wizard.bat" again.
        echo.
        pause
        exit /b 1
    )
)

echo.
python --version
echo  Python found. Starting the setup wizard...
echo.

:: Run the Python wizard
python setup_wizard.py

echo.
pause
