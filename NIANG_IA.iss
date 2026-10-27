#define AppName "NIANG IA"
#define AppVersion "1.0.0"
#define SourceDir AddBackslash(SourcePath) + "dist\NIANG_IA_" + AppVersion

[Setup]
AppId={{AC51AB64-08DA-4BC6-9CE1-1D5D0AD4B304}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\NIANG IA
DefaultGroupName=NIANG IA
OutputDir=dist
OutputBaseFilename=NIANG_IA_Setup_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NIANG IA"; Filename: "{app}\START_NIANG_IA.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\NIANG IA"; Filename: "{app}\START_NIANG_IA.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\START_NIANG_IA.bat"; Description: "Launch NIANG IA"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent
