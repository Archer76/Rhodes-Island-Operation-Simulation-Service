package main

import (
	"encoding/json"
	"errors"
	"math"
	"rios-sim/mechanisms"
	"testing"
)

func TestConditionalASPDSourcesAllModuleLevels(t *testing.T) {
	chdirRepoRootForData(t)
	for _, c := range []struct {
		char, mod string
		level     int
	}{{"char_350_surtr", "uniequip_002_surtr", 60}, {"char_1019_siege2", "uniequip_002_siege2", 60}, {"char_1001_amiya2", "uniequip_002_amiya2", 50}, {"char_185_frncat", "uniequip_002_frncat", 40}, {"char_1050_chen3", "uniequip_002_chen3", 60}} {
		for ml := 1; ml <= 3; ml++ {
			st := &OperatorStats{CharID: c.char, Name: c.char, Elite: 2, Level: c.level, Potential: 1, Module: c.mod, ModuleLevel: ml}
			value, _, err := conditionalModuleSpeed(st)
			if err != nil || value != 8 {
				t.Fatalf("exact %s/%d value %g err%v", c.mod, ml, value, err)
			}
			st.Level--
			value, _, err = conditionalModuleSpeed(st)
			if err != nil || value != 0 {
				t.Fatalf("locked source consumed %s/%d", c.mod, ml)
			}
		}
	}
}
func TestConditionalASPDMathAndDynamicBlocking(t *testing.T) {
	op := &operator{hp: 100, spec: OperatorSpec{MaxHP: 100, AttackSpeedWhenFree: 8, AttackTiming: &AttackTimingSpec{BaseAttackTime: 1.5, ASPD: 115}, Active: &Profile{AttackTiming: &AttackTimingSpec{BaseAttackTime: 1.5, ASPD: 165}}}}
	if op.interval() != 150.0/123 {
		t.Fatal("base flat denominator lost")
	}
	op.skillActive = true
	if op.interval() != 150.0/173 {
		t.Fatal("skill and condition were multiplied")
	}
	e := &enemy{hp: 100, blockedBy: op}
	op.blocking = []*enemy{e}
	if op.interval() != 150.0/165 {
		t.Fatal("blocking did not disable condition")
	}
	e.hp = 0
	if op.interval() != 150.0/173 {
		t.Fatal("same-frame dead blocker kept condition off")
	}
	e.hp = 100
	e.blockedBy = nil
	if op.interval() != 150.0/173 {
		t.Fatal("stale blocking ownership")
	}
	op.spec.Active.AttackTiming.BaseAttackTime = .7
	if op.interval() != 70.0/173 {
		t.Fatal("BAT override lost")
	}
	op.spec.Active.AttackTiming = &AttackTimingSpec{BaseAttackTime: 1, ASPD: 0}
	if op.interval() != 5 {
		t.Fatal("ASPD lower clamp lost")
	}
	op.spec.Active.AttackTiming = &AttackTimingSpec{BaseAttackTime: .001, ASPD: 1000}
	if op.interval() != .05 {
		t.Fatal("minimum interval lost")
	}
	op.attackTimer = .42
	deactivate(op)
	if op.attackTimer != .42 || op.interval() != 150.0/123 {
		t.Fatal("ending reset timer or lost base context")
	}
}
func TestConditionalASPDValidBlockingAndGeometry(t *testing.T) {
	op := &operator{hp: 100, spec: OperatorSpec{MaxHP: 100, BlockCnt: 1, ATK: 100, DamageType: "physical", Range: [][2]int{{0, 0}}, AttackSpeedWhenFree: 8, AttackTiming: &AttackTimingSpec{BaseAttackTime: 1, ASPD: 100}}}
	e := &enemy{hp: 100, blockedBy: op}
	for _, mutate := range []func(*enemy){func(e *enemy) { e.leaked = true }, func(e *enemy) { e.offMap = true }, func(e *enemy) { e.blockedBy = &operator{} }, func(e *enemy) { e.hp = 0 }} {
		copy := *e
		mutate(&copy)
		op.blocking = []*enemy{nil, &copy}
		if op.freeAttackSpeed() != 8 {
			t.Fatal("invalid blocker suppressed bonus")
		}
		op.blocking = append(op.blocking, e)
		if op.freeAttackSpeed() != 0 {
			t.Fatal("one valid mixed blocker ignored")
		}
	}
	op.blocking = nil
	e.blockedBy = nil
	updateBlocking([]*operator{op}, []*enemy{e})
	if e.blockedBy != op || op.freeAttackSpeed() != 0 {
		t.Fatal("geometric blocking was not consumed")
	}
	v := &Verdict{}
	s := &Spec{}
	operatorsAttack([]*operator{op}, []*enemy{e}, .94, .94, s, v)
	if e.hp != 100 {
		t.Fatal("geometric blocker got free bonus")
	}
	e.hp = 0
	updateBlocking([]*operator{op}, []*enemy{e})
	if op.freeAttackSpeed() != 8 {
		t.Fatal("dead geometry blocker not released")
	}
	next := &enemy{hp: 100, position: [2]float64{0, 0}, spec: SpawnSpec{Name: "next"}}
	operatorsAttack([]*operator{op}, []*enemy{next}, .001, .941, s, v)
	if next.hp != 0 {
		t.Fatal("release did not use accumulated attack timer")
	}
}

