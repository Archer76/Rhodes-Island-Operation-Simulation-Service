package main

import "math"

// shuTick 驱动黍（char_2025_shu）在主战斗循环里的三件事：
//
//  1. 天赋一「百谷长青」：播种地块上友方每秒回血（技能2 期间倍率提升）；
//  2. 天赋二「天有四时」：三档光环（不同职业 / 相同职业 / 编队四岁）；
//  3. 技能三「离离枯荣」：地块传送与「地面敌人踩田」时的攻速/攻击加成。
//
// ⚠ 技力与技能开关**不在这里**：那是 `skillTick` 的职责（引擎既有状态机）。
// 这里自建一套 SP 计时会让同一个技能被两条时钟驱动——原会话就是这么崩的。
func shuTick(ops []*operator, enemies []*enemy, dt, t float64, spec *Spec, verdict *Verdict) {
	// 天赋二与技能三的光环都是"全场/范围内"效果：每帧先清零，再由在场的
	// 黍重算。不清零的话，条件消失（职业构成变了、敌人离开地块）之后
	// 增益会永远挂着。
	for _, op := range ops {
		op.shuMaxHpPct = 0
		op.shuAspd = 0
		op.shuAtkPct = 0
	}
	for _, op := range ops {
		if op.spec.CharID != shuCharID || op.shuState == nil {
			continue
		}
		if !op.alive() {
			// PRTS 天赋备注：「本天赋效果为永久地块效果，**自身退场时清空
			// 所有地块的播种效果**」。地块回血与庇护查询都以这张表为准，
			// 清表之后两者同时失效。
			op.shuState.clearSown()
			continue
		}
		st := op.shuState
		cfg := st.Config
		if st.SeasonSuiCount == 0 && spec != nil {
			st.SeasonSuiCount = countSuiInSquad(spec)
		}

		// ---- 1. 天赋一：播种地块每秒回血 ----
		//
		// 技能二「嘉禾盈仓」把第一天赋效果提升至 extra_extend_scale 倍。
		talentScale := 1.0
		if op.skillActive && cfg.Slot == 2 {
			talentScale = cfg.S2TalentScale
		}
		for _, ally := range ops {
			if !ally.alive() {
				continue
			}
			if tile, ok := st.SownTiles[cellOf(ally.cell)]; ok {
				// PRTS 天赋备注：生命恢复的提供方式是增加位于地块上干员的
				// 「生命回复速度」属性，不受治疗加成与禁疗影响 ⇒ 不走
				// `heal()`（治疗类能力），累加到属性上、本帧末尾按秒结算。
				ally.shuRecoveryPerSec += tile.Recovery * talentScale
			}
		}

		// ---- 2. 天赋二：天有四时 ----
		applyShuSeason(ops, st, dt)

		// ---- 3. 技能三：传送 + 踩田光环 ----
		if op.skillActive && cfg.Slot == 3 {
			applyShuTeleport(op, st, enemies, verdict, t)
			applyShuS3Aura(op, st, ops, enemies)
		}
	}
	// 结算「生命回复速度」属性：按秒加血，不走 heal（PRTS：不是治疗类能力，
	// 不受治疗加成与禁疗影响）。属性是**这一帧**累加的，结算完即清零。
	for _, op := range ops {
		if r := op.shuRecoveryPerSec; r > 0 && op.alive() {
			op.hp = math.Min(op.maxHP(), op.hp+r*dt)
		}
		op.shuRecoveryPerSec = 0
	}
	// 上限变化后把当前血量夹一次（条件消失时上限会降回去）。
	for _, op := range ops {
		if op.hp > op.maxHP() {
			op.hp = op.maxHP()
		}
	}
}

