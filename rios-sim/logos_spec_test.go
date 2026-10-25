package main

import (
	"math"
	"testing"
)

func logosCfgForTest(t *testing.T, st *OperatorStats, slot, level int) *LogosRuntimeConfig {
	t.Helper()
	spec, err := buildLogosSourceSpec(st, slot, level)
	if err != nil {
		t.Fatalf("buildLogosSourceSpec E%dP%dS%dL%d: %v", st.Elite, st.Potential, slot, level, err)
	}
	cfg, err := decodeLogosRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decodeLogosRuntimeConfig E%dP%dS%dL%d: %v", st.Elite, st.Potential, slot, level, err)
	}
	return cfg
}

// TestLogosSourceTrainingSlotsAndRawEvidence 覆盖 精英×潜能×技能槽×技能等级 的规格矩阵
func TestLogosSourceTrainingSlotsAndRawEvidence(t *testing.T) {
	chdirRepoRootForData(t)

	for _, elite := range []int{0, 1, 2} {
		for _, pot := range []int{1, 5} {
			for slot := 1; slot <= 3; slot++ {
				if slot > elite+1 {
					continue
				}
				for _, sl := range []int{1, 7, 10} {
					if sl > 7 && elite < 2 {
						continue
					}
					st := &OperatorStats{
						CharID:    logosCharID,
						Elite:     elite,
						Level:     60,
						Potential: pot,
					}
					spec, err := buildLogosSourceSpec(st, slot, sl)
					if err != nil {
						t.Fatalf("E%dP%dS%dL%d buildLogosSourceSpec failed: %v", elite, pot, slot, sl, err)
					}
					if spec.Slot != slot || spec.SkillLevel != sl {
						t.Fatalf("spec mismatch slot=%d lvl=%d", spec.Slot, spec.SkillLevel)
					}
				}
			}
		}
	}
}

// TestLogosTalentsAndSkillsValues 严格比对 gamedata 原始数值
func TestLogosTalentsAndSkillsValues(t *testing.T) {
	chdirRepoRootForData(t)

	// 1. 精一天赋一基础档
	stE1P1 := &OperatorStats{CharID: logosCharID, Elite: 1, Level: 60, Potential: 1}
	cfgE1P1 := logosCfgForTest(t, stE1P1, 1, 7)
	if !cfgE1P1.Talent1Enabled || math.Abs(cfgE1P1.Talent1Prob-0.4) > 1e-6 || math.Abs(cfgE1P1.Talent1AtkScale-0.4) > 1e-6 {
		t.Fatalf("E1P1 talent1 mismatch: %+v", cfgE1P1)
	}
	if cfgE1P1.Talent2Enabled {
		t.Fatal("E1 不应该解锁天赋二")
	}

	// 2. 精二天赋一进阶与天赋二
	stE2P1 := &OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}
	cfgE2P1 := logosCfgForTest(t, stE2P1, 1, 10)
	if math.Abs(cfgE2P1.Talent1AtkScale-0.6) > 1e-6 || math.Abs(cfgE2P1.Talent1Sluggish-0.8) > 1e-6 {
		t.Fatalf("E2P1 talent1 mismatch: %+v", cfgE2P1)
	}
	if !cfgE2P1.Talent2Enabled || math.Abs(cfgE2P1.Talent2MagicResDelta-(-10)) > 1e-6 || math.Abs(cfgE2P1.Talent2AtkAddition-150) > 1e-6 {
		t.Fatalf("E2P1 talent2 mismatch: %+v", cfgE2P1)
	}

	// 3. 潜能提升 (潜能 5 = 潜能等级 5, index 4)
	stE2P5 := &OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 5}
	cfgE2P5 := logosCfgForTest(t, stE2P5, 1, 10)
	if math.Abs(cfgE2P5.Talent1AtkScale-0.65) > 1e-6 {
		t.Fatalf("E2P5 talent1 atk_scale mismatch: %v", cfgE2P5.Talent1AtkScale)
	}
	if math.Abs(cfgE2P5.Talent2AtkAddition-165) > 1e-6 {
		t.Fatalf("E2P5 talent2 atk_addition mismatch: %v", cfgE2P5.Talent2AtkAddition)
	}

	// 4. 技能一 (M3)
	if math.Abs(cfgE2P5.S1AtkRatio-1.0) > 1e-6 || math.Abs(cfgE2P5.S1KillAtkScale-1.5) > 1e-6 || cfgE2P5.SPCost != 60 {
		t.Fatalf("S1 M3 mismatch: %+v", cfgE2P5)
	}

	// 5. 技能二 (M3)
	cfgS2 := logosCfgForTest(t, stE2P5, 2, 10)
	if math.Abs(cfgS2.S2MagicRes-70) > 1e-6 || math.Abs(cfgS2.S2Cooldown-0.5) > 1e-6 || math.Abs(cfgS2.S2AtkScaleBase-0.75) > 1e-6 || math.Abs(cfgS2.S2AtkScaleDelta-0.15) > 1e-6 || cfgS2.S2MaxStackCnt != 10 {
		t.Fatalf("S2 M3 mismatch: %+v", cfgS2)
	}

	// 6. 技能三 (M3)
	cfgS3 := logosCfgForTest(t, stE2P5, 3, 10)
	if math.Abs(cfgS3.S3AtkRatio-3.0) > 1e-6 || cfgS3.S3MaxTarget != 4 || math.Abs(cfgS3.S3ProjectileMoveScale-0.05) > 1e-6 || cfgS3.SPCost != 45 || cfgS3.InitSP != 30 || math.Abs(cfgS3.Duration-30) > 1e-6 {
		t.Fatalf("S3 M3 mismatch: %+v", cfgS3)
	}
}

