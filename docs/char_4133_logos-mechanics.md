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

### 一条必须先说的结论：概率事件走**规格 seed 的精确抽样**（V-2 已裁定）

博士 2026-10-25 裁定 V-2「概率机制的结果语义」，原话：

> **「只要是能精准判定的都精准判定，很难做精准的才用期望值。」**

这条裁定覆盖了 2026-10-24 那条"概率机制一律不折期望值、作为具名 Gap 拒判"的指示。
落地口径（操作化，逐条对应）：

1. **默认走精准判定**：概率事件按「规格内固定 seed 的确定性伪随机逐次抽取」实现。
   种子住在规格层（`LogosSourceSpec.RNGSeed`，见 `logos_spec.go`），**运行期不生成任何随机性**——
   不读时间、不读地址、不调全局随机源。同一 (计划, seed) 必得同一条时间线。
2. **判决语义标注**：这样算出来的是「**该 seed 下的一次采样**」，**不是**胜率、不是期望值。
   判决事件流里有一条 `logos_rng_seed`（`who` 里带 `seed=<n>`），读判决的人据此知道
   这条时间线是哪一次采样。
3. **期望值只作例外**，且必须逐条给「精准不可行」的证据。本条天赋**不需要**这个例外：
   触发、目标选择、伤害、停顿全部可精确判定。
4. **折期望只许作用在加性标量上**，且一旦折后的值参与阈值/分支判断必须单独标出。
   本条天赋没有走这条路径（见第八节末「本仓里仍用期望值的地方」）。

因此逻各斯现在**能产出战斗判决**；剩下的拒判只来自与概率无关的具名缺口
（技能三的敌方子弹、模组X 的元素条件分支/凋亡损伤、模组Y 的回技力），见第五节。

---

## 一、第一天赋「语汇演化」——已建模（seed 精确抽样）

原文（E2 潜能 1）：「对一个目标发起攻击时，有 40% 几率额外对攻击范围内一个随机目标造成相当于攻击力 60% 的法术伤害并使其停顿 0.8 秒」。

### 1. 数值档位（来自 `character_table.json` 的 talents 原文）

| 精英 | 潜能 | prob | atk_scale | sluggish |
|---|---|---|---|---|
| E1 | 1–4 | 0.4 | 0.40 | 0 |
| E1 | 5–6 | 0.4 | 0.45 | 0 |
| E2 | 1–4 | 0.4 | 0.60 | 0.8 |
| E2 | 5–6 | 0.4 | 0.65 | 0.8 |

### 2. 实现（`logos_runtime.go::logosTalent1OnAttack`）

每一步都是**离散事件**，没有一处折期望：

- **触发**：`chance(prob)` 抽一次签。命中就走完整分支，没命中就当这一击没有额外事件
  ——不是"打折伤害"，而是**有时候根本没有这一笔**。
- **候选池**：攻击范围内、活着、还在场上的敌人（**包含本击的主目标**，见第八节待证栏）。
- **目标**：`pick(n)` 无放回地挑 `emit_count` 个（默认 1；模组Y 改写为 2），
  因此"两个随机目标"保证是**两个不同**的目标；候选不足时按现有的挑。
- **命中结果两半都真行使**：
  - 额外**法术伤害** = 当前攻击力 × `atk_scale`，走标准法术结算（目标法抗会削它），
    再叠加天赋二的"受到法术伤害 +N"平坦值；
  - **停顿** `sluggish` 秒：写进敌人的 `sluggishTimer`，与全局「停顿＝减速 80%」
    口径共用同一状态（`sluggishFactor()`），所以它**真的会减速**，
    而不是只记一个数。
- **计数留痕**：`T1Rolls`（抽签次数＝出手次数）与 `T1Procs`（命中次数）分开记。
  只报命中数看不出概率闸有没有在跑；`prob=0` 时"抽签 50 次、命中 0 次"才是合格读数。

### 3. 抽样器（`logos_rng.go`）

自带的 splitmix64，**不依赖 `math/rand`**：全局随机源在 Go 1.20 之后被运行时随机播种，
`rand.NewSource` 又属包内实现细节，升级 Go 时序列可能变——那会让历史读数无法复现，
而症状是"同一份规格两次跑出两个判决"。splitmix64 只有三行、常量固定、与语言版本无关。

两个边界**不取数**：`chance(0)` 恒假、`chance(1)` 恒真，都不消耗随机数——
否则"没有概率"与"有概率但恰好命中"会在序列上分叉。

### 4. 种子落点

- 种子住在 **`LogosSourceSpec.RNGSeed`**（`json:"rng_seed"`），建规格时显式写入
  默认值 `logosDefaultRNGSeed`（写死的 1）。规格没写（0）时按该默认值走——**不是**隐式随机。
- 所以「同一份 spec 反序列化后得到同一序列」是可证的：`TestLogosSeedSurvivesSerialization`
  把规格 marshal→unmarshal 之后逐次比对判定序列。
- 搜索侧所有计划共用同一个 seed，判决因此可比（裁定第 1 条）。

