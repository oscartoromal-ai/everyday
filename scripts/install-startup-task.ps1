<#
    Registers a Windows Task Scheduler task that starts Personal Calendar,
    hidden, whenever Oscar logs on -- so the app is effectively always up
    (the hook-spool design in SPEC.md section 6 assumes this).

    Run this once, manually, from an elevated or normal PowerShell prompt:
        .\scripts\install-startup-task.ps1

    To remove it later:
        Unregister-ScheduledTask -TaskName "Personal Calendar" -Confirm:$false
#>

$ErrorActionPreference = "Stop"

$taskName = "Personal Calendar"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runScript = Join-Path $repoRoot "scripts\run-app.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runScript`""

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Runs Oscar's Personal Calendar app hidden at logon." `
    -Force

Write-Host "Registered scheduled task '$taskName'. It will start on next logon."
Write-Host "To start it now: Start-ScheduledTask -TaskName '$taskName'"
