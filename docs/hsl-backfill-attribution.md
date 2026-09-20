# 怀黍离（`act31side`）零作业关 · 归因表

| 项 | 值 |
|---|---|
| 建立者会话 | `session-b9dfaa5f-149f-4172-ac8d-49e4f21d46db`（RIOS 怀黍离补齐） |
| 时刻 | 2026-09-20 12:2x（本表所有数字都是这一刻的快照） |
| 树 | `<仓库根>`，HEAD = `9d63b05`（本表写作时工作区有别的会话的暂存改动，与本表无关） |
| 仪器 | 未跑引擎。本表**不含任何判决读数**，只有数据侧勘察与代码侧取证 |
| 性质 | **手写文档**（不是生成物，不会被重新生成冲掉）。每一行都附复算命令，欢迎按命令复算打脸 |

**本表要回答的唯一问题**：`act31side` 里「有索引、没有作业」的关，各**先卡在哪一环**。

四环的定义（沿用 PM 派遣口径）：①没有关卡数据 ②没有夹具 ③没有基线 ④机制没移植。

---

## 〇、一句话结论

零作业的是 **17 关**（不是 18，见 §一）：`mo01` + `s01`–`s04` 这 5 个基础关**先卡在②没有夹具**；
`ex01#f#`–`ex08#f#`、`s01#f#`–`s04#f#` 这 12 个四星档**先卡在④机制没移植**——
而且卡的不是某一关的某个装置，是**难度这整条轴没接线**，所以今天给 `#f#` 写夹具，
只会录到一份**与普通档逐位相同**的读数（已实测两例，§四.3）。

---

## 一、口径更正：零作业是 17 关，不是 18

PM 派遣表给的是「全量 36 = 基础 24 + `#f#` 12；有作业 18；零作业 18」。
**「零作业」这一栏的来源是 `out/*.json` 的扫描结果，不是判据集**。两处差异：

| # | PM 表 | 实测 | 证据 |
|---|---|---|---|
| 1 | `_07` 零作业 | **`_07` 有作业**：`fixtures/plan-hs07.json`（2 手，commit `e9ed143`） | 该文件在 `fixtures/` 里且带 `stage`+`deploys` 两键；`out/` 里恰好**没有**它 |
| 2 | — | `act31side_08` 的作业**不在判据集**：`out/mech_parity_reborn_plan.json`（5 手） | `out/` 是易失目录；`fixtures/` 里没有第二份 `stage=act31side_08` 的夹具 |

**根因（代码级）**：

* `tools/golden_go.py::plan_files()` 是**判据集的认定口径**：
  `src = FIXTURES if FIXTURES.is_dir() else OUT`，且**按 schema 认**（`deploys` + `stage` 两键都在），不按文件名。
* 而 `tools/gate_ledger.py` 的 `PLAN_GLOBS` **只扫 `out/*.json`**；它自己那个「优先 `fixtures/`」的
  `fixture_globs()` 是**死代码**（迁移没做完）。PM 的台账走的是后者。

⇒ **判据集（`fixtures/`）里零作业的是 5 关：`mo01`、`s01`、`s02`、`s03`、`s04`。**
`fixtures/` 现有的 `act31side` 作业覆盖 18 个阶段：
`01`–`07`、`09`、`ex01`–`ex08`、`tr01`、`tr02`。

复算：

```
python tmp\inv.py                     # 逐份打印 fixtures/ 与 out/ 里夹具的 stage 与手数
```

---

## 二、归因表（17 行）

图例：✓ 有；✗ 无；**△** 有但不合格（说明见备注）；**?** 未核。

