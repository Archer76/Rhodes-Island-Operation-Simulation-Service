package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"math"
	"rios-sim/mechanisms"
	"testing"
)

func hpSpeedUnit() *operator {
	return &operator{hp: 1000, spec: OperatorSpec{Name: "HP speed", MaxHP: 1000, ATK: 100, AttackInterval: 1, DamageType: "physical", Range: [][2]int{{1, 0}}, AttackTiming: &AttackTimingSpec{BaseAttackTime: 1, ASPD: 100}, HPAttackSpeed: &HPAttackSpeedSpec{AboveRatio: .5, Bonus: 10}}}
}
func TestHPASPDStrictBoundaryDamageHealingAndTimer(t *testing.T) {
	op := hpSpeedUnit()
	op.hp = 500
	if op.interval() != 1 {
		t.Fatal("equality incorrectly gained bonus")
	}
	op.hp = math.Nextafter(500, math.Inf(1))
	if op.interval() != 100.0/110 {
		t.Fatal("one-ulp above lost strict bonus")
	}
	op.hp = math.Nextafter(500, 0)
	if op.interval() != 1 {
		t.Fatal("below gained bonus")
	}
	op.hp = 600
	op.hurt(100)
	if op.hpAttackSpeed() != 0 {
		t.Fatal("damage to boundary did not remove bonus")
	}
	op.heal(1)
	if op.hpAttackSpeed() != 10 {
		t.Fatal("healing across boundary did not restore bonus")
	}
	target := &enemy{hp: 1000, position: [2]float64{1, 0}, spec: SpawnSpec{Name: "target"}}
	v := &Verdict{}
	s := &Spec{}
	op.hp = 500
	operatorsAttack([]*operator{op}, []*enemy{target}, .92, .92, s, v)
	if target.hp != 1000 || op.attackTimer != .92 {
		t.Fatal("low HP attack fired early")
	}
	op.heal(1)
	operatorsAttack([]*operator{op}, []*enemy{target}, .001, .921, s, v)
	if target.hp != 900 {
		t.Fatal("HP transition failed to consume accumulated timer")
	}
	op.hp = 500
	operatorsAttack([]*operator{op}, []*enemy{target}, .92, 1.841, s, v)
	if target.hp != 900 {
		t.Fatal("condition latched high")
	}
	op.freezeTimer = 1
	before := op.attackTimer
	op.heal(1)
	operatorsAttack([]*operator{op}, []*enemy{target}, 1, 2.841, s, v)
	if target.hp != 900 || op.attackTimer != before {
		t.Fatal("freeze timer changed")
	}
	t.Logf("actual HP-threshold transition damage=%g", 1000-target.hp)
}
func TestHPASPDCurrentCapSkillAndBonusSum(t *testing.T) {
	op := hpSpeedUnit()
	op.hp = 600
	cap := 2000.0
	op.spec.Active = &Profile{MaxHP: &cap, AttackTiming: &AttackTimingSpec{BaseAttackTime: .7, ASPD: 150}}
	op.skillActive = true
	if op.hpAttackSpeed() != 0 || op.interval() != 70.0/150 {
		t.Fatal("read deployment cap instead of current cap")
	}
	op.hp = 1001
	op.spec.AttackSpeedWhenFree = 8
	if op.interval() != 70.0/168 {
		t.Fatal("skill/free/HP not additive")
	}
	blocker := &enemy{hp: 100, blockedBy: op}
	op.blocking = []*enemy{blocker}
	if op.interval() != 70.0/160 {
		t.Fatal("blocking incorrectly removed HP bonus")
	}
	op.attackTimer = .7
	deactivate(op)
	if op.hp != 1000 || op.hpAttackSpeed() != 10 || op.attackTimer != .7 {
		t.Fatal("expiry cap/timer condition wrong")
	}
	op.spec.Skill = &SkillSpec{SPCost: 10, Duration: 5, SelfHealMaxHPRatio: .1}
	op.hp = 400
	op.sp = 10
	cost := 0.0
	v := &Verdict{}
	activate(op, 0, &Spec{CostMax: 99}, &cost, v, false)
	if op.hp != 1600 || op.hpAttackSpeed() != 10 {
		t.Fatalf("activation maxHP then selfheal ordering %g", op.hp)
	}
	op.hp = 0
	if op.hpAttackSpeed() != 0 {
		t.Fatal("dead unit bonus")
	}
	op.hp = 1600
	op.retreated = true
	if op.hpAttackSpeed() != 0 {
		t.Fatal("retreated unit bonus")
	}
}
func TestHPASPDHealListOrder(t *testing.T) {
	for _, healerFirst := range []bool{true, false} {
		op := hpSpeedUnit()
		op.hp = 500
		medic := &operator{hp: 100, spec: OperatorSpec{Name: "medic", MaxHP: 100, ATK: 1, AttackInterval: .1, Heals: true, Range: [][2]int{{0, 0}}}}
		target := &enemy{hp: 1000, position: [2]float64{1, 0}, spec: SpawnSpec{Name: "target"}}
		ops := []*operator{op, medic}
		if healerFirst {
			ops = []*operator{medic, op}
		}
		operatorsAttack(ops, []*enemy{target}, .92, .92, &Spec{}, &Verdict{})
		if op.hp != 501 {
			t.Fatal("medic did not cross HP threshold")
		}
		want := 1000.0
		if healerFirst {
			want = 900
		}
		if target.hp != want {
			t.Fatalf("same-frame list order %t HP=%g", healerFirst, target.hp)
		}
	}
}
func TestHPASPDProductionSourcesAndNoDoubleCount(t *testing.T) {
	chdirRepoRootForData(t)
	for _, c := range []struct{ char, name, module string }{{"char_4037_demetr", "贝洛内", "uniequip_002_demetr"}, {"char_2024_chyue", "重岳", "uniequip_003_chyue"}} {
		for ml := 1; ml <= 3; ml++ {
			st := &OperatorStats{CharID: c.char, Name: c.name, Elite: 2, Level: 60, Potential: 1, Module: c.module, ModuleLevel: ml}
			rule, err := hpModuleSpeed(st)
			if err != nil || rule == nil || rule.Bonus != 10 || rule.AboveRatio != .5 {
				t.Fatalf("exact source %s/%d %v", c.module, ml, err)
			}
			st.Level = 59
			locked, err := hpModuleSpeed(st)
			if err != nil || locked != nil {
				t.Fatal("locked source consumed")
			}
			row := DeployRow{Operator: c.name, Skill: 1, SkillLevel: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: c.char, Elite: 2, Level: 60, Potential: 1, Module: &c.module, ModuleLevel: &ml}}
			out, err := buildOperatorOut(row, map[string]int{}, "")
			if err != nil {
				t.Fatal(err)
			}
			blob, err := json.Marshal(out)
			if err != nil {
				t.Fatal(err)
			}
			var wire OperatorSpec
			if err := json.Unmarshal(blob, &wire); err != nil {
				t.Fatal(err)
			}
			if wire.HPAttackSpeed == nil || !validAttackTiming(wire.AttackTiming) || !validAttackTiming(wire.Active.AttackTiming) {
				t.Fatal("production HP context missing")
			}
			parts, err := moduleParts(c.module, ml)
			if err != nil {
				t.Fatal(err)
			}
			flat, _ := moduleAttackSpeed(parts, 2, 60, 1)
			if flat != 10 {
				t.Fatalf("expected old precise Flat10 got %g", flat)
			}
			if wire.AttackTiming.ASPD != 100 {
				t.Fatalf("condition remained constant in baseline %g", wire.AttackTiming.ASPD)
			}
			for _, g := range wire.Placeholders {
				if g.ID == "module.conditional_attack_speed" && g.SourceID == c.module && g.Slot == 0 && g.Instance == 0 {
					t.Fatal("complete source blocked")
				}
			}
			if len(wire.Placeholders) == 0 {
				t.Fatal("other real gaps removed")
			}
			s := deploymentPrimitiveSpec(1)
			s.Operators = []OperatorSpec{wire}
			v, err := runSim(s)
			var incomplete *mechanisms.IncompleteError
			if v != nil || !errors.As(err, &incomplete) {
				t.Fatal("HP module support bypassed other gaps")
			}
			unit := &operator{hp: wire.MaxHP * .5, spec: wire}
			if unit.interval() != timingInterval(wire.AttackTiming, 0) {
				t.Fatal("low HP production double counts bonus")
			}
			unit.heal(1)
			if unit.interval() != timingInterval(wire.AttackTiming, 10) {
				t.Fatal("high HP production bonus absent")
			}
			if c.char == "char_4037_demetr" {
				row.Skill = 2
				s2, err := buildOperatorOut(row, map[string]int{}, "")
				if err != nil {
					t.Fatal(err)
				}
				if s2.AttackTiming.ASPD != 100 || s2.Active.AttackTiming.ASPD != 160 {
					t.Fatalf("S2 exact static/skill context double count %g/%g", s2.AttackTiming.ASPD, s2.Active.AttackTiming.ASPD)
				}
				blob, err := json.Marshal(s2)
				if err != nil {
					t.Fatal(err)
				}
				var s2wire OperatorSpec
				if err := json.Unmarshal(blob, &s2wire); err != nil {
					t.Fatal(err)
				}
				sourceUnit := &operator{hp: s2wire.MaxHP * .5, spec: s2wire, skillActive: true}
				if sourceUnit.interval() != timingInterval(s2wire.Active.AttackTiming, 0) {
					t.Fatal("S2 below bonus wrong")
				}
				sourceUnit.heal(1)
				if sourceUnit.interval() != timingInterval(s2wire.Active.AttackTiming, 10) {
					t.Fatal("S2 active160+10 not additive")
				}
			}

		}
	}
}
func TestHPASPDRegenDrainAndNewDeployment(t *testing.T) {
	op := hpSpeedUnit()
	op.hp = 501
	op.spec.HPDrainPerSec = .001
	traitDrainTick([]*operator{op}, 1, 0)
	if op.hp != 500 || op.hpAttackSpeed() != 0 {
		t.Fatal("trait damage boundary latched")
	}
	owner := &operator{hp: 100, deploySeq: 1, spec: OperatorSpec{MaxHP: 100, Range: [][2]int{{0, 0}}, RegenAura: &RegenAuraSpec{HPPerSec: 1, Duration: 5}}}
	regenAuraTick([]*operator{owner, op}, 1)
	if op.hp != 501 || op.hpAttackSpeed() != 10 {
		t.Fatal("regen did not restore same-frame condition")
	}
	for _, exit := range []string{"death", "retreat"} {
		old := hpSpeedUnit()
		if exit == "death" {
			old.hurt(1000)
		} else {
			old.retreated = true
			old.hp = 0
		}
		if old.hpAttackSpeed() != 0 {
			t.Fatal("exited object gained HP bonus")
		}
		next := hpSpeedUnit()
		if next.hpAttackSpeed() != 10 || next.skillActive || next.attackTimer != 0 {
			t.Fatal("new deployment state carried stale condition")
		}
	}
}
func TestHPASPDSourceMutationsAndProductionRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	parts, err := moduleParts("uniequip_002_demetr", 1)
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
	original := p.Bundle.Candidates[0]
	for _, mutate := range []func(*moduleSpeedCandidate){func(c *moduleSpeedCandidate) {
		s := "能够阻挡一个敌人，生命值不低于50%时攻击速度+{attack_speed}"
		c.OverrideDescription = &s
	}, func(c *moduleSpeedCandidate) { c.Blackboard = c.Blackboard[:1] }, func(c *moduleSpeedCandidate) { c.Blackboard = []json.RawMessage{c.Blackboard[0], c.Blackboard[0]} }, func(c *moduleSpeedCandidate) {
		c.Blackboard = []json.RawMessage{json.RawMessage(`{"key":"attack_speed","value":10,"valueStr":"token"}`), c.Blackboard[1]}
	}} {
		c := original
		mutate(&c)
		if exactHPModuleCandidate("char_4037_demetr", "uniequip_002_demetr", 1, 0, 0, parts[0], c) {
			t.Fatal("changed contract claimed")
		}
	}
	if exactHPModuleCandidate("wrong-owner", "uniequip_002_demetr", 1, 0, 0, parts[0], original) || exactHPModuleCandidate("char_4037_demetr", "uniequip_002_demetr", 1, 1, 0, parts[0], original) {
		t.Fatal("source mismatch claimed")
	}
	module := "uniequip_002_demetr"
	saved := append(json.RawMessage(nil), battleEquipCache[module]...)
	defer func() { battleEquipCache[module] = saved }()
	// A changed source retains its old numerical Flat, but remains incomplete.
	changed := bytes.ReplaceAll(saved, []byte("生命值高于50%"), []byte("生命值不低于50%"))
	if bytes.Equal(changed, saved) {
		t.Fatal("mutation did not reach real source")
	}
	battleEquipCache[module] = changed
	ml := 1
	row := DeployRow{Operator: "贝洛内", Skill: 1, SkillLevel: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: "char_4037_demetr", Elite: 2, Level: 60, Potential: 1, Module: &module, ModuleLevel: &ml}}
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
	if op.HPAttackSpeed != nil {
		t.Fatal("changed source bound rule")
	}
	requireSemanticGap(t, op.Placeholders, "module.conditional_attack_speed", module)
	spec := deploymentPrimitiveSpec(1)
	spec.Operators = []OperatorSpec{op}
	v, err := runSim(spec)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatal("changed source produced verdict")
	}
	// Same text but single-key module is deliberately still not this exact family.
	for _, owner := range []struct{ char, mod string }{{"char_157_dagda", "uniequip_002_dagda"}, {"char_264_f12yin", "uniequip_002_f12yin"}, {"char_155_tiger", "uniequip_002_tiger"}, {"char_415_flint", "uniequip_002_flint"}, {"char_137_brownb", "uniequip_002_brownb"}} {
		for level := 1; level <= 3; level++ {
			st := &OperatorStats{CharID: owner.char, Elite: 2, Level: 90, Potential: 1, Module: owner.mod, ModuleLevel: level}
			rule, err := hpModuleSpeed(st)
			if err != nil || rule != nil {
				t.Fatal("single-key sibling was claimed")
			}
			_, gaps, err := conditionalModuleSpeed(st)
			if err != nil {
				t.Fatal(err)
			}
			requireSemanticGap(t, gaps, "module.conditional_attack_speed", owner.mod)
			if len(gaps[0].RawSource) == 0 || len(gaps[0].RawSlot) == 0 || len(gaps[0].RawBlackboard) == 0 {
				t.Fatal("sibling source evidence missing")
			}
		}
	}
}

