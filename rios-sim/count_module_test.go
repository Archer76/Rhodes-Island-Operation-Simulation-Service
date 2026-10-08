package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func TestCountModuleProductionExactContextAndRemainingGaps(t *testing.T) {
	chdirRepoRootForData(t)
	for _, id := range []struct{ char, name, module, scope string }{{"char_4182_oblvns", "丰川祥子", "uniequip_002_oblvns", "base"}, {"char_4010_etlchi", "隐德来希", "uniequip_003_etlchi", "current"}} {
		for ml := 1; ml <= 3; ml++ {
			st := &OperatorStats{CharID: id.char, Elite: 2, Level: 60, Potential: 1, Module: id.module, ModuleLevel: ml}
			rule, err := countModuleSpeed(st)
			if err != nil || rule == nil || rule.Scope != id.scope || rule.Minimum != 2 || rule.Bonus != 12 {
				t.Fatalf("source bind %s %d %v", id.module, ml, err)
			}
			st.Level = 59
			locked, err := countModuleSpeed(st)
			if err != nil || locked != nil {
				t.Fatal("locked module bound")
			}
			row := DeployRow{Operator: id.name, Skill: 1, SkillLevel: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: id.char, Elite: 2, Level: 60, Potential: 1, Module: &id.module, ModuleLevel: &ml}}
			out, err := buildOperatorOut(row, map[string]int{}, "")
			if err != nil {
				t.Fatal(err)
			}
			blob, err := json.Marshal(out)
			if err != nil {
				t.Fatal(err)
			}
			var op OperatorSpec
			if err := json.Unmarshal(blob, &op); err != nil {
				t.Fatal(err)
			}
			if op.EnemyCountAttackSpeed == nil || !validAttackTiming(op.AttackTiming) || !validAttackTiming(op.Active.AttackTiming) {
				t.Fatal("production count timing missing")
			}
			// Independent selected-stat calculation gives old contribution; remove ONLY12.
			calculated, err := (&buildInputs{}).operatorStats(OperatorCalcConfig{CharID: id.char, Elite: 2, Level: 60, Potential: 1, Module: id.module, ModuleLevel: ml})
			if err != nil {
				t.Fatal(err)
			}
			aspd, err := totalOrDef(calculated.Total, "attackSpeed", 100)
			if err != nil {
				t.Fatal(err)
			}
			if op.AttackTiming.ASPD != aspd+calculated.AttackSpeedBonus.Flat-12 {
				t.Fatal("old condition not stripped exactly once")
			}
			// Module attributes are independent of the conditional +12. Check the
			// actual selected producer against no-module rather than old Flat only.
			plainRow := row
			plainRow.Entry.Module = nil
			plainRow.Entry.ModuleLevel = nil
			plainOut, err := buildOperatorOut(plainRow, map[string]int{}, "")
			if err != nil {
				t.Fatal(err)
			}
			plainRaw, err := json.Marshal(plainOut)
			if err != nil {
				t.Fatal(err)
			}
			var plainOp OperatorSpec
			if err := json.Unmarshal(plainRaw, &plainOp); err != nil {
				t.Fatal(err)
			}
			if plainOp.EnemyCountAttackSpeed != nil {
				t.Fatal("no module gained count rule")
			}
			plainStats, err := (&buildInputs{}).operatorStats(OperatorCalcConfig{CharID: id.char, Elite: 2, Level: 60, Potential: 1})
			if err != nil {
				t.Fatal(err)
			}
			plainASPD, err := totalOrDef(plainStats.Total, "attackSpeed", 100)
			if err != nil {
				t.Fatal(err)
			}
			if aspd-plainASPD != float64(ml+4) || op.AttackTiming.ASPD != plainASPD+plainStats.AttackSpeedBonus.Flat+float64(ml+4) {
				t.Fatalf("static module ASPD %d not preserved: base%v module%v", ml+4, plainASPD, op.AttackTiming)
			}
			inputs := &buildInputs{}
			skillID, _, err := selectedSkillID(id.char, row.Skill)
			if err != nil {
				t.Fatal(err)
			}
			meta, err := inputs.skillMeta(skillID, row.SkillLevel)
			if err != nil {
				t.Fatal(err)
			}
			mods, _ := ApplyBlackboard(meta.Blackboard)
			wantBAT := op.AttackTiming.BaseAttackTime
			if mods.BaseAttackTime > 0 {
				wantBAT = mods.BaseAttackTime
			}
			if op.Active.AttackTiming.BaseAttackTime != wantBAT || op.Active.AttackTiming.ASPD != op.AttackTiming.ASPD+mods.AttackSpeed || op.Active.Interval != timingInterval(op.Active.AttackTiming, 0) {
				t.Fatal("active raw context dropped/double-counted module or skill ASPD")
			}
			requireSemanticGap(t, op.Placeholders, "module.conditional_attack_speed", id.module)
			if ml > 1 {
				requireSemanticGap(t, op.Placeholders, "module.talent_override", id.module)
			}
			spec := deploymentPrimitiveSpec(1)
			spec.Operators = []OperatorSpec{op}
			v, err := runSim(spec)
			var incomplete *mechanisms.IncompleteError
			if v != nil || !errors.As(err, &incomplete) {
				t.Fatal("partial source/unknown enemy bypassed")
			}
			// Isolated interval witness, NOT a full run with production gaps deleted.
			a := countedEnemy(float64(op.Range[0][0]))
			a.position[1] = float64(op.Range[0][1])
			b := countedEnemy(a.position[0])
			b.position[1] = a.position[1]
			unit := &operator{hp: op.MaxHP, spec: op}
			got, err := unit.intervalForEnemies([]*enemy{a, b})
			if err != nil || got != timingInterval(op.AttackTiming, 12) {
				t.Fatal("real producer context not consumed")
			}
			b.spec.CountVisibility.Hidden = true
			got, err = unit.intervalForEnemies([]*enemy{a, b})
			if err != nil || got != timingInterval(op.AttackTiming, 0) {
				t.Fatal("real context counted hidden")
			}
			unit.skillActive = true
			got, err = unit.intervalForEnemies([]*enemy{a, b})
			if err != nil || got != timingInterval(op.Active.AttackTiming, 0) {
				t.Fatal("active producer context hidden control wrong")
			}
			// Use two verified current cells (base scope for Sakiko), not cached base
			// geometry for every source. This is an interval witness, not gap removal.
			cells := unit.targetRange()
			if op.EnemyCountAttackSpeed.Scope == "base" {
				cells = op.Range
			}
			if len(cells) == 0 {
				t.Fatal("real active witness missing range")
			}
			a.position = [2]float64{float64(cells[0][0]), float64(cells[0][1])}
			b.position = a.position
			b.spec.CountVisibility.Hidden = false
			got, err = unit.intervalForEnemies([]*enemy{a, b})
			if err != nil || got != timingInterval(op.Active.AttackTiming, 12) {
				t.Fatal("active producer raw numeric bonus missing/doubled")
			}
			unit.skillActive = false
		}
	}
}
func TestCountCharacterModuleUpgradeSourcesRemainRefused(t *testing.T) {
	chdirRepoRootForData(t)
	for _, owner := range []struct{ char, module string }{{"char_4182_oblvns", "uniequip_002_oblvns"}, {"char_4010_etlchi", "uniequip_003_etlchi"}} {
		for ml := 1; ml <= 3; ml++ {
			for _, pot := range []int{1, 5} {
				st := &OperatorStats{CharID: owner.char, Module: owner.module, ModuleLevel: ml, Elite: 2, Level: 60, Potential: pot}
				gaps, err := countCharacterModuleGaps(st)
				if err != nil {
					t.Fatal(err)
				}
				want := 0
				if ml > 1 {
					want = 2
					if owner.char == "char_4010_etlchi" && pot == 1 {
						want = 1
					}
				}
				if len(gaps) != want {
					t.Fatalf("%s level%d pot%d got%d want%d", owner.module, ml, pot, len(gaps), want)
				}
				for _, g := range gaps {
					if g.ID != "module.talent_override" || g.SourceID != owner.module || g.CharID != owner.char || g.Level != ml || g.Slot < 1 || len(g.RawSlot) == 0 || len(g.RawSource) == 0 {
						t.Fatalf("lost module source: %+v", g)
					}
				}
				if ml > 1 {
					// Production overwrites Instance with the deployment index. Candidate
					// identity must survive that overwrite and every downstream Merge.
					for i := range gaps {
						gaps[i].Instance = 7
					}
					if len(mechanisms.Merge(gaps)) != want {
						t.Fatal("candidate identity collapsed at deployment")
					}
					row := DeployRow{Skill: 1, SkillLevel: 7, PlanIdx: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: owner.char, Elite: 2, Level: 60, Potential: pot, Module: &owner.module, ModuleLevel: &ml}}
					out, err := buildOperatorOut(row, map[string]int{}, "")
					if err != nil {
						t.Fatal(err)
					}
					blob, err := json.Marshal(out)
					if err != nil {
						t.Fatal(err)
					}
					var op OperatorSpec
					if err := json.Unmarshal(blob, &op); err != nil {
						t.Fatal(err)
					}
					produced := deploymentPrimitiveSpec(1)
					produced.Operators = []OperatorSpec{op}
					var final []mechanisms.Gap
					for _, g := range specMechanismGaps(produced) {
						if g.ID == "module.talent_override" {
							final = append(final, g)
						}
					}
					if len(final) != want {
						t.Fatalf("production lost candidates: got%d want%d", len(final), want)
					}
					if owner.char == "char_4182_oblvns" {
						if len(gaps[0].RawBlackboard) != 5 || gaps[0].Description == "" || len(gaps[1].RawBlackboard) != 0 {
							t.Fatal("upgrade description or empty hidden prefab lost")
						}
					} else if len(gaps[0].RawBlackboard) != 6 || gaps[0].Description == "" {
						t.Fatal("steal/DoT/regen module payload lost")
					}
					// Prove the new guard alone rejects, independent of the old
					// count-rule/trait/talent gaps that already reject these people.
					spec := deploymentPrimitiveSpec(1)
					spec.Placeholders = gaps
					v, err := runSim(spec)
					var incomplete *mechanisms.IncompleteError
					if v != nil || !errors.As(err, &incomplete) {
						t.Fatal("module override guard not enforced")
					}
				}
				st.Level = 59
				locked, err := countCharacterModuleGaps(st)
				if err != nil || len(locked) != 0 {
					t.Fatal("locked upgrade included")
				}
				st.Level = 60
				st.Module = ""
				st.ModuleLevel = 0
				plain, err := countCharacterModuleGaps(st)
				if err != nil || len(plain) != 0 {
					t.Fatal("no module contaminated")
				}
				st.Module = owner.module
				st.ModuleLevel = ml
				st.CharID = "wrong"
				wrong, err := countCharacterModuleGaps(st)
				if err != nil || len(wrong) != 0 {
					t.Fatal("wrong owner contaminated")
				}
			}
		}
	}
}

