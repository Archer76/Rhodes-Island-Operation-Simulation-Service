package main

import (
	"context"
	"math"
	"testing"
)

// TestTyphonSourceSpecCoverage 验证不同精英、潜能、技能等级和模组组合下的数据驱动规格解析
func TestTyphonSourceSpecCoverage(t *testing.T) {
	// 1. 精英 0 阶段（天赋未解锁）
	stE0 := &OperatorStats{
		CharID:    typhonCharID,
		Elite:     0,
		Level:     50,
		Potential: 1,
	}
	specE0, err := buildTyphonSourceSpec(stE0, 1, 7)
	if err != nil {
		t.Fatalf("buildTyphonSourceSpec E0 failed: %v", err)
	}
	cfgE0, err := decodeTyphonRuntimeConfig(specE0)
	if err != nil {
		t.Fatalf("decodeTyphonRuntimeConfig E0 failed: %v", err)
	}
	if cfgE0.T1Unlocked {
		t.Errorf("E0 should not unlock T1")
	}
	if cfgE0.T2Unlocked {
		t.Errorf("E0 should not unlock T2")
	}

	// 2. 精英 1 阶段（第一天赋解锁）
	stE1 := &OperatorStats{
		CharID:    typhonCharID,
		Elite:     1,
		Level:     60,
		Potential: 1,
	}
	specE1, err := buildTyphonSourceSpec(stE1, 2, 7)
	if err != nil {
		t.Fatalf("buildTyphonSourceSpec E1 failed: %v", err)
	}
	cfgE1, err := decodeTyphonRuntimeConfig(specE1)
	if err != nil {
		t.Fatalf("decodeTyphonRuntimeConfig E1 failed: %v", err)
	}
	if !cfgE1.T1Unlocked {
		t.Errorf("E1 should unlock T1")
	}
	if math.Abs(cfgE1.T1DefPenetrate-0.05) > 1e-6 {
		t.Errorf("E1 T1DefPenetrate expected 0.05, got %f", cfgE1.T1DefPenetrate)
	}
	if math.Abs(cfgE1.T1Duration-3.0) > 1e-6 {
		t.Errorf("E1 T1Duration expected 3.0, got %f", cfgE1.T1Duration)
	}
	if cfgE1.T1MaxStackCnt != 8 {
		t.Errorf("E1 T1MaxStackCnt expected 8, got %d", cfgE1.T1MaxStackCnt)
	}
	if cfgE1.T2Unlocked {
		t.Errorf("E1 should not unlock T2")
	}

	// 3. 精英 2 满潜能 技能 3 专精 3 + X 模组 3 级
	stE2MaxX := &OperatorStats{
		CharID:      typhonCharID,
		Elite:       2,
		Level:       90,
		Potential:   6,
		Module:      typhonXModuleID,
		ModuleLevel: 3,
	}
	specE2X, err := buildTyphonSourceSpec(stE2MaxX, 3, 10)
	if err != nil {
		t.Fatalf("buildTyphonSourceSpec E2X failed: %v", err)
	}
	cfgE2X, err := decodeTyphonRuntimeConfig(specE2X)
	if err != nil {
		t.Fatalf("decodeTyphonRuntimeConfig E2X failed: %v", err)
	}
	if !cfgE2X.T1Unlocked || !cfgE2X.T2Unlocked {
		t.Errorf("E2 should unlock T1 and T2")
	}
	// X3 模组升级天赋一：def_penetrate 0.12, duration 10.0, max_stack_cnt 5
	if math.Abs(cfgE2X.T1DefPenetrate-0.12) > 1e-6 {
		t.Errorf("E2X3 T1DefPenetrate expected 0.12, got %f", cfgE2X.T1DefPenetrate)
	}
	if math.Abs(cfgE2X.T1Duration-10.0) > 1e-6 {
		t.Errorf("E2X3 T1Duration expected 10.0, got %f", cfgE2X.T1Duration)
	}
	if cfgE2X.T1MaxStackCnt != 5 {
		t.Errorf("E2X3 T1MaxStackCnt expected 5, got %d", cfgE2X.T1MaxStackCnt)
	}
	// 潜能 6 (潜能索引 4) 天赋二：atk_scale 1.7, sluggish 3.0
	if math.Abs(cfgE2X.T2AtkScale-1.7) > 1e-6 {
		t.Errorf("E2 Pot6 T2AtkScale expected 1.7, got %f", cfgE2X.T2AtkScale)
	}
	if math.Abs(cfgE2X.T2Sluggish-3.0) > 1e-6 {
		t.Errorf("E2 T2Sluggish expected 3.0, got %f", cfgE2X.T2Sluggish)
	}
	// X 模组特性追加：atk_scale 1.15, min_weight 3.0
	if math.Abs(cfgE2X.ModXAtkScale-1.15) > 1e-6 {
		t.Errorf("ModXAtkScale expected 1.15, got %f", cfgE2X.ModXAtkScale)
	}
	if math.Abs(cfgE2X.ModXMinWeight-3.0) > 1e-6 {
		t.Errorf("ModXMinWeight expected 3.0, got %f", cfgE2X.ModXMinWeight)
	}
	// 技能 3 M3 数值
	if math.Abs(cfgE2X.S3BaseAttackTime-3.1) > 1e-6 {
		t.Errorf("S3 BaseAttackTime expected 3.1, got %f", cfgE2X.S3BaseAttackTime)
	}
	if math.Abs(cfgE2X.S3Stun-0.4) > 1e-6 {
		t.Errorf("S3 Stun expected 0.4, got %f", cfgE2X.S3Stun)
	}
	if math.Abs(cfgE2X.S3AtkScale-1.75) > 1e-6 {
		t.Errorf("S3 AtkScale expected 1.75, got %f", cfgE2X.S3AtkScale)
	}
	if cfgE2X.S3TriggerTime != 10 {
		t.Errorf("S3 TriggerTime expected 10, got %d", cfgE2X.S3TriggerTime)
	}
	if cfgE2X.S3MaxHitNum != 5 {
		t.Errorf("S3 MaxHitNum expected 5, got %d", cfgE2X.S3MaxHitNum)
	}

	// 4. 精英 2 满潜能 + Y 模组 3 级
	stE2MaxY := &OperatorStats{
		CharID:      typhonCharID,
		Elite:       2,
		Level:       90,
		Potential:   6,
		Module:      typhonYModuleID,
		ModuleLevel: 3,
	}
	specE2Y, err := buildTyphonSourceSpec(stE2MaxY, 2, 10)
	if err != nil {
		t.Fatalf("buildTyphonSourceSpec E2Y failed: %v", err)
	}
	cfgE2Y, err := decodeTyphonRuntimeConfig(specE2Y)
	if err != nil {
		t.Fatalf("decodeTyphonRuntimeConfig E2Y failed: %v", err)
	}
	// Y 模组特性追加：damage_scale 0.12, min_dist 1.0, max_dist 4.5
	if math.Abs(cfgE2Y.ModYDamageScale-0.12) > 1e-6 {
		t.Errorf("ModYDamageScale expected 0.12, got %f", cfgE2Y.ModYDamageScale)
	}
	if math.Abs(cfgE2Y.ModYMinDist-1.0) > 1e-6 {
		t.Errorf("ModYMinDist expected 1.0, got %f", cfgE2Y.ModYMinDist)
	}
	if math.Abs(cfgE2Y.ModYMaxDist-4.5) > 1e-6 {
		t.Errorf("ModYMaxDist expected 4.5, got %f", cfgE2Y.ModYMaxDist)
	}
	// Y3 升级第二天赋：Pot6 atk_scale 2.3 (基础2.2+潜能0.1)
	if math.Abs(cfgE2Y.T2AtkScale-2.3) > 1e-6 {
		t.Errorf("E2Y3 Pot6 T2AtkScale expected 2.3, got %f", cfgE2Y.T2AtkScale)
	}
	// 技能 2 数值
	if math.Abs(cfgE2Y.S2Atk-0.5) > 1e-6 {
		t.Errorf("S2 Atk expected 0.5, got %f", cfgE2Y.S2Atk)
	}
	if math.Abs(cfgE2Y.S2AttackProb-0.4) > 1e-6 {
		t.Errorf("S2 AttackProb expected 0.4, got %f", cfgE2Y.S2AttackProb)
	}
	if math.Abs(cfgE2Y.S2AttackStun-1.0) > 1e-6 {
		t.Errorf("S2 AttackStun expected 1.0, got %f", cfgE2Y.S2AttackStun)
	}
	if math.Abs(cfgE2Y.S2FirstDuration-20.0) > 1e-6 {
		t.Errorf("S2 FirstDuration expected 20.0, got %f", cfgE2Y.S2FirstDuration)
	}
}

