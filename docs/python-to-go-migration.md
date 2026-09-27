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

**★ 2026-09-26 订正：本节这条代价已经消失，上面那条架构建议已被这一步实现。**

数据层后来搬进了可导入的子包 `rios-sim/data`（`475a06e`），而**根包没有任何文件 import 它**
（`git grep 'rios-sim/data' -- '*.go'` 只命中 `datachapter2.go` 里的一句注释；
sqlite 只被 `data/datadb.go` 引用）⇒ 引擎二进制**不再链 sqlite**。实测两种构建（同一份 HEAD 源码）：

| 构建 | 字节 |
| --- | --- |
| `go build .`（不剥符号） | **5,077,504** —— 回到 5.08 MB |
| `go build -trimpath -ldflags "-s -w"` | **3,592,704** —— 与 v0.2.0 发布附件**字节数相同** |

⇒ 那 5.6 MB 现在只属于**数据层/TUI**，不属于引擎；第 190-194 行那条建议
（让最热的路径别替最冷的路径付钱）不必再论证假说 —— 结构上已经做到了。

两条连带登记：

1. `out/acceptance/rios-sim-stage3.exe`（sha16 `17788F3D…`，11,240,960 字节）是
   `datadb.go` 还在根包时的**过渡态仪器**。用它取到的读数**依然有效**（引擎行为逐字节等价），
   但它**不再是 HEAD 全新构建的样子** ⇒ 以后比仪器身份时，不许把它当基准。
2. 第 187 行那句「旧 exe 已被覆盖，对拍做不了」现在**做得了**：两枚 exe 同时在盘上
   （5,077,504 与 11,240,960）。**仍未做** —— 假说已因架构变化失去实际意义，
   但若有人要结掉它，对照组是现成的。

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

---

## 九 · ★★ 订正：缺口不是三块，是**四块** —— 补上「**搜索层**」

**本文件 §三 曾写「TUI 第 [3] 步解算**只差接线**」，那句话是错的，在此订正。**

子代理在 `rios-sim/*.go` ＋ `rios-sim/mech/*.go`（**57 个非测试文件、24 276 行**）搜
`beam|Searcher|evaluated|candidates_for` ⇒ **零命中**（取证范围写全，免得被读成「大概没有」）。

⇒ **Go 侧没有搜索层。** 今天的「解算」是**两段**：

| 段 | 在哪 | 行数 |
| --- | --- | --- |
| beam 搜索（每次迭代挑候选、调评估） | **Python** `ak_tactic/search.py` | 425 |
| 一场战斗的推演 | **Go** `rios-sim`（`Verifier(engine="go")`，`ak_tactic/verify.py:150`） | 24 276 |

**所以「界面能自己解算」＝ 还得把搜索层搬过去**（连同 `eta.py` 的 `ArrivalIndex`／路线计划那一族）。
这条以前没进清单，是因为 §三当时只盘了「界面／数据／导出」，把「解算」误当成已经落在 Go 上了。

⚠ **未核**：搜索层搬到 Go 的工量**没有估**（425 行 Python，但它牵着 `parallel.py` 的多进程并行与
`Verifier` 的一整套取数面——**要单独做一次只读侦察**才知道边界）。

## 十 · bubbletea 落地蓝图（子代理交付，2026-09-26）

产出：`out/zz_go_tui_framework.md`（749 行／83 KB；第一部分＝4 个候选的选型依据，
第二部分＝bubbletea 落地蓝图）。

**三条会直接改实现方式的硬事实**：

1. **「UI 与引擎同进程」今天做不到**：`rios-sim` 根目录 **70 个 `.go` 全是 `package main`**
   （唯一可 import 的子包是 `rios-sim/mech`）⇒ 只能走**子进程 JSON 行协议**，
   或先做一次结构重构（把引擎拆成可 import 的包）。**这一条要博士裁**（它也决定
   §7.4 那条「数据面住不住引擎二进制」的答案）。
2. **bubbletea v2 换了 import path**（`charm.land/…`）＋ API 大面积改（`View() tea.View`、
   `tea.KeyPressMsg`、空格键叫 `"space"`、屏幕模式移到 View 字段）
   ⇒ 现网教程多数是 v1，照抄会编译不过。
3. **屏是 14 个，不是 6 个**：Welcome／Login／GuidesDir／Ask(modal)／Qr(modal)／Chapter／Part／
   Env／Stage／SquadAsk／SquadPick／Solve／Result／NoStage。建议**各自一个 Model ＋ 根 Model 持栈**
   （对照 Python 的 `_path`），并把 Python 里「按回调对象身份认关卡列表那一格」
   （`app.py:2643-2644`，注释自己说按名字认会漏）换成**显式 Kind 标记**。

**它还量了依赖代价**（不许 build，故按 `goproxy.cn` 的 `.mod` 递归求路径集合上界，
并用 `modernc.org/sqlite` 做**校准对照**：同法数 **53**、真值 `go list -m all` = **26** ⇒ ≈2× 高估）：
折算后 bubbletea 套装 **~19-20** 个模块、tview ~8、gocui ~5、tcell ~8。现水位：**1 个直接依赖**。
⚠ **体积与启动耗时未核**（零读数，不许 build）。

**★ 宽字符对拍探针 —— 已做，结论：两边同口径（2026-09-26）**

原先是「未核：`x/ansi` 的 `StringWidth` 与 Rich `cell_len` 在东亚歧义字符上是否逐字符一致
⇒ 建议写第一行界面代码之前先做这个探针」。**探针已跑**（`out/zz_width_probe.py`，
Go 侧在临时模块里 build 一枚，**未动 `rios-sim/go.mod`**）：

| 项 | 读数 |
| --- | --- |
| 对象 | **147 条**（60 个真实关卡名 ＋ 60 个真实干员名 ＋ **27 个**人工挑的歧义字符） |
| 整串宽度不同 | **0 / 147** |
| **逐字符分歧** | **0** |

⇒ **结论：界面照抄 Go 的 `x/ansi.StringWidth`，排版会与旧 TUI 一致**（Rich 的 `cell_len`
就是旧 TUI 用的那把尺子）—— 不必自己定口径，也没有分歧要登记。

⚠ **取证范围的限定**（照本仓口径写全，免得被读成「全 Unicode 都验过」）：
歧义字符那批是**人工挑的 27 个**（`·`／`※`／`→`／`℃`／`Ω`／全角空格…），**不是穷举**；
真实名那 120 条是从 `akdb` 现取的（关卡名 60 ＋ 干员名 60，按名去重）。

---

