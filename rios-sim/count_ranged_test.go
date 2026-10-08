package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func TestCountSakikoSkillRangedProductionAndRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	for ml := 1; ml <= 3; ml++ {
		for _, pot := range []int{1, 4, 5, 6} {
			module := "uniequip_002_oblvns"
			row := DeployRow{Operator: "丰川祥子", Skill: 1, SkillLevel: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: "char_4182_oblvns", Elite: 2, Level: 60, Potential: pot, Module: &module, ModuleLevel: &ml}}
			out, err := buildOperatorOut(row, map[string]int{}, "")
			if err != nil {
				t.Fatal(err)
			}
			raw, err := json.Marshal(out)
			if err != nil {
				t.Fatal(err)
			}
			var op OperatorSpec
			if err = json.Unmarshal(raw, &op); err != nil {
				t.Fatal(err)
			}
			if (op.SkillRangedExemption != nil) != (ml > 1) {
				t.Fatalf("ml%d pot%d exemption missing/spurious", ml, pot)
			}
			if ml > 1 && !validSkillRangedExemption(op.CharID, op.SkillRangedExemption) {
				t.Fatal("JSON source lost")
			}
			requireSemanticGap(t, op.Placeholders, "module.conditional_attack_speed", module)
			if ml > 1 {
				requireSemanticGap(t, op.Placeholders, "module.talent_override", module)
				// A raw caller omitting production gaps must still be refused.
				bare := op
				bare.Placeholders = nil
				spec := deploymentPrimitiveSpec(1)
				spec.Operators = []OperatorSpec{bare}
				requireSemanticGap(t, specMechanismGaps(spec), "module.talent_override", module)
				// An existing other deployment must not suppress this
				// operator's missing exact part1 source.
				other := op
				other.Placeholders = append([]mechanisms.Gap(nil), op.Placeholders...)
				for i := range other.Placeholders {
					other.Placeholders[i].Instance = 9
				}
				spec.Operators = []OperatorSpec{other, bare}
				found := false
				for _, g := range specMechanismGaps(spec) {
					if g.ID == "module.talent_override" && g.Key == "parts[1].addOrOverrideTalentDataBundle.candidates[0]" && g.Instance == 1 {
						found = true
					}
				}
				if !found {
					t.Fatal("other deployment suppressed missing source")
				}
				spec.Operators = []OperatorSpec{bare}
				v, err := runSim(spec)
				var incomplete *mechanisms.IncompleteError
				if v != nil || !errors.As(err, &incomplete) {
					t.Fatal("raw valid source bypassed remaining notes")
				}
			}
			u := &operator{hp: op.MaxHP, spec: op}
			target := countedEnemy(1)
			if u.rangedScaleFor(target) != .8 {
				t.Fatal("inactive base penalty lost")
			}
			u.skillActive = true
			want := .8
			if ml > 1 {
				want = 1
			}
			if u.rangedScaleFor(target) != want {
				t.Fatal("active exemption wrong")
			}
			target.blockedBy = u
			if u.rangedScaleFor(target) != 1 {
				t.Fatal("own block not melee")
			}
			target.blockedBy = &operator{}
			if u.rangedScaleFor(target) != want {
				t.Fatal("other unit block counted as own melee")
			}
			deactivate(u)
			if u.rangedScaleFor(target) != .8 {
				t.Fatal("skill end not restored")
			}
			row.Entry.Module = nil
			row.Entry.ModuleLevel = nil
			plain, err := buildOperatorOut(row, map[string]int{}, "")
			if err != nil || plain.SkillRangedExemption != nil {
				t.Fatal("no-module gained exemption")
			}
			st := &OperatorStats{CharID: op.CharID, Module: module, ModuleLevel: ml, Elite: 2, Level: 59, Potential: pot}
			locked, err := sakikoSkillRangedExemption(st)
			if err != nil || locked != nil {
				t.Fatal("locked exemption")
			}
		}
	}
}

func TestCountSakikoSkillRangedDamageAndSourceGuards(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		st := &OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1}
		rule, err := sakikoSkillRangedExemption(st)
		if err != nil || rule == nil {
			t.Fatal("exact source control missing")
		}
		// Isolated attack witness: no production gaps removed, no count-state default.
		for _, active := range []bool{false, true} {
			for _, block := range []string{"none", "own", "other"} {
				op := hpSpeedUnit()
				op.spec.HPAttackSpeed = nil
				op.spec.CharID = st.CharID
				op.spec.RangedAtkScale = .8
				op.spec.SkillRangedExemption = rule
				op.skillActive = active
				target := countedEnemy(1)
				target.spec.DEF = 30
				if block == "own" {
					target.blockedBy = op
					op.blocking = []*enemy{target}
				}
				if block == "other" {
					target.blockedBy = &operator{}
				}
				v := &Verdict{}
				if err := operatorsAttack([]*operator{op}, []*enemy{target}, 1, 1, &Spec{}, v); err != nil {
					t.Fatal(err)
				}
				want := 50.0
				if active || block == "own" {
					want = 70
				}
				count := 0
				if active && block != "own" {
					count = 1
				}
				if v.SkillRangedExemptions != count {
					t.Fatalf("exemption counter got%d want%d", v.SkillRangedExemptions, count)
				}
				if v.DamageDealt != want || target.hp != 1000-want {
					t.Fatalf("active%v block%s damage%v hp%v want%v", active, block, v.DamageDealt, target.hp, want)
				}
			}
		}
		for _, change := range []func(*SkillRangedExemption){func(r *SkillRangedExemption) { r.ModuleLevel = 1 }, func(r *SkillRangedExemption) { r.ModuleID = "wrong" }, func(r *SkillRangedExemption) { r.Part = json.RawMessage(`{}`) }, func(r *SkillRangedExemption) {
			r.Part = append(json.RawMessage(nil), rule.Part...)
			var p map[string]any
			json.Unmarshal(r.Part, &p)
			p["isToken"] = true
			r.Part, _ = json.Marshal(p)
		}} {
			bad := *rule
			change(&bad)
			if validSkillRangedExemption(st.CharID, &bad) {
				t.Fatal("mutated source accepted")
			}
			op := hpSpeedUnit()
			op.spec.HPAttackSpeed = nil
			op.spec.CharID = st.CharID
			op.spec.RangedAtkScale = .8
			op.spec.SkillRangedExemption = &bad
			op.skillActive = true
			if op.rangedScaleFor(countedEnemy(1)) != .8 {
				t.Fatal("invalid source granted exemption")
			}
			spec := deploymentPrimitiveSpec(1)
			spec.Operators = []OperatorSpec{op.spec}
			requireSemanticGap(t, specMechanismGaps(spec), "runtime.skill_ranged_exemption", "")
			v, err := runSim(spec)
			var incomplete *mechanisms.IncompleteError
			if v != nil || !errors.As(err, &incomplete) {
				t.Fatal("invalid raw source bypassed guard")
			}
		}
		if validSkillRangedExemption("char_4010_etlchi", rule) {
			t.Fatal("wrong owner accepted")
		}
	}
}