func TestConditionalASPDUnclaimedModuleSources(t *testing.T) {
	chdirRepoRootForData(t)
	// Nonexact source/field mutations must never become the same +8 primitive.
	parts, err := moduleParts("uniequip_002_frncat", 1)
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
	c := p.Bundle.Candidates[0]
	for _, x := range []struct {
		char, mod  string
		part, cand int
	}{{"wrong", "uniequip_002_frncat", 0, 0}, {"char_185_frncat", "unknown", 0, 0}, {"char_185_frncat", "uniequip_002_frncat", 1, 0}, {"char_185_frncat", "uniequip_002_frncat", 0, 1}} {
		if exactFreeModuleCandidate(x.char, x.mod, 1, x.part, x.cand, parts[0], c) {
			t.Fatal("different source claimed")
		}
	}
	changed := c
	changed.Blackboard = []json.RawMessage{json.RawMessage(`{"key":"attack_speed","value":9,"valueStr":null}`)}
	if exactFreeModuleCandidate("char_185_frncat", "uniequip_002_frncat", 1, 0, 0, parts[0], changed) {
		t.Fatal("different value claimed")
	}
	for _, module := range []string{"uniequip_002_oblvns", "uniequip_003_etlchi", "uniequip_003_agoat2"} {
		_, gaps, err := conditionalModuleSpeed(&OperatorStats{CharID: "unclaimed", Name: "unclaimed", Elite: 2, Level: 90, Potential: 6, Module: module, ModuleLevel: 1})
		if err != nil {
			t.Fatal(err)
		}
		if len(gaps) == 0 {
			t.Fatalf("unrecognized conditional source %s silently accepted", module)
		}
		g := gaps[0]
		if g.SourceID != module || g.Level != 1 || len(g.RawSource) == 0 || len(g.RawSlot) == 0 || len(g.RawBlackboard) == 0 {
			t.Fatal("source provenance missing")
		}
		raw, err := moduleParts(module, 1)
		if err != nil {
			t.Fatal(err)
		}
		saved := append([]byte(nil), g.RawSource...)
		original := append(json.RawMessage(nil), raw[g.Slot]...)
		raw[g.Slot][0] = ' '
		if string(g.RawSource) != string(saved) {
			t.Fatal("gap source aliases raw table")
		}
		copy(raw[g.Slot], original)
		spec := deploymentPrimitiveSpec(1)
		spec.Placeholders = gaps
		v, err := runSim(spec)
		var incomplete *mechanisms.IncompleteError
		if v != nil || !errors.As(err, &incomplete) {
			t.Fatal("unclaimed module produced verdict")
		}
	}
}