## 十一 · 范围收窄（博士 2026-09-26）：**工程侧保留 Python**

**博士原话**：「工程测就保留 python，这个不用改。」

### 11.1 这一条**取消了一整类风险**

之前 §三／§九 隐含一个更激进的读法（「Python 全消失」），那会带来一个严重后果：
**27 套判据的价值是「Go vs Python 逐字段一致」**——参照实现一没，它们同时失去意义，
只能改成冻结快照，而那等于**自己跟自己比**（自证）。

**工程侧保留 Python ⇒ 参照实现（`ak_tactic/battle/*`）、27 套判据、`tools/*.py` 全部保留
⇒ 对拍安全网保住，判据不需要换参照。** 数据供给链也不变：`akdb.sqlite` 仍由
`python -m ak_tactic db build` 建，**Go 只读**（`datadb.go` 正是这么做的）。

### 11.2 保留在 Python 的（**不改**）

建库（`python -m ak_tactic db build`）／数据重建（`tools/rebuild_data.py`）／
上游抓取（prts.wiki、gamedata 镜像）／森空岛登录（`ak_tactic/skland`）／
`operbox` 读取／`tools/*.py` 全部判据与驱动。

★ **界面不在这张名单里** —— 它已经迁到 Go（`rios-sim/cmd/rios-tui`），
`ak_tactic/tui` 从「主界面」变成「**对照物**」：`python -m ak_tactic tui` 仍然能跑
（并会往 stderr 打一句去向提示），但它**只提示、不拦截**，因为逐屏判据与 27 套
「Go vs Python 逐字段对拍」都还拿它当参照物 —— 拦掉入口等于撤了回归网。
发布形态里**不含它**（§12.6：安装包只放运行时必须的文件）。

### 11.3 要补写的收窄为**四块**

| # | 块 | 现状 |
| --- | --- | --- |
| 1 | **界面**（14 屏，bubbletea） | 蓝图已出（`out/zz_go_tui_framework.md`），**代码零行** |
| 2 | **搜索层**（`search.py` 425 行 beam ＋ `eta.py`） | Go 零命中；**工量未核** |
| 3 | **数据层缺口** | `list_chapters`／`zone_envs` 未做；`StageRows` 四处偏差（§7.6） |
| 4 | **MAA 导出** | 规格已出（`out/zz_maa_export_spec.md`），代码零行，估 300～500 行 |

### 11.4 裁定：登录／名册走 **Python 子进程**

**博士 2026-09-26 选 1**（另两个候选：自己实现森空岛登录／降级成读 operbox 文件）。

⇒ **Go TUI 的登录屏与「拉名册」由 Go 起子进程调现成的 Python 模块**
（`ak_tactic.skland`、`operbox_path` 那一族，出处见 `ak_tactic/tui/data.py:1-31`）。

**三条必须写进实现的约束**：

1. **它是一条已知的、要具名登记的依赖**：Go TUI 在本机**没有 Python 时登录／名册这两条路不可用**。
   按本仓口径，这属于「能力受环境限制」而不是「缺陷」——但**必须可见**：
   界面上要给出**具名失败**（照 `simgo/client.py:100` 那套写法：说清缺什么、怎么补），
   **不许**静默退化成「空名册」。
2. **不许把 `python` 写死成命令名**：要能指定解释器（与 `RIOS_SIM_BIN` 同款做法），
   否则将来换虚拟环境会静默走错。
3. **子进程协议要与现有那条同形**（JSON 行协议／一次性调用），
   别为它发明第二套 IPC —— 本仓已有 `ak_tactic/simgo/client.py` 那套可照抄的形状。

---

## 十二 · 发布形态（博士 2026-09-26）：**拆分，不做单文件 exe**

**博士原话**：「打包的时候不用把整个项目做成一个单独可运行的 exe 文件，该拆分的拆分」，
并给了参照物：本机一份 NW.js 游戏（路径从略，形态见下）。

### 12.1 参照物是什么形状（只读实测）

**瘦 exe ＋ 胖目录**：`Game_en.exe` **2.04 MB** ＋ `nw.dll` **136.58 MB** ＋ 运行时 DLL
（`d3dcompiler_47`／`libGLESv2`／`node.dll`…）＋ **资源全部外置成目录**
（`img/` 1213 文件 1.13 GB、`audio/` 120 文件 95.6 MB、`locales/` 106 文件 45.1 MB…）。
顶层 `package.json` ＋ `index.html` ⇒ 它是 NW.js 壳。总计 **1729 文件 / 1.44 GB**。

### 12.2 R.I.O.S. 的发布树（建议）

```
rios/
  rios-tui.exe      ← 界面（bubbletea）**兼双击入口**。纯 Go、零 DLL，小
  rios-sim.exe      ← 引擎（JSON 行协议），就是现在这枚
  data/             ← 关卡／敌人／干员数据（外置；发布包不含游戏数据是既有约定）
  eng/              ← 工程侧 Python（建库／抓取／登录／名册；见 §11.2）
  README.txt
```

★ **入口那一行已经改了**：这张表原先列的是 `启动.cmd`（双击入口）。**2026-09-27 取消**——
双击 `rios-tui.exe` 就是入口，发布形态里不再有启动器这一类中间件；理由、判据怎么换、
实测读数见 §12.9。

**三条为什么这样拆**：

1. **引擎与界面分两个 exe** —— 顺手解决了 §10 那条「70 个 `.go` 全是 `package main`、
   同进程做不到」：**不必重构**，界面照现有方式**子进程调引擎**
   （`ak_tactic/simgo/client.py` 与 `rios-sim/main.go` 的 JSON 行协议本来就是为这个设计的）。
2. **`data/` 外置** ⇒ 换数据不必重下 exe；且延续「发布包不含游戏数据」的既有做法。
3. **`eng/` 单放** ⇒ 工程侧保留 Python 的落点（§11.2），登录／名册走它（§11.4）。

★ **我们比参照物轻得多**：bubbletea 是**纯 Go**，界面 exe **不需要** `nw.dll` 那种 136 MB 运行时，
也没有 `d3dcompiler_47.dll`／`libGLESv2.dll` 那一族。所以「拆分」对我们＝**两三个 exe ＋ 两三个目录**，
不是 1700 文件的大摊子。

### 12.3 拆分的代价与必须补的一件

**代价**：目录必须完整才能跑（少一个文件就跑不起来）——这是单文件 exe 用体积换来的好处，
拆开就得自己还。

