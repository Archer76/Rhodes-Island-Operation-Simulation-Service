package main

import (
	"math"
	"testing"
)

func ulpiaCfgForTest(t *testing.T, st *OperatorStats, slot, level int) *UlpiaRuntimeConfig {
	t.Helper()
	spec, err := buildUlpiaSourceSpec(st, slot, level)
	if err != nil {
		t.Fatalf("buildUlpiaSourceSpec E%dP%dS%dL%d: %v", st.Elite, st.Potential, slot, level, err)
	}
	cfg, err := decodeUlpiaRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decodeUlpiaRuntimeConfig: %v", err)
	}
	return cfg
}

func TestUlpiaSourceTrainingSlotsAndRawEvidence(t *testing.T) {
	for _, elite := range []int{0, 1, 2} {
		for _, pot := range []int{1, 5} {
			for slot := 1; slot <= 3; slot++ {
				for _, sl := range []int{1, 7, 10} {
					if slot == 2 && elite < 1 {
						continue
					}
					if slot == 3 && elite < 2 {
						continue
					}
					if sl > 7 && elite < 2 {
						continue
					}
					st := &OperatorStats{
						Name:      "乌尔比安",
						CharID:    ulpiaCharID,
						Elite:     elite,
						Level:     60,
						Potential: pot,
					}
					spec, err := buildUlpiaSourceSpec(st, slot, sl)
					if err != nil {
						t.Fatalf("E%dP%dS%dL%d buildUlpiaSourceSpec failed: %v", elite, pot, slot, sl, err)
					}
					if !spec.ConsumerImplemented {
						t.Fatal("ConsumerImplemented must be true")
					}
					if spec.Evidence["character_table:"+ulpiaCharID] == nil {
						t.Fatal("character_table evidence missing")
					}
					if len(spec.OperatorSkill.Raw) == 0 {
						t.Fatal("skill raw missing")
					}
				}
			}
		}
	}
}

func TestUlpiaTalentsAndSkillsValues(t *testing.T) {
	stE1P1 := &OperatorStats{CharID: ulpiaCharID, Elite: 1, Level: 60, Potential: 1}
	cfgE1P1 := ulpiaCfgForTest(t, stE1P1, 1, 7)
	if !cfgE1P1.Talent1Enabled || cfgE1P1.Talent2Enabled {
		t.Fatalf("E1 should have talent1 but not talent2")
	}
	if cfgE1P1.Talent1Value1 != 80 || cfgE1P1.Talent1Value2 != 120 || cfgE1P1.Talent1HPRatio != 0.5 {
		t.Fatalf("E1P1 talent1 values mismatch: got %v/%v/%v", cfgE1P1.Talent1Value1, cfgE1P1.Talent1Value2, cfgE1P1.Talent1HPRatio)
	}

	stE2P1 := &OperatorStats{CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1}
	cfgE2P1 := ulpiaCfgForTest(t, stE2P1, 1, 10)
	if !cfgE2P1.Talent1Enabled || !cfgE2P1.Talent2Enabled {
		t.Fatalf("E2 should have both talent1 and talent2")
	}
	if cfgE2P1.Talent1Value1 != 100 || cfgE2P1.Talent1Value2 != 160 {
		t.Fatalf("E2P1 talent1 values mismatch: got %v/%v", cfgE2P1.Talent1Value1, cfgE2P1.Talent1Value2)
	}
	if cfgE2P1.Talent2MaxStackCnt != 9 || cfgE2P1.Talent2MaxHPPerStack != 120 || cfgE2P1.Talent2AtkPerStack != 30 {
		t.Fatalf("E2P1 talent2 values mismatch: got %v/%v/%v", cfgE2P1.Talent2MaxStackCnt, cfgE2P1.Talent2MaxHPPerStack, cfgE2P1.Talent2AtkPerStack)
	}
	if cfgE2P1.Talent2AbyssalMaxHP != 60 || cfgE2P1.Talent2AbyssalAtk != 15 || cfgE2P1.Talent2AbyssalMaxStack != 9 {
		t.Fatalf("E2P1 talent2 abyssal values mismatch: got %v/%v/%v", cfgE2P1.Talent2AbyssalMaxHP, cfgE2P1.Talent2AbyssalAtk, cfgE2P1.Talent2AbyssalMaxStack)
	}

	stE2P5 := &OperatorStats{CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 5}
	cfgE2P5 := ulpiaCfgForTest(t, stE2P5, 1, 10)
	if cfgE2P5.Talent2MaxStackCnt != 10 || cfgE2P5.Talent2AbyssalMaxStack != 10 {
		t.Fatalf("E2P5 talent2 max_stack_cnt should be 10, got %v/%v", cfgE2P5.Talent2MaxStackCnt, cfgE2P5.Talent2AbyssalMaxStack)
	}

	// 技能一黑板
	if cfgE2P5.S1AtkScale != 2.7 || cfgE2P5.S1MaxTarget != 2 || cfgE2P5.S1Force != 1.0 {
		t.Fatalf("S1 blackboard mismatch: %v/%v/%v", cfgE2P5.S1AtkScale, cfgE2P5.S1MaxTarget, cfgE2P5.S1Force)
	}
	if cfgE2P5.SkillRangeID != "3-2" || len(cfgE2P5.SkillRangeCells) != 4 {
		t.Fatalf("S1 range mismatch: %s / %d", cfgE2P5.SkillRangeID, len(cfgE2P5.SkillRangeCells))
	}

	// 技能二黑板
	cfgS2 := ulpiaCfgForTest(t, stE2P5, 2, 10)
	if cfgS2.S2TalentScale != 2.0 || cfgS2.S2AtkRatio != 1.6 || cfgS2.S2MaxHPRatio != 0.6 || cfgS2.S2BlockCnt != 1 {
		t.Fatalf("S2 blackboard mismatch: %v/%v/%v/%v", cfgS2.S2TalentScale, cfgS2.S2AtkRatio, cfgS2.S2MaxHPRatio, cfgS2.S2BlockCnt)
	}

	// 技能三黑板
	cfgS3 := ulpiaCfgForTest(t, stE2P5, 3, 10)
	if cfgS3.S3MaxHPRatio != 0.8 || cfgS3.S3AtkRatio != 2.6 || cfgS3.S3AtkScale != 1.6 || cfgS3.S3StunDuration != 6.0 || cfgS3.S3ProjectileRange != 1.8 {
		t.Fatalf("S3 blackboard mismatch: %v/%v/%v/%v/%v", cfgS3.S3MaxHPRatio, cfgS3.S3AtkRatio, cfgS3.S3AtkScale, cfgS3.S3StunDuration, cfgS3.S3ProjectileRange)
	}
	if cfgS3.SkillRangeID != "6-1" || len(cfgS3.SkillRangeCells) != 7 {
		t.Fatalf("S3 range mismatch: %s / %d", cfgS3.SkillRangeID, len(cfgS3.SkillRangeCells))
	}
}

