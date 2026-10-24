package main

import "testing"

func shuCfgForTest(t *testing.T, st *OperatorStats, slot, level int) *ShuRuntimeConfig {
	t.Helper()
	spec, err := buildShuSourceSpec(st, slot, level)
	if err != nil {
		t.Fatalf("buildShuSourceSpec E%dP%dS%dL%d: %v", st.Elite, st.Potential, slot, level, err)
	}
	cfg, err := decodeShuRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decodeShuRuntimeConfig E%dP%dS%dL%d: %v", st.Elite, st.Potential, slot, level, err)
	}
	return cfg
}

// TestShuSourceTrainingSlotsAndRawEvidence 覆盖 精英×潜能×技能槽×技能等级 的
// 规格矩阵：每一档都必须能取到原文证据，且解析出的槽号/等级与输入一致。
func TestShuSourceTrainingSlotsAndRawEvidence(t *testing.T) {
	chdirRepoRootForData(t)

	for _, elite := range []int{0, 1, 2} {
		for _, pot := range []int{1, 5} {
			for slot := 1; slot <= 3; slot++ {
				if slot > elite+1 {
					continue
				}
				for _, sl := range []int{1, 7, 10} {
					st := &OperatorStats{
						CharID:    shuCharID,
						Elite:     elite,
						Level:     60,
						Potential: pot,
					}
					spec, err := buildShuSourceSpec(st, slot, sl)
					if err != nil {
						t.Fatalf("E%dP%dS%dL%d buildShuSourceSpec failed: %v", elite, pot, slot, sl, err)
					}
					if spec.Slot != slot || spec.SkillLevel != sl {
						t.Fatalf("expected slot %d lv %d, got slot %d lv %d", slot, sl, spec.Slot, spec.SkillLevel)
					}
					if len(spec.Evidence) == 0 {
						t.Fatalf("evidence empty at E%dP%dS%dL%d", elite, pot, slot, sl)
					}
					// 精英 0 没有天赋（百谷长青在 PHASE_1 解锁）；精英 1 起必须有。
					if elite >= 1 && len(spec.Talents) == 0 {
						t.Fatalf("talents empty at E%dP%dS%dL%d", elite, pot, slot, sl)
					}
					cfg := shuCfgForTest(t, st, slot, sl)
					// 黑板书键必须**全部**有归宿；一个未消费键都不许静默。
					if len(cfg.UnusedKeys) != 0 {
						t.Fatalf("E%dP%dS%dL%d 存在未消费黑板键：%v", elite, pot, slot, sl, cfg.UnusedKeys)
					}
					if len(cfg.SkillRangeCells) == 0 {
						t.Fatalf("E%dP%dS%dL%d 技能范围格为空", elite, pot, slot, sl)
					}
				}
			}
		}
	}
}

// TestShuTalentNumericTiers 钉住「百谷长青」的四档真实数值。
// 数值来自 character_table 的 talents 原文，不是手写近似。
func TestShuTalentNumericTiers(t *testing.T) {
	chdirRepoRootForData(t)

	cases := []struct {
		elite, pot int
		recovery   float64
		protect    float64
	}{
		{0, 1, 0, 0}, // 精英 0：百谷长青未解锁（PHASE_1）
		{0, 5, 0, 0},
		{1, 1, 40, 0.05},
		{1, 5, 45, 0.07},
		{2, 1, 70, 0.10},
		{2, 5, 75, 0.12},
	}
	for _, c := range cases {
		st := &OperatorStats{CharID: shuCharID, Elite: c.elite, Level: 60, Potential: c.pot}
		cfg := shuCfgForTest(t, st, 1, 7)
		if cfg.SowRecoveryPerSec != c.recovery || cfg.SowProtect != c.protect {
			t.Fatalf("E%dP%d 百谷长青 = %v/%v，期望 %v/%v",
				c.elite, c.pot, cfg.SowRecoveryPerSec, cfg.SowProtect, c.recovery, c.protect)
		}
		if cfg.BornSow {
			t.Fatalf("E%dP%d 无模组却标记了部署播种", c.elite, c.pot)
		}
	}
}

// TestShuModuleOverridesTalentTraitAndBornSow 钉住模组三级的三件事：
// 天赋回血/庇护改写、特性覆写、部署播种。
func TestShuModuleOverridesTalentTraitAndBornSow(t *testing.T) {
	chdirRepoRootForData(t)

	type want struct {
		level    int
		recovery float64
		protect  float64
		born     bool
	}
	for _, c := range []want{
		{1, 75, 0.12, false}, // Lv1 只有特性覆写，天赋仍是 E2P5 基础值
		{2, 85, 0.12, false}, // Lv2 天赋改写：85/12%，未解锁部署播种
		{3, 85, 0.17, true},  // Lv3：85/17% + born_range_id=0-1
	} {
		st := &OperatorStats{
			CharID: shuCharID, Elite: 2, Level: 60, Potential: 5,
			Module: shuModuleID, ModuleLevel: c.level,
		}
		cfg := shuCfgForTest(t, st, 3, 10)
		if cfg.SowRecoveryPerSec != c.recovery || cfg.SowProtect != c.protect {
			t.Fatalf("模组Lv%d 百谷长青 = %v/%v，期望 %v/%v",
				c.level, cfg.SowRecoveryPerSec, cfg.SowProtect, c.recovery, c.protect)
		}
		if cfg.BornSow != c.born {
			t.Fatalf("模组Lv%d BornSow = %v，期望 %v", c.level, cfg.BornSow, c.born)
		}
		if cfg.LowHealScale != 1.15 || cfg.LowHealRatio != 0.5 {
			t.Fatalf("模组Lv%d 特性覆写未解析：%v/%v", c.level, cfg.LowHealScale, cfg.LowHealRatio)
		}
	}
}

