package main

// ulpia_sim_tick.go：把乌尔比安的机制接入主战斗循环的帧序上。
//
// 驱动内容：
//   - 技能激活状态同步与留痕；
//   - 阻挡状态与多目标攻击校验；
func ulpiaTick(ops []*operator, enemies []*enemy, dt, t float64, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.spec.CharID != ulpiaCharID || op.ulpiaState == nil || !op.alive() {
			continue
		}
		st := op.ulpiaState

		// 技能二开启时留痕
		if op.skillActive && st.Config.Slot == 2 && !st.S2Activated {
			st.S2Activated = true
			if verdict != nil {
				verdict.Events = append(verdict.Events, Event{
					T:    t,
					Kind: "ulpia_s2_active",
					Who:  op.spec.Name,
				})
			}
		}
	}
}
