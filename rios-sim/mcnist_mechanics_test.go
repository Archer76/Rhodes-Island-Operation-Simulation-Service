package main

import (
	"math"
	"testing"
)

// TestMcnistSourceSpecCoverage 验证不同精英、潜能、技能等级下的数据驱动规格解析与黑板键消费
func TestMcnistSourceSpecCoverage(t *testing.T) {
	// 1. 精0 1级 潜能1 技1 1级
	stE0 := &OperatorStats{
		CharID:    mcnistCharID,
		Elite:     0,
		Level:     1,
		Potential: 1,
	}
	specE0, err := buildMcnistSourceSpec(stE0, 1, 1)
	if err != nil {
		t.Fatalf("buildMcnistSourceSpec E0 failed: %v", err)
	}
	cfgE0, err := decodeMcnistRuntimeConfig(specE0)
	if err != nil {
		t.Fatalf("decodeMcnistRuntimeConfig E0 failed: %v", err)
	}
	if cfgE0.S1Times != 5 || math.Abs(cfgE0.S1AtkScale-0.8) > 1e-6 || cfgE0.S1TriggerTime != 3 {
		t.Errorf("E0 S1 config mismatch: %+v", cfgE0)
	}
	if cfgE0.TokenDuration != 0 {
		t.Errorf("E0 should have no token duration: got %f", cfgE0.TokenDuration)
	}

	// 2. 精1 80级 潜能1 技2 7级
	stE1 := &OperatorStats{
		CharID:    mcnistCharID,
		Elite:     1,
		Level:     80,
		Potential: 1,
	}
	specE1, err := buildMcnistSourceSpec(stE1, 2, 7)
	if err != nil {
		t.Fatalf("buildMcnistSourceSpec E1 failed: %v", err)
	}
	cfgE1, err := decodeMcnistRuntimeConfig(specE1)
	if err != nil {
		t.Fatalf("decodeMcnistRuntimeConfig E1 failed: %v", err)
	}
	if cfgE1.TokenDuration != 20.0 {
		t.Errorf("E1 TokenDuration expected 20.0, got %f", cfgE1.TokenDuration)
	}
	if math.Abs(cfgE1.S2Atk-1.2) > 1e-6 || cfgE1.S2TriggerTime != 7 || math.Abs(cfgE1.S2AtkScale-2.0) > 1e-6 {
		t.Errorf("E1 S2 L7 config mismatch: %+v", cfgE1)
	}

	// 3. 精2 90级 潜能5 技3 专三，带模组 SO-α 3级
	mod := mcnistModule2ID
	stE2Pot5 := &OperatorStats{
		CharID:      mcnistCharID,
		Elite:       2,
		Level:       90,
		Potential:   5,
		Module:      mod,
		ModuleLevel: 3,
	}
	specE2Pot5, err := buildMcnistSourceSpec(stE2Pot5, 3, 10)
	if err != nil {
		t.Fatalf("buildMcnistSourceSpec E2Pot5 failed: %v", err)
	}
	cfgE2Pot5, err := decodeMcnistRuntimeConfig(specE2Pot5)
	if err != nil {
		t.Fatalf("decodeMcnistRuntimeConfig E2Pot5 failed: %v", err)
	}
	if cfgE2Pot5.TokenDuration != 30.0 {
		t.Errorf("E2 TokenDuration expected 30.0, got %f", cfgE2Pot5.TokenDuration)
	}
	if math.Abs(cfgE2Pot5.LifeEquationHPRatio-0.4) > 1e-6 {
		t.Errorf("E2 Pot5 LifeEquationHPRatio expected 0.4, got %f", cfgE2Pot5.LifeEquationHPRatio)
	}
	if math.Abs(cfgE2Pot5.S3Atk-2.8) > 1e-6 || math.Abs(cfgE2Pot5.S3CrossAtkScale-2.6) > 1e-6 || math.Abs(cfgE2Pot5.S3DashAtkScale-3.0) > 1e-6 {
		t.Errorf("E2 S3 M3 config mismatch: %+v", cfgE2Pot5)
	}
	if math.Abs(cfgE2Pot5.ModuleAtk-100.0) > 1e-6 || math.Abs(cfgE2Pot5.ModuleDef-80.0) > 1e-6 {
		t.Errorf("Module Lv3 stats mismatch: Atk=%f, Def=%f", cfgE2Pot5.ModuleAtk, cfgE2Pot5.ModuleDef)
	}
}