// TestShuSecondTalentAndSkillBlackboards 钉住天赋二与三个技能的关键键值。
func TestShuSecondTalentAndSkillBlackboards(t *testing.T) {
	chdirRepoRootForData(t)

	base := &OperatorStats{CharID: shuCharID, Elite: 2, Level: 60, Potential: 5}
	cfg := shuCfgForTest(t, base, 1, 10)
	if !cfg.SeasonEnabled {
		t.Fatal("E2 应当解锁天有四时")
	}
	if cfg.SeasonMaxHPRatio != 0.12 || cfg.SeasonAspd != 12 ||
		cfg.SeasonAtkRatio != 0.12 || cfg.SeasonSPInterval != 4 || cfg.SeasonSPAmount != 1 {
		t.Fatalf("天有四时数值 = %v/%v/%v/%v/%v",
			cfg.SeasonMaxHPRatio, cfg.SeasonAspd, cfg.SeasonAtkRatio,
			cfg.SeasonSPInterval, cfg.SeasonSPAmount)
	}

	s1 := shuCfgForTest(t, base, 1, 10)
	if s1.SPCost != 4 || s1.MaxCharge != 3 || s1.S1HealScale != 1.8 || s1.S1Charges != 3 {
		t.Fatalf("化被草木 = cost%v charge%v heal%v ct%v",
			s1.SPCost, s1.MaxCharge, s1.S1HealScale, s1.S1Charges)
	}

	s2 := shuCfgForTest(t, base, 2, 10)
	if s2.SPCost != 25 || s2.InitSP != 20 || s2.Duration != 25 {
		t.Fatalf("嘉禾盈仓 sp = cost%v init%v dur%v", s2.SPCost, s2.InitSP, s2.Duration)
	}
	if s2.S2AtkRatio != 1.2 || s2.S2BlockBonus != 1 || s2.S2MaxTarget != 2 ||
		s2.S2HealInterval != 1.3 || s2.S2TalentScale != 1.5 {
		t.Fatalf("嘉禾盈仓 blackboard = %v/%v/%v/%v/%v",
			s2.S2AtkRatio, s2.S2BlockBonus, s2.S2MaxTarget, s2.S2HealInterval, s2.S2TalentScale)
	}

	s3 := shuCfgForTest(t, base, 3, 10)
	if s3.SPCost != 45 || s3.InitSP != 30 || s3.Duration != 30 {
		t.Fatalf("离离枯荣 sp = cost%v init%v dur%v", s3.SPCost, s3.InitSP, s3.Duration)
	}
	if s3.S3AtkRatio != 0.5 || s3.S3EnemyAtk != 0.25 || s3.S3EnemyAspd != 25 || s3.S3MaxDistance != 2 {
		t.Fatalf("离离枯荣 blackboard = %v/%v/%v/%v",
			s3.S3AtkRatio, s3.S3EnemyAtk, s3.S3EnemyAspd, s3.S3MaxDistance)
	}
}

// TestShuInvalidTrainingRejected 边界：非法槽号/未解锁槽/非法潜能必须具名报错。
func TestShuInvalidTrainingRejected(t *testing.T) {
	chdirRepoRootForData(t)

	if _, err := buildShuSourceSpec(&OperatorStats{CharID: shuCharID, Elite: 0, Level: 1, Potential: 1}, 2, 7); err == nil {
		t.Fatal("E0 选 2 技应当报错")
	}
	if _, err := buildShuSourceSpec(&OperatorStats{CharID: shuCharID, Elite: 2, Level: 60, Potential: 1}, 4, 7); err == nil {
		t.Fatal("槽号 4 应当报错")
	}
	if _, err := buildShuSourceSpec(&OperatorStats{CharID: shuCharID, Elite: 2, Level: 60, Potential: 0}, 1, 7); err == nil {
		t.Fatal("潜能 0 应当报错")
	}
	if _, err := buildShuSourceSpec(&OperatorStats{
		CharID: shuCharID, Elite: 1, Level: 60, Potential: 1,
		Module: shuModuleID, ModuleLevel: 1,
	}, 1, 7); err == nil {
		t.Fatal("E1 带模组应当报错（模组需 E2 Lv60）")
	}
}
