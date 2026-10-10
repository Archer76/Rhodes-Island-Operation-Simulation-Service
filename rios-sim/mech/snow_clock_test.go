package mech

import (
	"math"
	"rios-sim/timing"
	"testing"
)

func clockSnow(interval float64) *SnowField {
	return &SnowField{spec: SnowFieldSpec{Interval: interval, MaxLayers: 99, Ground: [][2]int{{0, 0}}}, layers: map[[2]int]int{}}
}
func TestSnowFrameCycleExactBoundaryAndNeighbors(t *testing.T) {
	for _, tc := range []struct {
		interval float64
		frames   int
	}{{.5, 15}, {5.5, 165}, {math.Nextafter(.5, math.Inf(1)), 16}, {.51, 16}} {
		f := clockSnow(tc.interval)
		for i := 1; i <= tc.frames; i++ {
			f.tickMode(timing.DT, true)
			want := 0
			if i == tc.frames {
				want = 1
			}
			if f.layers[[2]int{0, 0}] != want {
				t.Fatalf("interval=%g update=%d layers=%d want=%d", tc.interval, i, f.layers[[2]int{0, 0}], want)
			}
		}
	}
	f := clockSnow(.51)
	for i := 1; i <= 46; i++ {
		f.tickMode(timing.DT, true)
	}
	if f.layers[[2]int{0, 0}] != 3 {
		t.Fatal("cycle lost remainder", f.layers)
	}
	legacy := clockSnow(.5)
	legacy.tick(1.5)
	if legacy.layers[[2]int{0, 0}] != 3 {
		t.Fatal("arbitrary dt lost catch-up", legacy.layers)
	}
}
