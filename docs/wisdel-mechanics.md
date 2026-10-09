# 维什戴尔（char_1035_wisdel）战斗机制口径与建模规格

> 本文档记录维什戴尔在 `ak-tactic`（尤其是 Go 引擎 `rios-sim`）中的机制定义、数据来源、黑板键消费情况与建模实现方案。
> 遵循 `docs/operator-mechanics-workflow.md` 规程。

---

## 〇、基本属性与潜能

- **代号**：`char_1035_wisdel`
- **职业/子职业**：狙击·投掷手（高台物理、攻击对小范围地面敌人造成伤害、阻挡数 1、基础攻击间隔 2.1s）
- **攻击范围**：
  - 精0：`3-3`（12格，向前3格×宽3格）
  - 精1/精2：`3-9`（19格，向前3格×宽5格 + 顶端单格延伸）
- **潜能（游戏内编号 1–6）**：
  - 潜能 1：基础
  - 潜能 2：部署费用 -1
  - 潜能 3：再部署时间 -4秒
  - 潜能 4：攻击力 +32
  - 潜能 5：第一天赋效果增强（爆炸伤害+10%）
  - 潜能 6：部署费用 -1

---

## 一、特性、天赋与专属模组机制

### 1. 投掷手特性
- **无模组**：攻击对小范围的地面敌人造成**两次**物理伤害（第二次为余震，伤害降低至攻击力的 50%）。
  - 黑板键：`attack@append_atk_scale: 0.5`, `attack@enable_third_attack: 0.0`
- **专属模组 `uniequip_002_wisdel`（“祖宗发射器”，X模 1~3级）**：
  - 属性增益：
    - Lv1：攻击力 +45，攻击速度 +5
    - Lv2：攻击力 +55，攻击速度 +6
    - Lv3：攻击力 +65，攻击速度 +7
  - 特性强化（Lv1~3级均生效）：
    - 攻击对小范围地面敌人造成**三次**物理伤害（后两次为余震，伤害均为攻击力的 50%）。
    - 黑板键：`attack@append_atk_scale: 0.5`, `attack@enable_third_attack: 1.0`
  - 天赋强化（Lv2~3级改写第一天赋「好礼」）：见下节。

### 2. 第一天赋「好礼」
- 触发机制：
  - 维什戴尔普通攻击命中主目标时，为主目标附着**残影**（Mark/Residual Shadow）。
  - 当带有残影的目标受到**维什戴尔的余震**伤害影响时，有概率（常态 15%，技3期间提升至 100%）引发爆炸。
  - 爆炸效果：以目标为中心半径 `attack@range_radius: 1.1` 的小范围内所有敌人造成物理伤害并使其眩晕。
- 数值矩阵（含潜能与模组升级）：
  - **精1（潜1~4）**：主目标攻击力 100%，爆炸伤害 120%，眩晕 0.5s，概率 15%
  - **精1（潜5~6）**：主目标攻击力 100%，爆炸伤害 130%，眩晕 0.5s，概率 15%
  - **精2（潜1~4，无模组/模组Lv1）**：主目标攻击力提升至 115%，爆炸伤害 150%，眩晕 1.0s，概率 15%
  - **精2（潜5~6，无模组/模组Lv1）**：主目标攻击力提升至 115%，爆炸伤害 160%，眩晕 1.0s，概率 15%
  - **精2（潜1~4，模组Lv2）**：主目标攻击力提升至 120%，爆炸伤害 170%，眩晕 1.0s，概率 15%
  - **精2（潜5~6，模组Lv2）**：主目标攻击力提升至 120%，爆炸伤害 180%，眩晕 1.0s，概率 15%
  - **精2（潜1~4，模组Lv3）**：主目标攻击力提升至 125%，爆炸伤害 175%，眩晕 1.0s，概率 15%
  - **精2（潜5~6，模组Lv3）**：主目标攻击力提升至 125%，爆炸伤害 185%，眩晕 1.0s，概率 15%

