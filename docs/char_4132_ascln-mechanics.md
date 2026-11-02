# 阿斯卡纶（char_4132_ascln）战斗机制全生命周期闭环口径

> 本文档依据 `docs/operator-mechanics-workflow.md` 撰写，记录阿斯卡纶在 `rios-sim` 中的机制建模、数据来源、黑板键消费与全生命周期实现状态。
> 原始数据全部来自 gamedata 原文（`character_table.json` / `skill_table.json` / `battle_equip_table.json` / `range_table.json`），规格层保存原文，配置层解析，**严禁手写硬编码数值**。
> PRTS 取证资料已存档于仓外独立工作目录 `D:/home/DSH/ak-tactic-worklog/ascln-page-audit-20261102`。

---

## 〇、基础规格与证据

- **代号**：阿斯卡纶 / Ascalon
- **干员标识**：`char_4132_ascln`
- **职业分支**：特种 - 伏击客（stalker）
- **阵营**：`babel`（巴别塔）/ `rhodes`（罗德岛）
- **稀有度**：六星（TIER_6）
- **特性（Stalker Trait）**：
  - 对攻击范围内所有敌人造成物理伤害（无阻挡上限近战群攻）。
  - 拥有 50% 的物理和法术闪避（`prob: 0.5`）。
  - 不容易成为敌人的攻击目标（基础仇恨等级 `taunt_level: -1`）。
  - 阻挡数恒为 0（`block_cnt: 0`）。
  - 基础攻击间隔 3.5s。
- **天赋开放节点**：
  - 第一天赋「密林低语」在 `PHASE_0`（精英 0）开放。
  - 第二天赋「暗影遮蔽」在 `PHASE_2`（精英 2）开放。
- **潜能分档口径**：游戏内 1–6（0–5 索引，潜能 5 为潜能索引 4：第二天赋效果增强）。

---

## 一、第一天赋「密林低语」（Whispering Darkness）

### 1. 机制描述
攻击对敌人施加效果：移动速度降低（`move_speed`），每秒受到（`atk_ratio`）阿斯卡纶当前攻击力的法术伤害，持续 `debuff_duration` 秒，效果最多叠加 `max_stack_cnt` 层（3层）。

### 2. 数值档位（来自 `character_table.json` talents 候选原文）
| 精英阶段 | 潜能 | move_speed | atk_ratio | debuff_duration | interval | max_stack_cnt |
|---|---|---|---|---|---|---|
| E0 (PHASE_0) | 1–6 | -12% | 6% | 18.0s | 1.0s | 3 |
| E1 (PHASE_1) | 1–6 | -15% | 8% | 18.0s | 1.0s | 3 |
| E2 (PHASE_2) | 1–6 | -18% | 10% | 25.0s | 1.0s | 3 |

### 3. 模组升级覆盖（来自 `battle_equip_table.json`）
- **X 模组（`uniequip_002_ascln` - 刺客的凭证）**：
  - Lv1：特性覆写（攻击范围内所有敌人移动速度 -20%）。
  - Lv2：天赋一升级（`talentIndex=0`）-> `move_speed: -0.18`, `atk_ratio: 0.11`, `debuff_duration: 27.0s`, `interval: 1.0s`, `max_stack_cnt: 3`。
  - Lv3：天赋一升级（`talentIndex=0`）-> `move_speed: -0.18`, `atk_ratio: 0.11`, `debuff_duration: 30.0s`, `interval: 1.0s`, `max_stack_cnt: 3`。
