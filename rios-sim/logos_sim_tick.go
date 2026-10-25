package main

// logos_sim_tick.go：把逻各斯的机制接到主战斗循环的帧序上。
//
// 位置与理由（照 `shuTick` 的先例）：
//
//   - 排在**我方出手之前**（帧序 5）：本帧要结算的斩杀与锁定伤害用的是这一帧
//     刚算出来的面板（含技能 `atk` 与法抗加成），放到帧末会让"技能刚开的那一拍"
//     迟到一帧；
//   - 技力与技能开关**不在这里**：那是引擎既有 `skillTick` 的职责。这里再自建
//     一套 SP 时钟，同一个技能就会被两条时钟驱动。
//
// 本文件只做三件事，全部是逻各斯独有的：
//
//	1. 技能一「殁亡」的逐帧斩杀（`logosS1Execute`）；
//	2. 技能二「提喻」的锁定多段伤害与减速（`logosS2Tick`）；
//	3. 技能结束/目标消失时的状态重置。
//
// 天赋二「剜魂具辞」**不在这里**：它是"打中那一刻"的效果，挂在上伤害的
// 出手点（`sim.go` 的 `operatorsAttackMode`），放到逐帧 tick 里会变成
// "每一帧都在给同一个人续一次减益"，时长永远续满。

// logosTick 驱动场上所有逻各斯。
func logosTick(ops []*operator, enemies []*enemy, dt, t float64, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.spec.CharID != logosCharID || op.logosState == nil {
			continue
		}
		st := op.logosState
		if !op.alive() {
			// 撤退/倒下：把挂在敌人身上的减速撤销，再清状态。
			st.reset()
			continue
		}
		if !op.skillActive {
			// 技能没开（或刚结束）：重置。技能一/二的效果只在技能期间成立。
			st.reset()
			continue
		}
		switch st.Config.Slot {
		case 1:
			logosS1Execute(op, st, enemies, t, verdict)
		case 2:
			logosS2Tick(op, st, enemies, dt, t, verdict)
		case 3:
			// 技能三「延异视阈」没有逐帧状态：攻击力与多目标走引擎既有面板链
			// （`atk` 黑板键 → `Profile.ATK`；`attack@max_target` → `maxTarget()`），
			// 范围扩大走 `targetRange()` 的技能范围覆盖。
			//
			// ⚠ 正文那一半「使攻击范围内敌方子弹的飞行速度大幅降低、并在技能结束时
			// 将其全部清除」**未建模**：本仓没有敌方弹道实体（`projectile_move_scale`
			// 因此没有落点）。它是**具名缺口**，不是"忘了写"——见
			// `logosRemainingGapsFromSpec` 的 `logos.projectile_slow`。
		}
	}
}
