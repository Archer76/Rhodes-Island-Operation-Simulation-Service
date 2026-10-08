package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func TestEntelechiaRemainingTraitNamedGapsIndependentRefusal(t *testing.T) {
	rule := exactEntelechiaHealRule(t)
	gaps := entelechiaRemainingTraitGaps("char_4010_etlchi", "隐德来希", rule.Trait, 7)
	if len(gaps) != 2 {
		t.Fatal("remaining exact sources missing")
	}
	for _, g := range gaps {
		if g.SourceID != "trait:0" || g.Instance != 7 || g.Status != "unimplemented" || g.Description == "" || len(g.RawBlackboard) != 1 || string(g.RawSource) != string(rule.Trait) {
			t.Fatal("remaining source evidence lost")
		}
		// Each new mechanism alone must reject, independent of value/talent/count gaps.
		spec := deploymentPrimitiveSpec(1)
		spec.Placeholders = []mechanisms.Gap{g}
		v, e := runSim(spec)
		var inc *mechanisms.IncompleteError
		if v != nil || !errors.As(e, &inc) {
			t.Fatal("new gap not enforced", g.ID)
		}
	}
	for _, id := range []string{"trait.reaper.group_attack", "trait.reaper.recovery_lifecycle"} {
		requireSemanticGap(t, gaps, id, "trait:0")
	}
	if len(entelechiaRemainingTraitGaps("char_4182_oblvns", "wrong", rule.Trait, 0)) != 0 || len(entelechiaRemainingTraitGaps("char_4010_etlchi", "wrong", json.RawMessage(`{}`), 0)) != 0 {
		t.Fatal("source guard contaminated unrelated traits")
	}
}
func TestEntelechiaRemainingTraitProductionAndRawPreservation(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{0, 1, 2, 3} {
		module := "uniequip_003_etlchi"
		row := DeployRow{Skill: 1, SkillLevel: 7, PlanIdx: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: "char_4010_etlchi", Elite: 2, Level: 60, Potential: 5}}
		if ml > 0 {
			row.Entry.Module = &module
			row.Entry.ModuleLevel = &ml
		}
		out, e := buildOperatorOut(row, map[string]int{}, "")
		if e != nil {
			t.Fatal(e)
		}
		b, e := json.Marshal(out)
		if e != nil {
			t.Fatal(e)
		}
		var op OperatorSpec
		if e = json.Unmarshal(b, &op); e != nil {
			t.Fatal(e)
		}
		spec := deploymentPrimitiveSpec(1)
		spec.Operators = []OperatorSpec{op}
		for _, id := range []string{"trait.reaper.group_attack", "trait.reaper.recovery_lifecycle"} {
			n := 0
			for _, g := range specMechanismGaps(spec) {
				if g.ID == id {
					n++
					if g.Instance != 7 {
						t.Fatal("deployment source identity changed")
					}
				}
			}
			if n != 1 {
				t.Fatal("production source duplicated", id, n)
			}
		}
		// Keeping only the generic value gap cannot suppress named missing mechanisms.
		value := requireSemanticGap(t, op.Placeholders, "trait.blackboard.value", "trait:0")
		op.Placeholders = []mechanisms.Gap{value}
		spec.Operators = []OperatorSpec{op}
		for _, id := range []string{"trait.reaper.group_attack", "trait.reaper.recovery_lifecycle"} {
			g := requireSemanticGap(t, specMechanismGaps(spec), id, "trait:0")
			if g.Instance != 0 {
				t.Fatal("raw synthesized source wrong instance")
			}
		}
		v, e := runSim(spec)
		var inc *mechanisms.IncompleteError
		if v != nil || !errors.As(e, &inc) {
			t.Fatal("partial raw gap inventory bypassed refusal")
		}
	}
}
