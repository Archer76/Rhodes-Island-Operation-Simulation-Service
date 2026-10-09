package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func TestCountSakikoOrdinaryInventoryMixedSourceRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	p := map[int]*ExactModuleTalent{}
	r := map[int]*SkillRangedExemption{}
	for _, ml := range []int{2, 3} {
		st := &OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1}
		var e error
		p[ml], e = resolveExactCountModuleTalent(st)
		if e != nil || p[ml] == nil {
			t.Fatal(e)
		}
		r[ml], e = sakikoSkillRangedExemption(st)
		if e != nil || r[ml] == nil {
			t.Fatal(e)
		}
	}
	o := selfHealUnit(100)
	o.spec.CharID = "char_4182_oblvns"
	s := sakikoOrdinaryStore{owner: o}
	for _, ml := range []int{2, 3} {
		o.spec.SkillRangedExemption = r[ml]
		o.spec.ExactModuleTalent = p[5-ml]
		if _, e := s.launch(0, 0, 200, 1); e == nil || s.count() != 0 {
			t.Fatal("mixed tiers allowed launch")
		}
	}
	o.spec.SkillRangedExemption = r[2]
	o.spec.ExactModuleTalent = p[2]
	// Equivalent formatting is legitimate: validators authenticate canonical JSON.
	original := r[2].Part
	pretty, e := json.MarshalIndent(json.RawMessage(original), "", "  ")
	if e != nil {
		t.Fatal(e)
	}
	r[2].Part = pretty
	id, e := s.launch(0, 0, 200, 1)
	if e != nil {
		t.Fatal("equivalent JSON falsely refused", e)
	}
	r[2].Part = original
	if e = s.update(id, .4, true, -1); e != nil {
		t.Fatal(e)
	}
	target := countedEnemy(1)
	target.index = 0
	hp := target.hp
	o.spec.SkillRangedExemption = r[3]
	o.spec.ExactModuleTalent = p[3]
	if _, e = s.hit(.5, id, target, 0, 0); e == nil || target.hp != hp || s.count() != 1 {
		t.Fatal("post-launch tier change authorized")
	}
}
func TestCountSakikoOrdinaryInventoryHitChain(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		st := &OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1}
		p, e := resolveExactCountModuleTalent(st)
		if e != nil || p == nil {
			t.Fatal(e)
		}
		r, e := sakikoSkillRangedExemption(st)
		if e != nil || r == nil {
			t.Fatal(e)
		}
		o := selfHealUnit(100)
		o.spec.CharID = st.CharID
		o.spec.ExactModuleTalent = p
		o.spec.SkillRangedExemption = r
		store := sakikoOrdinaryStore{owner: o}
		target := countedEnemy(1)
		target.index = 0
		target.hp = 1000
		target.spec.HP = 1000
		target.spec.DEF = 100
		target.rebornAt = -1
		for i := 0; i < 2; i++ {
			id, e := store.launch(0, 0, 200, 1)
			if e != nil || id != i {
				t.Fatal(e)
			}
			if e = store.update(id, .4, true, -1); e != nil {
				t.Fatal(e)
			}
		}
		// Changing owner's attack after launch must not change cached note damage.
		o.spec.ATK = 9999
		dp := .04
		if ml == 3 {
			dp = .05
		}
		first := 200 - 100*(1-2*dp)
		got, e := store.hit(.5, 0, target, 0, 0)
		if e != nil || got != first || store.count() != 1 || target.hp != 1000-first {
			t.Fatal("hitting note excluded or cache reread", got, e)
		}
		second := 200 - 100*(1-dp)
		got, e = store.hit(.6, 1, target, 0, 0)
		if e != nil || got != second || store.count() != 0 || target.hp != 1000-first-second {
			t.Fatal("removed note counted", got, e)
		}
		hp := target.hp
		if _, e = store.hit(.7, 1, target, 0, 0); e == nil || target.hp != hp {
			t.Fatal("duplicate hit dealt twice")
		}
		spec := deploymentPrimitiveSpec(1)
		spec.Operators = []OperatorSpec{o.spec}
		v, e := runSim(spec)
		var inc *mechanisms.IncompleteError
		if v != nil || !errors.As(e, &inc) {
			t.Fatal("inventory authorized incomplete character")
		}
	}
}
func TestCountSakikoOrdinaryInventoryRefusalAndRetreat(t *testing.T) {
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
	a, e := s.launch(0, 0, 100, 1)
	if e != nil {
		t.Fatal(e)
	}
	if e = s.update(a, .4, true, -1); e != nil {
		t.Fatal(e)
	}
	_, e = s.launch(0, -1, 100, 1)
	if e != nil {
		t.Fatal(e)
	}
	target := countedEnemy(1)
	target.index = 1
	hp := target.hp
	if _, e = s.hit(.5, a, target, 0, 0); e == nil || target.hp != hp || s.count() != 2 {
		t.Fatal("wrong target mutated inventory")
	}
	s.sourceRetreat()
	if s.count() != 1 || s.notes[a].state.phase != sakikoNoteTracking {
		t.Fatal("retreat did not preserve only tracking")
	}
	o.hp = 0
	target.index = 0
	if _, e = s.hit(.5, a, target, 0, 0); e == nil || s.count() != 1 || target.hp != hp {
		t.Fatal("retreat penetration persistence assumed")
	}
}
