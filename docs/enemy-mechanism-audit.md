# 敌人机制审计：第 0～10 章（逐章）

本文件答的是**博士交给的第 0～2 章那一问的扩展版**：「每章的敌人，有没有未建模的机制」。
判据落在 `tools/check_enemy_mech_go.py`（第 27 套，已进 `tools/check_go_all.py` 的 SUITE），
本文件是它 2026-09-24 那一跑**落盘的读数**。

## 〇 · 一句话（两条腿求差 ＋ 具名登记）

> **第 0～10 章 153 只敌人、229 个机制键里，Go 一处欠账都没有（真红 0）；
> 但它们整族落在「两台引擎共同的边界」上（228 个键）。**
> 真正的 Go 欠账在**活动侧**：全缓存 320 关里 **17 个键次（11 个键）**是
> 「Python 有落点、Go 只填不用」，**已全部具名登记**（第八节，逐条带出处）。

★ **「真红 0」与「17 条没修」必须同屏读**：登记**不是修复**。汇总行因此长这样：

```
结论：已消费 41 ／ 具名 unported 17（逐条见文档「具名 unported 登记」一节）／ 真红 0
      （另：共同边界 238 个键、仅 Go 0 个键、判不了 194 条 —— 均不计入 rc）
```

`!! MECH-UNPORTED-REGISTERED n=17 —— 登记 ≠ 已修复` 这一行也**每次都会打**，
免得下一个人把那个绿读成「都搬完了」。

★ 之所以能这么说，是因为判据是**两条腿**的（2026-09-24 父会话裁定后重挑）：
只量「Go 读不读」会把**两台引擎共同的边界**记成 Go 的欠账，而假红等于没有判据。

## 一 · 口径（先说清在量什么，再说数）

**数据与仪器**（三者全部现算，读数不写死）

* 敌人数据：`data/gamedata/map.ark-nights.com/levels/enemydata/enemy_database.json`
  —— 天赋黑板、敌方技能黑板、`enemyData.description` 都出自这一份。
* 图鉴数据：`data/enemydb.sqlite`（**只读打开**）—— prts 侧的 `enemy_level.talent`
  与 `enemy.ability`。
* 仪器：`rios-sim/*.go`（Go 消费面）与 `ak_tactic/gamedata/enemy.py` ＋
  `ak_tactic/battle/*.py`（Python 消费面）的**现读源码**，不跑任何二进制。
* 关卡清单：**第 0～10 章全部 141 个 base 关卡**（`main_00-01` … `main_10-15`；
  不含 `#f#` 四星档）。关卡到敌人的映射走 `load_stage(...).spawns`——
  与「敌人」那一套判据**同一条路**。

**判据：两条腿，五个状态**（细节见工具文件头）

| 状态 | 判据 | 进不进 rc |
|---|---|---|
| **已消费** | Go 有读取点 **且** Go 有行为落点 | 否 |
| **具名 unported** | 真红，但已在第 27 套的登记表里有出处（**登记 ≠ 已修复**） | 否 |
| **真红** | ¬Go消费 **且 Python 侧有落点**，**且未登记** | **是**（Go 的欠账） |
| **共同边界** | 两侧都没有落点 | 否（**登记**，逐条落盘） |
| **仅 Go** | Go 有落点而 Python 没有 | 否（登记） |
| **判不了** | 正文是自然语言、没有具名判据 | 否（逐条落盘，**不装作已查**） |

**两侧同构地现算**：

* **读取点**＝键的**字面串**出现在「填充侧」的**代码行**里
  （Go：`bbFloat/bbInt/bbValue(bb,"K")`、`bb["K"]`；Python：`ak_tactic/gamedata/enemy.py`
  的 `_bb_float(bb,"K")`、`bb.get("K")`）。
* **行为落点**＝下游字段在「行为侧」被读（Go：`rios-sim/*.go` 去掉 填充／规格／闸门；
  Python：`ak_tactic/battle/*.py`）。源字段与规格字段之间的改名（
  `v.RebornDelay = es.RebornDuration`）现算成同义名一起找——**不过这一层会造出假红**，
  实测 `RebornDuration` 在 `sim.go` 里一处都没有，真正被读的是规格侧的名字。
* **两条具名族**：重生族（`Reborn.`／`Reborning.`，后缀集从源码现算，含拼接）
  与相性族（`AffinityOf(bb,"P")` × `p3rSlots` 槽位）。族判定**连后缀一起看**：
  `Reborn.invincible` 与 `Reborn.reborn_duration` 同前缀不同命。
* **技能读取器**：`proseSkillAttacks`（Go）／`PROSE_SKILL_ATTACK`（Python）那张表里的
  `prefabKey`，它读的黑板键两侧都算消费。该表实测**只有 `Drink` 一项**。
* ★ 要害仍是那一条：**「读了黑板、填进字段、模拟里没人读」不算建模**。

⚠ **Python 面的盲区**（写在这里，不藏在注释里）：它看不见「同一机制换了个键名实现」，
那是**未核**、不是没建。输出里另印一列 `py_token`（键的机制名在 Python 代码行里
出现与否）**只当线索、不参与判定**（逐条列在第五节）。

**正文/图鉴那一面**逐条按三条具名判据判：

* `C1` 命中 `UNMODELLED_ENEMY_ABILITIES` 的 `py_tokens` **且该敌人在它的 `carriers` 里**
  ⇒ 具名登记；命中词元但不在载体里 ⇒ 判不了（不许把别人的登记记到它头上）。
* `C2` 命中 `unportedLines` 的线名 ⇒ 具名登记。
* `C3` 该敌人在 gamedata 侧**一个机制键都没有**而正文提到了机制 ⇒ `PROSE_NO_KEY`：
  **登记为共同边界**（两侧连字段都没有 ⇒ 闸门对它永远沉默）。
* 其余 ⇒ **判不了**（`PROSE_NO_CRITERION`）。**判不了不计入 rc**，但逐条落在这里。

**风味筛**：正文先过一遍 `MECH_KEYWORDS` 词表（工具内常量）。不命中的（
「野生的被感染生物。」这类）记为 `FLAVOR`，**不进判据**，但全文列在第七节供人复核。
词表**故意不收** `攻击力`／`防御力`／`造成`／`受到`／`伤害`／`范围`／`层` 这些泛词——
实测它们会把风味文案判成机制正文（「整合运动的近身作战人员，**以高攻击力见长**。」）。

**这一跑的身份**（现算，不接受手抄）

* 仪器：rios-sim（59 个 .go）source_sig=c3316c8be94936a4
* 数据：data\gamedata\map.ark-nights.com\levels\enemydata\enemy_database.json sha256(16)=00ccabf846b35486
* data\enemydb.sqlite sha256(16)=d73403e1b2fd23a2
* 取证范围：关卡**键** 141 个（＝不同关卡**内容** 141 份 × 难度与别名标签；清单由调用方给出）
* 本判据自己的结论行：`MECH-VERDICT red=0 unported=0 common=228 go=1 go_only=0 undecidable=179`
* 复现命令（原样）：`python tools\\check_enemy_mech_go.py <141 个 base 关卡 id> --md out/_mech_main.md`

## 二 · 逐章读数（第 0～10 章）

| 章 | 敌人只数 | 机制键 | 已消费 | 具名 unported | 真红 | 共同边界 | 仅 Go | 正文已登记 | 正文无键 | 正文判不了 | 风味跳过 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| main_00 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 9 |
| main_01 | 7 | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 4 | 9 |
| main_02 | 14 | 5 | 0 | 0 | 0 | 5 | 0 | 0 | 3 | 3 | 20 |
| main_03 | 13 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 4 | 9 | 12 |
| main_04 | 11 | 12 | 0 | 0 | 0 | 12 | 0 | 0 | 2 | 6 | 12 |
| main_05 | 14 | 8 | 0 | 0 | 0 | 8 | 0 | 0 | 5 | 13 | 14 |
| main_06 | 17 | 20 | 0 | 0 | 0 | 20 | 0 | 0 | 2 | 32 | 13 |
| main_07 | 19 | 17 | 0 | 0 | 0 | 17 | 0 | 0 | 4 | 16 | 32 |
| main_08 | 18 | 78 | 0 | 0 | 0 | 78 | 0 | 0 | 8 | 23 | 17 |
| main_09 | 13 | 38 | 0 | 0 | 0 | 38 | 0 | 0 | 0 | 27 | 11 |
| main_10 | 19 | 47 | 1 | 0 | 0 | 46 | 0 | 0 | 0 | 46 | 11 |

* 各列口径**互不可比**：`机制键` 是去重后的键数，五个状态列是各自占的去重键数
  （同一个键在一章里只算一次）；`正文**` 那几列是正文/图鉴条目的条数。
* **真红一列整列为 0**、**具名 unported 一列整列也为 0** —— 两者理由不同，见下。

### 零行使的三条线

判据里有一条硬规矩：**某一章里三条线哪一条是 0，就要明说并给理由**。

* **`真红` 在 11 章里全是 0，`具名 unported` 也全为 0**，理由是同一条：
  本章的键在 **Python 侧也一个落点都没有** ⇒ 它们是**共同边界**，不是 Go 的欠账。
  第 27 套登记表里那 11 条登记的载体全在**活动侧**（怀黍离的田鼷 / 祟 / 天桩一族），
  第 0～10 章一条都碰不到 —— 这一点**不是「都搬完了」**，是**这批敌人的键根本没进过那张表**。
* **`已消费` 只在 main_10 有 1 个键**：`Reborn.interval`（曼弗雷德）——
  它落在具名族里，下游 `RebornInterval`／`RebornSummons` 有行为落点（`sim.go:828`）。
* **`共同边界` 只在 main_00 为 0**：那 8 只敌人**一个机制键都没有**
  （天赋黑板空、无技能）⇒ 连共同边界都无从谈起，只剩正文那一条 `PROSE_NO_KEY`。

### 正文三栏

`正文已登记` 0 条、`正文无键` 29 条、`正文判不了` 179 条、`风味跳过` 160 条。
见第六、七节。

## 三 · 结构性结论（比逐章数字更要紧的那一条）

> **Go 的敌人机制层搬的是「天赋黑板」那一族；敌方技能那一族，两台引擎都基本没建。**

拆开说，三句都有现算依据：

1. **Go 侧读「敌人天赋黑板」的地方只有一处**：`rios-sim/enemy_derive.go:243` 的
   `bb := s.TalentBlackboard`，交给 `DeriveBlackboardFields()`。它只认四族键——
   机制前缀七个（`Passive.`／`DeathPassive.`／`AuraHit.`／`SpeedUp.`／
   `Passive_Hit.`／`PassiveM2.`／`CheckAwake.`）、重生两个拼法（`Reborn.`／`Reborning.`）、
   相性四前缀（`TotalAttack`／`Mode_A`／`Mode_B` × 三个槽位）、击杀费用 `Talent1.cost`。
   全仓 `TalentBlackboard` 的出现处只有 `enemy.go`（读文件/深拷）与 `enemy_derive.go`
   （当黑板用）——**没有第二处通用消费者**，也没有按敌人名字/ID 的特判。
2. **第 0～10 章的敌人一个都不落在这四族里**（`Reborn.` 除外）。于是他们那些
   `shield.*`／`strength.*`／`aura.*`／`halfhp.*`／`refracting.*`／`atkup.*`／
   `deathrattle.*` … **两侧都没有读取点**。
   **实测（本仓现跑，带正对照，避免「零命中」是查询没跑成）**：

   ```
   $ git grep -n --untracked "defup" -- ak_tactic/          # 御4 的「防御力 +300」
   （无输出）rc=1
   $ git grep -n --untracked "ArcticBlast" -- ak_tactic/    # 霜星的技能
   （无输出）rc=1
   $ git grep -n --untracked "Talent1.cost" -- ak_tactic/   # 正对照：已知有人读
   ak_tactic/gamedata/enemy.py:674:        self.kill_cost = int(bb.get("Talent1.cost") or 0)
   rc=0
   ```

   正对照命中 ⇒ 查询本身跑得成 ⇒ 上面两个 rc=1 是**真的零命中**，不是仪器没跑。
   ⇒ 228 个键是**共同边界**（两台引擎共同没建），**不是 Go 的欠账**。
3. **敌方技能那一族**：两侧各有一张通用读取器表（`proseSkillAttacks`／
   `PROSE_SKILL_ATTACK`），实测**都只有 `Drink` 一项**（怀黍离「玷 / 勿玷」的技能）。
   第 0～10 章的敌方技能（`ArcticBlast`／`C4`／`blink`／`lasso`／`SummonBallis` …）
   一个都不在表里 ⇒ 整族是**共同边界**。

**那 Go 的欠账在哪里**：在**活动侧**（怀黍离那一批）。全缓存 320 关一跑，
**17 个键次（11 个键）**，形状全是同一个——**Go 读了黑板、填进了 `EnemyStats`、
模拟里没人读**（连 `spawns.go` 都没把它们搬进 `EnemyUnit`），而 Python 侧有真落点：

* `AuraHit.hp_ratio`（进阻流阀范围立刻真伤）→ Python `battle/sim.py:1615`
* `SpeedUp.move_speed`／`duration`／`cooldown`（受击未被阻挡时加速）→ `sim.py:1306/1308/1309`
* `DeathPassive.cnt`／`token_key`（被击倒给可部署装置）→ `sim.py:1614/1613`
* `Passive_Hit.extra_value`／`other_cnt` → `sim.py:1629/1299`
* `PassiveM2.value`／`dhnzzh_clean_water.magic_resistance`／`.move_speed`
  → `sim.py:1641/1637/1638`

⇒ **2026-09-24 父会话裁定：走「具名登记」**（不修 Go、也不放宽判据），
11 条登记**逐条带出处**列在第八节。登记只改分类、**不改事实**：它们仍是**已知行为分歧**。

## 四 · 已消费的键（第 0～10 章）

| 章 | 敌人 | 键 | 下游字段 | Go 行为落点 |
|---|---|---|---|---|
| main_10 | 曼弗雷德 | `Reborn.interval` | RebornInterval | sim.go:828 |

## 五 · 共同边界（**两台引擎都没建**，登记、不计红）

这是本文件**最主要的一份清单**——博士问的「有没有未建模的机制」，
答案主要在这里。`Python 同名词根` 一列是**线索**（Python 代码行里出现过这个
机制名），用来提示「可能是换了键名的第二写法」；它**不参与判定**。

