# 四星档 6 关为何算不出来（`enemy_talent_blackb_mul` / `enemy_skill_blackb_mul`）

> 只读调查。**没有**改 `rios-sim/**`、`ak_tactic/**`、`fixtures/**`、`data/**`、`tools/**`，
> 也没有 build。实验脚本在 `out/`：`zz_fourstar.py`、`zz_fourstar_go.py`、`zz_bb_dump.py`、
> `zz_key_scan.py`、`zz_bb_hit.py`、`zz_0914.py`（各自的原始读数见同名 `.log`）。

## 0. 结论速览

1. **这两个键住在关卡 JSON 的顶层 `runes` 数组里**（每条是 `{key, difficultyMask, blackboard}`），
   **不在** `options` / `optionalRunes` / 关卡自带的 `enemies` / 敌人的 `prefab`。
   它们的作用是**改写敌人的天赋/技能黑板**（所以叫 blackb_mul），改完必须重跑派生。
2. **参照实现有落点，而且分两半**：解析在 `ak_tactic/frontend/stage_mul.py`，
   真正写黑板＋重跑派生在 `ak_tactic/gamedata/enemy.py:691-752`，
   挂载点是模拟器构造时包在**取敌人属性的出口**上（`ak_tactic/battle/sim.py:403-411`）。
3. **Go 侧拒跑是一条具名守卫**：`rios-sim/spawns.go:832-846` 调
   `UnportedRuneMuls`（`rios-sim/stagemul.go:196-204`，判据是 `Kind` 不等于 `attr`）。
   现有代码把两类黑板乘数**一条都没实现**，而 **`attr` 那一条已经实现**（`ApplyAttrMuls`）。
   ⇒ 性质是「缺一个乘区（外加它要求的那次重派生）」，**不是缺一整套机制**。
4. **影响面计数（两层独立来源一致）**：主干 121 个 `main_*#f#` 里，
   四星档下 Go **ok = 115 / 拒跑 = 6**；两个键对 `FOUR_STAR` 生效的关数分别是
   **talent 5 关 / skill 2 关 / 并集 6 关**（`main_09-17#f#` 两条都有）。
   剩下 115 关**根本没有这两个键**（`仅别的难度有 = 0`，不是被 `difficultyMask` 挡掉），
   所以它们确实不受影响——不是「恰好没事」。
5. **补法形状**：**接一个乘区 ＋ 调一次已有的重派生**，不需要重跑敌人派生、不需要动数据。
   Go 侧已经把重派生抽成了可再调的函数（`enemy_derive.go:236-242` 明写这件事），
   缺口只有「谁去乘」和「乘完有没有再调它」。

## 1. 仪器与取证范围

| 项 | 值 |
|---|---|
| `RIOS_SIM_BIN` | `out/acceptance/rios-sim-stage3.exe` |
| sha256 | `603e656be5c42e10ecc7db271fbec31282c5c98fe5d2a92eef0d7f16992f0e97`（sha16 `603e656be5c42e10`） |
| mtime | 2026-09-25T22:05:11 |
| `RIOS_DATA` | `data/gamedata` |

⚠ **仪器在这次调查中途被换过**：本次会话开始时的 exe 是 sha16 `c7fc71bb304ef618`（mtime 20:37），
22:05 出现了新的一份。**本文件里所有 Go 读数都取自上面那一份 `603e656b…`**，
换前那一次的读数（拒跑清单）与换后一致，但不要把两者混成一个时刻的数。

取证范围：
* 关卡数据：`data/gamedata/map.ark-nights.com/levels/`，关卡 id → 文件走
  `data/gamedata/_level_index.json` 的 `data_path`（**同一份文件被普通档与四星档共用**，
  难度只住在索引条的 `difficulty` 字段里）。
* 敌人数据：`.../levels/enemydata/enemy_database.json`（2154 个 `Key`）。
* 代码：`rios-sim/`（Go 当前实现）与 `ak_tactic/`（只读参照实现）两棵树。

## 2. 问题一：这两个键在哪一层

**答案：关卡 JSON 顶层的 `runes` 数组**，每条形如

```
{"difficultyMask": "FOUR_STAR", "key": "enemy_talent_blackb_mul",
 "professionMask": 1023, "buildableMask": "ALL", "blackboard": [ … ]}
```

