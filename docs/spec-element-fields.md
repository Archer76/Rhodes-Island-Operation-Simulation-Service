# 元素损伤字段族：spec 该送什么（五列 · 已取证版）

> 依通告 #5 六：本文是**后端交付的元素损伤字段族清单**，供项目经理排 `spec.py` 的下一段窗口。
> 列名照裁定：**键名 / 类型 / 默认值 / 闸门语义 / Go 侧消费点**。
>
> **版本说明**：第一版是**从 Go 消费点反推**的，当时就写明「未从 `enemydb` 取证、不是施工图」。
> 本轮按承诺去数据里取证，**推翻了第一版的两处结构性假设**（见 §一）。以本版为准。

## 一、取证结论：第一版错在哪（这是本文最重要的部分）

| 第一版的假设 | 数据里的真相 | 取证命令 |
|---|---|---|
| 抗性按**元素种类**各一档（5 元组） | **标量**：`enemy_level.element_resistance` / `damage_resistance` 各**一个数**（2013 行全非空，取值如 `0.0` / `10.0`） | `PRAGMA table_info(enemy_level)` + `SELECT DISTINCT` |
| 元素损伤有**固定的字段名**（`element_amount` / `element_kind`） | **不是固定字段**，是**一整个黑板键族**，前缀**每个敌人各不相同** | 见 §二·B |
| 数值是绝对值 | **比例与绝对值两种都有**：`ep_damage_ratio`（多为 0.05~0.6，也有 `1.5`）/ `ep_damage_value`（绝对值，如 `ScreamDebuff.ep_damage_value=30.0`）/ `ep_damage_scale`（倍率） | `SELECT blackboard ... LIKE '%ep_damage%'` |

**⇒ 教训**：字段清单**不能从消费端反推**。Go 那边写成"按 5 种元素各存一档"是**实现的选择**，
而数据侧只有一个标量；照第一版施工，会造出五个数据侧根本填不满的数组，
**然后它们会静静地取默认 0** —— 正是本项目最贵的那条教训（缺字段静默按 0，对拍还全绿）。

## 二、字段清单（本版）

### A. 每单位的元素状态

| 键名 | 类型 | 默认值 | 闸门语义 | Go 侧消费点 |
|---|---|---|---|---|
| `element_resistance` | number（**标量**） | `0` | 可空（缺省 0＝不抵抗） | `resolveElementDamage(a, elementRes)`（伤害式，5% 保底那一路） |
| `damage_resistance` | number（**标量**） | `0` | 可空（缺省 0） | `elementDamage(amount, resist)`（损伤式） |
| `max_ep` | number | 普通/精英 `1000`、领袖 `2000` | **拒跑**：有元素损伤来源却缺此值不得猜档 | `newElementState(maxEP)`、`defaultMaxEP`/`leaderMaxEP` |
| `ep_init` | number | `= max_ep`（回满） | 可空（缺省＝回满，与口径一致） | `elemState.ep` 初值；守卫 `element_test.go:20` |

⚠ **`element_resistance` 与 `damage_resistance` 是两件事**（两条吃抗性的路不同），
数据侧就是两列，**不许并键**；也**不许**扩成按元素种类分档（数据侧没有这个维度）。

### B. 元素损伤的来源＝黑板键族（**不是固定字段**）

真实键名形如 **`<前缀>[.attack]@ep_damage_ratio`**，前缀由该敌人的机制决定，实测 40+ 种：
`EpDamage.` / `epdamage.` / `aura.` / `aura2.` / `aura3.` / `Attack.` / `Attack2.` / `Wake2Sleep.` /
`Drop.` / `GetEnmey.` / `EpAttack.` / `DamageAura.` / `M2ChargeAttack.` / `Reborn.` / `Boom.` /
`killed.` / `block.` / `mode.` / `aoe.` / `inside.` / `pow.` / `water.` / `recovery.` / `Element.` /
以及**纯数字前缀** `1.` / `2.` / `3.` / `4.` / `0.` ……

| 键名 | 类型 | 默认值 | 闸门语义 | Go 侧消费点 |
|---|---|---|---|---|
| `blackboard`（**原样映射**） | object（string→number） | `{}` | **拒跑**：键族里出现 `ep_damage*` 却**没送这张表**时拒跑 | 需新增一层"按前缀查表"的取值器，喂给 `elementDamage` |
| …其中 `*ep_damage_ratio` | number | 无 | 数值＜1 多为比例，实测也有 `1.5` ⇒ **比例是"乘以什么"必须取证后才许用** | `elementDamage` 的 `amount` |
| …其中 `*ep_damage_value` | number | 无 | **绝对值**（`ScreamDebuff.ep_damage_value=30.0`） | 同上，**直接当 amount** |
| …其中 `*ep_damage_scale` | number | `1` | 倍率式 | 乘在 amount 上 |
| `element_kind` | enum（`ba.dt.*`） | 无 | **拒跑**：有损伤就必给 | `elementKind`（须做 §三 的映射） |

