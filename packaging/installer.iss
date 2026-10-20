; Inno Setup 6 script for the Windows installer. packaging/build.py runs it after PyInstaller and passes:
;   /DAppVersion=1.2.3 /DSourceDir=<packaging\dist\LayeredHuman> /DOutputDir=<...> /DOutputName=<...> /DIconFile=<...>
; It installs for the current user by default (no administrator prompt, into %LOCALAPPDATA%\Programs); the
; first page lets someone with admin rights choose "all users" (Program Files) instead. Study progress lives in
; %LOCALAPPDATA%\AnatomyExplorer and is kept on uninstall, so reinstalling or upgrading never loses it.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\packaging\dist\LayeredHuman"
#endif
#ifndef OutputDir
  #define OutputDir "..\packaging\dist\release"
#endif
#ifndef OutputName
  #define OutputName "LayeredHuman-Setup-Windows"
#endif
#ifndef IconFile
  #define IconFile "..\app\resources\icon.ico"
#endif

#ifndef RepoDir
  #define RepoDir SourcePath + ".."
#endif

; build.py passes /DExperimental only for the experimental channel. Test whether it is defined, not its value: ISCC
; hands /D values over as text, and the text "0" counted as true, so v4.0.8 and earlier stable installers all
; installed as "Anatomy Explorer Experimental".
#ifdef Experimental
  #define AppName "Layered Human Experimental"
  #define LegacyAppName "Anatomy Explorer Experimental"
  #define ApplicationId "{{9CF5F0A1-BB14-4B56-85C2-17A6452C0430}"
#else
  #define AppName "Layered Human"
  #define LegacyAppName "Anatomy Explorer"
  #define ApplicationId "{{BF742270-7363-48E6-81D2-B588178D84A6}"
#endif
#define AppExe "LayeredHuman.exe"

[Setup]
; never change AppId: it is how an upgrade finds the installed copy
AppId={#ApplicationId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Layered Human
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
; ~1.5 GB of mostly already-compressed data (the atlas, the histology images and the 3D models): non-solid LZMA2
; keeps build time and memory sane
Compression=lzma2/normal
SolidCompression=no
LZMAUseSeparateProcess=yes
WizardStyle=modern
; the MIT licence of the app itself; third-party notices are installed beside it (see [Files])
LicenseFile={#RepoDir}\LICENSE
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; an upgrade replaces the whole program folder, so files dropped from a newer build do not linger
Type: filesandordirs; Name: "{app}\_internal"
; Replace the old public shortcuts while keeping its AppId and chosen install folder.
Type: files; Name: "{autoprograms}\{#LegacyAppName}.lnk"
Type: files; Name: "{autodesktop}\{#LegacyAppName}.lnk"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; copies of the notices at the top of the install folder, where people look for them (the bundle's own are in _internal)
Source: "{#RepoDir}\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "{#RepoDir}\THIRD_PARTY_LICENSES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
