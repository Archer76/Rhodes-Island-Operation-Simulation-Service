; R.I.O.S. 安装脚本（Inno Setup 6）
;
; 用法（Inno **本机还没装**，所以这份还没编译过一次 —— 见下面的"未核"）：
;
;   ISCC.exe /DAppVersion=0.3.0 ^
;            /DSrcDir="<仓库根>\out\release\rios-v0.3.0" ^
;            tools\rios_setup.iss
;
; ★ 路径一律写成**仓库相对**形式（本机绝对路径不进仓库，博士 2026-09-26 令）。
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
#define AppExeName "rios-tui.exe"

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
; 装完可以让玩家直接起一次（首启那几步由入口**自己**完成：无参数运行时它先跑一遍准备，
; 缺什么、怎么补都由它自己打印 —— 发布形态里没有启动器这一类中间件了，§12.9）。
; ★ 保留 `shellexec`：它与"双击"同一条路（走 ShellExecute，控制台窗口该有就有），
;   换成 exe 之后这一条依然对；`skipifsilent` 让静默安装（判据用的那种）不弹这个窗口。
Filename: "{app}\{#AppExeName}"; Description: "现在启动 R.I.O.S."; \
    Flags: postinstall nowait skipifsilent shellexec

[UninstallDelete]
; Python 一 import 我们的包，就往**代码目录旁**写 `__pycache__`（可重建）。
; 那些文件不是安装器装的 ⇒ Inno 默认不管，不写这一段的话「卸载干净」这条要打折：
; 玩家卸完会在 eng/ 下看到一堆 .pyc 残骸。
; ★ 为什么这里只有**两条**：`ak_tactic` 是**有子包**的（battle/db/frontend/gamedata/
;   operator/prts/simgo/tui，每个都自己写一份 `__pycache__`），而**通配在这里不生效** ——
;   实测（2026-09-27，装完自查造了三级夹具）：`Name: "{app}\eng\ak_tactic\*\__pycache__"`
;   这一行**一个都没删掉**，卸载后子包那层的 .pyc 还在（判据具名报的就是它）。
;   ⇒ 子包那一层改由 `[Code]` 的 `PurgePycache` 递归清（见下），这里留两条**声明式**的
;   顶层路径：它们与递归那套互为冗余，但让人一眼看得见"卸载会清代码缓存"这件事。
; ★ 只点 eng/ 下的**代码缓存**：玩家的数据在 `{app}\eng\data`，那一段走
;   InitializeUninstall 的「先问再删」，这里一条都不许碰到它（`data` 不在下面任何一行里）。
Type: filesandordirs; Name: "{app}\eng\ak_tactic\__pycache__"
Type: filesandordirs; Name: "{app}\eng\tools\__pycache__"

[Code]
// PurgePycache 递归删掉某棵树下的所有 `__pycache__`（可重建的代码缓存）。
//
// ★ **只从 `eng\ak_tactic` 与 `eng\tools` 两棵树往下走，绝不从 `eng` 开始**：
//   玩家的数据就在 `eng\data`（与那两棵同级），从 `eng` 递归就有扫到它的风险，
//   而那个目录是按「先问再删」处置的 —— 这里连碰一下都不许。从这两棵走，
//   `eng\data` 在构造上就不可能被访问到（它是兄弟，不是后代）。
// ★ 为什么不用 `[UninstallDelete]` 的通配：实测它不生效，理由写在上面那一段。
procedure PurgePycache(const Dir: String);
var
  FindRec: TFindRec;
  Sub: String;
begin
  if not FindFirst(Dir + '\*', FindRec) then
    Exit;
  repeat
    //: 不用 `Continue`：Inno 的 Pascal Script 对它支持不稳，改成嵌套判断。
    if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
    begin
      Sub := Dir + '\' + FindRec.Name;
      if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
      begin
        if CompareText(FindRec.Name, '__pycache__') = 0 then
          DelTree(Sub, True, True, True)
        else
          PurgePycache(Sub);
      end;
    end;
  until not FindNext(FindRec);
  FindClose(FindRec);
end;

// 首次运行不是"构建数据"一步，是三步（迁移图 §12.5）。
// 这段话必须出现在**安装向导里**：装完的目录里一份文档也没有（§12.6），
// 离线用户拿不到任何别的说明。
procedure InitializeWizard();
var
  Page: TOutputMsgWizardPage;
begin
  Page := CreateOutputMsgPage(wpWelcome,
    '装完之后还要你自己做一件事',
    '安装包只放运行时必须的文件：游戏数据与 Python 都不在里面。',
    '1) 装 Python（若机器上还没有）—— 到 python.org 自行下载；' + #13#10 +
    '   扫码登录还要 pip install qrcode，其余功能不受影响。' + #13#10 + #13#10 +
    '2) 其余两步**不用你操心**：双击目录里的 rios-tui.exe 之后，它会自己' + #13#10 +
    '   取游戏数据（要下载，几分钟到十几分钟）并建好派生库，' + #13#10 +
    '   做完直接进界面。缺 Python 时它会问一句要不要替你装。' + #13#10 + #13#10 +
    '数据与说明见：{#AppURL}/blob/main/docs/data-sources.md');
end;

// 卸载：玩家自己取的数据**先问再删**（§12.5 四件之一）。
// ★ `/VERYSILENT` 时**不许弹框** —— 无人值守的卸载会被那个 MsgBox 永久挂住。
//   静默就按"保留"处理（保数据是安全的那一侧：删了要重新下 156 MB）。
function InitializeUninstall(): Boolean;
var
  DataDir: String;
begin
  Result := True;
  //: ★ 代码缓存先清（`__pycache__`，可重建）—— 它**必须放在前面**：下面玩家数据那段
  //: 在 `/VERYSILENT` 分支里会 `Exit`，放它后面就等于静默卸载时不清。
  //: 只从这两棵树往下走，绝不从 `eng`（理由见 `PurgePycache` 的注释）。
  PurgePycache(ExpandConstant('{app}\eng\ak_tactic'));
  PurgePycache(ExpandConstant('{app}\eng\tools'));
  DataDir := ExpandConstant('{app}\eng\data');
  if DirExists(DataDir) then
  begin
    if UninstallSilent then
      Exit;
    if MsgBox('eng\data 里有你自己取的游戏数据（可能几百 MB）。' + #13#10 + #13#10 +
              '选「是」= 连它一起删掉；选「否」= 保留它，只卸载程序。',
              mbConfirmation, MB_YESNO) = IDYES then
      DelTree(DataDir, True, True, True);
  end;
end;