// TestTyphonTraitPreferHeaviest 验证攻城狙击手特性「优先攻击重量最重的敌人」索敌规则
func TestTyphonTraitPreferHeaviest(t *testing.T) {
	op := &operator{
		cell: [2]float64{0, 0},
		spec: OperatorSpec{
			Name:           "提丰",
			CharID:         typhonCharID,
			Range:          [][2]int{{1, 0}, {2, 0}, {3, 0}, {4, 0}},
			PreferHeaviest: true,
		},
	}

	enemies := []*enemy{
		{index: 1, hp: 1000, position: [2]float64{1, 0}, progress: 10, spec: SpawnSpec{Name: "轻量兵", Weight: 1}},
		{index: 2, hp: 1000, position: [2]float64{2, 0}, progress: 20, spec: SpawnSpec{Name: "中量兵", Weight: 2}},
		{index: 3, hp: 1000, position: [2]float64{3, 0}, progress: 5, spec: SpawnSpec{Name: "超重巨怪", Weight: 4}},
	}

	// 尽管轻量兵和中量兵的 progress 较大，但特性优先攻击重量最重的敌人
	targets := pickTargets(op, enemies, 1, 0)
	if len(targets) != 1 {
		t.Fatalf("pickTargets returned %d targets, expected 1", len(targets))
	}
	if targets[0].index != 3 {
		t.Errorf("Expected target 3 (Weight 4), got target %d (%s, Weight %f)",
			targets[0].index, targets[0].spec.Name, targets[0].weight())
	}
}

