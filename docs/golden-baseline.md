# 冻结基线：逐套状态与主判据

**这份文件不干活，它只登记状态。** 状态本身**现算**，不由本文件声明——
本文件里的任何一个数，都可以用下面那条命令重新算一遍，算不出来就是本文件过期。

## 0 · 主判据（现算，不是登记表）

```
python -X utf8 tools\freeze_baseline.py --status
```

`2026-09-24 02:13` 实测（仪器 `out\acceptance\rios-sim-stage3.exe`，sha256(16)=`908e2d2edce63543`）：

```
✓ 生命上限   冻结rc=0   默认档=绿        基线=有  0.2s
★ **冻结模式下跑得通：1 / 26 套**
有基线的 1 套里，两种模式**都给绿**（＝这一套的基线录对了）：1 / 1
```

★ 两个数的分母**不同、不可并列**：`1 / 26` 的分母是**全部套**（含 25 套还没录），
`1 / 1` 的分母是**跑过默认档那一腿的套**（＝有基线的套）。没基线的套印 `⊘无基线`——
「没跑」与「跑了但不一致」不许混成一个数。

`--status` 在没全绿时 **rc=1**（所以它是可以接进门的判据，不是一张给人看的表）。
**把这一刀接进验收门不在本会话的产权范围内**（`tools/check_go_all.py` 归上级会话），
本会话只保证它**可接**：一条命令、一个退出码、一个现算的数。

## 1 · 为什么做这件事

博士 2026-09-24 亲自问：**「为什么现在还在和 python 对拍？不是已经由 go 覆盖了吗」**。
逐套量的实测结果是 **26 套里 24 套现跑 Python 当 oracle**。而 2026-09-19 已经裁定过：

> 引擎切换定案：基线全用 Go、Python 仅作历史参考、**门判据＝Go 自身基线漂移即红**。

这条**没落地**。继续吃 Python 的三条代价：

* (a) 有人改了 `ak_tactic/`，**判据的期望值跟着变** ⇒ 两侧同错也判绿；
* (b) `ak_tactic/` 永远删不掉；
* (c) 它量的是「与旧实现一致」，**不是「对」**。

## 2 · 三种模式与退出码

| `RIOS_GOLDEN` | 语义 | 吃 Python 吗 |
| --- | --- | --- |
| 未设 / `0` / `off` | **现状**：现场调 `ak_tactic` 取期望值（对拍）。迁移期默认档，一个字不改 | 吃 |
| `record` | 调 `ak_tactic` 取期望值，**同时**把 `键 → 值` 收下来（由 `--record` 落盘） | 吃（录的时候本来就要吃） |
| `check` | **只读** `fixtures/golden/<套名>.json`；`ak_tactic` 被封死 | **不吃** |

退出码：判据自己的码不动；**`6` ＝ 通道自己的错**（无基线 / 键缺 / 顶层 import 了
`ak_tactic` / 期望值不可 JSON 化 / **脚本从未绑定通道**）。
`6` 的含义是「**这一套还没转**」，**不是「判据红」**——两者压成一个值会同时毁掉两个判读。

**两条防线**（少一条就会有假绿）：

1. **import 拦截器**：`check` 档下 `import ak_tactic` 立即 ImportError。没转好的取期望值点
   当场响，不会静默走回 Python。
2. **绑定断言**：`check` 档的进程退出时，若这一套**从未** `bind()`，以 rc=6 收场。
   ★ 没有它，一套**一个字没改**的脚本在 check 档下会照常跑 Python 并报绿——
   「未转」被读成「已转」。这是本设计的要害。

因此 `check` 档**必须经 runner** 起进程：
`python tools\freeze_baseline.py --run-script tools\check_xxx.py`。
直接 `RIOS_GOLDEN=check python tools\check_xxx.py` 只对**已转**的套安全（防线 1、2 都在
`bind()` 里），未转的套那样跑会假绿。

## 3 · 逐套状态（26 套 = `tools/check_go_all.py` 的 `SUITE`，**不在这里抄第二份**）

「初判」一栏是**给后续节点排序用的**，**不是结论**——「能冻」的证明只有一条：
`--record` 跑通、`--status` 上那一格变 ✓。所有初判均标 **未核**。

