package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func countSpeedUnit() *operator {
	o := hpSpeedUnit()
	o.spec.HPAttackSpeed = nil
	o.spec.EnemyCountAttackSpeed = &EnemyCountASPD{Scope: "current", Minimum: 2, Bonus: 12}
	return o
}
func countedEnemy(x float64) *enemy {
	return &enemy{hp: 1000, position: [2]float64{x, 0}, spec: SpawnSpec{Name: "counted", CountVisibility: &CountVisibility{}}}
}
func TestCountASPDUserFiltersAndGeometry(t *testing.T) {
	o := countSpeedUnit()
	a := countedEnemy(1)
	b := countedEnemy(1)
	check := func(want float64) {
		t.Helper()
		got, err := o.intervalForEnemies([]*enemy{a, b})
		if err != nil || got != want {
			t.Fatalf("interval %g want %g err %v", got, want, err)
		}
	}
	check(100.0 / 112)
	b.spec.IsFlying = true
	b.invincible = true
	check(100.0 / 112)
	b.spec.CountVisibility.Hidden = true
	check(1)
	b.spec.CountVisibility.Hidden = false
	b.spec.CountVisibility.Camouflage = true
	check(1)
	b.spec.CountVisibility.Camouflage = false
	b.hp = 0
	check(1)
	b.hp = 1000
	b.leaked = true
	check(1)
	b.leaked = false
	b.offMap = true
	check(1)
	b.offMap = false
	b.position[0] = 5
	b.blockedBy = o
	o.blocking = []*enemy{b}
	check(1)
	b.position[0] = 1.5
	check(1)
	b.position[0] = .5
	check(1)
	b.position[0] = 1.49
	check(100.0 / 112)
	// One object contributes once, not once per duplicate range cell.
	o.spec.Range = append(o.spec.Range, [2]int{1, 0})
	got, err := o.intervalForEnemies([]*enemy{a})
	if err != nil || got != 1 {
		t.Fatal("range duplicates counted twice")
	}
	if got, err := o.intervalForEnemies(nil); err != nil || got != 1 {
		t.Fatal("explicit empty scene rejected")
	}
}
func TestCountASPDCurrentRangeAndSakikoException(t *testing.T) {
	o := countSpeedUnit()
	a := countedEnemy(1)
	b := countedEnemy(2)
	scene := []*enemy{a, b}
	o.spec.Active = &Profile{TargetRange: &TargetRangeSpec{Cells: [][2]int{{1, 0}, {2, 0}}}, AttackTiming: &AttackTimingSpec{BaseAttackTime: .7, ASPD: 150}}
	o.spec.AttackSpeedWhenFree = 8
	o.spec.HPAttackSpeed = &HPAttackSpeedSpec{AboveRatio: .5, Bonus: 10}
	o.skillActive = true
	o.attackTimer = .42
	got, err := o.intervalForEnemies(scene)
	if err != nil || got != 70.0/180 {
		t.Fatalf("current range additive bonus %g %v", got, err)
	}
	o.spec.EnemyCountAttackSpeed.Scope = "base"
	got, err = o.intervalForEnemies(scene)
	if err != nil || got != 70.0/168 {
		t.Fatal("Sakiko base scope used active geometry")
	}
	o.spec.EnemyCountAttackSpeed.Scope = "current"
	o.spec.Active.TargetRange = &TargetRangeSpec{}
	got, err = o.intervalForEnemies(scene)
	if err != nil || got != 70.0/168 {
		t.Fatal("explicit empty scope inherited")
	}
	o.spec.Active.TargetRange = nil
	got, err = o.intervalForEnemies(scene)
	if err != nil || got != 70.0/168 {
		t.Fatal("nil scope did not inherit base")
	}
	deactivate(o)
	if o.attackTimer != .42 {
		t.Fatal("scope expiry reset timer")
	}
}
func TestCountASPDSameFrameKillAndTimer(t *testing.T) {
	for _, killerFirst := range []bool{true, false} {
		o := countSpeedUnit()
		a := countedEnemy(1)
		a.hp = 100
		b := countedEnemy(1)
		killer := hpSpeedUnit()
		killer.spec.HPAttackSpeed = nil
		killer.spec.AttackInterval = .1
		ops := []*operator{o, killer}
		if killerFirst {
			ops = []*operator{killer, o}
		}
		if err := operatorsAttack(ops, []*enemy{a, b}, .9, .9, &Spec{}, &Verdict{}); err != nil {
			t.Fatal(err)
		}
		if killerFirst {
			if a.hp != 0 || b.hp != 1000 || o.attackTimer != .9 {
				t.Fatal("後手 cached dead enemy count")
			}
			a.hp = 100
			if err := operatorsAttack([]*operator{o}, []*enemy{a, b}, .001, .901, &Spec{}, &Verdict{}); err != nil {
				t.Fatal(err)
			}
			if a.hp != 0 {
				t.Fatal("count transition reset accumulated timer")
			}
		} else {
			if a.hp != 0 || b.hp != 900 {
				t.Fatal("前手 did not use prekill live count")
			}
		}
	}
	o := countSpeedUnit()
	o.freezeTimer = 1
	if err := operatorsAttack([]*operator{o}, []*enemy{countedEnemy(1), countedEnemy(1)}, .9, 0, &Spec{}, &Verdict{}); err != nil || o.attackTimer != 0 {
		t.Fatal("freeze accrued timer")
	}
	t.Log("actual count 2-to-1 same-frame order: first count user fires; after preceding kill user waits")
}
func TestCountASPDUnknownStateAndRawGuard(t *testing.T) {
	o := countSpeedUnit()
	e := countedEnemy(1)
	e.spec.CountVisibility = nil
	if _, err := o.intervalForEnemies([]*enemy{e}); err == nil {
		t.Fatal("unknown visibility treated false")
	}
	if err := operatorsAttack([]*operator{o}, []*enemy{e}, 1, 0, &Spec{}, &Verdict{}); err == nil {
		t.Fatal("attack entry dropped error")
	}
	s := deploymentPrimitiveSpec(1)
	s.Operators = []OperatorSpec{o.spec}
	s.Spawns[0].CountVisibility = &CountVisibility{}
	s.Spawns[0].Time = 0
	s.Spawns[0].Legs = []LegSpec{{Kind: "wait", Seconds: 100, Points: [][2]float64{{1, 0}}}}
	s.Spawns[0].MoveSpeed = 0
	s.Spawns = append(s.Spawns, s.Spawns[0])
	s.Deploys = []DeploySpec{{Index: 0, Time: 0, Cost: 1}}
	blob, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	var restored Spec
	if err := json.Unmarshal(blob, &restored); err != nil {
		t.Fatal(err)
	}
	if v, err := runSim(&restored); err != nil || v == nil || v.DamageDealt == 0 {
		t.Fatalf("actual deployed count state did not produce attack %v %+v", err, v)
	}
	for _, mutate := range []func(*Spec){func(s *Spec) { s.Spawns[0].CountVisibility = nil }, func(s *Spec) { s.Operators[0].EnemyCountAttackSpeed.Scope = "target_pool" }, func(s *Spec) { s.Operators[0].EnemyCountAttackSpeed.Minimum = 0 }, func(s *Spec) { s.Operators[0].EnemyCountAttackSpeed.Bonus = 0 }, func(s *Spec) { s.Operators[0].AttackTiming = nil }, func(s *Spec) { s.Operators[0].Active = &Profile{} }} {
		var broken Spec
		if err := json.Unmarshal(blob, &broken); err != nil {
			t.Fatal(err)
		}
		mutate(&broken)
		v, err := runSim(&broken)
		var incomplete *mechanisms.IncompleteError
		if v != nil || !errors.As(err, &incomplete) {
			t.Fatal("raw omitted count context bypassed")
		}
	}
	// Missing count visibility does not change legacy scenes without this rule.
	restored.Operators[0].EnemyCountAttackSpeed = nil
	restored.Spawns[0].CountVisibility = nil
	if v, err := runSim(&restored); err != nil || v == nil {
		t.Fatal("legacy scene changed")
	}
}
func TestCountASPDVisibilityPresenceAndInstanceIsolation(t *testing.T) {
	for _, raw := range []string{`{}`, `{"hidden":false}`, `{"hidden":null,"camouflage":false}`, `{"hidden":false,"camouflage":null}`} {
		var v CountVisibility
		if err := json.Unmarshal([]byte(raw), &v); err == nil {
			t.Fatal("partial counting visibility accepted")
		}
	}
	spec := SpawnSpec{CountVisibility: &CountVisibility{}}
	a := newEnemy(spec, 0, [2]float64{}, nil)
	b := newEnemy(spec, 1, [2]float64{}, nil)
	a.spec.CountVisibility.Hidden = true
	if spec.CountVisibility.Hidden || b.spec.CountVisibility.Hidden {
		t.Fatal("instance mutation altered template/other instance")
	}
	scene := &Spec{Operators: []OperatorSpec{countSpeedUnit().spec}}
	ctx := &simCtx{spec: scene}
	newEnemy(SpawnSpec{}, 0, [2]float64{}, ctx)
	if ctx.countError == nil {
		t.Fatal("unknown generated without attacker did not record refusal")
	}
}
func TestCountASPDRealSourcesRemainIncomplete(t *testing.T) {
	chdirRepoRootForData(t)
	for _, id := range []struct{ char, module string }{{"char_4182_oblvns", "uniequip_002_oblvns"}, {"char_4010_etlchi", "uniequip_003_etlchi"}} {
		for ml := 1; ml <= 3; ml++ {
			_, gaps, err := conditionalModuleSpeed(&OperatorStats{CharID: id.char, Elite: 2, Level: 60, Potential: 1, Module: id.module, ModuleLevel: ml})
			if err != nil {
				t.Fatal(err)
			}
			requireSemanticGap(t, gaps, "module.conditional_attack_speed", id.module)
		}
	}
}
