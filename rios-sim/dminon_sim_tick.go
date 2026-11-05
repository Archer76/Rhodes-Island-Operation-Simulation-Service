package main

import (
	"math"
)

// dminonSimTick 驱动国度（char_4246_dminon）在主战斗循环 sim.go 中的全局逻辑
func dminonSimTick(ops []*operator, enemies []*enemy, dt, t float64, spec *Spec, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.spec.CharID != dminonCharID || op.dminonRuntime == nil {
			continue
		}
		rt := op.dminonRuntime
		cfg := rt.Config

		// 1. 第二天赋【此身为界】：离场（被击倒或主动撤退）瞬间引爆并清空国度
		if rt.WasAlive && !op.alive() {
			rt.TriggerRetreatExplosion(enemies, op, t, verdict)
			rt.WasAlive = false
			continue
		}
		if !op.alive() {
			continue
		}

		// 2. 技能生命周期与状态维护
		if op.skillActive {
			if !rt.SkillActive {
				rt.OnSkillStart()
			}
			// 技2 永续逻辑：第二次使用后持续时间无限
			if cfg.Slot == 2 && rt.IsPermanent {
				op.skillActive = true
				op.skillTimer = math.Inf(1)
			}
		} else {
			if rt.SkillActive {
				rt.OnSkillEnd()
			}
		}

		// 3. 技能三反击冷却计时器递减
		if rt.S3CounterTimer > 0 {
			rt.S3CounterTimer = math.Max(0, rt.S3CounterTimer-dt)
		}

		// 4. 第一天赋【实质坍缩】与技能一【停步】
		currentAtk := op.atk()
		dotTrigger := false
		rt.DoTTimer += dt
		interval := cfg.T1Interval
		if interval <= 0 {
			interval = 1.0
		}
		if rt.DoTTimer >= interval {
			rt.DoTTimer -= interval
			dotTrigger = true
		}

		for _, e := range enemies {
			if e == nil || !e.alive() || e.offMap || e.leaked {
				continue
			}
			ecell := [2]int{int(math.RoundToEven(e.position[0])), int(math.RoundToEven(e.position[1]))}
			isGround := !e.spec.IsFlying
			onRealm := isGround && rt.IsOnRealm(ecell)

			// 第一天赋：处于国度地块的地面敌人攻击速度降低
			if onRealm {
				// cfg.T1AttackSpeed 是负数（如 -15.0），削减幅度取绝对值
				e.dminonAspdDown = math.Abs(cfg.T1AttackSpeed)
			} else {
				e.dminonAspdDown = 0
			}

			// 技能一【停步】：每个敌人首次踏上国度时停顿
			if onRealm && rt.SkillActive && cfg.Slot == 1 {
				if slugDur, ok := rt.CheckS1Sluggish(e.index, ecell); ok {
					e.sluggishTimer = math.Max(e.sluggishTimer, slugDur)
					if verdict != nil {
						verdict.Events = append(verdict.Events, Event{
							T: t, Kind: "dminon_sluggish", Who: e.spec.Name,
						})
					}
				}
			}

			// 第一天赋：每秒受到攻击力百分比的法术持续伤害
			if onRealm && dotTrigger {
				rawDmg := currentAtk * cfg.T1AtkScale
				res := e.res()
				if res < 0 {
					res = 0
				}
				if res > 100 {
					res = 100
				}
				actualDmg := rawDmg * (1.0 - res/100.0)
				if actualDmg < 0.05*rawDmg {
					actualDmg = 0.05 * rawDmg
				}
				dealt := e.take(actualDmg, op)
				rt.TotalDoTDamage += dealt

				if !e.alive() && verdict != nil {
					verdict.Kills++
					verdict.Events = append(verdict.Events, Event{
						T: t, Kind: "kill", Who: e.spec.Name + " (实质坍缩)",
					})
				}
			}
		}
	}
}
