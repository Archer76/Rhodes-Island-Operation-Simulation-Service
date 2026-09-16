# SR-EX-8（`act54side_ex08`）8 种敌人的全部特殊机制

活动「月行水上」（SR）EX-8。关卡 `act54side_ex08`，13×9，生命 3，人数上限 8，初始费用 10，
`moveMultiplier = 0.5`，共 39 只敌人 8 种。

本报告的目标是把这 8 种敌人的**天赋、技能、被动**逐条摊开，并标明每一条是「确证」还是「推断」。

---

## 0. 证据分级与取数方式

| 标记 | 含义 | 来源 |
| --- | --- | --- |
| 【确证·原始数据】 | 直接从解包 JSON 读出的字段 | `levels/enemydata/enemy_database.json` |
| 【确证·图鉴】 | 游戏内图鉴文本（`abilityList` / `description`） | `excel/enemy_handbook_table.json` |
| 【确证·prts.wiki】 | prts.wiki 敌人页「天赋&能力 / 技能」段落，比图鉴更细（含数值、模式、阈值） | prts.wiki 敌人页 wikitext |
| 【确证·prts.wiki机制】 | prts.wiki「特殊机制」「全场总攻击（装置）」条目 | prts.wiki 词条 |
| 【推断】 | 我根据 prefabKey、blackboard 键名与上述文本做的对应关系推断 | — |

取数脚本一律走项目自有取数层（`GameDataSource` / `EnemyLibrary`），未自写 HTTP。
prts.wiki 侧用 `action=query&prop=revisions&rvslots=main`（`?action=raw` 在本 wiki 不可用）。

### 0.1 一个必须先讲清的数据版本事实

**这份 gamedata 版本里 `enemyData` 根本没有 `talents` 字段。**

```
"talents"          -> 0 次出现
"talentBlackboard" -> 2411 次出现（= 2151 个敌人条目 + 分档）
"skills"           -> 2411 次
"prefabKey"        -> 4106 次（= 2151 个 enemyData.prefabKey + 1955 条技能 prefabKey）
```

也就是说：**天赋被拍平成了一张 `talentBlackboard` 键值表，天赋自身的 `prefabKey` 在敌人侧不可得。**
能拿到的只有「命名空间前缀 + 键 + 值」，例如
`TotalAttack.weak_max = 2000`、`Shield.shield_hp_ratio = 0.25`、`Reborn.reborn_duration = 10`。

推断：**前缀就是该天赋的 prefabKey**。旁证是关卡装置 `trap_335_totalattack` 在 `character_table.json`
里的天赋 `prefabKey` 正是 `TalentTotalAttack`，而其 blackboard 键是无前缀的
`trigger_cd / attack@atk_scale / attack@base_atk / attack@all_atk_scale`；
全库前缀里 `Reborn`(241)、`TotalAttack`(110)、`switchMode`(104)、`Shield`(45)、`Talent1`(24) 等
都是典型的 prefabKey 命名风格。**这一点是推断，不是确证。**

**技能侧不受影响**：`enemyData.skills[]` 每条都有 `prefabKey`、`priority`、`cooldown`、
`initCooldown`、`spCost`、`blackboard`，与 prts.wiki 的技能表一一对得上。

---

## 1. 关卡级机制（这 8 个敌人全部依赖它，必须先懂）

### 1.1 伤害相性（P3R）/ 击破值 / 倒地 【确证·prts.wiki机制】

> 作为对《女神异闻录３ Reload》伤害相性机制的模拟，所有于月行水上登场的敌人均拥有
> 对于**物理 / 法术 / 元素**的**伤害相性**（弱点 / 正常 / 免疫 / 反射）及**击破值计量**。
>
> 伤害相性为**弱点**时：
> - **物理 / 法术**弱点：未【倒地】的情况下，成功受到对应伤害后，累积等同于**受伤前后生命值变化量**的击破值；击破值达到**倒地阈值**后清空计量并【倒地】。
>   ※ 物理与法术弱点二者有且仅有其一时，单位获得该伤害类型的固定弱点（可影响弱点伤害输出类型）。
> - **元素**弱点：未【倒地】的情况下，任意**元素损伤爆发**时，立即清空计量并【倒地】。
>
> 【倒地】持续一段时间，且：
> ① 【倒地】开始时获得**等时长的眩晕**（会随【倒地】的解除而解除）；
> ② 【倒地】期间**不可阻挡**，**嘲讽等级 −1**。
>
> 伤害相性为**免疫**时：受到对应类型伤害前，令该伤害**归零**；伤害相性为**元素免疫**时还会令所受损伤归零。
> 伤害相性为**反射**时：在免疫的基础上，将归零前的伤害/损伤量的 **10%** 以无途径真实持续伤害的形式「返还」给来源（直接选中）。

**要点（对模拟器最致命的三条）**：
1. 击破值累积的是**实际掉血量**，不是原始伤害 —— 也就是说被 DEF/RES 吃掉的部分不算。
2. 【倒地】= **眩晕**（不能动、不能攻击）+ **不可阻挡** + 嘲讽 −1。
3. 元素弱点这条**与伤害无关**：任意元素损伤爆发即立刻倒地。本关 8 种敌人里有 5 种带元素弱点。

### 1.2 黑板上 `TotalAttack.PHYSICAL / MAGICAL / ELEMENT` 的取值语义 【强推断，8/8 交叉验证】

原始数据里是 0 / 1 / 2 三个数，与图鉴「弱点」文本逐一对照后**完全吻合**：

| 值 | 含义 | 依据 |
| --- | --- | --- |
| `0` | **弱点** | 图鉴写「X 弱点」时该项必为 0 |
| `1` | **正常** | 图鉴写「物理正常」或未提及时为 1 |
| `2` | **免疫** | 图鉴写「免疫法术伤害」时该法术项为 2 |

验证用例（全部命中，无例外）：
- 刺溜冰淇淋 图鉴「弱点：物理、法术、元素」→ `0/0/0`
- 沉默收音机 图鉴「弱点：法术、元素」→ `1/0/0`
- 咆哮铳 图鉴「弱点：元素」→ `1/1/0`
- 吓人路灯 图鉴「弱点：物理、元素；免疫法术」→ `0/2/0`
- 挥铳圣像 图鉴「没有弱点」→ `1/1/1`
- 死志的凝结 第一形态「弱点物理、免疫法术」→ `0/2/1`；第二形态「弱点法术、免疫物理」→ `2/0/1`

`3`（反射）在本关 8 种敌人本体上未出现 —— BOSS 的反射是「重生后由免疫转化」，
写在天赋文本里而不是黑板上。**故 3=反射 是推断。**

