; Vox installer. Per-user, no admin needed for the app itself.
; Build with installer\build.ps1, or:
;   ISCC.exe /DAppVersion=1.0.0 installer\Vox.iss

#include "version.iss"

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8C3E1D42-5B7A-4F19-9E2C-6A1D8F0B3A57}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Vox-{#AppVersion}-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "vbcable"; Description: "Download VB-CABLE (the virtual microphone Vox feeds)"; GroupDescription: "Virtual microphone:"; Flags: checkedonce

[Files]
Source: "..\dist\Vox\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "install-vbcable.ps1"; DestDir: "{tmp}"; Flags: ignoreversion

[InstallDelete]
; PyInstaller's internal layout changes between versions; start clean.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{tmp}\install-vbcable.ps1"""; StatusMsg: "Opening the VB-CABLE installer..."; Flags: runhidden waituntilterminated; Tasks: vbcable
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeUninstall(): Boolean;
var
  Answer: Integer;
begin
  Result := True;
  if UninstallSilent then
    Exit;
  Answer := MsgBox(
    'Also delete your Vox voice profiles, settings and logs?' + #13#10 + #13#10 +
    'Choose No to remove only the program and keep them for a later install.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
  if Answer = IDYES then
  begin
    DelTree(ExpandConstant('{userappdata}\Vox'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\Vox'), True, True, True);
  end;
end;