| 章 | 敌人 | 键 | 原因 | Python 同名词根（线索，不参与判定） |
|---|---|---|---|---|
| main_01 | W | `C4@atk_scale` | SKILL_KEY_NO_READER |  |
| main_01 | W | `C4@range_radius` | SKILL_KEY_NO_READER |  |
| main_01 | 弑君者 | `blink@dist` | SKILL_KEY_NO_READER |  |
| main_02 | 碎骨 | `atkup.atk` | NO_READ_SITE |  |
| main_02 | 碎骨 | `atkup.hp_ratio` | NO_READ_SITE |  |
| main_02 | 碎骨 | `defdown.def` | NO_READ_SITE |  |
| main_02 | 御4 | `defup.def` | NO_READ_SITE |  |
| main_02 | 御4 | `defup.range_radius` | NO_READ_SITE |  |
| main_03 | 技术侦察兵 | `antiinvi.range_radius` | NO_READ_SITE |  |
| main_04 | 霜星 | `ArcticBlast@atk_scale` | SKILL_KEY_NO_READER |  |
| main_04 | 霜星 | `ArcticBlast@attack_speed` | SKILL_KEY_NO_READER |  |
| main_04 | 霜星 | `ArcticBlast@duration` | SKILL_KEY_NO_READER |  |
| main_04 | 霜星 | `ArcticBlast@range_radius` | SKILL_KEY_NO_READER |  |
| main_04 | 霜星 | `IceShield@max_cnt` | SKILL_KEY_NO_READER |  |
| main_04 | 弑君者 | `blink@dist` | SKILL_KEY_NO_READER |  |
| main_04 | 高能源石虫 | `boom.atk_scale` | NO_READ_SITE |  |
| main_04 | 萨卡兹术师 | `lasso@atk_scale` | SKILL_KEY_NO_READER |  |
| main_04 | 萨卡兹术师 | `lasso@hit_duration` | SKILL_KEY_NO_READER |  |
| main_04 | 萨卡兹术师 | `lasso@range_radius` | SKILL_KEY_NO_READER |  |
| main_04 | 霜星 | `reborn.atk` | NO_READ_SITE | 是 |
| main_04 | 霜星 | `reborn.duration` | NO_READ_SITE | 是 |
| main_05 | 浮士德 | `CriticalHit@atk_scale` | SKILL_KEY_NO_READER |  |
| main_05 | 浮士德 | `SummonBallis@branch_id` | SKILL_KEY_NO_READER |  |
| main_05 | 寒霜 | `atkSpeedDown.attack_speed` | NO_READ_SITE |  |
| main_05 | 暴鸰 | `boomb@move_speed` | SKILL_KEY_OTHER_KEYSPACE |  |
| main_05 | 寒霜 | `defup.range_radius` | NO_READ_SITE |  |
| main_05 | 梅菲斯特 | `healaura.hp_recovery_per_sec` | NO_READ_SITE |  |
| main_05 | 浮士德 | `invincible.duration` | NO_READ_SITE | 是 |
| main_05 | 粉碎攻坚手 | `stuncombat@stun` | SKILL_KEY_NO_READER |  |
| main_06 | 霜星，“冬痕” | `IceBurst@atk_scale` | SKILL_KEY_NO_READER |  |
| main_06 | 霜星，“冬痕” | `IceBurst@freeze` | SKILL_KEY_OTHER_KEYSPACE |  |
| main_06 | 霜星，“冬痕” | `IceBurst@frstar2_s.atk_scale` | SKILL_KEY_NO_READER |  |
| main_06 | 霜星，“冬痕” | `IceBurst[Reborn]@atk_scale` | SKILL_KEY_NO_READER |  |
| main_06 | 霜星，“冬痕” | `IceBurst[Reborn]@freeze` | SKILL_KEY_OTHER_KEYSPACE |  |
| main_06 | 霜星，“冬痕” | `IceBurst[Reborn]@frstar2_s.atk_scale` | SKILL_KEY_NO_READER |  |
| main_06 | 霜星，“冬痕” | `IceShield@max_cnt` | SKILL_KEY_NO_READER |  |
| main_06 | 霜星，“冬痕” | `IceShield[Reborn]@max_cnt` | SKILL_KEY_NO_READER |  |
| main_06 | 霜星，“冬痕” | `SummonFrosts@branch_id` | SKILL_KEY_NO_READER |  |
| main_06 | 雪怪小队 | `atkup.atk_scale` | NO_READ_SITE |  |
| main_06 | 霜星，“冬痕” | `attackfreeze.freeze` | NO_READ_SITE |  |
| main_06 | 霜星S | `blood.damage` | NO_READ_SITE |  |
| main_06 | 虚幻 | `bomb@freeze` | SKILL_KEY_OTHER_KEYSPACE | 是 |
| main_06 | 冰爆源石虫 | `boom.atk_scale` | NO_READ_SITE |  |
| main_06 | 冰爆源石虫 | `boom.freeze` | NO_READ_SITE |  |
| main_06 | 雪怪术师 | `coldattack@freeze` | SKILL_KEY_OTHER_KEYSPACE |  |
| main_06 | 狂暴宿主士兵 | `periodic_damage.damage` | NO_READ_SITE |  |
| main_06 | 霜星，“冬痕” | `reborn.atk` | NO_READ_SITE | 是 |
| main_06 | 霜星，“冬痕” | `reborn.duration` | NO_READ_SITE | 是 |
| main_06 | 霜星，“冬痕” | `reborn.reborn_invincible.duration` | NO_READ_SITE | 是 |
| main_07 | 游击队萨卡兹术师 | `Immo@atk_scale` | SKILL_KEY_NO_READER |  |
| main_07 | 游击队萨卡兹术师 | `Immo[Rage]@atk_scale` | SKILL_KEY_NO_READER |  |
| main_07 | 爱国者 | `immo_trigger[rage].atk` | NO_READ_SITE |  |
| main_07 | 爱国者 | `immo_trigger[rage].base_attack_time` | NO_READ_SITE |  |
| main_07 | 爱国者 | `immo_trigger[rage].def` | NO_READ_SITE |  |
| main_07 | 爱国者 | `immo_trigger[rage].interval` | NO_READ_SITE |  |
| main_07 | 爱国者 | `immo_trigger[rage].move_speed` | NO_READ_SITE |  |
| main_07 | 爱国者 | `reborn.duration` | NO_READ_SITE | 是 |
| main_07 | 爱国者 | `reborn.patrt_t_state_2[reborn_invincible].duration` | NO_READ_SITE | 是 |
| main_07 | 爱国者 | `shield.atk` | NO_READ_SITE | 是 |
| main_07 | 爱国者 | `shield.def` | NO_READ_SITE | 是 |
| main_07 | 爱国者 | `shield.magic_resistance` | NO_READ_SITE | 是 |
| main_07 | 游击队传令兵 | `strength.atk` | NO_READ_SITE |  |
| main_07 | 游击队迫击炮兵 | `strength.attack_speed` | NO_READ_SITE |  |
| main_07 | 游击队传令兵 | `strength.def` | NO_READ_SITE |  |
| main_07 | 游击队战士 | `strength.move_speed` | NO_READ_SITE |  |
| main_07 | 游击队盾卫 | `taunt.taunt_level` | NO_READ_SITE | 是 |
| main_08 | “皇帝的利刃” | `BringDown@def` | SKILL_KEY_OTHER_KEYSPACE |  |
| main_08 | “皇帝的利刃” | `BringDown@magic_resistance` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DanceFire@atk_scale` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DanceFire@range_radius` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DanceFire[Half]@atk_scale` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DanceFire[Half]@range_radius` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DragonFire@dragon_fire.addOnDamage` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DragonFire@dragon_fire.addOnDuration` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DragonFire@dragon_fire.baseDamage` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DragonFire@dragon_fire.duration` | SKILL_KEY_NO_READER |  |
| main_08 | 斗士塔露拉 | `DragonFire@range_radius` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `DragonFireExplode@atk_scale` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `DragonFireExplode@dragon_fire.addOnDamage` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `DragonFireExplode@dragon_fire.addOnDuration` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `DragonFireExplode@dragon_fire.baseDamage` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `DragonFireExplode@dragon_fire.duration` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DragonFire[Half]@dragon_fire.addOnDamage` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DragonFire[Half]@dragon_fire.addOnDuration` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DragonFire[Half]@dragon_fire.baseDamage` | SKILL_KEY_NO_READER |  |
| main_08 | 塔露拉 | `DragonFire[Half]@dragon_fire.duration` | SKILL_KEY_NO_READER |  |
| main_08 | 斗士塔露拉 | `DragonFire[Half]@range_radius` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `Ignite@dragon_fire.addOnDamage` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `Ignite@dragon_fire.addOnDuration` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `Ignite@dragon_fire.baseDamage` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `Ignite@dragon_fire.duration` | SKILL_KEY_NO_READER |  |
| main_08 | 梅菲斯特，“歌者” | `Poison@damage` | SKILL_KEY_NO_READER |  |
| main_08 | 梅菲斯特，“歌者” | `Poison@max_stack_cnt` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `ScreenAttack@atk_scale` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `ScreenAttack@duration` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `ScreenAttack@interval` | SKILL_KEY_OTHER_KEYSPACE |  |
| main_08 | “不死的黑蛇” | `ScreenAttack@invincible` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `ScreenAttack@trig_cnt` | SKILL_KEY_NO_READER |  |
| main_08 | “不死的黑蛇” | `SummonFlame@branch_id` | SKILL_KEY_NO_READER |  |
| main_08 | 帝国前锋精锐 | `atkup.atk` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `blink@cooldown_0` | SKILL_KEY_NO_READER |  |
| main_08 | 梅菲斯特，“歌者” | `blink@cooldown_1` | SKILL_KEY_NO_READER |  |
| main_08 | 梅菲斯特，“歌者” | `blink@cooldown_2` | SKILL_KEY_NO_READER |  |
| main_08 | 梅菲斯特，“歌者” | `blink@cooldown_3` | SKILL_KEY_NO_READER |  |
| main_08 | 梅菲斯特，“歌者” | `blink@cooldown_4` | SKILL_KEY_NO_READER |  |
| main_08 | 梅菲斯特，“歌者” | `blink@cooldown_5` | SKILL_KEY_NO_READER |  |
| main_08 | 梅菲斯特，“歌者” | `blink@delay` | SKILL_KEY_NO_READER |  |
| main_08 | 乌萨斯平民 | `dead.value` | NO_READ_SITE |  |
| main_08 | “不死的黑蛇” | `fire.attack@dragon_fire.addOnDamage` | NO_READ_SITE | 是 |
| main_08 | “不死的黑蛇” | `fire.attack@dragon_fire.addOnDuration` | NO_READ_SITE | 是 |
| main_08 | “不死的黑蛇” | `fire.attack@dragon_fire.baseDamage` | NO_READ_SITE | 是 |
| main_08 | “不死的黑蛇” | `fire.attack@dragon_fire.duration` | NO_READ_SITE | 是 |
| main_08 | 塔露拉 | `halfhp.def` | NO_READ_SITE |  |
| main_08 | 塔露拉 | `halfhp.hp_ratio` | NO_READ_SITE |  |
| main_08 | 塔露拉 | `halfhp.magic_resistance` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `healaura.hp_recovery_per_sec` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `poison_trigger_giver.hp_ratio` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `poison_trigger_giver.smephi_poison_trigger.duration` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `poison_trigger_giver.smephi_poison_trigger.interval` | NO_READ_SITE |  |
| main_08 | “不死的黑蛇” | `protect.bsnake_t[protect].damage_resistance` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `rage_aura.atk` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `rage_aura.attack_speed` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `rage_aura.bgm` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `rage_aura.damage` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `rage_aura_state_3.atk` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `rage_aura_state_3.attack_speed` | NO_READ_SITE |  |
| main_08 | 梅菲斯特，“歌者” | `rage_aura_state_3.damage` | NO_READ_SITE |  |
| main_08 | “不死的黑蛇” | `reborn.atk` | NO_READ_SITE | 是 |
| main_08 | “不死的黑蛇” | `reborn.bgm` | NO_READ_SITE | 是 |
| main_08 | “不死的黑蛇” | `reborn.bsnake_t[protect].damage_resistance` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `reborn.duration` | NO_READ_SITE | 是 |
| main_08 | “不死的黑蛇” | `reborn.max_hp` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `reborn.min_hp_ratio` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `reborn.smephi_heal[sheild].value` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `reborn.smephi_suicide_after_buff.duration` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `reborn.smephi_t[poison].hp_ratio` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `reborn.smephi_t[poison].smephi_poison_trigger.duration` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `reborn.smephi_t[poison].smephi_poison_trigger.interval` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `reborn.smephi_t_state_2[reborn_invincible].duration` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `reborn.smephi_t_state_3[reborn].atk` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `shield.def` | NO_READ_SITE | 是 |
| main_08 | 梅菲斯特，“歌者” | `shield.magic_resistance` | NO_READ_SITE | 是 |
| main_08 | 萨卡兹宿主百夫长 | `vampire.attack@max_target` | NO_READ_SITE |  |
| main_08 | 萨卡兹宿主百夫长 | `vampire.heal_scale` | NO_READ_SITE |  |
| main_09 | 深池焚毁者 | `DeadBoom@atk_scale` | SKILL_KEY_NO_READER |  |
| main_09 | 深池焚毁者 | `Flame@atk_scale` | SKILL_KEY_NO_READER |  |
| main_09 | 深池焚毁者 | `Flame@duspfr_flame[cd].cooldown` | SKILL_KEY_NO_READER |  |
| main_09 | 深池焚毁者 | `Flame@duspfr_flame[cd].duration` | SKILL_KEY_NO_READER |  |
| main_09 | 深池焚毁者 | `Flame@duspfr_flame[cd].interval` | SKILL_KEY_NO_READER |  |
| main_09 | 深池焚毁者 | `Flame@ep_damage_ratio` | SKILL_KEY_NO_READER |  |
| main_09 | 深池焚毁者 | `Flame@hit_interval` | SKILL_KEY_NO_READER |  |
| main_09 | 蔓德拉 | `PetrifiedRay@atk_scale` | SKILL_KEY_NO_READER |  |
| main_09 | 蔓德拉 | `PetrifiedRay@attack_speed` | SKILL_KEY_NO_READER |  |
| main_09 | 蔓德拉 | `PetrifiedRay@hit_interval` | SKILL_KEY_NO_READER |  |
| main_09 | 蔓德拉 | `PetrifiedRay@mandra_ray[cd].cooldown` | SKILL_KEY_NO_READER |  |
| main_09 | 蔓德拉 | `PetrifiedRay@mandra_ray[cd].duration` | SKILL_KEY_NO_READER |  |
| main_09 | 蔓德拉 | `PetrifiedRay@mandra_ray[cd].interval` | SKILL_KEY_NO_READER |  |
| main_09 | 蔓德拉 | `PetrifiedRay@range_radius` | SKILL_KEY_NO_READER |  |
| main_09 | 蔓德拉 | `ReSummonStoneSkin.duration` | NO_READ_SITE |  |
| main_09 | 蔓德拉 | `ReSummonStoneSkin.hp_ratio_offset` | NO_READ_SITE |  |
| main_09 | 蔓德拉 | `Reborn.branch_id` | SUFFIX_NOT_READ | 是 |
| main_09 | 蔓德拉 | `Reborn.duration` | SUFFIX_NOT_READ | 是 |
| main_09 | 蔓德拉 | `Reborn.mandra_p2_invinsible.duration` | SUFFIX_NOT_READ | 是 |
| main_09 | 蔓德拉 | `Reborn.mandra_ray_p2[cd]` | SUFFIX_NOT_READ | 是 |
| main_09 | 蔓德拉 | `Reborn.summon_dupilr_p2[cd]` | SUFFIX_NOT_READ | 是 |
| main_09 | 蔓德拉 | `StoneSkin.damage_resistance` | NO_READ_SITE |  |
| main_09 | 蔓德拉 | `StoneSkin_2.atk_scale` | NO_READ_SITE |  |
| main_09 | 蔓德拉 | `StoneSkin_2.interval` | NO_READ_SITE |  |
| main_09 | 蔓德拉 | `StoneSkin_2.range_radius` | NO_READ_SITE |  |
| main_09 | 深池塑能术师 | `SummonFireBall2@cnt` | SKILL_KEY_NO_READER |  |
| main_09 | 深池塑能术师 | `SummonFireBall2@enemy_key` | SKILL_KEY_NO_READER |  |
| main_09 | 深池塑能术师 | `SummonFireBall@cnt` | SKILL_KEY_NO_READER |  |
| main_09 | 深池塑能术师 | `SummonFireBall@enemy_key` | SKILL_KEY_NO_READER |  |
| main_09 | 深池方阵步兵 | `auraDefup.def` | NO_READ_SITE |  |
| main_09 | 深池侦察犬 | `refracting.magic_resistance` | NO_READ_SITE |  |
| main_09 | 守墓石像 | `stone.def` | NO_READ_SITE |  |
| main_09 | 守墓石像 | `stone.duration` | NO_READ_SITE |  |
| main_09 | 守墓石像 | `stone.magic_resistance` | NO_READ_SITE |  |
| main_09 | 深池伙友卫队 | `traitAbility.attack_speed` | NO_READ_SITE |  |
| main_09 | 深池伙友影刃 | `traitAbility.base_attack_time` | NO_READ_SITE |  |
| main_09 | 深池伙友卫队 | `traitAbility.range_radius` | NO_READ_SITE |  |
| main_09 | 深池伙友卫队 | `traitAbility.taunt_level` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_common.attack@attack_speed` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_common.attack@duration` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_common.attack@max_stack_cnt` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_rage@atk_scale` | SKILL_KEY_NO_READER |  |
| main_10 | 曼弗雷德 | `Funnel_rage_charge.sp` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_s1.attack@atk_scale` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_s1.attack@ep_damage_ratio` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_s1_charge.sp` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_s2.atk_scale` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_s2.attack@ep_damage_ratio` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_s2.ep_damage_ratio` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_s2.times` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Funnel_s2_charge.sp` | NO_READ_SITE |  |
| main_10 | 曼弗雷德 | `Reborn.duration` | SUFFIX_NOT_READ | 是 |
| main_10 | 曼弗雷德 | `Reborn.invincible` | SUFFIX_NOT_READ | 是 |
| main_10 | 曼弗雷德 | `Shield.disable_duration` | NO_READ_SITE | 是 |
| main_10 | 曼弗雷德 | `Shield.prob` | NO_READ_SITE | 是 |
| main_10 | 曼弗雷德 | `Shield[disable].stun` | NO_READ_SITE |  |
| main_10 | 萨卡兹子裔集恨者 | `aura.atk` | NO_READ_SITE | 是 |
| main_10 | 曼弗雷德 | `aura.atk_scale` | NO_READ_SITE | 是 |
| main_10 | 萨卡兹子裔改装补给车 | `aura.enemy_dsuply_2_t[attr_buff].atk` | NO_READ_SITE | 是 |
| main_10 | 萨卡兹子裔改装补给车 | `aura.enemy_dsuply_2_t[attr_buff].max_valid_stack_cnt` | NO_READ_SITE | 是 |
| main_10 | 萨卡兹子裔补给车 | `aura.enemy_dsuply_t[attr_buff].atk` | NO_READ_SITE | 是 |
| main_10 | 萨卡兹子裔补给车 | `aura.enemy_dsuply_t[attr_buff].max_valid_stack_cnt` | NO_READ_SITE | 是 |
| main_10 | 萨卡兹子裔补给车 | `aura.ep_damage_ratio` | NO_READ_SITE | 是 |
| main_10 | 曼弗雷德 | `aura.interval` | NO_READ_SITE | 是 |
| main_10 | 曼弗雷德 | `aura.isenabled` | NO_READ_SITE | 是 |
| main_10 | 萨卡兹子裔集恨者 | `aura.max_valid_stack_cnt` | NO_READ_SITE | 是 |
| main_10 | 曼弗雷德 | `aura.range_radius` | NO_READ_SITE | 是 |
| main_10 | 大君之触 | `buff_to_blocker.block_cnt` | NO_READ_SITE |  |
| main_10 | 大君之触 | `buff_to_blocker.max_valid_stack_cnt` | NO_READ_SITE |  |
| main_10 | 萨卡兹征用工程无人机 | `charge.sp` | NO_READ_SITE | 是 |
| main_10 | 萨卡兹子裔工匠 | `charge_gunctrl@enemy_dmech_charge[sp_reduce].sp` | SKILL_KEY_NO_READER |  |
| main_10 | 萨卡兹子裔工匠 | `charge_gunctrl@hit_duration` | SKILL_KEY_NO_READER |  |
| main_10 | 萨卡兹子裔工匠 | `charge_gunctrl@interval` | SKILL_KEY_OTHER_KEYSPACE |  |
| main_10 | 萨卡兹子裔工匠 | `charge_gunctrl@sp` | SKILL_KEY_OTHER_KEYSPACE |  |
| main_10 | 萨卡兹子裔战士 | `deathrattle.delay` | NO_READ_SITE |  |
| main_10 | 萨卡兹子裔战士 | `deathrattle.enemy_key` | NO_READ_SITE |  |
| main_10 | 大君之触 | `dmg_res.damage_resistance` | NO_READ_SITE |  |
| main_10 | 萨卡兹子裔链术师 | `epdamage.attack@chain.atk_scale` | NO_READ_SITE |  |
| main_10 | 萨卡兹子裔链术师 | `epdamage.attack@ep_damage_ratio` | NO_READ_SITE |  |
| main_10 | 萨卡兹子裔链术师 | `epdamage.attack@max_target` | NO_READ_SITE |  |
| main_10 | 萨卡兹子裔链术师 | `epdamage.attack@projectile_range` | NO_READ_SITE |  |
| main_10 | 萨卡兹征用工程无人机 | `periodic_damage.damage` | NO_READ_SITE |  |
| main_10 | 深池侦察队长 | `refracting.magic_resistance` | NO_READ_SITE |  |
| main_10 | 渴血的子裔 | `vampire.heal_scale` | NO_READ_SITE |  |

## 六 · 正文级（具名登记与「连字段都没有」）

`PROSE_NO_KEY` 的判据：该敌人在 gamedata 侧**一个机制键都没有**，而正文提到了机制。
这正是「闸门永远沉默」的形状——字段表里连一个能非零的字段都没有。
它登记为**共同边界**（不是 Go 的欠账），但它是**两台引擎共同的洞**。

| 章 | 敌人 | 来源 | 判定 | 原因 | 正文 |
|---|---|---|---|---|---|
| main_00 | 妖怪 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | {{特殊机制/静态刚体}}，不进行普通攻击 |
| main_02 | 弩手 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | {{特殊机制/被阻挡时使用不同攻击}}：<br>①被阻挡时进行近战途径攻击<br>②未被阻挡时进行远程途径攻击，不会攻击飞行单位<br>基础攻击速度为0（※攻击速度的[[游戏数据基础#属性基本公式/数值下限]]为20） |
| main_02 | 弩手组长 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | {{特殊机制/被阻挡时使用不同攻击}}：<br>①被阻挡时进行近战途径攻击<br>②未被阻挡时进行远程途径攻击，不会攻击飞行单位 |
| main_02 | 妖怪MKII | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | {{特殊机制/静态刚体}}，普通攻击造成近战途径伤害 |
| main_03 | 潜伏者 | gamedata.description | NOKEY | PROSE_NO_KEY | 整合运动的特殊作战人员，<@eb.key>在被阻挡前无法被攻击</>。 |
| main_03 | 隐形弩手 | gamedata.description | NOKEY | PROSE_NO_KEY | 射击作战人员，<@eb.key>在被阻挡前无法被攻击</>。 |
| main_03 | 隐形术师 | gamedata.description | NOKEY | PROSE_NO_KEY | 法术作战人员，<@eb.key>在被阻挡前无法被攻击</>。 |
| main_03 | 炮手 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | 不会攻击飞行单位<br>普通攻击向目标发射一枚炮弹，对目标所在地块及周围八格{{popup/range/x-4}}内的所有我方单位造成伤害（此弹道会强制击中主目标，可对空，碰撞无视{{异常效果/迷彩}}）<br>※对主目标造成物理普通伤害， |
| main_04 | 萨卡兹大剑手 | gamedata.description | NOKEY | PROSE_NO_KEY | 萨卡兹雇佣兵，拥有<@eb.key>较高攻击力和较高法术抗性</>。 |
| main_04 | 萨卡兹狙击手 | gamedata.description | NOKEY | PROSE_NO_KEY | 萨卡兹雇佣兵，拥有<@eb.key>较高攻击力和较高法术抗性</>，且可以进行<@eb.key>远距离物理射击</>。 |
| main_05 | 破阵者 | gamedata.description | NOKEY | PROSE_NO_KEY | 训练有素的敌方冲锋单位，移动速度极快且<@eb.key>攻击能力</>比一般单位略高。 |
| main_05 | 破阵者组长 | gamedata.description | NOKEY | PROSE_NO_KEY | 训练有素的敌方高级冲锋单位，移动速度极快且<@eb.key>攻击能力</>比一般单位略高。 |
| main_05 | 法术大师A1 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | {{特殊机制/静态刚体}} |
| main_05 | 宿主士兵 | prts.enemy.ability | NOKEY | PROSE_NO_KEY | ·能够自然回复生命 |
| main_05 | 宿主拾荒者 | prts.enemy.ability | NOKEY | PROSE_NO_KEY | ·能够自然回复生命 |
| main_06 | 宿主士兵组长 | prts.enemy.ability | NOKEY | PROSE_NO_KEY | ·能够自然回复生命 |
| main_06 | 宿主重装士兵 | prts.enemy.ability | NOKEY | PROSE_NO_KEY | ·能够自然回复生命 |
| main_07 | 宿主流浪者 | prts.enemy.ability | NOKEY | PROSE_NO_KEY | ·能够自然回复生命 |
| main_07 | 游击队萨卡兹战士 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | [[源石祭坛/免疫脉冲波]]，受[[源石祭坛]]/[[爱国者的源石祭坛]]的技能【脉冲波】影响后可进入{{color/#FF4F0B/强化模式}}<br>{{color/#FF4F0B/'''强化模式'''}}：普通攻击造成法术伤害 |
| main_07 | 游击队萨卡兹战士组长 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | [[源石祭坛/免疫脉冲波]]，受[[源石祭坛]]/[[爱国者的源石祭坛]]的技能【脉冲波】影响后可进入{{color/#FF4F0B/强化模式}}<br>{{color/#FF4F0B/'''强化模式'''}}：普通攻击造成法术伤害 |
| main_07 | 雇佣军萨卡兹战士 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | [[源石祭坛/免疫脉冲波]]，受[[源石祭坛]]/[[爱国者的源石祭坛]]的技能【脉冲波】影响后可进入{{color/#FF4F0B/强化模式}}<br>{{color/#FF4F0B/'''强化模式'''}}：普通攻击造成法术伤害 |
| main_08 | 感染者纠察官 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | 可对半径1.2范围内的[[乌萨斯平民]]/[[斗士塔露拉]]/[[矿工游击队]]进行普通攻击（不可对空） |
| main_08 | 感染者高级纠察官 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | 可对半径1.2范围内的[[乌萨斯平民]]/[[斗士塔露拉]]/[[矿工游击队]]进行普通攻击（不可对空） |
| main_08 | 乌萨斯突袭弩手 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | 不会攻击飞行单位<br>目标嘲讽等级相同时，远程攻击优先攻击[[乌萨斯平民]]/[[斗士塔露拉]]/[[矿工游击队]] |
| main_08 | 乌萨斯着铠术师 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | 不会攻击飞行单位<br>目标嘲讽等级相同时，远程攻击优先攻击[[乌萨斯平民]]/[[斗士塔露拉]]/[[矿工游击队]] |
| main_08 | 乌萨斯突击者 | gamedata.description | NOKEY | PROSE_NO_KEY | <@eb.key>阻挡能力大于等于2</>的作战人员可以阻止。可使用<@eb.key>远程武器</>攻击乌萨斯平民与斗士塔露拉 |
| main_08 | 乌萨斯突击者 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | 占用2个阻挡数<br>可对半径1.2范围内的[[乌萨斯平民]]/[[斗士塔露拉]]/[[矿工游击队]]进行普通攻击（不可对空） |
| main_08 | 帝国炮火先兆者 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | {{特殊机制/静态刚体}}，普通攻击向目标所在位置发射一枚于3秒后命中的弹道，弹道对半径1.2范围内的所有我方单位造成攻击力100%的无来源物理伤害（此弹道不会强制击中主目标，碰撞无视{{异常效果/迷彩}}）<br>目标嘲讽等级相同时，远程 |
| main_08 | 帝国炮火中枢先兆者 | prts.enemy_level.talent | NOKEY | PROSE_NO_KEY | {{特殊机制/静态刚体}}，普通攻击向目标所在位置发射一枚于3秒后命中的弹道，弹道对半径1.2范围内的所有我方单位造成攻击力100%的无来源物理伤害（此弹道不会强制击中主目标，碰撞无视{{异常效果/迷彩}}）<br>目标嘲讽等级相同时，远程 |

## 七 · 判不了 与 风味跳过

### 7.1 判不了（**判不了 ≠ 没问题**）

这些条目的机制确实写在正文里，但本工具**没有**把中文机制名映射到键名的具名判据，
所以既不判绿也不判红。它们**逐条留在这里**，供人接手。

| 章 | 敌人 | 来源 | 原因 | 正文 |
|---|---|---|---|---|
| main_01 | 弑君者 | gamedata.description | PROSE_NO_CRITERION | 整合运动干部，从事敌后活动与突袭暗杀行动，会敏捷地<@eb.key>穿过阻挡其的单位</>。 |
| main_01 | 弑君者 | prts.enemy.ability | PROSE_NO_CRITERION | ※被阻挡时可以快速移动至其身后 |
| main_01 | W | prts.enemy_level.talent | PROSE_NO_CRITERION | 普通攻击不会攻击飞行单位<br>生命值首次低于'''50%'''时，【C4】的冷却时间立刻归0 |
| main_01 | W | prts.enemy.ability | PROSE_NO_CRITERION | ·会使用爆破物，能对我方单位造成大量物理伤害<br>·生命值降至一半以下时炸药包的使用数量增加 |
| main_02 | 御4 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{特殊机制/静态刚体}}，不进行普通攻击<br>使2.5半径范围内实体类型为默认类或装置类的其他敌方单位防御力+300（不可叠加，可被沉默） |
| main_02 | 碎骨 | prts.enemy_level.talent | PROSE_NO_CRITERION | 不会攻击飞行单位<br>生命值低于'''50%'''时，攻击力+'''50%'''<br>未被阻挡时发射'''榴弹'''对目标及其周围八格的我方单位造成相当于攻击力'''26%'''的物理伤害，并令其在'''5'''秒内防御力下降'''{{ |
| main_02 | 碎骨 | prts.enemy.ability | PROSE_NO_CRITERION | ·未被阻挡时会发射榴弹，击中目标及其周围单位使其防御力在短时间内大幅度下降<br>·生命值降至一半以下时攻击力大幅度提升 |
| main_03 | 潜伏者 | prts.enemy_level.talent | PROSE_TOKEN_NOT_CARRIER | {{术语/ba.invisible/隐匿}} |
| main_03 | 潜伏者 | prts.enemy.ability | PROSE_TOKEN_NOT_CARRIER | ·{{术语/ba.invisible/隐匿}} |
| main_03 | 隐形弩手 | prts.enemy_level.talent | PROSE_TOKEN_NOT_CARRIER | {{术语/ba.invisible/隐匿}}<br>被阻挡时进行近战途径攻击<br>未被阻挡时进行远程途径攻击，不会攻击飞行单位 |
| main_03 | 隐形弩手 | prts.enemy.ability | PROSE_TOKEN_NOT_CARRIER | ·{{术语/ba.invisible/隐匿}} |
| main_03 | 技术侦察兵 | gamedata.description | PROSE_TOKEN_NOT_CARRIER | 技术作战人员，会使周围我方的<@eb.key>隐匿效果失效</>。 |
| main_03 | 技术侦察兵 | prts.enemy_level.talent | PROSE_TOKEN_NOT_CARRIER | {{术语/ba.invisible/隐匿}}<br>自身半径3.3范围内所有实体类型为默认类或装置类的我方单位获得{{异常效果/隐匿/免疫}}（无视无法选择、无视迷彩） |
| main_03 | 技术侦察兵 | prts.enemy.ability | PROSE_TOKEN_NOT_CARRIER | ·使周围我方单位的{{术语/ba.invisible/隐匿}}效果失效 |
| main_03 | 隐形术师 | prts.enemy_level.talent | PROSE_TOKEN_NOT_CARRIER | {{术语/ba.invisible/隐匿}}，不会攻击飞行单位 |
| main_03 | 隐形术师 | prts.enemy.ability | PROSE_TOKEN_NOT_CARRIER | ·{{术语/ba.invisible/隐匿}} |
| main_04 | 高能源石虫 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{特殊机制/死亡爆炸}}（爆炸半径1.25，延迟1秒，爆炸时来源无效，造成攻击力400%的无途径物理溅射伤害，无视{{异常效果/迷彩}}，不可对空） |
| main_04 | 萨卡兹术师 | gamedata.description | PROSE_NO_CRITERION | 拥有<@eb.key>较高攻击力和法术抗性</>。会使用<@eb.key>远距离法术攻击</>，且能够使用<@eb.key>禁锢我方单位</>的枷锁。 |
| main_04 | 弑君者 | gamedata.description | PROSE_NO_CRITERION | 整合运动干部，从事敌后活动与突袭暗杀行动，会敏捷地<@eb.key>穿过阻挡其的单位</>。 |
| main_04 | 弑君者 | prts.enemy.ability | PROSE_NO_CRITERION | ※被阻挡时可以快速移动至其身后 |
| main_04 | 霜星 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{异常效果/沉睡/免疫}}，普通攻击不会攻击飞行单位<br>首次被击倒后重生，重生持续5s，恢复100%生命值<br>重生后攻击力+50%，失去{{异常效果/沉睡/免疫}} |
| main_04 | 霜星 | prts.enemy.ability | PROSE_NO_CRITERION | ·常使用冰环法术，能对周围的我方单位造成大量法术伤害，并在数秒内降低击中目标的攻击速度<br>·会使用法术冻结地面，使其永久无法被部署单位<br>·首次死亡后重生，重生后攻击力提升 |
| main_05 | 暴鸰 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{特殊机制/静态刚体}}，不进行普通攻击 |
| main_05 | 暴鸰 | prts.enemy.ability | PROSE_NO_CRITERION | ·飞行单位<br>·可以投掷炸弹造成群体物理伤害<br>·投掷之后移动速度大幅度提升 |
| main_05 | 暴鸰·G | prts.enemy_level.talent | PROSE_NO_CRITERION | {{特殊机制/静态刚体}}，不进行普通攻击 |
| main_05 | 暴鸰·G | prts.enemy.ability | PROSE_NO_CRITERION | ·飞行单位<br>·可以投掷炸弹造成群体物理伤害<br>·投掷之后移动速度大幅度提升 |
| main_05 | 寒霜 | gamedata.description | PROSE_NO_CRITERION | <@eb.key>【飞行单位】</>防御力较高，会使周围我方单位的<@eb.key>攻击速度</>会大幅度削减。 |
| main_05 | 寒霜 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{特殊机制/静态刚体}}，不进行普通攻击<br>使2.5半径范围内的所有我方单位攻击速度-50%（不可叠加；可被沉默） |
| main_05 | 寒霜 | prts.enemy.ability | PROSE_NO_CRITERION | ·飞行单位<br>※周围的我方单位的攻击速度大幅度降低 |
| main_05 | 梅菲斯特 | gamedata.description | PROSE_NO_CRITERION | 整合运动干部，能同时治疗至多<@eb.key>3名</>敌人，并使全场宿主单位的自然生命回复速度加倍。 |
| main_05 | 梅菲斯特 | prts.enemy_level.talent | PROSE_NO_CRITERION | 普通攻击为治疗，可治疗生命值未满的敌方单位，最大目标数为3，治疗索敌不受阻挡影响<br>在场时令所有敌方单位的[[数值范围/生命回复速度]]+100% |
| main_05 | 梅菲斯特 | prts.enemy.ability | PROSE_NO_CRITERION | ·全场的敌方单位的自然生命回复速度加倍<br>·普通攻击能够同时治疗3名敌方单位 |
| main_05 | 浮士德 | gamedata.description | PROSE_NO_CRITERION | 整合运动干部，<@eb.key>无法被阻挡</>，能进行超远距离的物理攻击，并且能够启动场地中隐藏的<@eb.key>弩炮台</>。 |
| main_05 | 浮士德 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{异常效果/不可阻挡}}、{{异常效果/沉睡/免疫}}，普通攻击不会攻击飞行单位<br>出场时获得{{变动数值/120s/-}}{{异常效果/无敌}} |
| main_05 | 浮士德 | prts.enemy.ability | PROSE_NO_CRITERION | ·无法被阻挡且登场时一段时间内无敌<br>·会释放能使攻击力加倍的特殊弩箭<br>·每隔一段时间会召唤战场中隐藏的弩炮台 |
| main_06 | 狂暴宿主士兵 | prts.enemy_level.talent | PROSE_NO_CRITERION | 自身每秒受到330无来源真实伤害 |
| main_06 | 狂暴宿主组长 | prts.enemy_level.talent | PROSE_NO_CRITERION | 自身每秒受到500无来源真实伤害 |
| main_06 | 狂暴宿主投掷手 | prts.enemy_level.talent | PROSE_NO_CRITERION | 自身每秒受到250无来源真实伤害，不会攻击飞行单位 |
| main_06 | 狂暴宿主掷骨手 | prts.enemy_level.talent | PROSE_NO_CRITERION | 自身每秒受到350无来源真实伤害，不会攻击飞行单位 |
| main_06 | 雪怪小队 | gamedata.description | PROSE_NO_CRITERION | 雪怪小队基础近身作战人员，攻击被<@eb.key>冻结</>的单位时攻击力提高。 |
| main_06 | 雪怪小队 | prts.enemy_level.talent | PROSE_NO_CRITERION | 计算伤害时若目标正在受{{异常效果/冻结}}影响，攻击倍率提高至150% |
| main_06 | 雪怪小队 | prts.enemy.ability | PROSE_NO_CRITERION | ·攻击被{{术语/ba.frozen/冻结}}的目标时攻击力提升 |
| main_06 | 霜牙 | gamedata.description | PROSE_NO_CRITERION | 雪怪小队术师部队操纵的高速生物，攻击被<@eb.key>冻结</>的单位时攻击力提高。 |
| main_06 | 霜牙 | prts.enemy_level.talent | PROSE_NO_CRITERION | 计算伤害时若目标正在受{{异常效果/冻结}}影响，攻击倍率提高至150% |
| main_06 | 霜牙 | prts.enemy.ability | PROSE_NO_CRITERION | ·攻击被{{术语/ba.frozen/冻结}}的目标时攻击力提升 |
| main_06 | 霜锐 | gamedata.description | PROSE_NO_CRITERION | 比霜牙更加难缠，攻击被<@eb.key>冻结</>的单位时攻击力提高。 |
| main_06 | 霜锐 | prts.enemy_level.talent | PROSE_NO_CRITERION | 计算伤害时若目标正在受{{异常效果/冻结}}影响，攻击倍率提高至150% |
| main_06 | 霜锐 | prts.enemy.ability | PROSE_NO_CRITERION | ·攻击被{{术语/ba.frozen/冻结}}的目标时攻击力提升 |
| main_06 | 雪怪狙击手 | gamedata.description | PROSE_NO_CRITERION | 雪怪小队中的远程作战人员，攻击被<@eb.key>冻结</>的单位时攻击力提高。 |
| main_06 | 雪怪狙击手 | prts.enemy_level.talent | PROSE_NO_CRITERION | 不会攻击飞行单位<br>计算伤害时若目标正在受{{异常效果/冻结}}影响，攻击倍率提高至150% |
| main_06 | 雪怪狙击手 | prts.enemy.ability | PROSE_NO_CRITERION | ·攻击被{{术语/ba.frozen/冻结}}的目标时攻击力提升 |
| main_06 | 冰爆源石虫 | gamedata.description | PROSE_NO_CRITERION | 来自寒冷地区的被感染生物，死亡后对周围我方单位造成物理伤害且施加<@eb.key>寒冷</>。 |
| main_06 | 冰爆源石虫 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{特殊机制/死亡爆炸}}（爆炸半径1.65，延迟1秒，爆炸时来源无效，造成攻击力200%的无途径物理溅射伤害并施加持续10秒的{{术语/ba.cold/寒冷}}，无视{{异常效果/迷彩}}，不可对空） |
| main_06 | 冰爆源石虫 | prts.enemy.ability | PROSE_NO_CRITERION | ※死亡时对周围我方单位造成物理伤害，并施加{{术语/ba.cold/寒冷}}效果 |
| main_06 | 雪怪术师 | gamedata.description | PROSE_NO_CRITERION | 雪怪小队中的法术作战人员，每攻击2次后下次攻击会对目标施加<@eb.key>寒冷</>。 |
| main_06 | 雪怪术师 | prts.enemy.ability | PROSE_NO_CRITERION | ※攻击2次后，下一次攻击会对目标施加{{术语/ba.cold/寒冷}}效果 |
| main_06 | 雪怪术师组长 | gamedata.description | PROSE_NO_CRITERION | 雪怪小队法术作战人员中的精英，每攻击2次后下次攻击会对目标施加<@eb.key>寒冷</>。 |
| main_06 | 雪怪术师组长 | prts.enemy.ability | PROSE_NO_CRITERION | ※攻击2次后，下一次攻击会对目标施加{{术语/ba.cold/寒冷}}效果 |
| main_06 | 雪怪小队凿冰人 | gamedata.description | PROSE_NO_CRITERION | 雪怪小队中的特殊近身作战人员，攻击被<@eb.key>冻结</>的单位时攻击力大幅度提高。 |
| main_06 | 雪怪小队凿冰人 | prts.enemy_level.talent | PROSE_NO_CRITERION | 计算伤害时若目标正在受{{异常效果/冻结}}影响，攻击倍率提高至250% |
| main_06 | 雪怪小队凿冰人 | prts.enemy.ability | PROSE_NO_CRITERION | ·攻击被{{术语/ba.frozen/冻结}}的目标时攻击力大幅度提升 |
| main_06 | 虚幻 | gamedata.description | PROSE_NO_CRITERION | <@eb.key>【飞行单位】</>携带有冰爆弹头，投掷后造成群体法术伤害并施加<@eb.key>寒冷</>。 |
| main_06 | 虚幻 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{特殊机制/静态刚体}}，不进行普通攻击 |
| main_06 | 虚幻 | prts.enemy.ability | PROSE_NO_CRITERION | ·飞行单位<br>·可以投掷炸弹造成群体法术伤害并施加{{术语/ba.cold/寒冷}}效果 |
| main_06 | 霜星，“冬痕” | prts.enemy_level.talent | PROSE_NO_CRITERION | 普通攻击时对目标施加持续5秒的{{术语/ba.cold/寒冷}}，普通攻击不会攻飞行单位<br>首次被击倒后进行10秒的重生，恢复100%生命值<br>重生后攻击力提升50%，并获得{{变动数值/25/+}}秒无敌 |
| main_06 | 霜星，“冬痕” | prts.enemy.ability | PROSE_NO_CRITERION | ·普通攻击和冰环均能造成法术伤害，且对目标施加{{术语/ba.cold/寒冷}}效果<br>·冰环法术对被{{术语/ba.frozen/冻结}}的目标伤害加倍<br>·第二形态下会有一段无敌时间，且攻击和技能威力更强大 |
| main_06 | 霜星S | prts.enemy_level.talent | PROSE_NO_CRITERION | 演出用敌人<br>不进行普通攻击，每秒流失2000点生命 |
| main_07 | 游击队战士 | gamedata.description | PROSE_NO_CRITERION | 受到传令兵或爱国者<@eb.key>强化</>时，<@eb.key>移动速度</>提升 |
| main_07 | 游击队战士 | prts.enemy_level.talent | PROSE_NO_CRITERION | 受到<战术命令>影响时，移动速度+30% |
| main_07 | 游击队战士 | prts.enemy.ability | PROSE_NO_CRITERION | ·受到强化时，移动速度提升 |
| main_07 | 游击队战士组长 | gamedata.description | PROSE_NO_CRITERION | 受到传令兵或爱国者<@eb.key>强化</>时，<@eb.key>移动速度</>提升 |
| main_07 | 游击队战士组长 | prts.enemy_level.talent | PROSE_NO_CRITERION | 受到<战术命令>影响时，移动速度+30% |
| main_07 | 游击队战士组长 | prts.enemy.ability | PROSE_NO_CRITERION | ·受到强化时，移动速度提升 |
| main_07 | 游击队盾卫 | prts.enemy_level.talent | PROSE_NO_CRITERION | 自身嘲讽等级+1 |
| main_07 | 游击队迫击炮兵 | gamedata.description | PROSE_NO_CRITERION | 受到传令兵或爱国者<@eb.key>强化</>时，<@eb.key>攻击速度</>大幅提升 |
| main_07 | 游击队迫击炮兵 | prts.enemy_level.talent | PROSE_NO_CRITERION | 不会攻击飞行单位<br>受到<战术命令>影响时，攻击速度+50<br>炮弹能对目标及其周围八格的我方单位造成伤害<br>※对主目标造成物理普通伤害，对溅射目标造成物理溅射伤害，可溅射飞行单位，伤害无视{{异常效果/迷彩}} |
| main_07 | 游击队迫击炮兵 | prts.enemy.ability | PROSE_NO_CRITERION | ·受到强化时，攻击速度大幅提升 |
| main_07 | 游击队萨卡兹术师 | prts.enemy_level.talent | PROSE_NO_CRITERION | 攻击间隔-4.9，不进行普通攻击<br>[[源石祭坛/免疫脉冲波]]，受[[源石祭坛]]/[[爱国者的源石祭坛]]的技能【脉冲波】影响后可进入{{color/#FF4F0B/强化模式}} |
| main_07 | 游击队萨卡兹术师组长 | prts.enemy_level.talent | PROSE_NO_CRITERION | 攻击间隔-4.9，不进行普通攻击<br>[[源石祭坛/免疫脉冲波]]，受[[源石祭坛]]/[[爱国者的源石祭坛]]的技能【脉冲波】影响后可进入{{color/#FF4F0B/强化模式}} |
| main_07 | 雇佣军萨卡兹术师 | prts.enemy_level.talent | PROSE_NO_CRITERION | 攻击间隔-4.9，不进行普通攻击<br>[[源石祭坛/免疫脉冲波]]，受[[源石祭坛]]/[[爱国者的源石祭坛]]的技能【脉冲波】影响后可进入{{color/#FF4F0B/强化模式}} |
| main_07 | 爱国者 | gamedata.description | PROSE_NO_CRITERION | 最后一位纯血温迪戈。行军姿态<@eb.key>防御力与法术抗性</>极高，毁灭姿态<@eb.key>免疫眩晕</> |
| main_07 | 爱国者 | prts.enemy_level.talent | PROSE_NO_CRITERION | [[源石祭坛/免疫脉冲波]]<br>在场时令全场敌方单位（无视其可选性）攻击力+20%、防御力+200（多个爱国者给予的属性增益不叠加），并获得<战术命令>效果<br>'''{{color/#FF4F0B/行军姿态<初始形态>}}'''<b |
| main_07 | 爱国者 | prts.enemy.ability | PROSE_NO_CRITERION | ·大幅强化敌军攻击与防御力<br>{{color/#FF4F0B/行军姿态}}<br>·攻击力提升，防御力与法术抗性大幅提升，使自身极容易受到我方攻击，普通攻击为4连击<br>·生命值降为0后，进入重生阶段，期间持续对周围造成真实伤害，一段 |
| main_08 | 乌萨斯突击者 | prts.enemy.ability | PROSE_TOKEN_NOT_CARRIER | ·只能被阻挡数大于等于2的单位阻挡<br>·可使用远程武器攻击<乌萨斯平民>与<斗士塔露拉> |
| main_08 | 帝国前锋精锐 | gamedata.description | PROSE_NO_CRITERION | 未阻挡时远程攻击;生命值降至一半时攻击力<@eb.key>大幅提升</> |
| main_08 | 帝国前锋精锐 | prts.enemy_level.talent | PROSE_NO_CRITERION | 未被阻挡时可进行远程攻击，远程攻击造成攻击力50%的物理伤害，不会攻击飞行单位<br>目标嘲讽等级相同时，远程攻击优先攻击[[乌萨斯平民]]/[[斗士塔露拉]]/[[矿工游击队]]<br>生命值低于50%时，攻击力+100% |
| main_08 | 帝国前锋精锐 | prts.enemy.ability | PROSE_NO_CRITERION | ·生命值降至一半以下时攻击力大幅提升 |
| main_08 | 帝国前锋百战精锐 | gamedata.description | PROSE_NO_CRITERION | 未阻挡时远程攻击;生命值降至一半时攻击力<@eb.key>大幅提升</> |
| main_08 | 帝国前锋百战精锐 | prts.enemy_level.talent | PROSE_NO_CRITERION | 未被阻挡时可进行远程攻击，远程攻击造成攻击力50%的物理伤害，不会攻击飞行单位<br>目标嘲讽等级相同时，远程攻击优先攻击[[乌萨斯平民]]/[[斗士塔露拉]]/[[矿工游击队]]<br>生命值低于50%时，攻击力+100% |
| main_08 | 帝国前锋百战精锐 | prts.enemy.ability | PROSE_NO_CRITERION | ·生命值降至一半以下时攻击力大幅提升 |
| main_08 | 萨卡兹宿主百夫长 | gamedata.description | PROSE_NO_CRITERION | 同时攻击三个目标;每次<@eb.key>攻击回复自身生命值</> |
| main_08 | 萨卡兹宿主百夫长 | prts.enemy_level.talent | PROSE_NO_CRITERION | 最多同时攻击3个目标，不会攻击飞行单位<br>成功造成伤害后，治疗自身相当于伤害量150%的生命值 |
| main_08 | 萨卡兹宿主百夫长 | prts.enemy.ability | PROSE_NO_CRITERION | ·同时攻击三个目标<br>·恢复攻击总伤害一定比例的生命值 |
| main_08 | “皇帝的利刃” | prts.enemy_level.talent | PROSE_NO_CRITERION | 演出用敌人<br>{{异常效果/无敌}}，{{异常效果/免疫失衡}}，{{异常效果/沉睡/免疫}}，不进行攻击，无法被阻挡 |
| main_08 | 塔露拉 | prts.enemy_level.talent | PROSE_NO_CRITERION | 【烈焚灼息】：每秒受到固定值真实持续伤害，初始伤害量为50/s，在30s内线性提升至230/s<br>※【烈焚灼息】不可叠加，重复施加时刷新持续时间，可{{术语/ba.buffres/抵抗}}（伤害间隔/伤害提升间隔'''固定'''）；效果 |
| main_08 | 塔露拉 | prts.enemy.ability | PROSE_NO_CRITERION | ·【日冕】对范围内所有我方单位造成法术伤害<br>·【烈焚灼息】使场上一名我方单位持续受到逐渐递增的真实伤害（每秒造成真实伤害，可被{{术语/ba.buffres/抵抗}}）<br>·被阻挡时造成真实伤害<br>·生命值降至一半时防御力、法 |
| main_08 | 梅菲斯特，“歌者” | gamedata.description | PROSE_NO_CRITERION | 被痛苦包围的异样生物。<@eb.key>无法被阻挡</>且每损失一定生命会释放毒性粉尘 |
| main_08 | 梅菲斯特，“歌者” | prts.enemy_level.talent | PROSE_TOKEN_NOT_CARRIER | 无法移动，不可阻挡，{{异常效果/失衡免疫}}<br>普通攻击最多同时攻击2个目标，造成法术伤害<br>【毒性】：无效果，最多可叠加5层，每层独立计算持续时间<br>【毒性粉尘】：每秒对场上所有我方单位造成自身【毒性】层数×{{变动数值/8 |
| main_08 | 梅菲斯特，“歌者” | prts.enemy.ability | PROSE_NO_CRITERION | {{color/#FF4F0B/活性状态}}<br>·活性状态下治疗并强化敌方宿主单位<br>·每损失一定比例生命，对全场我方释放持续30秒可叠加的毒性粉尘<br>·生命值首次降至0后一段时间内进入休眠状态<br>{{color/#FF4F |
| main_08 | “不死的黑蛇” | prts.enemy_level.talent | PROSE_NO_CRITERION | 【烈焚灼息】：每秒受到固定值真实持续伤害，初始伤害量为50/s，在30s内线性提升至230/s<br>※重复施加时刷新持续时间，不可叠加。可{{术语/ba.buffres/抵抗}}（伤害间隔/伤害提升间隔'''固定'''）。效果结束时重置每 |
| main_08 | “不死的黑蛇” | prts.enemy.ability | PROSE_NO_CRITERION | {{color/#FF4F0B/第一阶段}}<br>·攻击造成真实伤害并对目标施加【烈焚灼息】(每秒造成真实伤害且伤害递增，可被{{术语/ba.buffres/抵抗}})<br>·周期性对两名我方单位施加【烈焚灼息】，附带【烈焚灼息】的我方 |
| main_08 | 乌萨斯平民 | gamedata.description | PROSE_NO_CRITERION | <@eb.key>友好单位</>撤回保护目标时不扣除关卡生命值，死亡时扣除关卡生命值;不计入歼灭数 |
| main_08 | 乌萨斯平民 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{特殊机制/中立单位}}，{{异常效果/沉睡/免疫}}，无法攻击/被阻挡<br>死亡时扣除1目标生命值 |
| main_08 | 斗士塔露拉 | gamedata.description | PROSE_NO_CRITERION | <@eb.key>友好单位</>进入侵入点时不扣除关卡生命值，死亡时扣除关卡生命值;不计入歼灭数 |
| main_08 | 斗士塔露拉 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{特殊机制/中立单位}}，{{异常效果/沉睡/免疫}}，无法被阻挡<br>普通攻击与技能不会选择[[道路障碍物]]作为目标；死亡时扣除2目标生命值<br><br>生命值低于50%时，进入【狂暴】状态<br>狂暴状态下，防御力提升50%，法 |
| main_08 | 斗士塔露拉 | prts.enemy.ability | PROSE_NO_CRITERION | ·进入敌方侵入点时不扣除目标生命，死亡时扣除目标生命<br>·对攻击范围的一名敌人施加【烈焚灼息】(每秒造成真实伤害且伤害递增，可被{{术语/ba.buffres/抵抗}})<br>·不计入歼灭数 |
| main_09 | 深池侦察犬 | gamedata.description | PROSE_NO_CRITERION | 深池部队操纵的生物。<@eb.key>折射</>生效时，法术抗性增加70 |
| main_09 | 深池侦察犬 | prts.enemy_level.talent | PROSE_NO_CRITERION | 折射：法术抗性增加70（可被沉默） |
| main_09 | 深池侦察兵 | gamedata.description | PROSE_NO_CRITERION | 深池部队中的侦察人员。<@eb.key>折射</>生效时，法术抗性增加70 |
| main_09 | 深池侦察兵 | prts.enemy_level.talent | PROSE_NO_CRITERION | 折射：法术抗性增加70（可被沉默） |
| main_09 | 深池狙击手 | gamedata.description | PROSE_NO_CRITERION | 深池部队中的狙击手。<@eb.key>折射</>生效时，法术抗性增加70 |
| main_09 | 深池狙击手 | prts.enemy_level.talent | PROSE_NO_CRITERION | 不会攻击飞行单位<br>折射：法术抗性增加70（可被沉默） |
| main_09 | 深池暗影术师 | gamedata.description | PROSE_NO_CRITERION | 深池部队中的术师。<@eb.key>折射</>生效时，法术抗性增加70 |
| main_09 | 深池暗影术师 | prts.enemy_level.talent | PROSE_NO_CRITERION | 不会攻击飞行单位<br>折射：法术抗性增加70（可被沉默） |
| main_09 | 深池方阵步兵 | gamedata.description | PROSE_NO_CRITERION | 距离较近的方阵步兵会相互支援，<@eb.key>防御力提升</>。<@eb.key>折射</>生效时，法术抗性增加70 |
| main_09 | 深池方阵步兵 | prts.enemy_level.talent | PROSE_NO_CRITERION | 折射：法术抗性增加70（可被沉默）<br>自身1.5半径内除自身外其它[[深池方阵战士]]/[[深池方阵指挥官]]防御力增加200（可无限叠加，不可被沉默） |
| main_09 | 深池重甲卫士 | gamedata.description | PROSE_NO_CRITERION | 深池部队中的重甲卫士。<@eb.key>折射</>生效时，法术抗性增加70 |
| main_09 | 深池重甲卫士 | prts.enemy_level.talent | PROSE_NO_CRITERION | 折射：法术抗性增加70（可被沉默） |
| main_09 | 深池飞行兵 | gamedata.description | PROSE_NO_CRITERION | 处于<@eb.key>近地悬浮</>状态，无法被阻挡，只受对空攻击影响。被晕眩或沉睡一次后失去<@eb.key>近地悬浮</> |
| main_09 | 深池飞行兵 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{color/#FF4F0B/'''初始模式'''}}<br>{{术语/ba.float/近地悬浮}}，{{异常效果/失衡免疫}}，不会攻击飞行单位<br>受{{异常效果/晕眩}}/{{异常效果/无法行动}}/{{异常效果/沉睡}}/{{ |
| main_09 | 守墓石像 | gamedata.description | PROSE_NO_CRITERION | <@eb.key>折射</>；首次被击倒后暂时变为<@eb.key>防御极高</>的石像，之后重生成为<@eb.key>空中单位</> |
| main_09 | 守墓石像 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{术语/ba.refraction/折射}}<br>'''{{color/#FF4F0B/地面模式<初始模式>}}'''<br>仅在被阻挡时进行近战攻击<br>受到来源于<破碎支柱>伤害时，获得持续1s的破碎效果（重复触发独立计算持续时间 |
| main_09 | 守墓石像 | prts.enemy.ability | PROSE_NO_CRITERION | ·首次被击倒时暂时变为防御力极高的石像，一段时间后重生为空中单位<br>※{{术语/ba.refraction/折射}} |
| main_09 | 深池焚毁者 | prts.enemy_level.talent | PROSE_NO_CRITERION | 仅进行阻挡攻击，造成物理普通伤害<br>（可沉默）持有{{异常效果/不死}}，受到致命伤害时：{{特殊机制/强制触发技能}}【爆炸】，期间持有{{异常效果/孤立}}、{{异常效果/不可选中}}、{{异常效果/无敌}}、{{异常效果/自缚}} |
| main_09 | 深池伙友卫队 | gamedata.description | PROSE_NO_CRITERION | <@eb.key>折射</>；更容易受到我方攻击，<@eb.key>伙友影刃</>位于附近时，激活力场使周围我方<@eb.key>攻击速度下降</> |
| main_09 | 深池伙友卫队 | prts.enemy_level.talent | PROSE_NO_CRITERION | {{术语/ba.refraction/折射}}；自身1.4半径范围内存在[[深池伙友影刃]]/[[深池伙友影刃精英]]时，使自身半径1.1范围内所有我方单位攻击速度-30 |
| main_09 | 深池伙友卫队 | prts.enemy.ability | PROSE_NO_CRITERION | ·容易受到我方单位攻击<br>·<深池伙友影刃>位于附近时，激活力场使周围我方攻击速度下降<br>※{{术语/ba.refraction/折射}} |
| main_09 | 深池伙友影刃 | gamedata.description | PROSE_TOKEN_NOT_CARRIER | <@eb.key>隐匿</>；<@eb.key>伙友卫队</>位于附近时，攻击速度大幅提升。 |
| main_09 | 深池伙友影刃 | prts.enemy_level.talent | PROSE_TOKEN_NOT_CARRIER | {{异常效果/隐匿}}<br>自身1.4半径范围内存在[[深池伙友卫队]]/[[深池伙友卫队精英]]时，自身攻击间隔减少1.2s |
| main_09 | 深池伙友影刃 | prts.enemy.ability | PROSE_TOKEN_NOT_CARRIER | ·{{术语/ba.invisible/隐匿}}<br>·<深池伙友卫队>位于附近时，攻击速度大幅提升 |
| main_09 | 深池塑能术师 | prts.enemy_level.talent | PROSE_NO_CRITERION | 不进行普通攻击 |
| main_09 | 蔓德拉 | prts.enemy_level.talent | PROSE_NO_CRITERION | 出场时持有【石之盾】<br>【石之盾】：受到的物理/法术伤害降低{{变动数值/65%/+}}<br>受到来自<破碎支柱>的伤害后，【石之盾】失效。<br>【石之盾】失效时，中断当前正在释放的技能并令其进入冷却。【石之盾】失效期间，无法释放技 |
| main_09 | 蔓德拉 | prts.enemy.ability | PROSE_NO_CRITERION | ·【石之盾】所受伤害降低，受到破碎支柱的伤害后暂时失效<br>{{color/#FF4F0B/第一形态}}<br>·【蔓德拉的注目】寻找范围内攻击最高的目标，造成法术伤害并使其攻速下降，若其撤退或被击倒则使所在地块损毁<br>{{color |
| main_10 | 深池侦察队长 | gamedata.description | PROSE_NO_CRITERION | 深池部队中的侦察队队长。<@eb.key>折射</>生效时，法术抗性增加70 |
| main_10 | 深池侦察队长 | prts.enemy_level.talent | PROSE_NO_CRITERION | 折射：法术抗性增加70（可被沉默） |
| main_10 | 深池狙击队长 | gamedata.description | PROSE_NO_CRITERION | 深池部队中的狙击队长。<@eb.key>折射</>生效时，法术抗性增加70 |
| main_10 | 深池狙击队长 | prts.enemy_level.talent | PROSE_NO_CRITERION | 不会攻击飞行单位<br>折射：法术抗性增加70（可被沉默） |
| main_10 | 大君之触 | gamedata.description | PROSE_NO_CRITERION | 难以击倒的<@eb.key>重生造物</>，阻挡该敌人的单位<@eb.key>阻挡数上限提升</>。 |
| main_10 | 大君之触 | prts.enemy_level.talent | PROSE_NO_CRITERION | 受到的物理/法术伤害降低90%<br/>阻挡该敌人的单位阻挡数+1，同类效果最多叠加6次 |
| main_10 | 大君之触 | prts.enemy.ability | PROSE_NO_CRITERION | ·重生造物（受到的物理和法术伤害大幅降低）<br>·阻挡该敌人的单位阻挡数上限+1（最多+6） |
| main_10 | 大君之赐 | gamedata.description | PROSE_NO_CRITERION | 难以击倒的<@eb.key>重生造物</>，阻挡该敌人的单位<@eb.key>阻挡数上限提升</>。 |
| main_10 | 大君之赐 | prts.enemy_level.talent | PROSE_NO_CRITERION | 受到的物理/法术伤害降低90%<br/>阻挡该敌人的单位阻挡数+1，同类效果最多叠加6次 |
| main_10 | 大君之赐 | prts.enemy.ability | PROSE_NO_CRITERION | ·重生造物（受到的物理和法术伤害大幅降低）<br>·阻挡该敌人的单位阻挡数上限+1（最多+6） |
| main_10 | 慷慨之赐 | gamedata.description | PROSE_NO_CRITERION | 难以击倒的<@eb.key>重生造物</>，阻挡该敌人的单位<@eb.key>阻挡数上限提升</>。 |
| main_10 | 慷慨之赐 | prts.enemy_level.talent | PROSE_NO_CRITERION | 受到的物理/法术伤害降低90%<br/>阻挡该敌人的单位阻挡数+1，同类效果最多叠加6次 |
| main_10 | 慷慨之赐 | prts.enemy.ability | PROSE_NO_CRITERION | ·重生造物（受到的物理和法术伤害大幅降低）<br>·阻挡该敌人的单位阻挡数上限+1（最多+6） |
| main_10 | 萨卡兹子裔战士 | gamedata.description | PROSE_NO_CRITERION | 受到血魔大君活体血液赐福的萨卡兹王庭军战士，首次倒下后重生为<@eb.key><大君之触></>。 |
| main_10 | 萨卡兹子裔战士 | prts.enemy_level.talent | PROSE_NO_CRITERION | 死亡1秒后在距离自身最近的可通行地块中心0.2边长正方形范围内随机位置以自身路径召唤1只[[大君之触]] |
| main_10 | 萨卡兹子裔战士 | prts.enemy.ability | PROSE_NO_CRITERION | ·首次倒下后重生为<大君之触> |
| main_10 | 萨卡兹子裔战士组长 | gamedata.description | PROSE_NO_CRITERION | 受到血魔大君活体血液赐福的萨卡兹王庭军战士组长，首次倒下后重生为<@eb.key><仁慈之触></>。 |
| main_10 | 萨卡兹子裔战士组长 | prts.enemy_level.talent | PROSE_NO_CRITERION | 死亡1秒后在距离自身最近的可通行地块中心0.2边长正方形范围内随机位置以自身路径召唤1只[[仁慈之触]] |
| main_10 | 萨卡兹子裔战士组长 | prts.enemy.ability | PROSE_NO_CRITERION | ·首次倒下后重生为<仁慈之触> |
| main_10 | 萨卡兹子裔工匠 | gamedata.description | PROSE_NO_CRITERION | 为<@eb.key>伦蒂尼姆城防副炮</>持续充能，被打断时城防炮<@eb.key>损失部分充能</>；首次倒下后重生为<@eb.key><大君之触></>。 |
| main_10 | 萨卡兹子裔工匠 | prts.enemy_level.talent | PROSE_NO_CRITERION | 死亡1秒后在距离自身最近的可通行地块中心0.2边长正方形范围内随机位置以自身路径召唤1只[[大君之触]] |
| main_10 | 萨卡兹子裔工匠 | prts.enemy.ability | PROSE_NO_CRITERION | ※为伦蒂尼姆城防副炮持续充能，被打断时城防炮损失部分充能<br>·首次倒下后重生为<大君之触> |
| main_10 | 萨卡兹子裔补给车 | gamedata.description | PROSE_NO_CRITERION | 在场时，重生造物的<@eb.key>攻击力提升</>且攻击附带<@eb.key>凋亡损伤</>。 |
| main_10 | 萨卡兹子裔补给车 | prts.enemy_level.talent | PROSE_NO_CRITERION | 不会攻击飞行单位<br>在场时，场上所有'''重生造物'''{{popup/内容=包含以下敌人：<br>[[大君之触]]，[[仁慈之触]]，[[大君之赐]]，[[慷慨之赐]]}}攻击力提升10%（最多叠加5层），且攻击时附加各自攻击力10% |
| main_10 | 萨卡兹子裔补给车 | prts.enemy.ability | PROSE_NO_CRITERION | ※在场时，重生造物的攻击力提升且攻击附带{{术语/ba.dt.apoptosis/凋亡损伤}} |
| main_10 | 萨卡兹子裔改装补给车 | gamedata.description | PROSE_NO_CRITERION | 在场时，重生造物的<@eb.key>攻击力提升</>且攻击附带<@eb.key>凋亡损伤</>。 |
| main_10 | 萨卡兹子裔改装补给车 | prts.enemy_level.talent | PROSE_NO_CRITERION | 不会攻击飞行单位<br>在场时，场上所有'''重生造物'''{{popup/内容=包含以下敌人：<br>[[大君之触]]，[[仁慈之触]]，[[大君之赐]]，[[慷慨之赐]]}}攻击力提升10%（最多叠加5层），且攻击时附加各自攻击力10% |
| main_10 | 萨卡兹子裔改装补给车 | prts.enemy.ability | PROSE_NO_CRITERION | ※在场时，重生造物的攻击力提升且攻击附带{{术语/ba.dt.apoptosis/凋亡损伤}} |
| main_10 | 萨卡兹子裔链术师 | gamedata.description | PROSE_NO_CRITERION | 攻击造成<@eb.key>法术伤害</>与<@eb.key>凋亡损伤</>，且会在4个敌人间跳跃，每次跳跃伤害降低；首次倒下后重生为<@eb.key><大君之赐></>。 |
| main_10 | 萨卡兹子裔链术师 | prts.enemy_level.talent | PROSE_NO_CRITERION | 攻击附加自身攻击力30%的凋亡损伤<br/>普通攻击可在最多4个单位间跳跃，最大跳跃半径1.6，每次跳跃攻击倍率降低至跳跃前的85%<br/>死亡1秒后在距离自身最近的可通行地块中心0.2边长正方形范围内随机位置以自身路径召唤1只[[大君之 |
| main_10 | 萨卡兹子裔链术师 | prts.enemy.ability | PROSE_NO_CRITERION | ·攻击造成{{术语/ba.dt.apoptosis/凋亡损伤}}，且会在4个敌人间跳跃，每次跳跃伤害降低<br>·首次倒下后重生为<大君之赐> |
| main_10 | 萨卡兹子裔链术师组长 | gamedata.description | PROSE_NO_CRITERION | 攻击造成<@eb.key>法术伤害</>与<@eb.key>凋亡损伤</>，且会在4个敌人间跳跃，每次跳跃伤害降低；首次倒下后重生为<@eb.key><慷慨之赐></>。 |
| main_10 | 萨卡兹子裔链术师组长 | prts.enemy_level.talent | PROSE_NO_CRITERION | 攻击附加自身攻击力30%的凋亡损伤<br/>普通攻击可在最多4个单位间跳跃，最大跳跃半径1.6，每次跳跃攻击倍率降低至跳跃前的85%<br/>死亡1秒后在距离自身最近的可通行地块中心0.2边长正方形范围内随机位置以自身路径召唤1只[[慷慨之 |
| main_10 | 萨卡兹子裔链术师组长 | prts.enemy.ability | PROSE_NO_CRITERION | ·攻击造成{{术语/ba.dt.apoptosis/凋亡损伤}}，且会在4个敌人间跳跃，每次跳跃伤害降低<br>·首次倒下后重生为<慷慨之赐> |
| main_10 | 萨卡兹子裔集恨者 | gamedata.description | PROSE_NO_CRITERION | 场上每有一个重生造物时<@eb.key>攻击力提升</>；首次倒下后重生为<@eb.key><大君之赐></>。 |
| main_10 | 萨卡兹子裔集恨者 | prts.enemy_level.talent | PROSE_NO_CRITERION | 场上每存在1个'''重生造物'''{{popup/内容=包含以下敌人：<br>[[大君之触]]、[[仁慈之触]]、[[大君之赐]]、[[慷慨之赐]]}}，自身攻击力提升15%，最多叠加6层<br/>死亡1秒后在距离自身最近的可通行地块中心0 |
| main_10 | 萨卡兹子裔集恨者 | prts.enemy.ability | PROSE_NO_CRITERION | ·场上每有一个重生造物时攻击力提升<br>·首次倒下后重生为<大君之赐> |
| main_10 | 萨卡兹子裔集怒者 | gamedata.description | PROSE_NO_CRITERION | 场上每有一个重生造物时<@eb.key>攻击力提升</>；首次倒下后重生为<@eb.key><慷慨之赐></>。 |
| main_10 | 萨卡兹子裔集怒者 | prts.enemy_level.talent | PROSE_NO_CRITERION | 场上每存在1个'''重生造物'''{{popup/内容=包含以下敌人：<br>[[大君之触]]、[[仁慈之触]]、[[大君之赐]]、[[慷慨之赐]]}}，自身攻击力提升25%，最多叠加6次<br/>死亡1秒后在距离自身最近的可通行地块中心0 |
| main_10 | 萨卡兹子裔集怒者 | prts.enemy.ability | PROSE_NO_CRITERION | ·场上每有一个重生造物时攻击力提升<br>·首次倒下后重生为<慷慨之赐> |
| main_10 | 萨卡兹征用工程无人机 | gamedata.description | PROSE_TOKEN_NOT_CARRIER | 隐匿，会逐渐损失生命，攻击时为<@eb.key>伦蒂尼姆城防副炮</>充能。 |
| main_10 | 萨卡兹征用工程无人机 | prts.enemy_level.talent | PROSE_TOKEN_NOT_CARRIER | {{特殊机制/静态刚体}}，{{术语/ba.invisible/隐匿}}，自身每秒受到60无来源真实持续伤害<br/>每次攻击使[[伦蒂尼姆城防副炮]]获得1SP，造成的伤害视为无来源 |
| main_10 | 萨卡兹征用工程无人机 | prts.enemy.ability | PROSE_TOKEN_NOT_CARRIER | ·飞行单位<br>·{{术语/ba.invisible/隐匿}}，会逐渐损失生命<br>·攻击时为伦蒂尼姆城防副炮充能 |
| main_10 | 渴血的子裔 | prts.enemy_level.talent | PROSE_NO_CRITERION | 成功造成伤害后，治疗自身相当于伤害量220%的生命值 |
| main_10 | 曼弗雷德 | prts.enemy_level.talent | PROSE_NO_CRITERION | '''※{{color/#FF0000/此敌人在部分关卡中存在天赋差异与额外启用的机制，请前往具体关卡页面查阅详细资料！}}'''<br><br>【专注】：普通攻击持续攻击相同目标时，每次攻击使自身攻击速度增加60，最多叠加5层。切换目标/ |
| main_10 | 曼弗雷德 | prts.enemy.ability | PROSE_NO_CRITERION | ·使用浮游炮攻击造成法术伤害，浮游炮攻击时为伦蒂尼姆城防副炮充能<br>·【军事训练】拥有高额的物理和法术闪避，但受到城防炮轰击后闪避失效一段时间并{{术语/ba.stun/晕眩}}数秒<br>{{color/#FF4F0B/第一形态}}< |

### 7.2 被判为风味而跳过

`MECH_KEYWORDS` 词表不命中的正文**不进任何判据**。列出全文是为了让「跳过」这件事
本身可复核——词表窄了、把机制正文错判成风味，只能靠这一节看出来。

| 章 | 敌人 | 来源 | 正文 |
|---|---|---|---|
| main_00 | 猎狗 | gamedata.description | 整合运动技术侦察部队操纵的生物，<@eb.key>行动速度很快</>。 |
| main_00 | 士兵 | gamedata.description | 整合运动的基础近身作战人员。 |
| main_00 | 妖怪 | gamedata.description | <@eb.key>【飞行单位】</>敌方人员操纵的无人机，不会进行攻击。 |
| main_00 | 妖怪 | prts.enemy.ability | ·飞行单位 |
| main_00 | 源石虫 | gamedata.description | 野生的被感染生物。 |
| main_00 | 源石虫·α | gamedata.description | 野生的被感染生物，比一般源石虫更具有威胁。 |
| main_00 | 暴徒 | gamedata.description | 来路不明的作战人员，使用随意制作的武器进行近身攻击。 |
| main_00 | 持盾刀兵 | gamedata.description | 整合运动的近身作战人员，拥有简单的物理防护能力。 |
| main_00 | 拾荒者 | gamedata.description | 缺少打理，穿着着破损服装的作战人员。 |
| main_01 | 猎狗pro | gamedata.description | 比一般猎狗更具有作战能力，<@eb.key>行动速度很快</>。 |
| main_01 | 术师 | gamedata.description | 整合运动的基础法术作战人员，使用<@eb.key>远距离法术攻击</>。 |
| main_01 | 术师 | prts.enemy_level.talent | 不会攻击飞行单位 |
| main_01 | 双持剑士 | gamedata.description | 整合运动的近身作战人员，以<@eb.danger>高攻击力</>见长。 |
| main_01 | 鸡尾酒投掷者 | gamedata.description | 来路不明的作战人员，使用土制燃烧瓶进行<@eb.key>远程物理攻击</>。 |
| main_01 | 鸡尾酒投掷者 | prts.enemy_level.talent | 不会攻击飞行单位 |
| main_01 | 燃烧瓶投掷者 | gamedata.description | 比一般鸡尾酒投掷者更具威胁，使用土制燃烧瓶进行<@eb.key>远程物理攻击</>。 |
| main_01 | 燃烧瓶投掷者 | prts.enemy_level.talent | 不会攻击飞行单位 |
| main_01 | W | gamedata.description | 整合运动干部，萨卡兹雇佣兵，擅长使用爆炸物。 |
| main_02 | 弩手 | gamedata.description | 整合运动的基础射击作战人员，<@eb.key>使用远距离攻击</>。 |
| main_02 | 弩手组长 | gamedata.description | 相比一般弩手更具作战能力，<@eb.key>使用远距离攻击</>。 |
| main_02 | 妖怪MKII | gamedata.description | <@eb.key>【飞行单位】</>妖怪的改进版，可进行<@eb.key>远程物理射击</>。 |
| main_02 | 妖怪MKII | prts.enemy.ability | ·飞行单位 |
| main_02 | 重装防御者 | gamedata.description | 整合运动的近身作战人员，<@eb.key>防御力很高</>且难以被击溃。 |
| main_02 | 空降兵 | gamedata.description | 特殊近身作战人员，他们可以从出其不意的位置切入战场。 |
| main_02 | 空降兵 | prts.enemy.ability | ·能够从战场中降落 |
| main_02 | 空降组长 | gamedata.description | 比空降兵更具威胁，他们可以从出其不意的位置切入战场。 |
| main_02 | 空降组长 | prts.enemy.ability | ·能够从战场中降落 |
| main_02 | 双持剑士组长 | gamedata.description | 比一般双持剑士更具威胁，以<@eb.danger>高攻击力</>见长。 |
| main_02 | 轻甲卫兵 | gamedata.description | 整合运动的近身作战人员，他们有较高的<@eb.key>防御力</>。 |
| main_02 | 磐蟹 | gamedata.description | 野生的被感染生物，普通武器对其效果都不太理想，但是<@eb.key>重量</>并没有想像的大。 |
| main_02 | 御4 | gamedata.description | <@eb.key>【飞行单位】</>无人机，能使周围敌军<@eb.key>防御力上升</>。 |
| main_02 | 御4 | prts.enemy.ability | ·飞行单位<br>※为周围敌军持续提供防御力加成 |
| main_02 | 高阶术师 | gamedata.description | 精英法术作战人员，擅长<@eb.key>远距离群体法术攻击</>。其攻击会伤害目标周围的单位。 |
| main_02 | 高阶术师 | prts.enemy_level.talent | 每次普通攻击以攻击主目标位置为中心对十字区域{{popup/range/x-5}}（碰撞判定，不对齐）内的所有我方单位造成伤害，不会攻击飞行单位<br>※对主目标造成近战途径法术普通伤害，对其他单位造成近战途径法术溅射伤害 |
| main_02 | 高阶术师 | prts.enemy.ability | ·攻击时对目标及其周围四格内的所有我方单位造成伤害 |
| main_02 | 暴乱分子 | gamedata.description | 比一般暴徒更具威胁，使用随意制作的武器进行近身攻击。 |
| main_02 | 伐木机 | gamedata.description | 来路不明，穿戴简易林业护具，携带伐木工具进行攻击。 |
| main_02 | 碎骨 | gamedata.description | 可以的话，请倾全队之力消灭他。该敌人<@eb.danger>威胁极大</>，<@eb.key>远程及近战攻击能造成大量伤害</>。 |
| main_03 | 狂暴的猎狗pro | gamedata.description | 比猎狗pro更具有作战能力，<@eb.key>行动速度很快</>。 |
| main_03 | 重装防御组长 | gamedata.description | 比一般重装防御者更具威胁，<@eb.key>防御力很高</>且难以被击溃。 |
| main_03 | 源石虫·β | gamedata.description | 野生的被感染生物，比源石虫·α更具有威胁。 |
| main_03 | 炮手 | gamedata.description | 特殊远程作战人员，能够进行<@eb.key>超远距离溅射攻击</>。 |
| main_03 | 炮手 | prts.enemy.ability | ·超远距离攻击<br>·炮弹能对目标及其周围八格内的所有我方单位造成伤害 |
| main_03 | 拳刃武士 | gamedata.description | 受过一些传统战斗训练的近身作战人员，兼具<@eb.key>较高攻击力和防御力</>。 |
| main_03 | 伐木老手 | gamedata.description | 来路不明，穿戴简易林业护具，携带伐木工具进行攻击。比“伐木机”更具有威胁。 |
| main_03 | 屠夫 | gamedata.description | 来路不明，使用巨大的钝器进行攻击。拥有一定防护能力。 |
| main_03 | 屠宰老手 | gamedata.description | 来路不明，使用巨大的钝器进行攻击。比屠夫更具有威胁，拥有一定防护能力。 |
| main_03 | 萨卡兹百夫长 | gamedata.description | 整合运动干部。该敌人<@eb.danger>威胁很大</>，<@eb.danger>难以被消灭</>。 |
| main_03 | 萨卡兹百夫长 | prts.enemy_level.talent | 可最多同时攻击2个目标，造成近战途径伤害，不会攻击飞行单位 |
| main_03 | 萨卡兹百夫长 | prts.enemy.ability | ·同时攻击两个目标 |
| main_04 | 术师组长 | gamedata.description | 相比一般术师更具作战能力，使用<@eb.key>远距离法术攻击</>。 |
| main_04 | 术师组长 | prts.enemy_level.talent | 不会攻击飞行单位 |
| main_04 | 萨卡兹狙击手 | prts.enemy_level.talent | 不会攻击飞行单位 |
| main_04 | 轻甲卫兵组长 | gamedata.description | 比一般轻甲卫兵更具威胁，他们有较高的<@eb.key>防御力</>。 |
| main_04 | 高能源石虫 | gamedata.description | 野生的被感染生物，死亡后会产生<@eb.danger>爆炸</>。 |
| main_04 | 高能源石虫 | prts.enemy.ability | ※死亡后对周围造成大量物理伤害 |
| main_04 | 萨卡兹术师 | prts.enemy_level.talent | 不会攻击飞行单位 |
| main_04 | 萨卡兹术师 | prts.enemy.ability | ※可以使用枷锁使我方单位瘫痪 |
| main_04 | 机动盾组长 | gamedata.description | 比一般机动盾兵更具威胁，拥有简单的物理防护能力。 |
| main_04 | 法术近卫 | gamedata.description | 受过法术战斗训练的近身作战人员，对目标造成<@eb.key>法术伤害</>。 |
| main_04 | 武装人员 | gamedata.description | 来路不明，使用巨大的钝器进行攻击。拥有高防护能力。 |
| main_04 | 霜星 | gamedata.description | 整合运动法术部队干部，<@eb.danger>威胁极大</>，能使用冰属性法术<@eb.danger>造成极为恶劣的作战环境</>。 |
| main_05 | 特战士兵 | gamedata.description | 整合运动的近身作战人员。配备了和其他战士稍有不同的装备。 |
| main_05 | 特战术师 | gamedata.description | 整合运动的法术作战人员，他配备的护甲使他拥有<@eb.key>一定防御</>。 |
| main_05 | 特战术师 | prts.enemy_level.talent | 不会攻击飞行单位 |
| main_05 | 特战术师组长 | gamedata.description | 整合运动的精英法术作战人员，他配备的护甲使他拥有<@eb.key>一定防御</>，并且能够同时攻击<@eb.key>两个</>目标。 |
| main_05 | 特战术师组长 | prts.enemy_level.talent | 可同时攻击2个目标，不会攻击飞行单位 |
| main_05 | 特战术师组长 | prts.enemy.ability | ·同时攻击两个目标 |
| main_05 | 暴鸰 | gamedata.description | <@eb.key>【飞行单位】</>携带有爆破弹头，将会在接近干员时投掷并造成群体物理伤害。 |
| main_05 | 暴鸰·G | gamedata.description | <@eb.key>【飞行单位】</>携带有大型爆破弹头，将会在接近干员时投掷并造成群体物理伤害。 |
| main_05 | 法术大师A1 | gamedata.description | <@eb.key>【飞行单位】</>飞行速度非常快，使用远程武器造成<@eb.key>法术</>伤害。 |
| main_05 | 法术大师A1 | prts.enemy.ability | ·飞行单位 |
| main_05 | 宿主士兵 | gamedata.description | 被不明意识控制身体的士兵，能快速自然恢复生命。 |
| main_05 | 宿主拾荒者 | gamedata.description | 被不明意识控制身体的拾荒者，能快速自然恢复生命。 |
| main_05 | 粉碎攻坚手 | gamedata.description | 整合运动的精英单位，穿着沉重的防爆护具，并且能在数次攻击后<@eb.key>晕眩</>我方单位。 |
| main_05 | 粉碎攻坚手 | prts.enemy.ability | ※攻击2次后，下一次攻击会{{术语/ba.stun/晕眩}}目标 |
| main_06 | 宿主士兵组长 | gamedata.description | 被不明意识控制身体的士兵组长，能快速自然恢复生命。 |
| main_06 | 宿主重装士兵 | gamedata.description | 被不明意识控制身体的重装士兵，能快速自然恢复生命。 |
| main_06 | 狂暴宿主士兵 | gamedata.description | 逐渐陷入狂乱的敌方士兵，<@eb.danger>攻击力很高</>，会持续损失生命。 |
| main_06 | 狂暴宿主士兵 | prts.enemy.ability | ·会逐渐损失生命 |
| main_06 | 狂暴宿主组长 | gamedata.description | 彻底失去理智的敌方士兵，<@eb.danger>攻击力很高</>，会持续损失生命。 |
| main_06 | 狂暴宿主组长 | prts.enemy.ability | ·会逐渐损失生命 |
| main_06 | 狂暴宿主投掷手 | gamedata.description | 逐渐陷入狂乱的敌方投掷手，<@eb.danger>攻击力很高</>，会持续损失生命。 |
| main_06 | 狂暴宿主投掷手 | prts.enemy.ability | ·会逐渐损失生命 |
| main_06 | 狂暴宿主掷骨手 | gamedata.description | 彻底失去理智的敌方投掷手，<@eb.danger>攻击力很高</>，会持续损失生命。 |
| main_06 | 狂暴宿主掷骨手 | prts.enemy.ability | ·会逐渐损失生命 |
| main_06 | 雪怪术师 | prts.enemy_level.talent | 不会攻击飞行单位 |
| main_06 | 雪怪术师组长 | prts.enemy_level.talent | 不会攻击飞行单位 |
| main_06 | 霜星，“冬痕” | gamedata.description | 雪怪小队领袖，为了最后的战斗解放了所剩无几的生命。 |
| main_07 | 宿主流浪者 | gamedata.description | 被不明意识控制身体的流浪者，能快速自然恢复生命。 |
| main_07 | 游击队猎犬 | gamedata.description | 穿戴轻量乌萨斯装甲的基础游击队战犬，拥有一定的防御性能，行动速度很快。 |
| main_07 | 游击队猎犬pro | gamedata.description | 穿戴轻量乌萨斯装甲的高级游击队战犬，攻击欲望比游击队战犬更强。 |
| main_07 | 游击队狙击手 | gamedata.description | 受到传令兵或爱国者<@eb.key>强化</>时，同时攻击<@eb.key>两个目标</> |
| main_07 | 游击队狙击手 | prts.enemy_level.talent | 不会攻击飞行单位<br>受到<战术命令>影响时，能够同时攻击两个目标 |
| main_07 | 游击队狙击手 | prts.enemy.ability | ·受到强化时，额外攻击一名目标 |
| main_07 | 游击队狙击手组长 | gamedata.description | 受到传令兵或爱国者<@eb.key>强化</>时，同时攻击<@eb.key>两个目标</> |
| main_07 | 游击队狙击手组长 | prts.enemy_level.talent | 不会攻击飞行单位<br>受到<战术命令>影响时，能够同时攻击两个目标 |
| main_07 | 游击队狙击手组长 | prts.enemy.ability | ·受到强化时，额外攻击一名目标 |
| main_07 | 游击队传令兵 | gamedata.description | 在场时，强化所有敌军的<@eb.key>攻击力</>与<@eb.key>防御力</> |
| main_07 | 游击队传令兵 | prts.enemy_level.talent | 在场时令全场敌方单位（无视其可选性）攻击力+10%、防御力+100，并获得<战术命令>效果 |
| main_07 | 游击队传令兵 | prts.enemy.ability | ·在场时，强化敌军攻击力与防御力 |
| main_07 | 游击队盾卫 | gamedata.description | 使自身容易受到我方单位的攻击，掩护敌军前进。 |
| main_07 | 游击队盾卫 | prts.enemy.ability | ·使自身容易受到敌人的攻击 |
| main_07 | 游击队突袭战士 | gamedata.description | 受到传令兵或爱国者<@eb.key>强化</>时，<@eb.key>攻击力</>大幅提升 |
| main_07 | 游击队突袭战士 | prts.enemy_level.talent | 受到<战术命令>影响时，攻击力+50% |
| main_07 | 游击队突袭战士 | prts.enemy.ability | ·能够从战场中降落<br>·受到强化时，攻击力大幅提升 |
| main_07 | 游击队突袭战士组长 | gamedata.description | 受到传令兵或爱国者<@eb.key>强化</>时，<@eb.key>攻击力</>极大幅提升 |
| main_07 | 游击队突袭战士组长 | prts.enemy_level.talent | 受到<战术命令>影响时，攻击力+80% |
| main_07 | 游击队突袭战士组长 | prts.enemy.ability | ·能够从战场中降落<br>·受到强化时，攻击力极大幅提升 |
| main_07 | 游击队萨卡兹战士 | gamedata.description | 接触脉冲波时，<@eb.key>不受伤害</>且攻击切换成<@eb.key>法术伤害</> |
| main_07 | 游击队萨卡兹战士 | prts.enemy.ability | ·接触脉冲波时，不受伤害且攻击切换成法术伤害 |
| main_07 | 游击队萨卡兹战士组长 | gamedata.description | 接触脉冲波时，<@eb.key>不受伤害</>且攻击切换成<@eb.key>法术伤害</> |
| main_07 | 游击队萨卡兹战士组长 | prts.enemy.ability | ·接触脉冲波时，不受伤害且攻击切换成法术伤害 |
| main_07 | 雇佣军萨卡兹战士 | gamedata.description | 接触脉冲波时，<@eb.key>不受伤害</>且攻击切换成<@eb.key>法术伤害</> |
| main_07 | 雇佣军萨卡兹战士 | prts.enemy.ability | ·接触脉冲波时，不受伤害且攻击切换成法术伤害 |
| main_07 | 游击队萨卡兹术师 | gamedata.description | 周期性对周围单位造成相当于攻击力的法术伤害。接触脉冲波时，<@eb.key>不受伤害</>且攻击<@eb.key>范围扩大</> |
| main_07 | 游击队萨卡兹术师 | prts.enemy.ability | ·周期性施法，对周围所有单位造成相当于攻击力的法术伤害<br>·接触脉冲波时，不受伤害且攻击范围扩大 |
| main_07 | 游击队萨卡兹术师组长 | gamedata.description | 周期性对周围单位造成相当于攻击力的法术伤害。接触脉冲波时，<@eb.key>不受伤害</>且攻击<@eb.key>范围扩大</> |
| main_07 | 游击队萨卡兹术师组长 | prts.enemy.ability | ·周期性施法，对周围所有单位造成相当于攻击力的法术伤害<br>·接触脉冲波时，不受伤害且攻击范围扩大 |
| main_07 | 雇佣军萨卡兹术师 | gamedata.description | 周期性对周围单位造成相当于攻击力的法术伤害。接触脉冲波时，<@eb.key>不受伤害</>且攻击<@eb.key>范围扩大</> |
| main_07 | 雇佣军萨卡兹术师 | prts.enemy.ability | ·周期性施法，对周围所有单位造成相当于攻击力的法术伤害<br>·接触脉冲波时，不受伤害且攻击范围扩大 |
| main_08 | 感染者纠察官 | gamedata.description | 可使用<@eb.key>远程武器</>攻击乌萨斯平民与斗士塔露拉 |
| main_08 | 感染者纠察官 | prts.enemy.ability | ·可使用远程武器攻击<乌萨斯平民>与<斗士塔露拉> |
| main_08 | 感染者高级纠察官 | gamedata.description | 可使用<@eb.key>远程武器</>攻击乌萨斯平民与斗士塔露拉 |
| main_08 | 感染者高级纠察官 | prts.enemy.ability | ·可使用远程武器攻击<乌萨斯平民>与<斗士塔露拉> |
| main_08 | 乌萨斯裂兽 | gamedata.description | 乌萨斯军训练的作战生物 |
| main_08 | 乌萨斯突袭弩手 | gamedata.description | 配备了威力强大的弩箭 |
| main_08 | 乌萨斯突袭弩手 | prts.enemy.ability | ·能够从战场中降落 |
| main_08 | 乌萨斯着铠术师 | gamedata.description | 乌萨斯军中的基础术师 |
| main_08 | 帝国炮火先兆者 | gamedata.description | 乌萨斯军炮兵术师操作的无人机，装甲厚重，材质坚实 |
| main_08 | 帝国炮火先兆者 | prts.enemy.ability | ·飞行单位 |
| main_08 | 帝国炮火中枢先兆者 | gamedata.description | 乌萨斯军炮兵术师操作的无人机中枢，装甲厚重，材质坚实 |
| main_08 | 帝国炮火中枢先兆者 | prts.enemy.ability | ·飞行单位 |
| main_08 | “皇帝的利刃” | gamedata.description | 两只穿着制服的恐怖精怪，正饶有兴趣地观察着塔露拉。对<@eb.key>斗士塔露拉</>永久施加【削弱】(<@eb.key>防御力与法抗大幅降低</>） |
| main_08 | “皇帝的利刃” | prts.enemy.ability | ·无法被攻击、消失时不会扣除目标生命<br>·对<斗士塔露拉>永久施加【削弱】(防御力与法抗大幅降低） |
| main_08 | 塔露拉 | gamedata.description | 令人捉摸不透的整合运动领袖。 |
| main_08 | “不死的黑蛇” | gamedata.description | 无数次死去也不曾自乌萨斯土地上消失的古老意志。 |
| main_08 | 乌萨斯平民 | prts.enemy.ability | ·撤回保护目标时不扣除目标生命，死亡时扣除目标生命<br>·不计入歼灭数 |
| main_09 | 深池侦察犬 | prts.enemy.ability | ※{{术语/ba.refraction/折射}} |
| main_09 | 深池侦察兵 | prts.enemy.ability | ※{{术语/ba.refraction/折射}} |
| main_09 | 深池狙击手 | prts.enemy.ability | ※{{术语/ba.refraction/折射}} |
| main_09 | 深池暗影术师 | prts.enemy.ability | ※{{术语/ba.refraction/折射}} |
| main_09 | 深池重甲卫士 | prts.enemy.ability | ※{{术语/ba.refraction/折射}} |
| main_09 | 深池飞行兵 | prts.enemy.ability | ·{{术语/ba.float/近地悬浮}} |
| main_09 | 深池焚毁者 | gamedata.description | 技能期间持续造成法术伤害和<@eb.key>灼燃损伤</>；<@eb.key>死亡时爆炸</>造成法术伤害，并击倒周围的<@eb.key>破碎支柱</>与其他<@eb.key>深池焚毁者</> |
| main_09 | 深池焚毁者 | prts.enemy.ability | ·技能期间持续造成法术和{{术语/ba.dt.burning/灼燃损伤}}<br>※死亡时爆炸造成法术伤害，并击倒周围的破碎支柱与其他<深池焚毁者> |
| main_09 | 深池塑能术师 | gamedata.description | 操纵沿地面移动的<@eb.key>净浊之焰</>。<@eb.key>净浊之焰</>遇到我方近战单位后爆炸造成法术伤害和<@eb.key>灼燃损伤</>，其伤害随移动距离减小 |
| main_09 | 深池塑能术师 | prts.enemy.ability | ·操纵沿地面移动的<净浊之焰>，遇到我方近战单位后爆炸，对周围造成法术和{{术语/ba.dt.burning/灼燃损伤}}，其伤害随移动距离减小 |
| main_09 | 蔓德拉 | gamedata.description | 操纵岩石的术师。她来自维多利亚的阴影深处，誓要将过去从贵族们手下受过的屈辱悉数奉还。 |
| main_10 | 深池侦察队长 | prts.enemy.ability | ※{{术语/ba.refraction/折射}} |
| main_10 | 深池狙击队长 | prts.enemy.ability | ※{{术语/ba.refraction/折射}} |
| main_10 | 渴血的子裔 | gamedata.description | 攻击造成<@eb.key>法术伤害</>，并恢复攻击伤害一定比例的生命。 |
| main_10 | 渴血的子裔 | prts.enemy.ability | ·攻击时恢复攻击伤害一定比例的生命 |
| main_10 | 萨卡兹王庭军战士 | gamedata.description | 攻击造成<@eb.key>法术伤害</>与<@eb.key>凋亡损伤</>。 |
| main_10 | 萨卡兹王庭军战士 | prts.enemy_level.talent | 每次攻击附加相当于攻击力37%的凋亡损伤 |
| main_10 | 萨卡兹王庭军战士 | prts.enemy.ability | ·攻击造成{{术语/ba.dt.apoptosis/凋亡损伤}} |
| main_10 | 萨卡兹王庭军精锐战士 | gamedata.description | 攻击造成<@eb.key>法术伤害</>与<@eb.key>凋亡损伤</>。 |
| main_10 | 萨卡兹王庭军精锐战士 | prts.enemy_level.talent | 每次攻击附加相当于攻击力37%的凋亡损伤 |
| main_10 | 萨卡兹王庭军精锐战士 | prts.enemy.ability | ·攻击造成{{术语/ba.dt.apoptosis/凋亡损伤}} |
| main_10 | 曼弗雷德 | gamedata.description | 卡兹戴尔军事委员会成员，年轻的萨卡兹将军。使用施术单元“提卡兹之根”与特雷西斯亲授的剑术作战。<@eb.key>攻击时为伦蒂尼姆城防副炮充能</>。 |

## 八 · 具名 unported 登记（Go 的欠账，**登记 ≠ 已修复**）

这是第 27 套**自己的登记表**（`tools/check_enemy_mech_go.py` 的 `NAMED_UNPORTED_KEYS`），
2026-09-24 父会话裁定后落地。登记的是「**Go 读了黑板、填进了 `EnemyStats`、
模拟里没人读**」那一类——它们**不是已修复**，是**已知行为分歧**。

**每条的四个槽**：键 → Go 字段名 → 读取点（文件:行，**现算**）→
判它没有行为落点的判据 → 旁证（引擎自己承认过的话，有就写）。

| 键 | Go 字段 | 读取点 | 为什么没有行为落点（判据） | 旁证 |
|---|---|---|---|---|
| `AuraHit.hp_ratio` | `AuraHitRatio` | `enemy_mech.go:133` | go.behaviour(AuraHitRatio) 为空 | — |
| `DeathPassive.cnt` | `DeathCnt` | `enemy_mech.go:129` | go.behaviour(DeathCnt) 为空 | 装置那一半另有 unsupported.go:121 的 death_token 线 |
| `DeathPassive.token_key` | `DeathToken` | `enemy_mech.go:126` | go.behaviour(DeathToken) 为空 | rios-sim/unsupported.go:121（unportedLines 的 death_token） |
| `PassiveM2.dhnzzh_clean_water.magic_resistance` | `Pm2CleanRes` | `enemy_mech.go:163` | go.behaviour(Pm2CleanRes) 为空 | — |
| `PassiveM2.dhnzzh_clean_water.move_speed` | `Pm2CleanMove` | `enemy_mech.go:164` | go.behaviour(Pm2CleanMove) 为空 | — |
| `PassiveM2.value` | `Pm2PollutThreshold` | `enemy_mech.go:167` | go.behaviour(Pm2PollutThreshold) 为空 | — |
| `Passive_Hit.extra_value` | `PhitExtra` | `enemy_mech.go:152` | go.behaviour(PhitExtra) 为空 | — |
| `Passive_Hit.other_cnt` | `PhitWeightCnt` | `enemy_mech.go:154` | go.behaviour(PhitWeightCnt) 为空 | rios-sim/sim.go:2826-2829（Go 侧没有重量字段、故不减，写在 `docs/uncertainties.md` 的口径里） |
| `SpeedUp.cooldown` | `SpeedupCooldown` | `enemy_mech.go:139` | go.behaviour(SpeedupCooldown) 为空 | rios-sim/sim.go:2789-2790（同上） |
| `SpeedUp.duration` | `SpeedupDuration` | `enemy_mech.go:138` | go.behaviour(SpeedupDuration) 为空 | rios-sim/sim.go:2789-2790（同上） |
| `SpeedUp.move_speed` | `SpeedupMove` | `enemy_mech.go:137` | go.behaviour(SpeedupMove) 为空 | rios-sim/sim.go:2789-2790（引擎自己写着「速度提升（SpeedUp.*）还没接，接的时候加在这里，不要另开调用点」） |

### 8.1 逐条的出现处（键 × 章 × 敌人）

| 章 | 敌人 | 键 | Go 字段 | Python 落点 |
|---|---|---|---|---|
| act31side_06 | 田鼷力士 | `AuraHit.hp_ratio` | AuraHitRatio | ak_tactic/battle/sim.py:1615 |
| act31side_06 | 田鼷飞贼 | `DeathPassive.cnt` | DeathCnt | ak_tactic/battle/sim.py:1614 |
| act31side_06 | 田鼷飞贼 | `DeathPassive.token_key` | DeathToken | ak_tactic/battle/sim.py:1613 |
| act31side_06 | 田鼷力士 | `SpeedUp.cooldown` | SpeedupCooldown | ak_tactic/battle/sim.py:1309 |
| act31side_06 | 田鼷力士 | `SpeedUp.duration` | SpeedupDuration | ak_tactic/battle/sim.py:1308 |
| act31side_06 | 田鼷力士 | `SpeedUp.move_speed` | SpeedupMove | ak_tactic/battle/sim.py:1306 |
| act31side_09 | “祟” | `PassiveM2.dhnzzh_clean_water.magic_resistance` | Pm2CleanRes | ak_tactic/battle/sim.py:1637 |
| act31side_09 | “祟” | `PassiveM2.dhnzzh_clean_water.move_speed` | Pm2CleanMove | ak_tactic/battle/sim.py:1638 |
| act31side_09 | “祟” | `PassiveM2.value` | Pm2PollutThreshold | ak_tactic/battle/sim.py:1641 |
| act31side_09 | “祟” | `Passive_Hit.extra_value` | PhitExtra | ak_tactic/battle/sim.py:1629 |
| act31side_09 | “祟” | `Passive_Hit.other_cnt` | PhitWeightCnt | ak_tactic/battle/sim.py:1299 |
| act31side_ex02 | 田鼷猛士 | `AuraHit.hp_ratio` | AuraHitRatio | ak_tactic/battle/sim.py:1615 |
| act31side_ex02 | 田鼷大盗 | `DeathPassive.cnt` | DeathCnt | ak_tactic/battle/sim.py:1614 |
| act31side_ex02 | 田鼷大盗 | `DeathPassive.token_key` | DeathToken | ak_tactic/battle/sim.py:1613 |
| act31side_ex02 | 田鼷猛士 | `SpeedUp.cooldown` | SpeedupCooldown | ak_tactic/battle/sim.py:1309 |
| act31side_ex02 | 田鼷猛士 | `SpeedUp.duration` | SpeedupDuration | ak_tactic/battle/sim.py:1308 |
| act31side_ex02 | 田鼷猛士 | `SpeedUp.move_speed` | SpeedupMove | ak_tactic/battle/sim.py:1306 |

### 8.2 为什么**不**进 `rios-sim/unsupported.go` 的拒跑线

父会话第 3 条附加条件。`unsupported.go` 的 `unportedLines`／`gateLineWhy` 是**闸门**：
一旦登记进去，**任何含这些敌人的关卡都会被整关拒跑**（怀黍离全活动，以及任何复用了
田鼷 / 祟 / 天桩一族的关）。而：

* 这 11 条里绝大多数是**边角量**（蜕皮的额外项、明识形态的清水抗性、加速的冷却），
  把它们换成一整关拒跑，代价远大于收益；
* 拒跑会让这些关卡**彻底失去判据**（本仓记过：拒跑与「跑了但不一致」是两种不同的红，
  前者什么也没证明）；
* 真正兜底的另有其人——见 8.3。

⇒ **这是裁定，不是遗漏**：登记进第 27 套的表，**不进闸门表**。

### 8.3 与端到端判据的**互相兜底**（这句话决定严重性）

这 11 条是**已知行为分歧**，不是「已修复」。它们**目前不影响 24 份夹具的判决**，
证据在**另一套判据**里：

> `tools/check_sim_via_python_go.py` 的端到端那一条 ——
> **24 / 24 份夹具的判决与 `d4ddc4c` 冻结基线逐键相同**（禁桶：拒跑 0、判决分歧 0）。

**两条是互相兜底的**：第 27 套保证这些分歧**被登记、不被绿盖住**；
端到端保证它们**至今没让某一份夹具的判决变样**。若某天真有一条开始影响判决，
**端到端那一条会红** —— 那一刻就不再是「已知行为分歧」，而是一次真回归。
（台账里那两行：`docs/go-selfsufficiency.md` 的「敌方机制」与「调用链」。）

## 九 · 附：全缓存一跑（320 个关卡键 ＝ 159 份不同内容）

第 0～10 章真红为 0；把**缓存可达的全部关卡键**（320 个键 ＝ **159 份不同内容** ×
难度与别名标签）一起跑，欠账才现形。这一跑的口径与上面完全一样，只是关卡清单不同。

* 结论行：`MECH-VERDICT red=0 unported=17 common=238 go=41 go_only=0 undecidable=194`
* 复现：`python tools\check_enemy_mech_go.py --md out/_mech_all.md`

真红（**未登记**的 Go 欠账）——逐条。本跑为 **0 条**：
那 17 个键次**全部**已在第八节具名登记（这是裁定②的结果，不是「都修好了」）。

| 章 | 敌人 | 键 | 原因 | 下游字段 | Go 侧 | Python 落点 |
|---|---|---|---|---|---|---|

## 十 · 复现与守卫

```
python tools\check_enemy_mech_go.py                       # 默认：缓存可达的全部关卡
python tools\check_enemy_mech_go.py main_00-01 main_02-07  # 只跑给定清单
python tools\check_enemy_mech_go.py --mutate               # 反向守卫（四组腿）
python tools\check_enemy_mech_go.py --md out/x.md          # 另写一份逐章 markdown
```

* 退出码：`0` 全绿（无真红）／`1` 有真红／`3` 仪器缺输入（含**登记与源码脱节**）／
  `5` 自己崩了（与业务态不重叠）。**具名 unported、共同边界、判不了都不计入 rc。**
* **反向守卫**（合成键 ＋ 登记保活，**不依赖取证范围**）四组腿，本跑全成立：

```
✓ 基线：两侧都没有落点                      期望 COMMON   实得 COMMON
✓ ③ 给共同边界注入 Go 消费（⇒ 绿，不许红）      期望 GO_ONLY  实得 GO_ONLY
✓ ② 打开 Python 落点（共同边界 ⇒ 真红）        期望 RED      实得 RED
✓ ② 关掉后回到共同边界                      期望 COMMON   实得 COMMON
✓ ①a 真红（Go 有读取点、无行为落点）           期望 RED      实得 RED
✓ ①a 抹掉 Go 读取点后仍为红                  期望 RED      实得 RED
✓ ①b 补上 Go 行为落点后转绿                  期望 GO       实得 GO
✓ ④ 登记键 AuraHit.hp_ratio 起初有效          期望 True     实得 True
✓ ④ 补上行为落点后该登记**消失**               期望 True     实得 True
✓ ④ 同一步不得再判 unported                 期望 GO       实得 GO
✓ ④ 撤掉后登记恢复                          期望 True     实得 True
MECH-MUTATE guard=OK legs=11 failed=0
```

  `①a`／`①b` 是 **Go 腿两个方向**的分辨力；`②` 是 **Python 腿**；
  `③` 保证「把共同边界错当欠账」会被判出来；
  **`④` 是「出处不许过期」**（父会话第 4 条附加条件）：把某条登记的行为落点补上，
  那条登记**必须当场消失**、键不得再判 unported；撤掉后登记恢复。
  没有 `④`，登记表会退化成**永久的假绿**。
* **登记表的三条腿每次现算**：读取点还在不在、字段名还对不对、字段是否已有行为落点。
  任何一条不成立 ⇒ 印 `MECH-STALE-REGISTRY`（该条当场失效、键退回真红）或
  `MECH-BROKEN-REGISTRY`（登记与源码脱节 ⇒ **rc=3**，不许带着过期登记往下跑）。
* 机读行一律 ASCII（敌人名/键名里的非 ASCII 退化成 `\uXXXX`），
  `--md` 另写一份逐章表格（本文件第二、四～九节即由它装配）。