`blackboard` 里两类条目：**选择器**（`enemy` 的 `valueStr` 是 `|` 分隔的敌人 id；`skill` 的
`valueStr` 是技能 `prefabKey`）与**系数**（其余键 → 乘数，可正可 0）。

取证（`out/zz_fourstar.raw.log`）：对每一关整份 JSON 逐顶层段搜这两个字符串，
命中段**只有 `runes`**，且 `options`、`optionalRunes`、`enemies`、`enemyDbRefs` 一律 0 次。
（`professionMask` / `buildableMask` 两侧解析器都不读——`stage_mul.py` 与 `stagemul.go` 都只看
`key` / `difficultyMask` / `blackboard`。）

### 6 关的原文片段（逐字，未删节）

`main_06-05#f#`（`obt/main/level_main_06-05.json`，`runes[2]`）：

```json
{"difficultyMask": "FOUR_STAR", "key": "enemy_talent_blackb_mul",
 "professionMask": 1023, "buildableMask": "ALL",
 "blackboard": [{"key": "periodic_damage.damage", "value": 0, "valueStr": null},
                {"key": "enemy", "value": 0,
                 "valueStr": "enemy_1062_rager|enemy_1062_rager_2|enemy_1063_rageth|enemy_1063_rageth_2"}]}
```

`main_08-12#f#`（`…main_08-12.json`，`runes[2]`）：

```json
{"difficultyMask": "FOUR_STAR", "key": "enemy_talent_blackb_mul",
 "professionMask": 1023, "buildableMask": "ALL",
 "blackboard": [{"key": "enemy", "value": 0, "valueStr": "enemy_1114_rgrdmn"},
                {"key": "vampire.heal_scale", "value": 2, "valueStr": null}]}
```

`main_08-14#f#`（`…main_08-14.json`，`runes[2]`，**注意是 skill 那一条**）：

```json
{"difficultyMask": "FOUR_STAR", "key": "enemy_skill_blackb_mul",
 "professionMask": 1023, "buildableMask": "ALL",
 "blackboard": [{"key": "enemy", "value": 0, "valueStr": "enemy_1514_smephi"},
                {"key": "skill", "value": 0, "valueStr": "Poison"},
                {"key": "damage", "value": 2, "valueStr": null}]}
```

`main_08-16#f#`（`…main_08-16.json`，`runes[2]`）：

```json
{"difficultyMask": "FOUR_STAR", "key": "enemy_talent_blackb_mul",
 "professionMask": 1023, "buildableMask": "ALL",
 "blackboard": [{"key": "enemy", "value": 0, "valueStr": "enemy_1503_talula"},
                {"key": "halfhp.hp_ratio", "value": 2, "valueStr": null}]}
```

`main_09-14#f#`（`…main_09-14.json`，`runes[2]`，**没有 `enemy` 选择器 ⇒ 作用于全场敌人**）：

```json
{"difficultyMask": "FOUR_STAR", "key": "enemy_talent_blackb_mul",
 "professionMask": 1023, "buildableMask": "ALL",
 "blackboard": [{"key": "Weaken.atk", "value": 0, "valueStr": null}]}
```

`main_09-17#f#`（`…main_09-17.json`，`runes[2]` 与 `runes[4]`，**两条都在**）：

```json
{"difficultyMask": "FOUR_STAR", "key": "enemy_skill_blackb_mul",
 "professionMask": 1023, "buildableMask": "ALL",
 "blackboard": [{"key": "enemy", "value": 0, "valueStr": "enemy_1523_mandra"},
                {"key": "PetrifiedRay.atk_scale", "value": 1.2, "valueStr": null}]}
```
```json
{"difficultyMask": "FOUR_STAR", "key": "enemy_talent_blackb_mul",
 "professionMask": 1023, "buildableMask": "ALL",
 "blackboard": [{"key": "enemy", "value": 0, "valueStr": "enemy_1523_mandra"},
                {"key": "StoneSkin_2.atk_scale", "value": 1.5, "valueStr": null}]}
```

### 系数打到谁身上：逐键核查（`out/zz_key_scan.log`、`out/zz_bb_dump.log`）

⚠ **一条尺子自身的教训**：第一版脚本把黑板读在 `enemyData.attributes.blackboard` 上，
结果 2154 个敌人**全读成空黑板**，于是「六个键全都命中不到」看起来像是结论。
加了正对照才发现路径错了——黑板在 **`enemyData.talentBlackboard`**（`[{key,value,valueStr}]`）。
修正后的正对照：**2154 个敌人里档 0 黑板非空的有 1469 个**。下表是修正后的读数：

