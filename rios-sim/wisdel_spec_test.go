package main

import (
	"encoding/json"
	"testing"
)

func TestWisdelSourceTrainingSlotsAndRawEvidence(t *testing.T) {
	for elite := 0; elite <= 2; elite++ {
		for pot := 1; pot <= 6; pot++ {
			maxSlot := elite + 1
			for slot := 1; slot <= maxSlot; slot++ {
				maxLvl := 7
				if elite == 2 {
					maxLvl = 10
				}
				for sl := 1; sl <= maxLvl; sl++ {
					st := &OperatorStats{
						CharID:    wisdelCharID,
						Elite:     elite,
						Level:     60,
						Potential: pot,
					}
					spec, err := buildWisdelSourceSpec(st, slot, sl)
					if err != nil {
						t.Fatalf("E%dP%dS%dL%d buildWisdelSourceSpec failed: %v", elite, pot, slot, sl, err)
					}
					if spec == nil {
						t.Fatalf("E%dP%dS%dL%d returned nil spec", elite, pot, slot, sl)
					}
					if len(spec.Evidence) == 0 {
						t.Fatalf("E%dP%dS%dL%d empty evidence", elite, pot, slot, sl)
					}
					blob, err := json.Marshal(spec)
					if err != nil {
						t.Fatalf("marshal failed: %v", err)
					}
					var decoded WisdelSourceSpec
					if err := json.Unmarshal(blob, &decoded); err != nil {
						t.Fatalf("unmarshal failed: %v", err)
					}
				}
			}
		}
	}
}

func TestWisdelInvalidSlotOrTraining(t *testing.T) {
	st := &OperatorStats{CharID: "char_unknown", Elite: 2, Level: 90, Potential: 1}
	s, err := buildWisdelSourceSpec(st, 1, 7)
	if err != nil || s != nil {
		t.Fatalf("expected nil for non-wisdel, got %v, %v", s, err)
	}

	st = &OperatorStats{CharID: wisdelCharID, Elite: 0, Level: 1, Potential: 1}
	_, err = buildWisdelSourceSpec(st, 2, 7)
	if err == nil {
		t.Fatalf("expected error for locked slot 2 at E0")
	}
}

func TestWisdelModuleEvidence(t *testing.T) {
	st := &OperatorStats{
		CharID:      wisdelCharID,
		Elite:       2,
		Level:       90,
		Potential:   1,
		Module:      wisdelModuleID,
		ModuleLevel: 3,
	}
	spec, err := buildWisdelSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildWisdelSourceSpec with module failed: %v", err)
	}
	if spec.Module == nil {
		t.Fatalf("expected module spec, got nil")
	}
	if len(spec.ModuleCandidates) == 0 {
		t.Fatalf("expected module candidates, got empty")
	}
}
