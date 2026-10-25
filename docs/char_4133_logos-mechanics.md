# 逻各斯（char_4133_logos）战斗机制全生命周期闭环口径

> 本文档依据 `docs/operator-mechanics-workflow.md` 撰写，记录逻各斯在 `rios-sim` 中的机制建模、数据来源、黑板键消费与全生命周期实现状态。
> 数值全部来自 gamedata 源表原文（`character_table.json` / `skill_table.json` / `battle_equip_table.json` / `range_table.json`），规格层只存原文、配置层解析，**没有任何一个写死的数值**。

---

## 〇、基础规格

- **代号**：逻各斯 / logos
- **干员标识**：`char_4133_logos`
- **职业分支**：术师 - 中坚术师（corecaster）
- **稀有度**：六星
- **技能槽**：`skchr_logos_1` / `skchr_logos_2` / `skchr_logos_3`
- **天赋解锁**：第一天赋「语汇演化」在 `PHASE_1`（精英 1）解锁；第二天赋「剜魂具辞」在 `PHASE_2`（精英 2）解锁。**精英 0 没有天赋**。
- **潜能编号口径**：游戏内 1–6（潜能 1 为基础档）。

### 一条必须先说的结论：**本干员在 V-2 裁定之前不可能产出战斗判决**

第一天赋「语汇演化」是概率机制，按博士 2026-10-24 裁定**必须**作为具名 Gap 上报
（不得折算成期望值）。本仓的规格闸门是「`specMechanismGaps(spec)` 非空即整场拒跑」
（`sim.go:731`，`mechanisms.IncompleteError`），因此逻各斯在 V-2 裁定之前**任何一局都会拒判**，
拒判理由里带着 `logos.talent1.prob_v2`。

这不是接线没通：`logos_full_lifecycle_test.go` 的 `TestLogosRefusedUntilV2Ruling`
就是拿**这条语义**做判据——它断言拒判发生、且理由具名到 V-2。
真要跑起来只有两条路：① 博士裁定 V-2；② 明确授权把该天赋折成某个口径（本档**不**做）。

---

## 一、第一天赋「语汇演化」——**未建模（等 V-2 裁定）**

原文（E2 潜能 1）：「对一个目标发起攻击时，有 40% 几率额外对攻击范围内一个随机目标造成相当于攻击力 60% 的法术伤害并使其停顿 0.8 秒」。

### 1. 数值档位（来自 `character_table.json` 的 talents 原文）

| 精英 | 潜能 | prob | atk_scale | sluggish |
|---|---|---|---|---|
| E1 | 1–4 | 0.4 | 0.40 | 0 |
| E1 | 5–6 | 0.4 | 0.45 | 0 |
| E2 | 1–4 | 0.4 | 0.60 | 0.8 |
| E2 | 5–6 | 0.4 | 0.65 | 0.8 |

### 2. 为什么整条链都不建模

它不是"少了个消费者"，而是**语义未定**：40% 的触发在精确事件下应当如何表达
（逐次随机 / 最坏情况 / 枚举），正是 `docs/roadmap.md` 第六节 **V-2** 的待裁定项。
在裁定之前：

- **不许折期望值**（`1 + p·(M−1)` 那种写法）——那会让同一条时间线两次跑出两个数，
  而判决比对靠的就是可重复；
- 不许"只在有额外目标时结算"（那是另一种近似：把概率当成 1）；
- 实现上留 `LogosRuntimeConfig.Talent1*` 字段（证据齐、键齐、值齐），但
  **没有任何运行期读取者**，并由 `logosRemainingGapsFromSpec` 具名上报
  `logos.talent1.prob_v2`（理由里写明"在等 V-2 裁定"）。

模组进一步改写这条天赋（见第四节），改写后的 `element_atk_scale` / `emit_count`
同样跟着整条链一起待裁定——所以缺口报的是**整条链**，不是单个键。

---

## 二、第二天赋「剜魂具辞」（精英 2）——已建模

原文：「攻击使目标在 **5 秒**内法术抗性 **−10** 且受到的法术伤害提高 **150** 点」。

| 潜能 | duration | magic_resistance | atk_addition |
|---|---|---|---|
| 1–2 | 5 | −10 | 150 |
| 3–6（潜 2 起） | 5 | −10 | 165 |