func TestConditionalASPDActualAttackSwitches(t *testing.T) {
	op := &operator{hp: 100, spec: OperatorSpec{Name: "free", MaxHP: 100, ATK: 100, AttackInterval: 1, DamageType: "physical", Range: [][2]int{{1, 0}}, AttackSpeedWhenFree: 8, AttackTiming: &AttackTimingSpec{BaseAttackTime: 1, ASPD: 100}}}
	e := &enemy{hp: 1000, position: [2]float64{1, 0}, spec: SpawnSpec{Name: "target"}}
	s := &Spec{}
	v := &Verdict{}
	operatorsAttack([]*operator{op}, []*enemy{e}, .94, .94, s, v)
	if e.hp != 900 {
		t.Fatal("free attack frequency not consumed")
	}
	e.blockedBy = op
	op.blocking = []*enemy{e}
	operatorsAttack([]*operator{op}, []*enemy{e}, .94, 1.88, s, v)
	if e.hp != 900 || op.attackTimer != .94 {
		t.Fatal("blocking interval or timer wrong")
	}
	e.blockedBy = nil
	operatorsAttack([]*operator{op}, []*enemy{e}, .001, 1.881, s, v)
	if e.hp != 800 {
		t.Fatal("released blocker failed to use accumulated timer")
	}
	op.freezeTimer = 1
	before := op.attackTimer
	operatorsAttack([]*operator{op}, []*enemy{e}, 1, 3, s, v)
	if op.attackTimer != before || e.hp != 800 {
		t.Fatal("frozen attack timer advanced")
	}
	t.Logf("actual free/block/free hit damage=%g", 1000-e.hp)
}
func TestConditionalASPDJSONContextGuard(t *testing.T) {
	s := deploymentPrimitiveSpec(1)
	addDeploymentPrimitive(s, "ctx", "ctx", [2]int{0, 0}, 0, 0)
	op := &s.Operators[0]
	op.AttackSpeedWhenFree = 8
	op.AttackTiming = &AttackTimingSpec{BaseAttackTime: 1, ASPD: 115}
	op.Active = &Profile{AttackTiming: &AttackTimingSpec{BaseAttackTime: .7, ASPD: 165}}
	blob, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	var restored Spec
	if err := json.Unmarshal(blob, &restored); err != nil {
		t.Fatal(err)
	}
	if v, err := runSim(&restored); err != nil || v == nil {
		t.Fatalf("valid JSON refused %v", err)
	}
	for _, mutate := range []func(*OperatorSpec){func(o *OperatorSpec) { o.AttackTiming = nil }, func(o *OperatorSpec) { o.Active.AttackTiming = nil }, func(o *OperatorSpec) { o.AttackTiming.BaseAttackTime = 0 }, func(o *OperatorSpec) { o.AttackTiming.ASPD = math.NaN() }} {
		var broken Spec
		if err := json.Unmarshal(blob, &broken); err != nil {
			t.Fatal(err)
		}
		mutate(&broken.Operators[0])
		v, err := runSim(&broken)
		var incomplete *mechanisms.IncompleteError
		if v != nil || !errors.As(err, &incomplete) {
			t.Fatal("missing/bad raw context produced verdict")
		}
	}
	legacy := rangePrimitiveOperator()
	legacy.spec.AttackInterval = .7
	legacy.spec.Active.Interval = .4
	legacy.skillActive = false
	if legacy.interval() != .7 {
		t.Fatal("zero-condition legacy changed")
	}
	legacy.skillActive = true
	if legacy.interval() != .4 {
		t.Fatal("legacy active interval changed")
	}
}
func TestConditionalASPDProductionKeepsOtherGaps(t *testing.T) {
	chdirRepoRootForData(t)
	for _, c := range []struct {
		char, name, mod string
		level           int
	}{{"char_350_surtr", "史尔特尔", "uniequip_002_surtr", 60}, {"char_1019_siege2", "维娜·维多利亚", "uniequip_002_siege2", 60}, {"char_1001_amiya2", "阿米娅", "uniequip_002_amiya2", 50}, {"char_185_frncat", "慕斯", "uniequip_002_frncat", 40}, {"char_1050_chen3", "赤刃明霄陈", "uniequip_002_chen3", 60}} {
		for ml := 1; ml <= 3; ml++ {
			module := c.mod
			row := DeployRow{Operator: c.name, Skill: 1, SkillLevel: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: c.char, Elite: 2, Level: c.level, Potential: 1, Module: &module, ModuleLevel: &ml}}
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
			if op.AttackSpeedWhenFree != 8 || !validAttackTiming(op.AttackTiming) || !validAttackTiming(op.Active.AttackTiming) {
				t.Fatalf("production context lost %+v", op)
			}
			if len(op.Placeholders) == 0 {
				t.Fatal("other real sources silently consumed")
			}
			for _, g := range op.Placeholders {
				if g.ID == "module.attack_speed_when_free" || (g.ID == "module.conditional_attack_speed" && g.SourceID == c.mod && g.Slot == 0 && g.Instance == 0) {
					t.Fatal("precise source remains blocked")
				}
			}
			spec := deploymentPrimitiveSpec(1)
			spec.Operators = []OperatorSpec{op}
			v, err := runSim(spec)
			var incomplete *mechanisms.IncompleteError
			if v != nil || !errors.As(err, &incomplete) {
				t.Fatal("module support removed unrelated gaps")
			}
			// Source-real isolated consumer: no complete verdict is claimed for Mousse.
			unit := &operator{hp: op.MaxHP, spec: op}
			unit.skillActive = true
			if unit.interval() != timingInterval(op.Active.AttackTiming, 8) {
				t.Fatal("real active timing failed")
			}
		}
	}
}