// TestLogosModuleEvidenceAndUpgrades 测试模组升级覆盖
func TestLogosModuleEvidenceAndUpgrades(t *testing.T) {
	chdirRepoRootForData(t)

	// 模组X: 来自河谷的笔盒 Lv3
	stModX := &OperatorStats{
		CharID: logosCharID, Elite: 2, Level: 60, Potential: 1,
		Module: logosModule1ID, ModuleLevel: 3,
	}
	cfgX := logosCfgForTest(t, stModX, 3, 10)
	if math.Abs(cfgX.Talent1Prob-0.6) > 1e-6 || math.Abs(cfgX.Talent1ElementScale-0.6) > 1e-6 || math.Abs(cfgX.ModTraitEPDamageRatio-0.08) > 1e-6 {
		t.Fatalf("Module X Lv3 mismatch: %+v", cfgX)
	}

	// 模组Y: 《语义范式百科》 Lv3
	stModY := &OperatorStats{
		CharID: logosCharID, Elite: 2, Level: 60, Potential: 1,
		Module: logosModule2ID, ModuleLevel: 3,
	}
	cfgY := logosCfgForTest(t, stModY, 3, 10)
	if cfgY.Talent1EmitCount != 2 || math.Abs(cfgY.Talent1AtkScale-0.65) > 1e-6 || cfgY.ModTraitSP != 1 {
		t.Fatalf("Module Y Lv3 mismatch: %+v", cfgY)
	}
}

// TestLogosIllegalStatsBoundaries 测试边界与非法档位拒绝
func TestLogosIllegalStatsBoundaries(t *testing.T) {
	chdirRepoRootForData(t)

	// 非 Logos
	if s, err := buildLogosSourceSpec(&OperatorStats{CharID: "char_100_not_logos"}, 1, 7); err != nil || s != nil {
		t.Fatal("non-logos must return nil, nil")
	}
	// 精0解锁技2
	if _, err := buildLogosSourceSpec(&OperatorStats{CharID: logosCharID, Elite: 0, Level: 1, Potential: 1}, 2, 7); err == nil {
		t.Fatal("elite 0 slot 2 must fail")
	}
	// 技能槽超范围
	if _, err := buildLogosSourceSpec(&OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}, 4, 7); err == nil {
		t.Fatal("slot 4 must fail")
	}
	// 技能等级超范围
	if _, err := buildLogosSourceSpec(&OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}, 1, 0); err == nil {
		t.Fatal("skillLevel 0 must fail")
	}
	// 精1专精
	if _, err := buildLogosSourceSpec(&OperatorStats{CharID: logosCharID, Elite: 1, Level: 60, Potential: 1}, 1, 8); err == nil {
		t.Fatal("mastery at elite 1 must fail")
	}
}
