package main

import (
	"math"
	"testing"
)

// TestDminonSourceSpecCoverage 验证不同精英、潜能、技能等级和模组组合下的数据驱动规格解析
func TestDminonSourceSpecCoverage(t *testing.T) {
	stBase := &OperatorStats{
		CharID:    dminonCharID,
		Elite:     0,
		Level:     50,
		Potential: 1,
	}
	specE0, err := buildDminonSourceSpec(stBase, 1, 7)
	if err != nil {
		t.Fatalf("buildDminonSourceSpec E0 failed: %v", err)
	}
	cfgE0, err := decodeDminonRuntimeConfig(specE0)
	if err != nil {
		t.Fatalf("decodeDminonRuntimeConfig E0 failed: %v", err)
	}
	if math.Abs(cfgE0.T1AttackSpeed-(-5.0)) > 1e-6 {
		t.Errorf("E0 T1AttackSpeed expected -5.0, got %f", cfgE0.T1AttackSpeed)
	}
	if math.Abs(cfgE0.T1AtkScale-0.10) > 1e-6 {
		t.Errorf("E0 T1AtkScale expected 0.10, got %f", cfgE0.T1AtkScale)
	}
	if cfgE0.T2Unlocked {
		t.Errorf("E0 should not unlock T2")
	}

	// 精英 1 阶段
	stE1 := &OperatorStats{
		CharID:    dminonCharID,
		Elite:     1,
		Level:     80,
		Potential: 1,
	}
	specE1, err := buildDminonSourceSpec(stE1, 2, 7)
	if err != nil {
		t.Fatalf("buildDminonSourceSpec E1 failed: %v", err)
	}
	cfgE1, err := decodeDminonRuntimeConfig(specE1)
	if err != nil {
		t.Fatalf("decodeDminonRuntimeConfig E1 failed: %v", err)
	}
	if math.Abs(cfgE1.T1AttackSpeed-(-10.0)) > 1e-6 {
		t.Errorf("E1 T1AttackSpeed expected -10.0, got %f", cfgE1.T1AttackSpeed)
	}
	if math.Abs(cfgE1.T1AtkScale-0.10) > 1e-6 {
		t.Errorf("E1 T1AtkScale expected 0.10, got %f", cfgE1.T1AtkScale)
	}

	// 精英 2 阶段，潜能 1 (第二天赋 500%)
	stE2Pot1 := &OperatorStats{
		CharID:    dminonCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}
	specE2Pot1, err := buildDminonSourceSpec(stE2Pot1, 3, 10)
	if err != nil {
		t.Fatalf("buildDminonSourceSpec E2Pot1 failed: %v", err)
	}
	cfgE2Pot1, err := decodeDminonRuntimeConfig(specE2Pot1)
	if err != nil {
		t.Fatalf("decodeDminonRuntimeConfig E2Pot1 failed: %v", err)
	}
	if !cfgE2Pot1.T2Unlocked {
		t.Errorf("E2 should unlock T2")
	}
	if math.Abs(cfgE2Pot1.T1AttackSpeed-(-15.0)) > 1e-6 {
		t.Errorf("E2 T1AttackSpeed expected -15.0, got %f", cfgE2Pot1.T1AttackSpeed)
	}
	if math.Abs(cfgE2Pot1.T1AtkScale-0.13) > 1e-6 {
		t.Errorf("E2 T1AtkScale expected 0.13, got %f", cfgE2Pot1.T1AtkScale)
	}
	if math.Abs(cfgE2Pot1.T2AtkScale-5.0) > 1e-6 {
		t.Errorf("E2 Pot1 T2AtkScale expected 5.0, got %f", cfgE2Pot1.T2AtkScale)
	}
	if math.Abs(cfgE2Pot1.T2Stun-5.0) > 1e-6 {
		t.Errorf("E2 Pot1 T2Stun expected 5.0, got %f", cfgE2Pot1.T2Stun)
	}
	// 技能三 专三数值
	if math.Abs(cfgE2Pot1.S3Atk-1.0) > 1e-6 {
		t.Errorf("S3 Atk expected 1.0, got %f", cfgE2Pot1.S3Atk)
	}
	if math.Abs(cfgE2Pot1.S3AttackSpeed-40.0) > 1e-6 {
		t.Errorf("S3 AttackSpeed expected 40.0, got %f", cfgE2Pot1.S3AttackSpeed)
	}
	if math.Abs(cfgE2Pot1.S3AoeAtkScale-0.8) > 1e-6 {
		t.Errorf("S3 AoeAtkScale expected 0.8, got %f", cfgE2Pot1.S3AoeAtkScale)
	}
	if math.Abs(cfgE2Pot1.S3CounterCD-0.5) > 1e-6 {
		t.Errorf("S3 CounterCD expected 0.5, got %f", cfgE2Pot1.S3CounterCD)
	}

	// 精英 2 满潜能 (潜能 5+ 第二天赋提升至 600%) + X 模组 3 级
	stE2Max := &OperatorStats{
		CharID:      dminonCharID,
		Elite:       2,
		Level:       90,
		Potential:   6,
		Module:      dminonXModuleID,
		ModuleLevel: 3,
	}
	specE2X, err := buildDminonSourceSpec(stE2Max, 2, 10)
	if err != nil {
		t.Fatalf("buildDminonSourceSpec E2X failed: %v", err)
	}
	cfgE2X, err := decodeDminonRuntimeConfig(specE2X)
	if err != nil {
		t.Fatalf("decodeDminonRuntimeConfig E2X failed: %v", err)
	}
	if math.Abs(cfgE2X.T2AtkScale-6.0) > 1e-6 {
		t.Errorf("E2 Pot6 T2AtkScale expected 6.0, got %f", cfgE2X.T2AtkScale)
	}
	// X 模组 3 级：T1 升级为 -20 攻速, 0.20 倍率
	if math.Abs(cfgE2X.T1AttackSpeed-(-20.0)) > 1e-6 {
		t.Errorf("E2X3 T1AttackSpeed expected -20.0, got %f", cfgE2X.T1AttackSpeed)
	}
	if math.Abs(cfgE2X.T1AtkScale-0.20) > 1e-6 {
		t.Errorf("E2X3 T1AtkScale expected 0.20, got %f", cfgE2X.T1AtkScale)
	}
	// 模组特性移速 -0.2
	if math.Abs(cfgE2X.TraitMoveSpeed-(-0.2)) > 1e-6 {
		t.Errorf("E2X3 TraitMoveSpeed expected -0.2, got %f", cfgE2X.TraitMoveSpeed)
	}
	// 技能二 专三数值
	if math.Abs(cfgE2X.S2Atk-0.75) > 1e-6 {
		t.Errorf("S2 Atk expected 0.75, got %f", cfgE2X.S2Atk)
	}
	if math.Abs(cfgE2X.S2AttackSpeed-30.0) > 1e-6 {
		t.Errorf("S2 AttackSpeed expected 30.0, got %f", cfgE2X.S2AttackSpeed)
	}
}