### 1.3 全场总攻击（`trap_335_totalattack`）—— 关卡唯一的全局装置 【确证·prts.wiki机制 + 原始数据】

SR-EX-8 的 `predefines.tokenInsts` 里有且仅有一个装置，部署在 (0,0) 朝上：

```json
{"characterKey": "trap_335_totalattack", "level": 1, "phase": "PHASE_0"}
```

它在 `character_table.json` 里的天赋 `prefabKey = TalentTotalAttack`，黑板书：

| key | value |
| --- | --- |
| `trigger_cd` | 8.0 |
| `attack@atk_scale` | 1.0 |
| `attack@base_atk` | 15000.0 |
| `attack@all_atk_scale` | 1.0 |

装置名「全场总攻击」，我方阵营，生命 100，攻 0 防 0 抗 0，阻挡数 0，占用部署数 0，攻击范围 0-1，
阻挡半径 0.7071，技力恢复 1.0/s。prts.wiki 装置页给出的机制：

> - 无法被玩家选择查看详细信息。
> - 持有**无敌、不可阻挡、孤立、禁疗、沉睡免疫、闭锁免疫**。
> - **每 0.1 秒检测一次**，场上所有具有伤害相性（P3R）的单位（不包括消失状态的单位）**全部【倒地】时触发**：
>   - 触发 0.1 秒后，直接选中全场范围内的所有**角色类**我方干员，自身获得
>     `攻击力最终增加 [(15000 + 此次选中干员的攻击力总和) × 1.0]` 的增益（最终加算，重复获得时刷新增益数值）。
>   - 触发 0.8 秒后，对全场范围内的**所有敌方单位（可对空）**造成
>     `攻击力 100% 的无来源近战途径真实伤害`，随后直接选中并**解除全场范围内所有敌方单位的【倒地】效果**。
>   - 触发后的 8 秒内无法再次触发。

黑板书对应关系：`trigger_cd 8.0` ↔「触发后 8 秒内无法再次触发」；
`attack@base_atk 15000` + `attack@all_atk_scale 1.0` ↔ 增益公式；`attack@atk_scale 1.0` ↔ 伤害 100%。

**这是本关真正的主轴**：玩家把全场敌人**同时打倒在地**，装置就给全体干员一笔
`15000 + 干员攻击力总和` 的最终攻击力加成（含装置自身，所以每次是 15000 再 + 全队攻击力 ×2），
再过 0.8 秒把这份攻击力当**全场真实伤害**糊所有敌人脸上，并清掉倒地状态、重置 8 秒 CD。
换言之：**倒地是「计量表」，全场总攻击是「结算」**。

反过来说，**只要有一只有 P3R 的敌人没倒地，装置就不触发** —— 这就是「没法被倒地」的挥铳圣像
（它明确没有弱点）在关卡里存在的意义：它会卡住整条链路。同理，吓人路灯的屏障会**取消范围内其他敌人的弱点**，
也是为了让它们无法倒地。

### 1.4 关卡 `runes` 【确证·原始数据】

`runes` 共 3 条，**全部 `difficultyMask = "FOUR_STAR"`** —— 只在四星（挑战）版本生效，普通难度无效果：

| key | blackboard |
| --- | --- |
| `global_lifepoint` | `value = 1` |
| `enemy_attribute_mul` | `atk = 1.2`, `def = 1.2`, `max_hp = 1.2` |
| `char_cost_mul` | `scale = 3`（professionMask 36） |

`optionalRunes` / `globalBuffs` / `branches` 均为 `null`。`hardPredefines` 为空。

### 1.5 本关敌人实际使用的数据档 【确证·原始数据】

`enemyDbRefs` 里 8 条，**`enemy_1589_pppdth` 引用的是 `level: 1`**（其余全是 0）：

| enemy_id | level |
| --- | --- |
| `enemy_1589_pppdth` | **1** |
| `enemy_10184_pppsbr_2` | 0 |
| `enemy_10185_pppshd_2` | 0 |
| `enemy_10186_ppparc_2` | 0 |
| `enemy_10188_pppdp_2` | 0 |
| `enemy_10189_pppmag_2` | 0 |
| `enemy_10191_pppgst` | 0 |
| `enemy_10192_ppprpr` | 0 |

prts.wiki 的「级别 1」表给出的 180000 / 750 / 800 与 `Value[1]` 完全一致，
且其【未来的期盼】倍率写作 350%（级别 0 是 250%），正对应
`Value[1].Mode_A.attack@power_atk_scale = 3.5`（级别 0 是 2.5）。
**BOSS 在本关不是 15 万血，是 18 万血。**（`docs/stage-sr-ex-8.md` 记的 15 万应按此更正。）

### 1.6 取数层的字段缺口（供后续修改 `EnemyStats` 参考）

`EnemyStats` 暴露的字段只有：
`enemy_id, level, name, alias, max_hp, atk, defense, magic_resistance, move_speed,
attack_speed, base_attack_time, weight, life_point_reduce, range_radius,
hp_recovery_per_sec, level_type, immunities, raw_attributes`。

**被丢掉的原始字段**：
- 整个 `skills`、整个 `talentBlackboard`、`spData`、`prefabKey`、`description`、
  `enemyTags`、`applyWay`、`motion`、`notCountInTotal`、`numOfExtraDrops`、`viewRadius`、
  `epDamageResistance`、`epResistance`、`damageHitratePhysical/Magical`、`baseForceLevel`。
- `_ATTR_FIELDS` 里列了 `tauntLevel / blockCnt / maxDeployCount / respawnTime / spRecoveryPerSec`，
  也确实算进了 `merged`，**但 dataclass 没有对应字段，取值时静默丢弃**。
- `raw_attributes` 声明了却**从未被赋值**，恒为 `{}`。

**一个真实 bug**：`immunities` 取自当前档的 `attrs_raw`，**不参与跨档合并**。
`enemy_1589_pppdth` 的 `Value[1]` 所有免疫位都是 `m_defined: false`，`_unwrap` 返回 `None`，
于是 `bool(None) → False`：

```
lib.get("enemy_1589_pppdth", 0).immunities -> {'silenceImmune':True,'sleepImmune':True,'frozenImmune':True,
                                               'levitateImmune':True,'fearedImmune':True,'palsyImmune':True,
                                               'attractImmune':True,'groundBoundImmune':True,
                                               'disarmedCombatImmune':True}
lib.get("enemy_1589_pppdth", 1).immunities -> {}          # ← 而关卡用的正是 level=1
```