| # | 套名 | 脚本 | 状态 | 取期望值的那一段（oracle） | 初判（未核） |
| --- | --- | --- | --- | --- | --- |
| 1 | 关卡 | `check_stage_go.py` | **未转** | `gamedata.stage.load_stage` | 乙 |
| 2 | 敌人 | `check_enemy_go.py` | **未转** | `enemy_stats` / `EnemyLibrary` / `load_stage` | 乙 |
| 3 | 干员 | `check_operator_go.py` | **未转**（**归另一个会话，本会话不碰**） | `OperatorCalculator` / `TalentBook` / `traits` / `talents` | 乙 |
| 4 | 范围 | `check_range_go.py` | **未转** | `RangeTable.cells` / `battle.range.footprint` | 乙 |
| 5 | 技能 | `check_skill_go.py` | **未转** | `SkillBook` | 乙 |
| 6 | 分类 | `check_classify_go.py` | **未转** | `skill._classify` / `_split_variant` | 甲 |
| 7 | 生命上限 | `check_profile_go.py` | **已转**（100 值，两档都绿） | `simgo.skills._max_hp_after_bonus` | 甲 · 已核 |
| 8 | 攻击间隔 | `check_interval_go.py` | **未转** | `skill.SkillEffects` / `ASPD_MIN` / `MIN_INTERVAL` | 甲 |
| 9 | 面板 | `check_panel_go.py` | **未转** | `operator_view.OperatorView` / `SkillEffects` | 乙 |
| 10 | 名册 | `check_roster_go.py` | **未转** | `plan.Roster` | 乙 |
| 11 | 练度 | `check_loadout_go.py` | **未转** | `OperatorCalculator` / `Verifier` / `Plan` / `Roster` | 乙 |
| 12 | 计划 | `check_plan_go.py` | **未转** | `plan.Plan` | 乙 |
| 13 | 关卡静态 | `check_stageenv_go.py` | **未转** | `stage_env` / `load_stage` / `mask_applies` | 乙 |
| 14 | 格表 | `check_cells_go.py` | **未转** | `load_stage` / `spec._find_goals` / `_highland_cells` | 乙 |
| 15 | 部分规格 | `check_specgo_go.py` | **未转** | `build_spec` 一族（`SpecInputs` / `Plan` / `Roster` / `stage_env`） | 乙 |
| 16 | 费用天赋 | `check_costbonus_go.py` | **未转** | `talents.squad_cost_bonus` / `TalentBook` / `Roster` | 甲乙混 |
| 17 | 部署费用 | `check_costof_go.py` | **未转** | `Plan` / `Roster` / `Verifier` / `OperatorCalculator` | 乙 |
| 18 | 寻路 | `check_stagepath_go.py` | **未转** | `eta.leading_wait` / `eta.route_plans` / `load_stage` | 乙 |
| 19 | 闸门 | `check_unsupported_go.py` | **未转** | `spec.unsupported_reasons` 一族 | 乙 |
| 20 | 出怪规格 | `check_spawns_go.py` | **未转** | `parse_stage` / `_route_tables` / `_spawn_spec` / `stage_mul` / `enemy_view` | 乙 |
| 21 | 机制规格 | `check_mechspec_go.py` | **未转** | `build_spec` 一族 | 乙 |
| 22 | 单一入口 | `check_buildspec_go.py` | **未转** | `build_spec` 一族 / `battle.sim.make_total_attack` | 乙 |
| 23 | 干员规格 | `check_operators_go.py` | **未转** | `build_spec` / `talent_finders` / `OperatorCalculator` / `Verifier` | 乙 |
| 24 | 自造规格 | `check_sim_selfspec_go.py` | **未转**（**具名**：见 §4 第 24 行） | **无 `ak_tactic` import**：判据是 Go 两种入参形式的**差分** | 丙 · **口径待定** |
| 25 | 调用链 | `check_sim_via_python_go.py` | **未转** | `Plan` / `Roster` / `ensure_go_engine` / `Verifier`；「以前」取自 `git show d4ddc4c:` 的**原文** | 丙 |
| 26 | 命令面 | `check_cli_go.py` | **未转** | **被测方就是 Python CLI**（`python -m ak_tactic stage …`，子进程） | 丙 |