// TestTyphonT1StackingAndPenetration 验证第一天赋连续攻击破甲叠层与目标切换/超时重置
func TestTyphonT1StackingAndPenetration(t *testing.T) {
	cfg := &TyphonRuntimeConfig{
		T1Unlocked:     true,
		T1DefPenetrate: 0.10, // 每层 10% 破甲
		T1Duration:     8.0,
		T1MaxStackCnt:  5, // 最大 5 层 (50%)
	}
	rt := newTyphonRuntime(cfg)

	targetA := &enemy{index: 1, spec: SpawnSpec{DEF: 1000}}
	targetB := &enemy{index: 2, spec: SpawnSpec{DEF: 1000}}

	// 初始状态：无破甲
	if def := rt.EffectiveDEF(targetA); math.Abs(def-1000) > 1e-6 {
		t.Fatalf("Initial DEF expected 1000, got %f", def)
	}

	// 第 1 次命中 Target A：叠 1 层，破甲 10%
	rt.RecordHit(targetA)
	if rt.T1Stacks != 1 {
		t.Errorf("Expected 1 stack, got %d", rt.T1Stacks)
	}
	if def := rt.EffectiveDEF(targetA); math.Abs(def-900) > 1e-6 {
		t.Errorf("Stack 1 DEF expected 900, got %f", def)
	}

	// 第 2 次命中 Target A：叠 2 层，破甲 20%
	rt.RecordHit(targetA)
	if rt.T1Stacks != 2 {
		t.Errorf("Expected 2 stacks, got %d", rt.T1Stacks)
	}
	if def := rt.EffectiveDEF(targetA); math.Abs(def-800) > 1e-6 {
		t.Errorf("Stack 2 DEF expected 800, got %f", def)
	}

	// 连续命中达到 5 层封顶
	for i := 0; i < 5; i++ {
		rt.RecordHit(targetA)
	}
	if rt.T1Stacks != 5 {
		t.Errorf("Expected capped 5 stacks, got %d", rt.T1Stacks)
	}
	if def := rt.EffectiveDEF(targetA); math.Abs(def-500) > 1e-6 {
		t.Errorf("Stack 5 DEF expected 500, got %f", def)
	}

	// 切换目标命中 Target B：Target A 加成失去，Target B 重置为 1 层
	rt.RecordHit(targetB)
	if rt.T1TargetIndex != 2 || rt.T1Stacks != 1 {
		t.Errorf("Switch target expected index 2 with 1 stack, got index %d with %d stacks",
			rt.T1TargetIndex, rt.T1Stacks)
	}
	if defA := rt.EffectiveDEF(targetA); math.Abs(defA-1000) > 1e-6 {
		t.Errorf("Target A DEF after switch expected 1000, got %f", defA)
	}
	if defB := rt.EffectiveDEF(targetB); math.Abs(defB-900) > 1e-6 {
		t.Errorf("Target B DEF after switch expected 900, got %f", defB)
	}

	// 超时重置测试
	rt.Tick(8.1)
	if rt.T1Stacks != 0 || rt.T1TargetIndex != -1 {
		t.Errorf("After timeout expected 0 stacks, got %d (target=%d)", rt.T1Stacks, rt.T1TargetIndex)
	}
}

