package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"strings"
	"testing"
)

func TestSkillRangeExactSourcesAndBinding(t *testing.T) {
	chdirRepoRootForData(t)
	for _, c := range []struct {
		char, id, code string
		n              int
	}{{"char_284_spot", "skchr_spot_1", "x-4", 7}, {"char_1014_nearl2", "skchr_nearl2_1", "2-2", 10}} {
		for level := 1; level <= c.n; level++ {
			meta, err := SkillMetaFor(c.id, level)
			if err != nil {
				t.Fatal(err)
			}
			code, ok := exactSkillTargetRange(*meta)
			if !ok || code != c.code {
				t.Fatalf("source %s/%d not consumed %+v", c.id, level, meta)
			}
			gaps := skillMechanismGaps(*meta, c.char, c.char, 1, "base")
			if len(gaps) != 0 {
				t.Fatalf("complete skill blocked %+v", gaps)
			}
			for _, dir := range []string{"Right", "Up", "Left", "Down"} {
				row := DeployRow{Skill: 1, SkillLevel: level, Direction: dir, Position: [2]int{10, 20}, Entry: LoadoutEntry{CharID: c.char, Level: 1, Potential: 1}}
				if level > 7 {
					row.Mastery = level - 7
					row.Entry.Elite = 2
				}
				scope, err := bindSkillTargetRange(row, nil)
				if err != nil || scope == nil {
					t.Fatalf("binding lost %s %v", c.id, err)
				}
				var expected [][2]int
				if c.id == "skchr_nearl2_1" {
					expected = map[string][][2]int{"Right": {{10, 20}, {11, 20}, {12, 20}}, "Up": {{10, 20}, {10, 19}, {10, 18}}, "Left": {{10, 20}, {9, 20}, {8, 20}}, "Down": {{10, 20}, {10, 21}, {10, 22}}}[dir]
				} else {
					for x := 9; x <= 11; x++ {
						for y := 19; y <= 21; y++ {
							expected = append(expected, [2]int{x, y})
						}
					}
				}
				if len(scope.Cells) != len(expected) {
					t.Fatal("wrong full footprint size")
				}
				for _, cell := range expected {
					if !inCells(scope.Cells, cell) {
						t.Fatalf("missing exact cell %v in %v", cell, scope.Cells)
					}
				}
				if c.id == "skchr_nearl2_1" {
					terminal := map[string][2]int{"Right": {12, 20}, "Up": {10, 18}, "Left": {8, 20}, "Down": {10, 22}}[dir]
					if len(scope.Cells) != 3 || !inCells(scope.Cells, terminal) {
						t.Fatalf("orientation %s %+v", dir, scope.Cells)
					}
				} else if len(scope.Cells) != 9 || !inCells(scope.Cells, [2]int{9, 19}) || !inCells(scope.Cells, [2]int{11, 21}) {
					t.Fatalf("spot exact geometry %+v", scope.Cells)
				}
			}
		}
	}
	for _, id := range []string{"skchr_fmout_2", "skchr_ling_1", "skchr_amgoat_3"} {
		meta, err := SkillMetaFor(id, 7)
		if err != nil {
			t.Fatal(err)
		}
		if _, ok := exactSkillTargetRange(*meta); ok {
			t.Fatalf("other purpose claimed %s", id)
		}
		gapID := "skill.range_override"
		if id == "skchr_ling_1" {
			gapID = "skill.summon_entity"
		}
		requireSemanticGap(t, skillMechanismGaps(*meta, "x", "x", 1, "base"), gapID, id)
	}
}