### 实现

- **施加点**：`sim.go` 我方出手路径里 `target.take()` 之后（`dealt > 0` 才施加——
  0 伤害是"没打中"，免疫/无敌窗口不该吃到减益）。
- **法抗削减**：挂在 `enemy.res()` 这个**唯一入口**上。任何来源的法术伤害都吃到它，
  不会出现"普攻吃到了、技能伤害没吃到"的分裂。
- **法伤平坦加值**：加在 `resolveDamage()` **之后**（正文说的是"受到的法术伤害"，
  不是"法术攻击力"）。加在结算之前会顺带被法抗削一遍，症状是"对高法抗目标几乎不生效"。
- **续期取 max**：剩余秒数取更晚的时刻，与全仓时限状态的写法一致。
- **到期三项一起失效**：法抗、平坦加值同源同刻，不许只掉一半。

---

## 三、技能

### 1. 一技能「殁亡」（`skchr_logos_1`）

- 类型：`INCREASE_WITH_TIME`；Lv10：`spCost=60`、`initSp=0`、`duration=-1`（持续时间无限）。
- 范围：`3-3`（技能期间攻击范围扩大）。
- 黑板（Lv10）：`atk=1.0`、`attack@kill_atk_scale=1.5`、`attack@kill_damage=9999999`。
- 效果：攻击范围扩大、攻击力 +100%；使攻击范围内生命值低于「逻各斯攻击力 × 150%」的
  敌人**立刻倒下**，并对**另一个随机目标**造成与倒下单位生命值相等的法术伤害。
- 实现：
  - 攻击力 +100% 由引擎既有黑板键表消费（`atk` → `ATKPct` → `Profile.ATK`）。
  - 「立刻倒下」用 `attack@kill_damage` 走同一条 `take()` 入口——这样"击杀归谁"
    与"累计伤害"两个读数与普攻同源，不留第二套账。
  - 斩杀阈值取**当前**攻击力（技能期间已被 `atk` 抬到 2 倍），所以阈值随技能开关变。
  - 「另一个随机目标」在 Go 里落成**按敌人列表次序的第一个合格目标**（确定性、可复核）；
    该口径登记在 `Unresolved`。
  - 转移伤害先当作**法术伤害原值**，再走标准法术结算（法抗会削它）。

### 2. 二技能「提喻」（`skchr_logos_2`）

- 类型：`INCREASE_WITH_TIME`；Lv10：`spCost=30`、`initSp=20`、`duration=20`。
- 范围：无改写（`rangeId=null`）。
- 黑板（Lv10）：`magic_resistance=70`、`attack@cooldown=0.5`、
  `attack@atk_scale_base=0.75`、`attack@atk_scale_delta=0.15`、
  `attack@move_speed=-0.06`、`attack@max_stack_cnt=10`。
- 效果：法术抗性 +70；攻击**改为**锁定一个目标，每 0.5 秒造成一次
  「攻击力 × 倍率」的法术伤害，对相同目标伤害逐渐提高至 **3 倍**、移速逐渐降低至 **40%**
  （锁定 5 秒后达到上限）；被打断或目标倒下时重新索敌且效果重置。
- 实现：
  - **平A 停摆**：`operatorsAttackMode` 开头对「技能二 + 逻各斯」整段跳过（含出手计时器）。
    伤害那一支在 `logosTick` 里独立结算。
  - **法术抗性 +70**：`magic_resistance` 没有走 `applyMods`（那一族只折
    atk/def/max_hp/攻速），因此在 `operator.res()` 里按"技能期间加平坦值"接上。
  - **倍率爬坡**：`base + delta × 层数`。数据自洽的判据是「满层 = 3 × base」：
    `0.75 + 0.15 × 10 = 2.25 = 3 × 0.75`；移速 `1 + (−0.06) × 10 = 0.4`。
    两者同时成立，正对应正文的"3 倍 / 40% / 锁定 5 秒后达到上限"（10 层 × 0.5 秒 = 5 秒）。
  - **层数时序**：每拍**先加一层再结算**，所以第 10 拍（5.0 秒）就是满层。反过来
    （先结算后加层）会把满层推后一拍——该口径登记在 `Unresolved`。
  - **移速**：走 `enemy.logosMoveDown`，在 `advance` 的速度式末尾乘一个乘区；
    没叠过层时**恰好返回 1.0**（乘 1.0 在 IEEE754 下精确），所以没被她盯上的敌人
    这次接线前后逐位相同。不复用 `sluggishTimer`：那是全局常数 80% 的二值停顿，
    这一条是按层爬坡的。

