package main

import (
	"math"
	"testing"
)

func TestCountSakikoOrdinaryNearestGeometryRefusal(t *testing.T) {
	near := sakikoNoteCandidate{7, [2]float64{.3, 0}}
	far := sakikoNoteCandidate{0, [2]float64{.8, 0}}
	for _, cs := range [][]sakikoNoteCandidate{{near, far}, {far, near}} {
		id, e := nearestSakikoOrdinaryNoteTarget([2]float64{}, cs)
		if e != nil || id != 7 {
			t.Fatal("input order overrides nearest", id, e)
		}
	}
	for _, cs := range [][]sakikoNoteCandidate{nil, {{0, [2]float64{2, 0}}}} {
		id, e := nearestSakikoOrdinaryNoteTarget([2]float64{}, cs)
		if e != nil || id != -1 {
			t.Fatal("empty radius invented target")
		}
	}
	for _, cs := range [][]sakikoNoteCandidate{{{0, [2]float64{.5, 0}}, {1, [2]float64{-.5, 0}}}, {{0, [2]float64{1, 0}}}, {{0, [2]float64{.2, 0}}, {0, [2]float64{.3, 0}}}, {{0, [2]float64{math.NaN(), 0}}}} {
		if _, e := nearestSakikoOrdinaryNoteTarget([2]float64{}, cs); e == nil {
			t.Fatal("unproved or invalid choice allowed")
		}
	}
	// A farther tie is irrelevant once a unique closer target exists.
	id, e := nearestSakikoOrdinaryNoteTarget([2]float64{}, []sakikoNoteCandidate{{0, [2]float64{.5, 0}}, {1, [2]float64{-.5, 0}}, near})
	if e != nil || id != 7 {
		t.Fatal("nonminimum tie blocked unique minimum", id, e)
	}
}
func TestCountSakikoOrdinaryAcquisitionInventoryDamage(t *testing.T) {
	chdirRepoRootForData(t)
	st := &OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: 3, Elite: 2, Level: 60, Potential: 1}
	p, e := resolveExactCountModuleTalent(st)
	if e != nil {
		t.Fatal(e)
	}
	r, e := sakikoSkillRangedExemption(st)
	if e != nil {
		t.Fatal(e)
	}
	o := selfHealUnit(100)
	o.spec.CharID = st.CharID
	o.spec.ExactModuleTalent = p
	o.spec.SkillRangedExemption = r
	s := sakikoOrdinaryStore{owner: o}
	id, e := s.launch(0, -1, 200, 1)
	if e != nil {
		t.Fatal(e)
	}
	before := *s.notes[id].state
	if e = s.acquire(id, .4, [2]float64{}, []sakikoNoteCandidate{{0, [2]float64{1, 0}}}); e == nil || *s.notes[id].state != before {
		t.Fatal("boundary refusal mutated note")
	}
	if e = s.acquire(id, .4, [2]float64{}, []sakikoNoteCandidate{{4, [2]float64{.8, 0}}, {0, [2]float64{.2, 0}}}); e != nil || s.notes[id].state.target != 0 || s.notes[id].state.phase != sakikoNoteTracking {
		t.Fatal("nearest did not reach tracking", e)
	}
	target := countedEnemy(1)
	target.index = 0
	target.hp = 1000
	target.spec.HP = 1000
	target.spec.DEF = 100
	target.rebornAt = -1
	got, e := s.hit(.5, id, target, 0, 0)
	if e != nil || got != 105 || target.hp != 895 || s.count() != 0 {
		t.Fatal("acquisition to real cached damage failed", got, e)
	}
}
