; Inno Setup 6 script for the Windows installer. packaging/build.py runs it after PyInstaller and passes:
;   /DAppVersion=1.2.3 /DSourceDir=<packaging\dist\AnatomyExplorer> /DOutputDir=<...> /DOutputName=<...> /DIconFile=<...>
; It installs for the current user by default (no administrator prompt, into %LOCALAPPDATA%\Programs); the
; first page lets someone with admin rights choose "all users" (Program Files) instead. Study progress lives in
; %LOCALAPPDATA%\AnatomyExplorer and is kept on uninstall, so reinstalling or upgrading never loses it.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\packaging\dist\AnatomyExplorer"
#endif
#ifndef OutputDir
  #define OutputDir "..\packaging\dist\release"
#endif
#ifndef OutputName
  #define OutputName "AnatomyExplorer-Setup-Windows"
#endif
#ifndef IconFile
  #define IconFile "..\app\resources\icon.ico"
#endif

#define AppName "Anatomy Explorer"
#define AppExe "AnatomyExplorer.exe"

[Setup]
; never change AppId: it is how an upgrade finds the installed copy
AppId={{BF742270-7363-48E6-81D2-B588178D84A6}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Anatomy Explorer
AppPublisherURL=https://github.com/ethanprince4/AnatomyExplorer
AppSupportURL=https://github.com/ethanprince4/AnatomyExplorer/issues
AppUpdatesURL=https://github.com/ethanprince4/AnatomyExplorer/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; ~1.5 GB of mostly already-compressed data: non-solid LZMA2 keeps build time and memory sane
Compression=lzma2/normal
SolidCompression=no
LZMAUseSeparateProcess=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; an upgrade replaces the whole program folder, so files dropped from a newer build do not linger
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
