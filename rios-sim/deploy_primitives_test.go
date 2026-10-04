package main

// These fixtures test deployment primitives, not a real stage battle. They are
// constructed independently of BuildSpecFull: no production mechanism markers
// are removed to bypass refusal. Production wiring remains covered separately
// by TestDeployLimitWiredFromStage, TestRedeployTimeInSpec and TestRedeployTimeTruth.
func deploymentPrimitiveSpec(lastAction float64) *Spec {
	maxTime := lastAction + 2
	return &Spec{
		Stage: "synthetic-deployment-primitives", FPS: 30, Life: 1,
		CostInit: 100, CostMax: 100, CostTime: 1, MaxTime: maxTime,
		SpeedScale: 1,
		// A future ordinary enemy keeps the simulation running to MaxTime.
		// An empty spawn list would finish on the first frame. No enemy enters
		// during the test, so combat cannot kill an operator or end the run.
		Spawns: []SpawnSpec{{Time: maxTime + 10, Name: "future primitive",
			HP: 1000, ATK: 0, Interval: 1, LifeCost: 1}},
	}
}

func addDeploymentPrimitive(spec *Spec, charID, name string, cell [2]int, at, rt float64) {
	i := len(spec.Operators)
	spec.Operators = append(spec.Operators, OperatorSpec{
		CharID: charID, Name: name, Cell: cell, MaxHP: 1000,
		ATK: 0, AttackInterval: 1, BlockCnt: 0, DeployCost: 1, RedeployTime: rt,
	})
	spec.Deploys = append(spec.Deploys, DeploySpec{Index: i, CharID: charID, Time: at, Cost: 1})
}

// A and A2 share identity but not Cell; B is a distinct auxiliary identity.
// Names match the original event/rejection assertions, not real operator kits.
func redeployPrimitiveSpec(secondAt, retreatAt float64) *Spec {
	spec := deploymentPrimitiveSpec(secondAt)
	addDeploymentPrimitive(spec, "char_103_angel", "能天使", [2]int{3, 5}, 0, 70)
	addDeploymentPrimitive(spec, "char_311_mudrok", "泥岩", [2]int{2, 3}, 0, 70)
	addDeploymentPrimitive(spec, "char_103_angel", "能天使", [2]int{3, 4}, secondAt, 70)
	if retreatAt >= 0 {
		spec.Retreats = []RetreatSpec{{Operator: "能天使", Time: retreatAt}}
	}
	return spec
}

func gravelPrimitiveSpec(retreatAt, secondAt, rt float64) *Spec {
	spec := deploymentPrimitiveSpec(secondAt)
	addDeploymentPrimitive(spec, "char_103_angel", "能天使", [2]int{3, 5}, 2, 70)
	addDeploymentPrimitive(spec, "char_311_mudrok", "泥岩", [2]int{2, 3}, 24, 70)
	addDeploymentPrimitive(spec, "char_237_gravel", "砾", [2]int{2, 4}, 30, rt)
	addDeploymentPrimitive(spec, "char_237_gravel", "砾", [2]int{3, 4}, secondAt, rt)
	spec.Retreats = []RetreatSpec{{Operator: "砾", Time: retreatAt}}
	return spec
}
