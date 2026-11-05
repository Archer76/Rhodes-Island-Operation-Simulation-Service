package main

import (
	"math"
	"testing"
)

// TestSbell2SourceSpecCoverage 验证不同精英、潜能、技能等级和模组组合下的数据驱动规格解析
func TestSbell2SourceSpecCoverage(t *testing.T) {
	stBase := &OperatorStats{
		CharID:     sbell2CharID,
		Name:       "圣聆初雪",
		Elite:      0,
		Level:      50,
		Potential:  1,
	}

	specE0, err := buildSbell2SourceSpec(stBase, 1, 7)
	if err != nil {
		t.Fatalf("buildSbell2SourceSpec E0 failed: %v", err)
	}
	cfgE0, err := decodeSbell2RuntimeConfig(specE0)
	if err != nil {
		t.Fatalf("decodeSbell2RuntimeConfig E0 failed: %v", err)
	}

	if cfgE0.Slot != 1 || cfgE0.SkillLevel != 7 {
		t.Fatalf("E0 slot/level mismatch: got slot=%d lvl=%d", cfgE0.Slot, cfgE0.SkillLevel)
	}
	if cfgE0.T1Interval != 10.0 || cfgE0.T1TalentMagicScale != 0.20 || cfgE0.T1MoveSpeed != -0.10 {
		t.Fatalf("E0 T1 mismatch: interval=%v scale=%v spd=%v", cfgE0.T1Interval, cfgE0.T1TalentMagicScale, cfgE0.T1MoveSpeed)
	}
	if cfgE0.T2Unlocked {
		t.Fatalf("E0 should not unlock T2")
	}

	// 精英2 满潜 模组 Y Lv3 S3 M3
	stE2Max := &OperatorStats{
		CharID:      sbell2CharID,
		Name:        "圣聆初雪",
		Elite:       2,
		Level:       90,
		Potential:   6,
		Module:      sbell2YModuleID,
		ModuleLevel: 3,
	}
	specE2Y, err := buildSbell2SourceSpec(stE2Max, 3, 10)
	if err != nil {
		t.Fatalf("buildSbell2SourceSpec E2Y failed: %v", err)
	}
	cfgE2Y, err := decodeSbell2RuntimeConfig(specE2Y)
	if err != nil {
		t.Fatalf("decodeSbell2RuntimeConfig E2Y failed: %v", err)
	}

	if !cfgE2Y.T2Unlocked {
		t.Fatalf("E2 should unlock T2")
	}
	if cfgE2Y.T2Cold != 2.0 || cfgE2Y.T2Freeze != 4.0 || cfgE2Y.T2C2eFreeze != 8.0 || cfgE2Y.T2HpRatio != 1.0 {
		t.Fatalf("E2 T2 mismatch: cold=%v freeze=%v c2e=%v hp_ratio=%v",
			cfgE2Y.T2Cold, cfgE2Y.T2Freeze, cfgE2Y.T2C2eFreeze, cfgE2Y.T2HpRatio)
	}
	// 模组 Y Lv3 天赋一升级检验
	if cfgE2Y.T1Interval != 5.0 || cfgE2Y.T1TalentMagicScale != 1.05 || !cfgE2Y.T1FirstSnow {
		t.Fatalf("Module Y Lv3 T1 mismatch: interval=%v scale=%v first_snow=%v",
			cfgE2Y.T1Interval, cfgE2Y.T1TalentMagicScale, cfgE2Y.T1FirstSnow)
	}
	// 模组 Y 特性强化检验
	if cfgE2Y.TraitDamageScale != 0.03 || cfgE2Y.TraitMaxValidStackCnt != 5 {
		t.Fatalf("Module Y Trait mismatch: scale=%v stacks=%v",
			cfgE2Y.TraitDamageScale, cfgE2Y.TraitMaxValidStackCnt)
	}
	// S3 检验
	if cfgE2Y.S3Atk != 1.0 || cfgE2Y.S3AttackSpeed != 30.0 || cfgE2Y.S3MagicResistPenetrateFixed != 10.0 || cfgE2Y.S3AtkScaleS3 != 2.6 {
		t.Fatalf("S3 values mismatch: atk=%v aspd=%v respen=%v scale=%v",
			cfgE2Y.S3Atk, cfgE2Y.S3AttackSpeed, cfgE2Y.S3MagicResistPenetrateFixed, cfgE2Y.S3AtkScaleS3)
	}
}

// TestSbell2PhalanxTrait 验证阵法术师未开技能高防抗且不攻击，开技能群攻且防抗回归常态
func TestSbell2PhalanxTrait(t *testing.T) {
	cfg := &Sbell2RuntimeConfig{
		TraitDef:             2.0,
		TraitMagicResistance: 20.0,
		Slot:                 1,
	}
	rt := newSbell2Runtime(cfg)

	// 未开启技能
	if !rt.CanNormalAttack(false) {
		// 期望：false (未开技能不攻击)
	} else {
		t.Fatalf("Phalanx caster should not attack when skill is inactive")
	}

	baseDEF := 265.0
	bonusDEF := rt.TraitBonusDEF(false, baseDEF)
	if bonusDEF != 530.0 { // 265 * 2.0 = 530
		t.Fatalf("Trait bonus DEF mismatch: got %v, expected 530.0", bonusDEF)
	}
	bonusRES := rt.TraitBonusRES(false)
	if bonusRES != 20.0 {
		t.Fatalf("Trait bonus RES mismatch: got %v, expected 20.0", bonusRES)
	}

	// 开启技能
	if !rt.CanNormalAttack(true) {
		t.Fatalf("Phalanx caster should attack when skill is active")
	}
	if rt.TraitBonusDEF(true, baseDEF) != 0 {
		t.Fatalf("Trait bonus DEF should be 0 when skill is active")
	}
	if rt.TraitBonusRES(true) != 0 {
		t.Fatalf("Trait bonus RES should be 0 when skill is active")
	}
}

