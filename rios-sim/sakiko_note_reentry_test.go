package main

import (
	"math"
	"testing"
)

func TestCountSakikoSineReentryDelayedFreeUpdateRefusal(t *testing.T) {
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
	b, e := s.launchSine(0, [2]float64{}, [2]float64{1, 0}, true, 200, 1)
	if e != nil {
		t.Fatal(e)
	}
	if e = s.update(b.id, .4, false, 0); e != nil {
		t.Fatal(e)
	}
	if e = s.update(b.id, .5, false, -1); e != nil {
		t.Fatal(e)
	}
	if e = s.update(b.id, .6, false, -1); e != nil {
		t.Fatal(e)
	}
	n := s.notes[b.id].state
	before := *n
	if n.freeEntered != .5 || n.lastUpdate != .6 {
		t.Fatal("entry time overwritten")
	}
	for _, t2 := range []float64{.5, .6} {
		if _, e = b.reenter(t2, [2]float64{10, 10}, [2]float64{1, 0}, true); e == nil || *n != before || b.reentered {
			t.Fatal("delayed construction authorized or mutated state")
		}
	}
}
func TestCountSakikoSineReentryGenerationAndCache(t *testing.T) {
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
	first, e := s.launchSine(0, [2]float64{}, [2]float64{1, 0}, true, 200, 1)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = first.acquire(.4, []sakikoNoteCandidate{{0, [2]float64{.6, .1}}}); e != nil {
		t.Fatal(e)
	}
	if e = s.update(first.id, .5, false, -1); e != nil {
		t.Fatal(e)
	}
	before := *s.notes[first.id].state
	if _, e = first.reenter(.6, [2]float64{10, 10}, [2]float64{0, 1}, false); e == nil || *s.notes[first.id].state != before {
		t.Fatal("delayed reentry invented origin time")
	}
	second, e := first.reenter(.5, [2]float64{10, 10}, [2]float64{0, 1}, false)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = first.reenter(.5, [2]float64{99, 99}, [2]float64{1, 0}, true); e == nil {
		t.Fatal("duplicate reentry rerolled trajectory")
	}
	t2 := .55
	elapsed := t2 - .5
	x := elapsed * 1.3
	y := -.3 * math.Sin(x)
	pos := [2]float64{10 - y, 10 + x}
	gotPos, e := second.acquire(t2, []sakikoNoteCandidate{{1, [2]float64{pos[0] + .1, pos[1]}}})
	if e != nil || gotPos != pos || s.notes[first.id].state.firstFree || s.notes[first.id].state.target != 1 {
		t.Fatal("reentry did not use new origin or repeated initial delay", gotPos, e)
	}
	if e = s.update(first.id, .6, false, -1); e != nil {
		t.Fatal(e)
	}
	before = *s.notes[first.id].state
	if _, e = second.acquire(.61, nil); e == nil || *s.notes[first.id].state != before {
		t.Fatal("old reentry segment drove next generation")
	}
	third, e := second.reenter(.6, [2]float64{20, 0}, [2]float64{1, 0}, true)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = third.acquire(.65, []sakikoNoteCandidate{{2, [2]float64{20.1, 0}}}); e != nil {
		t.Fatal(e)
	}
	o.spec.ATK = 9999
	target := countedEnemy(1)
	target.index = 2
	target.spec.HP = 1000
	target.hp = 1000
	target.spec.DEF = 100
	target.rebornAt = -1
	got, e := s.hit(.7, first.id, target, 0, 0)
	if e != nil || got != 105 || target.hp != 895 || s.count() != 0 || len(s.notes) != 1 {
		t.Fatal("reentry spawned or changed cached note", got, e)
	}
}
