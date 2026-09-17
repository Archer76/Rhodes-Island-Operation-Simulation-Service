# 明日方舟技能/伤害公式 —— GitHub 取源对照

调查日期：2026-09-15。目的是为 ak-tactic 阶段4「技能系统未实现」找可直接对齐的公式出处。

## 一、结论速览

GitHub 上「有完整公式实现」的项目只有两个（外加一个数据侧）：

| 项目 | 性质 | 我们要的东西在哪 | 可信度 |
|---|---|---|---|
| [xulai1001/akdata](https://github.com/xulai1001/akdata) | 社区主力 DPS 计算器（AKData，NGA 发布） | `resources/dpsv2.js`（64KB 引擎）、`resources/dps_actions.js`、`npm/src/attributes.js`、`npm/customdata/dps_anim.json` | 最高：六年持续维护，每版修帧数补正 |
| [wxhwwla/calc-framework](https://github.com/wxhwwla/calc-framework) | 通用伤害计算框架（含方舟适配） | `framework/adapters/arknights/dag/arknights_full.dag.json`、`.../functions.py`、`games/arknights/calc/skill_parser.py` | 中：结构清晰、可读性好，但方舟部分较新、细节少于 AKData |
| [arkntools/arknights-toolbox](https://github.com/arkntools/arknights-toolbox) | 工具箱 | **没有伤害公式**（只做公招/精英材料/升级/基建），别再翻它 | — |

数据侧（公式的输入口径，本项目已在用）：
[Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData) 的 `excel/skill_table.json`、
[MooncellWiki/OpenArknightsFBS](https://github.com/MooncellWiki/OpenArknightsFBS)（FBS schema）。

wiki 侧（非 GitHub，但公式最权威、最适合当验收基线）：
[Arknights Terra Wiki](https://arknights.wiki.gg/) 的 `Damage` / `Damage/Physical` / `Damage/Arts` /
`Attribute/Attack_interval` / `Skill Point`。用 `api.php?action=parse&page=X&prop=wikitext` 取纯文本，比读 HTML 干净。
（prts.wiki 的 `/w/伤害` 页不存在，别再找。）

## 二、AKData 引擎里的公式（`resources/dpsv2.js`）

### 1. 敌人受击面板（先算有效防御/法抗）

```js
def = max(0, (enemy.def + edef) * edef_scale * (1 - edef_pene_scale) - edef_pene)
mr  = max(0, (enemy.mr  + emr ) * emr_scale  - emr_pene);  mrpct = mr / 100
```
注意顺序：**先加算固定减防/减抗，再乘百分比缩放，最后减固定穿透**（与 wiki 的 `(Def - Ignore_flat) × ∏(1-Ignore_%)` 是同构写法）。

### 2. 单次伤害 `calcHitDamage`

```js
物理: max(atk - def, atk * 0.05)          // minRate = 0.05，即"抛光系数"
法术: max(atk * (1 - mrpct), atk * 0.05)  // AKData 对法术也给了 5% 保底
其他: atk
再乘 damage_scale（只作用于 物理/法术/真伤，不含治疗）
```

### 3. 攻速 → 攻击间隔（帧对齐）

```js
spd      = clamp(finalFrame.attackSpeed, 10, 600)     // 面板攻速，100 = 基准
realTime = baseAttackTime * 100 / attackSpeed          // 秒
frame    = round(realTime * _fps)                      // _fps = 30
frame   += frameCorr(charId | skillId)                 // 帧数补正，见 customdata
```
即 `攻击间隔(帧) = round(基础间隔 × 100 / 攻速 × 30) + 帧数补正`。**帧数补正是必须的**，否则连击/边缘刀会差 1–2 帧。

### 4. 技力（SP）回转

```js
buffFrame.spRecoveryPerSec += blackboard.sp_recovery_per_sec   // 如白面鸮 0.3/s
startSp        = spCost - initSp                               // 距点火还差多少 SP
attackDuration = spCost / (1 + spRecoveryPerSec) - stunDuration // 距点火还差多少"秒"
```
帧级模拟用整数帧记账：`sp = (spCost - startSp) * 30`、`spCost_frames = spCost * 30`，每帧 `sp < spCost ? attack() : skill()`。
另有 `prepDuration`（准备时间，如蓄力技）、`stunDuration`（眩晕/阻回）参与扣减。

### 5. 技能期间攻击次数

```js
attackCount = ceil((levelData.duration - prepDuration) / attackTime)   // 常规持续技
attackCount = ceil((duration - beg/30) / attackTime)                   // 抬手 beg 帧会在首刀吃掉时间
attackCount = ceil(30 / attackTime)    // 瞬发技，duration 记 30s 基准
attackCount = ceil(1800 / attackTime)  // 永续技按 180s
attackCount = spCost                   // 攻回瞬发（按 spCost 次攻击回转）
```
`resources/dps_actions.js` 里按技能类型分支（蓄力/弹药/过载/连击/脱手/切换/召唤物），
`npm/customdata/dps_anim.json` 是抬手与动画帧表，`dps_specialtags.json` 是个体特判标记。这三个文件是 AKData 真正的"私有知识"。

## 三、calc-framework 的方舟适配

`framework/adapters/arknights/dag/arknights_full.dag.json` 是声明式 DAG（8 种节点，可可视化编辑）：

```
物理: max(ATK×倍率 - max(DEF-减防,0), ATK×倍率×5%) × (1+伤害加成)
法术: ATK×倍率 × (1 - max(RES×(1-减抗%),0)/100) × (1+伤害加成)
真伤: ATK×倍率 × (1+伤害加成)
最终攻击力: base_atk×(1+攻击力%/100) + 信赖攻击 + 潜能攻击
```
同式另有纯 Python 版 `.../functions.py`（`physical_damage()` / `magical_damage()` / `true_damage()`），拿来抄最快。
`games/arknights/calc/skill_parser.py`（6.4KB）做「技能描述文本 → 倍率参数」的解析，可用性待评估。
**注意其最终攻击力式少了 FLOOR 取整**，与官方口径不同，别照抄。许可：AGPL-3.0（数据另有限制）——只借鉴公式、不引用代码则无碍。

## 四、wiki 的官方口径（建议作为回归基线）

```
攻击力: Atk       = [FLOOR(Atk_base × Atk_stage) × (1 + Atk_+%)] + Atk_ex
        Atk_final = FLOOR[Atk × ∏(1 - Atk_-%)]

物理  : Dmg = (Atk_final × Atk_x%) − [(Def − Ignore_flat) × ∏(1 − Ignore_%)]
法术  : Dmg = (Atk_final × Atk_x%) × [1 − ((Res − Ignore_flat) × ∏(1 − Ignore_%))]
        「不论伤害类型，最终伤害至少为攻击力的 5%」   ← Damage 总览页原文

攻速  : AtkTime_direct = (base + flat) × (1 + percent) × mult
        AtkSpeed       = 100 / ((100 + ASPD_flat) × ∏(1 + ASPD_percent))
        AtkInterval    = AtkTime_direct × AtkSpeed      // ASPD 区间 20 ~ 600

SP    : 自动回复 1/s；攻击回复每次攻击 1 点（含治疗）；受击回复每次受击 1 点（闪避/抵抗也算）
        充能技上限 = 2 × spCost；SP lockout（蓄满未放/技能生效中）时不能"被回复"
```

## 五、三个来源的三处分歧（需要实机定案）

1. **法术是否有 5% 保底**：wiki 总览页、AKData 都说**有**；calc-framework 只对物理做了保底。
   → 与本项目 `battle/damage.py` 现在的写法（法术无保底）相反。若确有保底，SR-EX-8「吓人路灯 RES 99」就是稳定 5% 而非 1%。
   简易判据：用固定攻击力干员打高法抗敌人，看飘字伤害是否被 5% 卡住（法抗 ≥95 时飘字不再变化即为有保底）。
2. **攻速下限**：wiki 说最终 ASPD 不低于 **20**；AKData 代码夹到 **10**。
3. **攻击力取整**：wiki 明确的 `FLOOR` 两处是**伤害结算**里的，与**面板**取整不是一回事。
   面板取整 2026-09-17 已由实机定案为**四舍五入**（见 `docs/uncertainties.md` 第一节与
   `tools/check_db.py` 的 [4b] 节：红豆 1185/510、怒潮凛冬 2981/1307/473 逐位命中 round）。
   旁证：prts.wiki 干员页内嵌的「属性计算器」用的也是 `Math.round`。
   故本项目 `operator/stats.py` 的 `rounding` 默认已改为 `round`，
   而 `battle/damage.py` 的伤害侧**仍是 floor**——两者各自成立。

## 六、对 ak-tactic 的落地建议

1. `battle/damage.py`：补 `minRate=0.05` 的法术分支开关（默认按 wiki 打开），留一个 flag 便于实机对比。
2. `battle/sim.py`：现在是"秒"为单位的浮点推进，技能一接就会暴露帧误差 → 建议改为 **30fps 整数帧推进**，攻击间隔走
   `round(base*100/aspd*30) + frameCorr`，SP 用帧记账（AKData 的做法）。
3. 新增 `ak_tactic/battle/skill.py`：读 `skill_table.json` 的 `blackboard`，按 `spChargeType / spCost / initSp / duration /
   sp_recovery_per_sec / base_attack_time / atk_scale / damage_scale / prepDuration / stunDuration` 驱动；
   攻击次数用第三节的 `ceil((duration - prep)/attackTime)` 族。
4. 回归用例：拿 1-7 与 SR-6 现成基线（怒潮凛冬 2 倍速录像、SR-6 21 杀 0 漏）重跑，先只开"技能倍率 + 帧对齐"，再逐项加特判。

---

# 附：干员数据与技能的计算口径（2026-09-15 补）

上面一到六节是**取源调查**（谁的公式可信）。以下三节是**落地口径**：数据在哪个
字段、按什么规则算、哪一条已经验过、哪一条还只是假设。全部字段都能在本地库
`data/akdb.sqlite` 里直接查（见 `docs/operator-db.md`）。

## 七、面板（属性）怎么算

```
属性 = 等级插值(基础关键帧) + 信赖(插值) + 潜能修正 + 模组加成
```

| 环节 | 数据位置 | 规则 |
|---|---|---|
| 等级 | `phases[i].attributesKeyFrames` | 多数阶段只有 **2 帧**（如精1 的 1 级与 70 级），中间靠线性插值。**阶段内等级从 1 重新起算**（精1 的帧是 1→70，不是 51→70） |
| 信赖 | `favorKeyFrames` | `level` 是 **0–50**，对应**游戏内显示信赖 0%–200%**（每 level 4 点），故 `level = trust / 2`；`trust` 是 **0–100 内部标度**（= 显示值 ÷ 2，100 即满 200%）；同为线性插值 |
| 潜能 | `potentialRanks` | 只有 **5 项**，对应**潜能 2–6**；取前 `potential - 1` 项。`buff.attributes.attributeModifiers` 里 `formulaItem=ADDITION` 加算、`MULTIPLIER` 乘算 |
| 模组 | `battle_equip_table` | `attributeBlackboard` 是**该等级的总加成，不是增量**（阿米娅 1/2/3 级 = max_hp 100/130/150、atk 30/40/50） |

**取整已于 2026-09-17 定案为四舍五入（`round`）。** 早先的依据是 wiki 的
`Attribute` 页写的 `FLOOR`——但那说的是**伤害结算**里的取整，与**面板**不是一回事，
两者被混在一行里问过。面板侧靠两份独立证据定案：
① prts.wiki 干员页内嵌的「属性计算器」（`static.prts.wiki/charinfo/charinfo_*.min.js`
注入的那段内联脚本）用的就是 `Math.round`；此前以为「prts.wiki 拿不到更多端点」，
但**403 的是模板命名空间，干员页整页 HTML 走 `action=parse&prop=text` 一直拿得到**；
② 博士实机面板逐位命中：红豆 生命 1185 / 攻击 510，怒潮凛冬 2981 / 1307 / 473。
项目把取整做成 `rounding` 参数（**默认 `round`**），并留了 `calibrate()`
用一条实机面板反推——留作日后遇到反例时的校准口。

**验过的锚点**（都是外部数据，不是从库里反推的）：

* 阿米娅六个端点 699/276/48/10 → 1480/612/121/20（prts.wiki 属性模板）；
* 怒潮凛冬 精2 60 = **2731 / 1193 / 387 / 0 / 攻击间隔 1.80 / 阻挡 2 / 费用 20**
  （实机录像逐项读过）——这条特别有价值，因为它落在**插值中段**，
  能同时验关键帧与插值口径。

## 八、天赋与模组的口径

**天赋的位置：没有独立表。** `excel/talent_table.json` **不存在（404）**，
天赋就在 `character_table.json` 的 `talents` 字段里，结构是「组 → 候选」：

```json
"talents": [{"candidates": [
  {"unlockCondition": {"phase": "PHASE_2", "level": 1},
   "requiredPotentialRank": 5, "prefabKey": "1",
   "name": "情绪吸收", "blackboard": [{"key": "amiya_t_1[atk].sp", "value": 3}]}]}]
```

三条判读规则：

1. **同组候选不是叠加，是版本切换。** 由 `unlockCondition.phase/level` 与
   `requiredPotentialRank` 决定哪一个生效；潜能高的候选取代低的那条。
2. **方括号变体键不能覆盖基础键。** `headb2_s_2[second].atk = 1.8` 是"第二次及
   以后"的取值，若按普通键写进字典，第一次也会被算成 1.8。1-7 的实机录像
   用例正是靠这条才对上（只按黑板 35 杀，叠上变体 41 杀）。
3. **`prefabKey` 是机制标识，黑板键名常带它做前缀**（`amiya_t_1[atk].sp`），
   所以"键名像什么"不能当归类依据，得看 `prefabKey` 与描述。

**模组的「三道门」，缺一不可：**

| 门 | 判据 | 为什么 |
|---|---|---|
| ① | `type != "INITIAL"` | 基础证章只有文字描述，`battle_equip_table` 里没有它（396 条无一有数值） |
| ② | `isSpecialEquip == false` | **最容易漏的一道**：特限/特勤证章 `type` 仍是 `ADVANCED`、**也照样有战斗数值**，唯一标志是 `specialEquipDesc == "适配限定模式"`（全表 21 条）。普通关一律不生效 |
| ③ | 在 `battle_equip_table` 里且等级表非空 | 只有 509 条专属模组有数值 |

模组还能**改写特性与天赋**：`phases[].parts[]` 里带
`overrideTraitDataBundle` / `addOrOverrideTalentDataBundle`，特性改写常伴随
`additionalDescription` 与新的黑板（麦哲伦模组：`cnt = 1`，首个召唤物不占部署位）。

## 九、技能效果怎么从黑板读出来

`skill_table.json` 的 `levels[i].blackboard` 是 `[{key, value, valueStr}]` 列表。
**拍平后不要去掉 `attack@` 前缀**——它表示"由这次攻击施加"，是消歧义的唯一线索；
去前缀是 `SkillEffects` 归一化的活，不是建库的活。几个踩过的坑：

| 坑 | 事实 | 标本 |
|---|---|---|
| `atk_scale` 二义 | `attack@atk_scale` 是平A倍率，裸 `atk_scale` 可能是冲锋段等另一段 | 机械师「工程学十字星」2.6 vs 3.0 |
| 弹药数藏在两个键名里 | `durationType == "AMMO"` 时，`attack@trigger_time`（8）**或裸 `trigger_time`**（20）才是弹药数；非弹药技里裸 `trigger_time` 是"触发间隔"（共 320 处） | 圣约送葬人 8 发 / 望「天下劫」20 发 |
| `duration = -1` **不等于**无限 | `duration is None` 有歧义：无限持续（圣聆初雪技2）与瞬发（她的技1）在数据里长一样，只能靠描述文本区分 | 判错会把 12 秒一次的爆发技变成**永续 520% 平A**，高估六倍 |
| 范围改写 | `levels[i].rangeId` 覆盖阶段范围；技能期间的格集合以它为准 | 圣约送葬人「遗嘱执行」→ `2-5`；望「天下劫」→ `4-12` |
| 攻击回复 vs 自动回复 | `spData.spType`：`INCREASE_WITH_TIME` / `INCREASE_WHEN_ATTACK` / 被动（spType 8 归一成 `PASSIVE`，不是第四种回复） | 阿米娅 100 技力 = 100s；圣约送葬人是攻击回复 |

**技能期间出手次数**（AKData 的读法，见上文第三节）：

```
ceil((duration - prepDuration) / attackTime)  常规持续技
ceil(30 / attackTime)                          瞬发技（duration 记 30s 基准）
ceil(1800 / attackTime)                        永续技（按 180s）
spCost                                         攻回瞬发（按 spCost 次攻击回转）
```

**已经对齐的部分**：伤害（物理/法术/真伤，含 5% 保底的处理见第五节分歧 1）、
攻击间隔、SP 回转、技能倍率与连击、弹药、范围改写、技能与天赋的黑板解析。
**仍未对齐的**：抬手（`prepDuration`）与敌人的攻击动作时长——前者管的是
**首刀时机**，后者是模拟器给的 0.5 秒假设，见
[ranged-enemy-rule.md](ranged-enemy-rule.md) 第四节。

> **「攻击间隔需要动画帧补正吗」已定案：否**（2026-09-16 实机核对）。
> 赤刃明霄陈在攻略录像里的连续攻击基频是 **15.11 帧**（2 倍速、30fps），
> 换算游戏内 **1.008s**，与 `基础间隔 × 100 / 总攻速` = 1.25×100/124 的预测
> **15.12 帧吻合到 0.07%**（按攻速 100 算则是 1.25s，差 24%）。
> AKData 的 `customdata/dps_anim.json` 里的帧数补正属于**首刀时机**那一族
> （`ceil((duration − prepDuration) / attackTime)`），与出手周期无关，
> 本项目不必为周期再找这份数据。

