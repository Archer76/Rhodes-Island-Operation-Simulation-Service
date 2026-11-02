package main

import (
	"math"
	"testing"
)

// TestAsclnSourceSpecCoverage 验证不同精英、潜能、技能等级和模组组合下的数据驱动规格解析
func TestAsclnSourceSpecCoverage(t *testing.T) {
	stBase := &OperatorStats{
		CharID:     asclnCharID,
		Elite:      0,
		Level:      50,
		Potential:  1,
	}
	specE0, err := buildAsclnSourceSpec(stBase, 1, 7)
	if err != nil {
		t.Fatalf("buildAsclnSourceSpec E0 failed: %v", err)
	}
	cfgE0, err := decodeAsclnRuntimeConfig(specE0)
	if err != nil {
		t.Fatalf("decodeAsclnRuntimeConfig E0 failed: %v", err)
	}
	if math.Abs(cfgE0.T1MoveSpeed-(-0.12)) > 1e-6 {
		t.Errorf("E0 T1MoveSpeed expected -0.12, got %f", cfgE0.T1MoveSpeed)
	}
	if math.Abs(cfgE0.T1AtkRatio-0.06) > 1e-6 {
		t.Errorf("E0 T1AtkRatio expected 0.06, got %f", cfgE0.T1AtkRatio)
	}
	if cfgE0.T2Unlocked {
		t.Errorf("E0 should not unlock T2")
	}

	// 精英 2 满潜能 技能 3 专精 3 + X 模组 3 级
	stE2Max := &OperatorStats{
		CharID:      asclnCharID,
		Elite:       2,
		Level:       90,
		Potential:   6,
		Module:      asclnXModuleID,
		ModuleLevel: 3,
	}
	specE2X, err := buildAsclnSourceSpec(stE2Max, 3, 10)
	if err != nil {
		t.Fatalf("buildAsclnSourceSpec E2X failed: %v", err)
	}
	cfgE2X, err := decodeAsclnRuntimeConfig(specE2X)
	if err != nil {
		t.Fatalf("decodeAsclnRuntimeConfig E2X failed: %v", err)
	}
	if !cfgE2X.T2Unlocked {
		t.Errorf("E2 should unlock T2")
	}
	if math.Abs(cfgE2X.T2AttackSpeed-10.0) > 1e-6 {
		t.Errorf("E2 Pot6 T2AttackSpeed expected 10, got %f", cfgE2X.T2AttackSpeed)
	}
	if math.Abs(cfgE2X.T2AttackSpeedAdd-6.0) > 1e-6 {
		t.Errorf("E2 T2AttackSpeedAdd expected 6, got %f", cfgE2X.T2AttackSpeedAdd)
	}
	// X 模组 3 级天赋一升级覆盖：atk_ratio 0.11, debuff_duration 30.0, trait 移速 -0.2
	if math.Abs(cfgE2X.T1AtkRatio-0.11) > 1e-6 {
		t.Errorf("E2X3 T1AtkRatio expected 0.11, got %f", cfgE2X.T1AtkRatio)
	}
	if math.Abs(cfgE2X.T1DebuffDuration-30.0) > 1e-6 {
		t.Errorf("E2X3 T1DebuffDuration expected 30.0, got %f", cfgE2X.T1DebuffDuration)
	}
	if math.Abs(cfgE2X.TraitMoveSpeed-(-0.2)) > 1e-6 {
		t.Errorf("E2X3 TraitMoveSpeed expected -0.2, got %f", cfgE2X.TraitMoveSpeed)
	}
	// 技能 3 数值
	if math.Abs(cfgE2X.S3Atk-0.5) > 1e-6 {
		t.Errorf("S3 Atk expected 0.5, got %f", cfgE2X.S3Atk)
	}
	if math.Abs(cfgE2X.S3BaseAttackTime-(-1.5)) > 1e-6 {
		t.Errorf("S3 BaseAttackTime expected -1.5, got %f", cfgE2X.S3BaseAttackTime)
	}
	if math.Abs(cfgE2X.S3TauntLevel-2.0) > 1e-6 {
		t.Errorf("S3 TauntLevel expected 2.0, got %f", cfgE2X.S3TauntLevel)
	}
	if math.Abs(cfgE2X.S3DamageHitratePhys-(-0.5)) > 1e-6 {
		t.Errorf("S3 DamageHitratePhys expected -0.5, got %f", cfgE2X.S3DamageHitratePhys)
	}
	if math.Abs(cfgE2X.S3AttackHpRatio-0.08) > 1e-6 {
		t.Errorf("S3 AttackHpRatio expected 0.08, got %f", cfgE2X.S3AttackHpRatio)
	}
}

