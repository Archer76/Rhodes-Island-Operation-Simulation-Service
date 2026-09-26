; R.I.O.S. 安装脚本（Inno Setup 6）
;
; 用法（Inno **本机还没装**，所以这份还没编译过一次 —— 见下面的"未核"）：
;
;   ISCC.exe /DAppVersion=0.3.0 ^
;            /DSrcDir="D:\home\DSH\ak-tactic\out\release\rios-v0.3.0" ^
;            tools\rios_setup.iss
;
; 版本号与 tag 名按目标判据 7 要先跟博士确认一次；本文件把版本号做成**必填参数**，
; 就是为了不让它悄悄写死一个。
;
; ## 三个不做会出事的决定
;
; 1. **装到用户目录、不要管理员**（`PrivilegesRequired=lowest` +
;    `{localappdata}\Programs`）。理由不是"免得 UAC 烦人"，而是**功能性的**：
;    发布树的数据根是 `eng/data/`（迁移图 §12.7 ①：Python 侧硬编码
;    `parents[2]/data`），而玩家**必须**能往那里放 156 MB 的 gamedata 与派生库。
;    装进 `Program Files` 的话，那一步会被 UAC 挡住 —— 安装器"成功"了，
;    玩家却做不完首次运行。
; 2. **`SHA256SUMS.txt` 不进包**（`Excludes`）。按 §12.6 的判据逐个文件问
;    "删掉它程序跑不起来吗"：它是**校验用**的，不是运行时必须 ⇒ 不进。
;    它在构建树里留着（发布说明要用），但不进安装包。
; 3. **卸载不许删玩家的数据**：`eng/data/` 是玩家自己取的（可能几百 MB），
;    卸载时**问一句**再决定（§12.5 四件里的"要留的先问"）。
;    Inno 默认只删自己装过的文件，所以不写任何 `[UninstallDelete]` 就是"保留"。

#ifndef AppVersion
  #error 必须用 /DAppVersion=<版本号>（如 0.3.0）指定 —— 不许写死在这里
#endif
#ifndef SrcDir
  #error 必须用 /DSrcDir=<拆分发布树>（tools/build_release.py 的产物目录）指定
#endif

#define AppName "R.I.O.S. 作战演算"
#define AppPublisher "Archer76"
#define AppURL "https://github.com/Archer76/Rhodes-Island-Operation-Simulation-Service"
#define AppExeName "启动.cmd"

[Setup]
; AppId 是「同一个程序」的身份证：换掉它 = 变成另一个程序（升级会装成两份、卸载卸不干净）。
; ⚠ 第一次发出去之后就**不许再改**。
AppId={{8B0A0D3E-6C71-4E62-9A4B-2F5C7D1E3A90}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={localappdata}\Programs\RIOS
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\out\release
OutputBaseFilename=RIOS-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName} {#AppVersion}

[Languages]
; Inno 6 自带的是英文语言文件；中文（ChineseSimplified.isl）在"非官方语言包"里，
; 各版本是否随装不一样 ⇒ 这里**只用自带的那份**，别让编译因为缺一个 .isl 直接失败。
; 中文出现在向导正文里（见 [Code]，那是我们的字，不依赖语言文件）。
Name: "en"; MessagesFile: "compiler:Default.isl"

[Files]
; 整棵拆分树，除了校验清单（§12.6：它不是运行时必须的）。
; ★ `eng/data` 不在这棵树里（data 与 Python 运行时不随包，§12.5）
;   ⇒ 玩家自己建的 `eng/data` 不会被覆盖，也不会被卸载带走。
Source: "{#SrcDir}\*"; DestDir: "{app}"; \
    Excludes: "SHA256SUMS.txt"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Run]
; 装完可以让玩家直接起一次（首启那几步的提示由启动器自己的预检打印）。
Filename: "{app}\{#AppExeName}"; Description: "现在启动 R.I.O.S."; \
    Flags: postinstall nowait skipifsilent shellexec

[Code]
// 首次运行不是"构建数据"一步，是三步（迁移图 §12.5）。
// 这段话必须出现在**安装向导里**：装完的目录里一份文档也没有（§12.6），
// 离线用户拿不到任何别的说明。
procedure InitializeWizard();
var
  Page: TOutputMsgWizardPage;
begin
  Page := CreateOutputMsgPage(wpWelcome,
    '装完之后还要你自己做两件事',
    '安装包只放运行时必须的文件，游戏数据与 Python 都不在里面。',
    '1) 装 Python（若机器上还没有）—— 到 python.org 自行下载；' + #13#10 +
    '   扫码登录还要 pip install qrcode，其余功能不受影响。' + #13#10 + #13#10 +
    '2) 取游戏数据，放到 eng\data\gamedata\ ——' + #13#10 +
    '   这一步**不能构建，只能下载**（约 156 MB）。' + #13#10 +
    '   地址与说明见：{#AppURL}/blob/main/docs/data-sources.md' + #13#10 + #13#10 +
    '做完这两步，双击目录里的 启动.cmd 即可；' + #13#10 +
    '启动器会自己逐项检查，缺什么会具名告诉你。');
end;

// 卸载：玩家自己取的数据**先问再删**（§12.5 四件之一）。
function InitializeUninstall(): Boolean;
var
  DataDir: String;
begin
  Result := True;
  DataDir := ExpandConstant('{app}\eng\data');
  if DirExists(DataDir) then
  begin
    if MsgBox('eng\data 里有你自己取的游戏数据（可能几百 MB）。' + #13#10 + #13#10 +
              '选「是」= 连它一起删掉；选「否」= 保留它，只卸载程序。',
              mbConfirmation, MB_YESNO) = IDYES then
      DelTree(DataDir, True, True, True);
  end;
end;
