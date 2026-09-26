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

---

## 七 · 裁定与实测（2026-09-26，博士已裁）

> **博士原话**：「走甲，有现成的数据库当然直接用。」

⇒ **§四 定为「甲：开库」** —— Go 直接读 `data/akdb.sqlite`（必要时 `enemydb.sqlite`）。

### 7.1 实测：纯 Go 驱动可行（在临时目录里量的，**未动 `rios-sim/go.mod`**）

| 项 | 读数 |
| --- | --- |
| 驱动 | `modernc.org/sqlite` **v1.59.0**（纯 Go，**免 CGO**） |
| 取得到吗 | 取得到（`GOPROXY=https://goproxy.cn,direct`；`proxy.golang.org` 与本机代理都回 200） |
| 拉进多少模块 | `go list -m all` = **26**（`go mod tidy` 又补了 2 个测试期依赖） |
| 最小程序体积 | **9.34 MB**（现役 `rios-sim` exe 是 **5.08 MB**） |
| **真库可读性** | ✅ `akdb.sqlite` → `integrity_check=ok`、`stage=3055`、`operator=1164`；`enemydb.sqlite` → `integrity_check=ok`、`enemy=1807` |

★ **代价要登记**：`rios-sim/go.mod` 今天是**零依赖**（`module rios-sim` ＋ `go 1.26`，全仓无第三方包）。
走甲会给它加上**第一个依赖**，连带两个后果：
1. **首次构建要能联网**（之后走模块缓存）。而 `tools/verify_pinned_tree.py` 会在**新建的冻结树里
   自己 `go build`** ⇒ 那一步从此依赖模块缓存或网络。**这是本次方针带来的第一处真实风险，具名在此。**
2. exe 体积约 5.08 MB → 9 MB 量级（发布包的体积会跟着变）。

### 7.2 下一刀的第一步（已定）

1. **取真 schema**：`akdb.sqlite` 的表／列名（小刀已踩过一次：我拿 `stage_id` 当列名、
   又拿 `stage` 表去 `enemydb` 上查 ⇒ **那是探针的错，不是能力缺失**，两条报错原文在
   §六 的口径下都属于「未核」而非「没有」）。
2. 按 schema 定 Go 侧的**只读取数面**（先只做 TUI 第 [1] 步要的关卡列表／章节／zone）。
3. 与 `data/gamedata` 那条既有入口（`DataRoot()`）分开命名，**不许混成一个入口**——
   前者是**派生库**（一条命令几秒重建），后者是**非派生**数据（要下载），两者的失效处置不同。

### 7.3 真 schema（2026-09-26 现查，下一刀直接照这张表写）

**`data/akdb.sqlite`**（派生库，`python -m ak_tactic db build` 几秒重建）：

| 表 | 关键列 | 谁要用 |
| --- | --- | --- |
| `stage` | `level_id, code, difficulty, zone_id, data_path, name, stage_type, diff_group, hard_level_id` | TUI 第 [1] 步**选关卡**（关卡列表／章节归属） |
| `zone` | `zone_id, zone_index, type, name_first/second/title/third, activity_id, activity_name` | 同上（章节与活动名） |
| `operator` | `char_id, name, appellation, rarity, profession_cn, position, is_operator, is_not_obtainable, …` | 第 [2] 步**编队**（按职业/星级筛） |
| `operator_attr` / `operator_phase` / `operator_trait` / `operator_talent` / `operator_potential` / `operator_skill` | 逐档面板／范围／特性／天赋／潜能／技能槽 | 编队面板与练度显示 |
| `module` / `module_level` | `module_id, char_id, name, type…`；`module_id, level, …` | **缺口 ② MAA 导出**的 `_uniequip()` |
| `skill` / `skill_level` | `skill_id, name, level_count…`；`skill_id, level, …, blackboard` | 同上，`_skill_book()` |
| `attack_range` / `tile` / `meta` | 范围格表／地块／元信息 | 范围显示 |

**`data/enemydb.sqlite`**（prts.wiki 侧，**要联网**才有）：