| 关 | kind | 选择器 | 键 ×系数 | 被点名敌人身上有吗 | 乘完变成 |
|---|---|---|---|---|---|
| `main_06-05#f#` | talent | 4 只 rager/rageth | `periodic_damage.damage` ×0 | 有（330 / 500 / 250 / …） | 0 |
| `main_08-12#f#` | talent | `enemy_1114_rgrdmn` | `vampire.heal_scale` ×2 | 有（1.5） | 3.0 |
| `main_08-14#f#` | skill | `enemy_1514_smephi` / 技能 `Poison` | `damage` ×2 | 有（技能黑板 `damage` = 50） | 100 |
| `main_08-16#f#` | talent | `enemy_1503_talula` | `halfhp.hp_ratio` ×2 | 有（0.5） | 1.0 |
| `main_09-14#f#` | talent | （空＝全场） | `Weaken.atk` ×0 | 全库只有 `enemy_1177_dufrbl(_2)` 有，而它**就在这一关的 `enemyDbRefs` 里** | 0 |
| `main_09-17#f#` | skill | `enemy_1523_mandra`（**无 `skill` 键**） | `PetrifiedRay.atk_scale` ×1.2 | **没有**：技能黑板里那个键叫 `atk_scale` | —— |
| `main_09-17#f#` | talent | `enemy_1523_mandra` | `StoneSkin_2.atk_scale` ×1.5 | 有（0.3） | 0.45 |

全库出现次数（作为「这条键是不是孤例」的旁证）：`periodic_damage.damage` 20 个敌人、
`vampire.heal_scale` 6、`halfhp.hp_ratio` 1、`Weaken.atk` 2、`StoneSkin_2.atk_scale` 1、
`PetrifiedRay.atk_scale` 0（技能侧同样 0）、裸 `damage` 在技能黑板 18 条。

## 3. 问题二：参照实现有没有落点

**有，而且是完整的一条链**（`ak_tactic/`，只读）：

| 环节 | 位置 |
|---|---|
| 解析（按难度消歧、键名归一化、拆选择器/系数） | `ak_tactic/frontend/stage_mul.py:105-170`（`_bb_pairs` / `_parse_one` / `parse_rune_muls`） |
| 老键名 `ebuff_attribute` → 新名 | 同文件 `:64-67` |
| 分发（attr / talent / skill 三支） | 同文件 `:173-202`（`apply_rune_muls`，talent → `rescale_talent_blackboard`，skill → `rescale_skill_blackboard`） |
| 挂在取数**出口**上 | 同文件 `:205-219`（`wrap_enemy_at`） |
| 挂载点 | `ak_tactic/battle/sim.py:403-411`（`self.rune_muls = parse_rune_muls(...)`；`self.enemy_at = wrap_enemy_at(enemy_at, self.rune_muls)`） |
| 天赋：乘黑板键 **＋ 重跑派生** | `ak_tactic/gamedata/enemy.py:691-711`（`rescale_talent_blackboard`；命中才 `derive_blackboard_fields()`） |
| 技能：按 `prefabKey` 点名、**重建**那一项再重跑派生 | 同文件 `:713-752`（`rescale_skill_blackboard`；`prefab_key` 为空直接返回 `[]`） |
| 派生本身 | 同文件 `:656-689`（`derive_blackboard_fields` / `derive_skill_fields`） |

两条纪律写在 `stage_mul.py` 的开头（`:23-29`）：**不许改库里的对象**（要 `clone()`）、
**不许只改黑板不重算派生**。

⚠ 但要说清一件事：**参照实现改到的那几个键，在它自己那里也没有消费者**。
两侧的派生表都只认固定几个前缀——Go `enemy_mech.go:31-34` 的 `mechPrefixes` 是
`Passive.` / `DeathPassive.` / `AuraHit.` / `SpeedUp.` / `Passive_Hit.` / `PassiveM2.` / `CheckAwake.`
七项，Python `mech_fields`（`enemy.py:276-323`）是同样七项；再加 `Reborn.` / `TotalAttack.` /
`Shield.` / `Talent1.` 与技能侧的 `Drink`（`PROSE_SKILL_ATTACK`，`enemy.py:193-201` 与
`rios-sim/enemy_derive.go:162-170` 两侧同表）。
本次这 6 条乘数打的键（`periodic_damage.` / `vampire.` / `halfhp.` / `Weaken.` /
`StoneSkin_2.` / 技能 `Poison` 的 `damage`）**一个都不在这几张表里**——
在 `ak_tactic/` 与 `rios-sim/` 两棵树里搜这六个名字，命中数都是 **0**。
所以参照实现在这 6 关上「乘是乘了，派生字段没变」：它没有拒跑，因为它
**不会把这件事当成错误**，而 Go 现在把它当成「算不了」而拒跑。