⇒ **必须补「启动器自检」**：入口（现为 `rios-tui.exe` 自己，2026-09-27 起不再有 `.cmd`，见 §12.9）
在启动时逐项检查 `rios-sim.exe`／`data/`／`eng/` 是否在位，**缺什么就具名报出来**（照
`ak_tactic/simgo/client.py:100-108` 那套写法：说清缺什么、怎么补），
**不许**静默退化成「空列表」或「跑一半才报」。

⚠ **未核**：`data/` 在发布包里的形态（随包附 / 玩家自取 / 只附骨架）**未定**——
它取决于「下载即用」这条要走到哪一步，需要博士裁（本仓既有约定是**不附**游戏数据，
按 `docs/data-sources.md` 自己取）。

### 12.4 发布物＝**一个安装程序**（博士 2026-09-26 追加）

**博士原话**：「发布的时候做成一个安装文件。」

⇒ **构建产物仍是 §12.2 那个拆分目录；交付给用户的是单个安装程序**（两者不矛盾：
装完是拆分树，下载的是一个 `setup.exe`）。这正好把 §12.3 那条「目录少一个文件就跑不起来」
从「用户自己踩」变成「安装器保证」。

**工具二选一**（都产出单个安装 exe）：

| 工具 | 一行代价 |
| --- | --- |
| **Inno Setup（推荐）** | 脚本化 `.iss`、内建中文、压缩好、自带卸载；本仓要的全有 |
| NSIS | 更小更灵活、插件多；脚本语法较老、中文要自己配 |
| WiX（`.msi`） | 企业级、可组策略部署；学习曲线陡、对便携脚本类偏重 |

**两件决定安装包大小的、仍待博士裁的**：

1. **`data/` 随包附吗** —— 现 `data/gamedata` **156 MB** 且是**非派生**（要下载）⇒
   随包附＝安装包直接 +100 MB 量级；不附＝装完还要跑一次数据获取。
2. **`eng/` 的 Python 怎么办** —— 内嵌便携 Python（+40～60 MB，下载即用）／要求用户已装
   Python（安装时检测并提示，零体积代价）／只附我们的代码＋要求系统 Python。

### 12.5 已裁（博士 2026-09-26）：`data/` 与 Python 都**不随包**

**博士原话**：「data 还是由玩家自己运行时构建，python 让玩家自行下载。」

```
安装器装：  rios-tui.exe（入口）/ rios-sim.exe / eng/
安装器不装：data/            ← 玩家自己取
            Python 运行时     ← 玩家自己装
            文档            ← 见 §12.6（2026-09-26 追加裁定）
```

⚠ **一处必须纠正的说法（否则安装器的提示会写错）**：`data/` 里**只有一半能「运行时构建」**。
照 `docs/data-sources.md` 第五节与本仓 `.gitignore` 的分工：

| 部分 | 性质 | 玩家能自己「构建」吗 |
| --- | --- | --- |
| `data/gamedata/`（**156 MB**） | **非派生** —— 要从镜像**下载** | ❌ **不能构建**，只能下载 |
| `data/cache/`、`*.sqlite`、`ranges.json`、`op-briefs.txt` | **派生** | ✅ `python tools/rebuild_data.py` 一条命令重建 |
| `data/operbox/`、`data/skland/` | 玩家导出／要登录态 | ✅ 但只能玩家产出 |

⇒ **首次运行不是「构建数据」一步，是三步**：

1. **检测 Python**：没有 ⇒ **具名**报「未找到 Python，请自行安装」，给下载地址，**不代装**。
2. **检测 `data/gamedata/`**：没有 ⇒ 具名说「需先**下载**数据（这一步**不能构建**）」，
   指向 `docs/data-sources.md`。
3. **检测派生数据**：没有 ⇒ 提供「现在跑 `python tools/rebuild_data.py`」的入口。
4. **检测 `operbox`／`skland`**（可选）：没有就降级为「无名册」，但**要明说**。

★ **如实登记（不许被读成「下载即用」）**：在这套裁定下，玩家装完还要
**① 装 Python ＋ ② 下载 156 MB 数据**。这是**选定的取舍**（安装包小、不背运行时），
不是遗漏——写在这里免得下一个人以为装完就能跑。

**安装器必须做的四件（照本仓纪律）**：

1. **依赖自检**：缺件**具名报错**（照 `ak_tactic/simgo/client.py:100-108` 那套），
   **不许**装完才在运行时报错。
2. **不覆盖已有 `data/`**：用户可能自己取过 ⇒ 检测到就不动。
3. **卸载干净**：不留 `data/`（用户数据）与配置；要留的先问。
4. **可重复安装／升版本**：就地覆盖 exe，不破坏 `data/`。

**工作量**：`.iss` 约 100 行 ＋ 一个构建步骤 ＋ 一次冒烟（装到临时目录 → 跑入口预检 → 卸载），
**约半天**；且**必须先有两个 exe** ⇒ 排在界面之后。

### 12.6 安装包**只放运行时必须的文件**（博士 2026-09-26 追加）

**博士原话**：「文档就不要打包到安装包了，安装包里只需要运行时必须的文件。」

判据（可判，不靠感觉）：**一个文件进包 ⟺ 删掉它，程序跑不起来、或首次运行走不下去。**
逐个候选问一遍「删掉它会怎样」，答不出后果的一律不进包。

| 进包 | 为什么它是「运行时必须」 |
| --- | --- |
| `rios-tui.exe` | 界面本体，**也是唯一的入口**（§12.9：双击它就行）——删了没有入口 |
| `rios-sim.exe` | 模拟引擎；界面是**子进程**调它（§12.2 之 1），删了点不动任何东西 |
| `eng/`（至少 `ak_tactic/`） | 登录／名册／数据重建走 Python 子进程（§11.4），删了这三件事全废 |
| `eng/tools/rebuild_data.py` | 首次运行第 3 步要跑它（§12.5）⇒ 属于运行时必须 |
| ~~`fetch_prts_notes.py`~~ | **2026-09-27 起不进包**：它只被「干员备注库」那一步用，而玩家的一键流程只跑三步（干员库／关卡索引／敌人库，见 §12.7 ④）。实测备注语料在 Go 与 Python 的**产品路径**里零命中，只有判据与开发审计用得上 —— 按 §12.6 的判据问「删掉它程序跑不起来吗」，对玩家那条路答案是"跑得起来" |
| ~~`启动.cmd`~~ | **2026-09-27 起不进包**：入口是 `rios-tui.exe` 自己（无参数运行时它自己先跑一遍 `-setup`，判据是纯函数 `shouldAutoSetup`）。那个壳只干三件事，两件早就由 Go 解决、剩下一件也进了 Go ——逐条理由见 §12.9 |