func TestCountModuleSourceMutationsRefused(t *testing.T) {
	chdirRepoRootForData(t)
	st := &OperatorStats{CharID: "char_4010_etlchi", Elite: 2, Level: 60, Potential: 1, Module: "uniequip_003_etlchi", ModuleLevel: 1}
	parts, err := moduleParts(st.Module, 1)
	if err != nil {
		t.Fatal(err)
	}
	var p struct {
		Bundle struct {
			Candidates []moduleSpeedCandidate `json:"candidates"`
		} `json:"overrideTraitDataBundle"`
	}
	if err := json.Unmarshal(parts[0], &p); err != nil {
		t.Fatal(err)
	}
	orig := p.Bundle.Candidates[0]
	for _, change := range []func(*moduleSpeedCandidate){func(c *moduleSpeedCandidate) { c.Blackboard = c.Blackboard[:2] }, func(c *moduleSpeedCandidate) {
		c.Blackboard = []json.RawMessage{c.Blackboard[0], c.Blackboard[0], c.Blackboard[2]}
	}, func(c *moduleSpeedCandidate) {
		s := "攻击范围内存在3名及以上敌人时攻击速度+{attack_speed}"
		c.AdditionalDescription = &s
	}, func(c *moduleSpeedCandidate) { c.RequiredPotentialRank = 1 }} {
		c := orig
		change(&c)
		if exactCountModuleCandidate(st, 0, 0, parts[0], c) {
			t.Fatal("changed source bound")
		}
	}
	if exactCountModuleCandidate(st, 1, 0, parts[0], orig) || exactCountModuleCandidate(st, 0, 1, parts[0], orig) {
		t.Fatal("wrong source position bound")
	}
	st.CharID = "wrong"
	if exactCountModuleCandidate(st, 0, 0, parts[0], orig) {
		t.Fatal("wrong owner bound")
	}
}
