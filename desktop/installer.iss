; The desktop app's installer (Inno Setup 6), built by desktop/build.ps1 from
; PyInstaller's folder and the launcher. Per user, no admin: the app goes to
; %LOCALAPPDATA%\Programs\Personal Calendar; its data, in
; %LOCALAPPDATA%\Personal Calendar, is the app's own (app/config.py) and is
; kept through upgrades and uninstalls.
;
; The launcher, Personal Calendar.exe, is what the shortcuts start; it starts
; the version current.txt names, each in a folder of its own beside it
; (app-<commit>), so an update can stage the next one while the app runs
; (desktop/launcher.cs, app/desktop/update.py).

#ifndef AppVersion
  #error Pass /DAppVersion=... (build.ps1 does)
#endif
#ifndef AppFolder
  #error Pass /DAppFolder=app-... (build.ps1 does)
#endif
#ifndef BuildDir
  #error Pass /DBuildDir=... (build.ps1 does)
#endif

#define AppName "Personal Calendar"
#define AppExe "Personal Calendar.exe"
; As in app/desktop: the taskbar groups the app's windows under its shortcut by this id.
#define AppUserModelID "Oscar.PersonalCalendar"
#define Port "8377"

[Setup]
; app/desktop/update.py sets the version in Installed apps by it.
AppId={{6C1B0E5A-3F4B-4E8C-9C1D-2B7A5E9F4D21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Oscar
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Personal-Calendar-Setup
SetupIconFile=..\app\static\icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The app is asked to quit before files are replaced (PrepareToInstall below).
CloseApplications=no
RestartApplications=no

[Tasks]
Name: "autostart"; Description: "Start {#AppName} when I sign in, in the tray (Claude, reminders and the phone need it running)"
Name: "desktopicon"; Description: "A desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BuildDir}\launcher\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\dist\{#AppName}\*"; DestDir: "{app}\{#AppFolder}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BuildDir}\current.txt"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; An upgrade replaces every version before it whole, and the layout from
; before versions had folders, so nothing stale lingers.
Type: filesandordirs; Name: "{app}\app-*"
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
; The versions updates staged beside the installed one.
Type: filesandordirs; Name: "{app}\app-*"
Type: files; Name: "{app}\current.tmp"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --background"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; Through Explorer, as the Start menu would: a program Setup starts itself
; inherits its RedirectionGuard mitigation, under which the app's Update
; (uv, behind its Python's junction) cannot build.
Filename: "{win}\explorer.exe"; Parameters: """{app}\{#AppExe}"""; Description: "Open {#AppName}"; Flags: nowait postinstall

[Code]
// The running app quits when asked over its own server (POST /desktop/quit,
// app/desktop); this waits until it has, so no file is in use.
function AppRunning(): Boolean;
begin
  Result := CheckForMutexes('Local\{#AppUserModelID}');
end;

procedure QuitApp();
var
  Request: Variant;
  Waited: Integer;
begin
  if not AppRunning() then
    Exit;
  try
    Request := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Request.Open('POST', 'http://127.0.0.1:{#Port}/desktop/quit', False);
    Request.SetRequestHeader('Content-Type', 'application/json');
    Request.Send('');
  except
    Log('The app did not answer its quit request: ' + GetExceptionMessage());
  end;
  Waited := 0;
  while AppRunning() and (Waited < 30000) do
  begin
    Sleep(250);
    Waited := Waited + 250;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  QuitApp();
  if AppRunning() then
    Result := '{#AppName} is still running. Quit it from its tray icon, then try again.'
  else
    Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  QuitApp();
  Result := not AppRunning();
  if not Result then
    MsgBox('{#AppName} is still running. Quit it from its tray icon, then try again.', mbError, MB_OK);
end;