## 4. 问题三：Go 现在为什么拒跑

**拒跑点在 `rios-sim/spawns.go:832-846`**（`bad := UnportedRuneMuls(muls)` → `return out, fmt.Errorf(...)`，
`defs2` 是 `st.Difficulty`）。运行期那条错误的**原文**（verbatim，取自本机实测：

```
这一关在难度 FOUR_STAR 下有 Go 未实现的敌人修饰层（talent）：`enemy_talent_blackb_mul` / `enemy_skill_blackb_mul` 要改黑板并重跑派生，Go 侧一行都没有。**拒跑**而不是按普通档算——静默少乘系数会造出一份看着对的规格
```

括号里那个 `talent` / `skill` / `skill、talent` 就是归因（`main_08-14#f#` 是 `skill`，
`main_09-17#f#` 是 `skill、talent`，其余四条是 `talent`），它来自把命中的
`RuneMul.Kind` 用顿号连起来那一步。

判据在 `rios-sim/stagemul.go:196-204`：

```go
196: func UnportedRuneMuls(muls []RuneMul) []RuneMul {
197: 	out := []RuneMul{}
198: 	for _, m := range muls {
199: 		if m.Kind != "attr" {
200: 			out = append(out, m)
201: 		}
202: 	}
203: 	return out
204: }
```

也就是说：**`Kind` 等于 `attr` 那一类（`enemy_attribute_mul` / 老名 `ebuff_attribute`）已经实现了**
（`stagemul.go:206-247` 的 `ApplyAttrMuls`，挂在取数出口 `spawns.go:762-781` 的 `statsFor` 上），
**只有 `talent` / `skill` 两条没有**（`stagemul.go:17-27` 的注释把三条列成一张表，后两条写的就是
「未搬 ⇒ 拒跑」）。

**性质：缺一个乘区，不是缺一整套机制。** 依据是「乘完要重跑的那件事」Go 侧已经准备好了：

* 敌人的**原始天赋黑板**就带在规格对象上：`enemy.go:84`（`TalentBlackboard map[string]any`），
  且 `Clone()` 会深拷它（`enemy.go:388-397`）。
* 重派生已经是**独立、可再调**的函数：`enemy_derive.go:236-242`
  （`DeriveBlackboardFields`，注释原话是「**它的输出是纯函数**……所以关卡 runes 改了黑板之后
  这里必须能被再调一次」）。
* 缺的只是「谁去乘」：`statsFor` 只调 `ApplyAttrMuls`；`spawns` 造出来的规格里
  **根本不带原始黑板**（在 `spawns.go` 里搜 `talent_blackboard` 命中 0），
  所以今天这条乘数没有任何落点。

**难度是怎么定的（顺带一条硬事实）**：`spawns.go:1189-1202` 的 `loadStageWithRaw` 走索引
`ResolveLevel` 后传的是 **`entry.Difficulty`**，查询里给的 `difficulty` 对 `level` 口径**不生效**。
实测：拿 `main_06-05#f#` 配 `difficulty=NORMAL` 请求，照样按 FOUR_STAR 拒跑。
⇒ 「A 层拒跑」这个判决是**跟着关卡 id 走的**，不是调用方可以绕过的一个开关。

## 5. 问题四：影响面计数

两层独立来源，结论一致：

**（甲）数据侧**（扫 121 个 `main_*#f#` 的 `runes`，按 `difficultyMask` 判是否对本关难度生效；
`out/zz_fourstar.sweep.log`）：

| 键 | 对 FOUR_STAR 生效的关数 | 仅别的难度有 |
|---|---|---|
| `enemy_talent_blackb_mul` | **5** | 0 |
| `enemy_skill_blackb_mul` | **2** | 0 |
| （并集＝Go 拒跑集合） | **6** | — |
| `enemy_attribute_mul`（已实现） | 58 | 0 |
| `ebuff_attribute`（老名，已实现） | 62 | 0 |