其余字段（max_hp/atk/def/res/…）因为走了 `_merge_defined` 所以是对的，
唯独自带免疫在 level 1 上全部丢失。**模拟器读 level 1 就会把 BOSS 的沉默/沉睡/冻结免疫全部当没有。**

---

## 2. 逐敌详表

### 2.1 `enemy_10184_pppsbr_2` 刺溜冰淇淋 ×12

- 图鉴编号 **SD1R**，地位 **普通**，`levelType = NORMAL`，`applyWay = MELEE`，`motion = WALK`
- 伤害类型：物理｜攻击方式：近战｜行动方式：地面
- 首次出场 **3.0s**，共 12 只

| 属性 | 值 |
| --- | --- |
| 生命 | 20000 |
| 攻击 | 420 |
| 防御 | 150 |
| 法术抗性 | 0 |
| 移动速度 | 0.8 |
| 攻击间隔 | 2.5 s |
| 攻击速度 | 100 |
| 重量等级 | 1 |
| 阻挡数 | 数据里 `blockCnt` 未定义（常规可被阻挡） |
| `lifePointReduce` | 1 |
| `rangeRadius` | 0.0 |

**天赋（`talentBlackboard`，无天赋 prefabKey 可用）**

前缀推断为 **`TotalAttack`**（【推断】）：

| key | value |
| --- | --- |
| `TotalAttack.weak_max` | 2000.0 |
| `TotalAttack.fall_duration` | 15.0 |
| `TotalAttack.PHYSICAL` | 0.0 |
| `TotalAttack.MAGICAL` | 0.0 |
| `TotalAttack.ELEMENT` | 0.0 |

**技能**：`skills = null` —— **没有技能**。

**机制**

- **仅进行阻挡攻击** 【确证·prts.wiki】。它只打挡住自己的单位，不会顺手打旁边的我方单位。
- **伤害相性（P3R）**：物理弱点、法术弱点、元素弱点 【确证·图鉴/prts.wiki】
  → 黑板 `0/0/0` 完全对应。
- **【倒地】阈值 2000 / 持续 15 秒** 【确证·prts.wiki】→ `weak_max 2000`、`fall_duration 15`。
- **元素弱点**意味着：任意元素损伤爆发 → 立即倒地（不看伤害量）【确证·prts.wiki机制】。

**关注项**：无沉默、无眩晕（除倒地自带）、无召唤、无复活、无护盾、无反伤、无远程、无光环、无死亡效果、
无变身、无成长、无对空限制。**唯一机制就是 P3R + 倒地**，且它是全关最容易被点燃的表——2000 阈值、15 秒倒地，12 只。

---

### 2.2 `enemy_10185_pppshd_2` 沉默收音机 ×10

- 图鉴编号 **SD2R**，地位 **普通**，`levelType = NORMAL`，`applyWay = MELEE`，`motion = WALK`
- 伤害类型：物理｜攻击方式：近战｜行动方式：地面
- 首次出场 **3.0s**，共 10 只

| 属性 | 值 |
| --- | --- |
| 生命 | 40000 |
| 攻击 | 750 |
| 防御 | **1750** |
| 法术抗性 | 0 |
| 移动速度 | 0.7 |
| 攻击间隔 | 3.5 s |
| 重量等级 | 3 |
| `lifePointReduce` | 1 |
| `rangeRadius` | 0.0 |

**天赋（前缀推断 `TotalAttack`）**

| key | value |
| --- | --- |
| `TotalAttack.weak_max` | 2000.0 |
| `TotalAttack.fall_duration` | 15.0 |
| `TotalAttack.PHYSICAL` | **1.0（正常）** |
| `TotalAttack.MAGICAL` | **0.0（弱点）** |
| `TotalAttack.ELEMENT` | **0.0（弱点）** |

**技能**：`skills = null` —— **没有技能**。

**机制**

- **仅进行阻挡攻击** 【确证·prts.wiki】。
- **伤害相性**：物理正常、法术弱点、元素弱点 【确证·图鉴/prts.wiki】。
- **【倒地】阈值 2000 / 持续 15 秒** 【确证·prts.wiki】。
- 名字叫「沉默收音机」但**它并不施加沉默** —— 描述只讲它自己被源石技艺扰乱。
  【确证·图鉴】：`silenceImmune = false`，天赋里也没有任何沉默相关键。

**关注项**：除 P3R 外全无。**它是全关的物理检定关**：1750 防御配 40000 血，
物理平 A 会被压到 5% 保底（`max(ATK×scale − 1750, ATK×scale×0.05)`），
必须靠法术或靠「全场总攻击」的真实伤害。它同时也是**法系最好打的靶子**（法抗 0、2000 阈值）。
10 只 × 40000 血是拖时间的主力。

---

### 2.3 `enemy_10186_ppparc_2` 蹒跚羽兽 ×10

- 图鉴编号 **SD12R**，地位 **普通**，`levelType = NORMAL`，`applyWay = RANGED`，`motion = WALK`
- 伤害类型：物理｜攻击方式：远程｜行动方式：地面
- 首次出场 **6.0s**，共 10 只

| 属性 | 值 |
| --- | --- |
| 生命 | 31000 |
| 攻击 | 420 |
| 防御 | 50 |
| 法术抗性 | 0 |
| 移动速度 | 0.9 |
| 攻击间隔 | 3.0 s |
| 重量等级 | 2 |
| `lifePointReduce` | 1 |
| `rangeRadius` | **2.0** |

**天赋（前缀推断 `TotalAttack`）**

| key | value |
| --- | --- |
| `TotalAttack.weak_max` | 2000.0 |
| `TotalAttack.fall_duration` | 15.0 |
| `TotalAttack.PHYSICAL` | **0.0（弱点）** |
| `TotalAttack.MAGICAL` | **1.0（正常）** |
| `TotalAttack.ELEMENT` | **1.0（正常）** |

**技能**：`skills = null` —— **没有技能**。

**机制**（全部【确证·prts.wiki】）

- **近地悬浮**（`ba.float`）：一个独立的悬浮状态。
- **伤害相性**：物理弱点、法术正常、元素正常。
- **【倒地】阈值 2000 / 持续 15 秒**。
- **初始模式**：近地悬浮、失衡免疫、不会攻击飞行单位。
  - 受**眩晕 / 沉睡**影响时 → 进入**坠落模式**。
  - 受**冻结 / 束缚**影响时 → 进入**预坠落模式**。
- **坠落模式**：**无法被阻挡**；普通攻击变「持续攻击」，**不造成伤害**，而是使自身进入**地面模式**
  （普通攻击没有持续时间，不触发麻痹）。