// TestDminonStalkerTrait 验证伏击客特性（范围内全攻、50% 双闪避、低嘲讽）
func TestDminonStalkerTrait(t *testing.T) {
	op := &operator{
		hp: 1590,
		spec: OperatorSpec{
			CharID:         dminonCharID,
			Name:           "国度",
			MaxHP:          1590,
			ATK:            927,
			BlockCnt:       0,
			Range:          [][2]int{{0, 0}, {1, 0}, {2, 0}},
			DamageType:     "PHYSICAL",
			AttackInterval: 3.5,
		},
	}

	// 1. 阻挡数为 0
	if op.spec.BlockCnt != 0 {
		t.Fatalf("Stalker BlockCnt expected 0, got %d", op.spec.BlockCnt)
	}

	// 2. 双闪避 50%
	if physDodge := op.dodgeVs("PHYSICAL"); physDodge != 0.50 {
		t.Errorf("Stalker Physical Dodge expected 0.50, got %f", physDodge)
	}
	if magicDodge := op.dodgeVs("MAGIC"); magicDodge != 0.50 {
		t.Errorf("Stalker Magic Dodge expected 0.50, got %f", magicDodge)
	}

	// 3. 目标数上限为范围内所有（99）
	if maxT := op.maxTarget(); maxT < 99 {
		t.Errorf("Stalker maxTarget expected >= 99, got %d", maxT)
	}
}

