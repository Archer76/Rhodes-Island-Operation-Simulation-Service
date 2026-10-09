package main

import (
	"testing"
)

func TestWisdelConfigDecodeS1(t *testing.T) {
	st := &OperatorStats{
		CharID:    wisdelCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}
	spec, err := buildWisdelSourceSpec(st, 1, 10)
	if err != nil {
		t.Fatalf("build spec failed: %v", err)
	}
	cfg, err := decodeWisdelRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decode config failed: %v", err)
	}
	if cfg.Slot != 1 {
		t.Fatalf("expected slot 1, got %d", cfg.Slot)
	}
	if cfg.S1AppendAtkScale != 1.2 {
		t.Fatalf("expected S1AppendAtkScale 1.2, got %v", cfg.S1AppendAtkScale)
	}
	if cfg.S1StunDuration != 1.5 {
		t.Fatalf("expected S1StunDuration 1.5, got %v", cfg.S1StunDuration)
	}
	if cfg.TalentMainAtkScale != 1.15 {
		t.Fatalf("expected TalentMainAtkScale 1.15 at E2, got %v", cfg.TalentMainAtkScale)
	}
	if cfg.TalentBombAtkScale != 1.5 {
		t.Fatalf("expected TalentBombAtkScale 1.5 at E2 Pot1, got %v", cfg.TalentBombAtkScale)
	}
	if cfg.TalentBombStun != 1.0 {
		t.Fatalf("expected TalentBombStun 1.0, got %v", cfg.TalentBombStun)
	}
}

func TestWisdelConfigDecodeS2(t *testing.T) {
	st := &OperatorStats{
		CharID:    wisdelCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}
	spec, err := buildWisdelSourceSpec(st, 2, 10)
	if err != nil {
		t.Fatalf("build spec failed: %v", err)
	}
	cfg, err := decodeWisdelRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decode config failed: %v", err)
	}
	if cfg.Slot != 2 {
		t.Fatalf("expected slot 2, got %d", cfg.Slot)
	}
	if cfg.S2Atk != 0.35 {
		t.Fatalf("expected S2Atk 0.35, got %v", cfg.S2Atk)
	}
	if cfg.S2BaseAttackTime != -0.7 {
		t.Fatalf("expected S2BaseAttackTime -0.7, got %v", cfg.S2BaseAttackTime)
	}
	if cfg.S2AtkScaleOl != 0.8 {
		t.Fatalf("expected S2AtkScaleOl 0.8, got %v", cfg.S2AtkScaleOl)
	}
}

func TestWisdelConfigDecodeS3AndModule(t *testing.T) {
	st := &OperatorStats{
		CharID:      wisdelCharID,
		Elite:       2,
		Level:       90,
		Potential:   5, // Pot 5 (+10% bomb scale)
		Module:      wisdelModuleID,
		ModuleLevel: 3,
	}
	spec, err := buildWisdelSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("build spec failed: %v", err)
	}
	cfg, err := decodeWisdelRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decode config failed: %v", err)
	}
	if cfg.Slot != 3 {
		t.Fatalf("expected slot 3, got %d", cfg.Slot)
	}
	if cfg.S3Atk != 1.8 {
		t.Fatalf("expected S3Atk 1.8, got %v", cfg.S3Atk)
	}
	if cfg.S3AtkScale3 != 2.2 {
		t.Fatalf("expected S3AtkScale3 2.2, got %v", cfg.S3AtkScale3)
	}
	if cfg.S3Prob != 1.0 {
		t.Fatalf("expected S3Prob 1.0, got %v", cfg.S3Prob)
	}
	if cfg.S3TriggerTime != 6 {
		t.Fatalf("expected S3TriggerTime 6, got %v", cfg.S3TriggerTime)
	}
	if cfg.S3BaseAttackTime != 2.9 {
		t.Fatalf("expected S3BaseAttackTime 2.9, got %v", cfg.S3BaseAttackTime)
	}
	if cfg.S3MaxCnt != 2 {
		t.Fatalf("expected S3MaxCnt 2, got %v", cfg.S3MaxCnt)
	}

	// Module Lv3 + Pot 5 checks
	if !cfg.EnableThirdAttack {
		t.Fatalf("expected EnableThirdAttack true with module")
	}
	if cfg.TalentMainAtkScale != 1.25 {
		t.Fatalf("expected TalentMainAtkScale 1.25 at Mod3, got %v", cfg.TalentMainAtkScale)
	}
	if cfg.TalentBombAtkScale != 1.85 {
		t.Fatalf("expected TalentBombAtkScale 1.85 at Mod3 Pot5, got %v", cfg.TalentBombAtkScale)
	}

	// Token skill checks
	if cfg.WardSluggish != 1.0 {
		t.Fatalf("expected WardSluggish 1.0, got %v", cfg.WardSluggish)
	}
	if cfg.WardSpMax != 3.0 {
		t.Fatalf("expected WardSpMax 3.0, got %v", cfg.WardSpMax)
	}
}
