$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = (Resolve-Path (Join-Path $scriptDir "..")).Path
$syncScript = Join-Path $projectDir "garmin_sync.py"

# --- 8 PM Full Sync ---
$action  = New-ScheduledTaskAction -Execute "python" -Argument "`"$syncScript`"" -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -Daily -At "8:00PM"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "Health Tracker - Garmin Sync" -Action $action -Trigger $trigger -Settings $settings -Force

# --- 11 AM Sleep Notification (smart retry) ---
$sleepAction  = New-ScheduledTaskAction -Execute "python" -Argument "`"$syncScript`" --sleep-notify" -WorkingDirectory $projectDir
$sleepTrigger = New-ScheduledTaskTrigger -Daily -At "11:00AM"
$sleepSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "Health Tracker - Sleep Notification" -Action $sleepAction -Trigger $sleepTrigger -Settings $sleepSettings -Force

# --- 12 AM Day Prep (empty Nutrition + Daily Log rows) ---
$prepAction  = New-ScheduledTaskAction -Execute "python" -Argument "`"$syncScript`" --prep-day" -WorkingDirectory $projectDir
$prepTrigger = New-ScheduledTaskTrigger -Daily -At "12:00AM"
$prepSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "Health Tracker - Day Prep" -Action $prepAction -Trigger $prepTrigger -Settings $prepSettings -Force

Write-Host ""
Write-Host "Verifying tasks were created..."
foreach ($taskName in @("Health Tracker - Garmin Sync", "Health Tracker - Sleep Notification", "Health Tracker - Day Prep")) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "SUCCESS: $taskName"
        Write-Host "  State:   $($task.State)"
        Write-Host "  Trigger: $($task.Triggers[0].StartBoundary)"
    } else {
        Write-Host "FAILED: $taskName not found. Try running as Administrator."
    }
}
