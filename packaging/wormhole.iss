; Inno Setup script for Wormhole (one-folder)
; Save as packaging/wormhole.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppName=Wormhole
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Wormhole
DefaultGroupName=Wormhole
OutputDir=.
OutputBaseFilename=wormhole-windows-installer
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\wormhole\*"; DestDir: "{app}\wormhole"; Flags: recursesubdirs

[Icons]
Name: "{group}\Wormhole (GUI)"; Filename: "wscript.exe"; Parameters: """{app}\Wormhole-GUI.vbs"""; IconFilename: "{app}\wormhole\wormhole.exe"
Name: "{group}\Wormhole (CLI)"; Filename: "{app}\wormhole\wormhole.exe"; WorkingDir: "{app}\wormhole"; IconFilename: "{app}\wormhole\wormhole.exe"
Name: "{userdesktop}\Wormhole (GUI)"; Filename: "wscript.exe"; Parameters: """{app}\Wormhole-GUI.vbs"""; IconFilename: "{app}\wormhole\wormhole.exe"

[Run]
Filename: "{app}\wormhole\wormhole.exe"; Parameters: "--version"; Flags: nowait postinstall skipifsilent