**（乙）运行期**（把 121 个 id 一次性喂给 Go 的 `spawns`，`out/zz_fourstar_go.log`）：

```
★ FOUR_STAR 档：ok = 115，拒跑 = 6（对象 = 121 个 main_*#f#）
  拒跑清单 = ['main_06-05#f#', 'main_08-12#f#', 'main_08-14#f#',
             'main_08-16#f#', 'main_09-14#f#', 'main_09-17#f#']
  归因 kind：talent ×4、skill ×1（main_08-14#f#）、skill、talent ×1（main_09-17#f#）
```

**正对照（同一份关卡文件的普通档 id，去掉 `#f#`）**：6 关全部 `ok=True`，
`params.rune_muls = 0`、`params.stage_difficulty = NORMAL` ⇒ 拒跑确实只由四星档那几条 rune 引起，
关卡文件本身没问题。

⚠ **一个差点读错的地方**：第一次跑批时我把请求的 `id` 写成字符串，
Go 的 `request.id` 是 `int`，于是**每一条请求**都被拒成
`cannot unmarshal string into Go struct field request.id of type int`、回包的 `id` 恒为 0，
按 id 取回来全是空 ⇒ 眼看是「**121 关全拒跑**」。
这是**我方仪器的假读数**，由单发请求的抽查（返回的正是那条 talent 拒跑原文）抓出来。
⇒ 报「N 关全红」之前先证明**报数的那条路**是通的，这与工具返回什么无关。

**回答「115 个能过的关是不是真的不受影响」**：是，而且原因不是「恰好没事」——
它们的 `runes` 里**根本没有这两个键**（`仅别的难度有 = 0` 说明也不是被 `difficultyMask` 挡掉的，
是压根没有）。115 = 121 − 6，两边相等。这些关在四星档下带的同族 rune 只有属性乘数
（`enemy_attribute_mul` / `ebuff_attribute`），那一条 Go 已经实现并有行使计数。

## 6. 问题五：补法的形状（提纲，不含实现）

**最小改动＝接一个乘区 ＋ 调一次已有的重派生**；不需要重跑敌人派生、不需要改数据、
不需要动 `enemy_database.json` 或库里任何东西。理由：待乘的键、选择器、系数的解析**都已经在**
（`ParseRuneMuls` 已能解出 `Kind/Enemies/Skill/Factors`），重派生**已经是可再调的函数**。

**改哪几处（按依赖顺序）**

1. `rios-sim/stagemul.go` —— 新增 `ApplyBBMuls(es *EnemyStats, muls []RuneMul) (*EnemyStats, hits)`：
   * 选择器判据与 `ApplyAttrMuls` 同一套（`Enemies` 为空＝全场；否则 `Enemies[es.EnemyID]`）；
   * **talent 支**：命中任何一条时先 `es.Clone()`（库里那份**不许写回**），
     对 `Factors` 里**确实存在于 `es.TalentBlackboard` 的键**做 `v * factor`，
     一个键都没命中就**什么都不做**（对齐 `rescale_talent_blackboard` 的 `hits` 语义：
     键不在黑板上＝数据与敌人对不上，不是错误，但要能被计数看见）；
   * **skill 支**：对齐 `rescale_skill_blackboard`——`Skill` 为空直接返回空命中；
     否则只改 `prefabKey == Skill` 的那一项，且**必须重建**那一项的 `blackboard` 切片
     （`Clone()` 对 `Skills` 只做切片浅拷，`enemy.go:398`，就地改会污染全库缓存）；
     同样跳过带 `valueStr` 的条目；
   * 只要有命中，**最后调一次 `es.DeriveBlackboardFields()`**（`enemy_derive.go:242`）。
2. `rios-sim/spawns.go:762-781` —— `statsFor` 里在 `ApplyAttrMuls` 之后接上 `ApplyBBMuls`；
   顺序与权威一致（权威是把所有 mul 依次作用在同一个出口上，`apply_rune_muls` 的循环）。
3. `rios-sim/spawns.go:832-846` —— 撤掉那条 blanket 拒跑。
   建议保留一条**更窄的守卫**：只对「`skill` 类但 `Skill` 选择器为空」这种必然空转的写法
   给出**具名警告并计数**（`main_09-17#f#` 的那条就是），而不是拒跑——权威实现也只当它是空操作。
   `UnportedRuneMuls` 可以退休或改成上面这条窄判据。
