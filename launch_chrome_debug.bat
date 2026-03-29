@echo off
REM Launch Chrome with remote debugging port for automated Garmin sync.
REM Chrome opens with your existing profile and all saved sessions.
REM IMPORTANT: --user-data-dir MUST be passed explicitly or debug port won't bind.

REM Check if debug port is already listening
powershell -Command "if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 9222 -WarningAction SilentlyContinue).TcpTestSucceeded) { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 (
    echo Chrome debug port already active on 9222.
    exit /b 0
)

REM Kill any existing Chrome (it blocks the debug port if running without it)
taskkill /F /IM chrome.exe >nul 2>&1
timeout /t 3 /nobreak >nul

REM Launch Chrome with debug port and explicit user-data-dir
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="C:\Users\dseki\AppData\Local\Google\Chrome\User Data" --no-first-run --restore-last-session

echo Chrome launched with remote debugging on port 9222.
