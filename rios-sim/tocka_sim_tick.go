package main

// tockaSimTick 驱动冻河在主战斗循环中的全局时序逻辑
func tockaSimTick(ops []*operator, enemies []*enemy, dt, t float64, spec *Spec, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.spec.CharID != tockaCharID || op.tockaRuntime == nil {
			continue
		}
		rt := op.tockaRuntime
		cfg := rt.Config

		// 若干员已倒下/撤退，清空所有协同与状态
		if !op.alive() {
			rt.ClearAll()
			continue
		}

		// 1. 技能释放瞬发处理 (S1 与 S2 为 duration == -1.0 的瞬发技能)
		if op.skillActive {
			if cfg.Slot == 1 {
				// S1：选取攻击范围内未持有该效果的干员，至多 S1MaxTarget 名
				appliedCount := 0
				for _, ally := range ops {
					if ally == nil || !ally.alive() || ally == op {
						continue
					}
					if !inCells(op.targetRange(), [2]int{int(ally.cell[0]), int(ally.cell[1])}) {
						continue
					}
					st, exists := rt.OpStates[ally]
					if exists && st.TriggerKind != TockaTriggerNone {
						continue // 只选择未持有该效果的目标
					}
					rt.ApplyS1Trigger(ally)
					appliedCount++
					if appliedCount >= cfg.S1MaxTarget {
						break
					}
				}
				// 瞬发结算：重置技力与激活状态
				op.sp = 0
				op.skillActive = false
			} else if cfg.Slot == 2 {
				// S2：在全场选取未持有该效果的干员，至多 S2MaxTarget 名
				appliedCount := 0
				for _, ally := range ops {
					if ally == nil || !ally.alive() || ally == op {
						continue
					}
					st, exists := rt.OpStates[ally]
					if exists && st.TriggerKind != TockaTriggerNone {
						continue
					}
					rt.ApplyS2Trigger(ally)
					appliedCount++
					if appliedCount >= cfg.S2MaxTarget {
						break
					}
				}
				// 瞬发结算
				op.sp = 0
				op.skillActive = false
			} else if cfg.Slot == 3 {
				// S3：持续型技能。检查开技初动瞬发施加
				// 当技能刚开启时，立刻对攻击范围内另一名干员施加触发型效果（已存在时改为将其触发）
				if !rt.S3InitialCastDone {
					rt.S3InitialCastDone = true
					var targetAlly *operator
					var existingAlly *operator

					for _, ally := range ops {
						if ally == nil || !ally.alive() || ally == op {
							continue
						}
						if !inCells(op.targetRange(), [2]int{int(ally.cell[0]), int(ally.cell[1])}) {
							continue
						}
						st, exists := rt.OpStates[ally]
						if exists && st.TriggerKind == TockaTriggerS3 {
							existingAlly = ally
							break
						}
						if targetAlly == nil {
							targetAlly = ally
						}
					}

					if existingAlly != nil {
						// 已存在时改为将其触发
						rt.HandleAllySkillActivated(existingAlly, op, ops)
					} else if targetAlly != nil {
						rt.ApplyS3Trigger(targetAlly)
					}
				}

				// S3 激活期间，持有该效果的干员每秒获得 bonus_sp 点技力
				for _, ally := range ops {
					if ally == nil || !ally.alive() {
						continue
					}
					st, exists := rt.OpStates[ally]
					if exists && st.TriggerKind == TockaTriggerS3 {
						if ally.spec.Skill != nil && ally.spec.Skill.SPCost > 0 {
							maxSP := float64(ally.spec.Skill.SPCost)
							if ally.sp < maxSP {
								ally.sp += cfg.S3BonusSP * dt
								if ally.sp > maxSP {
									ally.sp = maxSP
								}
							}
						}
					}
				}
			}
		} else {
			rt.S3InitialCastDone = false
		}

		// 2. 推进友方干员身上的协同衍生状态
		for ally, st := range rt.OpStates {
			if ally == nil || !ally.alive() {
				delete(rt.OpStates, ally)
				continue
			}

			// S1 衰减屏障
			if st.Barrier > 0 {
				st.Barrier -= st.BarrierDecayRate * dt
				if st.Barrier < 0 {
					st.Barrier = 0
				}
			}

			// S2 攻速与自动开启时限
			if st.S2AspdBuffTime > 0 {
				st.S2AspdBuffTime -= dt
				if st.S2AspdBuffTime <= 0 {
					st.S2AspdBuffTime = 0
					st.S2AspdBonus = 0
					st.S2AutoTrigger = false
				}
			}

			// 持有者 S3 衰减攻击力加成
			if st.DecayAtkTime > 0 {
				st.DecayAtkTime -= dt
				st.DecayAtkBuff -= st.DecayAtkDecayRate * dt
				if st.DecayAtkBuff < 0 || st.DecayAtkTime <= 0 {
					st.DecayAtkBuff = 0
					st.DecayAtkTime = 0
				}
			}

			// 检查持有 S2 标记的友方干员技能是否就绪
			if st.TriggerKind == TockaTriggerS2 {
				rt.HandleAllySkillReady(ally, op, ops)
			}

			// 若处于 S2 自动开启托管期且技能满 SP，自动触发开启
			if st.S2AutoTrigger {
				if ally.spec.Skill != nil && ally.spec.Skill.SPCost > 0 {
					maxSP := float64(ally.spec.Skill.SPCost)
					if ally.sp >= maxSP && !ally.skillActive {
						ally.skillActive = true
						ally.sp = 0
						// 如果同时持有 S3 标记，触发 S3 开技
						if st.TriggerKind == TockaTriggerS3 {
							rt.HandleAllySkillActivated(ally, op, ops)
						}
					}
				}
			}
		}

		// 3. 推进冻河自身的 S3 衰减攻击力加成
		if rt.SelfDecayAtkTime > 0 {
			rt.SelfDecayAtkTime -= dt
			rt.SelfDecayAtkBuff -= rt.SelfDecayAtkDecayRate * dt
			if rt.SelfDecayAtkBuff < 0 || rt.SelfDecayAtkTime <= 0 {
				rt.SelfDecayAtkBuff = 0
				rt.SelfDecayAtkTime = 0
			}
		}

		// 4. 第二天赋「雪的印痕」虚弱与法术 DoT 推进
		tockaAtk := op.atk()
		for _, e := range enemies {
			if e == nil || !e.alive() {
				continue
			}
			st, exists := rt.WeakenDebuffs[e.index]
			if !exists || st == nil {
				continue
			}

			// 持续时间递减
			st.RemainingTime -= dt
			if st.RemainingTime <= 0 {
				delete(rt.WeakenDebuffs, e.index)
				continue
			}

			// DoT 每秒跳字
			st.IntervalTimer += dt
			for st.IntervalTimer >= 1.0 {
				st.IntervalTimer -= 1.0
				dotDmg := tockaAtk * st.DotRatio
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
					delete(rt.WeakenDebuffs, e.index)
					break
				}
			}
		}
	}
}
