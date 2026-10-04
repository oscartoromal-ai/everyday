<#
    Updates the installed desktop app to a commit of its repo. Started by the
    app's Update button (app/desktop/update.py), in the background, with
    no window.

    The commit is built in a worktree of its own, so whatever is uncommitted
    in the repo stays out (desktop\build.ps1), then staged: its version's
    folder put in the install's (-Install), beside the running one, and the
    status file the app reads says so, for its Restart. The versions before
    the running one go. Its installer is left in the repo's build\ for
    another machine. A failure is written to the status file, and why to
    data\logs\update.log beside it.

    An app from before versions had folders of their own passes no -Install;
    the installer then replaces it, quitting it and opening the new one.
#>

param(
    [Parameter(Mandatory)][string]$Status,
    [Parameter(Mandatory)][string]$Sha,
    [string]$Install
)

# Failures are read from exit codes and exceptions: Windows PowerShell would
# take the native tools' progress on stderr for errors.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$log = Join-Path (Split-Path -Parent $Status) "logs\update.log"
# A worktree of the app's own, by its status file: two apps (homes of their
# own) can update at once, and one app never runs two updates.
$app = [BitConverter]::ToString([Security.Cryptography.SHA1]::Create().ComputeHash(
    [Text.Encoding]::UTF8.GetBytes($Status.ToLowerInvariant()))).Replace("-", "").Substring(0, 8)
$work = Join-Path $env:TEMP "personal-calendar-update-$app"

function Write-Log([string]$line) {
    "$(Get-Date -Format s) $line" | Out-File -Append -Encoding utf8 $log
}

# Everything a command writes, into the log as UTF-8 (Windows PowerShell's
# own redirection writes UTF-16).
function Invoke-Logged([scriptblock]$command) {
    & $command *>&1 | ForEach-Object { "$_" } | Out-File -Append -Encoding utf8 $log
}

function Remove-Worktree {
    Set-Location $repo
    if (Test-Path $work) {
        Invoke-Logged { git -C $repo worktree remove --force $work }
        Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }
    Invoke-Logged { git -C $repo worktree prune }
}

# (Not $status: PowerShell's names ignore case, and it would hide $Status.)
function Set-Status([hashtable]$fields) {
    $fields | ConvertTo-Json | Out-File -Encoding utf8 $Status
}

function Fail([string]$why) {
    Write-Log $why
    Set-Status @{ state = "failed"; sha = $Sha; log = $log }
    Remove-Worktree
    exit 1
}

New-Item -ItemType Directory -Force (Split-Path -Parent $log) | Out-Null
"$(Get-Date -Format s) Updating to $Sha from $repo" | Out-File -Encoding utf8 $log

Remove-Worktree
Invoke-Logged { git -C $repo worktree add --detach $work $Sha }
if ($LASTEXITCODE) { Fail "Could not check out $Sha" }

try {
    if ($Install) {
        Invoke-Logged { & (Join-Path $work "desktop\build.ps1") }
    } else {
        Invoke-Logged { & (Join-Path $work "desktop\build.ps1") -Install }
    }
} catch {
    Fail "The update failed: $_"
}

if ($Install) {
    try {
        $folder = [IO.File]::ReadAllText((Join-Path $work "build\current.txt")).Trim()
        $running = [IO.File]::ReadAllText((Join-Path $Install "current.txt")).Trim()
        # The versions before the running one, and any half staged before.
        Get-ChildItem -Directory -Path $Install -Filter "app-*" |
            Where-Object { $_.Name -ne $running } |
            ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction Stop }
        $staged = Join-Path $Install $folder
        Move-Item (Join-Path $work "build\dist\Personal Calendar") $staged -ErrorAction Stop
    } catch {
        Fail "Could not stage the update: $_"
    }
    Set-Status @{ state = "staged"; sha = $Sha; app = $staged }
    Write-Log "Staged $Sha in $staged"
}

New-Item -ItemType Directory -Force (Join-Path $repo "build") | Out-Null
Copy-Item (Join-Path $work "build\Personal-Calendar-Setup.exe") (Join-Path $repo "build") -Force
Write-Log "Built $Sha; its installer is in $repo\build"
Remove-Worktree