// TestDminonT1SubstantialCollapse 验证第一天赋【实质坍缩】（国度地块、攻速降低、DoT法术伤害）
func TestDminonT1SubstantialCollapse(t *testing.T) {
	cfg := &DminonRuntimeConfig{
		T1AttackSpeed: -15.0,
		T1AtkScale:    0.13,
		T1Interval:    1.0,
		Slot:          1,
	}
	rt := newDminonRuntime(cfg)
	baseCells := [][2]int{{1, 1}, {1, 2}, {2, 1}, {2, 2}}
	rt.InitRealm(baseCells, nil)

	// 检查地块判断
	if !rt.IsOnRealm([2]int{1, 1}) {
		t.Errorf("Cell {1, 1} should be in realm")
	}
	if rt.IsOnRealm([2]int{0, 0}) {
		t.Errorf("Cell {0, 0} should not be in realm")
	}

	// 模拟敌人进入与 DoT
	op := &operator{
		hp: 1590,
		spec: OperatorSpec{
			CharID: dminonCharID,
			Name:   "国度",
			ATK:    1000.0,
		},
		dminonRuntime: rt,
	}
	eInside := &enemy{
		hp:       5000,
		position: [2]float64{1.0, 1.0},
		spec: SpawnSpec{
			Name:     "GroundEnemy1",
			Interval: 2.0,
			RES:      20.0,
		},
	}
	eOutside := &enemy{
		hp:       5000,
		position: [2]float64{5.0, 5.0},
		spec: SpawnSpec{
			Name:     "GroundEnemy2",
			Interval: 2.0,
			RES:      20.0,
		},
	}
	eFlying := &enemy{
		hp:       5000,
		position: [2]float64{1.0, 1.0},
		spec: SpawnSpec{
			Name:     "FlyingEnemy",
			Interval: 2.0,
			IsFlying: true,
		},
	}

	enemies := []*enemy{eInside, eOutside, eFlying}
	ops := []*operator{op}

	// 执行 1.0 秒模拟（触发一次 DoT）
	dminonSimTick(ops, enemies, 1.0, 1.0, nil, nil)

	// eInside 应受到攻速降低：15
	if eInside.dminonAspdDown != 15.0 {
		t.Errorf("eInside dminonAspdDown expected 15.0, got %f", eInside.dminonAspdDown)
	}
	// 攻速降低后攻击间隔拉长：2.0 * 100 / (100 - 15) = 2.0 * 100 / 85 ≈ 2.3529s
	expectedInterval := 2.0 * 100.0 / 85.0
	if math.Abs(eInside.interval()-expectedInterval) > 1e-4 {
		t.Errorf("eInside interval expected %f, got %f", expectedInterval, eInside.interval())
	}

	// eOutside 不在国度内，不应受到减攻速
	if eOutside.dminonAspdDown != 0 {
		t.Errorf("eOutside dminonAspdDown expected 0, got %f", eOutside.dminonAspdDown)
	}

	// DoT 伤害：1000 * 0.13 * (1 - 0.20) = 104
	expectedDmg := 1000.0 * 0.13 * 0.80
	if math.Abs((5000.0-eInside.hp)-expectedDmg) > 1e-4 {
		t.Errorf("eInside took damage expected %f, got %f", expectedDmg, 5000.0-eInside.hp)
	}
	// eOutside 与 eFlying 不应受到伤害
	if eOutside.hp != 5000.0 {
		t.Errorf("eOutside should not take DoT damage, hp=%f", eOutside.hp)
	}
	if eFlying.hp != 5000.0 {
		t.Errorf("eFlying should not take DoT damage, hp=%f", eFlying.hp)
	}
}