### 3. 第二天赋「死魂灵的余息」
- 解锁条件：精2 1级。
- 效果：
  - 部署后立刻在攻击范围内召唤一个**魂灵之影**（`token_10035_wisdel_wward`）。
  - 召唤位置寻位优先级：攻击范围内离维什戴尔最近、可放置地面/高台且无单位占用的地块。
  - **迷彩效果**：维什戴尔处于魂灵之影周围（相邻 8 格或同格）时获得**迷彩**（不成为敌方远程攻击目标，但仍受范围伤害）。

---

## 二、召唤物实体：魂灵之影（`token_10035_wisdel_wward`）

- **属性**：
  - 随维什戴尔精英阶段与等级同比例成长（HP 3500，ATK 385~777，DEF 457~650，RES 50，阻挡 0，攻击间隔 1.0s）。
  - 无被动普攻，靠自动技能进行攻击与干扰。
- **攻击范围**：
  - 自身范围为 `0-1`（自身所在格），但其技能可攻击**维什戴尔攻击范围内**的敌人。
- **自动技能「魂灵之影」**（`sktok_wisdel_wward`）：
  - 消耗 SP 5.0，初始 SP 0.0，自然回复，自动触发。
  - 对一名在维什戴尔攻击范围内的敌人造成自身攻击力 100% 的法术伤害；
  - 施加 `sluggish: 1.0` 秒停顿（移速 -80%）；
  - 为该目标附着**残影**（可与第一天赋联动）；
  - 攻击完成后，为维什戴尔恢复随机 `[sp_min: 0, sp_max: 3)`（实为 0~2 点）SP。

---

## 三、技能机制全量盘点

### 1. 技1「定点清算」（`skchr_wisdel_1`）
- 消耗/初动/持续：SP 4~2（Lv10 为 2 SP），初始 0，攻击回复，自动触发。
- 效果：
  - 下次攻击额外造成 2 次余震（无模组共 4 次伤害，有模组共 5 次伤害）；
  - 溅射范围扩大；
  - 所有余震伤害变为攻击力的 `{append_atk_scale:0%}`（Lv1: 60% ~ Lv10: 120%）；
  - 使溅射范围内所有目标眩晕 `{stun_duration}` 秒（Lv1: 0.5s ~ Lv10: 1.5s）。

### 2. 技2「饱和复仇」（`skchr_wisdel_2`）
- 消耗/初动/持续：SP 35~25（Lv10 为 25 SP），初始 15，自然回复，持续 25s，手动可随时关闭。
- 效果：
  - 攻击力提升：`+{atk:0%}`（Lv1: 10% ~ Lv10: 35%）；
  - 基础攻击间隔缩短：`{base_attack_time}`（Lv1: -0.5s ~ Lv10: -0.7s，由 2.1s 变为 1.4s）；
  - 同时攻击目标数：3 名敌人；
  - **过载机制（Overdrive）**：持续时间过半（12.5s）后进入过载状态：
    - 攻击改为攻击力 `{attack@atk_scale_ol:0%}`（Lv1: 60% ~ Lv10: 80%）的 **4 连发**；
    - 随机攻击范围内的目标（每次攻击随机索敌）。

### 3. 技3「爆裂黎明」（`skchr_wisdel_3`）
- 消耗/初动/持续：SP 70~50（Lv10 为 50 SP），初始 25~40（Lv10 为 40 SP），自然回复，弹药机制（6发），手动可随时关闭。
- 效果：
  - 开启瞬间立刻在攻击范围内召唤 `{max_cnt}` 个魂灵之影（Lv1~6: 1个，Lv7~10: 2个；全场魂灵之影最多存在 3 个，技能结束后保留）；
  - 攻击力大幅提升：`+{atk:0%}`（Lv1: 95% ~ Lv10: 180%）；
  - 攻击间隔大幅增大：`+{base_attack_time}`（+2.9s，基础攻击间隔增至 5.0s）；
  - 攻击时对主目标攻击力提升至 `{attack@atk_scale_3:0%}`（Lv1: 160% ~ Lv10: 220%）；
  - 溅射范围大幅扩大；
  - 第一天赋残影爆炸概率锁定提升至 **100%**（`attack@prob: 1.0`）；
  - 装填 `{attack@trigger_time}` 发弹药（6 发），打完后技能自动结束。

---

## 四、全量黑板键（Blackboard Keys）审计台账

