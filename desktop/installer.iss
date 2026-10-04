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

[Messages]
WizardSelectComponents=Modules
SelectComponentsDesc=Which modules should this machine have?
SelectComponentsLabel2=Untick the modules you do not want here. Planner and Projects are always in. Run Setup again to change them.

; The modules, ticked or not on a page of their own: the app leaves out the
; ones unticked (WriteModules below). Setup remembers them for the next install.
[Types]
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "planner"; Description: "Planner and Projects: Today, Calendar, Projects"; Types: custom; Flags: fixed
Name: "health"; Description: "Health: Nutrition, Me, Garmin"; Types: custom
Name: "finances"; Description: "Finances: Spending, Accounts, Bills, Goals"; Types: custom
Name: "code"; Description: "Code: Repositories"; Types: custom

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

// The everyday files (SPEC.md, Agent runs): the folder for agentic work,
// asked on a page of its own after the modules, the system drive's
// everyday-files to start with, remembered for the next install.
var
  EverydayPage: TInputDirWizardPage;

// The modules page lists the modules alone: every module is the same files,
// so there is no size to show, and no preset to choose.
procedure InitializeWizard();
begin
  WizardForm.TypesCombo.Visible := False;
  WizardForm.ComponentsDiskSpaceLabel.Visible := False;
  WizardForm.ComponentsList.Top := WizardForm.TypesCombo.Top;

  EverydayPage := CreateInputDirPage(wpSelectComponents,
    'Everyday files', 'Where should the files for agentic work go?',
    'Setup makes this folder, with three folders in it: repos, each repository''s main clone; ' +
    'projects, each project''s context; and work, the folders agents work in.' + #13#10#13#10 +
    'A short path at the root of a drive keeps deep worktrees under Windows'' path length limit. ' +
    'Uninstalling keeps it.',
    False, '');
  EverydayPage.Add('');
  EverydayPage.Values[0] := GetPreviousData('EverydayFiles', ExpandConstant('{sd}\everyday-files'));
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'EverydayFiles', EverydayPage.Values[0]);
end;

// The everyday files' folders, made where missing. False when they cannot be.
function MakeEverydayFiles(): Boolean;
var
  Dir: String;
begin
  Dir := RemoveBackslashUnlessRoot(EverydayPage.Values[0]);
  Result := ForceDirectories(Dir + '\repos') and ForceDirectories(Dir + '\projects') and
    ForceDirectories(Dir + '\work');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = EverydayPage.ID) and not MakeEverydayFiles() then
  begin
    MsgBox('Setup could not make ' + EverydayPage.Values[0] + '. Choose a folder you can write to.',
      mbError, MB_OK);
    Result := False;
  end;
end;

// The modules unticked, for the app to leave out, and the everyday files'
// folder: install.toml in its home (app/config.py's [install] and
// [everyday_files]), written whole on every install.
procedure WriteInstallToml();
var
  Home, Without, Everyday: String;
  Modules: TArrayOfString;
  I: Integer;
begin
  Home := GetEnv('PC_HOME');
  if Home = '' then
    Home := ExpandConstant('{localappdata}\{#AppName}');
  Modules := ['health', 'finances', 'code'];
  Without := '';
  for I := 0 to GetArrayLength(Modules) - 1 do
    if not WizardIsComponentSelected(Modules[I]) then
    begin
      if Without <> '' then
        Without := Without + ', ';
      Without := Without + '"' + Modules[I] + '"';
    end;
  // A TOML string: its backslashes and quotes escaped.
  Everyday := RemoveBackslashUnlessRoot(EverydayPage.Values[0]);
  StringChangeEx(Everyday, '\', '\\', True);
  StringChangeEx(Everyday, '"', '\"', True);
  ForceDirectories(Home);
  if not SaveStringToFile(Home + '\install.toml',
    '# The modules unticked in Setup, which the app leaves out, and the folder for' + #13#10 +
    '# agentic work. Written by Setup: run it again to change them.' + #13#10 +
    '[install]' + #13#10 +
    'without = [' + Without + ']' + #13#10 + #13#10 +
    '[everyday_files]' + #13#10 +
    'dir = "' + Everyday + '"' + #13#10, False) then
    RaiseException('Could not write ' + Home + '\install.toml');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WriteInstallToml();
    // A silent install has no page to ask on; the app makes them as it starts.
    if not MakeEverydayFiles() then
      Log('Could not make the everyday files in ' + EverydayPage.Values[0]);
  end;
end;

function InitializeUninstall(): Boolean;
begin
  QuitApp();
  Result := not AppRunning();
  if not Result then
    MsgBox('{#AppName} is still running. Quit it from its tray icon, then try again.', mbError, MB_OK);
end;
