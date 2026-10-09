package main

import "testing"

func TestWangS1ActualDOTSnapshotAndIndependentApplications(t *testing.T) {
	w := wangCombatState{Deployment: wangDeploymentState{Owner: "one", Config: wangRuntimeConfig{Slot: 1, DamageScale: 1, EffectDuration: 6.5, PerDamage: .1, PerResistPenetration: 9}}}
	a, _ := w.Deployment.Field.add("one", Cell{0, 0}, false, 1)
	b, _ := w.Deployment.Field.add("one", Cell{1, 0}, false, 1)
	w.Deployment.Field.add("one", Cell{2, 0}, true, 1)
	e := &enemy{hp: 100000, position: [2]float64{0, 0}, rebornAt: -1, spec: SpawnSpec{RES: 50}}
	v := &Verdict{}
	hits, err := w.triggerDOT(a, e, 1000, 0, v)
	if err != nil || len(hits) != 1 || len(w.DOTs) != 1 || e.sluggishTimer != 6.5 {
		t.Fatal(hits, err)
	}
	first := w.DOTs[0].Schedule.Damage
	e.position = [2]float64{1, 0}
	e.spec.RES = 0
	hits, err = w.triggerDOT(b, e, 500, .5, v)
	if err != nil || len(hits) != 1 || len(w.DOTs) != 2 {
		t.Fatal(hits, err)
	}
	if w.DOTs[0].Schedule.Damage != first || w.DOTs[1].Schedule.Damage == first {
		t.Fatal("DOT overwrite/resnapshot")
	}
	hits, err = w.tickDOTs(1, v)
	if err != nil || len(hits) != 1 || hits[0].Requested != first {
		t.Fatal("first tick snapshot changed", hits, err)
	}
	if e.lastHitBy != nil {
		t.Fatal("DOT falsely credited to last ordinary attacker")
	}
}
func TestWangS1RefusalAndTargetDeathCleanup(t *testing.T) {
	w := wangCombatState{Deployment: wangDeploymentState{Owner: "one", Config: wangRuntimeConfig{Slot: 1, DamageScale: 1, EffectDuration: 6.5}}}
	id, _ := w.Deployment.Field.add("one", Cell{0, 0}, false, 1)
	w.Deployment.Field.add("one", Cell{1, 0}, true, 1)
	e := &enemy{hp: 1000, position: [2]float64{1, 1}, rebornAt: -1}
	v := &Verdict{}
	if _, err := w.triggerDOT(id, e, 100, 0, v); err == nil || len(w.Deployment.Field.stones) != 2 || len(w.DOTs) != 0 {
		t.Fatal("bad target consumed")
	}
	e.position = [2]float64{0, 0}
	w.triggerDOT(id, e, 100, 0, v)
	e.hp = 0
	hits, err := w.tickDOTs(2, v)
	if err != nil || len(hits) != 0 || len(w.DOTs) != 0 {
		t.Fatal("dead target effect remains")
	}
}
