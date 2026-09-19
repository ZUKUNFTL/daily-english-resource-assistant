#ifndef ProjectRoot
  #error ProjectRoot must be supplied by build_installer.ps1
#endif
#ifndef AppVersion
  #define AppVersion "0.1.2"
#endif

#define AppName "每日英语听力资源助手"
#define AppExeName "每日英语听力资源助手.exe"
#define AppId "{{D9B3BAB7-6BF7-4AE8-93A1-96B39619A1BA}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ZUKUNFTL
AppPublisherURL=https://github.com/ZUKUNFTL/daily-english-resource-assistant
AppSupportURL=https://github.com/ZUKUNFTL/daily-english-resource-assistant/issues
DefaultDirName={localappdata}\Programs\DailyEnglishResourceAssistant
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#ProjectRoot}\installer-output
OutputBaseFilename=DailyEnglishResourceAssistant-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#ProjectRoot}\LICENSE
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#AppExeName}
VersionInfoVersion={#AppVersion}
VersionInfoCompany=ZUKUNFTL
VersionInfoDescription={#AppName} 安装程序
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: checkedonce

[Files]
Source: "{#ProjectRoot}\dist\每日英语听力资源助手\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\build\installer-runtime\argos_translate\*"; DestDir: "{app}\engine\argos_translate"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\work\models\argos\*"; DestDir: "{localappdata}\DailyEnglishResourceAssistant\work\models\argos"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\work\data\argos-translate\*"; DestDir: "{localappdata}\DailyEnglishResourceAssistant\work\data\argos-translate"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\work\cache\huggingface\hub\models--Systran--faster-whisper-small\*"; DestDir: "{localappdata}\DailyEnglishResourceAssistant\work\cache\huggingface\hub\models--Systran--faster-whisper-small"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\work\cache\huggingface\hub\models--Systran--faster-whisper-medium\*"; DestDir: "{localappdata}\DailyEnglishResourceAssistant\work\cache\huggingface\hub\models--Systran--faster-whisper-medium"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{localappdata}\DailyEnglishResourceAssistant\data"
Name: "{localappdata}\DailyEnglishResourceAssistant\work\cache"
Name: "{localappdata}\DailyEnglishResourceAssistant\work\tmp"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
