package main

import (
	"math"
	"testing"
)

func TestCountSakikoOrdinaryNoteTurnWeightsAndMagnitude(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		r, e := sakikoSkillRangedExemption(&OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1})
		if e != nil || r == nil {
			t.Fatal(e)
		}
		for _, had := range []bool{false, true} {
			p, e := newSakikoOrdinaryTurn(OperatorSpec{CharID: "char_4182_oblvns", SkillRangedExemption: r}, had)
			if e != nil {
				t.Fatal(e)
			}
			w := 7.0 / 30
			if had {
				w = 1.0 / 6
			}
			got, e := p.next([2]float64{1, 0}, [2]float64{0, 0}, [2]float64{0, 10})
			if e != nil || got != [2]float64{1 - w, w} {
				t.Fatal("weighted direction wrong", got, e)
			}
			if math.Hypot(got[0], got[1]) >= 1 {
				t.Fatal("output wrongly renormalized")
			}
			again, e := p.next(got, [2]float64{}, [2]float64{0, 10})
			if e != nil || again != [2]float64{(1 - w) * (1 - w), w*(1-w) + w} {
				t.Fatal("current magnitude or launch branch overwritten")
			}
			straight, e := p.next([2]float64{1, 0}, [2]float64{}, [2]float64{10, 0})
			if e != nil || straight != [2]float64{1, 0} {
				t.Fatal("aligned control altered")
			}
		}
	}
}
func TestCountSakikoOrdinaryNoteTurnInvalidInputs(t *testing.T) {
	if _, e := newSakikoOrdinaryTurn(OperatorSpec{}, true); e == nil {
		t.Fatal("missing source accepted")
	}
	p := sakikoOrdinaryTurn{weight: 1.0 / 6}
	if _, e := p.next([2]float64{1, 0}, [2]float64{}, [2]float64{}); e == nil {
		t.Fatal("coincident target invented direction")
	}
	if _, e := p.next([2]float64{math.NaN(), 0}, [2]float64{}, [2]float64{1, 0}); e == nil {
		t.Fatal("nonfinite direction accepted")
	}
	if _, e := (sakikoOrdinaryTurn{}).next([2]float64{1, 0}, [2]float64{}, [2]float64{1, 0}); e == nil {
		t.Fatal("uninitialized launch branch accepted")
	}
}
