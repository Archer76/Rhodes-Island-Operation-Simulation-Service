# 乌尔比安（char_4145_ulpia）战斗机制全生命周期闭环口径

> 本文档依据 `docs/operator-mechanics-workflow.md` 撰写，记录乌尔比安在 `rios-sim` 中的机制建模、数据来源、黑板键消费与全生命周期实现状态。
> 数值全部来自 gamedata 源表原文（`character_table.json` / `skill_table.json` / `battle_equip_table.json` / `range_table.json`），规格层只存原文、配置层解析，**严禁任何硬编码数值**。

---

## 〇、基础规格

- **代号**：乌尔比安 / Ulpianus
- **干员标识**：`char_4145_ulpia`
- **职业分支**：近卫 - 重剑手（crusher）
- **稀有度**：六星
- **特性**：同时攻击阻挡的<@ba.kw>所有敌人</>（`operator_traits.go` 既有支持）。
- **技能槽**：`skchr_ulpia_1` / `skchr_ulpia_2` / `skchr_ulpia_3`
- **天赋解锁**：
  - 第一天赋「本性的坚守」在 `PHASE_1`（精英 1）解锁；
  - 第二天赋「血脉的哺养」在 `PHASE_2`（精英 2）解锁；
  - 天赋三在 `PHASE_0` 为占位空黑板。
- **专属模组**：
  - `uniequip_001_ulpia`：基础证章（INITIAL，不参与战斗加成）；
  - `uniequip_002_ulpia`：模组X「乌尔比安的新晨」（CRU-X，特性受治疗+20%，改写天赋一）；
  - `uniequip_003_ulpia`：模组Y「往前路去」（CRU-Y，特性对被阻挡敌人伤害+10%，改写天赋二）。
- **潜能编号口径**：游戏内 1–6（潜能 1 为基础档，潜能 5 对应 `requiredPotentialRank=4`）。

### 零近似原则与已知后果：**乌尔比安在位移等Gap闭合前整场拒判**

根据本仓建模纪律与 `sim.go:731` 的既定语义，`specMechanismGaps(spec)` 非空即抛出 `mechanisms.IncompleteError` 整场拒判。
乌尔比安包含以下未完成的物理与全局机制：
1. **技能一** `force=1.0` 包含位移拖拽机制（属于 roadmap M-X2，本仓目前无位移物理引擎），**严禁以原地攻击假装实现**，必须具名 Gap 拒判；
2. **技能三** `projectile_range` 与船锚投掷、落点部署判定、干员位移及技能结束返回初始位置属于复杂实体与位移系统（roadmap M-X2），必须具名 Gap 拒判；
3. **第二天赋** 对其他【深海猎人】干员的增益键（`ulpia_t_1[abyssal].*`），因当前引擎无跨干员阵营光环广播系统，已在配置层精确解析，但作为具名 Gap 登记。

**测试验证保证**：`ulpia_full_lifecycle_test.go` 中的 `TestUlpiaRefusedByMechanismGaps` 断言该拒判确实发生且精确具名；而帧内行使测试（`TestUlpiaFrameWiringTalent1AndTalent2` 等）对天赋与技能各数值和状态机逐帧取证，证明已实现机制真实生效。

---

## 一、第一天赋「本性的坚守」——已建模

原文：「每次受到伤害时，治疗自身 value1 点生命值；生命值低于 hp_ratio 时，治疗效果提升至 value2 点生命值」。

### 1. 数值档位（来自 `character_table.json` 及模组X 原文）

| 来源 / 阶段 | hp_ratio | value1 (常态自愈) | value2 (低血自愈) |
|---|---|---|---|
| 精英 1 | 0.5 | 80 | 120 |
| 精英 2 | 0.5 | 100 | 160 |
| 模组X 等级 2 | 0.5 | 120 | 170 |
| 模组X 等级 3 | 0.6 | 130 | 175 |

### 2. 运行期实现
- **触发入口**：挂在干员掉血唯一入口 `operator.hurt(dealt)` 之后。当且仅当真实受到伤害（`dealt > 0` 且 `op.alive()`）时触发。
- **阈值判定**：受击扣血后判断当前生命值百分比 `op.hp / op.maxHP()` 是否小于 `hp_ratio`。低于阈值时自愈 `value2` 点，否则自愈 `value1` 点。
- **技能二联动**：技能二开启期间，治疗效果享受 `talent_scale`（2.0倍）加成。
- **模组X 联动**：模组X 特性提供 `heal_scale`（1.2倍），自愈数值直接享受 1.2 倍加成。