func TestSkillRangeProductionHealingAndUnsupported(t *testing.T) {
	chdirRepoRootForData(t)
	roster := writeTempRoster(t, `[{"name":"斑点","charId":"char_284_spot","elite":0,"level":40,"potential":1}]`)
	plan := json.RawMessage(`{"stage":"main_01-07","deploys":[{"operator":"斑点","position":[3,5],"direction":"Up","skill":1}]}`)
	built, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	blob, err := json.Marshal(built.Spec)
	if err != nil {
		t.Fatal(err)
	}
	var spec Spec
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	if len(spec.Placeholders) != 0 || spec.Operators[0].Active.TargetRange == nil || !spec.Operators[0].HealsOnSkill {
		t.Fatalf("production consumer blocked %+v", spec.Placeholders)
	}
	// Genuine built operator (no gaps removed) exercises a friend only in active scope.
	op := &operator{hp: spec.Operators[0].MaxHP, spec: spec.Operators[0], cell: [2]float64{3, 5}, sp: 40}
	ally := &operator{hp: 100, cell: [2]float64{4, 5}, spec: OperatorSpec{Name: "ally", MaxHP: 1000}}
	if len(pickHeals(op, []*operator{ally}, 1)) != 0 {
		t.Fatal("base healed outside base scope")
	}
	cost := 0.0
	v := &Verdict{}
	activate(op, 0, &spec, &cost, v, false)
	operatorsAttack([]*operator{op, ally}, nil, 10, 10, &spec, v)
	if ally.hp <= 100 {
		t.Fatal("real active range did not produce healing")
	}
	t.Logf("real spot active-only ally actualHP=%g", ally.hp-100)
	deactivate(op)
	if len(pickHeals(op, []*operator{ally}, 1)) != 0 {
		t.Fatal("expired range persisted")
	}
	roster = writeTempRoster(t, `[{"name":"远山","charId":"char_109_fmout","elite":1,"level":1,"potential":1}]`)
	plan = json.RawMessage(`{"stage":"main_01-07","deploys":[{"operator":"远山","position":[3,5],"direction":"Up","skill":2}]}`)
	built, err = BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	blob, err = json.Marshal(built.Spec)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	requireSemanticGap(t, spec.Placeholders, "skill.range_override", "skchr_fmout_2")
	verdict, err := runSim(&spec)
	var incomplete *mechanisms.IncompleteError
	if verdict != nil || !errors.As(err, &incomplete) {
		t.Fatalf("unfinished range produced verdict %v/%v", verdict, err)
	}
}

func TestSkillRangeInfiniteAutoProductionDamage(t *testing.T) {
	chdirRepoRootForData(t)
	roster := writeTempRoster(t, `[{"name":"耀骑士临光","charId":"char_1014_nearl2","elite":0,"level":1,"potential":1}]`)
	plan := json.RawMessage(`{"stage":"main_01-07","deploys":[{"operator":"耀骑士临光","position":[3,5],"direction":"Right","skill":1}]}`)
	built, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	blob, err := json.Marshal(built.Spec)
	if err != nil {
		t.Fatal(err)
	}
	var spec Spec
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	// Exercise the genuine built operator's normal-attack consumer, not a verdict:
	// unrelated real talent gaps remain intact and still refuse the full simulator.
	if len(spec.Placeholders) != 0 {
		t.Fatalf("E0 precise source blocked %+v", spec.Placeholders)
	}
	for _, g := range spec.Placeholders {
		if g.ID == "skill.range_override" && g.SourceID == "skchr_nearl2_1" {
			t.Fatal("complete skill range blocked")
		}
	}
	op := &operator{hp: spec.Operators[0].MaxHP, spec: spec.Operators[0], cell: [2]float64{3, 5}, sp: spec.Operators[0].Skill.SPCost}
	if op.spec.Active.TargetRange == nil || !op.spec.Skill.AutoTrigger || !op.spec.Skill.Infinite {
		t.Fatal("production infinite scope lost")
	}
	target := &enemy{hp: 10000, position: [2]float64{5, 5}, spec: SpawnSpec{Name: "active-only target"}}
	if len(pickTargets(op, []*enemy{target}, 1, 0)) != 0 {
		t.Fatal("base already covers active-only enemy")
	}
	cost := 0.0
	v := &Verdict{}
	skillTick([]*operator{op}, 1.0/30, 0, &spec, &cost, v)
	operatorsAttack([]*operator{op}, []*enemy{target}, 10, 10, &spec, v)
	if target.hp >= 10000 {
		t.Fatal("production expanded scope produced no damage")
	}
	t.Logf("real nearl2 active-only damage=%g", 10000-target.hp)
	skillTick([]*operator{op}, 1000, 1000, &spec, &cost, v)
	if !op.skillActive || !inCells(op.targetRange(), [2]int{5, 5}) {
		t.Fatal("infinite scope expired")
	}
	verdict, err := runSim(&spec)
	if verdict == nil || err != nil {
		t.Fatalf("E0 production rejected %v", err)
	}
	roster = writeTempRoster(t, `[{"name":"耀骑士临光","charId":"char_1014_nearl2","elite":1,"level":1,"potential":1}]`)
	built, err = BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	var incomplete *mechanisms.IncompleteError
	blob, err = json.Marshal(built.Spec)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	verdict, err = runSim(&spec)
	if verdict != nil || !errors.As(err, &incomplete) {
		t.Fatal("range support bypassed E1 deployment talent gaps")
	}
}