| 关卡 | ①数据 | ②夹具 | ③基线 | ④机制 | **先卡在哪一环** | 备注（证据） |
|---|:--:|:--:|:--:|:--:|---|---|
| `act31side_mo01` | ✓ 已取 129345 B | ✗ | ✗ | **△ 有疑** | **②** | 索引有条目、缓存有；本关**无 `#f#` 档**。机制面：预置阻流阀×3，且出怪表里有**田鼷族**（会攻击阻流阀）⇒ 走的就是「拆阀还原」那条路，而它在 Go 侧没有生产调用点（§四.4） |
| `act31side_s01` | ✓ 已取 52612 B | ✗ | ✗ | ? 倾向齐 | **②** | 数据文件是 `level_act31side_sub-1-1.json`（**不能按关卡号猜文件名**）。机制面：预置阻流阀×4＋天桩×4，支线召失控天桩-甲；Go 的天桩链已接线（§四.4） |
| `act31side_s02` | △ 索引有，**本树未取** | ✗ | ✗ | ? | **②** | 缓存无 `sub-1-2`。第一步动作＝取数（会落缓存，`data/gamedata` 已 gitignore，**不许 `git add`**） |
| `act31side_s03` | △ 同上（`sub-1-3`） | ✗ | ✗ | ? | **②** | 同上 |
| `act31side_s04` | △ 同上（`sub-1-4`） | ✗ | ✗ | ? | **②** | 同上 |
| `act31side_ex01#f#` | ✓ 与基础版同一文件 | ✗ | ✗ | **✗ 未移植** | **④** | 四星档专属 rune：`level_predefines_enable`／`global_lifepoint`／`enemy_attribute_mul`——全部静默不生效 |
| `act31side_ex02#f#` | ✓ 同上 | ✗ | ✗ | **✗ 未移植** | **④** | `global_lifepoint`／`enemy_attribute_mul`×2 |
| `act31side_ex03#f#` | ✓ 同上 | ✗ | ✗ | **✗ 未移植** | **④** | `env_system_new`(FOUR_STAR)／`global_lifepoint`／`enemy_attribute_mul`；本关普通档的 `env_system_new` 是 NORMAL，**两档数据真的不一样** |
| `act31side_ex04#f#` | ✓ 同上 | ✗ | ✗ | **✗ 未移植** | **④** | ＋`enemy_skill_blackb_mul` |
| `act31side_ex05#f#` | ✓ 同上 | ✗ | ✗ | **✗ 未移植** | **④** | ＋`level_hidden_group_enable` |
| `act31side_ex06#f#` | ✓ 同上 | ✗ | ✗ | **✗ 未移植** | **④** | ＋`global_token_cnt_add`（装置额度） |
| `act31side_ex07#f#` | ✓ 同上 | ✗ | ✗ | **✗ 未移植** | **④** | ＋`enemy_talent_blackb_mul` |
| `act31side_ex08#f#` | ✓ 同上 | ✗ | ✗ | **✗ 未移植** | **④** | ＋`env_system_new`(FOUR_STAR)；**本表认为这是 12 个 `#f#` 里最便宜的一关**（§五） |
| `act31side_s01#f#` | ✓ 与基础版同一文件 | ✗ | ✗ | **✗ 未移植** | **④** | `global_lifepoint`／`enemy_attribute_mul`（本关 `enemy_attribute_mul` 同时有 ALL 与 FOUR_STAR 两份）／`env_system_new`(FOUR_STAR) |
| `act31side_s02#f#` | △ 索引有，本树未取 | ✗ | ✗ | **✗ 未移植** | **④** | 先卡④（数据也还没取） |
| `act31side_s03#f#` | △ 同上 | ✗ | ✗ | **✗ 未移植** | **④** | 同上 |
| `act31side_s04#f#` | △ 同上 | ✗ | ✗ | **✗ 未移植** | **④** | 同上 |

**为什么 `#f#` 的「先卡环」是④而不是②**：④是**前置**的。今天写一份 `#f#` 夹具，
拿到的是**普通档的读数**（§四.3 实测：`spec_sha` 逐位相同）——那不是「多补一关」，
是「给同一关录了第二份一模一样的读数」，还会顺手污染台账（多一行看着像覆盖率提高）。
按 2614aa70 的口径：**没跑的那一步不为缺失负责，但「跑了却问错了对象」要负责**。

---

## 三、两条边界件（不在零作业名单里，但会影响别人按名单干活）

| 关卡 | 状态 | 说明 |
|---|---|---|
| `act31side_07` | 三件齐，但**仪器身份待重录** | `fixtures/plan-hs07.json`（`e9ed143`）＋基线条目在 `fixtures/golden_go.json`。但该条目记的 `engine_bin_sha16 = 6ab41e7de224017f`（`rios-sim-4f47539b.exe`），**不是**现钉的 `1DD24575475ECB07`。⇒ 用钉住的仪器跑 `--check`，它报的是**仪器差**，不是漂移；要它进「仪器身份齐全」的名单，得用钉住的仪器重录一遍 |
| `act31side_08` | 作业只在 `out/` | `out/mech_parity_reborn_plan.json`（5 手）。`out/` 易失 ⇒ 它现在**不在判据集**。要算数，得先把夹具落进 `fixtures/` 并走 `golden_go.py --extend` |

---

## 四、我实测到的机制面（本节全部是复算得出的，不是转述）

### 1. 索引与缓存（复算：`python tools\hsl_backfill_probe.py --data`）

* 索引 36 条 = 基础 24 + `#f#` 12，逐条带 `difficulty`（`#f#` 是 `FOUR_STAR`）。
* **每一对「基础 / `#f#`」的 `data_path` 逐条相同**（12/12）——四星档在数据源里**没有第二份文件**，
  只有那张索引记着难度。⇒ 难度只可能从**索引**流进模型。