| 表 | 关键列 | 谁要用 |
| --- | --- | --- |
| `enemy` | `page, prts_id, name, display_name, grade, category, camp, ability…` | 敌人图鉴 |
| `enemy_level` | `page, level, hp, atk, defense, res, move_speed, blackboard…` | 逐档数值 |
| `enemy_resist` | `page, level, name, value, is_immune, source` | 抗性 |
| `enemy_skill` | `page, level, slot, name, init_cooldown, cooldown, sp_cost, kind, effect` | 敌方技能 |

★ **`enemydb` 正是 `spawns.go:36` 那条现成裂缝要的东西**（`species_provider` 今天由 Python 送）。
开库之后可以顺带把它接上 —— 但**那是另一刀**，不在本次数据层里顺手做（会改判决面，必须单独过闸）。

★ **未核**：这两张表与 `ak_tactic` 侧读它们的那段代码是否**逐列同名同义**未核；
`meta` 表里有没有版本号可用于「库与代码对不上」的守卫，**未核**。

### 7.4 ★ 开库的**第二处代价**：引擎变胖会让「高频 spawn」的判据整体变慢（**待核**）

**观察**（2026-09-26，整闸跑到 92 分钟仍未结束；历史同规模约 65 分钟）：

| 进程 | 存活 | CPU | 读法 |
| --- | --- | --- | --- |
| 编排（`check_go_all.py`） | 92 分钟 | 0.6 s | 在等子进程 —— 正常 |
| 某一套判据 | 25 分钟 | 233 s | **CPU/墙钟 ≈ 0.16** ⇒ **大头在等，不在算** |

**假说**（**待核**，不是结论）：那一套是**反复 spawn 引擎**的密集型（本仓判据普遍如此：
一套要问几百到几千次），而 exe 从 **5.08 MB → 10.72 MB**（含 sqlite 驱动），
每次启动的加载开销被放大几百次。⇒ 墙钟显著变长。
**我没有对照组**：旧 exe 已被覆盖，同源码「加/不加驱动」的耗时对拍**做不了**，
要证实得另建两枚 exe（一枚不带 `datadb.go`）单独量。**在那之前这只是假说。**

**若假说成立，它指向一条架构建议**（记在这里，供第一刀之后的选型用）：
**把数据库取数面做成独立的小二进制**（或至少在引擎之外），
让**被高频 spawn 的引擎本体保持精简** —— 引擎的调用模式是「一次进程、批量作业」，
而数据面是「人机交互时偶尔查一次」，两者的体积/启动成本敏感度完全不同。
把两者编进同一个二进制，等于让最热的那个路径替最冷的那个付钱。

**这不改变 §四 的裁定**（甲仍然对：有现成的库当然直接用），
但它改变**代码放哪**：库的读取代码不必住在引擎二进制里。

### 7.5 下一刀要对齐的三件事（读 `ak_tactic/tui/data.py` 现得，**只读**）

★ **第一刀那个 `StageRows` / `ZoneRows` 是「不够 + 粒度不对」，不是「够用了」** ——
TUI 的选关流程是**三层**，而我写的只是中间那层的一部分：

| 层 | Python 落点 | 我第一刀的状态 |
| --- | --- | --- |
| **[1] 章／活动**（第一屏） | `data.py::chapter_rows()` → `db/stages.py::list_chapters(conn)`，返回 `[{key, title, subtitle, levels, parts}]` | ❌ **没做**（我写的 `ZoneRows` 是它的**下一级**） |
| **[2] 环境分层** | `data.py::zone_envs(zone_id)` → `[{env, label, levels}]`，按 `ENV_ORDER` 排（剧情体验 → 标准实战 → 磨难险地 → 通用） | ❌ 没做 |
| **[3] 关卡列表** | `data.py::stage_rows(keyword, limit, zone_id, env, difficulty)` → `db/stages.py::list_stages(...)` | ⚠️ 部分（我的 `StageRows` 只有 `zone_id` ＋ `keyword`） |

**三条必须照抄的口径**（不照抄就会「看着对、筛错了」）：