★ 打包脚本必须具名登记一件容易漏的事：`tools/fetch_prts_notes.py` **在产品仓 `.gitignore`
的「内部件」名单里**（它被摘出过）。**2026-09-27 之前**玩家的一键流程会跑到「干员备注库」
那一步、因而要用它 ⇒ 那时它只能从**本机工作树**取（照 `git ls-files` 找会静默少一件，
装出来才在首次运行炸）。**现在玩家那三步里没有备注库**，所以它整个不进包；
本机工作树里没有它时，打包脚本会给具名报错 —— 那条机制保留着（它防的是"照索引找文件"
这个形状本身），只是不再对这个文件触发。

**明确不进包**（都不是运行时必须；括号里是为什么）：

- `docs/` **全树**（含本文件）—— 我们自己写的账本与规格，程序不读它；
- `tools/` 的全部判据（`check_*_go.py`、`freeze_baseline.py`、`golden_go.py` …）—— 那是**我们的尺子**，不是玩家的运行时；
- `fixtures/`（含 24 份冻结基线）—— 判据的期望值，同上；
- `out/`（判据产物与中间 exe）—— 可重建；
- `rios-sim/*.go` 源码与 `go.mod` —— 玩家拿到的是**构建产物**，源码在 GitHub；
- `README.md`／`.gitignore`／`THIRD-PARTY.md` 等仓根文件。

**这条裁定把「用户怎么知道怎么用」换了个位置**：装完的目录里**一份文档也没有**
（连 `README.txt` 也不放 —— 它同样不是运行时必须）。所以：

1. **三步引导（§12.5）必须落在安装器向导里**，以及首次启动时界面自己的提示里；
2. 其余文档的唯一去处是 **GitHub 仓**，安装器最多给一个链接。

⚠ **如实登记两条**：① 离线用户拿不到任何文档（这是「包只放运行时必须」的直接代价，
不是遗漏）；② 我们与参照物（§12.1 那种 NW.js 游戏）在这一点上**不同**：
它连 `README`、`package.json`、`licenses` 都随包，我们**不随** —— 因为我们的文档是
**开发账本**（行号现算、附本机命令），对玩家没有意义，随包只会让人误读。

⚠ **未核**：`eng/` 能瘦到哪一步，还没量过 —— 登录／名册这条路径到底 import 了
`ak_tactic/` 的哪些子包（`battle/`？`simgo/`？）未逐个查过。查清了才能说
「`eng/` 只要这几个目录」，现在写的都是**上界**。

### 12.7 实做时撞到的三件事（2026-09-27，打包脚本 + 装完自查实测）

这三条都是**装出来才会炸**的形状，第 12 节前面的规划看不出来，故补在这里。

**① 发布树的数据根是 `eng/data/`，不是 `<发布根>/data/`。**

Python 侧的数据根是**硬编码**的 `Path(__file__).resolve().parents[2] / "data"`：

| 出处 | 认的路径 |
| --- | --- |
| `ak_tactic/db/build.py:40`（`DEFAULT_DB_PATH`） | `parents[2]/data/akdb.sqlite` |
| `ak_tactic/tui/data.py:239`（名册缓存） | `parents[2]/data/skland/roster_<uid>.json` |
| `ak_tactic/tui/data.py:406`（OperBox 降级） | `parents[2]/tools/operbox_path.py` |

`ak_tactic` 住在 `eng/` 下 ⇒ `parents[2]` 就是 `eng/`。**Go 侧跟着改了**：
`dataDirCandidates()`（`cmd/rios-tui/main.go`）现在把 `eng/data` 也列进候选，
所以两侧指向同一处，且**双击 exe 不靠环境变量也能跑**。
⇒ 给玩家的话也要跟着改：数据放 `eng/data/gamedata/`（预检的输出里已经这么写了）。

**② 两处查找**不许**从发布树往上借**（真踩到了）。

`findEngineExe`／`findBridgeScript` 都会往上走若干层 —— 那是为开发形态准备的
（exe 常建在 `out/xxx/` 里）。装完自查的**负对照**当场抓到：把发布树的 `eng/` 改名
之后，预检**照样报「工程侧 Python 在位」**，报的还是开发树那份
`D:\...\ak-tactic\tools\rios_bridge.py`。这正是本仓最忌讳的形状（你以为读的是 A，
实际读的是 B），而且在"打包自查"里最危险：**少装一个目录，却因为旁边有棵开发树而判绿**。

处置：新增 `isReleaseTree(dir)`（同级有 `eng/` 或有 `rios-sim.exe`）⇒ 是发布树就
**只在这棵树里找**，一步都不往上走。开发树照旧往上走。
⚠ 登记的代价：若哪次开发把引擎 exe 建在 `out/`（`go build -o out/rios-sim.exe`），
`out/` 会被判成发布树、桥脚本查找在那止步并**具名**报错；处置是摆一份 `tools/`
或用 `RIOS_BRIDGE` 指定。

**③ 装完自查里 ✓ 会比开发树少 6 条，且两条差异都必须**具名**。**

实测：开发树 `-selftest` 216 个 ✓，**发布树 210**。少的 6 条是：

| 少的条数 | 为什么 | 具名说法（原文） |
| --- | --- | --- |
| 2 | 扫**本包 Go 源码**的防绕过判据 —— 发布树里没有 `.go` | `未核：读不到本包源码目录 rios-sim\cmd\rios-tui，不判红` |
| 4 | 要**真名册**的判据 —— Python 侧认 `eng/data/skland/`，发布树里没有 | `未核：桥这次取不到名册，不判红`（下一条给出 `load_roster() 返回 None` 的原因） |

⇒ 打包脚本**不盯 ✓ 总数**（盯它会把"环境不同"误判成"少跑了"），盯的是性质：
rc=0、结论全绿、✓≥200、且那两条具名未核必须出现。**少跑而被静默吞掉**才算红。

**另两件顺带记下的**：