func TestHPASPDPredicateIdentityNegative(t *testing.T) {
	chdirRepoRootForData(t)
	parts, err := moduleParts("uniequip_003_chyue", 1)
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
	for _, identity := range []struct {
		char, module      string
		level, part, cand int
	}{{"wrong", "uniequip_003_chyue", 1, 0, 0}, {"char_2024_chyue", "unknown", 1, 0, 0}, {"char_2024_chyue", "uniequip_003_chyue", 4, 0, 0}, {"char_2024_chyue", "uniequip_003_chyue", 1, 1, 0}, {"char_2024_chyue", "uniequip_003_chyue", 1, 0, 1}} {
		if exactHPModuleCandidate(identity.char, identity.module, identity.level, identity.part, identity.cand, parts[0], c) {
			t.Fatal("wrong identity accepted")
		}
	}
	for _, change := range []struct {
		key   string
		value any
	}{{"resKey", "chyue_equip_1_1_p1"}, {"target", "TALENT"}, {"isToken", true}, {"validInGameTag", "mode"}} {
		var fields map[string]any
		if err := json.Unmarshal(parts[0], &fields); err != nil {
			t.Fatal(err)
		}
		if fields[change.key] == change.value {
			t.Fatal("negative mutation already present")
		}
		fields[change.key] = change.value
		raw, err := json.Marshal(fields)
		if err != nil {
			t.Fatal(err)
		}
		if exactHPModuleCandidate("char_2024_chyue", "uniequip_003_chyue", 1, 0, 0, raw, c) {
			t.Fatal("changed part accepted")
		}
	}
}

