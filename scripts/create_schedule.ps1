$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = (Resolve-Path (Join-Path $scriptDir "..")).Path
$syncScript = Join-Path $projectDir "garmin_sync.py"
$pythonExe  = "C:\Users\dseki\AppData\Local\Python\bin\python.exe"
$logFile    = Join-Path $projectDir "garmin_sync.log"

# Verify python exists
if (-not (Test-Path $pythonExe)) {
    Write-Host "ERROR: Python not found at $pythonExe"
    Write-Host "Update `$pythonExe in this script to your actual Python path."
    exit 1
}

# --- 8 PM Full Sync ---
$action  = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$syncScript`"" -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -Daily -At "8:00PM"
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "Health Tracker - Garmin Sync" -Action $action -Trigger $trigger -Settings $settings -Force

# --- 11 AM Sleep Notification (smart retry) ---
$sleepAction  = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$syncScript`" --sleep-notify" -WorkingDirectory $projectDir
$sleepTrigger = New-ScheduledTaskTrigger -Daily -At "11:00AM"
$sleepSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "Health Tracker - Sleep Notification" -Action $sleepAction -Trigger $sleepTrigger -Settings $sleepSettings -Force

# --- 12 AM Day Prep (empty Nutrition + Daily Log rows) ---
$prepAction  = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$syncScript`" --prep-day" -WorkingDirectory $projectDir
$prepTrigger = New-ScheduledTaskTrigger -Daily -At "12:00AM"
$prepSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "Health Tracker - Day Prep" -Action $prepAction -Trigger $prepTrigger -Settings $prepSettings -Force

Write-Host ""
Write-Host "Verifying tasks were created..."
$allGood = $true
foreach ($taskName in @("Health Tracker - Garmin Sync", "Health Tracker - Sleep Notification", "Health Tracker - Day Prep")) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = $task | Get-ScheduledTaskInfo
        Write-Host "SUCCESS: $taskName"
        Write-Host "  State:          $($task.State)"
        Write-Host "  Trigger:        $($task.Triggers[0].StartBoundary)"
        Write-Host "  Next Run:       $($info.NextRunTime)"
        Write-Host "  StartWhenAvail: $($task.Settings.StartWhenAvailable)"
        Write-Host "  Executable:     $($task.Actions[0].Execute)"
    } else {
        Write-Host "FAILED: $taskName not found. Try running as Administrator."
        $allGood = $false
    }
}

if ($allGood) {
    Write-Host ""
    Write-Host "All 3 tasks registered. Python: $pythonExe"
    Write-Host "Missed-start catch-up enabled (StartWhenAvailable)."
} else {
    Write-Host ""
    Write-Host "Some tasks failed. Re-run this script as Administrator."
}
