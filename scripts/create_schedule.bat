@echo off
schtasks /create /tn "NS Habit Tracker - Garmin Sync" /tr "python \"%~dp0..\garmin_sync.py\"" /sc daily /st 20:00 /f
schtasks /create /tn "NS Habit Tracker - Sleep Notification" /tr "python \"%~dp0..\garmin_sync.py\" --sleep-notify" /sc daily /st 11:00 /f
echo.
echo Done! Two tasks scheduled:
echo   - Sleep Notification: daily at 11:00 AM (smart retry until 12:00 PM)
echo   - Full Garmin Sync:   daily at 8:00 PM
pause