func TestSkillRangeSourceMutations(t *testing.T) {
	chdirRepoRootForData(t)
	meta, err := SkillMetaFor("skchr_spot_1", 7)
	if err != nil {
		t.Fatal(err)
	}
	empty := ""
	unknown := "unknown-range"
	zero := 0.0
	for _, mutate := range []func(*SkillMeta){
		func(m *SkillMeta) { m.RangeID = &empty }, func(m *SkillMeta) { m.RangeID = &unknown },
		func(m *SkillMeta) { m.RawDescription += "且伤害提高" }, func(m *SkillMeta) { m.OverrideTokenKey = "token" },
		func(m *SkillMeta) { m.Duration = &zero }, func(m *SkillMeta) { m.DurationType = "AMMO" },
		func(m *SkillMeta) {
			m.RawBlackboard = cloneRawBlackboard(m.RawBlackboard)
			m.RawBlackboard[1] = m.RawBlackboard[0]
		},
		func(m *SkillMeta) {
			m.RawBlackboard = cloneRawBlackboard(m.RawBlackboard)
			m.RawBlackboard[0] = json.RawMessage(`{"key":"atk","value":0.45,"valueStr":"variant"}`)
		},
	} {
		changed := *meta
		mutate(&changed)
		if _, ok := exactSkillTargetRange(changed); ok {
			t.Fatalf("changed source claimed %+v", changed)
		}
		gaps := skillMechanismGaps(changed, "x", "x", 1, "base")
		if *changed.RangeID != "" {
			requireSemanticGap(t, gaps, "skill.range_override", changed.SkillID)
		}
	}
	if _, err := selectedSkillSource(meta, "char_284_spot", 0); err == nil {
		t.Fatal("invalid source slot accepted")
	}
	selected, err := selectedSkillSource(meta, "char_284_spot", 1)
	if err != nil {
		t.Fatal(err)
	}
	if selected.SkillID != meta.SkillID || len(selected.RawSlot) == 0 {
		t.Fatal("selected source lost")
	}
	// Exercise source/table corruption through both the real binder and producer.
	tbl, err := LoadRangeTable()
	if err != nil {
		t.Fatal(err)
	}
	original := tbl["x-4"]
	defer func() { tbl["x-4"] = original }()
	delete(tbl, "x-4")
	row := DeployRow{Skill: 1, SkillLevel: 7, Direction: "Right", Position: [2]int{3, 5}, Entry: LoadoutEntry{CharID: "char_284_spot", Level: 1, Potential: 1}}
	if scope, err := bindSkillTargetRange(row, nil); err != nil || scope != nil {
		t.Fatalf("unknown code fallback %v/%v", scope, err)
	}
	requireSemanticGap(t, skillMechanismGaps(*meta, "x", "x", 1, "0-1"), "skill.range_override", meta.SkillID)
	roster := writeTempRoster(t, `[{"name":"斑点","charId":"char_284_spot","elite":0,"level":40,"potential":1}]`)
	plan := json.RawMessage(`{"stage":"main_01-07","deploys":[{"operator":"斑点","position":[3,5],"direction":"Right","skill":1}]}`)
	built, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	blob, err := json.Marshal(built.Spec)
	if err != nil {
		t.Fatal(err)
	}
	var spec Spec
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	if spec.Operators[0].Active.TargetRange != nil {
		t.Fatal("missing range bound fallback geometry")
	}
	requireSemanticGap(t, spec.Placeholders, "skill.range_override", "skchr_spot_1")
	v, err := runSim(&spec)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatal("missing range produced verdict")
	}
	tbl["x-4"] = []Cell{{0, 0}, {1, 0}}
	if _, ok := exactSkillTargetRange(*meta); ok {
		t.Fatal("wrong known-code cells accepted")
	}
}