- **Y 模组（`uniequip_003_ascln` - 愿阿斯卡纶的眼睛……）**：
  - Lv1：特性覆写（拥有 65% 的物理和法术闪避，`prob: 0.65`）。
  - Lv2：天赋一升级（`talentIndex=0`）-> `move_speed: -0.18`, `atk_ratio: 0.10`, `debuff_duration: 25.0s`, `interval: 1.0s`, `max_stack_cnt: 3`, `hp_ratio: 0.05`（拥有该效果的敌人被击倒时阿斯卡纶回复5%最大生命）。
  - Lv3：天赋一升级（`talentIndex=0`）-> `move_speed: -0.18`, `atk_ratio: 0.10`, `debuff_duration: 25.0s`, `interval: 1.0s`, `max_stack_cnt: 3`, `hp_ratio: 0.10`（拥有该效果的敌人被击倒时阿斯卡纶回复10%最大生命）。

### 4. 关键规则
- **层数与减速叠加**：根据 PRTS 官方口径与游戏表现，攻击已有本效果的单位时叠加 1 层并刷新持续时间至上限；减速按层数线性增加，即减速幅度 = `move_speed × stacks`（例如 E2 满层 3 层减速为 `-18% × 3 = -54%`）。
- **持续伤害（DoT）**：每 1 秒触发一次法术伤害，每层伤害为 `当前攻击力 × atk_ratio`，总 DoT 伤害 = `当前攻击力 × atk_ratio × stacks`。
- **退场清空**：阿斯卡纶退场（击倒或撤退）时，场上敌人已施加的本天赋 debuff 立刻结束。

---

## 二、第二天赋「暗影遮蔽」（Shrouded Shadow）

### 1. 机制描述
攻击速度 +8，自身周围四格有高台时，攻击速度额外 +6。潜能 5 时基础攻击速度加成提升至 +10。

### 2. 数值档位
| 精英阶段 | 潜能 | attack_speed | attack_speed_add | cnt |
|---|---|---|---|---|
| E0/E1 | - | 未解锁 | - | - |
| E2 (PHASE_2) | 1–4 | +8 | +6 | 1 |
| E2 (PHASE_2) | 5–6 | +10 | +6 | 1 |

### 3. 高台几何判定
- 检查阿斯卡纶当前站位 `(col, row)` 的上下左右相邻四格：`(col+1, row)`, `(col-1, row)`, `(col, row+1)`, `(col, row-1)`。
- 若任一相邻格为高台地块（地块高度非地面，或存在高台属性），则激活 `attack_speed_add` 加成。

---

## 三、技能解析

### 1. 技能一「无声收割」（追袭 / `skchr_ascln_1`）
- **类型**：AUTO 自动充能，AUTO 自动触发。
- **黑板键**：
  - `atk_scale`：下次攻击力倍率（Lv1: 1.05 ~ Lv10: 2.10）。
  - `cnt`：充能层数上限（Lv1-3 为 1，Lv4-6 为 2，Lv7-10 为 3）。
- **表现**：下一次攻击力提升至 `atk_scale`，并连续攻击两次。由于伏击客特性为群攻，范围内所有敌人均受到 2 次物理攻击，每次命中均正常触发第一天赋施加与叠加判定。

### 2. 技能二「荆棘束缚」（恩赐 / `skchr_ascln_2`）
- **类型**：AUTO 自动充能，MANUAL 手动触发。持续时间 35.0s。
- **黑板键**：
  - `atk`：攻击力增加比例（Lv1: +0.20 ~ Lv10: +1.30）。
  - `move_speed`：技能范围内的敌人移动速度降低（Lv1: -0.20 ~ Lv10: -0.60）。
  - `range_radius`：地面敌人被击倒时的尸爆传播半径（固定 1.3 格）。
- **表现**：
  - 技能开启期间攻击力增加。
  - 技能范围内的所有敌人受到直接减速光环效果（与第一天赋减速乘法/独立叠加）。
  - 当地面敌人被击倒时，对死亡位置半径 `range_radius` 范围内的其他地面敌人施加 1 层第一天赋效果。

