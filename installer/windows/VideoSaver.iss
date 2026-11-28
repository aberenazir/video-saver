; Inno Setup recipe: turns the PyInstaller folder (dist\Video Saver) into "Video Saver Setup.exe".
; Built by .github/workflows/build.yml:  iscc /DAppVersion=2.0 installer\windows\VideoSaver.iss
; Installs for the current user only (no admin password), adds a Start menu entry and an uninstaller.
; Settings and the saved list (%APPDATA%\Video Saver) and the videos themselves are never removed.

#ifndef AppVersion
  #define AppVersion "2.0"
#endif

[Setup]
AppId={{6F1C7E52-3B8D-4E0A-9C64-7A1E5D2B9F31}
AppName=ThumbStudio Video Saver
AppVersion={#AppVersion}
AppVerName=ThumbStudio Video Saver {#AppVersion}
AppPublisher=ThumbStudio Video Saver
DefaultDirName={localappdata}\Programs\Video Saver
DefaultGroupName=ThumbStudio Video Saver
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
Name: "desktopicon"; Description: "Put ThumbStudio Video Saver on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\Video Saver\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; shortcuts from before the rename (they had the old name; the new ones replace them)
Type: files; Name: "{group}\Video Saver.lnk"
Type: files; Name: "{userdesktop}\Video Saver.lnk"

[Icons]
Name: "{group}\ThumbStudio Video Saver"; Filename: "{app}\Video Saver.exe"
Name: "{userdesktop}\ThumbStudio Video Saver"; Filename: "{app}\Video Saver.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Video Saver.exe"; Description: "Open ThumbStudio Video Saver now"; Flags: nowait postinstall skipifsilent
; an update from inside the app runs this Setup silently: then open the new version straight away
Filename: "{app}\Video Saver.exe"; Flags: nowait skipifnotsilent
