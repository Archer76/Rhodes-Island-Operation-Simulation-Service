package main

import (
	"math"
)

// oxiSimTick 驱动塔露拉在主战斗循环 sim.go 中的全局逻辑（按 ops 扫描）
func oxiSimTick(ops []*operator, enemies []*enemy, dt, t float64, spec *Spec, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.spec.CharID != oxiCharID || op.oxiRuntime == nil {
			continue
		}
		rt := op.oxiRuntime

		// 若干员已倒下/撤退，清理所有临时弹道与足迹
		if !op.alive() {
			if len(rt.Waves) > 0 {
				rt.Waves = nil
			}
			if len(rt.FlameCells) > 0 {
				rt.FlameCells = nil
			}
			continue
		}

		// 1. 推进第一天赋未攻击计时与增伤层数积蓄
		rt.TickT1(dt)

		// 2. 检查第二天赋爆发窗口中的敌人足迹生成
		if rt.Config != nil && rt.Config.T2Unlocked {
			for _, e := range enemies {
				if e == nil || !e.alive() || e.offMap || e.leaked {
					continue
				}
				if until, ok := rt.BurstEnemyWindow[e.index]; ok && t <= until {
					cell := [2]int{int(math.RoundToEven(e.position[0])), int(math.RoundToEven(e.position[1]))}
					rt.TryAddFlameField(cell, t)
				}
			}
			// 驱动第二天赋足迹伤害跳动与过期移除
			rt.TickFlameFields(t, dt, op, enemies, verdict)
		}

		// 3. 推进技能二受击时钟与 Buff 时钟
		if rt.Config != nil && rt.Config.Slot == 2 {
			rt.TickS2(t, dt)
		}

		// 4. 推进技能三引导、火浪推移与碰撞
		if rt.Config != nil && rt.Config.Slot == 3 {
			rt.TickS3(t, dt, op, enemies, verdict)
		}
	}
}
