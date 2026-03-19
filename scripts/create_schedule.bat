@echo off
set PYTHON=C:\Users\dseki\AppData\Local\Python\bin\python.exe
set SCRIPT=%~dp0..\garmin_sync.py

schtasks /create /tn "Health Tracker - Garmin Sync" /tr "\"%PYTHON%\" \"%SCRIPT%\"" /sc daily /st 20:00 /f
schtasks /create /tn "Health Tracker - Sleep Notification" /tr "\"%PYTHON%\" \"%SCRIPT%\" --sleep-notify" /sc daily /st 11:00 /f
schtasks /create /tn "Health Tracker - Day Prep" /tr "\"%PYTHON%\" \"%SCRIPT%\" --prep-day" /sc daily /st 00:00 /f
echo.
echo Done! Three tasks scheduled:
echo   - Day Prep:            daily at 12:00 AM
echo   - Sleep Notification:  daily at 11:00 AM
echo   - Full Garmin Sync:    daily at  8:00 PM
echo.
echo Python: %PYTHON%
pause