4. **行使可见**：`spawnCounter` 上加两三个计数（如 `talent_mul_applied` / `bb_mul_hits` /
   `bb_mul_missing_keys`）。理由就是本仓库反复吃过的那个教训：键非空 ≠ 行使过，
  而「乘数是 0 次命中」与「乘数没接」在读数上长得一模一样。
5. **验收判据**（三件齐才算接上）：
   * `spawns` 对 121 个 `main_*#f#` 全部 `ok=True`（今天的 6 红变绿）；
   * 与**参照实现**逐字对拍这 6 关的规格：`ak_tactic` 侧 `build_spec`（difficulty=FOUR_STAR）
     与 Go 侧 `buildspec` 的 `spawns` 必须一致——**这一步是这条改动唯一能证伪它的判据**；
   * 反例守卫：造一条**键确实喂派生字段**的合成 rune（例如把某个敌人的
     `Passive.extra_value` ×2），断言 `passive_pollut` 跟着变——今天这 6 关打的键
     没有一个喂派生字段（见 §3 末尾），只用这 6 关**验不出「重派生」这一步有没有接对**。
     现成的正例有两处可以取材：`docs/activity.md:105` 记的 `act31side_ex07`
     （「四星档把污染 +5/+15 乘成 +10/+30」），以及 `ak_tactic/frontend/stage_mul.py:16-18`
     写明的落点——给 `enemy_1390_dhsbr_2|enemy_1392_dhshld_2` 的 `Passive.extra_value`
     乘 2。本次顺带核过：`enemy_1390_dhsbr_2` 档 0 的天赋黑板是
     `Passive.extra_value` = 5 与 `Passive.range_radius` = 1 两项，而 `passive_pollut` 正是
     两侧都建模了的派生字段（`enemy_mech.go:119-123`），所以它是一条**能红得起来**的夹具。

**要不要重跑派生？** 要，但「重跑」指的只是**运行期再调一次 `DeriveBlackboardFields()`**，
不是去重建 `enemy_database.json` 或任何落盘派生物。这一点 Go 侧已经就位，
缺口在「谁去乘」这一步。

## 7. 未核 / 欠账

* **`main_09-17#f#` 的 skill 那条（`PetrifiedRay.atk_scale` ×1.2）是一条空转乘数**：
  技能黑板里的键名是 `atk_scale`，而 rune 写的是 `PetrifiedRay.atk_scale`；
  参照实现的 `rescale_skill_blackboard` 因为这条**没有 `skill` 选择器**而直接返回 `[]`，
  所以连「键名对不上」这一步都走不到。**这是数据与敌人对不上**，我只登记，不擅自解释成谁写错了。
* **这 6 条乘数的键有没有落在「还没建模」的机制上**：我只取证到「两棵树里搜不到这几个名字」
  （命中 0），因此判定它们**今天**没有消费者。**没有**去核「游戏里这些机制实际怎么作用」，
  也没有核「将来有人建模 `halfhp` / `vampire` 时，这条乘数会不会立刻变得必须」。
* `professionMask`（1023）/ `buildableMask`（ALL）两侧都不读——**未核**这会不会在别的关卡类型上
  造成语义差（本次 6 条的取值看起来是「无限制」）。
* 主干 262 之外的关卡 id（索引里 `main_*` 前缀共 434 个、其余活动 `#f#` 780 − 121 个）
  **未核**；本文件的所有计数只覆盖 `main_*#f#` 这 121 个。

---

## 8. 落地记录（2026-09-26 补齐两支；仪器 `F4D389568ED8780F`）

> §1～§7 是**改动前**的调查（仪器 `603e656be5c42e10`）。本节的读数**只对本节的仪器负责**，
> 与上面几节的数**不许相加、不许比红绿**。探针在 `out/`（不入库）：`zz_fs_probe.py`（影响面，可切 before/after）、
> `zz_bbmul_check.py`（行使计数＋反例守卫）、`zz_0914_why.py`（§8.4 那条归因）。

### 8.1 改了什么（四处）

