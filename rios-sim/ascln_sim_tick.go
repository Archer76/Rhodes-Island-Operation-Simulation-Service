package main

// asclnSimTick 驱动阿斯卡纶在主战斗循环 sim.go 中的全局逻辑（按 ops 扫描）
func asclnSimTick(ops []*operator, enemies []*enemy, dt, t float64, spec *Spec, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.spec.CharID != asclnCharID || op.asclnRuntime == nil {
			continue
		}
		rt := op.asclnRuntime
		cfg := rt.Config

		// 若干员已倒下/撤退，清空所有施加的 debuff
		if !op.alive() {
			if len(rt.Debuffs) > 0 {
				rt.ClearAllDebuffs()
			}
			continue
		}

		// 推进干员自身技能持续时间
		if op.skillActive {
			rt.SkillActive = true
		} else {
			rt.SkillActive = false
		}

		// 检查第二天赋高台攻速加成应用
		if cfg.T2Unlocked {
			aspdBonus := cfg.T2AttackSpeed
			if rt.AdjacentHighground {
				aspdBonus += cfg.T2AttackSpeedAdd
			}
			_ = aspdBonus
		}

		// 第一天赋 debuff 推进与 DoT 伤害跳字
		currentAtk := op.atk()
		for _, e := range enemies {
			if e == nil || !e.alive() {
				continue
			}
			st, exists := rt.Debuffs[e.index]
			if !exists || st == nil {
				continue
			}

			// 持续时间递减
			st.RemainingTime -= dt
			if st.RemainingTime <= 0 {
				delete(rt.Debuffs, e.index)
				continue
			}

			// DoT 计时
			st.IntervalTimer += dt
			interval := cfg.T1Interval
			if interval <= 0 {
				interval = 1.0
			}
			for st.IntervalTimer >= interval {
				st.IntervalTimer -= interval
				dotDmg := currentAtk * cfg.T1AtkRatio * float64(st.Stacks)
				res := e.res()
				if res < 0 {
					res = 0
				}
				if res > 100 {
					res = 100
				}
				actualDmg := dotDmg * (1.0 - res/100.0)
				if actualDmg < 0.05*dotDmg {
					actualDmg = 0.05 * dotDmg
				}
				dealt := e.take(actualDmg, op)
				rt.TotalDoTDamage += dealt

				if !e.alive() {
					if verdict != nil {
						verdict.Kills++
					}
					// Y 模组击倒回复
					if cfg.T1OnKillHpRatio > 0 {
						heal := op.maxHP() * cfg.T1OnKillHpRatio
						op.hp += heal
						if op.hp > op.maxHP() {
							op.hp = op.maxHP()
						}
						rt.TotalHeal += heal
					}
					delete(rt.Debuffs, e.index)
					break
				}
			}
		}
	}
}

