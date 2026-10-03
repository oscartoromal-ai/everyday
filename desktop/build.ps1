<#
    Builds the desktop app's installer: build\Personal-Calendar-Setup.exe.

        .\desktop\build.ps1            # build it
        .\desktop\build.ps1 -Install   # build it and install it over the running app

    PyInstaller freezes the app (desktop\personal-calendar.spec) into
    build\dist\Personal Calendar; Inno Setup (desktop\installer.iss, its
    compiler found where winget installs it) wraps that into the installer.
    Installing quits the running app, replaces it, and opens the new one; its
    database migrates as it starts.
#>

param([switch]$Install)

# Failures are read from exit codes: Windows PowerShell would take the
# native tools' progress on stderr for errors.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 is not installed: winget install JRSoftware.InnoSetup --scope user" }

# The version: pyproject's, and the commit it was built from (with a + when
# the working tree had changes), as Windows' Installed apps shows it.
$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
$commit = (git rev-parse --short HEAD).Trim()
if (git status --porcelain --untracked-files=no -- app migrations desktop config.toml pyproject.toml uv.lock) { $commit += "+" }
$numeric = ($version -split '[^0-9]+' | Where-Object { $_ } | Select-Object -First 3) -join ','

New-Item -ItemType Directory -Force build | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($numeric,0), prodvers=($numeric,0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('ProductName', 'Personal Calendar'),
      StringStruct('FileDescription', 'Personal Calendar'),
      StringStruct('ProductVersion', '$version ($commit)'),
      StringStruct('FileVersion', '$version'),
      StringStruct('OriginalFilename', 'Personal Calendar.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Out-File -Encoding utf8 build\version.txt

# What the app was built from, for its Update button (app/desktop/update.py):
# the commit, and the repo itself even when this is a worktree of it.
$repo = Split-Path -Parent (git rev-parse --path-format=absolute --git-common-dir).Trim()
@{ sha = (git rev-parse HEAD).Trim(); commit = $commit; repo = $repo } |
    ConvertTo-Json | Out-File -Encoding utf8 build\build-info.json

uv run pyinstaller desktop\personal-calendar.spec --noconfirm --clean --distpath build\dist --workpath build\work
if ($LASTEXITCODE) { throw "PyInstaller failed" }

& $iscc /Q "/DAppVersion=$version ($commit)" "/DSourceDir=$root\build\dist\Personal Calendar" "/O$root\build" desktop\installer.iss
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
