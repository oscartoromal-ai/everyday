<#
    Updates the installed desktop app to a commit of its repo. Started by the
    app's Update button (app/desktop/update.py), in the background, with
    no window.

    The commit is built in a worktree of its own, so whatever is uncommitted
    in the repo stays out, then installed (desktop\build.ps1 -Install), which
    quits the app and opens the new one. Its installer is left in the repo's
    build\ for another machine. A failure is written to the status file the
    app reads, and why to data\logs\update.log beside it.
#>

param(
    [Parameter(Mandatory)][string]$Status,
    [Parameter(Mandatory)][string]$Sha
)

# Failures are read from exit codes and exceptions: Windows PowerShell would
# take the native tools' progress on stderr for errors.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$log = Join-Path (Split-Path -Parent $Status) "logs\update.log"
$work = Join-Path $env:TEMP "personal-calendar-update"

function Write-Log([string]$line) {
    "$(Get-Date -Format s) $line" | Out-File -Append -Encoding utf8 $log
}

function Remove-Worktree {
    Set-Location $repo
    if (Test-Path $work) {
        git -C $repo worktree remove --force $work *>> $log
        Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }
    git -C $repo worktree prune *>> $log
}

function Fail([string]$why) {
    Write-Log $why
    @{ state = "failed"; sha = $Sha; log = $log } | ConvertTo-Json | Out-File -Encoding utf8 $Status
    Remove-Worktree
    exit 1
}

New-Item -ItemType Directory -Force (Split-Path -Parent $log) | Out-Null
"$(Get-Date -Format s) Updating to $Sha from $repo" | Out-File -Encoding utf8 $log

Remove-Worktree
git -C $repo worktree add --detach $work $Sha *>> $log
if ($LASTEXITCODE) { Fail "Could not check out $Sha" }

try {
    & (Join-Path $work "desktop\build.ps1") -Install *>> $log
} catch {
    Fail "The update failed: $_"
}

New-Item -ItemType Directory -Force (Join-Path $repo "build") | Out-Null
Copy-Item (Join-Path $work "build\Personal-Calendar-Setup.exe") (Join-Path $repo "build") -Force
Write-Log "Installed $Sha; its installer is in $repo\build"
Remove-Worktree