// TestMcnistTalent1StructuralPrinciple 验证第一天赋【结构性原理】召唤物生命周期与独立属性
func TestMcnistTalent1StructuralPrinciple(t *testing.T) {
	st := &OperatorStats{
		CharID:    mcnistCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}
	spec, _ := buildMcnistSourceSpec(st, 1, 10)
	cfg, _ := decodeMcnistRuntimeConfig(spec)
	rt := newMcnistRuntime(cfg)

	owner := &operator{
		spec: OperatorSpec{
			CharID:   mcnistCharID,
			Name:     "机械师",
			MaxHP:    3631.0,
			ATK:      513.0,
			DEF:      705.0,
			BlockCnt: 3,
		},
		hp:   3631.0,
		cell: [2]float64{2, 2},
	}
	rt.InitOnDeploy(owner)

	// 部署召唤物结构性原理 (token_10069_mcnist_mcgraf)
	token := &operator{
		spec: OperatorSpec{
			CharID:   mcnistTokenID,
			Name:     "结构性原理",
			MaxHP:    3500.0,
			ATK:      600.0,
			DEF:      550.0,
			BlockCnt: 3,
			Range:    [][2]int{{0, 0}},
		},
		hp:   3500.0,
		cell: [2]float64{3, 2},
	}
	rt.DeployToken(token)

	if !rt.TokenDeployed || rt.TokenOp != token {
		t.Fatalf("Token failed to deploy")
	}
	if rt.TokenLifetime != 30.0 {
		t.Errorf("TokenLifetime expected 30.0s, got %f", rt.TokenLifetime)
	}

	// 模拟运行 10 秒
	owner.mcnistRuntime = rt
	ops := []*operator{owner, token}
	mcnistSimTick(ops, nil, 10.0, 10.0, nil, nil)

	if math.Abs(rt.TokenLifetime-20.0) > 1e-6 {
		t.Errorf("TokenLifetime after 10s expected 20.0, got %f", rt.TokenLifetime)
	}
	if !token.alive() {
		t.Errorf("Token should still be alive")
	}

	// 再次推进 21 秒，使生命周期耗尽
	mcnistSimTick(ops, nil, 21.0, 31.0, nil, nil)
	if token.alive() || rt.TokenDeployed {
		t.Errorf("Token should have expired and retreated")
	}
	if rt.TokenCooldown != 40.0 {
		t.Errorf("TokenCooldown expected 40.0, got %f", rt.TokenCooldown)
	}
}

// TestMcnistTalent2LifeEquationOverkillProtection 验证第二天赋【生命方程】屏障与超额防护机制
func TestMcnistTalent2LifeEquationOverkillProtection(t *testing.T) {
	st := &OperatorStats{
		CharID:    mcnistCharID,
		Elite:     2,
		Level:     90,
		Potential: 1, // 30% 屏障
	}
	spec, _ := buildMcnistSourceSpec(st, 1, 10)
	cfg, _ := decodeMcnistRuntimeConfig(spec)
	rt := newMcnistRuntime(cfg)

	owner := &operator{
		spec: OperatorSpec{
			CharID:   mcnistCharID,
			Name:     "机械师",
			MaxHP:    3000.0,
			ATK:      500.0,
			DEF:      600.0,
			BlockCnt: 3,
		},
		hp:   3000.0,
		cell: [2]float64{2, 2},
	}
	rt.InitOnDeploy(owner)

	// 部署时获得 30% 屏障 = 900.0
	expectedBarrier := 3000.0 * 0.3
	if math.Abs(rt.OwnerBarrier.Barrier-expectedBarrier) > 1e-6 {
		t.Fatalf("OwnerBarrier expected %f, got %f", expectedBarrier, rt.OwnerBarrier.Barrier)
	}
	if !rt.OwnerBarrier.OverkillProtect {
		t.Fatalf("OverkillProtect should be true")
	}

	// 1. 吸收一次小于屏障值的伤害：400 伤害
	rem1 := rt.AbsorbDamageWithBarrier(owner, 400.0)
	if rem1 != 0.0 {
		t.Errorf("Expected 0 remaining damage, got %f", rem1)
	}
	if math.Abs(rt.OwnerBarrier.Barrier-500.0) > 1e-6 {
		t.Errorf("Remaining barrier expected 500.0, got %f", rt.OwnerBarrier.Barrier)
	}

	// 2. 超额伤害：剩余屏障 500，受到 5000 致命攻击！
	// 超额防护机制：吸收 500 屏障，屏障归零，剩余 4500 超额伤害完全抵挡，返回 0 剩余伤害！
	rem2 := rt.AbsorbDamageWithBarrier(owner, 5000.0)
	if rem2 != 0.0 {
		t.Errorf("Overkill protection failed: expected 0 remaining damage, got %f", rem2)
	}
	if rt.OwnerBarrier.Barrier != 0.0 {
		t.Errorf("Barrier should be 0 after overkill hit, got %f", rt.OwnerBarrier.Barrier)
	}
	if rt.TotalOverkillBlocks != 1 {
		t.Errorf("TotalOverkillBlocks expected 1, got %d", rt.TotalOverkillBlocks)
	}

	// 3. 屏障已破裂，后续攻击正常造成全额伤害
	rem3 := rt.AbsorbDamageWithBarrier(owner, 200.0)
	if rem3 != 200.0 {
		t.Errorf("Without barrier damage should pass through, got %f", rem3)
	}
}

