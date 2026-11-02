# 塔露拉（char_4247_oxi）战斗机制全生命周期闭环口径

> 本文档依据 `docs/operator-mechanics-workflow.md` 撰写，记录六星近卫·本源近卫塔露拉在 `rios-sim` 中的机制建模、数据来源、黑板键消费与全生命周期实现状态。
> 原始数据全部来自 gamedata 原文（`character_table.json` / `skill_table.json` / `range_table.json`），规格层保存原文，配置层解析，**严禁手写硬编码数值**。
> 所有中文名称均 100% 对应 gamedata 原始 JSON 中的官方字段。

---

## 〇、基础规格与证据

- **代号**：塔露拉 / Talulah
- **干员标识**：`char_4247_oxi`
- **职业分支**：近卫 - 本源近卫（primguard）
- **稀有度**：六星（TIER_6）
- **特性（Primguard Trait）**：
  - 能够阻挡两个敌人（`block_cnt: 2`）。
  - 可以造成元素伤害 / 真实伤害通道。
  - 基础攻击间隔 1.2s（`baseAttackTime: 1.2`）。
  - 基础攻击范围：`1-1`（自身格 + 正前 1 格，共 2 格）。
  - 基础法抗：10.0。
- **天赋开放节点**：
  - 第一天赋「绝不妥协」在 `PHASE_0`（精英 0）开放，`PHASE_1`、`PHASE_2` 逐步强化。
  - 第二天赋「我即火焰」在 `PHASE_2`（精英 2）开放。
- **潜能分档口径**：
  - 潜能 2（Index 0）：部署费用 -1
  - 潜能 3（Index 1）：第二天赋效果增强（`requiredPotentialRank: 2`）
  - 潜能 4（Index 2）：攻击力 +35
  - 潜能 5（Index 3）：第一天赋效果增强（`requiredPotentialRank: 4`）
  - 潜能 6（Index 4）：部署费用 -1
- **模组情况**：
  - 截至当前 gamedata 版本，`uniequip_table.json` 中塔露拉未收录专属模组，模组分支保持为未实装/空。

---

## 一、第一天赋「绝不妥协」

### 1. 机制描述
攻击造成法术伤害；造成法术伤害时附带一定比例（`ep_damage_ratio`）的灼燃损伤（`elemFire`）；停止攻击 `arcane_idle_delay`（3.0秒）后，法术和元素伤害逐渐提升（每 `arcane_step_interval` 0.5秒提升 `arcane_step`，最高提升 `arcane_max`），每次攻击时衰减 1 层。

### 2. 数值档位（来自 `character_table.json` talents 候选原文）
| 精英阶段 | 潜能要求 | arcane_idle_delay | arcane_step_interval | arcane_step | arcane_max | ep_damage_ratio |
|---|---|---|---|---|---|---|
| E0 (PHASE_0) | 潜能 1–4 | 3.0s | 0.5s | 0.0% | 0.0% | 3% |
| E0 (PHASE_0) | 潜能 5–6 | 3.0s | 0.5s | 0.0% | 0.0% | 5% |
| E1 (PHASE_1) | 潜能 1–4 | 3.0s | 0.5s | 1.5% | 9.0% | 6% |
| E1 (PHASE_1) | 潜能 5–6 | 3.0s | 0.5s | 2.0% | 12.0% | 8% |
| E2 (PHASE_2) | 潜能 1–4 | 3.0s | 0.5s | 2.5% | 15.0% | 11% |
| E2 (PHASE_2) | 潜能 5–6 | 3.0s | 0.5s | 3.0% | 18.0% | 13% |

### 3. 关键实现规则
- **伤害属性转化**：普通攻击伤害类型恒定转化为 `MAGIC`（法术伤害）。
- **灼燃损伤附带**：造成法术伤害时，对目标施加 `ep_damage_ratio` 比例的灼燃损伤（`elemFire`），通过 `elementState.damage(elemFire, amount)` 结算。
- **未攻击积蓄与衰减状态机**：
  - 干员未进行攻击时，`idleTimer` 累加；
  - 当 `idleTimer >= arcane_idle_delay`（3.0s）后，每经过 `arcane_step_interval`（0.5s），积蓄层数 `arcane_stacks++`，上限为 `int(round(arcane_max / arcane_step))`；
  - 伤害加成系数为 `1.0 + float64(arcane_stacks) * arcane_step`，同时作用于法术伤害与元素伤害；
  - 每次出手攻击命中时，`idleTimer` 重置为 0，且 `arcane_stacks` 衰减 1 层（若大于 0 则减 1）。

