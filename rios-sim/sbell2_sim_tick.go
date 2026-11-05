package main

// sbell2SimTick 驱动圣聆初雪在主战斗循环 sim.go 中的全局逻辑（按 ops 扫描）
func sbell2SimTick(ops []*operator, enemies []*enemy, dt, t float64, spec *Spec, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.spec.CharID != sbell2CharID || op.sbell2Runtime == nil {
			continue
		}
		rt := op.sbell2Runtime
		cfg := rt.Config

		if !op.alive() {
			continue
		}

		// 1. 部署瞬间（Y 模组 Lv3 first_snow）
		if !rt.DeployedInitDone {
			rt.DeployedInitDone = true
			if cfg.T1FirstSnow {
				// 产生第一层积雪
				if verdict != nil {
					verdict.Events = append(verdict.Events, Event{
						T:    t,
						Kind: "sbell2_first_snow",
						Who:  op.spec.Name,
					})
				}
			}
		}

		// 2. 技能三持续时间与诱导吸引推进
		if op.skillActive && cfg.Slot == 3 {
			if rt.S3AttractRemaining > 0 {
				rt.S3AttractRemaining -= dt
			}
		}

		// 3. 技能二持续状态与强化判定
		if op.skillActive && cfg.Slot == 2 {
			rt.S2Active = true
		} else {
			rt.S2Active = false
		}
	}
}
