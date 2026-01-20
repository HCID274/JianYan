#define MyAppName "简言"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "LHQ"
#define MyAppExeName "Jianyan.exe"
; onedir 模式，EXE 在 dist/Jianyan/ 目录下
#define SourcePath "..\dist\Jianyan"

[Setup]
AppId={{C6B5C7F8-1F6D-4D37-9D72-29D2C89D0D7D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; 默认安装到用户目录，避免权限问题
DefaultDirName={userpf}\Jianyan
DefaultGroupName={#MyAppName}
OutputDir=output
OutputBaseFilename=JianyanSetup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64
InfoBeforeFile=info_before.txt
; 不需要管理员权限
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=..\assets\icon_setup.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面图标"; GroupDescription: "附加任务"; Flags: unchecked

[Dirs]
Name: "{app}\models"; Permissions: users-modify
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\temp"; Permissions: users-modify

[Files]
; 主程序 EXE
Source: "{#SourcePath}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; PyInstaller 的 _internal 目录（包含所有依赖）
Source: "{#SourcePath}\_internal\*"; DestDir: "{app}\_internal"; Flags: recursesubdirs createallsubdirs ignoreversion
; 模型文件（从源码目录复制，保持结构）
Source: "..\models\*"; DestDir: "{app}\models"; Flags: recursesubdirs createallsubdirs
; data 目录（如果存在）
Source: "{#SourcePath}\data\*"; DestDir: "{app}\data"; Flags: recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]

function IsSystemProtectedDir(Path: string): Boolean;
var
  lowerPath: string;
begin
  lowerPath := Lowercase(Path);
  Result := (Pos(':\windows', lowerPath) = 2) or
            (Pos(':\program files', lowerPath) = 2) or
            (Pos(':\program files (x86)', lowerPath) = 2);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if IsSystemProtectedDir(WizardForm.DirEdit.Text) then
    begin
      MsgBox('请不要安装到系统保护目录（如 C:\Program Files）。建议选择普通可写目录，例如 D:\Apps 或您的用户目录。', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    MsgBox('温馨提示：' + #13#10 + #13#10 +
           '为了获得最佳体验，建议您在首次启动后：' + #13#10 +
           '1. 点击任务栏右下角的"向上箭头"' + #13#10 +
           '2. 找到"简言"图标并将其拖拽到任务栏上固定' + #13#10 +
           '这样可以方便您随时查看状态和使用。', mbInformation, MB_OK);
  end;
end;
