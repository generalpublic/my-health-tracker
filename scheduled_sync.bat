@echo off
REM Daily Garmin sync via browser-based fetch.
REM Scheduled to run at 12:05 AM and 11:00 AM daily.
REM Requires Chrome running with --remote-debugging-port=9222.

cd /d "%~dp0"

REM Ensure Chrome debug port is available
curl -s http://127.0.0.1:9222/json/version >nul 2>&1
if %errorlevel% neq 0 (
    echo Chrome not running with debug port. Launching...
    call launch_chrome_debug.bat
    timeout /t 5 >nul
)

REM Run the sync pipeline
"C:\Users\dseki\AppData\Local\Programs\Python\Python312\python.exe" garmin_sync.py --today >> garmin_sync.log 2>&1

echo Sync completed at %date% %time% >> garmin_sync.log