1. **`zone_id` 是精确匹配**，Python 那侧专门写了理由：
   「按分部下钻时必须精确：`main_1` 用子串会把 `main_10` 一起捞出来」。
   ⇒ 我的 `StageRows` 里 `zone_id = ?` 是对的；**但 `keyword` 那一路的语义要跟 `list_stages` 对齐**（未核）。
2. **`chapter` 比 `zone` 高一级**：「103 个活动含多个 zone（『月行水上』= 通学路 ＋ 殡仪堂），
   平铺会让用户自己认前缀」⇒ 第一屏要的是 chapter。
3. **`zone_envs` 的条数含四星限定版**，理由写得明白：「不含的话菜单报 24、列表给 41 行，看着像筛错了」；
   而且**全是 `NONE` 的章节（第 0～8、15～17 章）这一层菜单就不该出现**。

**未核**：`list_stages`／`list_chapters`／`zone_envs` 的完整语义（排序、limit 的默认、`env`↔`diff_group` 的映射、
`ENV_ORDER`／`ENV_LABELS` 的取值）**只看了 `data.py` 这一侧的调用与 docstring**；
`ak_tactic/db/stages.py` 里的实现**未逐行读**（它是参照实现，只读不改）。

### 7.6 ★ `list_stages` 的逐行语义已读 —— 第一刀的 `StageRows` 有**四处实质偏差**

出处：`ak_tactic/db/stages.py:746-782`（`list_stages`）、`:785-790`（`_code_sort_key`）、
`:89` / `:92` / `:116` / `:125` / `:137`。**下一刀必须按这张表改，不是「在原来基础上加参数」。**

| # | 项 | 参照实现怎么做（原文出处） | 我第一刀 `StageRows` 的做法 | 判定 |
| --- | --- | --- | --- | --- |
| 1 | `keyword` 匹配哪几列 | **四列**：`level_id`／`code`／**`zone_id`**／**中文名**，且**全部先 `.upper()`**（`:756`、`:769-772`） | 只匹配 `level_id` 与 `name` 两列，未统一大小写 | ❌ **窄了两列、且大小写口径不同** |
| 2 | **排序** | `(是否四星档, DIFFICULTY_ORDER 里的序号, _code_sort_key(code), level_id)`（`:775-781`） | `order by zone_id, level_id` | ❌ **完全不同** |
| 3 | `code` 的排序键 | `_code_sort_key`：按 `-` 分段、**数字段按数值比** ⇒ 让 `2-7` 排在 `2-10` **前面**（`:785-790`） | 没有这个概念（SQL 直接按字符串排 ⇒ `2-10` 会在 `2-7` 前） | ❌ **纯 SQL 排序排不出这个序** |
| 4 | 过滤面 | 还有 `difficulty`／`env`（对 `diff_group`，大小写不敏感）／`zone`（子串，命令行用）／`exclude_four_star`／`limit`（`:759-768`、`:782`） | 只有 `zone_id` ＋ `keyword` | ⚠️ 缺四项 |

**四条常量（原样抄，出处见上）**：

* `FOUR_STAR_SUFFIX = "#f#"`
* `DIFFICULTY_ORDER = ("NORMAL", "FOUR_STAR", "RUNE", "SIX_STAR")` —— 备注：这是**四档**，
  其中 `RUNE` 在本仓的 `stage` 表里实测**未出现**（表里只有 NORMAL 2249／FOUR_STAR 761／SIX_STAR 45）
* `ENV_ORDER = ("EASY", "NORMAL", "TOUGH", "ALL")`；`ENV_LABELS = {EASY: 剧情体验, NORMAL: 标准实战, TOUGH: 磨难险地, ALL: 通用, NONE: 空, "": 空}`
* `CHAPTER_TYPES = ("MAINLINE", "BRANCHLINE", "CAMPAIGN", "MAINLINE_ACTIVITY", "ACTIVITY")`；
  另有一份**只管顺序**的 `CHAPTER_ORDER`（主线各章 → 第 15～17 章 → 剿灭 → 插曲·别传 → 活动）
  —— 注释里写明了「口径那一份（筛选用）不承担顺序，所以单列一份」

