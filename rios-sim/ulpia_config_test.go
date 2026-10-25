package main

import (
	"testing"
)

func TestUlpiaAuditAndUnusedKeys(t *testing.T) {
	st := &OperatorStats{
		CharID:    ulpiaCharID,
		Elite:     2,
		Level:     60,
		Potential: 5,
		Module:    ulpiaModule2ID,
		ModuleLevel: 3,
	}
	for slot := 1; slot <= 3; slot++ {
		cfg := ulpiaCfgForTest(t, st, slot, 10)
		if len(cfg.UnusedKeys) != 0 {
			t.Fatalf("slot %d has unused keys: %v", slot, cfg.UnusedKeys)
		}
		if len(cfg.ConsumedKeys) == 0 {
			t.Fatalf("slot %d consumed keys is empty", slot)
		}
	}
}