- **预坠落模式**：**无法被阻挡**；普通攻击变「持续攻击」，**不造成伤害**，攻击结束时自身进入**地面模式**。
- **地面模式**：不会攻击飞行单位。

**关注项**：**远程攻击（半径 2.0）**、**悬浮/坠落三态转换**、**坠落期间不可阻挡**。
它是本关唯一「打得到高台」的常规敌人（攻击半径 2.0 且为 RANGED），
也是唯一会因为被控而**反过来获得不可阻挡**的敌人 —— 对模拟器来说
「把它打晕 → 它掉下来变成不可阻挡 → 直接穿过去」是个反直觉的惩罚。

---

### 2.4 `enemy_10188_pppdp_2` 咆哮铳 ×2

- 图鉴编号 **SD9R**，地位 **精英**，`levelType = ELITE`，`applyWay = MELEE`，`motion = WALK`
- 伤害类型：物理｜攻击方式：近战｜行动方式：地面
- 首次出场 **3.0s**，共 2 只

| 属性 | 值 |
| --- | --- |
| 生命 | 30000 |
| 攻击 | 450 |
| 防御 | 600 |
| 法术抗性 | 10 |
| 移动速度 | 1.0 |
| 攻击间隔 | 2.7 s |
| 重量等级 | 2 |
| `lifePointReduce` | 1 |
| `rangeRadius` | 0.0 |

**天赋（前缀推断 `TotalAttack`）**

| key | value |
| --- | --- |
| `TotalAttack.weak_max` | **4000.0** |
| `TotalAttack.fall_duration` | **10.0** |
| `TotalAttack.PHYSICAL` | **1.0（正常）** |
| `TotalAttack.MAGICAL` | **1.0（正常）** |
| `TotalAttack.ELEMENT` | **0.0（弱点）** |

**技能（有，1 条）** 【确证·原始数据】

| 字段 | 值 |
| --- | --- |
| `prefabKey` | **`AttackSelf`** |
| `priority` | 10 |
| `cooldown` | **5.0** |
| `initCooldown` | **5.0** |
| `spCost` | 0 |
| `spData` | `null`（默认自动回复、自动触发） |

blackboard：

| key | value |
| --- | --- |
| `attr_duration` | 10.0 |
| `move_speed` | 2.0 |
| `attack_speed` | 1.0 |
| `self_damage` | 100.0 |

**机制**（【确证·prts.wiki】，技能名在 prts.wiki 上写作「炸膛」）

- **仅进行阻挡攻击**；**无法获得【炸膛增益】**；**索敌不受阻挡影响**。
- 天赋「伤害相性」：物理正常、法术正常、**元素弱点**；【倒地】阈值 4000 / 持续 10 秒。
- **技能【炸膛】**（初始 5 / 消耗 5）：
  > 令**全场范围内**拥有伤害相性（P3R）的**所有其他敌方单位**（无视**孤立**）获得
  > **持续时间无限**的【炸膛增益】（生效期间无法重复获得，于受益者【倒地】开始时解除），
  > 随后对**自身造成 100 真实伤害**。
  >
  > 【炸膛增益】生效期间：
  > ① 受益者**正常**的伤害相性变为**免疫**；
  > ② 受益者**免疫 / 反射**的伤害相性归零伤害或损伤时，受益者自身获得 10 秒
  >    「**攻击速度 +100%、移动速度最终提升至 200%、伤害相性的弱点效果暂时失效**（不影响获得固定弱点的部分）」的增益
  >    （该增益生效期间无法重复获得，于受益者的【炸膛增益】解除时解除）。

**黑板 ↔ 文本对应（这是最干净的一组对照，可作为 prefabKey 语义推断的基准）**

| blackboard | 文本 |
| --- | --- |
| `initCooldown 5.0` / `cooldown 5.0` | 初始 5 / 消耗 5 |
| `attr_duration 10.0` | 增益持续 10 秒 |
| `attack_speed 1.0` | 攻击速度 +100% |
| `move_speed 2.0` | 移动速度最终提升至 200% |
| `self_damage 100.0` | 对自身造成 100 真实伤害 |

**关注项**：**光环式群体增益（全场、无视孤立）**、**给友军加免疫**、**给友军加速加攻速**、
**使友军弱点失效**、**自身周期性自伤**。
它本身没有远程、没有召唤、没有复活、没有护盾、没有反伤、没有死亡效果。
**但它会把整场的 P3R 表盘掀翻**：只要 2 只咆哮铳还活着，每 5 秒就能把全场敌人的
「正常」相性改成「免疫」，把弱点暂时抹掉，并让它们变成 200% 移速、攻击间隔砍半的怪物。
**它是「全场总攻击」链路最大的破坏者之一**。

---

### 2.5 `enemy_10189_pppmag_2` 吓人路灯 ×2

- 图鉴编号 **SD3R**，地位 **精英**，`levelType = ELITE`，`applyWay = RANGED`，`motion = WALK`
- 伤害类型：**法术**｜攻击方式：远程｜行动方式：地面
- 首次出场 **6.0s**，共 2 只

| 属性 | 值 |
| --- | --- |
| 生命 | 50000 |
| 攻击 | 650 |
| 防御 | 300 |
| 法术抗性 | **99** |
| 移动速度 | 0.6 |
| 攻击间隔 | 5.0 s |
| 重量等级 | 2 |
| `lifePointReduce` | 1 |
| `rangeRadius` | **2.5** |

**天赋（前缀推断 `TotalAttack` + `Shield`）**

| key | value |
| --- | --- |
| `TotalAttack.weak_max` | 4000.0 |
| `TotalAttack.fall_duration` | 10.0 |
| `TotalAttack.PHYSICAL` | **0.0（弱点）** |
| `TotalAttack.MAGICAL` | **2.0（免疫）** |
| `TotalAttack.ELEMENT` | **0.0（弱点）** |
| `Shield.shield_hp_ratio` | **0.25** |

**技能**：`skills = null` —— **没有技能**。

**机制**（全部【确证·prts.wiki】）

- **普通攻击为法术伤害**，且是**溅射**：
  > 对**主目标**造成攻击力 100% 的**近战途径法术伤害**，
  > 对主目标**周围四格**内的所有其他我方单位（格子判定，无视目标可选择性，不受**迷彩**制约，**不可对空**）
  > 造成攻击力 100% 的**预计远程途径法术伤害**；**不会攻击飞行单位**。