// shuSkillCells 把技能范围的相对格平移到黍的落点。
func shuSkillCells(op *operator, cfg *ShuRuntimeConfig) [][2]int {
	center := cellOf(op.cell)
	cx, cy := center[0], center[1]
	cells := make([][2]int, 0, len(cfg.SkillRangeCells))
	for _, c := range cfg.SkillRangeCells {
		cells = append(cells, [2]int{cx + c[0], cy + c[1]})
	}
	return cells
}

// applyShuS1Heal 实现技能一「化被草木」的**攻击附带治疗**。
//
// 判据：这一次真的出手了（调用点在出手计时归零之后）＋ 手里有充能
// ＋ 技能范围内有血量不足一半的友方。三者任一不成立就什么也不做——
// 没有充能时不治疗，也不能把充能"存着"到下次。
func applyShuS1Heal(op *operator, ops []*operator, verdict *Verdict) {
	st := op.shuState
	cfg := st.Config
	if cfg.Slot != 1 || st.Charges <= 0 {
		return
	}
	cells := shuSkillCells(op, cfg)
	var target *operator
	worst := 1.0
	for _, ally := range ops {
		if !ally.alive() || ally == op {
			continue
		}
		if !inCells(cells, cellOf(ally.cell)) {
			continue
		}
		ratio := ally.hp / ally.maxHP()
		if ratio >= 0.5 {
			continue
		}
		if target == nil || ratio < worst {
			target = ally
			worst = ratio
		}
	}
	if target == nil {
		return
	}
	st.Charges--
	amount := op.atk() * cfg.S1HealScale
	target.healFromCharacter(op, amount, verdict)
}

// 天赋原文是「**编队中**有四名【岁】干员」——不是场上。数场上会把
// 「带了四个岁的编队、只上了一半」误判成不满足。
func countSuiInSquad(spec *Spec) int {
	if spec == nil {
		return 0
	}
	n := 0
	for _, op := range spec.Operators {
		if op.GroupID == "sui" {
			n++
		}
	}
	return n
}

// applyShuSeason 实现天赋二的三档条件光环。
//
//	场上有 3 名不同职业干员 ⇒ 所有干员生命上限 +(max_hp)
//	场上有 3 名相同职业干员 ⇒ 所有干员攻击速度 +(attack_speed)
//	编队中有 4 名【岁】干员 ⇒ 所有干员攻击力 +(atk)、每 interval 秒获得 sp 点技力
func applyShuSeason(ops []*operator, st *ShuBattleState, dt float64) {
	cfg := st.Config
	if !cfg.SeasonEnabled {
		return
	}
	profCount := map[string]int{}
	for _, ally := range ops {
		if !ally.alive() || ally.spec.Profession == "" {
			continue
		}
		profCount[ally.spec.Profession]++
	}
	distinct, sameMost := 0, 0
	for _, n := range profCount {
		distinct++
		if n > sameMost {
			sameMost = n
		}
	}

	if distinct >= cfg.SeasonProfessionCount && cfg.SeasonMaxHPRatio > 0 {
		for _, ally := range ops {
			if ally.alive() {
				ally.shuMaxHpPct = math.Max(ally.shuMaxHpPct, cfg.SeasonMaxHPRatio)
			}
		}
	}
	if sameMost >= cfg.SeasonSameProfessionCnt && cfg.SeasonAspd > 0 {
		for _, ally := range ops {
			if ally.alive() {
				ally.shuAspd = math.Max(ally.shuAspd, cfg.SeasonAspd)
			}
		}
	}

	suiOK := st.SeasonSuiCount >= cfg.SeasonSuiDeployCount
	if !suiOK || cfg.SeasonAtkRatio <= 0 || cfg.SeasonSPInterval <= 0 || cfg.SeasonSPAmount <= 0 {
		st.SeasonSPTimer = 0
		return
	}
	for _, ally := range ops {
		if ally.alive() {
			ally.shuAtkPct = math.Max(ally.shuAtkPct, cfg.SeasonAtkRatio)
		}
	}
	st.SeasonSPTimer += dt
	for st.SeasonSPTimer >= cfg.SeasonSPInterval {
		st.SeasonSPTimer -= cfg.SeasonSPInterval
		for _, ally := range ops {
			if !ally.alive() {
				continue
			}
			cap := math.Inf(1)
			if sk := ally.spec.Skill; sk != nil {
				cap = sk.SPCost * math.Max(1, float64(sk.MaxCharge))
			}
			ally.sp = ally.spClock.AddNumeric(ally.sp, cfg.SeasonSPAmount, cap)
		}
	}
}

