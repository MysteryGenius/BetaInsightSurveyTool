[Setup]
AppId={{166AD19C-88F9-4C02-8531-B2D4C0BF394D}
AppName=SurveyTool
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\SurveyTool
DefaultGroupName=SurveyTool
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename={#MyOutputBaseName}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\SurveyTool\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\SurveyTool"; Filename: "{app}\SurveyTool.exe"
Name: "{userdesktop}\SurveyTool"; Filename: "{app}\SurveyTool.exe"

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; \
    Parameters: "/silent /install"; \
    StatusMsg: "Installing WebView2 Runtime..."; \
    Check: not IsWebView2Installed

[Code]
function IsWebView2Installed: Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
    or RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;