// TestDminonT2SelfAsRealm 验证第二天赋【此身为界】（离场引爆、法术伤害、眩晕与国度清空）
func TestDminonT2SelfAsRealm(t *testing.T) {
	cfg := &DminonRuntimeConfig{
		T2Unlocked: true,
		T2AtkScale: 5.0,
		T2Stun:     5.0,
	}
	rt := newDminonRuntime(cfg)
	baseCells := [][2]int{{2, 2}}
	rt.InitRealm(baseCells, nil)

	op := &operator{
		hp: 1590,
		spec: OperatorSpec{
			CharID: dminonCharID,
			Name:   "国度",
			ATK:    1000.0,
		},
		dminonRuntime: rt,
	}
	e1 := &enemy{
		hp:       10000,
		position: [2]float64{2.0, 2.0},
		spec: SpawnSpec{
			Name: "Victim1",
			RES:  10.0,
		},
	}
	enemies := []*enemy{e1}
	ops := []*operator{op}

	// 干员撤退离场
	op.retreated = true

	verdict := &Verdict{}
	dminonSimTick(ops, enemies, 0.1, 10.0, nil, verdict)

	// 验证第二天赋引爆伤害：1000 * 5.0 * (1 - 0.1) = 4500
	expectedDmg := 1000.0 * 5.0 * 0.90
	if math.Abs((10000.0-e1.hp)-expectedDmg) > 1e-4 {
		t.Errorf("e1 took explosion damage expected %f, got %f", expectedDmg, 10000.0-e1.hp)
	}
	// 验证眩晕 5.0 秒
	if e1.stunTimer != 5.0 {
		t.Errorf("e1 stunTimer expected 5.0, got %f", e1.stunTimer)
	}
	// 验证场上所有国度地块已清空
	if len(rt.RealmTiles) != 0 {
		t.Errorf("RealmTiles should be cleared after retreat, remaining: %d", len(rt.RealmTiles))
	}
	if rt.IsOnRealm([2]int{2, 2}) {
		t.Errorf("Cell {2, 2} should no longer be realm after retreat")
	}
}

// TestDminonS1StepStop 验证技能一【停步】（攻速加成与首次踏上停顿）
func TestDminonS1StepStop(t *testing.T) {
	cfg := &DminonRuntimeConfig{
		Slot:          1,
		S1AttackSpeed: 80.0,
		S1Sluggish:    5.0,
	}
	rt := newDminonRuntime(cfg)
	rt.InitRealm([][2]int{{3, 3}}, nil)

	op := &operator{
		hp: 1590,
		spec: OperatorSpec{
			CharID:         dminonCharID,
			Name:           "国度",
			ATK:            1000.0,
			AttackInterval: 3.5,
		},
		dminonRuntime: rt,
		skillActive:   true,
	}
	e := &enemy{
		index:    101,
		hp:       5000,
		position: [2]float64{3.0, 3.0},
		spec: SpawnSpec{
			Name: "WalkingEnemy",
		},
	}

	ops := []*operator{op}
	enemies := []*enemy{e}

	// 第一次进入国度，应触发停顿
	dminonSimTick(ops, enemies, 0.1, 1.0, nil, nil)
	if e.sluggishTimer != 5.0 {
		t.Errorf("Enemy sluggishTimer expected 5.0, got %f", e.sluggishTimer)
	}

	// 计时减少
	e.sluggishTimer = 2.0
	// 第二次检查，同一技能期间不再重复触发首次踏入停顿
	dminonSimTick(ops, enemies, 0.1, 2.0, nil, nil)
	if e.sluggishTimer != 2.0 {
		t.Errorf("Enemy sluggishTimer should not be re-applied in same skill, got %f", e.sluggishTimer)
	}

	// 验证攻速提升加成（+80 攻速）
	interval := op.interval()
	expectedInterval := 3.5 * 100.0 / (100.0 + 80.0)
	if math.Abs(interval-expectedInterval) > 1e-4 {
		t.Errorf("op S1 interval expected %f, got %f", expectedInterval, interval)
	}
}

