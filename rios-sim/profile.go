package main

import "math"

// profile.go：两套数值 profile 里**可独立验收的纯函数**（丙阶段四·第九、十批）。
//
// ## 为什么只做这一小块
//
// `simgo/skills.py:_profile`（`:202-256`）造两份快照——不开启那套与开启那套——
// 靠的是**驱动原版引擎的读数函数**（`op.current_atk()` / `current_defense()` /
// `current_res()` / `current_interval()` / `current_max_target()` /
// `active_attack_type()`）：临时把「这一帧开没开技能」的三个字段摆成开启态、
// 读完立刻还原。那需要一个能起 `sim` 的 harness，**本轮仍没搭**。
//
// 但已落地的两块**都不需要那个 harness**，因为它们的原版实现自己就是纯函数：
//
//   - `MaxHPAfterBonus` ← `_max_hp_after_bonus(op, eff)`；
//   - `AttackInterval` ← `SkillEffects.attack_interval`——`SkillEffects` 是
//     全字段有默认值的 dataclass，`SkillEffects(buffs=...)` 这个裸对象
//     就够当 oracle，不必起 sim。
//
// ## `_max_hp_after_bonus` 的来历
//
// `simgo/skills.py:239-255` 的注释写明：**这一段曾经整条没送**——规格里的
// `max_hp` 只有开场那一个静态值，于是「开技能把生命上限翻倍」的干员在 Go 侧
// 少了一半血：HS-EX-8 第 3 手圣聆初雪承受 2058 就倒，原版要到 4116（正好一半），
// **整局因此短了 18 秒**。
//
// 两处口径不许合并：
//
//   - 基准取 `_base_max_hp`，**不是** `op.max_hp`：后者是「主循环施加之后」的值，
//     照它当基准会越算越大；
//   - `base <= 0` 才回落到 `op.max_hp`（`or 0.0` → `if base <= 0.0`），
//     写 `< 0` 会让 `base == 0` 的路径分叉。
//
// ## `AttackInterval` 是两套快照的**同一行**
//
// 无技能帧那一侧不是另一条公式，而是同一函数空 buff 的特例
// （`simgo/spec.py:695-696`：`op.attack_interval × 100 / max(20, 总攻速)`）。
// 所以两套快照的间隔只差那一对 buff，实现上不许各写一份。

// : 攻击间隔的下限（`simgo/spec.py:58` 与 `operator/skill.py` 的 `MIN_INTERVAL`）。
// : 与 5% 保底那两个 0.05 不是同一个量，别互相借用。
const minInterval = 0.05

// MaxHPAfterBonus 复刻 `_max_hp_after_bonus`（`simgo/skills.py:186-199`）。
func MaxHPAfterBonus(baseMaxHP, curMaxHP, pct float64) float64 {
	base := baseMaxHP
	if base <= 0.0 {
		base = curMaxHP
	}
	return base * (1.0 + pct)
}

// AttackInterval 复刻干员侧的开技能间隔折算
// （`ak_tactic/operator/skill.py:1379-1400` 的 `SkillEffects.attack_interval`）。
//
//	间隔 = (基础间隔 ＋ 间隔加算) × 100 / max(20, 总攻速 ＋ 攻速加成)
//
// 再把结果夹到下限 0.05 秒。两个加算分别读 buffs 的 `attack_interval`
// 与 `attack_speed` 两个键。
//
// 两条修正**先加算秒数、再按攻速折算**，顺序不能换。`baseAttackSpeed` 传的是
// **总攻速**（基础 100 ＋ 天赋 ＋ 模组特性，由 `operator/attack_speed.py` 取数），
// 技能自己的攻速加成叠在它上面，所以两个 buff 是分开的两个入参。
//
// 下限 `aspdMin` 不夹的话，减速叠满会把间隔拉到无穷大、加速叠满又会打出
// 游戏里打不出的频率（见 `sim.go:47-50` 与 2026-09-16 的裁定）。
func AttackInterval(baseInterval, baseAttackSpeed, intervalBuff, speedBuff float64) float64 {
	spd := math.Max(aspdMin, baseAttackSpeed+speedBuff)
	return math.Max(minInterval, (baseInterval+intervalBuff)*100.0/spd)
}