// TestMcnistSkill1ClusterAnalysis 验证技能一【聚类分析】五连击与弹药耗尽结束机制
func TestMcnistSkill1ClusterAnalysis(t *testing.T) {
	st := &OperatorStats{
		CharID:    mcnistCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}
	spec, _ := buildMcnistSourceSpec(st, 1, 10)
	cfg, _ := decodeMcnistRuntimeConfig(spec)
	rt := newMcnistRuntime(cfg)

	owner := &operator{
		spec: OperatorSpec{
			CharID:   mcnistCharID,
			Name:     "机械师",
			MaxHP:    3631.0,
			ATK:      513.0,
			BlockCnt: 3,
			Range:    [][2]int{{0, 0}, {1, 0}, {2, 0}},
		},
		hp:            3631.0,
		cell:          [2]float64{1, 1},
		mcnistRuntime: rt,
		skillActive:   true,
	}
	rt.InitOnDeploy(owner)

	// 激活 S1
	mcnistSimTick([]*operator{owner}, nil, 0.1, 0.1, nil, nil)
	if rt.AmmoRemaining != 3 {
		t.Fatalf("AmmoRemaining expected 3, got %d", rt.AmmoRemaining)
	}

	// hitCount 应为 5
	if owner.hitCount() != 5 {
		t.Errorf("S1 hitCount expected 5, got %d", owner.hitCount())
	}
	// atkScale 应为 1.55
	if math.Abs(owner.atkScale()-1.55) > 1e-6 {
		t.Errorf("S1 atkScale expected 1.55, got %f", owner.atkScale())
	}
	// 目标数应为 99（群体攻击）
	if owner.maxTarget() != 99 {
		t.Errorf("S1 maxTarget expected 99, got %d", owner.maxTarget())
	}
}

// TestMcnistSkill2CoordinatedDefense 验证技能二【协防术式】获得屏障、爆破反击法伤、战栗与重装填
func TestMcnistSkill2CoordinatedDefense(t *testing.T) {
	st := &OperatorStats{
		CharID:    mcnistCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}
	spec, _ := buildMcnistSourceSpec(st, 2, 10)
	cfg, _ := decodeMcnistRuntimeConfig(spec)
	rt := newMcnistRuntime(cfg)

	owner := &operator{
		spec: OperatorSpec{
			CharID:   mcnistCharID,
			Name:     "机械师",
			MaxHP:    3000.0,
			ATK:      1000.0,
			BlockCnt: 3,
		},
		hp:            3000.0,
		cell:          [2]float64{2, 2},
		mcnistRuntime: rt,
		skillActive:   true,
	}
	rt.InitOnDeploy(owner)

	// 敌方单位在周围 1 格处
	foe := &enemy{
		index:    1,
		hp:       5000.0,
		position: [2]float64{2.5, 2.0},
		spec: SpawnSpec{
			Name: "测试敌兵",
			HP:   5000.0,
			ATK:  500.0,
			DEF:  0.0,
		},
	}
	enemies := []*enemy{foe}

	curTime := 0.1
	simCtx := &simCtx{
		objs:    &[]*operator{owner},
		enemies: &enemies,
		time:    &curTime,
	}
	owner.sim = simCtx
	foe.sim = simCtx

	// 开启技能
	mcnistSimTick([]*operator{owner}, enemies, 0.1, 0.1, nil, nil)

	if rt.AmmoRemaining != 8 {
		t.Fatalf("S2 AmmoRemaining expected 8, got %d", rt.AmmoRemaining)
	}
	// 攻击力 +150% = 2500
	if math.Abs(owner.atk()-2500.0) > 1e-6 {
		t.Errorf("S2 ATK expected 2500, got %f", owner.atk())
	}

	// 击碎屏障
	owner.take(5000.0)
	// 触发爆破
	rt.CheckAndHandleS2BarrierBurst(true, owner, enemies)

	// 敌方应受到 200% 法术反击伤害 = 2500 * 2.0 = 5000
	if foe.hp > 0 {
		t.Errorf("Enemy should have taken 5000 damage and died, remaining: %f", foe.hp)
	}
	// 检查战栗状态施加
	if !rt.EnemyIsTrembling(foe.index) {
		t.Errorf("Enemy should have tremble debuff applied")
	}
	// 检查消耗 1 发弹药重新获得屏障
	if rt.AmmoRemaining != 7 {
		t.Errorf("AmmoRemaining expected 7 after burst, got %d", rt.AmmoRemaining)
	}
	expectedReloadBarrier := 3000.0 * 0.1
	if math.Abs(rt.OwnerBarrier.Barrier-expectedReloadBarrier) > 1e-6 {
		t.Errorf("Reloaded barrier expected %f, got %f", expectedReloadBarrier, rt.OwnerBarrier.Barrier)
	}
}