* 装完自查会真起一次桥 ⇒ Python 会往**发布树里**写 `__pycache__`。上一版就是这样：
  自查全绿，紧接着哈希那一步判据报"树里有 6 个 .pyc"。处置：哈希前清掉
  （可重建，§12.6 判据也认为它不该进包）。
  ★ **2026-09-27 补记**（入口换成 exe 之后，§12.9）：原先 `启动.cmd` 里那句
  `set PYTHONDONTWRITEBYTECODE=1` **一度没有落点** —— 那个壳取消后，Go 起 Python 子进程时
  只钉了 `PYTHONIOENCODING`／`PYTHONUTF8`，全仓再无第二处设它 ⇒ 玩家一跑 `eng/` 下就会长
  `__pycache__`。**已补上两处落点**（同日）：
  ① **Go 侧统一拼装** `pythonEnv()`（`engclient.go`）——「一处拼装、四处调用」：一次性桥
  （`engclient.go` 的 `call`）、常驻桥（`bridgesession.go`）、重建命令（`setup.go` 的
  `runStreaming`）、解释器版本探针（`preflight.go` 的 `probePython`）。抽成函数而不是各处
  `append` 抄几遍，是因为抄几遍迟早会漂，而漂的表现正是「有的路子干净、有的路子脏」。
  ② **安装器侧面**：`.iss` 里两条声明式的 `[UninstallDelete]`（`{app}\eng\ak_tactic\__pycache__`、`{app}\eng\tools\__pycache__`）
  ＋ `[Code]` 的 `PurgePycache` 递归清子包那一层 —— 不补这一条，「卸载干净」会被这批残骸打折。
  ★ **一条实测结论（别再走那条弯路）**：`[UninstallDelete]` 的 `Name` **不支持通配** ——
  先写的 `Name: "{app}\eng\ak_tactic\*\__pycache__"` **一个都没删掉**，是装完自查那条新判据
  当场抓到的（它造三级夹具、卸载后逐级点名）。所以子包那一层只能靠 `[Code]` 递归；
  递归**只从 `ak_tactic` 与 `tools` 两棵树往下**，绝不从 `eng` 开始 —— 玩家的数据
  `eng\data` 就在同一层，从 `eng` 递归就有扫到它的风险，而它是按「先问再删」处置的。
  **判据**：`build_installer.py` 的装完自查造三级 `__pycache__` 夹具（ak_tactic 根／子包 battle／tools），
  卸载后逐级点名要求消失，与「玩家的 `eng\data` 必须活下来」那条**成对**读。
* `启动.cmd` **纯 ASCII** —— 这条约束**已随入口取消而失效**（§12.9）：cmd.exe 是按
  **当前代码页**逐行读批处理的，`chcp 65001` 生效之前的行若含中文就会乱码。现在代码页由
  `console_windows.go` 用 syscall 自己切、退出前恢复；给玩家看的中文照旧由
  `rios-tui.exe -preflight` 打印。

**当次读数**（`python tools/build_release.py --version v0.3.0`，2026-09-27）：
发布树 **92 个文件 / 13.8 MB**；`rios-sim.exe` 3,679,744 B、`rios-tui.exe` 8,689,152 B、
`启动.cmd` 708 B（逐件 sha256 见树根 `SHA256SUMS.txt`；★ 那个 `.cmd` **已在 2026-09-27
取消**，§12.9 —— 这一行是**那一版树**的历史读数，不是现在的形态）；
装完自查三条预检读数：全新树 `rc=3`（指出 `eng/data/gamedata`）／拿走引擎 `rc=2`／
拿走 `eng/` `rc=2`；发布树的 exe 跑全量自检 `rc=0`、✓=210、全绿。

★ 与 v0.2.0 的对比：那一版引擎附件 **3,592,704 B**，现在 **3,679,744 B**（+87,040）
—— 多出来的正是搜索层（arrivals／spots／candidates／solver）与 `maa` 包。

### 12.8 判据 6 的落地方式（2026-09-27 演练已过，未推）

**要推的东西**：把改写结果落成新的 main。演练在**独立 worktree** 里做（不碰 main）：

```
git worktree add <仓外>\wt-rebase -b wip/tui-rebased-20260927 wip/tui-complete-20260926
git -C <仓外>\wt-rebase rebase --onto origin/rewrite/paths-2026-09-26 main
```

**演练读数**（2026-09-27）：

| 项 | 读数 |
| --- | --- |
| rebase | `Successfully rebased`，28 条非合并提交全部重放，**零冲突** |
| 结果树 | `015fa8f`（本支树原来是 `6a06622`） |
| 我的工作量 | `git diff 2b4be86 <本支>` 与 `git diff a31f4ee <rebase 后>` **逐字节相同**（各 23,426,855 B） |
| 构建 | 引擎与界面 exe 都 rc=0 |
| 自检 | rc=0、结论全绿、✓=212（少 4 条＝要真名册那几条，worktree 里没有名册缓存，**具名未核**） |
| 禁用串扫描 | **非预期命中 0**（blob 0 ＋ 提交信息 0），正负对照成立 |

★★ **一处必须留痕的自我更正**：动手前我以为不变式是「rebase 前后**树**一字不变」——
**错了**，实测树变了（`6a06622` → `015fa8f`）。原因不是 rebase 出问题，而是我搞错了血缘：

* `wip/tui-complete-20260926` 与 `main` 的公共祖先是 `2b4be86`，而 **`a31f4ee`
  （本地 main 的尖，即名册路径隐私修复 `tools/roster_path.py`）不是本支的祖先**；
* 改写分支的树 == `a31f4ee` 的树 ⇒ rebase 到它上面，等于**顺带把 `a31f4ee` 并了进来**。

所以正确的不变式不是"树不变"，而是**"我的工作量不变"**：
`diff(基点, 本支) == diff(新基点, rebase 后)`。这条一量，字节数与逐行都相同，
才说明搬对了。★ 教训：拿"树哈希不变"当不变式之前，先确认**新基点就是旧基点** ——
差一笔提交，那两个哈希本来就该不一样，而"不一样"会被误读成"搬坏了"。

**禁用串判读口径（一并留痕）**：判据 6 写的是「10 串扫描 0 命中」。实测口径是
**非预期命中 0**：扫描器把 `README.md` 的占位符、`tools/check_tui.py` 的合成路径、
内部档的**文件名**、以及同级内部件目录的**相对写法**逐条登记（每条给理由），
其余必须为 0。为什么不能追求字面 0：判据 6 同时要求**树哈希与改前一字不变**，
而那类相对写法在 blob 里本来就有（是上一轮改写**故意**换成的形式）——
要字面 0 就得改 blob，那就违反"树不变"。
**绝对路径一律洗**（本轮洗掉了界面源码里那三处写死的解释器路径），名字与相对写法登记保留。
扫描器：`out/acceptance/_banned_scan.py`（含正负对照，对照不成立就宣布读数作废）。

★ **这一节自己踩过一次**：上面这几句原本把禁用串**原样写了出来**（当例子），
于是这份文档本身成了非预期命中 —— 推送前的扫描当场拦下（"记录纪律的正文不许带禁用串"）。
现在一律改成描述性写法：**要讲某个串被洗掉了，就说它是什么形态，不要把那个串抄一遍。**

