
### 3.23 ✅ 甲的自缚晚一帧：真因是**缺夹零**（不是快照）

博士要求把上一轮那处"只对了一半"的改动查到底。查清了，结论与上一轮的猜测**相反**。

**真病根**：Go 的 `diverTick` 里自缚写的是裸的 `u.idleTimer -= dt`，
而原版是 `e.idle_timer = max(0.0, e.idle_timer - dt)`（`sim.py:2730`）。
那个 `max(0.0, …)` **对浮点残差是有意义的**：初值 1.0、`dt` 是 1/30，
反复相减会留下约 2e-16 的**正**残差，`> 0` 又多真一帧，乙整整晚一帧扑出去。

⚠ **而上一轮那条"本帧新建不当帧跑"的快照改动恰好把这个残差抵消掉了**——
两处错误互相遮盖。所以当时看到的是"ex07 全绿 + HS-S-1 转红"这种自相矛盾的画面，
而且它**看起来是验过的**。补上夹零、退掉快照之后两边同时绿。

**两侧的帧相位其实不同，靠夹零之后才等价**：

| | 递减发生在 | 判 `> 0` 发生在 | 出手帧 |
|---|---|---|---|
| 原版 | 帧序 3（`_pile_tick` 之前），且夹零 | 帧序 3.9 | F+30 |
| Go | `diverTick` 内（帧序 3.9），帧首判、帧尾减 | 同函数开头 | F+30 |

⇒ 一个"递减早一帧、判据晚一帧"的组合恰好抵消。**这条等价是脆的**，
改动 `diverTick` 里那两行的任何顺序都必须重跑两个入口。

**只留了天标那条**"当帧不跑"（`u.isMark && u.bornAt == t`）——那是**真的快照语义**
（原版快照取在 ① 之后，乙当帧挂的天标确实不在里面，首次扣血落在 1.0333s）。

**验证与登记**：甲啃啮四组各四笔**逐位相同**；16 份计划 16/16；三判据 11 通过 0 失败。
真因与脆弱点登记在 `docs/uncertainties.md`，Go 侧注释同步改写。

### 3.24 ⊘「咬不到机制」两例的真因：**用例里根本没有这只怪**

`check_mech_parity.py` 的 `HS-EX-7` 与 `HS-8` 被判"把敌方技能出手整组清零、判决一字不变"。

博士先纠正了一处**我读错的原文**：`勿玷` 的能力是「吸收浅水，攻击全图我方近战单位
并造成十字溅射伤害；位于受病害污染的田地上时攻击附带法术伤害并对田地造成病害污染」——
**它照打**，只是**没有普通远程攻击**（原文「不进行远程普通攻击」）。

顺着查：

* Go **确实实现了**这一层：`rios-sim/mech/huai_shu_li.go:1369-1473`，走 `ctx.HitOperator`。
* 钩 `_build_enemy` 数过：`out/plan-hsex07.json` 里刷出来的是
  失控天桩-甲 6 / 乙 40 / 除秽 16 / 身上的天标二 16 / 去蚀 3 / 厌肮 3，
  **带技能出手的出怪 = 0**。`勿玷` 从未生成。