**由此得出的一条实现约束**：第 2、3 项意味着**排序不能在 SQL 里做**（`_code_sort_key` 是分段数值序，
SQLite 没有现成表达）⇒ Go 侧要**取回后在内存里按同一个 key 排**，且比较器必须与参照实现**逐段同序**。
这一点与 `datadb.go` 现在的 `order by ...` 直接冲突。

★ **`StageRows`／`ZoneRows` 的处置建议**：`StageRows` **改写**（按上表四项 ＋ 内存排序 ＋ 补过滤）；
`ZoneRows` **保留但改名**（它是「原始 zone 表」，而 TUI 第一屏要的是 `list_chapters` 的 chapter 层）。

---

## 八 · 2026-09-26 追加裁定（博士）

### 8.1 六星档（`SIX_STAR`）**不做，直接删除**

**博士原话**：「六星是游戏内名为**沙盘推演**的模式，本项目不做这些关卡的模拟，直接删除。」

**它是哪些**：**45 关**，全部是第 15～17 章的 `#s` 险地作战变体，分属三个 zone
`act2mainss_zone1`（15 章 16 关）／`act3mainss_zone1`（16 章 15 关）／`act4mainss_zone1`（17 章 14 关）。
（缺号：15 无 `15-01`／`15-17`，16 无 `16-08`，17 无 `17-13`／`17-15`。）
> ⚠ **这一条会改分母**：当前「缓存可达」的 **562 个关卡键**里含这 45 个。
> 排除之后，全量扫描的分母、各批台账的口径、以及 `check_go_all.py` 的取证范围
> **都要跟着改并具名登记**——不许悄悄少 45 关。

**落点（按「不碰上游数据」处理，除非另有指示）**：在**执行面**排除
（Go 的取数口与各级清单），**不去删** `data/gamedata/_level_index.json`（**非派生**，要下载）
或 `akdb.sqlite`（**派生**，可重建）里的行。**若博士要的是真的把那 45 行从索引/库里删掉**，
那是另一类动作（破坏性），要**先列清单再动**。
★ 顺带一条已登记的语义差：`rios-sim/stage.go:211` 的 `ResolveLevel` 用 `strings.Contains(lid, "#")`，
与 Python `resolve_code`（`not endswith("#f#")`）**语义不同**——本条不必改它，但记账。

### 8.2 干员练度取不到 ⇒ **全部写 0**

**博士原话**：「干员练度取不到就全部写 0。」

Python 的做法是**把字面量 `None` 插进 f-string**（`精None None 潜None`），出现在两处、**都是给人看的文字**：
* 导出的 MAA 作业 JSON 的 `doc` 字段（`ak_tactic/maa_export.py:434-435`）；
* TUI 结果屏（`ak_tactic/tui/app.py:2362` 的 `operators_lines`、`:2414` 的 `operators_brief`）。
它**不进** `opers[]` 那种机器字段。

⇒ **这是一处「Go 与 Python 分道扬镳」，按最高优先级口径 1② 必须具名登记**：

| 项 | 内容 |
| --- | --- |
| 分道在哪 | 练度取不到时：Python 印 `None`，**Go 写 `0`** |
| 哪条判据会因此红 | MAA 导出的**逐字节对拍**（`out/zz_maa_golden.json` 那条路子）——退化路径的 `doc` 会不同 |
| 为什么红是对的 | 博士裁定：`None` 是 Python 的表示法泄漏，不是**这个作业**要传达的信息；`0` 是明确的「取不到」 |
| 口径怎么改 | 对拍判据在**退化路径**上按「Go 写 0 ∧ Python 印 None」写成**登记分歧**，不按逐字节比 |

### 8.3 已裁：NFKC 走**窄表**（不加依赖）

中文输入法全角输入（如 `ＳＲ`）在 Python 侧由 `unicodedata.normalize("NFKC", …)` 归一
（`ak_tactic/tui/app.py:1256`／`:1463`）。Go stdlib 没有 NFKC ⇒ **不加 `golang.org/x/text`**，
自写窄表：`U+FF01–FF5E` 减 `0xFEE0` ＋ `U+3000` → 空格。**覆盖真实场景，零新依赖。**