func TestUlpiaModuleEvidenceAndUpgrades(t *testing.T) {
	// 模组X: uniequip_002_ulpia
	stModX := &OperatorStats{
		CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1,
		Module: ulpiaModule1ID, ModuleLevel: 3,
	}
	cfgX := ulpiaCfgForTest(t, stModX, 2, 10)
	if cfgX.ModTraitHealScale != 1.2 {
		t.Fatalf("Mod X heal_scale expected 1.2, got %v", cfgX.ModTraitHealScale)
	}
	if cfgX.Talent1Value1 != 130 || cfgX.Talent1Value2 != 175 || cfgX.Talent1HPRatio != 0.6 {
		t.Fatalf("Mod X talent1 upgrade mismatch: %v/%v/%v", cfgX.Talent1Value1, cfgX.Talent1Value2, cfgX.Talent1HPRatio)
	}

	// 模组Y: uniequip_003_ulpia
	stModY := &OperatorStats{
		CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1,
		Module: ulpiaModule2ID, ModuleLevel: 3,
	}
	cfgY := ulpiaCfgForTest(t, stModY, 2, 10)
	if cfgY.ModTraitDamageScale != 1.1 {
		t.Fatalf("Mod Y damage_scale expected 1.1, got %v", cfgY.ModTraitDamageScale)
	}
	if cfgY.Talent2MaxHPPerStack != 150 || cfgY.Talent2AtkPerStack != 38 {
		t.Fatalf("Mod Y talent2 self mismatch: %v/%v", cfgY.Talent2MaxHPPerStack, cfgY.Talent2AtkPerStack)
	}
	if cfgY.Talent2AbyssalMaxHP != 90 || math.Abs(cfgY.Talent2AbyssalAtk-22.8) > 0.1 {
		t.Fatalf("Mod Y talent2 abyssal mismatch: %v/%v", cfgY.Talent2AbyssalMaxHP, cfgY.Talent2AbyssalAtk)
	}
	if cfgY.Talent2ModAddBlockCnt != 1 || cfgY.Talent2ModAddBlockStack != 9 {
		t.Fatalf("Mod Y talent2 block_cnt mismatch: %v/%v", cfgY.Talent2ModAddBlockCnt, cfgY.Talent2ModAddBlockStack)
	}
}

func TestUlpiaIllegalStatsBoundaries(t *testing.T) {
	if s, err := buildUlpiaSourceSpec(&OperatorStats{CharID: "char_100_not_ulpia"}, 1, 7); err != nil || s != nil {
		t.Fatal("non-ulpia must return nil, nil")
	}
	if _, err := buildUlpiaSourceSpec(&OperatorStats{CharID: ulpiaCharID, Elite: 0, Level: 1, Potential: 1}, 2, 7); err == nil {
		t.Fatal("slot 2 at E0 must fail")
	}
	if _, err := buildUlpiaSourceSpec(&OperatorStats{CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1}, 4, 7); err == nil {
		t.Fatal("slot 4 must fail")
	}
	if _, err := buildUlpiaSourceSpec(&OperatorStats{CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1}, 1, 0); err == nil {
		t.Fatal("skillLevel 0 must fail")
	}
	if _, err := buildUlpiaSourceSpec(&OperatorStats{CharID: ulpiaCharID, Elite: 1, Level: 60, Potential: 1}, 1, 8); err == nil {
		t.Fatal("mastery at E1 must fail")
	}
}