// TestSbell2Talent2BlessingSave 验证第二天赋致命伤免死满血复活、自身冻结、全范围敌人冻结
func TestSbell2Talent2BlessingSave(t *testing.T) {
	cfg := &Sbell2RuntimeConfig{
		T2Unlocked:  true,
		T2HpRatio:   1.0,
		T2Cold:      1.5,
		T2Freeze:    4.0,
		T2C2eFreeze: 8.0,
	}
	rt := newSbell2Runtime(cfg)

	op := &operator{
		spec: OperatorSpec{
			CharID: sbell2CharID,
			Name:   "圣聆初雪",
			MaxHP:  2058,
			Range:  [][2]int{{0, 0}, {0, 1}, {1, 0}},
		},
		hp: 0, // 濒死
	}

	enemies := []*enemy{
		{spec: SpawnSpec{Name: "敌人A"}, hp: 1000, position: [2]float64{0.0, 0.0}},  // cell 0,0
		{spec: SpawnSpec{Name: "敌人B"}, hp: 1000, position: [2]float64{0.0, 1.0}},  // cell 0,1
		{spec: SpawnSpec{Name: "远方敌"}, hp: 1000, position: [2]float64{5.0, 5.0}}, // cell 5,5
	}
	enemies[0].index = 0
	enemies[1].index = 1
	enemies[2].index = 2

	verdict := &Verdict{}
	triggered := rt.TriggerBlessingSave(op, enemies, 10.0, verdict)
	if !triggered {
		t.Fatalf("Blessing save should be triggered")
	}
	if op.hp != 2058 {
		t.Fatalf("Operator should be restored to max HP, got %v", op.hp)
	}
	if op.freezeTimer != 4.0 {
		t.Fatalf("Operator should be frozen for 4.0s, got %v", op.freezeTimer)
	}
	if enemies[0].freezeTimer != 8.0 || enemies[1].freezeTimer != 8.0 {
		t.Fatalf("Enemies in range should be frozen for 8.0s, got e0=%v e1=%v",
			enemies[0].freezeTimer, enemies[1].freezeTimer)
	}
	if enemies[2].freezeTimer != 0 {
		t.Fatalf("Enemy out of range should not be frozen, got %v", enemies[2].freezeTimer)
	}

	// 再次濒死不该再次触发免死
	op.hp = 0
	if rt.TriggerBlessingSave(op, enemies, 20.0, verdict) {
		t.Fatalf("Blessing save should only trigger once")
	}
}

// TestSbell2Talent2CounterCold 验证受到攻击反击寒冷
func TestSbell2Talent2CounterCold(t *testing.T) {
	cfg := &Sbell2RuntimeConfig{
		T2Unlocked: true,
		T2Cold:     1.5,
	}
	rt := newSbell2Runtime(cfg)

	e := &enemy{
		spec: SpawnSpec{Name: "攻击者"},
		hp:   1000,
	}

	rt.OnTakeDamage(e, true)
	if math.Abs(e.coldTimer-1.5) > 1e-4 {
		t.Fatalf("Attacker should receive 1.5s cold, got %v", e.coldTimer)
	}
	if e.freezeTimer != 0 {
		t.Fatalf("First cold should not freeze")
	}

	// 再次受击反击寒冷应转为冻结
	rt.OnTakeDamage(e, true)
	if math.Abs(e.freezeTimer-1.5) > 1e-4 {
		t.Fatalf("Subsequent cold should convert to freeze, got %v", e.freezeTimer)
	}
}

// TestSbell2ModuleDamageScale 验证 Y 模组范围内敌人越多造成的伤害越高
func TestSbell2ModuleDamageScale(t *testing.T) {
	cfg := &Sbell2RuntimeConfig{
		TraitDamageScale:      0.03,
		TraitMaxValidStackCnt: 5,
	}
	rt := newSbell2Runtime(cfg)

	if mult := rt.DamageMultiplier(0); mult != 1.0 {
		t.Fatalf("0 enemies: expected 1.0, got %v", mult)
	}
	if mult := rt.DamageMultiplier(1); math.Abs(mult-1.03) > 1e-4 {
		t.Fatalf("1 enemy: expected 1.03, got %v", mult)
	}
	if mult := rt.DamageMultiplier(3); math.Abs(mult-1.09) > 1e-4 {
		t.Fatalf("3 enemies: expected 1.09, got %v", mult)
	}
	if mult := rt.DamageMultiplier(5); math.Abs(mult-1.15) > 1e-4 {
		t.Fatalf("5 enemies: expected 1.15, got %v", mult)
	}
	if mult := rt.DamageMultiplier(10); math.Abs(mult-1.15) > 1e-4 {
		t.Fatalf("10 enemies: expected 1.15 (capped), got %v", mult)
	}
}
