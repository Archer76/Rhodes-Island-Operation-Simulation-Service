package main

import (
	"math"
	"testing"
)

func TestCountSakikoOrdinarySineThreePeriods(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		r, e := sakikoSkillRangedExemption(&OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1})
		if e != nil || r == nil {
			t.Fatal(e)
		}
		source := OperatorSpec{CharID: "char_4182_oblvns", SkillRangedExemption: r}
		for _, positive := range []bool{false, true} {
			p, e := newSakikoOrdinarySine(source, 0, [2]float64{2, 3}, [2]float64{0, 2}, positive)
			if e != nil {
				t.Fatal(e)
			}
			for n := 1; n <= 3; n++ {
				x := float64(n-1)*2*math.Pi + math.Pi/2
				got, e := p.position(x / 1.3)
				sgn := -1.0
				if positive {
					sgn = 1
				}
				want := [2]float64{2 - sgn*.3*float64(n), 3 + x}
				if e != nil || math.Abs(got[0]-want[0]) > 1e-14 || math.Abs(got[1]-want[1]) > 1e-14 {
					t.Fatal(n, got, want, e)
				}
			}
			got, e := p.position(0)
			if e != nil || got != [2]float64{2, 3} {
				t.Fatal("entry origin wrong")
			}
			if _, e = p.position(7 * math.Pi / 1.3); e == nil {
				t.Fatal("unproved fourth period allowed")
			}
			// Re-entering movement sets a new local origin/time and resets amplitude.
			q, e := newSakikoOrdinarySine(source, 10, [2]float64{8, 9}, [2]float64{1, 0}, positive)
			if e != nil {
				t.Fatal(e)
			}
			got, e = q.position(10)
			if e != nil || got != [2]float64{8, 9} {
				t.Fatal("reentry retained old origin")
			}
		}
	}
}
func TestCountSakikoOrdinarySineInvalidInputs(t *testing.T) {
	if _, e := newSakikoOrdinarySine(OperatorSpec{}, 0, [2]float64{}, [2]float64{1, 0}, true); e == nil {
		t.Fatal("missing source authorized")
	}
	if _, e := (sakikoOrdinarySine{}).position(0); e == nil {
		t.Fatal("unspecified random outcome allowed")
	}
	p := sakikoOrdinarySine{axis: [2]float64{1, 0}, entered: 1, sign: 1}
	if _, e := p.position(.9); e == nil {
		t.Fatal("time before entry allowed")
	}
	if _, e := p.position(math.Inf(1)); e == nil {
		t.Fatal("nonfinite time allowed")
	}
}
