package main

import "testing"

func TestWangHitUsesActualSinkWitnessAndDeadGuard(t *testing.T) {
	e := &enemy{hp: 100, index: 7, rebornAt: -1, spec: SpawnSpec{Name: "target"}}
	v := &Verdict{}
	got, err := wangApplyMagicHit(e, nil, 200, 2, v)
	if err != nil || got.Requested != 200 || got.Dealt != 100 || v.DamageDealt != 100 || len(v.Events) != 1 || e.deathTime != 2 {
		t.Fatalf("actual sink %+v %v verdict%+v", got, err, v)
	}
	if _, err := wangApplyMagicHit(e, nil, 200, 3, v); err == nil || v.DamageDealt != 100 || len(v.Events) != 1 {
		t.Fatal("dead target damaged twice")
	}
	e = &enemy{hp: 100, index: 8, invincible: true, rebornAt: -1}
	v = &Verdict{}
	got, err = wangApplyMagicHit(e, nil, 50, 0, v)
	if err != nil || got.Dealt != 0 || got.Requested != 50 || e.hp != 100 {
		t.Fatal("zero damage witness lost", got, err)
	}
}
func TestWangHitAOEPreflightDeduplicatesCenter(t *testing.T) {
	e := &enemy{hp: 1000, rebornAt: -1, spec: SpawnSpec{RES: 50}}
	cfg := wangRuntimeConfig{DamageScale: 1, PerDamage: .1, PerResistPenetration: 9}
	amounts, err := wangPrepareMagicHits([]*enemy{e}, 1000, cfg, 3)
	if err != nil || len(amounts) != 1 {
		t.Fatal(amounts, err)
	}
	if _, err := wangPrepareMagicHits([]*enemy{e, e}, 1000, cfg, 3); err == nil {
		t.Fatal("cross center double counted")
	}
	if e.hp != 1000 {
		t.Fatal("preflight changed hp")
	}
	e.leaked = true
	if _, err := wangPrepareMagicHits([]*enemy{e}, 1000, cfg, 3); err == nil {
		t.Fatal("leaked enemy accepted")
	}
}
