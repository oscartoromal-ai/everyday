<#
    Builds the desktop app: its version's folder, build\dist\Personal
    Calendar, and the installer around it, build\Personal-Calendar-Setup.exe.

        .\desktop\build.ps1            # build it
        .\desktop\build.ps1 -Install   # build it and install it over the running app

    PyInstaller freezes the app (desktop\personal-calendar.spec) into the
    version's folder: Python and the libraries frozen, the app's own code and
    files as they are. The C# compiler that comes with Windows builds its
    launcher (desktop\launcher.cs); Inno Setup (desktop\installer.iss, its
    compiler found where winget installs it) wraps both into the installer.
    Installing quits the running app, replaces it, and opens the new one; its
    database migrates as it starts.

    An update (desktop\update.ps1) stages the version's folder itself, so it
    passes -NoInstaller, and passes the running version's folder as -Reuse:
    when that one's libraries are this tree's (its runtime, in its
    build-info.json), the build is a copy of it with this tree's app put in,
    in seconds rather than the minutes freezing takes. Either way the program
    built checks itself (--self-check, app/selfcheck.py), compiling the app's
    code; a reused build that fails it is frozen anew.
#>

param(
    [switch]$Install,
    [switch]$NoInstaller,
    # An installed version's folder (app-<commit>), to build from when its
    # libraries are this tree's.
    [string]$Reuse
)

# Failures are read from exit codes: Windows PowerShell would take the
# native tools' progress on stderr for errors.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if ($Install -and $NoInstaller) { throw "-Install needs the installer: drop -NoInstaller" }

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $NoInstaller -and -not $iscc) { throw "Inno Setup 6 is not installed: winget install JRSoftware.InnoSetup --scope user" }
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not $NoInstaller -and -not (Test-Path $csc)) { throw "The .NET Framework 4 C# compiler is missing: $csc" }

$dist = Join-Path $root "build\dist\Personal Calendar"
$internal = Join-Path $dist "_internal"

# What the frozen part of a build is made from: the libraries, how they are
# frozen, and what goes into the program itself. Two builds of the same
# runtime differ only in the app's own files, which -Reuse puts in.
function Get-Runtime {
    $files = "uv.lock", "pyproject.toml", "desktop\personal-calendar.spec", "desktop\main.py",
        "desktop\version-info.txt", "app\static\icons\app.ico"
    $hashes = git hash-object -- $files
    if ($LASTEXITCODE) { throw "The runtime's files could not be read" }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($hashes -join "`n"))
    -join ([Security.Cryptography.SHA256]::Create().ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") })
}

function Copy-Folder([string]$from, [string]$to) {
    robocopy $from $to /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
    # Robocopy's codes below 8 are successes.
    if ($LASTEXITCODE -ge 8) { throw "Could not copy $from to $to" }
    $global:LASTEXITCODE = 0
}

# This tree's app and its other files (desktop\app-files.txt) put in the
# version's folder, over the ones it has.
function Copy-AppFiles {
    Remove-Item -Recurse -Force (Join-Path $internal "app")
    Copy-Folder (Join-Path $root "app") (Join-Path $internal "app")
    foreach ($line in Get-Content (Join-Path $root "desktop\app-files.txt")) {
        if (-not $line.Trim() -or $line.StartsWith("#")) { continue }
        $source, $folder = -split $line
        $from = Join-Path $root $source
        $to = Join-Path $internal $folder
        if (Test-Path $from -PathType Container) {
            if (Test-Path $to) { Remove-Item -Recurse -Force $to }
            Copy-Folder $from $to
        } else {
            New-Item -ItemType Directory -Force $to | Out-Null
            Copy-Item -Force $from $to
        }
    }
}