---

## 二、第二天赋「血脉的哺养」——已建模（自身层数）与具名 Gap（队友光环）

原文：「每次击倒一名敌人时，自身的生命上限提高 max_hp，攻击力提高 atk，最多叠加 max_stack_cnt 次，其他【深海猎人】干员获得 50% 的提高效果」。
模组Y 升级：叠加 9 次后乌尔比安阻挡数 +1。

### 1. 数值档位与方括号变体键判定依据

#### 方括号键（`ulpia_t_1[abyssal].*`）判定依据：
在原始数据中，黑板键同时存在两组：
- 乌尔比安自身增益键：`max_stack_cnt`、`max_hp`、`atk`；
- 方括号变体键：`ulpia_t_1[abyssal].max_hp`、`ulpia_t_1[abyssal].atk`、`ulpia_t_1[abyssal].max_stack_cnt`。
**判定结论**：
1. 方括号键为**队友分发变体**（不是同义键，也不是独立叠加）。正文描述中明确指出「其他【深海猎人】干员获得 50%（模组升级后 55%/60%）的提高效果」，表中的数值正好是 `120 * 0.5 = 60`、`30 * 0.5 = 15`，即游戏数据表直接将队友享受的数值按方括号变体键预计算给出。
2. 乌尔比安自身击杀叠层仅消费自身键（`max_hp` 与 `atk`），严禁将方括号键与自身键并排重复叠加；队友光环部分作为未接线机制具名上报 Gap。

| 来源 / 潜能 | max_stack_cnt | max_hp / 层 | atk / 层 | 队友 abyssal.max_hp | 队友 abyssal.atk | 模组Y block_cnt (达到9层时) |
|---|---|---|---|---|---|---|
| E2 潜能 1–4 | 9 | 120 | 30 | 60 | 15 | - |
| E2 潜能 5–6 | 10 | 120 | 30 | 60 | 15 | - |
| 模组Y 潜能 1–4 | 9 | 140 / 150 (Lv3) | 35 / 38 (Lv3) | 77 / 90 (Lv3) | 19.25 / 22.8 (Lv3) | +1 (需9层) |
| 模组Y 潜能 5–6 | 10 | 140 / 150 (Lv3) | 35 / 38 (Lv3) | 77 / 90 (Lv3) | 19.25 / 22.8 (Lv3) | +1 (需9层) |

### 2. 运行期实现
- **击杀结算入口**：在主循环 `resolve()` 阶段，当敌人生命值归零（`e.hp <= 0 && !e.costAwarded`）且其 `lastHitBy` 是乌尔比安时触发 `ulpiaTalent2OnKill`。
- **面板加成**：
  - `operator.maxHP()` 动态加入 `st.KillStack * cfg.Talent2MaxHPPerStack`；
  - `operator.atk()` 动态加入 `st.KillStack * cfg.Talent2AtkPerStack`；
  - 封顶于 `cfg.Talent2MaxStackCnt`。
- **阻挡数增加**：当装备模组Y 且 `KillStack >= add_block_cnt_stack_cnt`（9层）时，`ulpiaBlockCntBonus()` 返回 +1，使基础阻挡数从 2 变 3。

---

## 三、专属模组特性与覆写

### 1. 模组X「乌尔比安的新晨」（CRU-X）
- **特性改写**：受到治疗效果提升至 `heal_scale` (1.2) 倍。
- **天赋改写**：天赋一自愈数值提升至 120/170（Lv2）与 130/175（Lv3，阈值提至 60%）。

### 2. 模组Y「往前路去」（CRU-Y）
- **特性改写**：对自身被阻挡的敌人造成的伤害提升至 `damage_scale` (1.1) 倍。
  - 实现位置：在普攻伤害结算 `resolveDamage` 后，若目标敌人处于 `op.blocking` 列表中，则伤害乘 1.1。
- **天赋改写**：天赋二每层数值提升至 140/35（Lv2）与 150/38（Lv3），满 9 层阻挡数 +1。

---

## 四、技能机制

### 1. 技能一「必须促成的接触」（`skchr_ulpia_1`）
- **类型**：自动回复 / 手动触发；spCost=4, initSp=0, duration=-1；范围 `3-2`（正前方 4 格）。
- **黑板键**：`atk_scale=2.7`, `max_target=2`, `force=1.0`。
- **实现与Gap**：
  - 倍率伤害与范围配置层严格解析；
  - `force=1.0` 为位移拖拽机制，按零近似原则严禁假装实现，具名上报 `ulpia.skill1.displacement_force` 拒判。