### 3. 三技能「延异视阈」（`skchr_logos_3`）

- 类型：`INCREASE_WITH_TIME`；Lv10：`spCost=45`、`initSp=30`、`duration=30`。
- 范围：`3-4`（技能期间攻击范围扩大）。
- 黑板（Lv10）：`atk=3.0`、`attack@max_target=4`、`projectile_move_scale=0.05`。
- 实现：
  - 攻击力 +300% 由黑板键 `atk` 消费（引擎既有键表）。
  - **同时攻击 4 个目标**：在 `operator.maxTarget()` 里按技能状态返回 `attack@max_target`。
    ⚠ 它**不能**写进 `OperatorSpec`（部署前的静态快照）——那样没开技能时也一次打四个，
    症状是"整关伤害凭空变高"，而不是少打。
  - **攻击范围扩大**：技能 `rangeId` 在建规格时按部署朝向折成绝对格
    （`LogosSourceSpec.SkillRangeAbsCells`），运行期 `targetRange()` 按技能开关切换。
    运行期再算一遍就是第二套旋转/平移口径。
  - **敌方子弹减速与清空（未建模）**：本仓没有敌方弹道实体，`projectile_move_scale`
    没有落点。它是具名缺口 `logos.skill3.projectile`，不是"忘了写"。

---

## 四、模组

| 模组 | 标识 | 改写内容 |
|---|---|---|
| 来自河谷的笔盒 | `uniequip_002_logos` | 特性：造成法术伤害时附带 8% 凋亡损伤；天赋一 Lv2 起 `prob=0.5/0.6`、`element_atk_scale=0.4/0.6` |
| 《语义范式百科》 | `uniequip_003_logos` | 特性：普攻命中精英/领袖回 1 点技力；天赋一改为「额外对**两个**目标」（`emit_count=2`）、`atk_scale` 0.63–0.70 |

**两个模组的隐藏天赋都没有运行期消费者**，各有一条具名缺口：

- `logos.module.trait_ep_damage`（`ep_damage_ratio`）：元素损伤状态机（`element.go`）
  已存在但**尚无战斗调用点**，本档不冒充已消费。
- `logos.module.trait_sp`（`sp`）：敌人规格里**没有精英/领袖分类字段**，找不到判据。

---

## 五、黑板键消费台账

| 来源 | 键 | 消费者 |
|---|---|---|
| 天赋一 | `prob` / `atk_scale` / `sluggish` | **无**（V-2 待裁定，具名缺口 `logos.talent1.prob_v2`） |
| 天赋二 | `duration` / `magic_resistance` / `atk_addition` | `enemy.res()` 与伤害结算后的平坦加值（`logosTalent2OnHit`） |
| 模组X 隐藏天赋 | `ep_damage_ratio` | **无**（具名缺口 `logos.module.trait_ep_damage`） |
| 模组Y 隐藏天赋 | `sp` | **无**（具名缺口 `logos.module.trait_sp`） |
| 模组X 天赋改写 | `prob` / `atk_scale` / `sluggy` / `element_atk_scale` / `emit_count` | 同上（整条链随天赋一一起待裁定） |
| 技能一 | `atk` | 引擎键表（攻击力） |
| 技能一 | `attack@kill_atk_scale` / `attack@kill_damage` | 斩杀阈值 / 立刻倒下 |
| 技能二 | `magic_resistance` | `operator.res()` 技能期间加法抗 |
| 技能二 | `attack@cooldown` / `attack@atk_scale_base` / `attack@atk_scale_delta` / `attack@max_stack_cnt` | 锁定多段伤害与爬坡 |
| 技能二 | `attack@move_speed` | 锁定目标的移速乘区 |
| 技能三 | `atk` | 引擎键表（攻击力） |
| 技能三 | `attack@max_target` | `operator.maxTarget()` |
| 技能三 | `projectile_move_scale` | **无**（具名缺口 `logos.skill3.projectile`） |