### 5. 通用分类器的豁免

通用天赋分类器对任何 `0 < prob < 1` 的载荷都会报 `talent.probability_event`
（"概率事件当前仅有期望值消费者"）——V-2 之后这句话对逻各斯不成立。
`mechanism_gaps.go::logosExactProbTalent` 按 **charID + 键集**精确开豁免
（键集必须 ⊆ {prob, atk_scale, sluggish, emit_count, element_atk_scale}，
且 prob∈(0,1)、atk_scale>0、sluggish>0）；同时把 `sluggish` 认领为该链的消费者，
不再落到 `talent.blackboard.*` 的未识别栏。判据里配了**负对照**：
同一份载荷换个 charID 仍然要报概率缺口。

模组进一步改写这条天赋（见第四节）：`emit_count` 进同一套抽样；`element_atk_scale`
需要"目标处于凋亡损伤爆发期间"，条件判不出来 ⇒ 具名缺口（概率那一半不受影响）。

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

**两层各报一次的现象已消除**：V-2 裁定前，通用天赋分类器会报 `talent.probability_event`，
操作员闭环再报一条 `logos.talent1.prob_v2`（"在等 V-2"），拒判理由里会同时看到两条。
裁定之后两条都没有了——`logosExactProbTalent` 让通用分类器认出"这条链已被精确抽样消费"，
`prob_v2` 那条随裁定撤销。**反向**由判据守着：`TestLogosGapsNameEveryUnconsumedMechanism`
显式断言 `logos.talent1.prob_v2` 不许再出现。

---

## 六、运行期接线点

| 位置 | 作用 |
|---|---|
| `sim.go` 部署分支 | 解码运行期配置、建立 `LogosBattleState`（**seed 从规格来**）、写 `logos_rng_seed` 事件 |
| `sim.go` 主循环（帧序 5，我方出手之前） | `logosTick`：技能一斩杀、技能二锁定拍 |
| `sim.go` 我方出手路径（主目标循环之后） | **天赋一精确抽样**（额外法伤＋停顿）、天赋二施加、技能三多目标痕迹 |
| `sim.go` 我方出手开头 | 技能二期间**整段跳过**（平A 停摆，因此那一档不抽天赋一的签） |
| `sim.go` `enemy.res()` | 天赋二的法抗削减 |
| `sim.go` `advance` 速度式 | 技能二的移速乘区（天赋一的停顿走既有 `sluggishFactor`） |
| `skill.go` `res()` | 技能二的法术抗性 +70 |
| `skill.go` `maxTarget()` | 技能三的同时攻击目标数 |
| `skill_range.go` `targetRange()` | 技能一/三的攻击范围扩大 |
| `logos_rng.go` | splitmix64 抽样器（`chance` / `pick` / `float`） |
| `operators.go` / `wire.go` | `LogosSource` 字段、技能范围绝对格、`rng_seed` |
| `mechanism_gaps.go` | 逻各斯分支：具名缺口逐条上报；`logosExactProbTalent` 给概率链开精确豁免 |

---

## 七、测试与验收

- `logos_spec_test.go`：精英×潜能×技能槽×技能等级矩阵、天赋与技能数值逐档比对、
  模组三级覆盖、非法训练档边界。
- `logos_mechanics_test.go`：天赋二的法抗/平坦加值与到期、技能一阈值与转移伤害
  （含法抗削减）、技能二爬坡与满层自洽性、目标倒下重置、技能三目标数、
  技能范围扩大、缺口逐条具名（含"概率缺口不许再出现"的反向断言）。
- `logos_prob_test.go`（V-2 裁定新增）：
  - `TestLogosTalent1SameSeedBitIdentical`：同 seed 两次 `runSimContext` 的判决
    **字节级相等**（只剔掉墙钟 `sim_ms`），并配"换 seed 必须不同"的正对照；
  - `TestLogosTalent1DifferentSeedDiffers`：8 个 seed 的命中次数集合必须不止一个值；
  - `TestLogosTalent1DistributionLoose`：2000 次抽签的命中率落在 prob 的 ±0.06 松界内
    （3σ≈0.033 再留余量，不写成必然绿）；
  - `TestLogosTalent1BoundaryAndNoTargetControls`：prob=0／prob=1／范围无候选三个负对照；
  - `TestLogosTalent1ExactDamageAndSluggish`：额外伤害＝atk×scale 经法抗结算、停顿秒数
    与 `sluggishFactor()` 的 80% 口径；
  - `TestLogosTalent1EmitCountDistinctTargets`：`emit_count=2` 打两个**不同**目标，候选不足时不重复打；
  - `TestLogosGenericClassifierExemptsExactProbChain`：通用分类器不报概率缺口，且配负对照
    （换 charID 仍要报）；
  - `TestLogosExactProbTalentValidatorBoundaries`：豁免判据能收也能拒（四个反例）；
  - `TestLogosSeedSurvivesSerialization`：seed 序列化后不变、判定序列可重放、相邻 seed 不退化；
  - `TestLogosSpecHasNoProbabilityGapAtFullTraining`：满练时规格级闸门不再产出概率缺口。