* 代码注释里写着「HS-EX-8 上「勿玷」一度同时有六七只」，而 `out\` 下
  **没有 ex08 的计划**（16 份只有 hsex01–07）。

**⇒ 等效核查做得到，而且不用改数据**：补一份 HS-EX-8 的计划进对拍集，它自带 `勿玷`。
改 `skill_atk_init` 之类的数据动不了判决，因为那只怪压根没上场。

**顺带的仪器教训**（同一个坑本轮踩了两回）：`ENEMYATK-BONUS` **不是**敌方技能出手，
是**重生充能附加伤害**（`rebornChargeBonus`）。把 Go 的 `trace` 标签全表列出来确认：
**没有任何一个标签覆盖敌方技能出手**。这条与记忆里"一个痕迹标签只覆盖发出它的那条路"同源。

### 3.25 怀黍离敌人盘点（本地侧）

`data/enemydb.sqlite` 的 `enemy` 表（1804 行）里，`debut_event = 怀黍离` 的共 **23 只**，
能力都能读到。⚠ 其中 **`玷`（HSL7）与 `勿玷`（HSL8）是同一套能力**，`玷` 也没在任何计划里出现过。

**Wiki 那一半（对照官方图鉴逐只核对能力有没有漏拉）尚未做**——留作下一轮第一件事。

### 3.26 闸门盲区（第三类）：**字段驱动看不见"没有字段的东西"**

**先更正上一轮的两处错误结论**（都是同一个病）：

1. 上一轮写「`spec.py` 闸门对敌人侧能力零提及」——**错**。`spec.py:127` 有
   `bad += _enemy_reasons(sim)`，而且相当完整：`field_why`（awake_value /
   hp_drain_per_sec）、`ENEMY_BEHAVIOR_ATTRS`（modes）、「被击倒给可部署装置」
   的条件分支，外加六族**已接线因此不报**的行为（skill_atk_* / passive_pollut /
   reborn_* / phit_* / reborn_summons / pm2_*，`spec.py:412-426` 逐条有出处）。
2. 上一轮写「击倒后获得可部署单位：原版 0 处、Go 0 处」——**错**。代码里写的是
   「可部署**装置**」，我按「可部署**单位**」去 grep ⇒ 空。
   **某名字不在这一层，不能推出"没实现"**——本条铁律又一次复现。

**真正的缺口**：`_enemy_reasons` 是**字段驱动**的（"`EnemyUnit` 上哪个字段非零"）。
这个设计本身是对的（不看名字、不看关键词），但它有一类**结构性**的盲——
有些能力**在原版里也没拿到字段**，只活在图鉴正文里 ⇒ 闸门对它们**永远沉默**，
而"沉默"与"查过了没问题"在输出上长得一模一样。
⚠ `audit_gate_blindspot.py` 补不了这一块：它扫 `sim.X` 的**读写时机**，是字段级的。

**补上的东西**：`ak_tactic/simgo/mech.py` 新增第三张表 `UNMODELLED_ENEMY_ABILITIES`
（5 条）+ `tools/audit_unmodelled_abilities.py`。判据两道：

* **原版战斗层也没建模**——对每条 `py_tokens` 扫 `ak_tactic/battle/*.py` 的
  **代码行**（docstring 与注释行不计；`devices.py:25` 的「浅水」是泵站正文的文档
  字符串，扫成"已实现"是这类工具最容易出的假红）。命中 0 ⇒ 两台同样不建模 ⇒
  对拍成立 ⇒ **不进闸门**（进了是无理由拒跑，把整关挡在门外）。
* **载体清单对得上**（`carriers` 按**名字**写，不按 enemy_id——同一只怪在不同关里
  有 `_2` 变体后缀）。

**自动守卫**：每条带 `py_tokens`，一旦某条被接进原版战斗层而 Go 没跟上，立刻翻红。
理由会过期而没人知道，所以理由必须带一个能重算的守卫。

### 3.27 ⚠ 这五条**不是"暂时碰不到"**，是当场就在跑

上一轮写「尚未证实有实际损失」——**也错**。`--plans` 逐个计划对出怪表：
**17 份计划里有 14 份带着这些未建模能力**（除秽在 ex07 实测刷了 16 只；
勿玷的吸收浅水正在刚验过的 HS-EX-8 里）。

**但这不是对拍的红**：两台引擎**同样**不建模 ⇒ 四项照样全归零。它是**保真的红**：

* **对拍**问"Go 与原版一不一致" → **一致**；
* **保真**问"两台合起来像不像真游戏" → 这五条上**不像**。

裁定 `77fce667` 只在**对拍**这一层设门槛，所以不进闸门是对的；
但必须**登记在册并带守卫**，否则"两台一起错"会被下一轮读成"这里没问题"。

**回归**：17/17 计划全绿；两个审计工具全绿（闸门盲区 9 条/0 未登记；未建模能力
5 条/0 翻红）；三判据 11 通过 0 失败。详见 `docs/audit-huai-shu-li-enemies.md` §三/§六。

### 3.28 ★ 默认模拟器切到 Go（博士裁定，重构任务收尾）

**博士 2026-09-19 裁定**：「先切过去，python 模拟器直接弃用，切换之后开始补充建模。」
门槛（裁定 `77fce667` 要求"全部通过并经博士确认"）已达：17 份计划四项全归零、
三判据无失败、两处机制缺口已用等效核查补齐。**本轮执行切换。**

#### 改了什么

| 位置 | 改动 |
|---|---|
| `ak_tactic/verify.py:139` | `Verifier(engine=...)` 默认 `"python"` → **`"go"`** |
| `ak_tactic/verify.py:432` | 基类 `_run_other_engine` 新增 `"go"` 分支（**关键**，见下） |
| `ak_tactic/simgo/verifier.py` | 新增 `ensure_go_engine(obj)`：惰性把 Go 出口绑到实例 |
| `tools/parity_plan.py::PyCapture` | **显式钉住** `engine="python"` |
| `tools/check_battle.py` | 24 处 `v = Verifier()` → `Verifier(engine="python")` |

#### ⚠ 切换时撞到的真问题：默认值一改，**全仓会崩**

Go 的出口本来**只挂在 `GoVerifier`（混入 `GoEngineMixin`）上**，基类的
`_run_other_engine` 是一句"基类没有这个能力"的报错。而默认引擎一改成 `"go"`，
**全仓那些裸 `Verifier()` 全都会走进那条报错**——不是跑 Go，是当场崩。

实测复现：`Verifier().run(...)` → `ValueError: engine='go' 没有实现`。

**修法**：`ensure_go_engine(obj)` 把混入类那三个方法 + 计数器**绑到实例上**。
绑实例而不是改类/改继承，两条理由：
* `verify.py` **不能** import `simgo`（`simgo.verifier` 反过来 import `verify`），循环；
  函数内 import 是惰性的，绕开这条边；
* 只有真要跑 Go 的实例付这份代价，`GoVerifier` 那条路完全不受影响。

#### ⚠ 为什么 `PyCapture` 与 `check_battle` 必须**显式**钉住 Python

这是同一条纪律的两半：**默认值改变是静默的语义变化**。

* `PyCapture` 是**对拍基准**。不钉住的话，默认一改它会静默走到 Go 那条路上——
  于是"对拍"变成 **"Go 与 Go 比"**：两边永远一致、全绿，而且**没人看得出来**。
  这是本项目最怕的那种绿。
* `check_battle.py` 那 24 处的期望值是**照 Python 写死的**。不钉住，套件会变成
  在用 Python 的数字考 Go——语义完全不同，且失败原因会被误读成"Go 有 bug"。

⚠ **留一个待博士定夺的口子**：`check_battle.py` 钉在 Python 是**保守**选择
（保住"考权威实现"的原意）。若希望它改成考 Go，那是一次独立变更——因为它同时
会改变"失败意味着谁错"。

#### 验证

```
① 裸 Verifier()  →  engine='go'（实测）
   PyCapture     →  engine='python'（实测）
② 默认路径冒烟：plan-hsex07 → 42杀 3漏 121.3000s 伤害=50627.6
   go_runs=1  go_fallbacks=0  诊断："引擎：rios-sim（Go）……"
③ 回归：17/17 计划四项全归零；三判据 13 例（通过 11/失败 0/咬不到 2）；
   闸门盲区审计 9 条 0 未登记；未建模能力审计 5 条 0 翻红
```

#### 切换后遗留（**保真**课题，不是对拍课题）

`UNMODELLED_ENEMY_ABILITIES` 那 5 条（隐匿 / 吸收浅水 / 田鼷系三项）两台引擎
都不建模，影响 17 份计划里的 14 份。裁定 `77fce667` 的门槛只在**对拍**这一层，
所以不进闸门是对的；博士已定"切换之后开始补充建模"，它们就是那份清单。

### 3.29 弃用 Python 模拟器：**能弃用到哪一步**（含一处前提修正）

博士指示：「第三段那两项都可以改掉了，弃用 python 模拟器的情况下不再需要对拍，
也没有可以参考的由 python 模拟器生成的数据了」；范围追问答：**连原版模拟器一起弃用**。

#### ⚠ 前提修正：`ak_tactic/battle/` **不能删**——它是 Go 的前端

```
build_spec(sim, ...) -> dict        # "BattleSimulator → 规格 dict"
verify.py:19  from .battle import BattleSimulator, Deployment, RangeProvider
spec.py:300   from ..battle import talents as _talents
mech.py:36    from ..battle import environment as env
verifier.py:96  res = sim.run(...)  # 退回原版那条路
```

**Go 那份规格是从一个 Python `BattleSimulator` 实例造出来的。** `battle/` 同时是
Go 的**排程器**与**规格源**；删掉它，Go 路径与"退回原版"那条路**一起断**。

⇒ 能弃用的是**"跑战斗"这个用途**，不是整个模块。要真把 `battle/` 去掉，得先把
排程器与规格构建器移植进 Go——那是另一个量级的工程，不在本次裁定范围内。

#### 落地了什么

| 位置 | 改动 | 理由 |
|---|---|---|
| `tools/check_battle.py` | 24 处 `Verifier(engine="python")` **解 pin** → `Verifier()` | 唯一回归套件，应当考**现行引擎** |
| `tools/parity_plan.py` | 文件头加**废弃横幅** | 对拍前提（两台引擎并存）没了 |
| `tools/check_mech_parity.py` | 同上 | 同上 |

**对拍三件套保留而不删**：它是"切换前 17 份计划四项全归零 / 三判据 11-0-2"这条结论的
**唯一可复现证据**。⚠ 但它们现在**不再是交付门槛**，头上的横幅就是这么写的。
`PyCapture` 仍显式钉 `engine="python"`——原版实现没被删，这条路仍然是真的两台引擎对账，
只是不用于验收。

#### 验证

```
① 自检套件（已解 pin，跑的就是 Go）：**通过 813 项，无失败**   ← 本次切换后最强的一条
② 裸 Verifier() -> 'go'；PyCapture -> 'python'                实测
③ 对拍工具仍可跑（证据用途）：plan-hsex08 四项全归零；三判据 11 通过/0 失败
④ 三个工具语法均通过（⚠ 中途用 `""" + """` 拼 docstring 破坏了 `from __future__`
   的位置，两处都已改成单一 docstring）
```

### 3.30 对拍三件套已删除 + Go 金标准基线已固化（摘除 battle/ 的地基）

博士 2026-09-19 追加裁定：①「不必保留」——对拍三件套删；②「按你说的全部移植」——
把 Python 排程器与规格构建器移植进 Go，从而真正删掉 `ak_tactic/battle/`。

#### ① 已删

`tools/parity_plan.py`、`tools/check_mech_parity.py`。
⚠ 副作用（已查清，不是没看见）：**15 个工具**引用它们——`check_spec_keys.py`、
`dump_spec_key.py`、`sweep_hsl_parity.py`，以及 12 个 `probe_*.py`（它们把
`parity_plan` 当工具库用：`GoCapture` / `resolve` / `compare`）。
这些全是**对拍期的调查工具**，第 ② 项做完后会一并作废；本轮**不擅自多删**，
留待摘除 `battle/` 时统一处置。`tools/selftest.py` **不跑**它们（已确认）。

#### ② 已立的账：`ak_tactic/battle/` 的量级

```
sim.py 4700  unit.py 1452  talents.py 920  environment.py 626
devices.py 326  traits.py 272  stage_mul.py 209  p3r.py 174
displace.py 145  damage.py 133  range.py 115  hammer.py 108
summons.py 75  __init__.py 25          小计 9280 行
另有 tools/check_battle.py 5957 行专考它
```

**核心难点**：`build_spec(sim)` 读的是**活的 `BattleSimulator`**，共 20+ 项
（`stage` / `deployments` / `retreats` / `skill_uses` / `_spawn` / `_range_of` /
`_path_from` / `_devices` / `_pile_mark_key` / `team_auras` / `snow_fields` …），
而 `verify.py` 的排程也建在这个 sim 上。

#### ③ 本轮实际交付：`tools/golden_go.py` —— **迁移的地基**

摘除 `battle/` 最典型的翻车方式是"**规格悄悄变了但判决没变**"（或反过来）。
而对拍三件套刚按裁定删掉了 ⇒ **没有基线，"一致"两字就无从检验**。所以第一件事
是把切换后这一版固化成金标准：

* **口径是 Go 自己**（不是 Go vs Python）——`battle/` 即将不存在，Python 的数字没有复核能力。
* 每份计划记两样：**判决四数**（杀/漏/用时/伤害）＋ **整份规格的规范化 SHA-256**
  （`sort_keys=True`）。只比判决会漏掉"规格变了但这一局恰好没受影响"。
* 规格从哪来：不复制排程逻辑，而是借 `_run_other_engine(sim=...)` 这个**挂载点**
  ——它拿到的正是那个"排好程、还没跑"的 sim。

```
基线：out/golden_go.json（17 份）
plan-hs01   50杀 0漏 134.9333s  89100.0   spec=19822902fa0d
plan-hsex07 42杀 3漏 121.3000s  50627.6   spec=f899f95f74fb
plan-hstr02  7杀 0漏 430.1333s  28000.0   spec=575b375a270c
…（17 份全录）
复算：python tools\\golden_go.py --check → ✅ 全部 17 份与基线逐项一致（含规格哈希）
```

**下一步**：把 `build_spec` 改成从 gamedata + 计划 + 干员计算器直接构建（不再读活 sim），
每改一步用 `golden_go.py --check` 卡住规格哈希与四数。

### 3.31 摘除 battle/ 的**面**已量清：要搬的不到 3%

新目标（摘除 `ak_tactic/battle/`）round 1。**先量面，不动手**——不知道哪些函数真在路上，
就只能整包重写，那是把它当新项目做。

工具：`tools/spec_deps.py`（静态名字可达性，**上界**口径：宁可多算不可少算）。
文档：`docs/spec-extraction-surface.md`。

```
battle/ 全部                        10548 行
从 build_spec 出发可达的函数          10 个，合计 268 行
它们引用的类                          3 个（EnemyUnit 618 / OperatorUnit 844 / BreakState 47）
build_spec 读 sim 的属性              17 项（无函数体 → 改成显式入参）
一份敌人规格实际读的字段              ~40 个标量
```

**可达的 10 个函数**（除末条外全在 `sim.py`）：`_build_enemy` 132、
`_note_mode_skill` 26、`_range_of` 21、`_cannot_clear` 18、`_enemy_stats` 18、
`_path_from` 15、`_summon_level` 14、`_pile_mark_key` 13、`_spawn` 6、
`unit.py::OperatorUnit.current_range_id` 5。

⇒ **整台战斗引擎（`_enemies_attack` / 伤害 / 位移 / 索敌…）根本不在 Go 这条路上**
——打仗那部分已经归 Go 了。**其余 97% 随 `battle/` 一起消失。**

**关键判据**：`_unit_spec`（`spec.py:848`）从敌人对象上读的全是**标量**
（`max_hp`/`atk`/`defense`/`res`/`move_speed`/`attack_interval`/`phit_*`/`skill_atk_*`/
`reborn_*`/`pm2_*`…），**不读对象** ⇒ 把 `_spawn`/`_build_enemy` 换成纯函数
`enemy_stats(enemy_id, level, route_index, t)` 之后，`EnemyUnit` 就不需要了。
（那 618+844 行里最重的方法全是**跑帧**用的，而跑帧归 Go。）

#### 第一批要摘的 8 项，推导已查清（下一轮照抄）

`spec.py:1062-1078` 那 8 项全是 `sim` 的**派生属性**，源头在 `sim.py:418-489`，
与战斗无关。⚠ 两处**容易漏的派生**正是"四星档"的来历：`cost_time` 要被
`cbuff_cost_recovery.scale` **除**；`life` 要被关卡级 `global_lifepoint` **改写**
（八关 EX 的四星档都改成 1，而关卡文件自己是 3）。两者住在 `battle/stage_mul.py`
（209 行，纯函数）。

⚠ `stage_mul.py` **不自足**：`stage_mul.py:42` 有 `from .environment import
bb_number, find_rune, mask_applies`，而 `environment.py` 是 626 行、同时装着田地逻辑。

#### ★ 动手前先查"判据看不看得见"——查出两条，都改变了做法

1. 17 份计划的 keys 只有 `stage`/`title`/`deploys`，**没有难度档**；
   难度来自 `BattleSimulator(..., environment_difficulty="NORMAL")`（`sim.py:381`，构造参数），
   而 `Verifier` 建模拟器时（`verify.py:343`）**不传它** ⇒ 经本流水线**恒为 NORMAL**。
   * **好的一面**：`NORMAL` 下的 `life`/`cost_time` 也是规格字段、被哈希进去了 ⇒ 搬错会翻红 ✓
   * **要紧的一面**：非 `NORMAL` 那条分支是**沉默区** ⇒ 搬迁口径只能是
     **原样搬（move），不许"照 NORMAL 的行为重写"**。
2. `_cannot_clear` 那条同理（它在可达集里，属于要搬的）。

**这一轮没有改任何源码**（除新增工具/文档）：先量面、先验证判据看不看得见，
再动手——这正是本项目反复吃过的"覆盖不到机制的判据只会沉默不会否证"。

### 3.32 摘除 battle/ round 2：新家 `ak_tactic/frontend/` 已开，第一批已搬并接上

#### 新家的位置（有讲究）

`ak_tactic/frontend/`，**不是** `ak_tactic/simgo/frontend/`——后者会踩到
`simgo/__init__` → `spec` → `battle.talents` 的**循环导入**。

依赖方向立住了：`battle/` → `frontend/`（要删的那一边依赖新家），
`frontend/` 不 import `battle/`、也不 import `simgo/`。

```
ak_tactic/frontend/   376 行      （__init__ 25 / blackboard 66 / stage_env 78 / stage_mul 209）
ak_tactic/battle/     9062 行     （迁移前 9280）
```

#### 搬了什么（口径：**原样搬，不重写**）

1. **黑板取值四原语** `mask_applies` / `find_rune` / `bb_number` / `bb_text`
   —— 从 `battle/environment.py` 搬到 `frontend/blackboard.py`。
   `battle/environment.py` 改为**从新家 import 并继续转出**同一个函数对象
   （实测 `env.bb_number is frontend.blackboard.bb_number` → True），
   `__all__` 不变 ⇒ **既有写法一个字都不用改**。
2. **`stage_mul.py`（209 行）整体搬走**（`Move-Item` 保字节 + 只改一行 import）。
   4 处 `activity.py` 的锚点字符串同步改成 `ak_tactic.frontend.stage_mul:...`。
3. **新增 `frontend/stage_env.py`**：把 `sim.py:474-489` 那一段（费用三项 ＋ 生命点）
   原样搬成一个纯函数，另加构造参数那四项。

#### 接上了哪 4 项

`spec.py` 里的 `life` / `cost_init` / `cost_max` / `cost_time`
**不再从活的模拟器上读**，改成 `stage_env(sim.stage, environment_difficulty=...)`。

⚠ **一处必要的"只新增、不改行为"**：`life` 与 `cost_time` 在非 NORMAL 档下与普通档
不同（八关 EX 的四星档把 `global_lifepoint` 改成 1、`cbuff_cost_recovery.scale` 让
每点费用秒数变小），而模拟器**此前没把难度存成属性** ⇒ 规格构建器无从知道按哪一档算。
所以给 `sim` 加了 `self.environment_difficulty = environment_difficulty`（只新增）。

`FPS` 也收成**一份来源**：定义住 `frontend/stage_env.py`，`battle/sim.py:79` 转出。

#### 验证（三道都过）

```
① 金标准：python tools\\golden_go.py --check → ✅ 17 份与基线逐项一致
   ⚠ 这一条是决定性的：那 4 项**都在规格里**，算错一个哈希就翻红。
② 自检套件：813 项，无失败（搬 stage_mul 之后一次、接 stage_env 之后一次，各 813/0）
③ 新函数跨关卡抽样：act31side_01 / 08 / ex07 / ex08 / main_01-07 全部算得出
```

#### 下一轮

继续摘那 17 项属性里剩下的（`deployments` / `_devices` / `snow_fields` / `team_auras` …）
与 10 个可达函数（`_spawn` / `_build_enemy` / `_range_of` / `_path_from` …）。
⚠ 后者要搬 `EnemyUnit` 的**造面板**那一段（不是 618 行整类——`advance`/`take` 那些是跑帧用的）。

### 3.33 摘除 battle/ round 3：敌方三条规矩搬走，可达闭包 10 → 7

新家加一件：`frontend/enemy_rules.py`（`cannot_clear` / `summon_level` / `pile_mark_key`
＋ `PILE_MARK` / `PILE_CHILD` 两张表）。

#### 为什么先摘这三个

`tools/spec_deps.py` 量出的 7 个 `sim.<方法>` 调用里，**这三个是唯一不需要造对象**的
——另外四个（`_spawn` / `_build_enemy` / `_range_of` / `_path_from`）要 `EnemyUnit`
或地图寻路。读一遍就知道它们跟引擎状态无关：

| 函数 | 它到底读了什么 |
|---|---|
| `cannot_clear(unit)` | 单位自己的 `always_invincible` ＋ `route_length` |
| `summon_level(stage, key)` | `stage.enemy_refs` |
| `pile_mark_key(stage, diver)` | `PROSE_SUMMON_EDGES`（**gamedata**）＋ `stage.local_enemy_prefab` |

`PILE_MARK` 与 `PILE_CHILD` 也是从 `gamedata/enemy.py:PROSE_SUMMON_EDGES` 推出来的
（原来写在 `sim.py:150/154`），所以跟着一起搬。

#### 接法

`battle/sim.py` 的那三个方法**改成转调**新家（一份实现、两个消费者），
`spec.py` 则**直接调新家**——每一处都少一次对模拟器的依赖：

```
spec.py 里的 sim.<方法> 调用：9 处 → 5 处
  摘掉：_pile_mark_key(3)  _cannot_clear(1)  _summon_level(2)
  剩下：_range_of(2)  _spawn(1)  _build_enemy(1)  _path_from(1)
```

`spec_deps.py` 复量（闭包确实缩了）：

```
可达闭包    10 个函数 → 7 个（sim.py 6 + unit.py 1）
方法调用     7 项     → 4 项
```

#### 顺手堵掉一个漂移口

搬完发现 `PILE_MARK` **两份定义**（`sim.py` 一份、新家一份）——正是"两边各写一遍
必然走散"。改成 `sim.py` 从新家**转出**，实测 `sim.PILE_MARK is frontend.PILE_MARK`
→ True、`PILE_CHILD` 同。

#### 验证（三道都过）

```
① 金标准：`python tools\golden_go.py --check` → ✅ 17 份与基线逐项一致（规格哈希一字未动）
② 自检：813 项，无失败
③ 别名同一性：两张表都是同一个对象，不是复制
```

#### 下一轮

剩下 4 个方法全都要 `EnemyUnit` 或寻路：
* `_range_of` / `_path_from` —— 看能不能只靠 `stage` ＋ 范围表（`range_provider`）
* `_spawn` / `_build_enemy` —— 要 `EnemyUnit` 的**造面板**那一段（不是 618 行整类）

### 3.34 摘除 battle/ round 4：两条几何搬走 ＋ **一次差点静默出错的险情**

#### ⚠⚠ 险情：`DIRECTIONS` 是**两张不同的表**，我差点把它们并成一张

`battle/unit.py:22` 与 `battle/devices.py:121` **各有一张 `DIRECTIONS`**，
名字相同、**键的大小写不同**：

| 表 | 键 | 消费者 |
|---|---|---|
| `unit.py` | **Title Case**：`"Right"` / `"Left"` / `"Up"` / `"Down"` | 干员的 `direction`、`OperatorUnit.facing` |
| `devices.py` | **UPPER**：`"LEFT"` / `"RIGHT"` / `"UP"` / `"DOWN"` | 装置朝向（`environment.py` / `sim.py`） |

我一开始把 `unit.py` 的 `facing` 改成"转调新家那张表"，而新家那张当时抄的是
**devices 的 UPPER 版** ⇒ `DIRECTIONS.get("Left", (1, 0))` **查不到**、
静默落回默认值 `(1, 0)`——**朝左变成朝右**。

**为什么差点没人发现**：`range_of` 只在**取数钩子失效**时才走"按朝向前方三格"的
退化路径；钩子正常时不碰它。而两张表都不会报错——`dict.get` 的默认值就是这么个东西。

**怎么发现的**：搬之前先去核 `unit.py:22` 到底写了什么（不是"应该一样"），
一读就看到键是 `"Right"`。**没有靠"同名就是同一个"这个假设。**

**修法与守卫**：新家 `frontend/geometry.py` 收 **Title Case** 那张（`range_of` 要用），
`unit.py` 从它转出；`devices.py` 那张**原封不动保留**——它们本来就是两件事。
两边各写了一段警告。抽验：

```
unit 表键 : ['Down', 'Left', 'Right', 'Up']
devices 表键: ['DOWN', 'LEFT', 'RIGHT', 'UP']
两张表是不同对象 : True
facing: Right=(1,0) Left=(-1,0) Up=(0,-1) Down=(0,1) 兜底=(1,0)   ✅
```

#### 搬了什么

新家加 `frontend/geometry.py`：`DIRECTIONS`(Title Case) / `facing` /
`current_range_id` / `range_of` / `path_from`。搬法照旧——**原样搬 ＋ 原处转调**
（`sim.py::_range_of` / `_path_from`、`unit.py::facing` / `current_range_id`、
`devices.py` 保留自己那张）。

#### 顺带修掉一处坏味道

原版为了算"某个**假设位置**上的范围"，是**先篡改干员对象再调 `sim._range_of(op)`**
（`spec.py:349-350` 与 `645-646`）。新接口把位置与朝向**当参数传**，
范围那一问不再需要动任何对象。
⚠ 那两处赋值**仍然保留**——后面的 `op.current_atk()` / `current_defense()` 还要吃
位置上的光环。只把范围那一问改成显式传参。

#### 量出来的进展

```
spec.py 里的 sim.<方法> 调用：5 处 → 2 处（只剩 _spawn / _build_enemy）
可达闭包：7 个函数 → 4 个（且**不再牵 unit.py**）
  剩：_build_enemy 132 / _note_mode_skill 26 / _enemy_stats 18 / _spawn 6
```

#### 下一轮要处理的**真障碍**（这一轮读出来了）

`_note_mode_skill` **不是纯函数**——它写 `self.mode_skill` / `self._mode_next`，
即"造敌人"会**顺手改模拟器状态**。`spec.py` 现在是靠 `copy.copy(sim)` 绕开它
（`spec.py:1005-1007` 有说明）。搬到新家后这个绕法自然消失，
但**迁的时候必须保证那个副作用不被带过来**——否则会提前改掉要跑的那一份。

#### 验证（三道都过）

```
① 金标准：`python tools\golden_go.py --check` → ✅ 17 份与基线逐项一致
② 自检：813 项，无失败
③ 朝向抽验：四向＋兜底全对，两张表仍是两个对象
```

### 3.35 摘除 battle/ round 5：数值取法搬走，**副作用按归属切开**

新家加一件：`frontend/enemy_stats.py`（`enemy_stats` ＋ `mode_skill_from_stats`）。

#### 搬的原则：**纯的整套搬，不纯的只搬纯的那半**

| 原方法 | 纯不纯 | 怎么搬 |
|---|---|---|
| `_enemy_stats` | **纯**（只读 `enemy_at` 钩子与 `stage`） | 整体搬走，一点不改 |
| `_note_mode_skill` | **不纯**（写 `self.mode_skill` / `self._mode_next`） | 只搬"算出黑板"那半；**副作用留在 `sim.py`** |

⚠ `_note_mode_skill` 的副作用是**"造一个敌人会顺手改模拟器状态"**。
`spec.py` 现在正是靠 `copy.copy(sim)` 绕开它（`spec.py:1005-1007` 有说明）。
所以搬的时候**绝不能把那个写入一起带走**——带走了，"造模板"就会提前改掉
"要跑的那一份"，而且**看不出来**。

落地成两个函数：

* `mode_skill_from_stats(stats) -> dict | None` —— **纯**，只算不写；
* `BattleSimulator._note_mode_skill(stats, t)` —— 拿它算完，**再写自己的实例字段**
  （`sim.py:1489-1490`，行为一字不改）。

#### 验证"副作用没跟着搬跑"

```
sim.py:1489  self.mode_skill = bb          ← 写入仍在 sim
sim.py:1490  self._mode_next = t + ...
frontend/enemy_stats.py 里的 self. 只出现在**注释**（讲这个分工），无任何写入
```

#### 顺带记下一条给下一轮的

`_build_enemy` 不只是"把 `stats` 的字段抄进 `EnemyUnit`"——**末尾还有构造后的调整**：

```
sim.py:1690-1692   ratio = stats.shield_hp_ratio
                   if ratio: e.shield = e.shield_max = e.max_hp * ratio
```

即"层数护盾"那套（bug 13 移植过的东西）。搬的时候这一段**不能漏**，
它落在一个 `getattr` 工厂的尾巴上，很容易在抄字段时被跳过。

#### 量出来的进展

```
可达闭包：仍是 4 个函数，但**只有 `_build_enemy`(132 行) 是实在的**
  _enemy_stats      18 行 → 7 行（转调）
  _note_mode_skill  26 行 → 17 行（只留副作用与转调）
spec.py 里的 sim.<方法> 调用：仍是 2 处（_spawn / _build_enemy）
```

#### 验证（三道都过）

```
① 金标准：`python tools\golden_go.py --check` → ✅ 17 份与基线逐项一致
② 自检：813 项，无失败
③ 副作用归属核对（见上）
```

### 3.36 摘除 battle/ round 6：`enemy_view` —— **机械生成**，798 行出怪逐字段验过

最后那块骨头是 `_build_enemy`（造一个 `EnemyUnit` 才能读它的字段）。
这一轮的关键判断是：**不手抄，让生成器从 AST 里抽。**

#### 为什么生成而不是手抄

`_build_enemy` 里那一大段是**同一个形状**的搬运，一共 **80 行**：

```
<字段名>=<从 stats 上 getattr 出来、再转个型或兜个底>,
```

手抄必然错一两个，而抄错的表现是"某个数值差一点"——**最贵的那种**：
不报错、不对齐、要一列一列比才看得出来。

`tools/gen_enemy_view.py` 直接把 `EnemyUnit(...)` 的实参**从 AST 里原样取出**，
生成的代码里放的就是**同一段表达式**。这是"原样搬，不许重写"的彻底版：
连文字都不是我打的。

* 读：`battle/sim.py::_build_enemy` 的 `EnemyUnit(...)` 调用
* 写：`ak_tactic/frontend/enemy_view.py`（幂等；与现有内容一致时不改）
* 自由变量只有 10 个，其中**只有 `self.species_provider` 一个**碰了引擎状态 ⇒ 参数化

#### 读出来的两条口径

1. **`always_invincible` 与 `unblockable` 不在那 80 个里**——它们是**运行时**由天桩
   机制写的（`sim.py:4612-4613` / `4772`）。刚造出来的敌人两者都是 `False`，
   生成物照此置 `False`，由规格层自己显式写死需要的值。
2. 尾部还有**构造后调整**（上一轮就记下了）：`e.reborn_def_base = e.defense` 与
   屏障 `e.shield = e.shield_max = e.max_hp * ratio`。它们形状与那 80 行不同，
   抄字段时最容易漏，生成器里单列一段。

#### 新工具：A/B 逐字段比

`tools/check_enemy_view.py`：对每份计划的**每一行出怪**，同时造真 `EnemyUnit`
与新家 `enemy_view`，比 **54 个字段**。

比哪 54 个不是随便挑的——**与 `spec.py::_unit_spec` 实际读的那一组一一对应**。
判据能看见什么，必须与结论要说的东西对齐。

⚠ 故意**不比 `affinity` / `break_state`**：它们取决于 `total_attack` / `boss_mode`，
而这两个在当前流水线里是关的（两边恒为空），比了只会把"两个都是空"当成通过，
是假信号。

```
$ python tools\check_enemy_view.py
  ...
  合计 17 份计划、798 行出怪；有差异的计划 0 份
  ✅ 规格真正会读的那 54 个字段，798 行出怪**逐个一致**
```

#### 顺带

`path_length`（折线总长）也从 `battle/unit.py:54` 搬进了 `frontend/geometry.py`
（`route_length` 在没有分段腿时要用），`unit.py` 改成转出。

#### 验证（四道都过）

```
① A/B：17 份计划、798 行出怪、54 个字段 → 零差异
② 金标准：`python tools\golden_go.py --check` → ✅ 17 份与基线逐项一致
③ 自检：813 项，无失败
④ 生成器幂等：重跑输出"与现有文件一致，未改动"
```

### 3.37 摘除 battle/ round 7：★ `build_spec` **不再调用 `battle/` 的任何函数**

里程碑。接线用了上一轮生成好的 `enemy_view`，`build_spec` 对模拟器的**方法调用归零**。

#### 做了什么

| 位置 | 原来 | 现在 |
|---|---|---|
| `_spawn_spec` | `sim._spawn(id, lv, route, t)` | `_view(...)`（`enemy_view` ＋ `route_plans`） |
| 天标模板 | `sim._build_enemy(key, lv, [(0,0)], [], 0, 0)` | `_view(...)` |
| `_reborn_summons_spec` 模板 | `copy.copy(sim)` ＋ `probe._build_enemy(...)` | `_view(...)` |

路线分段不再从 `sim._route_points` / `sim._route_legs` 取——改成 `_route_tables(stage)`，
它调的 `route_plans` 就是**原版 `sim.py:583` 用的那一份**（`ak_tactic/eta.py:122`），
所以"两边各写一遍必然对不上"这条风险不存在。
⚠ 路由表**算一次**（里面要走寻路），不能放进按敌人循环里。

#### 顺带消掉一处陷阱

`_reborn_summons_spec` 原来要用 `copy.copy(sim)` 绕开"造敌人会顺手写 `sim.mode_skill`"
这个问题。改用 `enemy_view`（**不写任何地方**）之后，副本与 `import copy` 都不需要了。
这正是上一轮"把副作用按归属切开"的回报——它顺手消掉了一处很容易再踩的坑。

#### 量出来的结果

```
① 属性读：16 项（上一轮 17 项，但成分变了：多了 enemy_at/species_provider，
          少了 _route_points/_route_legs 那些）
② **方法调：0 项**
③ **可达闭包：0 个函数**
battle/ 合计 10277 行（开工时 10548）
```

⇒ **`build_spec` 与 `battle/` 之间现在只剩"读属性"这一种关系，没有任何函数体。**
剩下那 16 项分三类，都有明确的去处：

* **关卡静态 4 项**（`fps` / `speed_scale` / `ranged_enemies` / `enemy_windup`）
  —— `stage_env` 已经会算，缺的是"把这些**原始构造参数**传进来"（现在是从
  `sim` 上读**派生后**的值，反推不回原始值）。
* **gamedata 直取 5 项**（`stage` / `_spawns` / `enemy_at` / `species_provider` /
  `range_provider`）—— `_spawns` 就是 `stage.timeline()`，其余从敌库/范围表拿。
* **排程产物 7 项**（`deployments` / `retreats` / `skill_uses` / `device_deployments`
  / `summon_deployments` / `_devices` / `snow_fields`）—— 落在目标的**第 ② 条**
  （排程层）上，是最需要设计的一块。

#### 验证（四道都过）

```
① 金标准：`python tools\golden_go.py --check` → ✅ 17 份与基线逐项一致
   ⚠ 这一条是决定性的：规格现在**完全由 `enemy_view` 构成**，
     它要与原版一模一样，哈希才会一字不动。
② 自检：813 项，无失败
③ A/B：`tools\check_enemy_view.py`（上一轮建立，798 行出怪 × 54 字段零差异）
④ `spec_deps`：方法调 0、闭包 0
```

### 3.38 摘除 battle/ round 8：★ 排程那一层**几乎不用重写**——量出来的结论

目标第 ② 条（"把排程挪出去"）听上去是最大的一块。**量过之后发现它是白送的。**

#### 反直觉的发现

排程**逻辑**本来就不在 `battle/` 里：

* **费用模型**（"钱够了就下" / 显式时刻按那一刻结账）、落地时刻、地形守卫、
  翔虫机动的上次落点 —— 全在 **`verify.py::run`**（`verify.py:363-414`），
  `battle/` 一行都没有。
* `battle/` 在排程上只出**五个 append**：

| 方法 | 行数 | 正文 |
|---|---|---|
| `plan(dep)` | 2 | `deployments.append(dep)` |
| `retreat(pos, t)` | 2 | `retreats.append((t, tuple(pos)))` |
| `use_skill(pos, t)` | 7 | `skill_uses.append(SkillUse(...))` |
| `plan_device(dep)` | 1 | `device_deployments.append(dep)` |
| `plan_summon(dep)` | 1 | `summon_deployments.append(dep)` |

`Verifier.run` 一共只有 96 行，它对 `sim` 的调用就只有
`sim.plan` / `sim.retreat` / `sim.use_skill`（外加 Go 不走的 `sim.run`）。

⇒ **"把排程挪出 `battle/`"不是重写一套排程器，而是把这五个 append 收进一个
不依赖 `battle/` 的载体。**

#### 本轮做了什么

* 新 `ak_tactic/frontend/schedule.py`：
  * `Deployment` 与 `SkillUse` —— 从 `battle/sim.py:207/232` 搬来的 dataclass
    （纯数据；`Deployment.operator` 那类注解在 `from __future__ import annotations`
    下只是字符串，不牵 import，所以搬走零代价）。
  * `Schedule` —— 五个列表 ＋ **与 `BattleSimulator` 逐字同名同参**的五个方法。
    命名故意一致：迁移期 `verify.py` 可以**同步写到两边**、随时可对，
    切过去只是不再调 sim 而已（strangler 式）。
  * `Schedule.diff(sim)` —— 迁移期的脚手架，`battle/` 删掉后连同调用点一起删。
* `battle/sim.py` 的两个 dataclass 改成**同名转出**。
  验证过是**同一批对象**：
  ```
  sim.Deployment is frontend.Deployment : True
  sim.SkillUse   is frontend.SkillUse   : True
  battle.Deployment 同一对象            : True
  ```
  ⇒ `battle/__init__.py`、`verify.py` 等处的既有 import 全部照旧。

#### 两个字段为什么不进载体（不是漏了）

`snow_fields`（`sim.py:3380`）与 `_devices`（`sim.py:3016`）是**跑帧时**才被填的。
规格在**跑之前**读它们，拿到的本来就是空的 —— 这正是"积雪闸门盲区"那条已知问题
的来历（`build_spec` 取开局态，部署时才建的机制闸门永远看不见）。
载体里不放它们，与那条口径一致。

#### 验证

```
① 金标准：✅ 17 份与基线逐项一致
② 自检：813 项，无失败
③ 身份：三个 import 点拿到同一批对象
④ 摘除面：属性读 16 项、方法调 0、闭包 0（未变——本轮搬的是数据不是调用）
```

#### 下一步

`verify.py::run` 那一处现在是 `sim.plan(...)` 三连。收尾就是：
**让它改调 `Schedule`，并把载体递到 `build_spec`**（迁移期先两边都填、用
`Schedule.diff` 核一遍）。那一步做完，16 项属性读里的**排程产物 7 项**就没了。

### 3.39 摘除 battle/ round 9：`build_spec` 的排程改读新家载体；★ 两种"抄不到"的红长得一样

#### 做了什么

`verify.py::run` 现在把排程**同时写两份**（`Schedule` 与 `sim`），
`_run_other_engine(schedule=...)` 一路递到 `build_spec(sim, schedule=...)`。

* `Schedule` 与 `BattleSimulator` 的方法名、参数**逐字相同**，所以同步只是多一行。
* `Deployment` 对象**两边同一个**——各造一个内容相同的话，`diff()` 比的是"构造"
  而不是"排程"。
* `build_spec` 里那句开关：`sch = schedule if schedule is not None else sim`。

**属性读：16 → 12**，排程产物那 5 项清零（`deployments` 只剩 `snow_mech_spec`
里的兜底分支）。

#### ★ 本轮最值钱的教训：两种"抄不到"的红长得一模一样

金标准第一次是红的，报的是 `spec_sha: 基线='...' 现在=None`。
**从外面看，这是"规格抄不到"——像是这次改动把规格改坏了。但两次都不是。**

| 红 | 真因 | 属于 |
|---|---|---|
| 第一次 | `tools/golden_go.py` 的 `SpecCapture` 复写了 `_run_other_engine` 却没跟上新参数 `schedule` | **工具** |
| 第二次 | `sch` 只定义在 `unsupported_reasons()` 里，而部署循环在 `build_spec()` 里 —— `NameError` | **代码** |

两次都落进 `spec_error` 那条通道，都被打印成"规格抄不到"。
⇒ **`spec_error` 这个通道把"工具坏了"和"代码坏了"压成了同一种颜色。**

处置：
* 工具的钩子签名改成**收 `**kw`**，并在正文写明理由——基类一加参数就
  `TypeError` 的话，那是工具的红，别读成代码的红。
* `build_spec` 与 `unsupported_reasons` **各留一份 `sch`**，并注明"闸门与部署
  循环是两个函数"。⚠ 我一开始是拿 `bad: list[str] = []` 定位插入点的，
  而那段在 `unsupported_reasons()` 里 —— **"看起来像 build_spec 开头"不等于
  它在 `build_spec` 里**。

#### ⚠ 覆盖诚实：那四张表**没被走到**

`Schedule` 五张表在 17 份计划上的合计：

```
部署 46、撤退 0、开技 0、装置 0、召唤 0
```

⇒ **`sched.retreat` / `sched.use_skill` / `sched.plan_device` / `sched.plan_summon`
四处双写是"写了但没验过"的。** 金标准对它们**什么都不说**。

这不是不管了，是查清了没有第二条路绕开载体（全仓调用点）：

| 入口 | 谁在调 |
|---|---|
| `plan_device` | **全仓没有调用者**（`audit_gate_blindspot.py` 早就把它登记为"死判据"） |
| `plan_summon` | 只有 `check_battle.py`（直连 sim，不走 `Verifier`） |
| `retreat` / `use_skill` | 只有我改的 `verify.py` 与直连 sim 的 `check_battle.py` |

⇒ 没有路径绕过载体，闸门口径与迁移前一致。`audit_gate_blindspot.py`：
**7 条已登记、0 未登记、0 守卫失效**。

#### 验证

```
① 金标准：✅ 17 份与基线逐项一致（规格现在从 Schedule 读排程）
② 自检：813 项，无失败
③ 载体一致性：17 份的 `Schedule.diff(sim)` 全部为空（五张表逐条一致）
④ 闸门审计：7 已登记 / 0 未登记 / 0 守卫失效
⑤ 摘除面：属性读 16 → 12、方法调 0、闭包 0
```

### 3.40 摘除 battle/ round 10：关卡静态 8 项改由**调用方从原始参数**给出

#### 做了什么

`verify.py::run` 现在算一份 `env`（`frontend/stage_env.py`）交给换引擎那一侧：
`_run_other_engine(..., env=env)` → `build_spec(sim, ..., env=env)`。

**为什么必须在 `run()` 里算**：那四个参数（`fps` / `speed_scale` / `ranged_enemies` /
`enemy_windup`）是 `**switches`，**只有 `run` 手上有**。`build_spec` 之前是回头问
模拟器要 `sim.speed_scale` —— 那是**派生后**的结果（已乘过关卡的 `move_multiplier`、
已夹过零），反推不回原始参数；靠猜默认值则会在非默认关卡上悄悄分叉。

`stage_env` 的口径与 `sim.py:418-440` 逐字相同，所以算出来的值与模拟器一致。

顺带清掉两处：

* `sim._spawns` → `sim.stage.timeline()`。出怪表是**关卡数据**，模拟器那一次
  只是把它排好序存下（`sim.py:557`）。少读一个**私有**属性。
* `getattr(sim, "skill_uses", [])` → `sch.skill_uses`（上一轮的双写在这儿兑现）。

属性读：**12 → 11**（`_spawns`、`skill_uses` 走掉；那四个静态量仍在，
但只剩 `env is None` 的**兜底分支**里那一次）。

#### 验证：算出来的值 == 模拟器派生的值

```
17 份计划 × 4 项 → ✅ 逐个相同
```

⚠ **但"默认值相等"是最弱的那种证据**——不传 switches 时两边都在用同一个默认。
真正有分量的是**派生那一步**：`speed_scale = 原始 × stage.options.move_multiplier`。
查了 17 关，**6 关的 `move_multiplier = 0.5`**：

```
act31side_ex05 / ex06 / ex07 / ex08 / tr01 / tr02
```

⇒ 那 6 关走的正是"派生"这条路，值仍然逐个相同。这条证据才算数。

#### ★ 第三次"机械替换撞作用域"

`NameError: name 'stage' is not defined` —— 我把 `sim._spawns` 换成 `stage.timeline()`，
而 `stage` 不是 `build_spec` 的局部名（它是 `sim.stage`）。

前两次同类（round 9）：`sch` 定义在 `unsupported_reasons()` 而用在 `build_spec()`；
更早是 `unit.py` 的 `DIRECTIONS` 大小写。

**共同形态**：替换的目标**看起来**在当前作用域里，实际不是。
⇒ 纪律：**机械替换之后立刻跑一次**（金标准就是那次"立刻跑"），
而且替换时优先用**能从当前作用域直接看见的写法**（`sim.stage.timeline()`），
不要顺手简化成"看起来更干净"的名字。

#### 验证

```
① 金标准：✅ 17 份与基线逐项一致
② 自检：813 项，无失败
③ env 一致性：17 份 × 4 项逐个相同（含 6 关 move_multiplier=0.5 的派生路径）
④ 摘除面：属性读 12 → 11、方法调 0、闭包 0
```

### 3.41 摘除 battle/ round 11：★ 纠正一个错误结论——"闭包归零"是仪器的视野给的

#### 我之前说过什么

round 7 起，我一直在报 **"方法调 0 项、可达闭包 0 个函数"**，并据此说
"`build_spec` 与 `battle/` 之间只剩读属性这一种关系"。

**这个结论是错的。**

#### 怎么发现的

本轮为了算"`SpecInputs` 要覆盖多少字段"，新写了 `tools/spec_sim_surface.py`。
第一版用**正则扫行**，把文档串里的名字也算进去了（`py`、`_attach_skill`…），
读数虚高到 30 项。改成 **AST 只认真的属性访问**之后，`mech.py` 那 8 项里赫然有
`sim._build_enemy` —— 而 `spec_deps.py` 同一时刻报的是"方法调 0"。

**两个工具的结论互相矛盾**，于是去查 `spec_deps.py` 扫哪些文件：

```
spec_deps.py:44   SPEC = ROOT / "ak_tactic" / "simgo" / "spec.py"
```

**它只扫 `spec.py`。** 而 `mech.py` 里那 5 个 `sim._*` 调用一直是活的：

| 名字 | 位置 | 干什么 |
|---|---|---|
| `_spawn` | `mech.py:210` | 天桩链里刷敌人 |
| `_pile_spec` | `mech.py:258` | 装置 → 甲 |
| `_build_enemy` | `mech.py:267` | 模板"真建出来" |
| `_summon_level` | `mech.py:267` | 同上 |
| `_pile_mark_key` | `mech.py:313` | 乙 → 天标 |

⇒ **仪器没往那边看，那 5 个名字就从来没机会出现，看起来像"已经摘干净了"。**
这正是本项目反复吃亏的同一形态：**判据覆盖不到的地方只会沉默，不会否证**
（已有记忆 `909503b7`、`1c768671`）。一个"归零"的读数，
必须先问**"这台仪器看得见哪些文件"**，再当结论用。

#### 修仪器

`spec_deps.py` 改成扫 **整个 `simgo/` 包**（现在 6 个文件），并：

* 每条读数带上**出处文件与行号**（`mech.py:267`），不再只报一个数字；
* 加了 `KNOWN_OK` 逐项注释——**一张"还差 N 项"的表如果不写清哪几项不是欠账，
  下一个人会照着它去修不该修的东西**。

修好之后的真实读数：

```
② 方法调 7 项 ⇒ **真正要搬的 5 项**（全在 mech.py）
     sim._build_enemy / _pile_mark_key / _pile_spec / _spawn / _summon_level
   已核过不是欠账的 2 项：
     sim.ping  → client.py 里的 `sim` 是 **Go 进程句柄**（Simgo），假阳性
     sim.run   → verifier.py 的**退回 Python 兜底路径**，有意保留
③ 可达闭包 **223 个函数**（不是 0）
     sim.py 109 / talents.py 43 / unit.py 27 / environment.py 21 / devices.py 8 / p3r.py 6
```

#### 顺带量清楚的另一件事：`OperatorUnit` 是剩下的最大一块

```
unit.py 1600 行
   Combatant      39 行
   OperatorUnit  846 行   ← 规格要它的 **27 个字段 + 4 个 current_* 方法**
   EnemyUnit     618 行   （规格已脱钩，走 enemy_view）
```

`_operator_spec` 读 36 个名字，其中 27 个是 `OperatorUnit`/`Combatant` 的字段、
4 个是 `current_atk` / `current_defense` / `current_res` / `current_range_id`。
⇒ 敌人那一侧的 `enemy_view` 模式，操作员这一侧要照做一遍。

#### 验证

```
① 金标准：✅ 17 份与基线逐项一致（本轮只改工具，未动产品代码）
② 仪器一致性：两个工具现在给出**互相印证**的读数（同一个 `_build_enemy` 都看得见）
```

#### 下一轮

`mech.py` 那 5 处按 `spec.py` 的老办法改：`sim._spawn` → `_view`、
`_pile_spec` / `_pile_mark_key` / `_summon_level` → 直接调 `frontend/enemy_rules.py`
（`sim` 上的方法本来就只是转调）。

### 3.42 摘除 battle/ round 12：★ 真正要搬的 0 项 ＋ 抓回一条**静默消失**的审计登记

#### 一、`mech.py` 那 5 处搬完

| 原来 | 现在 |
|---|---|
| `sim._spawn(id, lv, route, t)` | `spec._view(...)` ＋ `_route_tables(sim.stage)` |
| `sim._build_enemy(key, sim._summon_level(key), ...)` | `spec._view(...)` ＋ `summon_level(sim.stage, key)` |
| `sim._pile_spec(d)` | `pile_spec(sim.stage, d)` |
| `sim._pile_mark_key(乙)` | `pile_mark_key(sim.stage, 乙)` |

`_pile_spec`（36 行）**只用 `self.stage`**，其余全是结构化字段查询 ⇒ 整体搬进
`frontend/enemy_rules.py::pile_spec`，`sim` 上那个方法只剩转调。

⚠ 还剩三个**常量**（`PILE_SUMMON_DELAY` / `PILE_POLLUT_FULL` / `PILE_SELF_BIND`）
住在 `battle/sim.py`。它们是**数值**不是行为，不进任何函数体，但仍是 `battle/`
的一部分——等常量也搬完才能断干净。已在代码里注明。

```
② 方法调 7 项 → **真正要搬的 0 项**
③ 可达闭包 → **0 个函数**
```

#### 二、★ 抓回一条静默消失的审计登记

改完之后跑闸门审计，读到 **6 条**——而 round 9 是 **7 条**。
**少了一条，而"未登记 0、守卫失效 0"两条都是绿的。**

查出来是 `summon_deployments`：round 9 我把闸门的读法从 `sim.summon_deployments`
改成 `sch.summon_deployments`，而审计的接收者模式只有 `sim\.` ——
**它再也看不见那一项了**。

⇒ 那条登记项的消失**不是"盲区治好了"，是"审计看不见了"**。
盲区的定义是"早期有、内容是空、晚点才填"，**与它挂在哪个对象上无关**：
排程那五张表在迁移期由 `verify.py` 同时写进两边，闸门改读 `sch` 之后，
同一个盲区只是换了个宿主。

处置：审计的接收者加上 `sch`（并写明理由）。恢复后：

```
已登记且守卫成立：7 条；未登记：0；守卫失效：0
反向守卫自检：伪造一条晚写+被读的字段 → ✅ 会被报出
```

⚠ 这类"登记项悄悄消失、报告全绿"比"报红"危险得多：
**报红有人看，消失没人看。** 凡是"数量变了"的读数，都得先问"少了的那条去哪了"。

#### 验证

```
① 金标准：✅ 17 份与基线逐项一致
② 自检：813 项，无失败
③ 闸门审计：7 条 / 未登记 0 / 守卫失效 0；反向守卫自检通过
④ 摘除面：真正要搬 0 项、可达闭包 0 个函数
```

### 3.43 摘除 battle/ round 13：干员视图（机械生成）＋ 一条**无法归因**的数量变化

#### 一、`OperatorUnit` 的字段视图

量清了形状：`kw` 只有 **35 键**，`OperatorUnit` 是 **134 字段** dataclass，
`_operator_spec` 读的 31 个名字里 **22 个来自 `kw` / 4 个是方法 / 5 个走默认值**。

⇒ 视图 = `kw` ＋ 全部默认值 ＋ 四个现算的方法。三样**全从 AST 取**，
写成生成器 `tools/gen_operator_view.py`（与 `gen_enemy_view.py` 同一手法）：

| 来源 | 怎么取 |
|---|---|
| 默认值 | `Combatant` / `OperatorUnit` 的 dataclass 右值，原样 `ast.unparse` |
| 方法 | `current_atk` / `current_defense` / `current_res` 的函数体**原文** |
| `effects` | 原版是 **property**，照抄成 property（顺带没有初始化顺序问题） |

产出 `ak_tactic/frontend/operator_view.py`（280 行，143 处赋值）。

#### 二、生成器连撞三个坑——都是"跑一下才知道"

| 症状 | 根因 |
|---|---|
| `def current_atk` 落在**第 0 列** | `ast.get_source_segment` 从 `col_offset` 切，**首行缩进不在段里**，后几行却在 |
| `NameError: field` | dataclass 用 `field(default_factory=list)` 表达"每实例一份空表"，视图里没这个名字 |
| `NameError: POSITION_TOL` | 默认值引用了**模块级常量**，抄默认值必须连常量一起抄 |

⇒ 生成器现在把 `field(...)` 翻成可执行形式、把用到的常量一并带过来，
**认不出的形式直接报错**而不是猜——悄悄塞个默认值进去，症状会是
"某字段开局不是它该有的值"，不报错、只在特定关卡差一点。

#### 三、A/B

`tools/check_operator_view.py`：对每份计划上场过的每个练度，`kw` **同时**喂给
`OperatorUnit(**kw)` 与原版，逐项比 `_operator_spec` 读到的东西。

⚠ **读取面从 AST 现取，不写死**：同一份代码在本会话里量出过 31 与 36 两个数
（正则口径不同），照哪一张写都会漏。

```
读取面：31 个名字、其中 4 个是方法
采到 7 个练度的 `kw`
   `kw` 的键覆盖：**35/35**        ← 覆盖自检：没踩到的键 = 从没被比过的字段
✅ 7 个练度 × 31 项，逐项一致
```

#### 四、★ 一条无法归因的数量变化

自检从 round 12 的 **813 项**变成 **816 项**，而本轮我**没改任何产品代码**。

先排除随机性：连跑两次，条目数 816/816、输出**逐字相同** ⇒ 是确定的，不是抖动。

再查来源时发现：**另一个会话正在并发改这个仓库**——

```
rios-sim/mech/huai_shu_li.go、rios-sim/main.go、rios-sim/mech/mech.go
ak_tactic/activity.py、ak_tactic/simgo/skills.py …
```

而 `check_battle.py` 的条目数依赖**技能库与天赋库的循环**。

⇒ **这 +3 归因不了**：两次运行之间工作树被第三方动过，这不是受控对比。
如实记在这里，**不猜、也不当成"我的改动引起的"**。

⚠ 由此得到一条新纪律：**跨轮次比数量之前，先确认工作树没被别人动过**；
否则"数量变了"既不能用来报警，也不能用来证明没问题。
（可做的改进：让自检把**条目名清单**落盘，这样下次能 diff 出到底多了哪三条。
已记入待办，本轮不动 `check_battle.py`——它正被另一个会话碰。）

#### 验证

```
① 金标准：✅ 17 份与基线逐项一致
② 自检：816 项，无失败（连跑两次逐字相同）
③ 干员视图 A/B：✅ 7 个练度 × 31 项一致，kw 键覆盖 35/35
④ 产品代码：本轮**未改**任何既有文件，只新增 frontend/operator_view.py 与两个工具
```

### 3.44 摘除 battle/ round 14：★ `_operator_spec` 改读视图，**规格哈希逐字不变**

#### 一、做了什么

round 13 造好 `OperatorView` 之后，这一轮把它**接进规格**：

| 处 | 改动 |
|---|---|
| `frontend/schedule.py` | `Deployment` 加 `operator_view` 字段（**并行字段**，不换掉 `operator`）＋ 新函数 `operator_of(d)` |
| `simgo/spec.py`、`simgo/skills.py` | **10 处** `d.operator` → `operator_of(d)` |
| `verify.py` | 抽出 `_unit_key()`，新增 `unit_kw()`；排程时给 `Deployment` 挂上视图 |

**为什么是并行字段而不是直接换掉 `operator`**：迁移期两台引擎同时在跑，
`operator` 必须是活的 `OperatorUnit`（Python 引擎要拿它跑帧），而规格只要开局那组字段。

**为什么要有 `operator_of` 这个单一入口**：`d.operator` 有 10 处读。
留一处不换，那一处就会读活对象——症状是"规格里某一个字段跟别的不一样"，
不报错、只有在那个字段被读到的关卡上才看得出来。

⚠ 机械替换这次用 **AST 定位**（`tools/rename_operator_of.py`），不逐行正则：
`skills.py:266` 的**文档串**里就写着 `d.operator`（那是在解释口径），
逐行替换会把它也改掉。脚本先**列 10 处原文**给人核，再 `--apply`。

#### 二、验证（本轮的硬证据）

`golden_go.py` 的 `spec_sha` 是**整份规格字典的哈希**，干员块就在里面：

```
✅ 全部 17 份与基线逐项一致      ← 含 spec=4ae2140cd53c / 575b375a270c 等，与切换前逐字相同
```

⇒ 规格层从"读活 `OperatorUnit`"换成"读视图"，**输出一个字节都没变**。

其余：

```
干员视图 A/B：7 个练度 × 31 项一致；`kw` 键覆盖 35/35
自检：816 项，无失败（与 round 13 相同）
```

#### 三、项目记忆里查到的事（博士让我看的）

* **另一个会话在做别的工作线**：寒冷数值（`COLD_ASPD_DOWN` / `EnemyUnit.effective_interval`）、
  待裁定清单静默 bug、修饰器四型口径。**他们在改 `battle/unit.py`。**
  → 我的两个生成器（`gen_operator_view.py` / `gen_enemy_view.py`）就是从 `unit.py` 的 AST 取的，
    所以**他们改完要重跑一遍**。本轮实测两个都**幂等**、且 `effective_interval` 在 `EnemyUnit` 上
    不影响 `operator_view`（它只读 `Combatant`/`OperatorUnit` 的字段）。
* **⚠ 一条待定的事**：记忆里写着提交 `97e8029` **意外带入了另一会话在途的 `sim.py` 重构**
  （266 行里约 260 行是他们的）。这正是"提交统一由 RIOS后端 执行"这条纪律的代价面——
  **我方迁移期大量改 `sim.py`，与他们的在途改动会互相卷入**。这条仍标着"待定"。
* 另一条与 round 13 对得上：自检条目数连续两轮都是 **816**（其间我改过产品代码），
  ⇒ 这个数对**我的**改动是稳定的；round12→13 的 +3 更可能来自当时另一会话的改动，
  但**我仍无法证明**（没留下列表）。如实记着。

#### 下一轮

`build_spec` 现在仍收 `sim`。下一块是把它换成 `SpecInputs`（stage ＋ env ＋ schedule ＋
enemy_at ＋ species_provider ＋ range_provider ＋ spawns），那之后 `sim` 只剩"排程载体"一个身份。

### 3.45 摘除 battle/ round 15：★ 补上**导入面**这张表——剩下要搬的比想象的大

#### 一、发现：`spec_deps` 结构上看不到一半的依赖

`spec_deps.py` 量的是"`build_spec` 调了 `battle/` 的哪些**方法**"，那一路已归零。
但它量不到另一种关系：

```python
from ..battle import environment as env          # mech.py:36
from ..battle.devices import BLOCKER_KEY …        # mech.py:37
from ..battle import sim as _sim_mod             # mech.py:270（三个常量）
from ..battle import talents as _talents         # spec.py 五处
```

这些**一个方法都不调**，可 `battle/` 一删就全断。

⇒ 新增 `tools/spec_imports.py`。**摘除面必须两张表一起看：调用面 ＋ 导入面。**

#### 二、导入面实测（这才是"还要搬什么"）

| 目标模块 | 行数 | 情况 |
|---|---|---|
| `battle/environment.py` | 738 | `mech.py` 用 15 次（`FarmlandSystem`） |
| `battle/talents.py` | 1126 | `spec.py` 用 38 次（`find_*` ＋ 常量） |
| `battle/devices.py` | 413 | 只要 **3 个常量**（`BLOCKER_KEY`/`PILE_KEY`/`PUMP_KEY`） |
| `battle/sim.py` | — | 只要 **3 个常量**（`PILE_SUMMON_DELAY` 等） |

⚠ 这比"把 `build_spec` 的 `sim` 换成 `SpecInputs`"要大得多：
`farmland_spec()` 深读 `sim.farmland`（`params`/`fields`）与 `sim._devices` 的每个装置，
那两个对象分别住在 `environment.py` 与 `devices.py`。
**先把这张表列出来，比闷头改 `build_spec` 诚实。**

#### 三、这一轮把 `talents` 里规格要的那一片搬出来了

实测 `spec.py` 用到的闭包：**13 个函数、46 行，全部无 `self`、无引擎态**
（`battle/talents.py` 共 1126 行）。⇒ 值得整体搬。

`tools/gen_talent_finders.py` **按行区间原样切**（连同紧邻的前导注释块）生成
`ak_tactic/frontend/talent_finders.py`（218 行）。

⚠ 为什么不重打：`talents.py` 的注释里记着**为什么这样认**——
例如「青色怒火」为什么只能按**天赋名**认、不能按黑板键名认（它和技能自己的
增益**完全同名**）。重打代码容易，重打论证不容易，而这段文字是判据的一半。

#### 四、三个"仪器自己的假信号"（全是我这轮造的工具）

| 症状 | 根因 |
|---|---|
| 报出一个**不存在的死导入** | `from ..battle import environment as env` 用的是**别名**，我按原名数 → 0 次 |
| `SyntaxError: invalid syntax` | `print("…"要搬什么"…")` 里嵌了半角引号 |
| **印着"行为层无一例外"，而它刚抛过异常** | 异常被 `except` 接住后，汇总句写死了 |

第三条最该记：**仪器没跑起来 ≠ 仪器说没问题**。已改成如实印"**没跑起来**"。

#### 五、A/B（两层）

`tools/check_talent_finders.py`：

```
源码层：常量 11 项 + 函数 13 项，**逐字一致**（AST unparse 后的正文比较）
行为层：8 条真天赋记录，无一例外
```

⚠ 只做行为层不够：六个 `find_*` 形状**完全一样**（遍历、判据、返回），
随便填一个判据进去都可能在这批样本上给出同样结果 ⇒ 源码层是主判据。
⚠ 测试台自己也有个 bug：`FUNCS` 里既有 `is_*`（收**单个**天赋）又有 `find_*`
（收**一列**），我一度一律传列表，炸在 `is_regen_talent` 的 `t.has(...)` 上
——**看起来像代码坏了**。

#### 验证

```
① 金标准：✅ 17 份与基线逐项一致
② 产品代码：本轮**未改**任何既有文件；`frontend/talent_finders.py` 是新增且**尚未接线**
   （与 `enemy_view` 当初一样：先搬出来、证明逐字一致，再接）
```

#### 下一轮

① 把 `talents.py` 的那 13 个函数改成从新家 re-export（注意模块级常量的**定义顺序**）；
② `spec.py` 改从 `frontend.talent_finders` 取；
③ 然后再动 `SpecInputs`——那时导入面只剩 `environment` / `devices` / `sim` 三家。

### 3.46 摘除 battle/ round 16：天赋查找器搬进 frontend/（提交 6782be3）

#### 一、做了什么

`build_spec` 需要"这位干员身上有没有这条天赋"。实测那一片闭包是
**14 个常量 + 21 个函数、全部无 `self`、无引擎态**，而 `battle/talents.py` 有 1126 行。
⇒ 整体搬进 `ak_tactic/frontend/talent_finders.py`，`talents.py` 改成 re-export（同一对象）。

| 处 | 改动 |
|---|---|
| `frontend/talent_finders.py` | **新增**，289 行，按 AST 行区间从原件原样切（连同前导注释） |
| `battle/talents.py` | 删掉那 35 个定义，插入转出导入 |
| `simgo/spec.py` | 5 处 `from ..battle import talents` → `from ..frontend import talent_finders` |
| `simgo/spec.py::_talent_dodge` | 去掉静默兜底（见下） |

⚠ **为什么不重打**：注释里记的是**为什么这样认**——「青色怒火」只能按天赋名认、
不能按黑板键名认（它和技能自己的增益在**同名黑板**上完全无法区分）。
重打代码容易，重打论证不容易。

#### 二、本轮抓到的两个真缺陷

**1. `_talent_dodge` 的静默兜底把 bug 藏起来了**

原写法是一串 `try/except` + `getattr(_talents, "find_damage_block", None)`，取不到就
`return 0.0, 0.0`。后果不是报错，而是**"这名干员恰好没有天赋闪避"**：

```
spec.py:793   if talent_phys or talent_arts:        ← 不成立
spec.py:794       out["talent_dodge_phys"] = ...    ← 两个键静默消失
```

`plan-hs06` 的判决**一模一样**，只有 `spec_sha` 变了。
**17 份金标准里它单独变红**，是唯一抓住这件事的判据。已改成直取、取不到就炸。

**2. 生成器的根名字扫描漏了 `getattr` 形态**

第一版只认 `_t.find_x`（属性访问），认不出 `getattr(_t, "find_x", None)`（字符串）。
`find_damage_block` 因此没被搬走 —— 而正是上面那条兜底把它藏住的。
两种形态现在都认。清单也不再手写：**从 `spec.py` 的实际用法反推 + 传递闭包**。

#### 三、验证

```
① 金标准：✅ 17 份与基线逐项一致，spec_sha 逐字相同（4ae2140cd53c / 575b375a270c …）
② 逐字 A/B：✅ 常量 14 + 函数 21 源码逐字一致；行为层 8 条真天赋无例外
③ 摘除面：方法调用真正要搬的 **0 项**、可达闭包 0 个函数
④ 导入面：battle/ 导入 10 处 → **5 处**
⑤ 全仓自检：通过 **816 项**，无失败
⑥ 闸门审计：已登记 7 / 未登记 0 / 守卫失效 0
```

⚠ **A/B 的基线必须取 `git HEAD` 那一版**，不能取工作树里的 `talents.py`：
搬完之后那里已经没有定义了，拿它比会报 35 项"原件里找不到"——
**看起来像搬坏了，其实只是基线选错了地方**。

#### 四、剩下的导入面（5 处）

| 目标 | 情况 |
|---|---|
| `battle/environment.py` | `mech.py` 用 15 次（`FarmlandSystem`，`farmland_spec` 深读 `params`/`fields`） |
| `battle/devices.py` | 只要 3 个常量 |
| `battle/sim.py` | 只要 3 个常量（`PILE_SUMMON_DELAY` 等） |

下一阶段：这 6 个常量先搬；之后再动 `environment`，最后才是 `build_spec` 收 `SpecInputs`。

### 3.47 摘除 battle/ round 17：6 个机制常量搬进 frontend/，**导入面 5 处 → 1 处**（提交 5e73e31）

#### 一、做了什么

| 处 | 改动 |
|---|---|
| `frontend/mech_consts.py` | **新增**：3 个装置键 + 3 条天桩时间常数 |
| `battle/devices.py` | 三个装置键改为转出（同一对象） |
| `battle/sim.py` | 三条时间常数改为转出（同一对象） |
| `simgo/mech.py` | 改从新家取，并去掉 `getattr` 兜底 |

**为什么单独一份**：`spec.py`/`mech.py` 送规格需要这几个值，
而它们原本住在 `battle/devices.py`（413 行）与 `battle/sim.py`（5069 行）里——
**为了三个字符串去 import 一个 413 行的模块**，就是把 `battle/` 钉在依赖图上。

⚠ 搬常量前**逐条读了原文的实际内容**（项目铁律 `ba47512d`）：
`unit.py` 与 `devices.py` 各有一张**同名不同义**的 `DIRECTIONS`，
合并会让 `dict.get` 静默落默认值、把方向弄反。这六条读过，没有重名冲突。

#### 二、本轮抓到的真缺陷：**默认值恰好等于真值的 `getattr` 兜底**

`mech.py` 里读这三条常数用的是：

```python
getattr(_sim_mod, "PILE_SUMMON_DELAY", 1.25)
```

那个默认值 **1.25 恰好就是真值**。⇒「取不到」**永远看不出来**：
把那行 import 整个删掉，行为一模一样，**任何判据都不会响**。

这与 round 16 的 `_talent_dodge` 是同一类，但更隐蔽：

| | 表现 |
|---|---|
| round 16 `_talent_dodge` | 默认值 `(0.0, 0.0)` **错得看不出来**（表现为"这名干员没有闪避"） |
| round 17 `getattr(..., 1.25)` | 默认值 `1.25` **对得看不出来**（多一个字符都不会变） |

后者更值得记：**它的失败模式是"什么都没发生"**。
已全部改成直取、取不到就炸。

#### 三、验证

```
① 导入面：battle/ 导入 10 处 → 5 处 → **1 处**
② 常量同一对象：devices 转出 3/3 True、sim 转出 3/3 True
③ 残留 _sim_mod：代码 0 处（只剩注释里两行说明）
④ 金标准：✅ 17 份与基线逐项一致，spec_sha 逐字不变
⑤ 全仓自检：通过 816 项，无失败
⑥ 摘除面：可达闭包 0 个函数；闸门审计：没有未登记的盲区
```

#### 四、最后一里：`battle/environment.py`

已量清路径：

* `mech.py` 从 `env` 用 **14 个名字**：10 个常数
  （`CACHE_*` / `ACTUAL_*` / `POLLUT_*` / `PUMP_*`）+ 4 个类函数
  （`FarmlandSystem` / `Field` / `PolluteParams` / `farmland_groups`）。
* **依赖方向干净**：`environment.py` 只依赖 `battle/devices.py`，
  而 `devices.py` **只依赖 `frontend/mech_consts`**（没有任何 `battle/` 内部依赖）。
  ⇒ 两个可以整体搬，原件留转出壳。

⚠ **一条必须先摆平的约束**：`activity.py`（**不是本会话的文件**）里有三个锚点：

```
anchor="ak_tactic.battle.environment:RUNES_KEY"
anchor="ak_tactic.battle.devices:BLOCKER_KEY"
anchor="ak_tactic.battle.devices:PUMP_KEY"
activity.py:376  from .battle.devices import parse_devices
```

留转出壳能让这些锚点与导入**继续解析**，但这件事必须显式验证，
不能靠"反正转出了"推断——`activity.py` 属于别人，我不改它。

#### 下一轮

搬 `devices` + `environment`（一起，一步）→ 导入面归零 → 然后才是
`build_spec` 收 `SpecInputs`。

### 3.48 摘除 battle/ round 18：devices + environment 搬进 frontend/，★ **导入面归零**（提交 80e3f84）

#### 一、结果

```
simgo/ 对 battle/ 的模块级导入：10 处 → 5 处 → 1 处 → 0 处
```

⚠ 归零的是**导入面**（"battle/ 被删之后 simgo/ 会不会断"），
**不是整个摘除目标**。还剩：`build_spec` 收 `SpecInputs`、`check_battle.py` 与
15 个探针的处置、以及最后删 `battle/` 本身。

#### 二、做法

`battle/devices.py`（414 行）与 `battle/environment.py`（738 行）**一起搬**，
因为 `environment.py` 依赖 `devices.py`，而 `devices.py` 只依赖
`frontend/mech_consts`（方向干净、无 `battle/` 内部依赖）。
原件留**转出壳**。

#### 三、壳为什么要 `__getattr__`

壳里是 `from ..frontend.X import *` + PEP 562 的模块级 `__getattr__`。

`import *` **只转 `__all__` 里的名字**，而 `environment.pump_once`
就**不在** `__all__` 里、却真的被 `sim.py` 点着：

```
实测：外部从 battle.environment 取用的 7 个名字里
      **1 个（pump_once）落在 __all__ 之外**
```

⇒ 少了这层 `__getattr__`，这一处会在**跑到那一行时**才 `ImportError`
——就是"改名时漏了一个"那类错。它**不是**本项目禁止的"带默认值的兜底"：
取不到照样 `AttributeError`，只是把查找转发到新家。

#### 四、新增判据：消费者体检（`tools/check_battle_shims.py`）

搬模块之后，"新家对不对"有金标准盯；但"**旧地址还有没有人用、用了还解析得到吗**"
原本**没有判据**。这个工具补上：

```
扫到 56 个从 battle/ 转出壳取名字的点（含 activity.py 的字符串锚点）
  battle.devices      被取用 14 个名字，逐条同一对象
  battle.environment  被取用  7 个名字，逐条同一对象（含 __all__ 之外的 pump_once）
✅ 全部转出壳：56 个取用点、2 个子模块，逐条同一对象
```

⚠ 工具自己会报**覆盖率**（"扫到 56 个点"），扫到 0 个就说"判据跑空了、不能当成通过"。

#### 五、`activity.py` 的锚点：实测而非推断

`activity.py`（**不是本会话的文件，我不改**）里有三个字符串锚点。
壳让它们继续解析——这一条**实测过**：

```
ak_tactic.battle.devices:BLOCKER_KEY    -> 'trap_139_dhtl'
ak_tactic.battle.devices:PUMP_KEY       -> 'trap_140_dhsb'
ak_tactic.battle.environment:RUNES_KEY  -> 'env_system_new'
```

⚠ 只验了"**解析得到**"，没验"用它跑起来还对"——那需要 activity 模块自己的判据。

#### 六、验证

```
① 导入面：**0 处**
② 消费者体检：56 个取用点逐条同一对象
③ 金标准：✅ 17 份与基线逐项一致，spec_sha 逐字不变
④ 全仓自检：通过 816 项，无失败
⑤ 摘除面可达闭包 0 个函数；闸门审计无未登记盲区；go build ./... 通过
```

#### 下一轮

导入面既已归零，下一块就是**规格层自己**：`build_spec` 收 `SpecInputs`
（round 13 量过：11 处属性读，其中 `sim.stage` 4 处、`range_provider` 2 处，
其余 `_devices`/`deployments`/`enemy_at`/`species_provider`/`snow_fields`/`max_time`）。
