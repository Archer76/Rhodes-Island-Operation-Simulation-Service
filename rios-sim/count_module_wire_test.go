package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func TestCountModuleSelectedSourceProductionAndRawGuards(t *testing.T) {
	chdirRepoRootForData(t)
	for _, owner := range []struct{ char, module string }{{"char_4182_oblvns", "uniequip_002_oblvns"}, {"char_4010_etlchi", "uniequip_003_etlchi"}} {
		for _, ml := range []int{2, 3} {
			for _, pot := range []int{1, 4, 5, 6} {
				row := DeployRow{Skill: 1, SkillLevel: 7, PlanIdx: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: owner.char, Elite: 2, Level: 60, Potential: pot, Module: &owner.module, ModuleLevel: &ml}}
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
				if op.ExactModuleTalent == nil {
					t.Fatal("selected source not sent")
				}
				ci := 0
				if owner.char == "char_4010_etlchi" && pot >= 5 {
					ci = 1
				}
				if op.ExactModuleTalent.CandidateIndex != ci {
					t.Fatal("wrong production selection")
				}
				if len(exactModuleTalentGaps(op, 0)) != 0 {
					t.Fatal("production source identity lost or duplicated")
				}
				// Isolate the new raw selected-source channel from all other known gaps.
				op.Placeholders = nil
				op.SkillRangedExemption = nil
				op.FriendlyHealRestriction = nil
				gaps := exactModuleTalentGaps(op, 0)
				if len(gaps) != 1 || gaps[0].ID != "module.talent_override" || gaps[0].Instance != 0 || len(gaps[0].RawSlot) == 0 {
					t.Fatal("raw selected source bypassed missing effect")
				}
				spec := deploymentPrimitiveSpec(1)
				spec.Operators = []OperatorSpec{op}
				v, e := runSim(spec)
				var inc *mechanisms.IncompleteError
				if v != nil || !errors.As(e, &inc) {
					t.Fatal("valid raw selected source allowed verdict")
				}
				for _, mutate := range []func(*ExactModuleTalent){func(r *ExactModuleTalent) { r.CandidateIndex = 9 }, func(r *ExactModuleTalent) { r.UpgradeDescription = "altered" }, func(r *ExactModuleTalent) { r.Blackboard = map[string]any{} }, func(r *ExactModuleTalent) { r.Potential = 0 }} {
					bad := *op.ExactModuleTalent
					mutate(&bad)
					changed := op
					changed.ExactModuleTalent = &bad
					g := exactModuleTalentGaps(changed, 0)
					if len(g) != 1 || g[0].ID != "runtime.exact_module_talent" {
						t.Fatal("mutated selected source accepted")
					}
					spec.Operators = []OperatorSpec{changed}
					v, e = runSim(spec)
					if v != nil || !errors.As(e, &inc) {
						t.Fatal("mutated raw source produced verdict")
					}
				}
			}
		}
	}
	st := &OperatorStats{CharID: "wrong", Module: "unknown-no-load", ModuleLevel: 2, Elite: 2, Level: 60, Potential: 1}
	if r, e := resolveExactCountModuleTalent(st); r != nil || e != nil {
		t.Fatal("unrelated owner loaded module")
	}
}