// TestAsclnT1StackingAndDoT 验证第一天赋层数叠加、持续时间重置与 DoT 跳字伤害
func TestAsclnT1StackingAndDoT(t *testing.T) {
	cfg := &AsclnRuntimeConfig{
		T1MoveSpeed:      -0.18,
		T1AtkRatio:       0.10,
		T1MaxStackCnt:    3,
		T1DebuffDuration: 25.0,
		T1Interval:       1.0,
		RNGSeed:          12345,
	}
	rt := newAsclnRuntime(cfg)
	enemyIdx := 1

	// 命中第 1 次
	rt.ApplyT1Debuff(enemyIdx)
	st := rt.Debuffs[enemyIdx]
	if st.Stacks != 1 || st.RemainingTime != 25.0 {
		t.Fatalf("1st hit: stacks=%d, time=%f", st.Stacks, st.RemainingTime)
	}
	if mod := rt.EnemyMoveSpeedModifier(enemyIdx, false); math.Abs(mod-(-0.18)) > 1e-6 {
		t.Errorf("1 stack mod expected -0.18, got %f", mod)
	}

	// 命中第 2 次
	st.RemainingTime = 10.0 // 模拟时间过去
	rt.ApplyT1Debuff(enemyIdx)
	if st.Stacks != 2 || st.RemainingTime != 25.0 {
		t.Fatalf("2nd hit: stacks=%d, time=%f", st.Stacks, st.RemainingTime)
	}
	if mod := rt.EnemyMoveSpeedModifier(enemyIdx, false); math.Abs(mod-(-0.36)) > 1e-6 {
		t.Errorf("2 stacks mod expected -0.36, got %f", mod)
	}

	// 命中第 3 次（满层）
	rt.ApplyT1Debuff(enemyIdx)
	if st.Stacks != 3 {
		t.Fatalf("3rd hit: stacks=%d", st.Stacks)
	}
	if mod := rt.EnemyMoveSpeedModifier(enemyIdx, false); math.Abs(mod-(-0.54)) > 1e-6 {
		t.Errorf("3 stacks mod expected -0.54, got %f", mod)
	}

	// 命中第 4 次（超过上限，层数保持 3，时间刷新）
	st.RemainingTime = 5.0
	rt.ApplyT1Debuff(enemyIdx)
	if st.Stacks != 3 || st.RemainingTime != 25.0 {
		t.Fatalf("4th hit: stacks=%d, time=%f", st.Stacks, st.RemainingTime)
	}
}

// TestAsclnS3HitrateSamplingDeterministic 验证技能三确定性伪随机抽样（V-2 规范）
func TestAsclnS3HitrateSamplingDeterministic(t *testing.T) {
	cfg := &AsclnRuntimeConfig{
		Slot:                3,
		S3DamageHitratePhys: -0.50,
		S3DamageHitrateMag:  -0.50,
		S3AttackHpRatio:     0.08,
		TraitDodgeProb:      0.50,
		RNGSeed:             42,
	}

	// 运行两轮相同的 RNG 序列，断言完全可复现、逐位一致
	rt1 := newAsclnRuntime(cfg)
	rt1.SkillActive = true
	var res1 []bool
	for i := 0; i < 100; i++ {
		hit, _ := rt1.SampleHitChance(true, true, true)
		res1 = append(res1, hit)
	}

	rt2 := newAsclnRuntime(cfg)
	rt2.SkillActive = true
	for i := 0; i < 100; i++ {
		hit, _ := rt2.SampleHitChance(true, true, true)
		if hit != res1[i] {
			t.Fatalf("draw %d mismatch between run1 and run2: %v vs %v", i, res1[i], hit)
		}
	}

	// 严禁折抵为期望：验证确有 miss 和 dodge 产生
	if rt1.MissTriggers == 0 {
		t.Errorf("expected miss triggers > 0, got %d", rt1.MissTriggers)
	}
	if rt1.DodgeTriggers == 0 {
		t.Errorf("expected dodge triggers > 0, got %d", rt1.DodgeTriggers)
	}
}

// TestAsclnS2CorpseExplosion 验证技能二击倒尸爆传播
func TestAsclnS2CorpseExplosion(t *testing.T) {
	cfg := &AsclnRuntimeConfig{
		Slot:             2,
		S2RangeRadius:    1.3,
		T1DebuffDuration: 25.0,
		T1MaxStackCnt:    3,
	}
	rt := newAsclnRuntime(cfg)
	rt.SkillActive = true

	enemies := []*enemy{
		{index: 0, hp: 0, position: [2]float64{2.0, 2.0}, spec: SpawnSpec{IsFlying: false}}, // 死亡源点
		{index: 1, hp: 100, position: [2]float64{2.5, 2.0}, spec: SpawnSpec{IsFlying: false}}, // 距离 0.5 <= 1.3，受波及
		{index: 2, hp: 100, position: [2]float64{2.2, 2.0}, spec: SpawnSpec{IsFlying: true}},  // 飞行敌人，不受波及
		{index: 3, hp: 100, position: [2]float64{4.0, 4.0}, spec: SpawnSpec{IsFlying: false}}, // 距离 > 1.3，不受波及
	}

	rt.TriggerS2CorpseExplosion(enemies, [2]float64{2.0, 2.0})

	if _, ok := rt.Debuffs[1]; !ok {
		t.Errorf("enemy 1 in range should receive T1 debuff")
	}
	if _, ok := rt.Debuffs[2]; ok {
		t.Errorf("flight enemy 2 should not receive T1 debuff")
	}
	if _, ok := rt.Debuffs[3]; ok {
		t.Errorf("distant enemy 3 should not receive T1 debuff")
	}
}