### 12.9 入口不再是 `启动.cmd`（博士 2026-09-27 裁）

**博士的问题**：release 包里为什么是个 `.cmd`，能不能改成双击 `rios-tui.exe` 直接进默认终端。

**能 —— 而且那个壳本来就多余**：它只干三件事，其中两件在 Go 里早就解决了。

| 壳里那件事 | 现在谁做 | 凭什么不需要它 |
| --- | --- | --- |
| `cd /d "%~dp0"` | 不需要 | 路径解析三处全走 `os.Executable()`：`main.go` 的 `dataDirCandidates`／`engclient.go` 的 `findBridgeScript`／`engpipe.go` 的 `findEngineExe`。cwd 在哪都不影响取数与找桥（§12.7 ①② 记的正是这两处） |
| 先 `-setup` 再起界面 | **程序自己**（`main.go`） | `-setup` 是同一个程序自己的参数；无参数运行时（`flag.NFlag()==0`）它自己先跑一遍准备，判据是纯函数 `shouldAutoSetup`。壳去串「两步」这件事本身多余 |
| `chcp 65001` ＋ 失败时 `pause` | **Go 自己**（`console_windows.go`） | syscall 调 kernel32 的 `Set/GetConsoleOutputCP` 切 UTF-8、退出前恢复原值（`main` 拆成 `setupConsole`＋`run`＋`restoreConsole`，因为 `os.Exit` 不跑 defer）；`pauseIfInteractive` 只在 stdin 是字符设备时停 —— 管道／重定向不停，判据友好 |

产品侧那一笔是 `696bed5`（`console_other.go`／`console_windows.go`／`main.go`／`selftest.go`／`setup.go`，自检 237 ✓）；本节的落点是**打包与文档**这一侧。

| 文件 | 改了什么 |
| --- | --- |
| `tools/build_release.py` | 删掉 `LAUNCHER` 常量与 `write_launcher()`（连同 `[3/6] 写 启动.cmd` 那一步，步骤由 6 步变 5 步）；白名单 `allowed_exact` 去掉 `启动.cmd`，并**新加一条具名拦阻**（树里出现 `.cmd`／`.bat` 就报「启动器已取消」）；`smoke()` 的两条启动器断言按下面的表处置 |
| `tools/rios_setup.iss` | `AppExeName` ⇒ `rios-tui.exe`；向导正文的「双击目录里的 启动.cmd」跟着改。`[Run]` 那条**不动**：`shellexec` 与「双击」是同一条路（走 ShellExecute，控制台窗口该有就有），换成 exe 之后依然成立；`skipifsilent` 让静默安装不弹它。**第二轮追加**：`[UninstallDelete]` 删 `eng/` 下的 `__pycache__`（见下） |
| `tools/build_installer.py` | `want` 名单去掉 `启动.cmd`；原先「读 `.cmd` 文本做接线断言」那一段换成「装出来的目录里**没有** `启动.cmd`」。**第二轮追加**：`--tree` 转绝对路径；新造三级 `__pycache__` 夹具并断言卸载后逐级消失 |
| `README.md` | 「安装包装好的目录里双击 `启动.cmd`」⇒ `rios-tui.exe` |
| 产品侧（**第二轮**，博士扩权后做） | ① `pythonEnv()` 统一 Python 子进程环境（含从 `启动.cmd` 搬进来的 `PYTHONDONTWRITEBYTECODE=1`），四处调用；② 十五处「启动器／`启动.cmd`」字样改完（表见下） |
| 本文件 | §12.2 的发布树、§12.3 的入口括注、§12.5 的「安装器装」一行、§12.6 的表、§12.7 的两条补记 —— 同一笔改齐；§12.9 本身是这次新增 |

★ **为什么「从壳里搬进 Go」这件事要单独记一笔**：那个壳除了串命令，还**顺带设了一个环境变量**（`PYTHONDONTWRITEBYTECODE=1`）。取消一个入口时最容易漏的就是这一类「壳的副作用」——命令搬到哪、判据换到哪都想到了，而它替我们设过的环境、它替我们摆正过的 cwd，只有**逐条对着壳的正文点一遍**才发现得了。这次是靠「壳里三件事」那张表逐行问「这一行还有谁在做」抓到的。

**判据怎么换（取消一个入口最要紧的部分）**：旧的两条断言里有一条**没有等价物**，不许假装它还在。

| 旧断言 | 现在 |
| --- | --- |
| 缺 `eng/` 时启动器必须停住 | **换成对 exe 的等价断言**：在缺 `eng/` 的树上跑 `rios-tui.exe -setup`（stdin 接 NUL），要求**具名失败 ＋ 非零退出**。它同时守三件事：缺件要具名、缺件时不许返回 0、NUL 不是字符设备所以**不许暂停**（真停了就会撞 300 秒超时 —— 「按时返回」本身就是没暂停的读数） |
| `.cmd` 里 `-setup` 必须在裸 `rios-tui.exe` 之前（顺序断言） | **删除，无等价物**：没有 `.cmd` 就没有那份文本可断言。那条性质现在由 `main.go` 的 `flag.NFlag()==0` 分支承担，而它已被无终端自检里的 `shouldAutoSetup` 那几条（纯函数、喂两格）覆盖 |

★ 两条**不许**进自动化（实测）：① 空树上跑**无参数**入口会真的去下 94 MB；② 以 NUL 作 stdin 起 TUI 会**挂住**（bubbletea 无 TTY 不退出）—— 两份冒烟都只跑 `-preflight` 与 `-setup`。

**实测读数**（2026-09-27，探针树 `python tools/build_release.py --version v0.3.2-probe --no-selftest`）：