---

## 二、第二天赋「我即火焰」

### 1. 机制描述
在场时，全场敌人灼燃损伤爆发后 5 秒内，于可通行地面留下持续 `field_duration` 秒的“足迹”（最多 `max_count` 25 格），每 `field_interval`（0.3秒）造成塔露拉攻击力 `field_atk_scale` 的法术伤害。

### 2. 数值档位
| 精英阶段 | 潜能要求 | field_duration | field_interval | field_atk_scale | max_count |
|---|---|---|---|---|---|
| E0 / E1 | - | 未解锁 | - | - | - |
| E2 (PHASE_2) | 潜能 1–2 | 3.0s | 0.3s | 12% | 25 |
| E2 (PHASE_2) | 潜能 3–6 | 4.0s | 0.3s | 15% | 25 |

### 3. 关键实现规则
- **触发条件**：当塔露拉在场存活时，场上任一敌人触发灼燃损伤爆发（`elemFire` 爆条触发冷却）；
- **足迹生成**：敌人处于爆发后 5 秒的窗口内，其在可通行地面移动所经过的地块生成烈焰足迹；
- **地块上限与覆盖**：同一地块刷新持续时间至 `field_duration`；地块总数上限为 `max_count`（25 格），达到上限时淘汰最先生成的地块；
- **周期跳伤**：每 `field_interval`（0.3s）对站在足迹地块上的所有地面敌人结算一次塔露拉当前攻击力 `field_atk_scale` 倍的法术伤害。

---

## 三、技能解析与黑板键消费

### 1. 技能一「照霎白夜」（skchr_oxi_1）
- **类型**：自动回复（INCREASE_WITH_TIME），自动触发（AUTO）。SP Cost 8，Init SP 0。
- **数值与黑板键**：
  - `atk_scale`：造成法术伤害倍率（Lv1: 3.4 ~ Lv7: 4.9 ~ Lv10: 6.0）。
  - `fear`：恐惧持续秒数（Lv1: 1.5s ~ Lv7: 2.5s ~ Lv10: 3.0s）。
- **执行逻辑**：
  - 下一次攻击时触发，对目标所在地块上的所有地面敌人造成攻击力 `atk_scale` 的法术伤害；
  - 附带第一天赋增伤与灼燃损伤；
  - 对被命中的地面敌人施加 `fear` 秒恐惧状态，激活诱发移动（`fear.go`）。

### 2. 技能二「阂断骤雪」（skchr_oxi_2）
- **类型**：自动回复（INCREASE_WITH_TIME），受击触发。可充能 `max_stack_cnt` 次（5次）。
- **数值与黑板键**：
  - `skill_duration`：技能持续时间 1.3s。
  - `damage_resistance`：减伤庇护比例（固定 0.9 = 90% 减伤）。
  - `damage_remaining_scale`：剩余承受伤害比例（0.1，与减伤互补）。
  - `shelter_hold_duration`：满额庇护保持时间 0.2s，之后在剩余 1.1s 内线性减弱至 0。
  - `retaliate_atk_scale`：反击法术伤害倍率（Lv1: 1.4 ~ Lv7: 2.3 ~ Lv10: 3.0）。
  - `heal_ratio`：反击伤害转化为生命恢复比例（固定 0.05 = 5%）。
  - `atk`：攻击力增加比例（Lv1: +0.3 ~ Lv7: +0.47 ~ Lv10: +0.6）。
  - `def`：防御力增加比例（Lv1: +0.3 ~ Lv7: +0.47 ~ Lv10: +0.6）。
  - `max_stack_cnt`：充能与增益叠加上限（5 层）。
  - `stack_duration`：增益持续时间 5.0s。
  - `ability_range_radius`：反击爆炸范围半径 1.0 格。
  - `attack@buffed_attack_atk_scale`：群攻倍率 1.0。
- **执行逻辑**：
  - 受到攻击时，若当前有充能且未处于技能生效期，消耗 1 点充能触发；
  - 触发即刻进入 1.3s 庇护，前 0.2s 减伤 90%，随后 1.1s 减伤线性递减；
  - 对攻击来源敌人的位置周围半径 1.0 格地面敌人造成 `retaliate_atk_scale` 倍法术伤害，并恢复伤害量 5% 的生命；
  - 获得持续 5.0s 的增益层数（最多叠加 5 层），每层提供 `+atk` 与 `+def`，且普通攻击变为攻击所有阻挡的敌人。