// TestDminonS2Slaughter 验证技能二【受戮】（范围扩大、必中无法闪避、二次开技永续+攻速）
func TestDminonS2Slaughter(t *testing.T) {
	cfg := &DminonRuntimeConfig{
		Slot:          2,
		S2Atk:         0.75,
		S2AttackSpeed: 30.0,
		Duration:      20.0,
	}
	rt := newDminonRuntime(cfg)
	baseCells := [][2]int{{0, 0}}
	skillCells := [][2]int{{0, 0}, {0, 1}, {0, 2}, {0, 3}}
	rt.InitRealm(baseCells, skillCells)

	op := &operator{
		hp: 1590,
		spec: OperatorSpec{
			CharID:         dminonCharID,
			Name:           "国度",
			ATK:            1000.0,
			AttackInterval: 3.5,
		},
		dminonRuntime: rt,
	}

	// 第一次开技
	op.skillActive = true
	rt.OnSkillStart()
	if rt.IsPermanent {
		t.Errorf("First cast should not be permanent")
	}
	if !rt.IsOnRealm([2]int{0, 3}) {
		t.Errorf("Skill range {0, 3} should be in realm during skill")
	}
	// 验证受戮必中机制：国度上敌人无法闪避
	if !rt.IsEnemyUndodgeable([2]int{0, 2}) {
		t.Errorf("Enemy on realm should be undodgeable")
	}
	if rt.IsEnemyUndodgeable([2]int{5, 5}) {
		t.Errorf("Enemy off realm should not be undodgeable")
	}

	// 技能结束
	op.skillActive = false
	rt.OnSkillEnd()
	if rt.IsOnRealm([2]int{0, 3}) {
		t.Errorf("Skill range {0, 3} should not be in realm after skill ends")
	}

	// 第二次开技（永续）
	op.skillActive = true
	rt.OnSkillStart()
	if !rt.IsPermanent {
		t.Errorf("Second cast should become permanent")
	}
	// 验证第二次开技后的攻速加成（+30 攻速）
	interval := op.interval()
	expectedInterval := 3.5 * 100.0 / (100.0 + 30.0)
	if math.Abs(interval-expectedInterval) > 1e-4 {
		t.Errorf("op S2 permanent interval expected %f, got %f", expectedInterval, interval)
	}
}

