package main

import (
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func TestCountSakikoOrdinaryNoteStateLifecycle(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		r, e := sakikoSkillRangedExemption(&OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1})
		if e != nil || r == nil {
			t.Fatal(e)
		}
		source := OperatorSpec{CharID: "char_4182_oblvns", SkillRangedExemption: r}
		n, e := newSakikoOrdinaryNote(source, 0, -1)
		if e != nil {
			t.Fatal(e)
		}
		if e = n.update(.05, false, 0); e != nil || n.target != 0 || n.phase != sakikoNoteFree {
			t.Fatal("first free minimum ignored or index0 lost")
		}
		if e = n.update(.1, true, -1); e != nil || n.phase != sakikoNoteTracking {
			t.Fatal("valid target failed tracking transition")
		}
		if e = n.update(.2, false, 9); e != nil || n.phase != sakikoNoteFree || n.target != -1 {
			t.Fatal("lost target did not reenter free")
		}
		if e = n.update(.21, false, 4); e != nil || n.phase != sakikoNoteTracking || n.target != 4 {
			t.Fatal("reentry incorrectly reapplied first-free minimum")
		}
		n.sourceRetreat()
		if n.phase != sakikoNoteTracking {
			t.Fatal("retreat cleared tracking note")
		}
		if e = n.hit(); e != nil || n.phase != sakikoNoteRemoved {
			t.Fatal("ordinary hit did not remove note")
		}
		free, _ := newSakikoOrdinaryNote(source, 0, -1)
		free.sourceRetreat()
		if free.phase != sakikoNoteRemoved {
			t.Fatal("retreat retained free note")
		}
		spec := deploymentPrimitiveSpec(1)
		spec.Operators = []OperatorSpec{source}
		v, e := runSim(spec)
		var inc *mechanisms.IncompleteError
		if v != nil || !errors.As(e, &inc) {
			t.Fatal("state kernel authorized incomplete combat")
		}
	}
}
func TestCountSakikoOrdinaryNoteInvalidTransitions(t *testing.T) {
	if n, e := newSakikoOrdinaryNote(OperatorSpec{}, 0, -1); e == nil || n != nil {
		t.Fatal("missing source allowed note")
	}
	n := &sakikoOrdinaryNote{phase: sakikoNoteFree, born: 1, lastUpdate: 1, firstFree: true, target: -1}
	before := *n
	if e := n.update(.9, false, 0); e == nil || *n != before {
		t.Fatal("backwards update mutated state")
	}
	if e := n.update(2, true, -1); e == nil || *n != before {
		t.Fatal("missing target validity mutated state")
	}
	if e := n.hit(); e == nil || *n != before {
		t.Fatal("free note hit authorized")
	}
}
