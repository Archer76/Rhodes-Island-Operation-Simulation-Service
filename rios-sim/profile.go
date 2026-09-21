package main

// profile.go：两套数值 profile 里**可独立验收的纯函数**（丙阶段四·第九批）。
//
// ## 为什么只做这一小块
//
// `simgo/skills.py:_profile`（`:202-256`）造两份快照——不开启那套与开启那套——
// 靠的是**驱动原版引擎的读数函数**（`op.current_atk()` / `current_defense()` /
// `current_res()` / `current_interval()` / `current_max_target()` /
// `active_attack_type()`）：临时把「这一帧开没开技能」的三个字段摆成开启态、
// 读完立刻还原。那需要一个能起 `sim` 的 harness，**本轮未搭**。
//
// 但其中**有一行是纯函数**，且它的来历值得单独钉住：
//
//	_max_hp_after_bonus(op, eff) = 基准 × (1 + buffs["max_hp"])
//	  基准 = op._base_max_hp（>0 时）否则 op.max_hp
//
// `simgo/skills.py:239-255` 的注释写明：**这一段曾经整条没送**——规格里的
// `max_hp` 只有开场那一个静态值，于是「开技能把生命上限翻倍」的干员在 Go 侧
// 少了一半血：HS-EX-8 第 3 手圣聆初雪承受 2058 就倒，原版要到 4116（正好一半），
// **整局因此短了 18 秒**。
//
// ## 两处口径不许合并
//
//   * 基准取 `_base_max_hp`，**不是** `op.max_hp`：后者是「主循环施加之后」的值，
//     照它当基准会越算越大；
//   * `base <= 0` 才回落到 `op.max_hp`（`or 0.0` → `if base <= 0.0`），
//     写 `< 0` 会让 `base == 0` 的路径分叉。

// MaxHPAfterBonus 复刻 `_max_hp_after_bonus`（`simgo/skills.py:186-199`）。
func MaxHPAfterBonus(baseMaxHP, curMaxHP, pct float64) float64 {
	base := baseMaxHP
	if base <= 0.0 {
		base = curMaxHP
	}
	return base * (1.0 + pct)
}