| 文件 | 改动 |
| --- | --- |
| `rios-sim/stagemul_bb.go`（**新增**） | `ApplyBBMuls`（talent / skill 两支）＋ `BBMulHits`（行使账）＋ `rescaleSkillBlackboard` ＋ `EmptySelectorSkillMuls` |
| `rios-sim/spawns.go` | `statsFor` 在 `ApplyAttrMuls` **之后、同一个取数出口上**接 `ApplyBBMuls`；5 个行使计数器；**撤掉 blanket 拒跑**，换成更窄的守卫 |
| `rios-sim/stagemul.go` | 三条 rune 的表全部改成「已搬」；`UnportedRuneMuls` **带痕迹退休**（函数删除，原位留一段说明它为什么退休、被什么顶替） |
| `tools/check_spawns_go.py` | §3b **翻向**：从「Go 必须拒跑并点名」改成三件（见 8.3） |

两条纪律的落点：`Clone()` 只在**真要改第一处**时发生（库里那份绝不写回）；有命中就调一次
`DeriveBlackboardFields()`；技能支**重建**那一项的 `blackboard` 切片（`Clone()` 对 `Skills` 只做浅拷，
`enemy.go:398`）⇒ 不重建就会污染全库缓存。

### 8.2 读数

| 项 | 改前（`2E9D706D1290D5C0`） | 改后（`F4D389568ED8780F`） |
| --- | --- | --- |
| `main_*#f#` 121 关 | ok **115** / 拒跑 **6** | ok **121** / 拒跑 **0** |
| `act31side` `#f#` 12 关 | ok 6 / 拒跑 6 | ok **8** / 拒跑 **4**（剩下 4 个是**另一回事**，见 §8.4） |
| `main_16-07#s`（SIX_STAR，本文件没覆盖的那一关） | 拒跑 | **ok**、`rune_muls=2`、`talent_mul_applied=17` |

逐关**行使计数**（口径：Go `spawns` 的 `covered`／`scanned`；`bb_mul_lookup` 是 `scan` 类，
住在 `scanned` 里，别按 `covered` 读——**我自己先按 covered 读过一次，恒印 0，是假读数**）：

| 关 | rune_muls | `bb_mul_lookup`(scan) | talent 命中 | talent 缺键 | skill 命中 | 空选择器(关卡级) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `main_06-05#f#` | 2 | 42 | **13** | 0 | 0 | 0 |
| `main_08-12#f#` | 2 | 48 | **3** | 0 | 0 | 0 |
| `main_08-14#f#` | 2 | 66 | 0 | 0 | **1** | 0 |
| `main_08-16#f#` | 2 | 32 | **1** | 0 | 0 | 0 |
| `main_09-14#f#` | 2 | 47 | 0 | **47** | 0 | 0 |
| `main_09-17#f#` | 4 | 63 | **1** | 0 | 0 | **1** |
| `act31side_ex04#f#` | 2 | 32 | 0 | 0 | **2** | 0 |
| `act31side_ex07#f#` | 2 | 59 | **48** | 0 | 0 | 0 |

★ 「键非空 ≠ 行使过」在这里是**看得见的**：8 关里 `talent_mul_missing_key=47` 的那一关
（`main_09-14#f#`）**一次都没命中**——见 §8.4，那是对读数，不是漏乘。

### 8.3 验收三件（施工图 §6.5 要的三件，逐件给读数）

**① 121 关全部 `ok=True`** —— 见 §8.2 表，拒跑 0。

**② 与参照实现逐字对拍这 8 关** —— 由 `tools/check_buildspec_go.py`（「单一入口」）承担：
它的 B 口径（空计划）里，这 8 关此前是「**具名拒跑、不计入可比分母**」的 9 关之一；
改动后它们变成**可比**对象 ⇒ 与 Python `build_spec` **逐字段比**。
⚠ 这一步的冻结档**必须重录**（对象集变了 ⇒ 旧记录里没有它们的期望值，通道给 `rc=6`，
那是「该重录」不是判据红）；重录命令 `python tools\freeze_baseline.py --record 单一入口`。
**读数见 `docs/golden-baseline.md` 的对应节点。**

**③ 反例守卫（乘完有没有真重跑派生）** —— 这一条**不能**用上面那 8 关验：
它们打的键（`periodic_damage.` / `vampire.` / `halfhp.` / `Weaken.` / `StoneSkin_2.` / 技能 `Poison` 的 `damage`）
**一个都不喂派生字段**（§3 末尾取证过）⇒ 把 `DeriveBlackboardFields()` 那一句整个删掉，
那 8 关照样全绿。所以另立一条**真数据真 rune** 的守卫，写在 `check_spawns_go.py` §3b-③：