「初判」三类：**甲**＝期望值是纯函数调用（输入可 JSON 化）⇒ 直接可冻；
**乙**＝期望值是「跑一遍 Python 构造/解析/求值」的结果 ⇒ 可冻，但**键必须带输入身份**
（关卡 id、夹具文件 sha、名册、计划），否则「输入换了而基线没换」会变成假绿；
**丙**＝判据的对象是 Python 侧自身的形状（源码 / CLI 行为），冻的只能是**原文或行为**。

## 4 · 未转的 25 套：**具名**理由（逐条，不许写「大致都转了」）

25 套当前都是同一条**程序给出的**具名理由：
`冻结基线防线：套「<脚本>」从未绑定通道（脚本没调 freeze_baseline.bind()）⇒ 未转，rc=6`
—— 即 **一个字还没改**。这不是敷衍的措辞：它是 rc=6 那条防线**现算**出来的，
改一套就少一行。逐套的**实质**理由（能不能冻、冻什么）分列如下：

* **第 1~23 行（甲/乙类）**：**未核——可冻性尚未逐套验证**。
  初判只从各自 `ak_tactic` 的 import 面得出。它们要在各自的节点上被**真录一遍**才算数。
  可能真冻不住的情形只有两类，遇到就具名登记：① 期望值由运行期非确定来源产生
  （时间戳 / 随机 / 文件系统状态）；② 期望值不可 JSON 化。
* **第 24 行 自造规格**：**不吃 Python，但现在也没有冻住的基线**。它的判据是
  「同一关同一计划下，查询形式与造好规格两种入参形式必须逐路径相同」——
  **差分判据**能红的是「两种形式不一致」，**红不了「Go 自己漂移」**。
  把它接到「Go 自身基线漂移即红」上需要一个**口径决定**（冻判决四数？冻规格摘要？
  冻 `unsupported` 逐位？）——**这一条我不自己定**，登记为**口径待定**，留给上级裁定。
* **第 25 行 调用链**：判据对象是 **Python 源码的形状**（不再造规格 / 不再跑模拟器）。
  它的期望值已经有一份冻住的东西：`git show d4ddc4c:<路径>` 的**原文**（不可变对象）。
  冻法应是把「以前」那一侧固化成入库的原文，而不是把 Python 现场输出冻成值。
* **第 26 行 命令面**：**被测方就是 Python CLI**。它 spawn `python -m ak_tactic stage …`
  并断言「缺值输入下不崩」。冻的只能是它的**期望值**（现算的正例/对照集合），
  CLI 本身照跑——本套**不算违规**（见 §5）。
* **第 3 行 干员**：**归另一个会话**（`tools/check_operator_go.py` 是别人的），
  本会话**只读、不改**。它的状态由那个会话推进。

## 5 · 封死的边界（已知，不假装没有）

**拦截器只盖得住本进程的 import。** 判据若 `subprocess.run([PY, "-m", "ak_tactic", …])`
去取期望值，`sys.meta_path` **看不见它**。与其把这句写成口号，不如把它变成一个数：

`check` 档下 runner 会给 `subprocess.Popen` 打一个探针，把**命令行里提到 `ak_tactic`
的每一次 spawn** 记下来并印在结论旁。实测（未转的「命令面」套）：

```
★ 冻结档下 spawn 过 2 个子进程，其命令行里提到 ak_tactic：
    python -X utf8 -m ak_tactic stage main_02-07
    python -X utf8 -m ak_tactic stage act31side_01
```

⇒ 每转一套都要回答一句：**这一套的取数口是不是全走 `G.expect()`**（spawn 计数为 0）。
被测方本来就是 Python CLI 的套（命令面）不算违规——**它测的是 Python，不是从 Python 取期望值**。

## 6 · 本节点（节点一 · 基础设施）实测：命令 + rc + 读数

仪器一律 `RIOS_SIM_BIN=out/acceptance/rios-sim-stage3.exe`
（sha256(16)=`908e2d2edce63543`）。