- `logos_full_lifecycle_test.go`：
  - `TestLogosRunsAfterV2Ruling`：真调 `runSimContext`，断言**能跑出判决**且判决上带
    `logos_rng_seed`（旧 `TestLogosRefusedUntilV2Ruling` 随裁定删除）；
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
   「先结算加层」会把满层推后一拍。
5. **技能二的锁定重选**：目标倒下/离开范围才重选；技能期间目标一直在范围内就一路锁死。
6. **天赋一的抽样口径**：每**普通出手**抽一次签；技能二「提喻」的锁定伤害不是普攻，
   不抽这一支（那一档的攻击已被技能替换）。
7. **天赋一的候选池是否排除本击主目标**：数据里没有第二个键可判；当前**包含**主目标
   （与"攻击范围内一个随机目标"的字面读法一致）。

### 本仓里仍用期望值的地方（裁定第 3/4 条的边界）

**已清掉**（2026-10-25 两档推进，`wip/expvalue-20261025` 与 `wip/prob-audit-20261025`）：
`sim.go` 里那两处改成了**精确抽样**，与逻各斯这条链**共用同一套**机制——种子仍在规格层
（落在 `OperatorSpec.rng_seed`，逻各斯证据包里的那份是手工规格的回落）、
同一台 `prob_rng.go` 的取数口、`chance(0)/chance(1)` 不取数、命中时写语义事件
（`talent_proc` / `talent_extra_heal`），并在第一次抽签时补一条 `prob_rng_seed`：

1. **「要害瞄准·初级」一族**（`talent_proc_*`）：原来乘期望倍率 `Π(1+p(s−1))`，
   现在**逐击独立抽签**、命中者把当次攻击力整份乘 `s`、未命中原样。
   `TalentProcFactor` 降级为**证据/自校验**用（战斗不再读它）。
2. **「附加治疗」**（`attack@prob`）：原来每次治 `p × 治疗量`，现在**抽中才治、
   治整份**（没抽中这一击就只有一名）。

#### 全键集闭合数据驱动豁免（2026-10-25 博士裁定第五节 (b)）

旧硬编码豁免（`logosExactProbTalent` 按 `charID == logosCharID` 豁免）已彻底废弃，
改为**数据驱动的全键集闭合审计**（`sampledProcChain` + `sampledExtraHealChain`）：
- 豁免是**按天赋**给的，不是按干员给的：只有当单条天赋的所有黑板键**全部**落到精确消费者
  （seed 抽样链或已建模机制）时才豁免该天赋的概率事件；
- 天赋中任何一个键无精确消费者 ⇒ 继续拒判，并在 `IncompleteError` 中具名报出未闭合的黑板键。

**24 位干员审计与翻转清单**：
- **整人翻转可跑（5 位）**：克洛丝（char_124_kroos）、跃跃（char_4100_caper）、
  红隼（char_4023_rfalcn）、风笛（char_222_bpipe）、月见夜（char_283_midn）。
  （加上此前已闭合的逻各斯 char_4133_logos 计 6 位）。
- **天赋闭合但技能/特性未闭合仍拒判（5 位）**：安赛尔（S1 缺 `ability_range_forward_extend`）、
  灰喉（S1 缺 `cnt`）、Stormeye-511（S1 缺 `attack@max_target`/`times`）、
  至简（特性缺 `delta/init/max_atk_scale`）、真言（S1 缺 `element_atk_scale`/`ep_damage_ratio`）。
- **多天赋部分闭合边界典型（2 位）**：Stormeye-611（T0 闭合，T1 缺 `delay`/`sp_recovery_per_sec`）、
  艾拉（T1 闭合，T0 缺 `cnt`/`tokenKey`）——整场仍被未闭合天赋拦截。
- **概率天赋本身仍有未识别键、天赋层面即拒判（11 位）**：古米（缺 `stun`）、
  达格达（缺 `atk_up_each_time`/`max_value` 等）、寒芒克洛丝（缺 `stun`）、
  槐琥（缺 `force`）、普罗旺斯（缺 `prob2`）、承曦格雷伊（缺 `attack@sluggish`）、
  黑（缺 `defdown_duration`/`def`）、维什戴尔（缺 `attack@main_atk_scale` 等）、
  澄闪（缺 `attack@atk_scale_2`/`max_stack_cnt`）、Misery（缺 `attack@normal_prob` 等）、
  锏（缺 `not_combat`/`def_penetrate`）。

对应双向对照测试落地于 `prob_controls_test.go`（`TestDataDrivenExemptionControls`）
与 `prob_exact_test.go`（`TestTalentProbGateDataDrivenExemption`）。

另：本档的 PRTS 整页取证尚未执行，数值与描述均取自 gamedata 原文。

---

## 九、中间文件清理

本档的全部取数都在仓外 shell 里用一次性脚本读 gamedata 原文完成（未落地任何中间文件）；
未产生需要清理的下载响应、解码 HTML 或临时探针。正式源码、测试与本文档保留。
