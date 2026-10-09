package main

import (
	"encoding/json"
	"testing"
)

func TestChen3SourceTrainingSlotsAndRawEvidence(t *testing.T) {
	for _, elite := range []int{0, 1, 2} {
		for _, pot := range []int{1, 3, 5, 6} {
			for _, slot := range []int{1, 2, 3} {
				if slot > elite+1 {
					continue
				}
				for _, sl := range []int{1, 7, 10} {
					st := &OperatorStats{
						CharID:    chen3CharID,
						Elite:     elite,
						Level:     60,
						Potential: pot,
					}
					spec, err := buildChen3SourceSpec(st, slot, sl)
					if err != nil {
						t.Fatalf("E%dP%dS%dL%d buildChen3SourceSpec failed: %v", elite, pot, slot, sl, err)
					}
					if spec.Slot != slot || spec.SkillLevel != sl || spec.Elite != elite || spec.Potential != pot {
						t.Fatalf("spec metadata mismatch: %+v", spec)
					}
					if len(spec.Evidence) == 0 {
						t.Fatalf("missing evidence in spec")
					}
					if spec.OperatorSkill.ID == "" {
						t.Fatalf("missing operator skill ID")
					}
					// JSON roundtrip test
					blob, err := json.Marshal(spec)
					if err != nil {
						t.Fatalf("marshal failed: %v", err)
					}
					var decoded Chen3SourceSpec
					if err := json.Unmarshal(blob, &decoded); err != nil {
						t.Fatalf("unmarshal failed: %v", err)
					}
					if decoded.Slot != spec.Slot || decoded.SkillLevel != spec.SkillLevel {
						t.Fatalf("decoded spec mismatch")
					}
				}
			}
		}
	}
}

func TestChen3NonChenRejected(t *testing.T) {
	st := &OperatorStats{CharID: "char_002_amiya"}
	s, err := buildChen3SourceSpec(st, 1, 7)
	if err != nil || s != nil {
		t.Fatalf("expected nil for non-chen3, got %v, %v", s, err)
	}
}

func TestChen3SlotLockedRejected(t *testing.T) {
	st := &OperatorStats{CharID: chen3CharID, Elite: 0, Level: 1, Potential: 1}
	_, err := buildChen3SourceSpec(st, 2, 7)
	if err == nil {
		t.Fatalf("expected error for slot 2 at E0")
	}
}

func TestChen3ModuleEvidence(t *testing.T) {
	st := &OperatorStats{
		CharID:      chen3CharID,
		Elite:       2,
		Level:       90,
		Potential:   1,
		Module:      chen3ModuleID,
		ModuleLevel: 3,
	}
	spec, err := buildChen3SourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildChen3SourceSpec with module failed: %v", err)
	}
	if spec.Module == nil || spec.Module.Level != 3 {
		t.Fatalf("expected module level 3, got %+v", spec.Module)
	}
}