- **出场后获得可吸收相当于最大生命值 25% 的物理/法术伤害的【屏障】**（= 50000 × 0.25 = **12500**）。
- 该屏障存在期间，**令其攻击范围内所有敌方单位的伤害相性（P3R）的「弱点」效果暂时失效**
  （不影响获得**固定弱点**的部分）。
- **伤害相性**：物理弱点、**法术免疫**、元素弱点；【倒地】阈值 4000 / 持续 10 秒。
  - 法术免疫的实现是双重的：`magicResistance 99`（≈只剩 1%）**加上** P3R 层面的「法术免疫 → 伤害归零」。
    按 P3R 规则，**法术伤害会被直接归零**，连那 1% 都没有。

**关注项**：**护盾/屏障（12500，只挡物理与法术）**、**法术免疫/几乎免疫**、
**远程溅射（主目标 + 四邻，法术伤害）**、**范围内取消友军弱点（光环）**。
无沉默、无眩晕、无召唤、无复活、无死亡效果、无变身。

**模拟层面的坑**：它的屏障**只吸收物理/法术**，而「全场总攻击」打的是**无来源真实伤害** ——
真实伤害能否穿透屏障需要在实现时明确。另：它的溅射**按格子判定、无视迷彩、不可对空**，
主目标吃「近战途径」、溅射吃「远程途径」，这两条途径不同会影响某些减伤结算。

---

### 2.6 `enemy_1589_pppdth` “死志的凝结” ×1（BOSS）

- 图鉴编号 **SD13**，地位 **领袖**，`levelType = BOSS`，`applyWay = RANGED`，`motion = WALK`
- 伤害类型：**物理 + 法术**｜攻击方式：远程｜行动方式：地面
- **本关使用 `level = 1`**（180000 血档）
- 首次出场 **24.0s**，共 1 只

| 属性 | 级别 0 | **本关用的级别 1** |
| --- | --- | --- |
| 生命 | 150000 | **180000** |
| 攻击 | 650 | **750** |
| 防御 | 600 | **800** |
| 法术抗性 | 20 | 20（继承） |
| 移动速度 | 0.7 | 0.7 |
| 攻击间隔 | 6.0 s | 6.0 s |
| 攻击速度 | 100 | 100 |
| 重量等级 | 7 | 7 |
| `lifePointReduce` | **2** | 2 |
| `rangeRadius` | 2.6 | 2.6 |

免疫位（取自级别 0，级别 1 未覆写）：
`silenceImmune / sleepImmune / frozenImmune / levitateImmune / fearedImmune /
palsyImmune / attractImmune / groundBoundImmune / disarmedCombatImmune` 全为 `true`；
**`stunImmune = false`**（图鉴写「免疫晕眩，但能被攻击弱点而倒地」—— 眩晕免疫由【倒地】机制之外的天赋提供）。

> `docs/stage-sr-ex-8.md` 记的「15 万血」是级别 0 的数，本关实际是 **18 万**。

**天赋（`talentBlackboard`，6 组前缀：`Mode_A` / `Mode_B` / `Reborn` / `TalentReborn` / `TotalAttack`）**

| key | 级别 0 | 级别 1 |
| --- | --- | --- |
| `Mode_A.trigger_cnt` | 2.0 | 2.0 |
| `Mode_A.attack_speed` | 50.0 | 50.0 |
| `Mode_A.attack@atk_scale` | 1.0 | 1.0 |
| `Mode_A.attack@power_atk_scale` | **2.5** | **3.5** |
| `Mode_A.PHYSICAL` | **0.0（弱点）** | 0.0 |
| `Mode_A.MAGICAL` | **2.0（免疫）** | 2.0 |
| `Mode_A.ELEMENT` | 1.0（正常） | 1.0 |
| `Mode_B.trigger_cnt` | 2.0 | 2.0 |
| `Mode_B.move_speed` | **2.0** | **1.0** |
| `Mode_B.attack@atk_scale` | 1.0 | 1.0 |
| `Mode_B.attack@power_atk_scale` | 0.6 | 0.6 |
| `Mode_B.PHYSICAL` | **2.0（免疫）** | 2.0 |
| `Mode_B.MAGICAL` | **0.0（弱点）** | 0.0 |
| `Mode_B.ELEMENT` | 1.0（正常） | 1.0 |
| `Reborn.reborn_duration` | 10.0 | 10.0 |
| `Reborn.hp_ratio` | 0.01 | 0.01 |
| `Reborn.max_hp_ratio` | 1.0 | 1.0 |
| `Reborn.attack@attack_trigger_cnt` | 6.0 | 6.0 |
| `Reborn.attack@atk_scale` | 0.5 | 0.5 |
| `TalentReborn.duration` | 0.1 | 0.1 |
| `TalentReborn.hp_ratio` | 0.01 | 0.01 |
| `TotalAttack.weak_max` | **6000.0** | 6000.0 |
| `TotalAttack.fall_duration` | **5.0** | 5.0 |
| `TotalAttack.PHYSICAL` | 1.0 | 1.0 |
| `TotalAttack.MAGICAL` | 1.0 | 1.0 |
| `TotalAttack.ELEMENT` | 1.0 | 1.0 |

**技能（有，1 条）** 【确证·原始数据】

| 字段 | 值 |
| --- | --- |
| `prefabKey` | **`Skill_Revelation`** |
| `priority` | **100** |
| `cooldown` | **30.0** |
| `initCooldown` | **25.0** |
| `spCost` | 0 |
| `spData` | `null` |

blackboard：

| key | value |
| --- | --- |
| `idle_duration` | 5.0 |
| `hp_ratio` | 0.99 |
| `disarmed_duration` | 7.0 |

**机制**（全部【确证·prts.wiki】，技能名 prts.wiki 写作【最后的奖赏】）

天赋：

- 持有**眩晕免疫**（【倒地】期间无效）；**普通攻击造成法术伤害**；
  **每次发动一次攻击获得一层【死志】**（可在形态间继承，达到 2 层时有明显音效提示）。
- **首次被击倒后回复 1% 生命值并进入重生形态**。

**第一形态（初始形态，向上蒸腾的金黄色雾气）**
- **攻击速度 +50**（→ `attack_speed 50.0`，即攻击间隔 6.0 / 1.5 = **4.0 s**）
- 伤害相性：**物理弱点**、**法术免疫（重生后改为反射）**、元素正常
- **【倒地】阈值 6000 / 持续 5 秒**
- **【未来的期盼】**：持有 ≥2 层【死志】时，普通攻击改为对**单个目标**造成攻击力 **250%（级别 1：350%）** 的物理伤害，随后清空【死志】
- 倒地时间结束 / 受**全场总攻击**伤害后 → 切换为**第二形态**并**无敌 5 秒**

