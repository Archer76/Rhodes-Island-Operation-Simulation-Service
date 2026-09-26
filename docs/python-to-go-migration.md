# Python → Go 转移清单 ＋ 施工图

> 立项：**2026-09-26 博士方针** —— 「项目接下来的要求是尽可能抛开 Python 那一侧，
> **UI 和模拟器都要彻底转移到 Go 侧并且以 Go 侧为主**」。
> 本文件是**只读侦察**的产物：不含实现、不改任何代码。
> 取证口径见 §五「未核」，**未取证的都标了「未核」，不是「没有」**。

## 一 · 一句话现状

**模拟器已经是 Go 的，数据面也大半在 Go 上了；真正只剩三块，而且它们共享同一个坎。**

| 层 | 现在是谁 | 证据 |
| --- | --- | --- |
| 战斗模拟 | **Go**（`rios-sim`） | 整闸 27/27（`out/pinned-gate-0875902.log`） |
| 数据自读 | **Go**（关卡 562/562、敌人 3077、干员面板/天赋/特性 679＋1324、技能 11 012、寻路 32 736、格表 562、范围 292、分类 1 056） | 同上 |
| 造规格 | **Go**（单一入口 `buildspec` 造齐 19 键） | 589 例逐路径一致 |
| 名册／练度／计划 | **Go**（直读） | 10／33／32 例逐字段一致 |
| **TUI** | **Python**（3 092 行，textual） | `ak_tactic/tui/{app,data,theme}.py` |
| **MAA 作业导出** | **Python**（21 KB） | `ak_tactic/maa_export.py` |
| **发布形态** | 单个**无界面** exe（双击 0 字节输出） | 实测：空 stdin → rc=0、stdout 0、stderr 0 |

## 二 · 那条坎：`Go 不碰数据源`（2026-09-18 裁定）

`rios-sim/main.go:31-33` 逐字写着：

> **Go 侧不做任何数据源访问**：不读数据库、不联网、不做练度折算。它只把一场战斗跑完——
> 输入是「已经完全算好的数字」，输出是判决与时间线。

现在的实现**严格守住了**这条：Go 的数据入口只有 `DataRoot()`（环境变量 `RIOS_DATA`，
默认 `data/gamedata`），只读四类 JSON —— `_level_index.json`、
`map.ark-nights.com/levels/**`、`enemydata/enemy_database.json`、
`raw.githubusercontent.com/excel/character_table.json` ＋ `char_patch_table.json`。
**全 `rios-sim/**` 搜 `sqlite|akdb|enemydb` 的 26 处命中逐处都是注释**（取证出处），
唯一的 `enemyDbRefs` 是关卡 JSON 里的字段名。

**而它已经有一条现成的裂缝**：`rios-sim/spawns.go:36` 自己写着
「`species_provider` 要 **enemydb（不在 gamedata）**」—— 那个量今天是**由 Python 送进来的**。

⇒ 下面三块**都绕不过这条裁定**，所以**第一件事是裁它**（§四）。

## 三 · 三块缺口逐块盘

### 缺口 ①：TUI —— 3 092 行 Python，Go 侧零

| 分块 | Python 在哪 | Go 已有什么 | Go 缺什么 |
| --- | --- | --- | --- |
| 界面（四步向导 ＋ `[0]` 登录屏） | `tui/app.py`（132 KB） | 无 | 整个界面层 ＋ 一个 Go TUI 框架选型 |
| 数据层 | `tui/data.py`（31 KB） | 关卡解析、干员面板、名册/练度、计划 —— **都已在 Go** | **关卡列表/章节/zone 现在走 `akdb.sqlite`**；`config`／`guides` 目录；`skland`／`operbox` 两条名册来路 |
| 第 [3] 步「解算」 | 叫 Python 模拟器 | **Go 模拟器已经在手**（`buildspec` ＋ `sim`） | 只差接线 |
| 第 [4] 步导出 | `maa_export.py` | 无 | 见缺口 ② |
| 主题 | `tui/theme.py`（5 KB） | 无 | 色板与样式 |

★ **`docs/tui-plan.md` 的 §十 已经把 20 多条 UX 细则裁定完了**（登录三条平铺、`Esc` 逐层返回、
[3]/[4] 不挂 `Esc`、`Q`/`H`/`R` 三个出口、账号一律显示「游戏用户名 ＋ 游戏 uid」……）。
「原样重做」的「原样」＝**这些已裁定条目逐条兑现**，不是自由发挥。

