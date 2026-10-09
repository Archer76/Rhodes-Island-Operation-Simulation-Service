package main

import (
	"testing"
)

func TestLingSourceSpecExtraction(t *testing.T) {
	chdirRepoRootForData(t)

	// 1. 精2满级 潜能1 技3 专三 无模组
	st := &OperatorStats{
		CharID:    lingCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}
	spec, err := buildLingSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildLingSourceSpec failed: %v", err)
	}
	if spec.TokenKey != lingTokenSoul3 {
		t.Errorf("expected tokenKey %s, got %s", lingTokenSoul3, spec.TokenKey)
	}
	if len(spec.Talents) != 2 {
		t.Errorf("expected 2 talents, got %d", len(spec.Talents))
	}

	// 2. 解码 Config
	cfg, err := decodeLingRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decodeLingRuntimeConfig failed: %v", err)
	}
	if cfg.InventoryMax != 5 {
		t.Errorf("expected InventoryMax 5 without module, got %d", cfg.InventoryMax)
	}
	if cfg.FieldMax != 3 {
		t.Errorf("expected FieldMax 3 without module, got %d", cfg.FieldMax)
	}
	if cfg.S3AtkBuff != 1.0 || cfg.S3DefBuff != 1.0 {
		t.Errorf("expected S3 atk/def buff 1.0, got atk=%v def=%v", cfg.S3AtkBuff, cfg.S3DefBuff)
	}
	if cfg.FusionBlockBonus != 2 {
		t.Errorf("expected FusionBlockBonus +2, got %d", cfg.FusionBlockBonus)
	}
	if cfg.FusionAtkMult != 1.8 {
		t.Errorf("expected FusionAtkMult 1.8, got %v", cfg.FusionAtkMult)
	}

	// 3. 模组 Lv3 测试：持有总数应为 5 + 3 = 8，场上最大部署应为 4，弦惊费用 23 - 5 = 18
	st.Module = lingModuleID
	st.ModuleLevel = 3
	specMod, err := buildLingSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildLingSourceSpec with module failed: %v", err)
	}
	cfgMod, err := decodeLingRuntimeConfig(specMod)
	if err != nil {
		t.Fatalf("decodeLingRuntimeConfig with module failed: %v", err)
	}
	if cfgMod.InventoryMax != 8 {
		t.Errorf("expected InventoryMax 8 with module Lv3, got %d", cfgMod.InventoryMax)
	}
	if cfgMod.FieldMax != 4 {
		t.Errorf("expected FieldMax 4 with module Lv3, got %d", cfgMod.FieldMax)
	}
	if cfgMod.TokenCost != 18 {
		t.Errorf("expected TokenCost 18 with module Lv3 (-5), got %v", cfgMod.TokenCost)
	}
	// 模组 Lv3 弦惊生命加成 +250, 攻击 +60
	if cfgMod.TokenMaxHp != 3607+250 {
		t.Errorf("expected TokenMaxHp %v, got %v", 3607+250, cfgMod.TokenMaxHp)
	}
}

func TestLingSkillsCoverage(t *testing.T) {
	chdirRepoRootForData(t)

	// S1 检查
	st := &OperatorStats{CharID: lingCharID, Elite: 2, Level: 90, Potential: 1}
	spec1, err := buildLingSourceSpec(st, 1, 10)
	if err != nil {
		t.Fatalf("build S1 spec failed: %v", err)
	}
	cfg1, err := decodeLingRuntimeConfig(spec1)
	if err != nil {
		t.Fatalf("decode S1 config failed: %v", err)
	}
	if cfg1.TokenKey != lingTokenSoul1 || cfg1.S1AtkBuff != 0.5 || cfg1.S1ASPD != 50.0 {
		t.Errorf("S1 config mismatch: %+v", cfg1)
	}

	// S2 检查
	spec2, err := buildLingSourceSpec(st, 2, 10)
	if err != nil {
		t.Fatalf("build S2 spec failed: %v", err)
	}
	cfg2, err := decodeLingRuntimeConfig(spec2)
	if err != nil {
		t.Fatalf("decode S2 config failed: %v", err)
	}
	if cfg2.TokenKey != lingTokenSoul2 || cfg2.S2AtkScale != 4.5 || cfg2.S2Duration != 3.0 || cfg2.S2MaxCharges != 2 {
		t.Errorf("S2 config mismatch: %+v", cfg2)
	}
}