// TestTyphonT2UnblockedDamageAndSluggish 验证第二天赋未阻挡敌人增伤与停顿
func TestTyphonT2UnblockedDamageAndSluggish(t *testing.T) {
	cfg := &TyphonRuntimeConfig{
		T2Unlocked: true,
		T2AtkScale: 1.70,
		T2Sluggish: 3.0,
	}
	rt := newTyphonRuntime(cfg)

	// 未被阻挡的敌人
	unblocked := &enemy{index: 1, blockedBy: nil}
	scale, applySlow := rt.CheckT2(unblocked)
	if math.Abs(scale-1.70) > 1e-6 || !applySlow {
		t.Errorf("Unblocked enemy expected scale 1.70 and applySlow=true, got scale=%f slow=%t",
			scale, applySlow)
	}

	// 被阻挡的敌人
	blocker := &operator{}
	blocked := &enemy{index: 2, blockedBy: blocker}
	scaleB, applySlowB := rt.CheckT2(blocked)
	if math.Abs(scaleB-1.0) > 1e-6 || applySlowB {
		t.Errorf("Blocked enemy expected scale 1.0 and applySlow=false, got scale=%f slow=%t",
			scaleB, applySlowB)
	}
}

// TestTyphonModXAndModY 验证模组 X 与模组 Y 的特性加成
func TestTyphonModXAndModY(t *testing.T) {
	cfg := &TyphonRuntimeConfig{
		ModXAtkScale:    1.15,
		ModXMinWeight:   3.0,
		ModYDamageScale: 0.12,
		ModYMinDist:     1.0,
		ModYMaxDist:     4.5,
	}
	rt := newTyphonRuntime(cfg)

	// 模组 X 验证：重量 >= 3.0
	heavy := &enemy{spec: SpawnSpec{Weight: 3.0}}
	light := &enemy{spec: SpawnSpec{Weight: 2.0}}
	if s := rt.CheckModX(heavy); math.Abs(s-1.15) > 1e-6 {
		t.Errorf("Heavy enemy ModX expected 1.15, got %f", s)
	}
	if s := rt.CheckModX(light); math.Abs(s-1.0) > 1e-6 {
		t.Errorf("Light enemy ModX expected 1.0, got %f", s)
	}

	// 模组 Y 验证：距离远近增伤
	opPos := [2]float64{0, 0}
	closePos := [2]float64{0.5, 0.5} // dist ≈ 0.707 <= 1.0
	if s := rt.CheckModY(opPos, closePos); math.Abs(s-1.0) > 1e-6 {
		t.Errorf("Close enemy ModY expected 1.0, got %f", s)
	}
	farPos := [2]float64{3.0, 4.0} // dist = 5.0 >= 4.5
	if s := rt.CheckModY(opPos, farPos); math.Abs(s-1.12) > 1e-6 {
		t.Errorf("Far enemy ModY expected 1.12, got %f", s)
	}
	midPos := [2]float64{2.75, 0}        // dist = 2.75 (刚好在 1.0 与 4.5 正中间)
	expectedMid := 1.0 + 0.12*(1.75/3.5) // = 1.06
	if s := rt.CheckModY(opPos, midPos); math.Abs(s-expectedMid) > 1e-6 {
		t.Errorf("Mid enemy ModY expected %f, got %f", expectedMid, s)
	}
}