**估工量**（粗，按 Python 行数 × Go 的表达密度 0.7～0.9 折算，**未做细拆**）：
界面层 ≈ 1 500～2 000 行 Go；数据层 ≈ 400～600 行；合计**约一周**（含自测）。

### 缺口 ②：MAA 作业导出 —— 21 KB

| 项 | 内容 |
| --- | --- |
| 对外面 | `used_operators`／`operators_report`／`operators_lines`／`operators_brief`／`module_type`／`module_name`／`module_slot`／`skill_usage`／`difficulty_code` |
| Go 已有什么 | `plan`（打法）已在 Go 直读；`buildspec` 造齐 19 键 |
| Go 缺什么 | 上面那一组函数本体；而且它们要读 **`_uniequip()`（模组表）与 `_skill_book()`（技能表）** —— 这两个住 `akdb.sqlite` |
| 估工量 | **≈ 300～500 行 Go**，是三块里**最小、最独立**的一块 |

### 缺口 ③：发布形态

现在发的是**单个无界面 exe**：双击 → rc=0、0 字节输出（实测）。这不是坏，是它本来就是个
JSON 行协议引擎。**TUI 一旦做进 Go，这一块自动闭合**（exe 双击即出界面），本身只需几十行入口分派。

## 四 · 要裁的那一条（**这是第一刀**）

三块都压在数据源上，所以先裁这一条：

| 路 | 做法 | 代价 | 与方针的关系 |
| --- | --- | --- | --- |
| **甲（推荐）** | **开库**：Go 直接读 `akdb.sqlite`／`enemydb.sqlite`（纯 Go 驱动，免 CGO） | Go 侧多一个依赖 ＋ 一份「库的表结构」契约要跟着建库脚本演进 | 最直，一次解决三块 |
| 乙 | **开 JSON**：把关卡索引/技能/模组另出一份 JSON 到 `data/gamedata`，Go 只读文件 | 保住「只读文件、不连库」的形状；多一份派生数据要同步（本仓已有 `data/gamedata` 是**非派生**、`akdb` 是**派生**的分工） | 同样解决，但多一层同步 |
| 丙 | 留一条 Python 取数边（TUI 要数据就叫 Python） | 最小改动 | **与本次方针冲突，不建议** |

★ 我的建议是**甲**：`akdb.sqlite` 本来就是「一条命令几秒重建」的派生物
（`docs/data-sources.md` 第五节），Go 读它与读 `gamedata/*.json` 在「不联网、可重建」上没有区别；
而乙会引入第二份需要同步的真相。

## 五 · 建议的切法（顺序）

1. **裁 §四**（甲/乙/丙）—— 一句话的事，但不定它后面全是返工。
2. **第一刀：数据层**（Go 读库或读新 JSON）。它同时是 TUI 与 MAA 导出的地基。
3. **第二刀：MAA 导出**（最小、最独立）。落地后 [4] 屏的 `E` 就能通。
4. **第三刀：TUI 界面**（最大的一块，按 `docs/tui-plan.md` §十 的已裁定条目逐条兑现）。
5. **收口：发布形态**（入口分派 ＋ 重新发版）。

## 六 · 未核（**不是「没有」**）

* **Python 侧还有哪些入口被外部依赖**：只盘了 TUI／MAA 导出／发布三块；`ak_tactic/cli.py` 还有
  `db`／`formula`／`verify`／`tui` 等子命令，**它们各自的「有没有 Go 替代」未逐条盘**。
* **Go 侧库驱动的可用性**：`modernc.org/sqlite` 之类的纯 Go 驱动是否可离线构建、
  体积多少，**未核**（这一条会直接影响 §四 甲的可选性）。
* **`skland`／`operbox` 两条名册来路**的协议细节未读（`tui/data.py` 只看出它调
  `skland.resolve_game_uid_for` 之类，**联网行为与认证方式未核**）。
* **`ak_tactic/tui/app.py` 的界面清单**未逐屏清点（只知道四步 ＋ `[0]` 屏）；§三 的估工量
  按整文件行数折算，**未做屏级细拆**。
* **判据侧的影响面未盘**：现在有 `tools/check_tui.py` 钉着「跑别的子命令不会导入 textual」，
  Go 化之后那条守卫要重新设计——**未核**。

---

*本文件只读产出：未改 `rios-sim/**`、`ak_tactic/**`、`fixtures/**`、`data/**`、`tools/**`。*
