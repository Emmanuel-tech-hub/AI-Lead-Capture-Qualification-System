# Registers a Windows scheduled task that runs Recast Intelligence every 15 minutes while you are logged in.
# Delivery time, timezone and monitoring frequency are read from config.yaml on every run,
# so you never need to re-run this script after changing them.
# Run:  powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null
$bat = Join-Path $PSScriptRoot "run_tick.bat"
$taskName = "Recast Intelligence"

$action  = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Recast Intelligence newsletter (every 15 min; schedule lives in config.yaml)" -Force | Out-Null
Write-Host "Scheduled task '$taskName' installed. It runs every 15 minutes."
Write-Host "Remove it any time with:  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