**第二形态（水平掠过的青绿色雾气）**
- **移动速度 ×2**，**不可阻挡**（`move_speed 2.0`；级别 1 为 `1.0`，即级别 1 下不变速，但**仍然不可阻挡**）
- 伤害相性：**物理免疫（重生后改为反射）**、**法术弱点**、元素正常
- **【倒地】阈值 6000 / 持续 5 秒**
- **【过去的悔恨】**：持有 ≥2 层【死志】时，普通攻击改为对**攻击半径内所有我方单位**造成攻击力 **60%** 的物理伤害 **6 次**，随后清空【死志】
- 倒地时间结束 / 受全场总攻击伤害后 → 切换为**第一形态**并**无敌 5 秒**

**重生形态**
- 持有**无敌、不可阻挡、失衡免疫、自缚**
- **10 秒内每秒回复 10% 生命值**（生命复原）
- 攻击间隔缩短（prts.wiki 标注「存疑」），**普通攻击变为对全场我方单位造成攻击力 50% 的法术伤害**（不叠加【死志】，至多 6 次）
- 重生结束后，将技能【最后的奖赏】的剩余冷却时间**设为 25 秒**，随后切换到第一或第二形态
- 重生期间的 6 次全场攻击对应 `Reborn.attack@attack_trigger_cnt 6.0`、`Reborn.attack@atk_scale 0.5`、`Reborn.reborn_duration 10.0`

**技能【最后的奖赏】（`Skill_Revelation`）**
> 初始 25 / 消耗 30。**仅能在重生过一次后触发**（重生前会持续尝试触发但始终失败）。
> 蓄力 5s，期间倒地时蓄力与技能**强制终止**。
> 蓄力完成后，对全场每个我方单位造成**其最大生命值 99%** 的真实普通伤害
> （近战途径，**不会致死**），随后获得 **7s 缴械**。

黑板对照：`idle_duration 5.0` ↔ 蓄力 5s；`hp_ratio 0.99` ↔ 99%；
`disarmed_duration 7.0` ↔ 缴械 7s；`initCooldown 25.0` ↔ 初始 25；
`cooldown 30.0` ↔ 消耗 30。

**关注项（本关最复杂的一个）**：**眩晕免疫（倒地期间失效）**、**血量阈值变身（形态切换）**、
**复活/重生 + 重生期回血 + 全程无敌**、**反伤（重生后免疫转反射，10% 无途径真实伤害）**、
**不可阻挡（第二形态、重生形态）**、**攻击力成长/条件强化（【死志】层数 → 250%/350% 单体爆发、
60%×6 群体打击）**、**全场 AOE（重生期法术、最后的奖赏真实伤害）**、**缴械自身 7s**、
**攻击速度提升（第一形态 +50）**、**移动速度提升（第二形态 ×2）**。
无召唤、无死亡效果。

**一个已知机制 BUG（prts.wiki 标注）**：若在【倒地】期间进入重生，
可能因「全场总攻击」等原因在短时间内连续切换两三次形态再进入重生，
导致最终重生后进入的形态**不确定**。

---

### 2.7 `enemy_10191_pppgst` 没办法车 ×1

- 图鉴编号 **SD0**，地位 **普通**，`levelType = NORMAL`，`applyWay = NONE`，`motion = WALK`
- 伤害类型：**无**｜攻击方式：**不攻击**｜行动方式：地面
- 首次出场 **3.0s**，共 1 只

| 属性 | 值 |
| --- | --- |
| 生命 | 20000 |
| 攻击 | **0** |
| 防御 | 200 |
| 法术抗性 | 0 |
| 移动速度 | **1.4**（本关最快之一） |
| 攻击间隔 | 1.0 s（无意义，它不攻击） |
| 重量等级 | 1 |
| `lifePointReduce` | **0** |
| `rangeRadius` | 0.0 |

**天赋（前缀推断 `TotalAttack` + `Talent1`）**

| key | value |
| --- | --- |
| `TotalAttack.weak_max` | 2000.0 |
| `TotalAttack.fall_duration` | 15.0 |
| `TotalAttack.PHYSICAL` | **1.0（正常）** |
| `TotalAttack.MAGICAL` | **0.0（弱点）** |
| `TotalAttack.ELEMENT` | **1.0（正常）** |
| `Talent1.cost` | **50.0** |

**技能**：`skills = null` —— **没有技能**。

**机制**（全部【确证·prts.wiki】）

- **不可阻挡**（`不可阻挡` 异常效果），**不进行普通攻击**。
- **死亡时给予 50 点部署费用**（`Talent1.cost = 50`）。
- 进入**保护目标后不扣除目标生命值**（`lifePointReduce = 0`；图鉴「进入保护目标后，不扣除目标生命值」）。
- **伤害相性**：物理正常、法术弱点、元素正常；【倒地】阈值 2000 / 持续 15 秒。
- 图鉴描述提到「若你是源石技艺大师，也许能修好它，或者让它坏得更厉害」——
  这对应关卡里的 5 个同族变体：
  `enemy_10191_pppgst_2` 生气车（防 2000）、`_3` 困惑车（防 1000）、`_4` 难过车（防 500）、
  `_5` 无聊车（防 200），以及本体没办法车（防 200）。**但 SR-EX-8 只用了本体**。

**关注项**：**不可阻挡**、**漏怪不扣血（`lifePointReduce = 0`）**、**死亡返还 50 费用**。
无远程、无沉默、无眩晕、无召唤、无复活、无护盾、无反伤、无光环、无变身。
**它是本关唯一的「资源道具」**：不可阻挡所以拦不住，但杀了给 50 费，
而且它自己不会扣命 —— 从模拟角度看它既不是威胁也不是目标，是一个**可选的费用补给点**。

---

### 2.8 `enemy_10192_ppprpr` 挥铳圣像 ×1

- 图鉴编号 **SD5**，地位 **精英**，`levelType = ELITE`，`applyWay = RANGED`，**`motion = FLY`**
- 伤害类型：物理｜攻击方式：远程｜行动方式：**飞行**
- 首次出场 **169.0s**（全关最晚），共 1 只

| 属性 | 值 |
| --- | --- |
| 生命 | 25000 |
| 攻击 | **1500** |
| 防御 | 1000 |
| 法术抗性 | 40 |
| 移动速度 | 0.7 |
| 攻击间隔 | 2.0 s |
| 重量等级 | 4 |
| `lifePointReduce` | 1 |
| `rangeRadius` | **1.5** |

**天赋（前缀推断 `TotalAttack`）**

