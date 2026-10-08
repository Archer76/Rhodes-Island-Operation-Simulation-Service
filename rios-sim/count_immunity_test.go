package main

import (
	"encoding/json"
	"testing"
)

func TestCountImmunityHeldFlagAndEffectiveRestrictions(t *testing.T) {
	for _, c := range []struct {
		v       CountVisibility
		blocked bool
	}{{CountVisibility{}, false}, {CountVisibility{Hidden: true}, true}, {CountVisibility{Camouflage: true}, true}, {CountVisibility{Hidden: true, Camouflage: true, InvisibleImmune: true}, false}, {CountVisibility{Camouflage: true, CamouflageImmune: true}, false}, {CountVisibility{Hidden: true, CamouflageImmune: true}, true}} {
		if c.v.blocksCount() != c.blocked {
			t.Fatalf("effective count state %+v", c)
		}
	}
	o := countSpeedUnit()
	a := countedEnemy(1)
	b := countedEnemy(1)
	b.spec.CountVisibility.Camouflage = true
	b.spec.IsFlying = true
	b.invincible = true
	check := func(want float64) {
		t.Helper()
		got, err := o.intervalForEnemies([]*enemy{a, b})
		if err != nil || got != want {
			t.Fatalf("interval %g want %g err%v", got, want, err)
		}
	}
	check(1)
	b.spec.CountVisibility.InvisibleImmune = true
	check(100.0 / 112)
	if !b.spec.CountVisibility.Camouflage {
		t.Fatal("immunity erased held camouflage")
	}
	b.spec.CountVisibility.InvisibleImmune = false
	check(1)
	b.spec.CountVisibility.Camouflage = false
	b.spec.CountVisibility.Hidden = true
	check(1)
	b.spec.CountVisibility.CamouflageImmune = true
	check(1)
	b.spec.CountVisibility.InvisibleImmune = true
	check(100.0 / 112)
}
func TestCountImmunityActualAttackTransitionKeepsTimer(t *testing.T) {
	o := countSpeedUnit()
	a := countedEnemy(1)
	b := countedEnemy(1)
	b.spec.CountVisibility.Camouflage = true
	if err := operatorsAttack([]*operator{o}, []*enemy{a, b}, .9, .9, &Spec{}, &Verdict{}); err != nil {
		t.Fatal(err)
	}
	if a.hp != 1000 || o.attackTimer != .9 {
		t.Fatal("effective camouflage not excluded")
	}
	b.spec.CountVisibility.InvisibleImmune = true
	if err := operatorsAttack([]*operator{o}, []*enemy{a, b}, .001, .901, &Spec{}, &Verdict{}); err != nil {
		t.Fatal(err)
	}
	if a.hp != 900 || o.attackTimer != 0 {
		t.Fatal("anti-stealth did not count with accumulated timer")
	}
	b.spec.CountVisibility.InvisibleImmune = false
	if err := operatorsAttack([]*operator{o}, []*enemy{a, b}, .9, 1.801, &Spec{}, &Verdict{}); err != nil {
		t.Fatal(err)
	}
	if a.hp != 900 || !b.spec.CountVisibility.Camouflage {
		t.Fatal("immunity expiry failed to restore exclusion")
	}
}
func TestCountImmunityJSONAndInstanceSnapshot(t *testing.T) {
	var v CountVisibility
	if err := json.Unmarshal([]byte(`{"hidden":true,"camouflage":true,"invisible_immune":true}`), &v); err != nil || v.blocksCount() {
		t.Fatal("explicit immunity not decoded", err)
	}
	for _, raw := range []string{`{"hidden":false,"camouflage":true,"invisible_immune":null}`, `{"hidden":false,"camouflage":true,"camouflage_immune":"yes"}`} {
		if err := json.Unmarshal([]byte(raw), &v); err == nil {
			t.Fatal("invalid immunity silently false")
		}
	}
	if err := json.Unmarshal([]byte(`{"hidden":false,"camouflage":true}`), &v); err != nil || !v.blocksCount() || v.InvisibleImmune {
		t.Fatal("snapshot omitted immunity retained previous value")
	}
	s := SpawnSpec{CountVisibility: &CountVisibility{Camouflage: true, InvisibleImmune: true}}
	a := newEnemy(s, 0, [2]float64{}, nil)
	b := newEnemy(s, 1, [2]float64{}, nil)
	a.spec.CountVisibility.InvisibleImmune = false
	if b.spec.CountVisibility.blocksCount() || s.CountVisibility.blocksCount() {
		t.Fatal("immunity expiry changed other instance/template")
	}
}
