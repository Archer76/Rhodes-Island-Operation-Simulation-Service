# 元素损伤字段族：spec 该送什么（五列）

> 依通告 #5 六，本文是**后端交付的第一份字段清单**，用于项目经理排 `spec.py` 的下一段窗口。
> 列名照裁定：**键名 / 类型 / 默认值 / 闸门语义 / Go 侧消费点**。
>
> **口径来源**：PRTS 权威页原文（本仓库 `docs/mechanics-dictionary.md` §四 已登记），
> 以及 Go 侧已落地的 `rios-sim/element.go`（353 行，2026-09-19 第 4 轮）。
> **当前状态：Go 内核已落地、零生产调用点**（调用点只有 `element_test.go`），
> spec 侧**一个字段都没有**（`grep -n 'element\|ep_\|max_ep\|损伤' ak_tactic/simgo/spec.py` → 0 命中）。

## 一、先钉三条口径（这三条决定字段怎么切）

1. **元素值（EP）从最大值开始，降到 0 即"爆条"**；爆条后进入**爆发冷却**，
   *冷却期间对该元素免疫*，结束后 EP **回满**（不是留余量）。
2. **两套吃抗性的方式不同，别并成一个键**：
   * **损伤式**（EP 扣减）吃 **损伤抵抗**：`EP -= amount × (1 − resist%)`；
   * **伤害式**（真伤那一路）吃 **元素抗性**：`max(0.05a, 0.01a × (100 − elementRes))`
     —— 即 5% 保底那一路，与物理/法术的保底同源。
3. **最大 EP 只有两档**：普通/精英 **1000**、领袖 **2000**；
   全元素共用同一张最大值表，按**元素种类**各存一份 EP，互不抵扣。

## 二、字段清单（Go 消费点＝`rios-sim/element.go` 的对应符号）

### A. 每单位的元素状态（`newElementState(maxEP)` / `elemState.ep[]` / `elemState.resist`）

| 键名 | 类型 | 默认值 | 闸门语义 | Go 侧消费点 |
|---|---|---|---|---|
| `max_ep` | number | 普通/精英 `1000`、领袖 `2000` | **拒跑**：有元素损伤来源却缺此值时不得猜档 | `newElementState(maxEP)`、`leaderMaxEP`/`defaultMaxEP` |
| `ep_init` | number[5] | `= max_ep`（回满） | 可空（缺省＝回满，与口径 1 一致） | `elemState.ep` 初值；守卫见 `element_test.go:20` |
| `ep_resist` | number[5] | `0` | 可空（缺省 0 ＝不抵抗） | `elementDamage(amount, resist)` |
| `element_res` | number[5] | `0` | 可空（缺省 0） | `resolveElementDamage(a, elementRes)` |

⚠ 两个数组**都是按元素种类索引的 5 元组**（顺序：SANITY / WATER / FIRE / DARK / ANGER，
见 `element.go:46-51`）——不是按伤害类型。送字段时必须带上这个顺序的定义，
否则"神经抗性"会被读成"物理抗性"。

### B. 每次施加（攻击/技能/天赋那一路）

| 键名 | 类型 | 默认值 | 闸门语义 | Go 侧消费点 |
|---|---|---|---|---|
| `element_kind` | enum | 无 | **拒跑**：有损伤就必给（五种之一） | `elementKind`（0..5，0=NONE） |
| `element_amount` | number | 无 | **拒跑**：同上 | `elementDamage` 的 `amount` |
| `element_path` | enum `damage`/`loss` | 无 | **拒跑**：决定吃哪个抗性（口径 2） | `damage`→`resolveElementDamage`；`loss`→`elementDamage` |

### C. 爆发效果表（爆条那一下做什么）

| 键名 | 类型 | 默认值 | 闸门语义 | Go 侧消费点 |
|---|---|---|---|---|
| `burst_duration` | number | 无 | **拒跑**：有爆发就必给 | `elementBurst.Duration` |
| `burst_cooldown` | number | 无 | **拒跑**：同上（**与 `burst_duration` 是两列**，如侵蚀 10s vs 敌人 8s） | `elementBurst.Duration` 的第二节 |
| `burst_def_down` | number | `0` | 可空 | `elementBurst.DefDown`（侵蚀，立刻永久、不被重生清除） |
| `burst_res_down` | number | `0` | 可空 | `elementBurst.ResDown`（灼燃，直接加算） |
| `burst_weak_pct` | number | `0` | 可空 | `elementBurst.WeakPct`（凋亡，最终乘算） |
| `burst_palsy_stack` | int | `0` | 可空 | `elementBurst.PalsyStack`（神经，敌人列） |
| `burst_palsy_immune` | bool | `false` | 可空 | `elementBurst.PalsyImmune` |
| `burst_direct` / `burst_direct_type` | number / enum | `0` / 空 | 可空 | `Direct` / `DirectType`（PHYSICAL·MAGIC·TRUE·ELEMENT） |
| `burst_dot` / `burst_dot_type` | number / enum | `0` / 空 | 可空 | `Dot` / `DotType` |
| `burst_dot_growth` | number | `0` | 可空 | `DotGrowth`（狂躁：每次普攻/技能能力触发时递增） |

## 三、闸门语义为什么这样定（请项目经理核这一条设计）

`element.go` 已经能算，但**它算不出"这个敌人有没有元素损伤来源"** ——
那是数据侧的事实。所以闸门的判据应当是：

> 敌方的技能/天赋里**带着元素损伤**，而规格里**没有对应的 A/B 两组字段** ⇒ **拒跑**（不静默按 0 算）。

理由就是本项目的铁律：**静默按 0 算等于把机制悄悄关掉**，而对拍会因为两边都"没有元素损伤"
而全绿（记忆 `8a1ec6d6`：无回归不等于已验证）。C 组则相反——它描述的是"爆条时做什么"，
缺省 0 是**有意义的**（那种元素本来就没这个效果），所以可空。

## 四、未验证项（交清单时的诚实边界）

1. **数据侧键名未取证**：本清单的 A/B/C 是**从 Go 消费点反推**的（可复现：读 `element.go`），
   **不是**从 `data/enemydb.sqlite` 的敌方技能/天赋黑板里读出来的。下一步要做的正是后者：
   把"哪些敌人的哪个键带元素损伤"逐条对到 A/B 两组上——**这一步没做之前，本清单不能当施工图**。
2. **5 元组的顺序**（SANITY/WATER/FIRE/DARK/ANGER）来自 `element.go` 的常量定义，
   未与游戏数据里的枚举序对照过（若数据侧顺序不同，两个数组会整体错位）。
3. `burst_cooldown` 与 `burst_duration` 在 Go 里**共用同一个字段**（`elementBurst.Duration`），
   规格侧要不要拆成两个键，取决于数据侧是否本来就分两列——**待取证**。
4. 领袖档 `2000` 与 `defaultMaxEP` 的取值来自 PRTS 口径，**未逐敌人核对**。