| 项 | 读数 |
| --- | --- |
| `build_release.py` | **rc=0**；步骤 `[1/5]`…`[5/5]` 自洽 |
| 树里有没有 `启动.cmd` | **没有**（逐件 90 个文件的清单里没有它，`SHA256SUMS.txt` 里也没有） |
| 白名单判据（§12.6） | 通过：`树里共 90 个文件，全部在白名单内（入口 rios-tui.exe 自己；无 .cmd）` |
| 白名单判据的**负对照** | 往探针树里塞一个假的 `启动.cmd` ⇒ 判据具名拦下（`启动器已取消…不再有 .cmd/.bat 这一类中间件`，rc=1）；清掉夹具后再量真树 |
| `smoke()` 正例 | rc=3，且点名了 `eng/data/gamedata` |
| `smoke()` 负对照一（拿掉引擎） | rc=2，点名引擎 |
| `smoke()` 负对照二（拿掉 `eng/`） | rc=2，点名工程侧 Python |
| **入口那条新判据** | `rios-tui.exe -setup`（缺 `eng/`，stdin=NUL）⇒ **rc=3，0.4 秒内返回**（⇒ 确实没暂停），具名说法 `找不到工程侧脚本` |
| 文件数变化 | 90 个 / 13.9 MB。与 §12.7 那次 92 个的差正好是这两件：`启动.cmd`（本次取消）、`eng/tools/fetch_prts_notes.py`（早先那笔取消 —— 那棵树里确实没有它） |
| 安装器四件（装／查／卸／再装） | **首轮未取到**（撞上下面那条 `--tree` 口径问题）；修好后补跑 ⇒ 见下面「补跑读数」一表 |

**补跑读数**（同日，`--tree` 之修与 `pythonEnv`／`PurgePycache` 都落地之后）：

| 项 | 读数 |
| --- | --- |
| `go build ./...` / `go vet ./...` / `go test ./...`（在 `rios-sim/`） | 三个 **rc=0**；`go test` 四个包 `ok`（`rios-sim` 0.49s／`data` 0.82s／`maa` 0.76s／`mech` 0.45s），`cmd/rios-tui`／`core` 无测试 |
| `rios-tui.exe -selftest`（`RIOS_DB` 指本机数据、`RIOS_SIM_BIN` 指发布树引擎、`RIOS_BRIDGE` 指开发树的桥） | **rc=0、✓=237、结论全绿**；唯一剩下的未核是「应答 id 校验分支（需假引擎才走得到）」 |
| 同上但**不设** `RIOS_BRIDGE` | ✓=**233**，差的 4 条正是「要真名册」那一族，且有**具名**未核（桥报 `RosterUnavailable`）—— 发布树的 exe 按 `isReleaseTree` 只在自树里找桥，认的是 `eng/data/skland/`，而那是玩家装完才有的。**这不是回归**，是 §12.7 ③ 记的那条环境差异 |
| 安装器编译（ISCC 6.7.3，`--tree` 传**相对**路径） | **rc=0**，`RIOS-Setup-0.3.2.exe` 5,907,805 B，sha256 `3e8e5d50…`（⇒ `resolve()` 那修实测有效） |
| 第一次安装 | rc=0；运行时该有的 4 件点名在位；`SHA256SUMS.txt` 没进包；玩家的 `eng\data` 活过安装（判据 7 第 2 件） |
| 装完自查（`-preflight`） | rc=3，致命缺件 0 件；**入口 rios-tui.exe 在位且能跑预检，装出来的目录里没有 `启动.cmd`** |
| 静默卸载 | rc=0；程序文件走干净（第 3 件）；玩家数据留下（静默按保留）；**3 处 `__pycache__` 都被带走** |
| 第二次安装（升版本／就地覆盖） | rc=0，装回去了（第 4 件）；收尾再卸一次并清掉临时目录 |
| 装机产物 | 跑完即清（探针树与 `RIOS-Setup-0.3.2.exe` 都不留在 `out/release/` 冒充正式版） |

⚠ **顺带撞到一条口径问题（已修）**：`build_installer.py` 的 `--tree` 传**相对路径**时，ISCC 是**按 `.iss` 所在目录**解析 `Source` 的，于是报
`No files found matching "…\tools\out\release\rios-v0.3.2-probe\*"` —— 一条看上去像「树不存在」的错，其实树在、只是基准目录被拼错了。缺省值（`ROOT/out/release/rios-<版本>`）本来就是绝对路径，所以只有显式传相对路径才会踩。
**处置**：`main()` 里改成 `(Path(args.tree) if args.tree else …).resolve()`，两种写法归一（理由写在那一行的注释里）⇒ 现在传相对路径也对。

⚠ **两条一度登记为「代价」的事，现在都有落点了**（同日改完）：

1. **`PYTHONDONTWRITEBYTECODE=1`** —— 原先由 `启动.cmd` 设，入口取消后一度无人设。**已补两处**：Go 侧统一拼装 `pythonEnv()`（`engclient.go`，四处调用：一次性桥／常驻桥／重建命令／版本探针）＋ `.iss` 的 `[UninstallDelete]` 删 `eng/` 下的 `__pycache__`。逐处落点与配套判据见 §12.7 那条补记。
2. **产品侧提到启动器／`.cmd` 的正文** —— **已逐处改完**（玩家可见的改成「双击 `rios-tui.exe`」或「再双击一次」，注释顺手改）：

| 文件:行 | 原来 | 现在 |
| --- | --- | --- |
| `ak_tactic/cli.py:1783`（docstring） | 发布形态是安装包里的 `启动.cmd` | 安装包里的 `rios-tui.exe`，双击它即入口 |
| `ak_tactic/cli.py:1788`（**玩家可见**） | 或安装包里的 启动.cmd | 安装包装好后双击它 |
| `preflight.go:15`（注释） | 发布树里列着 `启动.cmd` | 只列 `rios-tui.exe`／`rios-sim.exe`／`eng/`，并注明双击 exe 就是入口、没有启动器这类中间件 |
| `preflight.go:111`（**玩家可见**） | 装完再跑一次本启动器 | 装完再双击一次 rios-tui.exe |
| `preflight.go:249`（注释） | 启动器每加一次进程启动 | 入口每加一次进程启动 |
| `setup.go:37`（注释） | 启动器每次都会调它 | 入口每次都会调它 |
| `setup.go:181`（注释） | 同上 | 同上 |
| `setup.go:212`（**玩家可见**） | 再双击一次本启动器即可 | 再双击一次 rios-tui.exe 即可 |
| `setup.go:287`（**玩家可见**） | 再双击一次启动器 | 再双击一次 rios-tui.exe |
| `main.go:136`（注释） | 双击 启动.cmd / exe | 双击 `rios-tui.exe` |
| `console_windows.go:16`（注释） | 根本不需要启动器 | 根本不需要那个壳 |
| `engpipe.go:74`（注释） | 启动器自检 | 启动前自检 |
| `welcome.go:126`（注释） | 启动器自检的第一项 | 启动前自检的第一项 |
| `rios-sim/data/datadb.go:75`（注释） | 启动器自检的第一项 | 启动前自检的第一项 |
| `selftest.go:1740`（判据标签） | 启动器每次都会调它 | 入口每次都会调它 |