| key | value |
| --- | --- |
| `TotalAttack.weak_max` | 4000.0 |
| `TotalAttack.fall_duration` | 10.0 |
| `TotalAttack.PHYSICAL` | **1.0（正常）** |
| `TotalAttack.MAGICAL` | **1.0（正常）** |
| `TotalAttack.ELEMENT` | **1.0（正常）** |

**技能**：`skills = null` —— **没有技能**。

**机制**（全部【确证·prts.wiki】）

- **飞行单位**（`motion = FLY`，行动方式＝飞行）。它是 SR-EX-8 里**唯一走 FLY 路线**的敌人
  （route 38，也是全关唯一不经过传送口的路线）。
- **静态刚体**：不可被推/拉。
- **不会攻击飞行单位**。
- **伤害相性：物理正常、法术正常、元素正常** —— 也就是**没有弱点**。
- 【倒地】阈值 4000 / 持续 10 秒，**但由于不存在弱点，该敌人将无法【倒地】**，
  从而**可阻止「全场总攻击」的发动**（prts.wiki 明确写了这一句）。

**关注项**：**飞行（无人机路线，只此一条）**、**远程 1.5（打 1500 攻 / 2.0 秒间隔，物理）**、
**高攻高防（1500/1000，法抗 40）**、**无弱点 → 永不倒地 → 卡死全场总攻击**、**静态刚体**。
无沉默、无眩晕、无召唤、无复活、无护盾、无反伤、无死亡效果、无变身、无成长、无光环。

**它是全关的「关门人」**：169 秒才入场，出现在整场最关键的收尾段，
1500 攻击力 2.0 秒一次，物理，能打到 1.5 半径内的干员。
在「全场总攻击」体系里它是个**负资产** —— 只要它活着，全场只要还有一只有 P3R 的敌人没倒地就无所谓，
但如果它是唯一在场且有 P3R 的敌人（其余全清），那么**装置永远不触发**。

---

## 3. 汇总

### 3.1 属性总表

| 敌人 | id | 数量 | HP | ATK | DEF | RES | 移速 | 攻击间隔 | 重量 | LPR | 半径 | 档位 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 刺溜冰淇淋 | `enemy_10184_pppsbr_2` | 12 | 20000 | 420 | 150 | 0 | 0.8 | 2.5 | 1 | 1 | 0.0 | NORMAL |
| 沉默收音机 | `enemy_10185_pppshd_2` | 10 | 40000 | 750 | **1750** | 0 | 0.7 | 3.5 | 3 | 1 | 0.0 | NORMAL |
| 蹒跚羽兽 | `enemy_10186_ppparc_2` | 10 | 31000 | 420 | 50 | 0 | 0.9 | 3.0 | 2 | 1 | **2.0** | NORMAL |
| 咆哮铳 | `enemy_10188_pppdp_2` | 2 | 30000 | 450 | 600 | 10 | 1.0 | 2.7 | 2 | 1 | 0.0 | ELITE |
| 吓人路灯 | `enemy_10189_pppmag_2` | 2 | 50000 | 650 | 300 | **99** | 0.6 | 5.0 | 2 | 1 | **2.5** | ELITE |
| “死志的凝结” | `enemy_1589_pppdth` | 1 | **180000** | **750** | **800** | 20 | 0.7 | 6.0 | 7 | **2** | 2.6 | BOSS |
| 没办法车 | `enemy_10191_pppgst` | 1 | 20000 | 0 | 200 | 0 | **1.4** | 1.0 | 1 | **0** | 0.0 | NORMAL |
| 挥铳圣像 | `enemy_10192_ppprpr` | 1 | 25000 | **1500** | 1000 | 40 | 0.7 | 2.0 | 4 | 1 | 1.5 | ELITE |

合计 39 只。`blockCnt` 在敌人数据里一律未定义（普通敌人默认可被阻挡，例外见「不可阻挡」条目）。

### 3.2 P3R / 倒地总表

| 敌人 | 物理 | 法术 | 元素 | 倒地阈值 | 倒地时长 |
| --- | --- | --- | --- | --- | --- |
| 刺溜冰淇淋 | 弱点 | 弱点 | 弱点 | 2000 | 15 s |
| 沉默收音机 | 正常 | 弱点 | 弱点 | 2000 | 15 s |
| 蹒跚羽兽 | 弱点 | 正常 | 正常 | 2000 | 15 s |
| 咆哮铳 | 正常 | 正常 | 弱点 | 4000 | 10 s |
| 吓人路灯 | 弱点 | **免疫** | 弱点 | 4000 | 10 s |
| BOSS 第一形态 | 弱点 | **免疫**（重生后反射） | 正常 | 6000 | 5 s |
| BOSS 第二形态 | **免疫**（重生后反射） | 弱点 | 正常 | 6000 | 5 s |
| 没办法车 | 正常 | 弱点 | 正常 | 2000 | 15 s |
| 挥铳圣像 | 正常 | 正常 | 正常（**无弱点**） | 4000 | 10 s（**永不触发**） |

### 3.3 天赋 / 技能清单（有无对照）

| 敌人 | 天赋（前缀） | 技能 |
| --- | --- | --- |
| 刺溜冰淇淋 | `TotalAttack`（1 组） | **无**（`skills = null`） |
| 沉默收音机 | `TotalAttack`（1 组） | **无** |
| 蹒跚羽兽 | `TotalAttack`（1 组） | **无** |
| 咆哮铳 | `TotalAttack`（1 组） | **有 1 条：`AttackSelf`**（初始 5 / 冷却 5 / spCost 0） |
| 吓人路灯 | `TotalAttack` + `Shield`（2 组） | **无** |
| “死志的凝结” | `Mode_A` + `Mode_B` + `Reborn` + `TalentReborn` + `TotalAttack`（5 组） | **有 1 条：`Skill_Revelation`**（初始 25 / 冷却 30 / spCost 0） |
| 没办法车 | `TotalAttack` + `Talent1`（2 组） | **无** |
| 挥铳圣像 | `TotalAttack`（1 组） | **无** |

> 注意：这 6 种「无技能」的敌人**不是数据缺失** —— 原始 JSON 里 `skills` 字段确实为 `null`，
> 全库 2151 个敌人条目里有 1320 个是 `skills` 为空、684 个是 `talentBlackboard` 为空。

---

## 4. 战斗模拟层面的建模清单一句话版

按「不实现会显著改变结果」排序：