// applyShuTeleport 结算技能三的播种标记与传送。
//
// PRTS（revision 442689）：
//   - 地面敌人**经过播种地块时**被施加【播种标记】并记录当前所在地块，
//     已有标记不重复施加；
//   - 「该敌人**每次进入地块时**」按与记录地块的**曼哈顿距离**判定，
//     超过标注距离（游戏原文「超过」）则传送回记录地块**中心**；
//   - 传送**不重置已经过的路径点**（只改位置，不改 legIndex/legU/progress）；
//   - 标记只在该敌人进入消失状态时清除。
func applyShuTeleport(op *operator, st *ShuBattleState, enemies []*enemy, verdict *Verdict, t float64) {
	for _, e := range enemies {
		// 敌人消失（阵亡/漏出/离场）：标记自动清除，同时忘掉上一帧所在格。
		if !e.alive() || e.leaked || e.spec.IsFlying || e.offMap {
			delete(st.TeleportAnchors, e.index)
			delete(st.LastCells, e.index)
			continue
		}
		cell := cellOf(e.position)
		prev, had := st.LastCells[e.index]
		st.LastCells[e.index] = cell
		if had && prev == cell {
			// 没换格：不是「进入地块」，一帧都不判。
			continue
		}
		// 进入可标记地块 → 施加标记（已有不覆盖、免疫不施加）。
		if st.markable(cell) {
			if _, existed := st.TeleportAnchors[e.index]; !existed {
				st.anchorOnEnter(e, cell)
				if _, ok := st.TeleportAnchors[e.index]; ok {
					trace("SHU-ANCHOR t=%.2f enemy=%s cell=%v progress=%.3f", t, e.spec.Name, cell, e.progress)
				}
			}
		}
		// 进入地块时判定距离（曼哈顿、严格大于）。
		if a, ok := st.shouldTeleportOnEnter(e, cell); ok {
			trace("SHU-TP t=%.2f enemy=%s from=%v back=%v", t, e.spec.Name, e.position, a.AnchorCell)
			st.teleportToAnchor(e, a)
			st.LastCells[e.index] = a.AnchorCell
			if verdict != nil {
				verdict.Events = append(verdict.Events, Event{
					T: t, Kind: "shu_teleport", Who: op.spec.Name,
				})
			}
		}
	}
}

// applyShuS3Aura 实现技能三的条件光环：有地面敌人处于播种地块时，
// 技能范围内的我方单位攻击力 +(e_atk)、攻击速度 +(e_attack_speed)。
func applyShuS3Aura(op *operator, st *ShuBattleState, ops []*operator, enemies []*enemy) {
	cfg := st.Config
	if cfg.S3EnemyAtk <= 0 && cfg.S3EnemyAspd <= 0 {
		return
	}
	onField := false
	for _, e := range enemies {
		if !e.alive() || e.spec.IsFlying || e.offMap {
			continue
		}
		if st.isSown(cellOf(e.position)) {
			onField = true
			break
		}
	}
	if !onField {
		return
	}
	cells := op.targetRange()
	for _, ally := range ops {
		if !ally.alive() {
			continue
		}
		if !inCells(cells, cellOf(ally.cell)) {
			continue
		}
		ally.shuAtkPct = math.Max(ally.shuAtkPct, cfg.S3EnemyAtk)
		ally.shuAspd = math.Max(ally.shuAspd, cfg.S3EnemyAspd)
	}
}
