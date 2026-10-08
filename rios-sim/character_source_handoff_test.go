package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func TestCountCharacterProductionLocalConsumersRetainNamedRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	for _, owner := range []struct{ char, module string }{{"char_4182_oblvns", "uniequip_002_oblvns"}, {"char_4010_etlchi", "uniequip_003_etlchi"}} {
		ml := 3
		row := DeployRow{Skill: 1, SkillLevel: 7, PlanIdx: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: owner.char, Elite: 2, Level: 60, Potential: 5, Module: &owner.module, ModuleLevel: &ml}}
		out, e := buildOperatorOut(row, map[string]int{}, "")
		if e != nil {
			t.Fatal(e)
		}
		blob, e := json.Marshal(out)
		if e != nil {
			t.Fatal(e)
		}
		var specOp OperatorSpec
		if e = json.Unmarshal(blob, &specOp); e != nil {
			t.Fatal(e)
		}
		op := selfHealUnit(100)
		op.spec = specOp
		op.spec.MaxHP = 1000
		op.skillActive = true
		target := countedEnemy(1)
		target.rebornAt = -1
		if owner.char == "char_4010_etlchi" {
			v := &Verdict{}
			if got, e := op.consumeEntelechiaDOTPulse(1, target, v); e != nil || got != 500 || target.hp != 500 {
				t.Fatal("production selected source failed actual damage", got, e)
			}
			if got, e := op.consumeEntelechiaRecoveryPulse(2, true, v); e != nil || got != 35 || op.hp != 135 {
				t.Fatal("production selected source failed own recovery", got, e)
			}
		} else {
			if op.rangedScaleFor(target) != 1 {
				t.Fatal("production ranged source lost active exemption")
			}
			op.skillActive = false
			if op.rangedScaleFor(target) != .8 {
				t.Fatal("production ranged source lost expiry control")
			}
		}
		spec := deploymentPrimitiveSpec(1)
		spec.Operators = []OperatorSpec{specOp}
		v, e := runSim(spec)
		var inc *mechanisms.IncompleteError
		if v != nil || !errors.As(e, &inc) {
			t.Fatal("partial consumers authorized full character")
		}
		candidates := map[string]bool{}
		for _, g := range inc.Placeholders {
			if g.ID == "module.talent_override" && g.CharID == owner.char && g.SourceID == owner.module && g.Level == 3 && g.Slot == 1 {
				if g.Instance != 7 || len(g.RawSource) == 0 || len(g.RawSlot) == 0 {
					t.Fatal("named source identity/provenance lost")
				}
				if candidates[g.Key] {
					t.Fatal("PlanIdx runtime duplicate")
				}
				candidates[g.Key] = true
			}
		}
		n := 1
		if owner.char == "char_4010_etlchi" {
			n = 2
		}
		if len(candidates) != n || !candidates["parts[1].addOrOverrideTalentDataBundle.candidates[0]"] {
			t.Fatal("eligible inventory missing from actual refusal", candidates)
		}
		if n == 2 && !candidates["parts[1].addOrOverrideTalentDataBundle.candidates[1]"] {
			t.Fatal("selected upgrade missing from refusal")
		}
	}
}