配置层（`decodeLogosRuntimeConfig`）会把黑板上出现却没被任何消费者认领的键记进
`UnusedKeys`，`specMechanismGaps` 逐条具名上报，不静默忽略。
本档在满练（E2 潜能 1 模组满级）下 `UnusedKeys` 应为空——所有键要么有消费者，
要么在第四节那三条具名缺口里。

**两层各报一次的现象**：通用天赋分类器对 `prob<1` 的载荷会报
`talent.probability_event`（"概率事件当前仅有期望值消费者"），本档操作员闭环再报一条
`logos.talent1.prob_v2`（写明在等 V-2）。两条说的是同一件事、两个作用域
（通用分类器认不出 V-2），所以拒判理由里会同时看到两条占位。

---

## 六、运行期接线点

| 位置 | 作用 |
|---|---|
| `sim.go` 部署分支 | 解码运行期配置、建立 `LogosBattleState` |
| `sim.go` 主循环（帧序 5，我方出手之前） | `logosTick`：技能一斩杀、技能二锁定拍 |
| `sim.go` 我方出手路径 | 天赋二施加；技能三多目标痕迹 |
| `sim.go` 我方出手开头 | 技能二期间**整段跳过**（平A 停摆） |
| `sim.go` `enemy.res()` | 天赋二的法抗削减 |
| `sim.go` `advance` 速度式 | 技能二的移速乘区 |
| `skill.go` `res()` | 技能二的法术抗性 +70 |
| `skill.go` `maxTarget()` | 技能三的同时攻击目标数 |
| `skill_range.go` `targetRange()` | 技能一/三的攻击范围扩大 |
| `operators.go` / `wire.go` | `LogosSource` 字段与技能范围绝对格 |
| `mechanism_gaps.go` | 逻各斯分支：具名缺口逐条上报 |

---

## 七、测试与验收

- `logos_spec_test.go`：精英×潜能×技能槽×技能等级矩阵、天赋与技能数值逐档比对、
  模组三级覆盖、非法训练档边界。
- `logos_mechanics_test.go`：天赋二的法抗/平坦加值与到期、技能一阈值与转移伤害
  （含法抗削减）、技能二爬坡与满层自洽性、目标倒下重置、技能三目标数、
  技能范围扩大、缺口逐条具名。
- `logos_full_lifecycle_test.go`：
  - `TestLogosRefusedUntilV2Ruling`：真调 `runSimContext`，断言**拒判**且理由具名到 V-2；
  - 三个 `TestLogosFrameWiringSkillN`：绕过规格闸门，直接驱动主循环**调用的那几个函数**
    （`logosTick` / `operatorsAttackMode`），证明三档机制在帧序上真被行使
    （多目标痕迹、天赋二施加、斩杀、锁定拍数与满层）。
- 全包回归：`go test ./...`（rios-sim 全部包）。

---

## 八、待证与口径裁定栏

以下项**已建模但语义待证**，登记在此而不是报成机制缺口（报成 Gap 会让整场拒判）：

1. **天赋二的时点**：本次这一击的伤害先结算、减益作用于之后的伤害。数据里没有第二个键
   能判"同一击是否享受到自己的减益"。
2. **技能一的「另一个随机目标」**：数据里没有种子也没有权重，本实现取敌人列表次序的
   第一个合格目标。换成别的确定性次序会改判决。
3. **技能一转移伤害的口径**：与倒下单位生命值相等的数值先当作法术伤害原值，
   再走标准法术结算（法抗会削它）。
4. **技能二的层数时序**：每拍先加一层再结算，因此第 10 拍（5.0 秒）满层；
   「先结算后加层」会把满层推后一拍。
5. **技能二的锁定重选**：目标倒下/离开范围才重选；技能期间目标一直在范围内就一路锁死。

另：本档的 PRTS 整页取证尚未执行，数值与描述均取自 gamedata 原文。

---

## 九、中间文件清理

本档的全部取数都在仓外 shell 里用一次性脚本读 gamedata 原文完成（未落地任何中间文件）；
未产生需要清理的下载响应、解码 HTML 或临时探针。正式源码、测试与本文档保留。
