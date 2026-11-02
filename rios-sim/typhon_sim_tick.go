package main

// typhonSimTick 驱动提丰在主战斗循环 sim.go 中的全局逻辑（按 ops 扫描）
func typhonSimTick(ops []*operator, enemies []*enemy, dt, t float64, spec *Spec, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.spec.CharID != typhonCharID || op.typhonRuntime == nil {
			continue
		}
		rt := op.typhonRuntime

		if !op.alive() {
			continue
		}

		// 推进天赋计时器
		rt.Tick(dt)

		// 检查技能状态切换
		if op.skillActive {
			if !rt.LastSkillActive {
				rt.OnSkillActivate(t, op, enemies, verdict)
			}
			// S3 追踪目标存活检查：若目标已死亡/离场，重新在常规范围内搜寻下一个重型目标
			if rt.Config.Slot == 3 {
				locked := rt.GetLockedEnemy(enemies)
				if locked == nil {
					rt.AcquireS3Lock(op, enemies)
				}
			}
		}
		rt.LastSkillActive = op.skillActive
	}
}
