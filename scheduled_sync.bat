@echo off
REM Daily Garmin sync via browser-based fetch.
REM Scheduled to run at 12:05 AM and 11:00 AM daily.
REM Requires Chrome running with --remote-debugging-port=9222.

cd /d "%~dp0"

REM Ensure Chrome debug port is available
powershell -NoProfile -Command "if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 9222 -WarningAction SilentlyContinue).TcpTestSucceeded) { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
    echo %date% %time% Chrome not running with debug port. Launching... >> garmin_sync.log
    call launch_chrome_debug.bat
    timeout /t 5 /nobreak >nul
)

REM Run the sync pipeline
"C:\Users\dseki\AppData\Local\Programs\Python\Python312\python.exe" garmin_sync.py --today >> garmin_sync.log 2>&1

if %errorlevel% neq 0 (
    echo %date% %time% *** SYNC FAILED (exit code %errorlevel%) *** >> garmin_sync.log
) else (
    echo %date% %time% Sync completed successfully >> garmin_sync.log
)