### 3. 技能三「日冕重烈」（skchr_oxi_3）
- **类型**：自动回复（INCREASE_WITH_TIME），手动开启（MANUAL）。持续时间 36.0s，SP Cost 45，Init SP 38（Lv10）。
- **数值与黑板键**：
  - `atk`：攻击力加成（Lv1: +1.0 ~ Lv7: +1.2 ~ Lv10: +1.4）。
  - `heatwave_atk_scale`：火浪爆炸伤害倍率（Lv1: 1.0 ~ Lv7: 1.75 ~ Lv10: 2.5）。
  - `normal_interval`：常规阶段火浪生成间隔（2.67s）。
  - `overload_interval`：过载阶段火浪生成间隔（2.0s）。
  - `wave_speed`：火浪推移速度（2.3 格/秒）。
  - `normal_half_width`：常规阶段火浪横向半宽（2.0 格，共 5 行）。
  - `overload_half_width`：过载阶段火浪横向半宽（6.0 格，共 13 行）。
  - `projectile_range`：火浪弹道碰撞判定半径（0.5 格）。
  - `range_radius`：火浪碰撞爆炸杀伤半径（1.5 格）。
  - `wave_exit_distance`：火浪最大推进距离（5.0 格）。
  - `same_wave_repeat_damage_scale`：同波次重复命中衰减比例（0.15）。
  - `random_birth_delay`：生成随机延迟（0.0，具名审计）。
- **执行逻辑**：
  - 开启后攻击力提升 `+atk`，塔露拉停止普通攻击，持续引导场地；
  - 前 18.0s 为常规阶段，每 2.67s 朝部署朝向推移一波 5 行全宽（半宽 2.0）的火浪；
  - 后 18.0s 触发过载（Overdrive），每 2.0s 朝部署朝向推移一波 13 行全宽（半宽 6.0）的火浪；
  - 火浪沿朝向以 2.3 格/秒速度推进，最远推进 5.0 格；
  - 当火浪与地面敌人的碰撞距离 ≤ 0.5 格时爆炸，对半径 1.5 格内所有地面敌人造成范围伤害；
  - 若目标处于灼燃损伤爆发期间，伤害类型由法术转为真实/元素伤害；
  - 同一波次若对同一敌人多次命中，后续伤害降为 15%（`same_wave_repeat_damage_scale`）；
  - 技能可随时手动提前关闭。

---

## 四、黑板键全量审计台账