1. **P3R + 击破值 + 倒地（全 8 种敌人）** —— 没有它，本关的核心（全场总攻击）不成立。
2. **全场总攻击装置（关卡级）** —— `15000 + 全队攻击力` 的最终攻击力加成 → 全场真实伤害，8 秒 CD，需要「全场同时倒地」。
3. **倒地本身的效果** —— 眩晕 + 不可阻挡 + 嘲讽 −1（不是单纯「不能动」）。
4. **BOSS 的双形态 + 重生 + 最后的奖赏** —— 18 万血、形态互切、重生 10 秒每秒回 10%、99% 真伤 + 7s 缴械。
5. **BOSS 的【死志】层数与条件强化** —— 2 层后 350% 单体物理 / 60%×6 群体物理。
6. **咆哮铳的【炸膛增益】** —— 全场友军「正常→免疫 + 弱点失效 + 攻速+100% + 移速 200%」，5 秒一次。
7. **吓人路灯的屏障与弱点光环** —— 12500 屏障 + 范围内友军弱点失效；它自己的法术免疫（RES 99 + P3R 免疫）。
8. **远程攻击** —— 蹒跚羽兽(2.0)、吓人路灯(2.5，溅射)、BOSS(2.6)、挥铳圣像(1.5)。
9. **蹒跚羽兽的悬浮三态** —— 被眩晕/沉睡 → 坠落（不可阻挡）；被冻结/束缚 → 预坠落（不可阻挡）。
10. **不可阻挡** —— 没办法车（常驻）、BOSS 第二形态与重生形态、【倒地】期间。
11. **死亡返还费用** —— 没办法车死亡 +50 费。
12. **`lifePointReduce = 0`** —— 没办法车漏了不扣命。
13. **飞行（`motion = FLY`）** —— 挥铳圣像走唯一一条无人机路线。
14. **沉默 / 冻结 / 束缚 / 麻痹 / 恐惧 / 沉睡 / 浮空免疫（BOSS）** —— 主要是排除法。
15. **静态刚体 / 失衡免疫** —— 挥铳圣像、蹒跚羽兽初始模式（本关无推拉手段时影响为 0）。

**在当前只有「物理/法术伤害 + 阻挡 + 移速」的模拟器里，以下机制会显著影响结果：**

- **P3R/倒地/全场总攻击**：这是最大的缺口。当前模拟器把伤害算完就结束了，
  而实战里「打够 2000 点弱点伤害」才换来 15 秒眩晕 + 一次全队攻击力加成 + 一次全场真伤。
  缺了它，SR-EX-8 的难度会被**高估**（玩家拿不到那份 `15000+` 的真实伤害爆发）。
- **BOSS 的 18 万血与重生形态**：当前若按 level 0（15 万）或忽略重生，会低估 20% 血量 + 10 秒回血 + 一次全场 99% 真伤。
- **吓人路灯的法术免疫（RES 99 + P3R 归零）**：物理伤害有 5% 保底，法术伤害没有保底，
  但 P3R 的「免疫→归零」会让法术变成**真正的 0**，和「RES 99 只剩 1%」是两回事，差别在 12500 点量级。
- **沉默收音机的 1750 防御**：靠 5% 保底是能磨的，但真实耗时会被严重低估 —— 平 A 每下只有 `ATK×0.05`。
- **咆哮铳的炸膛增益**：会把全场敌人的有效血量与推进速度整体抬升一个档，
  在只有移速的模拟器里完全看不见（它连移速倍率都改了）。
- **蹒跚羽兽的远程 2.0 与溅射**：当前模拟器没有「敌人打高台」的能力，会低估我方站位约束。
- **没办法车的死亡返费 50**：费用曲线会差出一整次部署，属于时间轴级影响。
- **挥铳圣像的无弱点**：它把整条全场总攻击链路锁死，是「什么时候能爆发」的开关。

不受当前模拟器影响（可实现但本关无差别）：静态刚体、失衡免疫、对空限制、
元素损伤（本关无我方元素输出手段时）、嘲讽等级。

---

## 5. 附：数据获取命令备忘

```python
import sys; sys.path.insert(0, r"<仓库目录>")
from ak_tactic.gamedata import GameDataSource, EnemyLibrary, load_stage

src = GameDataSource()                      # 首选源 map.ark-nights.com（无 excel/）
lib = EnemyLibrary(source=src)              # 只暴露数值，天赋/技能全部丢弃
st  = load_stage("act54side_ex08")          # 39 只、8 种；BOSS 的 s.level == 1

# 天赋 / 技能只能读原始 JSON
raw = src.enemy_database()                  # {"enemies":[{"Key":..., "Value":[{"level":0,"enemyData":{...}}]}]}
ed  = {e["Key"]: e for e in raw["enemies"]}["enemy_1589_pppdth"]["Value"][1]["enemyData"]
ed["skills"]           # [{"prefabKey":"Skill_Revelation","priority":100,"cooldown":30.0,
                       #   "initCooldown":25.0,"spCost":0,"blackboard":[...]}]
ed["talentBlackboard"] # [{"key":"Mode_A.attack@power_atk_scale","value":3.5,"valueStr":null}, ...]
src.release("levels/enemydata/enemy_database.json")   # 大文件用完必须释放

# 图鉴（有中文名与 abilityList 描述文本）
hb = src.enemy_handbook()["enemyData"]["enemy_1589_pppdth"]["abilityList"]
lib.handbook_entry("enemy_1589_pppdth")     # 同上，走 EnemyLibrary 的缓存
lib.describe("enemy_10192_ppprpr")          # 单行人类可读摘要
```

要点：
- `GameDataSource` 的公开方法是 `fetch_json(rel)` / `enemy_database()` / `enemy_handbook()` /
  `level()` / `resolve_level()` / `release()`，**没有 `load()`**。
- 图鉴表 `excel/enemy_handbook_table.json` 只有 GitHub 镜像（`GITHUB_BASE`）有；本机
  `data/gamedata/excel/` 下已缓存一份，可直接读（1.8 MB，1754 条）。
- 原始 JSON 的值一律包一层 `{m_defined, m_value}`，`m_defined = false` 表示沿用低优先级档，需逐档合并。
- `lifePointReduce` / `rangeRadius` / `levelType` 挂在 `enemyData` 顶层，不在 `attributes` 下。
- 本版本 `enemyData` **没有 `talents` 字段**，天赋全部拍平在 `talentBlackboard`。
- prts.wiki 侧取文本：`https://prts.wiki/api.php?action=query&prop=revisions&rvslots=main&rvprop=content&format=json&titles=<敌人名>`
  （`?action=raw` 不可用；本机 `curl` 直连一律 403，用 `web_fetch` 可通）。