* 缓存命中 21 个文件（30 条索引）；缺 `sub-1-2/3/4` 三个文件（对应 6 条索引：`s02`/`s03`/`s04` 及其 `#f#`）。

### 2. 四星档专属 rune 逐关点出（复算：`python tmp\survey_hsl7.py`）

* `01`–`09`、`mo01`、`tr01`、`tr02`：只有 `env_system_new`（掩码 `ALL`），**一条 FOUR_STAR rune 都没有**
  ——与它们**没有 `#f#` 档**这件事自洽。
* `ex01`–`ex08`、`sub-1-1`：**每条都带 FOUR_STAR rune**（`global_lifepoint`、`enemy_attribute_mul` 打底，
  外加 `level_predefines_enable`／`enemy_skill_blackb_mul`／`enemy_talent_blackb_mul`／
  `level_hidden_group_enable`／`global_token_cnt_add` 之一）。

⇒ 12 个 `#f#` **数据侧确实定义了差异**（最少也是「生命点改 1 ＋ 敌人属性倍率」两条），
不是空壳。差异在**流水线里被丢掉**，不是在数据里不存在。

### 3. 难度轴未接线（本表最硬的一条，两处独立取证）

**a. 结构取证**——`difficulty` 在链路上没有被接起来：

* `ak_tactic/gamedata/stage.py::parse_stage(raw, *, level_id, code)` **没有 `difficulty` 参数**；
  `load_stage` 拿到的 `entry`（带 `difficulty`）只用来取数，**难度在这一步被丢掉**。
* 实测 `getattr(stage, 'difficulty', '<无此属性>')` → `<无此属性>`（对 `act31side_s01` 与 `s01#f#` 都是）。
* `ak_tactic/verify.py:410-417`：`environment_difficulty` **只从 `**switches` 取**，缺省 `"NORMAL"`，
  没有任何调用方从关卡推它。

**b. 读数取证**——同一份作业、同一份数据，两个 stage id 建出**逐位相同**的规格：

```
python tools\hsl_backfill_probe.py --auto act31side_s01 act31side_s01#f#
  act31side_s01    spec_sha=5c4bf6011c5b223f3b3806906edaed342ea757a1823254e2170970dee5c3b99f
  act31side_s01#f# spec_sha=5c4bf6011c5b223f3b3806906edaed342ea757a1823254e2170970dee5c3b99f
python tools\hsl_backfill_probe.py --spec fixtures\plan-hsex01.json --stage "act31side_ex01#f#"
  spec_sha=39b1b02f3b5e4820728c65e2654c801ca12a67e89323ded38e76bf611fafdbcb   （与不覆写时逐位相同）
```

两例都是**换 stage 不换读数**。⇒ 今天写 `#f#` 夹具，录到的是普通档。

### 4. Go 侧接线状况（`rios-sim/mech/huai_shu_li.go`，逐行读数）

| 机制 | Go 侧状态 | 证据 |
|---|---|---|
| 天桩链（装置→甲→乙→天标） | **已接线** | `PileTick`（:197）、`summonParents`（:245，每个 `kind=pile` 装置在自己格上召一名甲）、`parentTick`（:291）、`diverTick`（:393）、`markTick`；装置三型按 `Kind` 分派（:1255-1274） |
| 泵站 | **已接线** | `m.pumps`（:1257）、`EnvTick` 里每秒泵一次（:1297-1308，排在伤害结算前） |
| 阻流阀**开场断田** | **已接线** | 几何烘进 `spec.Severed`（:680-681），`Farmland.Sever`（:794） |
| 阻流阀**运行期被拆 → 地形还原** | **未接线** | `Farmland.Restore`（:837）在**全树只有 1 个调用点，且在测试里**：`rios-sim/mech/farmland_golden_test.go:95`。生产路径没有。:1266-1272 明写「阻流阀**不该出现在规格里**……收到了就拒跑」 |

⚠ 两条与「按名字 grep」有关的更正，我**自己先踩了一次**：
`grep -r "dhdcr\|dhtl" rios-sim/` 是 **0 命中**，但**不能据此说天桩链没移植**——
Go 用的是 `Kind` 字段（`valve`/`pump`/`pile`），不是 `trap_146_dhdcr` 这个 key。
「0 命中」只有两种含义：对象真没有，或尺子问错了（0752e3c2）。

### 5. 会拆阀的敌人在哪几关（复算：`python tmp\survey_hsl5.py`）

按 `waves` ＋ `branches` 的 key 逐关解出敌人名字，**田鼷族（会攻击阻流阀）在**：
`03`、`04`、`05`、`06`、`08`、`ex02`、`ex06`、`ex07`、`mo01`、`tr01`。
其余关（含 `01`、`02`、`09`、`ex01`、`ex03`、`ex04`、`ex05`、`ex08`、`sub-1-1`、`tr02`）**出怪表里没有田鼷**。