| 来源 | 黑板键 | 类型 | 消费状态 | 消费模块 / 裁定说明 |
|---|---|---|---|---|
| 第一天赋 | `arcane_idle_delay` | float64 | 已消费 | `oxi_runtime.go`: 未攻击延迟计时器阈值（3.0s） |
| 第一天赋 | `arcane_step_interval` | float64 | 已消费 | `oxi_runtime.go`: 伤害提升步进周期（0.5s） |
| 第一天赋 | `arcane_step` | float64 | 已消费 | `oxi_runtime.go`: 每步法术/元素增伤幅度 |
| 第一天赋 | `arcane_max` | float64 | 已消费 | `oxi_runtime.go`: 最大法术/元素增伤上限 |
| 第一天赋 | `ep_damage_ratio` | float64 | 已消费 | `oxi_runtime.go`: 造成法术伤害附带的灼燃损伤比例 |
| 第二天赋 | `field_duration` | float64 | 已消费 | `oxi_runtime.go`: 足迹地块存留时间（3.0s/4.0s） |
| 第二天赋 | `field_interval` | float64 | 已消费 | `oxi_runtime.go`: 足迹伤害跳动周期（0.3s） |
| 第二天赋 | `field_atk_scale` | float64 | 已消费 | `oxi_runtime.go`: 足迹法术伤害倍率 |
| 第二天赋 | `max_count` | float64 | 已消费 | `oxi_runtime.go`: 足迹地块最大数量上限（25） |
| 技能一 | `atk_scale` | float64 | 已消费 | `oxi_config.go`: S1 斩击法术伤害倍率 |
| 技能一 | `fear` | float64 | 已消费 | `oxi_runtime.go`: S1 命中后恐惧持续时间 |
| 技能二 | `skill_duration` | float64 | 已消费 | `oxi_runtime.go`: S2 触发后受击减伤持续时间（1.3s） |
| 技能二 | `damage_remaining_scale` | float64 | 已消费 | `oxi_runtime.go`: S2 庇护最低承伤比例（0.1） |
| 技能二 | `damage_resistance` | float64 | 已消费 | `oxi_runtime.go`: S2 庇护峰值减伤比例（0.9） |
| 技能二 | `shelter_hold_duration` | float64 | 已消费 | `oxi_runtime.go`: S2 减伤峰值保持时间（0.2s） |
| 技能二 | `retaliate_atk_scale` | float64 | 已消费 | `oxi_runtime.go`: S2 反击法术伤害倍率 |
| 技能二 | `heal_ratio` | float64 | 已消费 | `oxi_runtime.go`: S2 反击伤害吸血比例（0.05） |
| 技能二 | `atk` | float64 | 已消费 | `oxi_runtime.go`: S2 触发后攻击力加成 |
| 技能二 | `def` | float64 | 已消费 | `oxi_runtime.go`: S2 触发后防御力加成 |
| 技能二 | `max_stack_cnt` | float64 | 已消费 | `oxi_runtime.go`: S2 充能上限与叠加上限（5） |
| 技能二 | `stack_duration` | float64 | 已消费 | `oxi_runtime.go`: S2 攻防与群攻增益持续时间（5.0s） |
| 技能二 | `ability_range_radius` | float64 | 已消费 | `oxi_runtime.go`: S2 反击爆炸杀伤半径（1.0 格） |
| 技能二 | `attack@buffed_attack_atk_scale` | float64 | 已消费 | `oxi_runtime.go`: S2 攻防增益期间阻挡群攻倍率 |
| 技能三 | `atk` | float64 | 已消费 | `oxi_config.go`: S3 攻击力加成（1.0 ~ 1.4） |
| 技能三 | `heatwave_atk_scale` | float64 | 已消费 | `oxi_runtime.go`: S3 火浪爆炸基础伤害倍率 |
| 技能三 | `normal_interval` | float64 | 已消费 | `oxi_runtime.go`: S3 常规期火浪生成周期（2.67s） |
| 技能三 | `overload_interval` | float64 | 已消费 | `oxi_runtime.go`: S3 过载期火浪生成周期（2.0s） |
| 技能三 | `wave_speed` | float64 | 已消费 | `oxi_runtime.go`: S3 火浪推移速度（2.3 格/秒） |
| 技能三 | `normal_half_width` | float64 | 已消费 | `oxi_runtime.go`: S3 常规期横向半宽（2.0 格） |
| 技能三 | `overload_half_width` | float64 | 已消费 | `oxi_runtime.go`: S3 过载期横向半宽（6.0 格） |
| 技能三 | `projectile_range` | float64 | 已消费 | `oxi_runtime.go`: S3 火浪碰撞判定距离（0.5 格） |
| 技能三 | `range_radius` | float64 | 已消费 | `oxi_runtime.go`: S3 火浪碰撞爆炸杀伤半径（1.5 格） |
| 技能三 | `wave_exit_distance` | float64 | 已消费 | `oxi_runtime.go`: S3 火浪推进最大有效距离（5.0 格） |
| 技能三 | `same_wave_repeat_damage_scale` | float64 | 已消费 | `oxi_runtime.go`: S3 同波次重复命中伤害衰减比例（0.15） |
| 技能三 | `random_birth_delay` | float64 | 具名审计 | 固定为 0.0，不改变确定性仿真时序 |

---

## 五、验收标准与自检清单

- [x] 数据驱动规格层，从 `character_table.json` 和 `skill_table.json` 读取原文。
- [x] 所有黑板键全量强类型映射，无静默泄漏。
- [x] 第一天赋未攻击积蓄、出手衰减与法术伤害附带灼燃损伤完整实现。
- [x] 第二天赋敌人灼燃爆发后 5s 内留足迹与 0.3s 跳伤完整实现。
- [x] S1 照霎白夜高倍率法伤与恐惧状态施加完整实现。
- [x] S2 阂断骤雪受击充能消耗、非线性庇护衰减、范围反击吸血与 5 层阻挡群攻攻防叠层完整实现。
- [x] S3 日冕重烈停攻引导、火浪推移弹道、常规 5 行与过载 13 行全宽焚原、爆发期转元素伤害与同波次衰减完整实现。
- [x] 专项测试套件 `TestOxi*` 全面覆盖数值与时序。
- [x] 全包回归测试通过。
