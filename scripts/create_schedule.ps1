$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$syncScript = Join-Path $scriptDir "..\garmin_sync.py"

# --- 8 PM Full Sync ---
$action  = New-ScheduledTaskAction -Execute "python" -Argument "`"$syncScript`""
$trigger = New-ScheduledTaskTrigger -Daily -At "8:00PM"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "NS Habit Tracker - Garmin Sync" -Action $action -Trigger $trigger -Settings $settings -Force

# --- 11 AM Sleep Notification (smart retry) ---
$sleepAction  = New-ScheduledTaskAction -Execute "python" -Argument "`"$syncScript`" --sleep-notify"
$sleepTrigger = New-ScheduledTaskTrigger -Daily -At "11:00AM"
$sleepSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "NS Habit Tracker - Sleep Notification" -Action $sleepAction -Trigger $sleepTrigger -Settings $sleepSettings -Force

Write-Host ""
Write-Host "Verifying tasks were created..."
foreach ($taskName in @("NS Habit Tracker - Garmin Sync", "NS Habit Tracker - Sleep Notification")) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "SUCCESS: $taskName"
        Write-Host "  State:   $($task.State)"
        Write-Host "  Trigger: $($task.Triggers[0].StartBoundary)"
    } else {
        Write-Host "FAILED: $taskName not found. Try running as Administrator."
    }
}