⇒ PM 线索里把它归到「装置层（阻流阀被拆 → 地形还原、天桩链）」的 `ex03`，
**实测出怪表里没有田鼷**（只有除秽/厌肮/勿玷＋失控天桩-甲）；天桩链也已接线。
**我这条线索未核**——它可能与这条不符，需要用真夹具量一次才知道。
`ex07` 则确实有田鼷猛士 ＋ 阻流阀×9，是**真会走拆阀那条路**的一关。

---

## 五、按「先卡环」排出的补关顺序与代价

| 序 | 关 | 要做的动作 | 代价 |
|---|---|---|---|
| 1 | `ex08#f#` | 先修④（难度接线，3 个文件的小改），再录夹具＋基线 | **最低**：已有 `fixtures/plan-hsex08.json`（1 手），既有基线 46.5333 s——是全部 EX 里最短的一关 |
| 2 | 其余 11 个 `#f#` | 同一个④修好后逐关可跑；作业可先**沿用普通档**（夹具不要求三星，但 `title` 里必须写清「沿用普通档，不是四星档的解」） | 每关一次引擎跑（121 s ~ 240 s） |
| 3 | `s01` | 新作业（`python -m ak_tactic search`）＋夹具＋基线 | 机制面倾向齐（天桩链已接线、无田鼷），但**作业成本未知** |
| 4 | `mo01` | 除夹具外，还要处置「拆阀还原未接线」 | **最贵**：200 条出怪、15 个敌人格、129 KB 关卡数据；且④有一条没落地 |
| 5 | `s02`–`s04` | 取数 → 建规格 → 夹具 → 基线 | 未知（要先取数） |

**④（难度接线）的判据**：既有的**每一份**夹具，`spec_sha` 必须逐份不变。
这条判据已经建好并且现在就是绿的（不跑引擎，纯 Python 算规格）：

```
python tools\hsl_backfill_probe.py --zero-change
  判据集 23 份：spec_sha 一致 23、变了 0、基线缺 0、抛错 0        ← 2026-09-20 12:26 现算
```

⚠ **份数不要写死在脑子里**：这一条我写作过程中就变了两次（20 → 23），
因为别的会话正在往 `fixtures/` 里加夹具（`plan-main-00-01/01-07/02-01`）。
判据是「**每一份**都不变」，不是「那 20 份不变」——跑之前现算，跑完比的是**同一批**。

（改④之前跑一次是基线，改完之后再跑一次必须**还是这些份数、且逐份一致**。变了就是动了既有读数。）

---

## 六、未核（写清楚，不许拿猜测顶替）

1. `s01`–`s04`、`mo01` 的④**没有实测**。理由：没有夹具就建不出**真**规格。
   我用「本关自己的可部署格凑出来的最小作业」建过规格（`--auto`），
   `unsupported` 为空——但**那份作业不是打法**，它的读数不具判决意义，只能说明「规格建得出来」。
2. 「拆阀还原未接线」**影响哪几关的读数**未量。要量它，得先有那几关的真夹具。
3. `#f#` 修好④之后，Go 侧是否**完整**吃下四星档（尤其是 `enemy_attribute_mul` 与
   `global_token_cnt_add` 两条），未核。已知：`enemy_attribute_mul` 走 Python 侧 `wrap_enemy_at`
   折进规格数值，而 `global_token_cnt_add`（装置额度）走的是另一条路。
4. PM 线索里把 `ex03` 归到「装置层未移植」这一条，与我实测（无田鼷、天桩链已接线）**不符**，
   未核。

---

## 七、复算命令总表

```
python tools\hsl_backfill_probe.py --data              # 索引 36 条 + 缓存命中
python tools\hsl_backfill_probe.py --auto <stage>...   # 对没有夹具的关建规格（凑最小作业）
python tools\hsl_backfill_probe.py --spec <夹具> [--stage <覆写>]
python tools\hsl_backfill_probe.py --zero-change       # 判据集每份 spec_sha 逐份对基线
python tmp\inv.py                                      # fixtures/ 与 out/ 里夹具的 stage 与手数
python tmp\survey_hsl5.py                               # 逐关敌人 id → 名字
python tmp\survey_hsl6.py                               # 逐关预置装置构成
python tmp\survey_hsl7.py                               # 索引 + 缓存 + 逐关 FOUR_STAR rune
```

（`tmp/` 已 gitignore：本表引用的四个勘察脚本是**一次性探针**，不入库；
入库的是 `tools/hsl_backfill_probe.py`。）