### C. 爆发效果表

| 键名 | 类型 | 默认值 | 闸门语义 | Go 侧消费点 |
|---|---|---|---|---|
| `burst_duration` | number | 无 | **拒跑**：有爆发就必给 | `elementBurst.Duration` |
| `burst_cooldown` | number | 无 | **拒跑** | `elementBurst.Duration`（Go 侧目前是同一个字段，见 §四.3） |
| `burst_def_down` / `burst_res_down` / `burst_weak_pct` | number | `0` | 可空 | `elementBurst.DefDown` / `ResDown` / `WeakPct` |
| `burst_palsy_stack` / `burst_palsy_immune` | int / bool | `0` / `false` | 可空 | `elementBurst.PalsyStack` / `PalsyImmune` |
| `burst_direct` / `burst_direct_type` | number / enum | `0` / 空 | 可空 | `Direct` / `DirectType`（PHYSICAL·MAGIC·TRUE·ELEMENT） |
| `burst_dot` / `burst_dot_type` / `burst_dot_growth` | number / enum / number | `0` | 可空 | `Dot` / `DotType` / `DotGrowth`（狂躁） |

⚠ **C 组在敌方黑板里没找到对应键**（我按 `ep|burst|break` 扫过整库，只扫出无关的 `Sleep2Wake.*`）。
⇒ 它很可能住在 **gamedata 的元素总表**（而不是逐敌人黑板），**这一点未取证**，见 §四.4。

## 三、种类 id 的对照（必须一起送，否则会整体错位）

数据侧权威 id 取自正文的 `术语|ba.dt.*`（实测计数）：

| 数据侧 id | 中文名 | 命中 | Go 侧现有常量（`element.go:46-51`） |
|---|---|---|---|
| `ba.dt.neural` | 神经损伤 | 72× | `elemSanity`（SANITY） |
| `ba.dt.erosion` | 侵蚀损伤 | 49× | `elemWater`（WATER） |
| `ba.dt.burning` | 灼燃损伤 | 78× | `elemFire`（FIRE） |
| `ba.dt.apoptosis` | 凋亡损伤 | 27× | `elemDark`（DARK） |
| `ba.dt.rampage` | 狂躁损伤 | 3× | `elemAnger`（ANGER） |
| `ba.dt.element` | 元素损伤（**通用**，非第六种） | 5× | ⚠ 无对应；**须裁定** |
| `ba.dt.stun` | 晕眩（**不是元素损伤**） | 3× | ⚠ 不得当元素处理 |

**这张表是承重墙**：Go 的常量名（SANITY/WATER/FIRE/DARK/ANGER）与数据侧 id 是**两套词**，
若靠"顺序猜"，神经会被当成灼燃。**键名映射必须显式写进规格或适配层，不许靠下标。**

## 四、未验证项（本版的诚实边界）

1. **`ep_damage_ratio` 的"比例"乘的是什么**：未取证。实测有 `1.5`（`GetEnmey.`，安眠伴随兽）
   ⇒ **不能假定它 ≤1**，也不能假定"比例×攻击力"。取证入口：`ak_tactic/formula` 的敌人侧编译
   （`python -m ak_tactic formula --enemy "<正文>"`）与该敌人的技能正文。
2. **前缀的语义**：`aura.` / `Wake2Sleep.` / `GetEnmey.`（原文拼写如此）是**机制来源**还是**触发时机**，
   未取证。它决定了"什么时候结算"——**不查清就接，会把持续伤害接成一次伤害**。
3. `burst_cooldown` 与 `burst_duration` 在 Go 里共用 `elementBurst.Duration` 一个字段。
4. **C 组的来源未找到**（见 §二·C ⚠）。可能住 gamedata 元素总表；**未验证**。
5. 领袖档 `2000` 未逐敌人核对（`defaultMaxEP/leaderMaxEP` 来自 PRTS 口径）。
6. 谁带元素损伤（用于闸门判据）已可列：正文命中 ≥10 个敌人，
   含「偏执泡影」「水上明珠」引浪兽「小惊喜」「余音」暗黑发条仆从「酒神」「剧团喉舌」「火种」等。

## 五、给窗口的建议（本清单的用法）

**先做 §二·B 的"黑板原样映射"这一条就够了**：它一条就能让所有带元素损伤的敌人
从"静默按 0"变成"要么真算、要么拒跑"。§二·C（爆发效果表）可以后置——
它缺省 0 是**有意义的**（那种元素本来就没这个效果），风险远低于 B 组的沉默。

**深水限定语**：本文不改变任何门的判据，也不构成对「本树现有用例全绿」之外的任何结论。