func TestSkillRangeRedeploymentResetsScope(t *testing.T) {
	spec := deploymentPrimitiveSpec(3)
	addDeploymentPrimitive(spec, "range-id", "range", [2]int{1, 1}, 0, 0)
	addDeploymentPrimitive(spec, "range-id", "range", [2]int{5, 5}, 2, 0)
	for i := range spec.Operators {
		cell := spec.Operators[i].Cell
		spec.Operators[i].Range = [][2]int{cell}
		spec.Operators[i].Skill = &SkillSpec{SPType: spAuto, SPCost: 10, InitSP: 10, Duration: 1}
		spec.Operators[i].Active = &Profile{Interval: 1, TargetRange: &TargetRangeSpec{Cells: [][2]int{{cell[0] + 1, cell[1]}}}}
	}
	spec.Deploys[0].AutoSkill = true
	spec.Deploys[1].AutoSkill = false
	spec.Retreats = []RetreatSpec{{Time: 1, Operator: "range"}}
	v, err := runSim(spec)
	if err != nil {
		t.Fatal(err)
	}
	if len(eventsOf(v, "deploy", "range")) != 2 || len(eventsOf(v, "skill", "range")) != 1 {
		t.Fatalf("redeployment scope state not reset %+v", v.Events)
	}
	dead := rangePrimitiveOperator()
	dead.hp = 0
	cost := 0.0
	verdict := &Verdict{}
	activate(dead, 0, spec, &cost, verdict, false)
	if dead.skillActive {
		t.Fatal("dead activated range")
	}
	retreat := rangePrimitiveOperator()
	retreat.retreated = true
	activate(retreat, 0, spec, &cost, verdict, false)
	if retreat.skillActive {
		t.Fatal("retreated activated range")
	}
}

func TestSkillRangeRealBindingAtNewDeployment(t *testing.T) {
	chdirRepoRootForData(t)
	for _, exit := range []string{"retreat", "death"} {
		makeOp := func(cell [2]int) *operator {
			row := DeployRow{Operator: "斑点", Skill: 1, SkillLevel: 7, Position: cell, Direction: "Right", Entry: LoadoutEntry{CharID: "char_284_spot", Level: 40, Potential: 1}}
			out, err := buildOperatorOut(row, map[string]int{}, "")
			if err != nil {
				t.Fatal(err)
			}
			blob, err := json.Marshal(out)
			if err != nil {
				t.Fatal(err)
			}
			var spec OperatorSpec
			if err := json.Unmarshal(blob, &spec); err != nil {
				t.Fatal(err)
			}
			return &operator{hp: spec.MaxHP, spec: spec, cell: [2]float64{float64(cell[0]), float64(cell[1])}, sp: 40}
		}
		old := makeOp([2]int{1, 1})
		next := makeOp([2]int{5, 5})
		oldAlly := &operator{hp: 100, cell: [2]float64{2, 1}, spec: OperatorSpec{Name: "old ally", MaxHP: 1000}}
		nextAlly := &operator{hp: 100, cell: [2]float64{6, 5}, spec: OperatorSpec{Name: "new ally", MaxHP: 1000}}
		cost := 0.0
		v := &Verdict{}
		s := &Spec{CostMax: 99}
		activate(old, 0, s, &cost, v, false)
		operatorsAttack([]*operator{old}, []*enemy{}, 10, 1, s, v)
		// The same attack consumer needs all allies present for treatment selection.
		operatorsAttack([]*operator{old, oldAlly, nextAlly}, nil, 10, 2, s, v)
		if oldAlly.hp <= 100 || nextAlly.hp != 100 {
			t.Fatal("old actual footprint not exercised")
		}
		before := oldAlly.hp
		if exit == "retreat" {
			old.retreated = true
		} else {
			old.hp = 0
		}
		operatorsAttack([]*operator{old, oldAlly, nextAlly}, nil, 10, 3, s, v)
		if oldAlly.hp != before {
			t.Fatal("exited active unit kept healing")
		}
		if len(pickHeals(next, []*operator{oldAlly, nextAlly}, 1)) != 0 {
			t.Fatal("new deployment inherited active geometry")
		}
		activate(next, 4, s, &cost, v, false)
		operatorsAttack([]*operator{next, oldAlly, nextAlly}, nil, 10, 5, s, v)
		if nextAlly.hp <= 100 || oldAlly.hp != before {
			t.Fatal("new placement healed old range instead of new range")
		}
	}
}