### 3. 技能三「尽头余烬」（降临 / `skchr_ascln_3`）
- **类型**：AUTO 自动充能，MANUAL 手动触发。持续时间 45.0s，初动 35s，消耗 45s（Lv10）。
- **黑板键**：
  - `atk`：攻击力增加比例（Lv1: +0.10 ~ Lv10: +0.50）。
  - `base_attack_time`：攻击间隔缩短秒数（Lv1-3: -0.7s, Lv4-6: -1.2s, Lv7-10: -1.5s）。
  - `taunt_level`：嘲讽等级提升值（+2.0，使仇恨等级从 -1 提升至 1）。
  - `attack@damage_hitrate_physical`：范围内地面敌人物理命中率修正（Lv10: -0.50）。
  - `attack@damage_hitrate_magical`：范围内地面敌人物术命中率修正（Lv10: -0.50）。
  - `attack@hp_ratio`：闪避或未命中时的回复生命值比例（Lv10: 0.08 = 8% 最大生命值）。
  - 攻击范围变为 `y-10`（扩大范围）。
- **口径与严禁近似要求**：
  - **命中率判定（V-2 规范）**：严禁将命中率降低 -50% 折算为 50% 减伤！必须在受击时，使用确定性伪随机数生成器（`prob_rng.go` 的 splitmix64）针对每次攻击抽样判定是否命中。
  - **回血触发**：当且仅当发生「自身闪避成功」或「敌方判定为未命中」时，触发 `MaxHP × attack@hp_ratio` 的即时生命回复。
  - **攻速间隔**：`base_attack_time` 改写与既有攻速公式 `(3.5 + base_attack_time) * 100 / max(20, aspd)` 协同，严禁重复修正。
  - **索敌仇恨**：`taunt_level` 遵循本仓 `-taunt_level` 优先级。

---

## 四、黑板键消费台账

| 来源 | 键 | 状态 | 消费者 |
|---|---|---|---|
| 第一天赋 | `move_speed` | 已消费 | 天赋一移速 debuff 计算（每层叠加） |
| 第一天赋 | `atk_ratio` | 已消费 | 天赋一每秒法术持续伤害 |
| 第一天赋 | `debuff_duration` | 已消费 | 天赋一持续时间计时器 |
| 第一天赋 | `interval` | 已消费 | 天赋一跳字间隔（1.0s） |
| 第一天赋 | `max_stack_cnt` | 已消费 | 天赋一最大堆叠层数（3） |
| 第二天赋 | `attack_speed` | 已消费 | 基础攻速面板提升（+8/+10） |
| 第二天赋 | `attack_speed_add` | 已消费 | 邻接高台条件攻速提升（+6） |
| 第二天赋 | `cnt` | 已消费 | 高台判定所需最小数量（1） |
| 模组 X | `move_speed` | 已消费 | 模组特性范围内移速降低 -20% |
| 模组 Y | `prob` | 已消费 | 模组特性闪避率提升至 65% |
| 模组 Y | `hp_ratio` | 已消费 | 击倒带天赋一敌人回复生命（5%/10%） |
| 技能 1 | `atk_scale` | 已消费 | 连击攻击倍率 |
| 技能 1 | `cnt` | 已消费 | 充能层数上限 |
| 技能 2 | `atk` | 已消费 | 技能期间攻击力加成 |
| 技能 2 | `move_speed` | 已消费 | 技能范围内减速光环 |
| 技能 2 | `range_radius` | 已消费 | 击倒尸爆传播半径（1.3） |
| 技能 3 | `atk` | 已消费 | 技能期间攻击力加成 |
| 技能 3 | `base_attack_time` | 已消费 | 基础攻击间隔改写（缩短 1.5s） |
| 技能 3 | `taunt_level` | 已消费 | 技能期间嘲讽等级提升（+2） |
| 技能 3 | `attack@damage_hitrate_physical` | 已消费 | 范围内地面敌人物理未命中抽样判定 |
| 技能 3 | `attack@damage_hitrate_magical` | 已消费 | 范围内地面敌人物术未命中抽样判定 |
| 技能 3 | `attack@hp_ratio` | 已消费 | 闪避/未命中生命回复 |