| 序号 | 黑板键名 | 关联机制与来源 | 消费去向与处理 |
|---|---|---|---|
| 1 | `append_atk_scale` | 技1 余震伤害倍率 | `wisdelCombatState.OnSkill1` 计算余震物理伤害 |
| 2 | `stun_duration` | 技1 眩晕持续时间 | `wisdelCombatState.OnSkill1` 赋予眩晕状态 |
| 3 | `atk` | 技2, 技3 攻击力加成比例 | `wisdelCombatState.EffectiveATK` 面板乘区结算 |
| 4 | `base_attack_time` | 技2(缩短), 技3(增大) 基础攻击间隔修正 | `wisdelCombatState.BaseAttackTime` 攻击间隔计算 |
| 5 | `attack@atk_scale_ol` | 技2 过载阶段 4 连发单发攻击力倍率 | `wisdelCombatState.OnSkill2Attack` 过载 4 连击计算 |
| 6 | `attack@atk_scale_3` | 技3 攻击时对主目标攻击力提升倍率 | `wisdelCombatState.OnSkill3Attack` 主目标伤害计算 |
| 7 | `attack@prob` | 天赋1(15%), 技3(100%) 残影爆炸概率 | `wisdelCombatState.RollShadowBomb` 判定爆炸触发 |
| 8 | `attack@trigger_time` | 技3 弹药装填数（6 发） | `wisdelCombatState.Skill3Ammo` 弹药扣减与生命周期 |
| 9 | `max_cnt` | 技3 开启时召唤魂灵之影数量上限 | `wisdelCombatState.ActivateSkill3` 召唤指定数量魂灵 |
| 10 | `sp` | 技3 内部参数 | 规格/配置层严格保留并审计 |
| 11 | `attack@append_atk_scale` | 特性与模组余震倍率（0.5） | `wisdelCombatState.TraitAftershockScale` |
| 12 | `attack@enable_third_attack` | 模组开启第 3 次余震（1.0） | `wisdelCombatState.HasThirdAftershock` |
| 13 | `attack@main_atk_scale` | 天赋1、模组对主目标基础攻击倍率 | `wisdelCombatState.TalentMainAtkScale` |
| 14 | `attack@bomb_atk_scale` | 天赋1、模组残影爆炸 AOE 伤害倍率 | `wisdelCombatState.TalentBombAtkScale` |
| 15 | `attack@stun` | 天赋1、模组残影爆炸眩晕时长（0.5/1.0s） | `wisdelCombatState.TalentBombStun` |
| 16 | `attack@range_radius` | 天赋1、模组残影爆炸范围半径（1.1格） | `wisdelCombatState.TalentBombRadius` |
| 17 | `sluggish` | 魂灵之影技能停顿时间（1.0s） | `wisdelWard.Attack` 施加停顿 |
| 18 | `sp_min` | 魂灵之影技能回复 SP 随机下限（0.0） | `wisdelWard.Attack` 随机回 SP |
| 19 | `sp_max` | 魂灵之影技能回复 SP 随机上限（3.0） | `wisdelWard.Attack` 随机回 SP |

---

## 五、Go 架构与代码设计

```
rios-sim/
 ├─ wisdel_spec.go          // 从 character_table/skill_table/battle_equip_table 提取原始证据与分级
 ├─ wisdel_spec_test.go     // 全矩阵覆盖单测（E0~E2, Pot1~6, S1~S3 Lv1~10, Module Lv0~3）
 ├─ wisdel_config.go        // 强类型配置映射，严格校验 19 个黑板键
 ├─ wisdel_config_test.go   // 黑板解析与边界单测
 ├─ wisdel_ward.go          // 魂灵之影实体：召唤寻位、属性继承、迷彩覆盖范围、技能 Tick 与 SP 赠送
 ├─ wisdel_ward_test.go     // 魂灵之影召唤、寻位与迷彩单测
 ├─ wisdel_combat.go        // 维什戴尔核心战斗状态机：投掷手余震、残影附着与爆炸、技1/技2/技3生命周期
 ├─ wisdel_combat_test.go   // 伤害段数、爆炸概率、弹药与过载生命周期单测
 └─ operators.go / wire.go  // 接入引擎 OperatorOut、序列化与仿真循环
```
