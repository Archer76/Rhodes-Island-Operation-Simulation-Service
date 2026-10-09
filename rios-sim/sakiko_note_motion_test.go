package main

import (
	"math"
	"testing"
)

func TestCountSakikoSineFirstSegmentRetirement(t *testing.T) {
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
	for _, bypass := range []bool{false, true} {
		o := selfHealUnit(100)
		o.spec.CharID = st.CharID
		o.spec.ExactModuleTalent = p
		o.spec.SkillRangedExemption = r
		s := sakikoOrdinaryStore{owner: o}
		b, e := s.launchSine(0, [2]float64{}, [2]float64{1, 0}, true, 200, 1)
		if e != nil {
			t.Fatal(e)
		}
		if bypass {
			e = s.update(b.id, .4, false, 0)
		} else {
			_, e = b.acquire(.4, []sakikoNoteCandidate{{0, [2]float64{.6, .1}}})
		}
		if e != nil || s.notes[b.id].state.firstFree {
			t.Fatal("initial tracking did not retire segment", e)
		}
		if e = s.update(b.id, .5, false, -1); e != nil {
			t.Fatal(e)
		}
		before := *s.notes[b.id].state
		if _, e = b.acquire(.6, []sakikoNoteCandidate{{0, [2]float64{.8, .2}}}); e == nil || *s.notes[b.id].state != before {
			t.Fatal("old launch trajectory reused after tracking loss")
		}
	}
}
func TestCountSakikoSineInventoryAcquisitionChain(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		for _, positive := range []bool{false, true} {
			st := &OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1}
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
			b, e := s.launchSine(0, [2]float64{}, [2]float64{1, 0}, positive, 200, 1)
			if e != nil {
				t.Fatal(e)
			}
			sign := -1.0
			if positive {
				sign = 1
			}
			x := .4 * 1.3
			y := sign * .3 * math.Sin(x)
			// Target0 nearest to original launch point, target1 nearest to moving note.
			cs := []sakikoNoteCandidate{{0, [2]float64{0, 0}}, {1, [2]float64{x + .1, y}}}
			pos, e := b.acquire(.4, cs)
			if e != nil || pos != [2]float64{x, y} || s.notes[b.id].state.target != 1 || s.notes[b.id].state.phase != sakikoNoteTracking {
				t.Fatal("acquisition used source instead of moving note", pos, e)
			}
			before := *s.notes[b.id].state
			if _, e = b.acquire(.8, cs); e == nil || *s.notes[b.id].state != before {
				t.Fatal("tracking continued free trajectory")
			}
			target := countedEnemy(1)
			target.index = 1
			target.spec.HP = 1000
			target.hp = 1000
			target.spec.DEF = 100
			target.rebornAt = -1
			want := 104.0
			if ml == 3 {
				want = 105
			}
			got, e := s.hit(.5, b.id, target, 0, 0)
			if e != nil || got != want || target.hp != 1000-want || s.count() != 0 {
				t.Fatal("trajectory to inventory cached damage failed", got, e)
			}
		}
	}
}
func TestCountSakikoSineInventoryBindingRefusal(t *testing.T) {
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
	if _, e = s.launchSine(0, [2]float64{}, [2]float64{}, true, 200, 1); e == nil || s.count() != 0 {
		t.Fatal("invalid motion appended note")
	}
	b, e := s.launchSine(0, [2]float64{}, [2]float64{1, 0}, true, 200, 1)
	if e != nil {
		t.Fatal(e)
	}
	before := *s.notes[b.id].state
	if _, e = b.acquire(7*math.Pi/1.3, nil); e == nil || *s.notes[b.id].state != before {
		t.Fatal("unproved motion mutated inventory")
	}
	s.sourceRetreat()
	if _, e = b.acquire(.4, nil); e == nil || s.count() != 0 {
		t.Fatal("removed note revived through motion")
	}
}