// TestTyphonS2InfiniteAndStunRNGDeterministic 验证二技能两次开启无限持续状态机与确定性概率晕眩抽样
func TestTyphonS2InfiniteAndStunRNGDeterministic(t *testing.T) {
	cfg := &TyphonRuntimeConfig{
		Slot:            2,
		S2Atk:           0.50,
		S2AttackProb:    0.40,
		S2AttackStun:    1.0,
		S2FirstDuration: 20.0,
		RNGSeed:         42,
	}
	rt := newTyphonRuntime(cfg)
	op := &operator{
		spec: OperatorSpec{
			Name:    "提丰",
			CharID:  typhonCharID,
			RNGSeed: 42,
		},
	}

	// 1. 首次开启：持续时间 20s
	rt.OnSkillActivate(10.0, op, nil, nil)
	if rt.S2CastCount != 1 {
		t.Errorf("S2CastCount expected 1, got %d", rt.S2CastCount)
	}
	if math.Abs(op.skillTimer-20.0) > 1e-6 {
		t.Errorf("First S2 duration expected 20.0, got %f", op.skillTimer)
	}

	// 2. 第二次开启：持续时间无限
	rt.OnSkillActivate(50.0, op, nil, nil)
	if rt.S2CastCount != 2 {
		t.Errorf("S2CastCount expected 2, got %d", rt.S2CastCount)
	}
	if !math.IsInf(op.skillTimer, 1) {
		t.Errorf("Second S2 duration expected Inf, got %f", op.skillTimer)
	}

	// 3. 概率晕眩遵循 V-2 规范确定性 RNG
	seedA := uint64(987654321)
	op1 := &operator{spec: OperatorSpec{RNGSeed: seedA}}
	op2 := &operator{spec: OperatorSpec{RNGSeed: seedA}}

	var res1, res2 []bool
	for i := 0; i < 20; i++ {
		res1 = append(res1, op1.probChance(0.4, "test", float64(i), nil))
		res2 = append(res2, op2.probChance(0.4, "test", float64(i), nil))
	}
	for i := range res1 {
		if res1[i] != res2[i] {
			t.Fatalf("Deterministic RNG failed at index %d: res1=%t res2=%t", i, res1[i], res2[i])
		}
	}
}

