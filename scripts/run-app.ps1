<#
    Runs Personal Calendar in the foreground of the current shell.
    Used directly for manual runs, and as the target of the Task Scheduler
    at-logon task installed by install-startup-task.ps1.
#>

$ErrorActionPreference = "Stop"

$env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

uv run personal-calendar