// TestMcnistSkill3EngineeringCross 验证技能三【工程学十字星】攻击范围、结构性原理冲锋与虚弱光环
func TestMcnistSkill3EngineeringCross(t *testing.T) {
	st := &OperatorStats{
		CharID:    mcnistCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}
	spec, _ := buildMcnistSourceSpec(st, 3, 10)
	cfg, _ := decodeMcnistRuntimeConfig(spec)
	rt := newMcnistRuntime(cfg)

	owner := &operator{
		spec: OperatorSpec{
			CharID:   mcnistCharID,
			Name:     "机械师",
			MaxHP:    3631.0,
			ATK:      1000.0,
			BlockCnt: 3,
			Range:    [][2]int{{0, 0}, {1, 0}, {2, 0}},
		},
		hp:            3631.0,
		cell:          [2]float64{2, 2},
		mcnistRuntime: rt,
		skillActive:   true,
	}
	rt.InitOnDeploy(owner)

	token := &operator{
		spec: OperatorSpec{
			CharID:   mcnistTokenID,
			Name:     "结构性原理",
			MaxHP:    3500.0,
			ATK:      600.0,
			BlockCnt: 3,
			Range:    [][2]int{{0, 0}, {1, 0}}, // 朝右
		},
		hp:   3500.0,
		cell: [2]float64{3, 2},
	}
	rt.DeployToken(token)

	foe := &enemy{
		index:    1,
		hp:       5000.0,
		position: [2]float64{6.0, 2.0},
		spec: SpawnSpec{
			Name: "前方敌兵",
			HP:   5000.0,
			ATK:  1000.0,
			DEF:  0.0,
		},
	}

	enemies := []*enemy{foe}

	// 触发 S3 冲锋
	mcnistSimTick([]*operator{owner, token}, enemies, 0.1, 0.1, nil, nil)

	// 冲锋停在 (6, 2)
	if token.cell[0] != 6.0 || token.cell[1] != 2.0 {
		t.Errorf("Token dash target expected (6, 2), got (%f, %f)", token.cell[0], token.cell[1])
	}
	// 造成 300% 物理伤害 = 3800 * 3.0 = 11400 (owner.atk() = 1000 * (1 + 2.8) = 3800)
	if foe.hp > 0 {
		t.Errorf("Enemy should have been crushed by dash, hp: %f", foe.hp)
	}

	// 虚弱光环激活，初始 50%
	if !rt.WeakenAuraActive || math.Abs(rt.WeakenAuraRatio-0.50) > 1e-4 {
		t.Errorf("WeakenAura expected active at 0.50, got active=%v ratio=%f", rt.WeakenAuraActive, rt.WeakenAuraRatio)
	}

	// 验证 S3 攻击范围改写为十字 9 格
	rng := owner.targetRange()
	if len(rng) != 9 {
		t.Errorf("S3 cross range cells count expected 9, got %d", len(rng))
	}
}