# The program built checking itself (app/selfcheck.py); why not, on the console.
function Test-Build {
    $report = Join-Path $root "build\self-check.txt"
    Remove-Item $report -ErrorAction SilentlyContinue
    $check = Start-Process -FilePath (Join-Path $dist "Personal Calendar.exe") `
        -ArgumentList "--self-check", "`"$report`"" -PassThru
    # Its exit code is only kept with its handle taken while it runs.
    $null = $check.Handle
    $check.WaitForExit()
    if ($check.ExitCode -eq 0) { return $true }
    Write-Host "The build failed its self-check (exit $($check.ExitCode)):"
    if (Test-Path $report) { Get-Content $report | ForEach-Object { Write-Host "  $_" } }
    return $false
}

# The version: the changelog's (app/changelog.py: the change files, in the
# order master took them), and the commit it was built from (with a + when
# the working tree had changes), as Windows' Installed apps shows it.
$version = "$(uv run python -m app.changelog --version)".Trim()
if ($LASTEXITCODE -or -not $version) { throw "The changelog could not be read (uv run python -m app.changelog)" }
$commit = (git rev-parse --short HEAD).Trim()
if (git status --porcelain --untracked-files=no -- app migrations desktop config.toml pyproject.toml uv.lock changes) { $commit += "+" }
# The version's folder in the install, beside its launcher.
$folder = "app-$commit"
$runtime = Get-Runtime

New-Item -ItemType Directory -Force build | Out-Null
# What the app was built from, for its Update button (app/desktop/update.py):
# the commit, the version Installed apps lists, the repo itself even when
# this is a worktree of it, and its runtime, for the next update to reuse.
$repo = Split-Path -Parent (git rev-parse --path-format=absolute --git-common-dir).Trim()
@{ sha = (git rev-parse HEAD).Trim(); commit = $commit; version = "$version ($commit)"; repo = $repo; runtime = $runtime } |
    ConvertTo-Json | Out-File -Encoding utf8 build\build-info.json
# Every version and what it changed, for its Changelog: the installed app
# has no git history to read them from.
uv run python -m app.changelog --json build\changelog.json
if ($LASTEXITCODE) { throw "The changelog could not be written" }
# The version the launcher starts, once installed.
[IO.File]::WriteAllText("$root\build\current.txt", $folder)

$reused = $false
if ($Reuse) {
    $was = $null
    try { $was = Get-Content -Raw (Join-Path $Reuse "_internal\build-info.json") | ConvertFrom-Json } catch {}
    if ($was -and $was.runtime -eq $runtime) {
        Write-Host "Reusing $Reuse, whose libraries are this tree's"
        if (Test-Path build\dist) { Remove-Item -Recurse -Force build\dist }
        Copy-Folder $Reuse $dist
        Copy-AppFiles
        $reused = Test-Build
        if (-not $reused) { Write-Host "Freezing anew" }
    } else {
        Write-Host "Freezing anew: the libraries of $Reuse are not this tree's"
    }
}
if (-not $reused) {
    uv run pyinstaller desktop\personal-calendar.spec --noconfirm --clean --distpath build\dist --workpath build\work
    if ($LASTEXITCODE) { throw "PyInstaller failed" }
    if (-not (Test-Build)) { throw "The build failed its self-check" }
}
Write-Host "Built $dist ($version, $commit)"

if ($NoInstaller) { return }

New-Item -ItemType Directory -Force build\launcher | Out-Null
& $csc /nologo /target:winexe /optimize+ /win32icon:app\static\icons\app.ico "/out:build\launcher\Personal Calendar.exe" desktop\launcher.cs
if ($LASTEXITCODE) { throw "The launcher did not compile" }

& $iscc /Q "/DAppVersion=$version ($commit)" "/DAppFolder=$folder" "/DBuildDir=$root\build" "/O$root\build" desktop\installer.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }
$setup = Join-Path $root "build\Personal-Calendar-Setup.exe"
Write-Host "Built $setup ($version, $commit)"

if ($Install) {
    # Not Start-Process -Wait: it would wait on the app the installer opens too.
    $process = Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -PassThru
    $process.WaitForExit()
    if ($process.ExitCode) { throw "The installer failed ($($process.ExitCode))" }
    Write-Host "Installed"
}