（`preflight.go`／`setup.go`／`main.go`／`console_windows.go`／`engpipe.go`／`welcome.go`／`selftest.go` 都在 `rios-sim/cmd/rios-tui/` 下。）

⇒ 产品侧（`rios-sim/**` 与 `ak_tactic/**`）现在**零处**把「启动器」当成一个还在的角色来写；剩下的「启动器」字样只出现在**登记它被取消**的正文里（本文件与 `tools/build_release.py` 的说明段）。

⚠ **一处刻意不改**：`tools/build_release.py`／`tools/build_installer.py`／本文件里那些「启动器已取消」的说法，是**取消这件事本身的登记**，删掉它们才是把账抹了。

### 12.10 `dwell` 的累加序：从「登记容差」改成「修根因」（博士 2026-09-27 裁 A）

**这一节记的是一次裁定的翻转，以及翻转它的那两条实证** —— 因为前一次裁定（同日早些时候的「按登记走、不修产品」）在只把它当成「比较噪声」的前提下是合理的，错的是那个前提。

**形状**：两侧 `visits()` 都是「按**调用方给的格序**拼接 → 再按 `enter` **稳定**排序」。而那个格序在 Python 侧是 `_range_cells` 返回的 `frozenset`（哈希序）、Go 侧是 `Footprint` 的序 —— 两者本来就不同。稳定排序只保证 `enter` 不同的那些有序，**`enter` 相等时保留的正是拼接序** ⇒ 同一个格集合、两种累加序 ⇒ 浮点 `total += hi - lo` 差 1 ulp。

**翻转它的两条实证**（都不是观感问题）：

1. **它不只住在比较里，还漏进了排序。** `value = dwell × atk`，两侧都按 `-value` **稳定**排序 ⇒ 1 ulp 的方向就决定平局谁在前；而 `per_op` 的截断**就切在这个序上**。603 关跑下来有 **6 条候选顺序不同**（`main/easy_14-12`、`main/main_01-09`、`main/main_15-13` 三份内容各带一个别名键），根因全是它 ⇒ 两侧可能留下**不同的六条**。
2. **它让三处守卫永远打不响。** 当时开的容差是 `1e-12 × max(1, visits)`，而 1 ulp 的相对差 ≤ 2.23e-16 ⇒ 只要 `cells` 相同就**必然**被收下，`dwell` / `value` 两栏永不报。`--mutate` 里按字段名认领的 `dwell 末位`／`value 末位`／`期望值 dwell 末位` 三处因此成了**打不响的尺子** —— 它们上一次报「判红=是」，是被自身格那 123 条噪声**按字段名**顶上去的（零行使的绿）。

**修法**：根因在**排序键**上，不在比较上。两侧 `visits()` 改用**全序键** —— `ak_tactic/eta.py` 的 `visit_order` 与 `rios-sim/arrivals.go` 的 `visitLess`，键 `(enter, cell, name, enemy_id, route, exit)`。同 `enter` 的两条 visit 谁在前**只由数据定**，与调用方给的格序无关。尾部的 `exit` 是收口：前六项全等的两条 visit 其贡献相同，余下的稳定序不影响浮点结果（`a + b` 与 `b + a` 在 IEEE 下相等）。

**落点（四笔，本地 HEAD `1020ed1`）**：

| 提交 | 改了什么 |
| --- | --- |
| `dba353e` | 产品两侧全序键（`eta.py` / `arrivals.go`）＋ `candidates.go` 那句过期注释（「`frozenset` ⇒ 顺序无意义」现在**才是**真话：累加序已与格序无关） |
| `e0221e0` | 判据：容差常数与「收下」那一支**整段删除**、`dwell`/`value` 改逐位比；`dwell` 差加**归因取证** |
| `8188b42` | 归因改用**只依赖 Go** 的忠实求和（冻结档也判得了因），两侧比对降级为具名证据 |
| `1020ed1` | `check_go_all.py` 里这一套的状态描述按新口径改齐 |

**读数**（4 关 live 档，含原先分叉的那 3 份内容）：`顺序不一致 6 → 0`；同一侧两种格序给出的 `dwell` **逐位相同**（正对照）；`--mutate` **十二处全部判红、rc=0**（含那三处复活的 1 ulp 守卫）；`check_eta.py` 35 项全过、`go test` 过、`gofmt` 干净（按 LF 归一后验，见本仓 CRLF 假红那条）。

★ **判据的一条新规矩（这次踩出来的）**：`dwell` 逐位不同有**三种**因 —— ① 自身格（`cells` 就不一样）、② **上游 `visit` 字段本身** 1 ulp、③ 累加序。`cells` 相同**只排掉 ①**。上一版判据在读数里写了一句「其中 N 条连 `cells` 都完全相同（**纯累加序所致**）」—— 那句话在 ② 存在时是**假的**。⇒ 判据不许**猜**因：现在要么证明、要么明说证明不了（用 Go 自己的 visit 按本口径复算，与 Go 自报的 `dwell` 逐位相同 ⇒ 差在**输入**；不等 ⇒ 本套的账）。同时写死一条：`bad` 一非 0 就**不印**「一致」，按族逐条点名 + 末尾一条兜底 —— 上一次出现过「rc=1 而日志里只有一句自称逐字段一致」的形态，判决没说清自己为什么红。

**仍未落定的一项（博士 2026-09-27 裁 D：先不裁）**：`main_15-13` 上还剩 **32 条 `dwell` 差**，取证到根因是**上游 `visit` 字段本身 1 ulp** —— `寒灾回响 (9,0)` **一条** visit 的 `enter`／`exit` 各差 1 ulp（Python `53.060915267313263` / Go `53.06091526731327`），那一格在候选范围里，于是所有覆盖它的候选一起偏 2 ulp。取证脚本 `out/acceptance/_diag_dwell1513.py`（只读）。它是 `arrivals` 那一套与 eta 移植的账（那边读数 `visit.enter=170 / visit.exit=168`）。**处置：本套如实红着（归因栏具名印出），等上游那一族修完重跑再定要不要改口径。** 顺带，同一族的第三处已交 eta 支一并修：`CellDwell` 拿 `math.Max(0, NaN)` 得 NaN（权威 `max(0.0, nan)` 给 `0.0`）、`CellDwell` 未走 `sumLikePython`、`Busiest` 遍历 Go map 是随机序 ⇒ `main_17-08` 连问 12 次得 12 种应答形状。

**基线**：`fixtures/golden/候选生成.json` 必须按新口径**重录**（`eta.py` 动了，冻着的期望值就是旧累加序的）。重录与冻结档复跑的读数另记。

