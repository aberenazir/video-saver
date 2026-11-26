; Inno Setup recipe: turns the PyInstaller folder (dist\Video Saver) into "Video Saver Setup.exe".
; Built by .github/workflows/build.yml:  iscc /DAppVersion=2.0 installer\windows\VideoSaver.iss
; Installs for the current user only (no admin password), adds a Start menu entry and an uninstaller.
; Settings and the saved list (%APPDATA%\Video Saver) and the videos themselves are never removed.

#ifndef AppVersion
  #define AppVersion "2.0"
#endif

[Setup]
AppId={{6F1C7E52-3B8D-4E0A-9C64-7A1E5D2B9F31}
AppName=Video Saver
AppVersion={#AppVersion}
AppVerName=Video Saver {#AppVersion}
AppPublisher=Video Saver
DefaultDirName={localappdata}\Programs\Video Saver
DefaultGroupName=Video Saver
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Video Saver Setup
SetupIconFile=..\AppIcon.ico
UninstallDisplayIcon={app}\Video Saver.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put Video Saver on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\Video Saver\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Video Saver"; Filename: "{app}\Video Saver.exe"
Name: "{userdesktop}\Video Saver"; Filename: "{app}\Video Saver.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Video Saver.exe"; Description: "Open Video Saver now"; Flags: nowait postinstall skipifsilent
; an update from inside the app runs this Setup silently: then open the new version straight away
Filename: "{app}\Video Saver.exe"; Flags: nowait skipifnotsilent
