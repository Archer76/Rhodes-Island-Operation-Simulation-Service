package main

import (
	"testing"
)

func TestChen3ConfigDecoding(t *testing.T) {
	st := &OperatorStats{
		CharID:      chen3CharID,
		Elite:       2,
		Level:       90,
		Potential:   5, // 天赋增强
		Module:      chen3ModuleID,
		ModuleLevel: 3,
	}

	// 技1 M3
	s1, err := buildChen3SourceSpec(st, 1, 10)
	if err != nil {
		t.Fatalf("build S1 failed: %v", err)
	}
	cfg1, err := decodeChen3RuntimeConfig(s1)
	if err != nil {
		t.Fatalf("decode S1 config failed: %v", err)
	}
	if cfg1.S1AtkScale != 1.2 {
		t.Fatalf("expected S1 atk 1.2, got %v", cfg1.S1AtkScale)
	}
	if cfg1.Talent1Atk != 0.16 || cfg1.Talent1ASPD != 16.0 {
		t.Fatalf("expected Talent1 enhanced (16%%, 16), got atk %v aspd %v", cfg1.Talent1Atk, cfg1.Talent1ASPD)
	}
	if cfg1.Talent2Interval != 6.0 {
		t.Fatalf("expected Talent2 mod interval 6.0, got %v", cfg1.Talent2Interval)
	}
	if cfg1.ModuleUnblockedASPD != 8.0 {
		t.Fatalf("expected module unblocked aspd 8.0, got %v", cfg1.ModuleUnblockedASPD)
	}

	// 技2 M3
	s2, err := buildChen3SourceSpec(st, 2, 10)
	if err != nil {
		t.Fatalf("build S2 failed: %v", err)
	}
	cfg2, err := decodeChen3RuntimeConfig(s2)
	if err != nil {
		t.Fatalf("decode S2 config failed: %v", err)
	}
	if cfg2.S2AtkScale != 4.8 || cfg2.S2RespawnAtk != 3.0 || cfg2.S2RespawnProb != 0.6 {
		t.Fatalf("unexpected S2 config: %+v", cfg2)
	}

	// 技3 M3
	s3, err := buildChen3SourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("build S3 failed: %v", err)
	}
	cfg3, err := decodeChen3RuntimeConfig(s3)
	if err != nil {
		t.Fatalf("decode S3 config failed: %v", err)
	}
	if cfg3.S3AtkScale != 2.1 || cfg3.S3MaxTarget != 4 || cfg3.S3HPRatio != 0.06 || cfg3.S3ProjectileMinAtkScale != 5.8 {
		t.Fatalf("unexpected S3 config: %+v", cfg3)
	}
}