// TestDminonS3NoMansRealm 验证技能三【无人之国度】（受击反击与地块扩散、技能结束重置）
func TestDminonS3NoMansRealm(t *testing.T) {
	cfg := &DminonRuntimeConfig{
		Slot:          3,
		S3Atk:         1.0,
		S3AttackSpeed: 40.0,
		S3AoeAtkScale: 0.8,
		S3CounterCD:   0.5,
		Duration:      36.0,
	}
	rt := newDminonRuntime(cfg)
	baseCells := [][2]int{{0, 0}}
	skillCells := [][2]int{{0, 0}, {1, 0}}
	rt.InitRealm(baseCells, skillCells)

	op := &operator{
		hp: 1590,
		spec: OperatorSpec{
			CharID:         dminonCharID,
			Name:           "国度",
			ATK:            1000.0,
			AttackInterval: 3.5,
		},
		dminonRuntime: rt,
		skillActive:   true,
	}
	rt.OnSkillStart()

	// 友方在国度地块内受到位于 (2, 2) 的地面敌人攻击
	attackerCell := [2]int{2, 2}
	diffCells, ok := rt.TryS3Counter(attackerCell)
	if !ok {
		t.Fatalf("TryS3Counter should succeed when ready")
	}
	if len(diffCells) != 4 {
		t.Fatalf("Diffused cells should be 4 neighbors, got %d", len(diffCells))
	}
	// 检查扩散出的四格均已加入国度
	for _, c := range diffCells {
		if !rt.IsOnRealm(c) {
			t.Errorf("Diffused cell %v should be in realm", c)
		}
	}

	// 处于 CD 中，再次受击不应触发扩散
	if _, ok := rt.TryS3Counter(attackerCell); ok {
		t.Errorf("TryS3Counter should fail during cooldown")
	}

	// 验证攻速加成（+40 攻速）
	interval := op.interval()
	expectedInterval := 3.5 * 100.0 / (100.0 + 40.0)
	if math.Abs(interval-expectedInterval) > 1e-4 {
		t.Errorf("op S3 interval expected %f, got %f", expectedInterval, interval)
	}

	// 技能结束：重置地块
	rt.OnSkillEnd()
	// 扩散的额外地块应全部消失
	for _, c := range diffCells {
		if rt.IsOnRealm(c) {
			t.Errorf("Diffused cell %v should be cleared on skill end", c)
		}
	}
	// 仅保留常态基础格
	if !rt.IsOnRealm([2]int{0, 0}) {
		t.Errorf("Base cell {0, 0} should still be realm")
	}
}

// TestDminonFullLifecycleIntegration 验证主模拟循环全流程生命周期闭环
func TestDminonFullLifecycleIntegration(t *testing.T) {
	st := &OperatorStats{
		CharID:      dminonCharID,
		Elite:       2,
		Level:       90,
		Potential:   6,
		Module:      dminonXModuleID,
		ModuleLevel: 3,
	}
	spec, err := buildDminonSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildDminonSourceSpec failed: %v", err)
	}
	cfg, err := decodeDminonRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decodeDminonRuntimeConfig failed: %v", err)
	}

	rt := newDminonRuntime(cfg)
	rt.InitRealm([][2]int{{0, 0}, {1, 0}}, [][2]int{{0, 0}, {1, 0}, {2, 0}})

	op := &operator{
		hp: 1590,
		spec: OperatorSpec{
			CharID:         dminonCharID,
			Name:           "国度",
			MaxHP:          1590,
			ATK:            1000.0,
			AttackInterval: 3.5,
			BlockCnt:       0,
			DminonSource:   spec,
		},
		dminonRuntime: rt,
		skillActive:   true,
	}

	e := &enemy{
		index:    1,
		hp:       8000,
		position: [2]float64{1.0, 0.0},
		spec: SpawnSpec{
			Name:     "EliteEnemy",
			ATK:      500,
			Interval: 3.0,
			RES:      15.0,
		},
	}

	ops := []*operator{op}
	enemies := []*enemy{e}
	verdict := &Verdict{}

	// 模拟运行 5 秒（150 帧，dt = 1/30s）
	dt := 1.0 / 30.0
	for frame := 0; frame < 150; frame++ {
		timeSec := float64(frame) * dt
		dminonSimTick(ops, enemies, dt, timeSec, nil, verdict)
	}

	// 验证 DoT 触发与伤害
	if rt.TotalDoTDamage <= 0 {
		t.Errorf("TotalDoTDamage should be > 0, got %f", rt.TotalDoTDamage)
	}

	// 验证撤退离场引爆
	op.retreated = true
	dminonSimTick(ops, enemies, dt, 5.0+dt, nil, verdict)
	if rt.TotalExplodeDamage <= 0 {
		t.Errorf("TotalExplodeDamage should be > 0, got %f", rt.TotalExplodeDamage)
	}
	if e.stunTimer <= 0 {
		t.Errorf("Enemy should be stunned after retreat explosion")
	}
}