// TestTyphonS3GlobalLockAndAmmoLifecycle 验证三技能全图锁定追踪与弹药生命周期
func TestTyphonS3GlobalLockAndAmmoLifecycle(t *testing.T) {
	cfg := &TyphonRuntimeConfig{
		Slot:             3,
		S3BaseAttackTime: 3.1,
		S3Stun:           0.4,
		S3AtkScale:       1.75,
		S3TriggerTime:    8,
		S3MaxHitNum:      5,
	}
	rt := newTyphonRuntime(cfg)
	op := &operator{
		cell: [2]float64{0, 0},
		spec: OperatorSpec{
			Name:           "提丰",
			CharID:         typhonCharID,
			Range:          [][2]int{{1, 0}, {2, 0}},
			PreferHeaviest: true,
		},
	}

	enemies := []*enemy{
		{index: 10, hp: 50000, position: [2]float64{1, 0}, spec: SpawnSpec{Name: "TargetBoss", DEF: 500, Weight: 5}},
	}

	// 开启技能 3：全图锁定 TargetBoss
	rt.OnSkillActivate(15.0, op, enemies, nil)
	if rt.S3LockedTargetIndex != 10 {
		t.Fatalf("Expected locked target 10, got %d", rt.S3LockedTargetIndex)
	}
	if op.ammoLeft != 8 {
		t.Fatalf("Expected ammo 8, got %d", op.ammoLeft)
	}

	// 即使目标走出常规攻击范围（移至 x=100, y=100）
	enemies[0].position = [2]float64{100, 100}
	locked := rt.GetLockedEnemy(enemies)
	if locked == nil || locked.index != 10 {
		t.Errorf("Target moved far away should still be tracked! Got %v", locked)
	}

	// 模拟 8 次完整射击后弹药归零
	for i := 0; i < 8; i++ {
		if op.ammoLeft <= 0 {
			t.Fatalf("Ammo depleted prematurely at shot %d", i)
		}
		op.ammoLeft--
	}
	if op.ammoLeft != 0 {
		t.Errorf("Expected ammo 0, got %d", op.ammoLeft)
	}
}

// TestTyphonFullBattleLifecycle 验证提丰在端到端真实战斗循环中的全生命周期（部署、索敌、叠层破甲、未阻挡停顿、技能与击杀）
func TestTyphonFullBattleLifecycle(t *testing.T) {
	st := &OperatorStats{
		CharID:      typhonCharID,
		Elite:       2,
		Level:       90,
		Potential:   6,
		Module:      typhonXModuleID,
		ModuleLevel: 3,
	}
	specE2X, err := buildTyphonSourceSpec(st, 2, 10)
	if err != nil {
		t.Fatalf("buildTyphonSourceSpec failed: %v", err)
	}

	opSpec := OperatorSpec{
		CharID:         typhonCharID,
		Name:           "提丰",
		Cell:           [2]int{0, 2},
		MaxHP:          2000,
		ATK:            1000,
		DEF:            200,
		RES:            0,
		AttackInterval: 2.4,
		DamageType:     "PHYSICAL",
		PreferHeaviest: true,
		TyphonSource:   specE2X,
		Range:          [][2]int{{1, 2}, {2, 2}, {3, 2}, {4, 2}},
	}

	spawns := []SpawnSpec{
		{
			EnemyID:    "light_runner",
			Name:       "轻型探路者",
			Time:       0.5,
			HP:         1500,
			ATK:        100,
			DEF:        100,
			MoveSpeed:  0.2,
			Weight:     1.0,
			DamageType: "PHYSICAL",
			Legs: []LegSpec{
				{
					Kind:   "walk",
					Points: [][2]float64{{4, 2}, {0, 2}},
				},
			},
		},
		{
			EnemyID:    "heavy_defender",
			Name:       "重装防暴卫士",
			Time:       1.0,
			HP:         3000,
			ATK:        200,
			DEF:        500,
			MoveSpeed:  0.2,
			Weight:     4.0,
			DamageType: "PHYSICAL",
			Legs: []LegSpec{
				{
					Kind:   "walk",
					Points: [][2]float64{{4, 2}, {0, 2}},
				},
			},
		},
	}

	simSpec := Spec{
		FPS:       30,
		MaxTime:   15.0,
		Life:      3,
		CostInit:  99,
		CostMax:   99,
		CostTime:  1.0,
		Operators: []OperatorSpec{opSpec},
		Deploys: []DeploySpec{
			{
				CharID: typhonCharID,
				Index:  0,
				Time:   0.0,
			},
		},
		Spawns: spawns,
	}

	verdict, err := runSimContext(context.Background(), &simSpec)
	if err != nil {
		t.Fatalf("runSimContext failed: %v", err)
	}

	t.Logf("Typhon battle lifecycle finished: DamageDealt=%f, Kills=%d, Events=%d",
		verdict.DamageDealt, verdict.Kills, len(verdict.Events))

	if verdict.DamageDealt <= 0 {
		t.Fatalf("Expected Typhon to deal damage, got %f", verdict.DamageDealt)
	}
}
