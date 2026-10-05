<#
    Updates the installed desktop app to a commit of its repo (-Repo). Started
    by the app (app/desktop/update.py), in the background, with no window,
    from the copy bundled with it: what it takes is always what that app
    passes, whatever the repo has checked out.

    The commit is built in a worktree of the app's own, so whatever is
    uncommitted in the repo stays out (desktop\build.ps1). The worktree is
    kept between updates, beside the status file, with its Python
    environment, which then only changes with the libraries. The build is
    staged: its version's folder put in the install's (-Install), beside the
    running one, and the status file the app reads says so, for its Restart.
    It reuses the running version when its libraries are the same
    (build.ps1 -Reuse), and builds no installer. The versions before the
    running one go. A failure is written to the status file, and why to
    data\logs\update.log beside it.

    An app from before versions had folders of their own passes no -Install;
    the installer then replaces it, quitting it and opening the new one, and
    is left in the repo's build\ for another machine.
#>

param(
    [Parameter(Mandatory)][string]$Status,
    [Parameter(Mandatory)][string]$Sha,
    [string]$Install,
    # The repo this script is in, for an app from before the script was
    # bundled with it, which runs the repo's copy and passes no -Repo.
    [string]$Repo = (Split-Path -Parent $PSScriptRoot)
)

# Failures are read from exit codes and exceptions: Windows PowerShell would
# take the native tools' progress on stderr for errors.
$ErrorActionPreference = "Continue"
$data = Split-Path -Parent $Status
$log = Join-Path $data "logs\update.log"
# The app's own worktree, by its data folder: two apps (homes of their own)
# can update at once, and one app never runs two updates.
$work = Join-Path $data "update-worktree"
$clock = [Diagnostics.Stopwatch]::StartNew()

function Write-Log([string]$line) {
    "$(Get-Date -Format s) $line ($([int]$clock.Elapsed.TotalSeconds)s in)" | Out-File -Append -Encoding utf8 $log
}

# Everything a command writes, into the log as UTF-8 (Windows PowerShell's
# own redirection writes UTF-16).
function Invoke-Logged([scriptblock]$command) {
    & $command *>&1 | ForEach-Object { "$_" } | Out-File -Append -Encoding utf8 $log
}

function Remove-Worktree([string]$path) {
    Set-Location $repo
    if (Test-Path $path) {
        Invoke-Logged { git -C $repo worktree remove --force $path }
        Remove-Item -Recurse -Force $path -ErrorAction SilentlyContinue
    }
    Invoke-Logged { git -C $repo worktree prune }
}

# The worktree at $Sha and clean, but for its Python environment; made
# afresh when it cannot be.
function Open-Worktree {
    if (Test-Path (Join-Path $work ".git")) {
        Invoke-Logged { git -C $work checkout --quiet --force --detach $Sha }
        if (-not $LASTEXITCODE) {
            Invoke-Logged { git -C $work clean -ffdxq -e /.venv }
            if (-not $LASTEXITCODE) { return $true }
        }
        Write-Log "The worktree could not be reused; making it afresh"
    }
    Remove-Worktree $work
    Invoke-Logged { git -C $repo worktree add --detach $work $Sha }
    return -not $LASTEXITCODE
}

# (Not $status: PowerShell's names ignore case, and it would hide $Status.)
function Set-Status([hashtable]$fields) {
    $fields | ConvertTo-Json | Out-File -Encoding utf8 $Status
}

function Fail([string]$why) {
    Write-Log $why
    Set-Status @{ state = "failed"; sha = $Sha; log = $log }
    exit 1
}

New-Item -ItemType Directory -Force (Split-Path -Parent $log) | Out-Null
"$(Get-Date -Format s) Updating to $Sha from $repo" | Out-File -Encoding utf8 $log

# Where updates were built before they kept a worktree: in TEMP, by the
# status file's name.
$before = [BitConverter]::ToString([Security.Cryptography.SHA1]::Create().ComputeHash(
    [Text.Encoding]::UTF8.GetBytes($Status.ToLowerInvariant()))).Replace("-", "").Substring(0, 8)
Remove-Worktree (Join-Path $env:TEMP "personal-calendar-update-$before")

if (-not (Open-Worktree)) { Fail "Could not check out $Sha" }
Write-Log "Checked out $Sha"

# The running version, for the build to reuse.
$reuse = $null
if ($Install) {
    try {
        $running = [IO.File]::ReadAllText((Join-Path $Install "current.txt")).Trim()
        $reuse = Join-Path $Install $running
    } catch {
        Fail "Could not read the running version: $_"
    }
}

try {
    if ($Install) {
        Invoke-Logged { & (Join-Path $work "desktop\build.ps1") -NoInstaller -Reuse $reuse }
    } else {
        Invoke-Logged { & (Join-Path $work "desktop\build.ps1") -Install }
    }
} catch {
    Fail "The update failed: $_"
}
Write-Log "Built $Sha"

if ($Install) {
    try {
        $folder = [IO.File]::ReadAllText((Join-Path $work "build\current.txt")).Trim()
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
} else {
    New-Item -ItemType Directory -Force (Join-Path $repo "build") | Out-Null
    Copy-Item (Join-Path $work "build\Personal-Calendar-Setup.exe") (Join-Path $repo "build") -Force
    Write-Log "Installed $Sha; its installer is in $repo\build"
}