| # | 命令 | rc | 读数 |
| --- | --- | --- | --- |
| 1 | `python tools\freeze_baseline.py --list` | 0 | 26 套，全部「无基线」 |
| 2 | `python tools\check_profile_go.py`（默认档，改造后） | 0 | `结论：100 / 100 个点逐点一致` ⇒ **现状一字未改** |
| 3 | `python tools\freeze_baseline.py --record 生命上限` | 0 | 写入 `fixtures/golden/生命上限.json`（100 个值） |
| 4 | `python tools\freeze_baseline.py --status 生命上限 --show` | 0 | 冻结 rc=0 / 默认档=绿 / `取期望值 100 次全部命中冻的那份，零次吃 Python` / `ak_tactic 已封死` |
| 5 | `python tools\freeze_baseline.py --status` | 1 | **1 / 26**；25 套的具名理由见 §4 |
| 6 | `python tools\freeze_baseline.py --check 生命上限` | 0 | `现读 ≡ 冻结（100 个值逐键相同）` |

**控制组（「红得起来吗」——绿必须能红）**：

| 组 | 做法 | 应然 | 实测 |
| --- | --- | --- | --- |
| A · 敏感性（负向） | 把冻的那份里 1 个值改 `+1.0`（改 `["maxhp",-1,0,-0.5]`：0.0→1.0） | 判据必须红 | rc=**1**，`✗ base=-1 cur=0 pct=-0.5 —— Go=0 Python=1.0`，`结论：99 / 100` ⇒ **冻的值真的是 oracle，不是摆设** |
| B · 缺键 | 从基线里删掉 1 个键 | rc=6 且具名，**不许**回退 Python | rc=**6**，`冻结基线防线：缺键 1 个` |
| C · 封锁 | 在 check 档跑一套**未转**的脚本（`check_range_go.py`，它在 `main()` 里 import） | 必须响，不许跑 Python | `ImportError: ★ 冻结基线模式…禁止 import ak_tactic` ＋ 防线 `从未绑定通道 ⇒ rc=6`，rc=**6** |
| D · 不装防线时会不会假绿 | 未转的套在 check 档（防线未上） | 会绿 ⇒ 所以防线 1、2 必需 | 见 §2：**这正是第一版的形式**，故 `check` 档一律经 runner |

★ B/D 两组一起才说明「rc=6」这一档**不是**判据红、也**没有**静默漏过去。
★ **A 组是本节点的关键读数**：它证明冻结档的判决**真的由冻的那份值驱动**，
而不是「读了个文件、判决照旧看 Go」（那会是本项目记过的「零信息量的绿」）。

## 7 · 基线里的身份栏位（不是元数据噪声）

`fixtures/golden/<套名>.json` 每条都记：

| 栏 | 值（以「生命上限」为例） | 为什么必须有 |
| --- | --- | --- |
| `suite` / `script` / `script_sha256_16` | `生命上限` / `tools/check_profile_go.py` / 内容 sha16 | 脚本改了而基线没重录 ⇒ 这个 sha 对不上，`--check` 报「该重录」 |
| `recorded_at` | 录制时刻 | 判「这份基线有多旧」 |
| `instrument.sha256_16` | `908e2d2edce63543` | ★ 不记仪器，将来绿红翻转时没人能判是 Go 变了还是仪器换了（本仓在 `baseline-flip-list.md` 有前车之鉴） |
| `python.version` / `git_head` / `ak_tactic.sig16` / `ak_tactic_dirty` | `3.14.4` / HEAD / 85 个 `.py` 的目录签名 / 脏文件名单 | ★ **「用哪个 Python 版本、哪次 HEAD 录的」是基线的身份**：没有它，将来对不上时没人能判是 Go 变了还是 Python 变了。脏名单单独一栏——**脏的那几行正是期望值的来源** |
| `values` / `keys_readable` | 100 个 `键 → 值` ＋ 人读的键 | 键由套自己给，**必须自带全部输入** |

`--record` **必须显式点名**；覆盖已有基线时先打印**被覆盖文件的完整录制身份**，
再把「新增 / 消失 / 同键改值」三栏逐块报出（本仓记过：生成物被静默覆盖，没有历史）。

## 8 · 换基线的当天必须登记

本次迁移是**换尺子**（期望值来源从「Python 现场」换成「冻结文件」）。
按 `docs/baseline-flip-list.md` 的规矩：**换尺子的同一个提交里就要写下哪些条目因此不红了**。
本文件 §3 逐套给出「已转 / 未转」，**未转的一律具名**——没有第三种写法。
另：本次迁移**不改变任何判据的比较逻辑与结论**，每一套在转好的那一刻，
默认档与冻结档**必须同时绿**（`--status` 的「默认档」栏就是这条的证据）。