### 2. 技能二「必须维系的界限」（`skchr_ulpia_2`）
- **类型**：自动回复 / 手动触发；spCost=70, initSp=0, duration=-1（永续）；范围不变。
- **黑板键**：`talent_scale=2.0`, `atk=1.6`, `max_hp=0.6`, `block_cnt=1`。
- **实现状态**：**完全闭环**。
  - `atk` (+160%) 与 `max_hp` (+60%) 走既有技能面板链（`Profile`）；
  - `block_cnt=1` 在技能激活期间使阻挡数 +1（`sim.go` 的 `canBlock` 接入 `ulpiaBlockCntBonus()`）；
  - `talent_scale=2.0` 在技能开启期间使第一天赋受击自愈点数翻倍。

### 3. 技能三「必须开辟的通路」（`skchr_ulpia_3`）
- **类型**：自动回复 / 手动触发；spCost=25, initSp=20, duration=25s；范围 `6-1`（正前方 7 格）。
- **黑板键**：`max_hp=0.8`, `atk=2.6`, `atk_scale=1.6`, `stun=6.0`, `projectile_range=1.8`。
- **实现与Gap**：
  - 属性提升、伤害倍率、眩晕时长已在配置层精确解析；
  - 船锚投掷、落点检测与干员位移/返回原位属于物理与位移实体系统（roadmap M-X2），按零近似原则具名上报 `ulpia.skill3.projectile_displacement` 拒判。

---

## 五、黑板键全量审计台账

| 键名 | 归属来源 | 消费状态 | 处理方式与判定依据 |
|---|---|---|---|
| `hp_ratio` | 天赋一 / 模组X | 已消费 | 低血自愈百分比阈值判定 |
| `value1` | 天赋一 / 模组X | 已消费 | 常态受击自愈生命值 |
| `value2` | 天赋一 / 模组X | 已消费 | 低血受击自愈生命值 |
| `max_stack_cnt` | 天赋二 / 模组Y | 已消费 | 乌尔比安自身击杀叠加层数上限（9/10） |
| `max_hp` | 天赋二 / 模组Y | 已消费 | 每层叠加生命上限绝对值 |
| `atk` | 天赋二 / 模组Y | 已消费 | 每层叠加攻击力绝对值 |
| `ulpia_t_1[abyssal].max_hp` | 天赋二 / 模组Y | 具名 Gap | 队友深海猎人生命加成，因无跨干员广播系统具名拒判 |
| `ulpia_t_1[abyssal].atk` | 天赋二 / 模组Y | 具名 Gap | 队友深海猎人攻击加成，同上 |
| `ulpia_t_1[abyssal].max_stack_cnt` | 天赋二 / 模组Y | 具名 Gap | 队友深海猎人层数上限，同上 |
| `block_cnt` | 模组Y | 已消费 | 达到 9 层击杀叠加后阻挡数 +1 |
| `add_block_cnt_stack_cnt` | 模组Y | 已消费 | 触发阻挡数 +1 所需的层数阈值 (9) |
| `heal_scale` | 模组X 特性 | 已消费 | 受到的治疗效果提升 (1.2) |
| `damage_scale` | 模组Y 特性 | 已消费 | 对阻挡目标造成的伤害提升 (1.1) |
| `atk_scale` | 技能一 | 已消费 | 物理攻击倍率 (2.7) |
| `max_target` | 技能一 | 已消费 | 最大拖拽与攻击目标数 (2) |
| `force` | 技能一 | 具名 Gap | 位移拖拽力度，roadmap M-X2 缺口 |
| `talent_scale` | 技能二 | 已消费 | 第一天赋治疗效果倍率提升 (2.0) |
| `atk` | 技能二 | 已消费 | 攻击力提升 (+160%) |
| `max_hp` | 技能二 | 已消费 | 生命上限提升 (+60%) |
| `block_cnt` | 技能二 | 已消费 | 技能期间阻挡数 +1 |
| `max_hp` | 技能三 | 已消费 | 生命上限提升 (+80%) |
| `atk` | 技能三 | 已消费 | 攻击力提升 (+260%) |
| `atk_scale` | 技能三 | 已消费 | 技能爆发物理伤害倍率 (1.6) |
| `stun` | 技能三 | 已消费 | 眩晕秒数 (6.0) |
| `projectile_range` | 技能三 | 具名 Gap | 船锚投掷与干员位移落点范围，roadmap M-X2 缺口 |
