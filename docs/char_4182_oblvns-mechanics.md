# 丰川祥子（char_4182_oblvns / oblivionis）战斗机制全生命周期闭环口径

> 本文档依据 `docs/operator-mechanics-workflow.md` 标准工作规程撰写，记录丰川祥子（代号 oblivionis）在 `rios-sim` 仿真引擎中的机制建模、数据来源、黑板键消费与全生命周期实现状态。
> 原始数据来自 `data/akdb.sqlite` 与官方游戏源表（`character_table.json`、`skill_table.json`、`battle_equip_table.json`、`uniequip_table.json`），杜绝臆测与伪造。

---

## 〇、干员背景与基础规格

- **代号**：oblivionis / 丰川祥子
- **干员标识**：`char_4182_oblvns`
- **职业分支**：近卫 - 领主（Lord）
- **阻挡数**：2
- **基础攻击间隔**：1.3 秒（39 帧 @ 30fps）
- **潜能编号口径**：本项目严格遵循游戏内 1–6 编号口径（潜能 1 为基础获得，潜能 6 为满潜）。
  - 潜能 2：部署费用 -1
  - 潜能 3：第一天赋效果增强
  - 潜能 4：攻击力 +35
  - 潜能 5：第二天赋效果增强
  - 潜能 6：部署费用 -1

---

## 一、特性与专属模组规格（uniequip_002_oblvns）

### 1. 领主分支特性
- **基础特性**：可以进行远程攻击，此时攻击力降低至 80%（`RangedAtkScale = 0.8`）。
- **近战与远程判据**：严格遵循博士裁定——被攻击的敌人若处于未被阻挡状态（`target.blockedBy != op`），无论几何朝向均判定为远程攻击；若被阻挡则判定为近战攻击（无衰减）。

### 2. 模组二/三级特性与天赋升级（TALENT_DATA_ONLY）
数据来源于 `battle_equip_table.json` 中 `uniequip_002_oblvns` 的第 2 与第 3 phase：
- **条件攻速（TRAIT）**：攻击范围内存在 2 名及以上敌人时，攻击速度 +12（`attack_speed: 12.0`）。
- **远程豁免（Skill Ranged Exemption）**：技能期间远程攻击不再降低攻击力（豁免 0.8 衰减，倍率保持 1.0）。
- **天赋升级「颂乐音符」**：
  - 丰川祥子可以持续攻击且攻击会演奏追踪敌人的音符，音符飘出攻击范围一段时间后消失。
  - 每存在一个音符，Ave Mujica 成员无视敌人一定比例的防御力和法术抗性，最多可叠加 12 层（`max_cnt: 12.0`）。
  - **模组 2 级**：
    - `def_penetrate_ratio = 0.04`（每层无视 4% 防御力）
    - `magic_resist_penetrate_ratio = 0.02`（每层无视 2% 法术抗性）
    - `delay = 1.0`（音符飞出攻击范围后存活 1.0 秒）
    - `attack@angle = 20.0`
  - **模组 3 级**：
    - `def_penetrate_ratio = 0.05`（每层无视 5% 防御力）
    - `magic_resist_penetrate_ratio = 0.025`（每层无视 2.5% 法术抗性）
    - `delay = 1.0`
    - `attack@angle = 20.0`

---

## 二、音符领域机制与状态机（Domain Mechanics）

音符实体由 `sakikoOrdinaryStore` 与 `sakikoOrdinaryNote` 统一管理，实现严格的三态生命周期状态机：

```
           launch / launchSine
                   │
                   ▼
         ┌───────────────────┐
         │  sakikoNoteFree   │ ◄──────┐ (目标阵亡/失效)
         └─────────┬─────────┘        │
                   │ (索敌半径1.0内   │
                   │  锁定目标)       │
                   ▼                  │
         ┌───────────────────┐        │
         │sakikoNoteTracking ├────────┘
         └─────────┬─────────┘
                   │ (逼近目标 /
                   │  命中结算)
                   ▼
         ┌───────────────────┐
         │ sakikoNoteRemoved │
         └───────────────────┘
```

1. **自由正弦飞行（Free Phase）**：
   - 当无目标时，音符按扩张正弦轨迹飞行（`sakikoOrdinarySine`），线速度为 1.3 格/秒，基础振幅 0.3 格，并根据周期数放大；
   - 正弦交替方向严格按照发射顺序正负交替；
   - 飞行过程中每帧以 1.0 格为半径执行最近目标检测（`nearestSakikoOrdinaryNoteTarget`）。
2. **追踪飞行（Tracking Phase）**：
   - 锁定目标后，音符按加权转向插值（`sakikoOrdinaryTurn`）实时追踪目标敌人位置；
   - 目标阵亡时，音符安全转回 `sakikoNoteFree` 状态，不产生空中野指针悬空。
3. **撤退清理（Retreat Lifecycle）**：
   - 干员撤退或被击倒瞬间调用 `sourceRetreat()`，自由音符立即安全移除，已在追踪途中的音符完成当前伤害结算后销毁。

---