| 关 | 敌人 | 普通档 `passive_pollut` | 四星档 | 期望 |
| --- | --- | ---: | ---: | ---: |
| `act31side_ex07` ↔ `#f#` | `enemy_1390_dhsbr_2` | **5** | **10** | ×2 ✓ |
| 同上 | `enemy_1392_dhshld_2` | **15** | **30** | ×2 ✓ |

`passive_pollut` 正是从 `Passive.extra_value` 派生出来的（`rios-sim/enemy_mech.go:120`）；
「普通 > 0」保证这条**红得起来**，「四星 == 2 × 普通」才证明乘数**落到了派生字段上**。
（同一对值 Python 侧也在断言：`tools/check_environment.py:843-888`。）

判据自身的读数：`check_spawns_go.py` **rc=0**、`--mutate` **rc=0**（五处变异各判红）。

### 8.4 两条途中查实的具名事实

**（甲）`act31side` 的 `#f#` 族有 6 个拒跑，两个根因。** `ex04#f#`（skill）与 `ex07#f#`（talent）
是本文件这条缺口；`s01#f#`～`s04#f#` **换了个根因**——不是 rune 缺实现，是**关卡文件本身不在缓存里**
（`level_act31side_sub-1-*.json` 读不到，报的是 `读关卡文件失败（…）：open …`）。
⇒ **「索引全部键」与「缓存可达键」是两个分母**：`docs/level-sweep-activity.md` 报的「A 层红 2」
是**缓存口径**下的数（`check_go_all.py::cached_levels()`），而按索引全键扫会多出这 4 个
——两件事不许混，也不许拿后者说前者漏了。

**（乙）`main_09-14#f#` 的 `talent_mul_missing_key=47` 为什么一次都没命中。** 该关那条 rune
**没有 `enemy` 选择器**（作用于全场敌人），系数键是 `Weaken.atk`，而 §2 记过「全库只有
`enemy_1177_dufrbl(_2)` 有它，而它就在这一关的 `enemyDbRefs` 里」。
现读该关出怪表（`out/zz_0914_why.py`）：**47 条全是另外 7 个敌人家族**
（`1165_duhond`×7、`1166_dusbr`×9、`1167_dubow`×4、`1168_dumage`×5、`1169_duphlx`×15、
`1170_dushld`×3、`1176_dusocr`×4），**`enemy_1177_*` 一条都没被刷出来**
——它在 `enemyDbRefs` 里，但**不在 wave 里**。
⇒ 47 = 出怪条数，这个计数**是对的**：它正确地把「这条乘数在这一关**没有任何对象**」记了出来。
（这正是「键非空 ≠ 行使过」要防的那种事，只不过这次的方向是「键存在、但没有能被它作用的对象」。）

### 8.5 Go 与 Python 的分道扬镳：本节点**没有新增可观察分歧**（逐条登记）

按 2026-09-24 的口径，Go 与 Python 分道扬镳的每一处都要具名。本节点逐条核过：

| 处 | 形状差 | 判定 |
| --- | --- | --- |
| `clone()` 的时机 | Python 在**选择器命中**时就 clone（哪怕一个键都没改到）；Go 改成**真要改第一处**时才 clone | **不可观察**：对象身份不进规格。换来的是「`out != es`」这个「有没有真改到」的判据保持干净 |
| `derive` 的次数 | Python 每个 `rescale_*` 各调一次；Go 只在**全部命中之后**调一次 | **不可观察**：`DeriveBlackboardFields` 是纯函数、只依赖 `TalentBlackboard` 与 `Skills`，且**不读** `Atk`/`Defense`/`MaxHP` ⇒ 中间那次必被最后一次整份覆盖 |
| 布尔值的 `float()` | Python `float(True)==1.0`，而 Go 原有的 `toFloat` **拒收** bool | Go 侧新写了 `bbFloatFaithful` 把 bool 按 Python 的语义收下 ⇒ 这一处**改成了对齐**，不是新增分歧 |
| **拒跑** | Python 从来不拒跑 | ★ 这一处是**分歧被消掉**：原来 Go 拒跑、Python 照算；现在两边都不拒跑 |

⇒ 本节点**没有**「Go 对、Python 错」或「Python 对、Go 错」的地方需要挂红；
`stage_mul.py` 开头那两条纪律（不改库里的对象、不重跑派生不算接上）都在 `ApplyBBMuls` 里兑现了。
