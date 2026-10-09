package main

import "testing"

func TestWangCombatS2RealHitsSingleCenterAndSlow(t *testing.T) {
	w := wangCombatState{Deployment: wangDeploymentState{Owner: "instance", Config: wangRuntimeConfig{Slot: 2, DamageScale: 1, EffectDuration: 6, SlowFactor: .5, PerDamage: .1, PerResistPenetration: 9}}}
	id, _ := w.Deployment.Field.add("instance", Cell{0, 0}, false, 2)
	w.Deployment.Field.add("instance", Cell{1, 0}, true, 2)
	center := &enemy{hp: 10000, position: [2]float64{0, 0}, rebornAt: -1, spec: SpawnSpec{RES: 50}}
	side := &enemy{hp: 10000, position: [2]float64{3, 0}, rebornAt: -1, spec: SpawnSpec{RES: 50}}
	v := &Verdict{}
	hits, err := w.triggerAOE(id, center, []*enemy{center, side}, 1000, 0, v)
	if err != nil || len(hits) != 2 || len(w.Deployment.Field.stones) != 1 {
		t.Fatal(hits, err)
	}
	if center.hp != side.hp || hits[0].Dealt != hits[1].Dealt || v.DamageDealt != hits[0].Dealt+hits[1].Dealt {
		t.Fatal("center double hit or accounting", hits)
	}
	if w.Slows[center].speed(1, 1) != .5 || w.Slows[side].speed(1, 6) != 1 {
		t.Fatal("slow bridge")
	}
}
func TestWangCombatPreflightRefusalDoesNotConsumeStone(t *testing.T) {
	w := wangCombatState{Deployment: wangDeploymentState{Owner: "instance", Config: wangRuntimeConfig{Slot: 3, DamageScale: 1}}}
	id, _ := w.Deployment.Field.add("instance", Cell{0, 0}, false, 3)
	w.Deployment.Field.add("instance", Cell{1, 0}, true, 3)
	entering := &enemy{hp: 10000, position: [2]float64{1, 1}, rebornAt: -1}
	outside := &enemy{hp: 10000, position: [2]float64{2, 2}, rebornAt: -1}
	v := &Verdict{}
	if _, err := w.triggerAOE(id, entering, []*enemy{outside}, 1000, 0, v); err == nil {
		t.Fatal("outside accepted")
	}
	if len(w.Deployment.Field.stones) != 2 || outside.hp != 10000 || v.DamageDealt != 0 {
		t.Fatal("failed AOE mutated")
	}
	hits, err := w.triggerAOE(id, entering, []*enemy{entering}, 1000, 0, v)
	if err != nil || len(hits) != 1 || len(w.Deployment.Field.stones) != 1 || entering.hp != 9000 {
		t.Fatal("S3 diagonal real damage", hits, err)
	}
}