func TestHPASPDJSONMalformedContextRefused(t *testing.T) {
	s := deploymentPrimitiveSpec(1)
	addDeploymentPrimitive(s, "hp", "hp", [2]int{0, 0}, 0, 0)
	unit := hpSpeedUnit()
	s.Operators[0] = unit.spec
	blob, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	var restored Spec
	if err := json.Unmarshal(blob, &restored); err != nil {
		t.Fatal(err)
	}
	if v, err := runSim(&restored); v == nil || err != nil {
		t.Fatalf("valid HP spec refused %v", err)
	}
	for _, mutate := range []func(*OperatorSpec){func(o *OperatorSpec) { o.HPAttackSpeed.AboveRatio = math.NaN() }, func(o *OperatorSpec) { o.HPAttackSpeed.Bonus = 0 }, func(o *OperatorSpec) { o.HPAttackSpeed.Bonus = math.NaN() }, func(o *OperatorSpec) { o.MaxHP = math.Inf(1) }, func(o *OperatorSpec) { o.AttackTiming.BaseAttackTime = -1 }, func(o *OperatorSpec) { o.AttackTiming.ASPD = math.Inf(1) }, func(o *OperatorSpec) { o.HPAttackSpeed.AboveRatio = 0 }, func(o *OperatorSpec) { o.HPAttackSpeed.AboveRatio = 1 }, func(o *OperatorSpec) { o.HPAttackSpeed.Bonus = -1 }, func(o *OperatorSpec) { o.HPAttackSpeed.Bonus = math.Inf(1) }, func(o *OperatorSpec) { o.AttackTiming = nil }, func(o *OperatorSpec) { o.MaxHP = 0 }, func(o *OperatorSpec) { v := math.NaN(); o.Active = &Profile{MaxHP: &v, AttackTiming: o.AttackTiming} }, func(o *OperatorSpec) { o.Active = &Profile{} }} {
		var broken Spec
		if err := json.Unmarshal(blob, &broken); err != nil {
			t.Fatal(err)
		}
		mutate(&broken.Operators[0])
		v, err := runSim(&broken)
		var incomplete *mechanisms.IncompleteError
		if v != nil || !errors.As(err, &incomplete) {
			t.Fatal("invalid HP spec produced verdict")
		}
	}
}
