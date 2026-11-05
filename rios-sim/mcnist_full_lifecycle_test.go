package main

import (
	"testing"
)

// TestMcnistFullBattleLifecycle 验证机械师全生命周期战斗集成模拟
func TestMcnistFullBattleLifecycle(t *testing.T) {
	st := &OperatorStats{
		CharID:      mcnistCharID,
		Elite:       2,
		Level:       90,
		Potential:   5,
		Module:      mcnistModule2ID,
		ModuleLevel: 3,
	}
	spec, err := buildMcnistSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildMcnistSourceSpec failed: %v", err)
	}

	cfg, err := decodeMcnistRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decodeMcnistRuntimeConfig failed: %v", err)
	}

	rt := newMcnistRuntime(cfg)
	owner := &operator{
		spec: OperatorSpec{
			CharID:       mcnistCharID,
			Name:         "机械师",
			MaxHP:        3631.0,
			ATK:          513.0,
			DEF:          705.0,
			BlockCnt:     3,
			Range:        [][2]int{{0, 0}, {1, 0}, {2, 0}},
			McnistSource: spec,
		},
		hp:            3631.0,
		cell:          [2]float64{2, 2},
		mcnistRuntime: rt,
		skillActive:   true,
	}
	rt.InitOnDeploy(owner)

	// 部署召唤物
	token := &operator{
		spec: OperatorSpec{
			CharID:   mcnistTokenID,
			Name:     "结构性原理",
			MaxHP:    3500.0,
			ATK:      600.0,
			DEF:      550.0,
			BlockCnt: 3,
			Range:    [][2]int{{0, 0}, {1, 0}},
		},
		hp:   3500.0,
		cell: [2]float64{3, 2},
	}
	rt.DeployToken(token)

	// 设置敌人
	e1 := &enemy{
		index:    1,
		hp:       10000.0,
		position: [2]float64{5.0, 2.0},
		spec: SpawnSpec{
			Name: "精英先锋",
			HP:   10000.0,
			ATK:  600.0,
			DEF:  200.0,
		},
	}
	enemies := []*enemy{e1}
	ops := []*operator{owner, token}

	curTime := 0.0
	verdict := &Verdict{}
	simCtx := &simCtx{
		objs:    &ops,
		enemies: &enemies,
		time:    &curTime,
		verdict: verdict,
	}
	owner.sim = simCtx
	token.sim = simCtx
	e1.sim = simCtx

	// 跑 10 秒战斗步长 (dt = 0.1s, 共 100 帧)
	dt := 0.1
	for step := 0; step < 100; step++ {
		curTime += dt
		mcnistSimTick(ops, enemies, dt, curTime, nil, verdict)

		// 模拟敌人攻击召唤物
		if token.alive() && e1.alive() {
			token.take(300.0)
		}
	}

	t.Logf("Mcnist battle lifecycle: DashHits=%d, OverkillBlocks=%d, TokenLifetime=%.2f, WeakenRatio=%.3f",
		rt.TotalDashDamageHits, rt.TotalOverkillBlocks, rt.TokenLifetime, rt.WeakenAuraRatio)

	if !rt.S3DashTriggered {
		t.Errorf("S3 dash should have been triggered during skillActive")
	}
	if !rt.WeakenAuraActive && rt.WeakenAuraRatio <= 0 {
		t.Errorf("Weaken aura should be active during the 10s window")
	}
}