func rangePrimitiveOperator() *operator {
	return &operator{hp: 1000, spec: OperatorSpec{Name: "range", MaxHP: 1000, Range: [][2]int{{1, 0}}, ATK: 100, AttackInterval: 1, DamageType: "physical", Skill: &SkillSpec{SPCost: 10, Duration: 1}, Active: &Profile{ATK: 100, Interval: 1, DamageType: "physical", MaxTarget: 1, AtkScale: 1, HitCount: 1, TargetRange: &TargetRangeSpec{Cells: [][2]int{{2, 0}}}}}, sp: 10}
}
func TestSkillRangeActivationExpiryTargetsAndTimer(t *testing.T) {
	op := rangePrimitiveOperator()
	e1 := &enemy{hp: 1000, position: [2]float64{1, 0}}
	e2 := &enemy{hp: 1000, position: [2]float64{2, 0}}
	if g := pickTargets(op, []*enemy{e1, e2}, 1, 0); len(g) != 1 || g[0] != e1 {
		t.Fatal("base geometry lost")
	}
	op.attackTimer = .75
	cost := 0.0
	v := &Verdict{}
	s := &Spec{CostMax: 99}
	activate(op, 0, s, &cost, v, false)
	if op.attackTimer != .75 {
		t.Fatal("range activation reset attack timer")
	}
	if g := pickTargets(op, []*enemy{e1, e2}, 1, 0); len(g) != 1 || g[0] != e2 {
		t.Fatal("active geometry not consumed")
	}
	if g := inRangeOf(op, []*enemy{e1, e2}); len(g) != 1 || g[0] != e2 {
		t.Fatal("trace differs from runtime")
	}
	operatorsAttack([]*operator{op}, []*enemy{e1, e2}, .25, .25, s, v)
	if e2.hp != 900 || e1.hp != 1000 {
		t.Fatalf("actual selected damage wrong %g/%g", e1.hp, e2.hp)
	}
	skillTick([]*operator{op}, 1, 1, s, &cost, v)
	if op.skillActive || !inCells(op.targetRange(), [2]int{1, 0}) || inCells(op.targetRange(), [2]int{2, 0}) {
		t.Fatal("expiry failed to restore base")
	}
	if !inCells(op.spec.Range, [2]int{1, 0}) {
		t.Fatal("base source mutated")
	}
}
func TestSkillRangeScopeIsolation(t *testing.T) {
	op := rangePrimitiveOperator()
	op.skillActive = true
	op.deploySeq = 1
	op.spec.RegenAura = &RegenAuraSpec{HPPerSec: 10, Duration: 5}
	base := &operator{hp: 50, cell: [2]float64{1, 0}, spec: OperatorSpec{MaxHP: 100}}
	active := &operator{hp: 50, cell: [2]float64{2, 0}, spec: OperatorSpec{MaxHP: 100}}
	regenAuraTick([]*operator{op, base, active}, 1)
	if base.hp != 60 || active.hp != 50 {
		t.Fatalf("targeting scope changed aura %g/%g", base.hp, active.hp)
	}
	op.blessingFreeze = 3
	v := &Verdict{}
	e1 := &enemy{hp: 100, position: [2]float64{1, 0}}
	e2 := &enemy{hp: 100, position: [2]float64{2, 0}}
	blessingTick([]*operator{op}, []*enemy{e1, e2}, 0, v)
	if e1.freezeTimer != 3 || e2.freezeTimer != 0 {
		t.Fatal("targeting scope changed blessing")
	}
}
func TestSkillRangeNilEmptyHealingAndBlocking(t *testing.T) {
	op := rangePrimitiveOperator()
	op.skillActive = true
	ally := &operator{hp: 10, cell: [2]float64{2, 0}, spec: OperatorSpec{MaxHP: 100}}
	if len(pickHeals(op, []*operator{ally}, 1)) != 1 {
		t.Fatal("healing did not use targeting scope")
	}
	op.spec.Active.TargetRange = &TargetRangeSpec{Cells: [][2]int{}}
	if len(pickHeals(op, []*operator{ally}, 1)) != 0 || len(op.targetRange()) != 0 {
		t.Fatal("explicit empty scope inherited base")
	}
	blocked := &enemy{hp: 100, position: [2]float64{9, 9}}
	op.blocking = []*enemy{blocked}
	if g := pickTargets(op, []*enemy{blocked}, 1, 0); len(g) != 1 || g[0] != blocked {
		t.Fatal("blocking priority was geometry filtered")
	}
	op.spec.Active.TargetRange = nil
	if !inCells(op.targetRange(), [2]int{1, 0}) {
		t.Fatal("nil did not inherit base")
	}
	blob, err := json.Marshal(op.spec)
	if err != nil {
		t.Fatal(err)
	}
	var copied OperatorSpec
	if err := json.Unmarshal(blob, &copied); err != nil {
		t.Fatal(err)
	}
	if copied.Active.TargetRange != nil {
		t.Fatal("nil range JSON lost")
	}
	op.spec.Active.TargetRange = &TargetRangeSpec{Cells: [][2]int{}}
	blob, err = json.Marshal(op.spec)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(blob, &copied); err != nil {
		t.Fatal(err)
	}
	if copied.Active.TargetRange == nil || len(copied.Active.TargetRange.Cells) != 0 {
		t.Fatal("empty scope JSON lost")
	}
}