## 三、穿透伤害与战斗循环集成（Engine Integration）

1. **规格与配置挂钩**：
   - `rios-sim/sakiko_spec.go` 中声明 `SakikoSourceSpec` 与 `defaultSakikoSource()`。
   - `rios-sim/operators.go` 与 `rios-sim/wire.go` 中接驳 `SakikoSource`。
2. **主战斗循环接驳**：
   - **部署初始化**：干员入场时实例化 `sakikoOrdinaryStore`。
   - **每帧状态推进**：在战斗主循环中调用 `sakikoTick(ops, enemies, dt, t, verdict)`，驱动所有活跃音符的飞行、索敌、碰撞与状态跃迁。
   - **穿透伤害计算**：
     $$\text{defPen} = \text{otherDefPen} + \min(\text{count}, \text{max\_cnt}) \times \text{def\_penetrate\_ratio}$$
     $$\text{resPen} = \text{otherResPen} + \min(\text{count}, \text{max\_cnt}) \times \text{magic\_resist\_penetrate\_ratio}$$
     通过 `consumeSakikoNoteDamage` 真实扣减目标敌人生命值，记录 `sakiko_note_hit` 与 `kill` 事件。
3. **机制缺口闭合**：
   - 在 `count_module_resolver.go` 与 `mechanism_gaps.go` 中，对配置了有效 `SakikoSource` 且 `ConsumerImplemented: true` 的干员放行，解除 `module.talent_override` 与 `runtime.skill_ranged_exemption` 缺口拦截。

---

## 四、黑板键消费与机制 Gaps 审计台账

| 来源 | 黑板键 / 字段 | 状态 | 消费位置 / 裁定说明 |
|---|---|:---:|---|
| 特性 | `RangedAtkScale = 0.8` | ✅ 已消费 | `sim.go:rangedScaleFor`，未阻挡目标远程衰减 |
| 模组特性 | `SkillRangedExemption` | ✅ 已消费 | `sim.go` 技能期间豁免远程倍率衰减（1.0 结算） |
| 模组特性 | `attack_speed = 12.0` | ✅ 已消费 | `count_module.go:countModuleASPD`，≥2名敌人攻速生效 |
| 模组天赋 | `def_penetrate_ratio` | ✅ 已消费 | `sakiko_note_damage.go`，物理防御穿透累积 |
| 模组天赋 | `magic_resist_penetrate_ratio`| ✅ 已消费 | `sakiko_note_damage.go`，法术抗性穿透累积 |
| 模组天赋 | `max_cnt = 12.0` | ✅ 已消费 | `sakiko_note_damage.go`，穿透最大叠加层数 |
| 模组天赋 | `delay = 1.0` | ✅ 已消费 | `sakiko_spec.go` / 音符飞行存活周期 |
| 模组天赋 | `attack@angle = 20.0` | ✅ 已消费 | 音符初始发散角配置 |
| 普攻/音符 | 正弦轨迹与追踪转向 | ✅ 已消费 | `sakiko_note_sine.go` / `sakiko_note_turn.go` |
| 普攻/音符 | 索敌与锁定机制 | ✅ 已消费 | `sakiko_note_acquire.go`，1.0 格半径最近优先 |
| 普攻/音符 | 撤退生命周期清理 | ✅ 已消费 | `sakiko_note_store.go:sourceRetreat` |
| 技能 1 | `skchr_oblvns_1` (天鹅之死) | 🔶 占位守卫 | 普攻/模组音符已闭合；技能特定多段弹药状态机保留占位 |
| 技能 2 | `skchr_oblvns_2` (阿刻戎) | 🔶 占位守卫 | 模组远程豁免已生效；音色切换技能状态机保留占位 |
| 技能 3 | `skchr_oblvns_3` (假面舞宴) | 🔶 占位守卫 | 双目标防御/法抗极值索敌与致死保护保留占位 |

---

## 五、验收测试结论

1. **单元测试矩阵**：
   - `sakiko_note_state_test.go`：PASS（状态机构建、更新与异常跃迁拦截）
   - `sakiko_note_turn_test.go`：PASS（加权转向插值与权重验证）
   - `sakiko_note_sine_test.go`：PASS（正弦三周期轨迹与边界拦截）
   - `sakiko_note_acquire_test.go`：PASS（最近目标索敌与重复/等距守卫）
   - `sakiko_note_damage_test.go`：PASS（防御与法抗穿透及实际伤害计算）
   - `sakiko_note_motion_test.go`：PASS（正弦自由段重入与绑定）
2. **全生命周期测试**：
   - `sakiko_full_lifecycle_test.go`：
     - `TestSakikoFullBattleLifecycle`：PASS（部署、发射、索敌锁定、追踪命中、全歼击杀全链事件闭环）
     - `TestSakikoSineAcquisitionAndRetreatCleanup`：PASS（无目标正弦发射、动态索敌命中、撤退立即清理全生命周期验证）
3. **全包回归测试**：
   - 全仿真引擎包及工具链回归测试通过，无静默降级假绿，零近似。
