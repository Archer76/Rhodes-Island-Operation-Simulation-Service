package main

import (
	"math"
	"testing"
)

func TestFrameFreezeBoundaryAndStrictNeighbor(t *testing.T) {
	for _, tc := range []struct {
		duration float64
		frames   int
	}{{1, 30}, {.5, 15}, {math.Nextafter(1, math.Inf(1)), 31}, {.51, 16}} {
		op := hpSpeedUnit()
		op.freezeTimer = tc.duration
		cost := 0.0
		for i := 1; i <= tc.frames; i++ {
			skillTickFrame([]*operator{op}, float64(i-1)/30, &Spec{}, &cost, &Verdict{})
			if (op.freezeTimer == 0) != (i == tc.frames) {
				t.Fatalf("freeze=%g update=%d remainder=%g", tc.duration, i, op.freezeTimer)
			}
		}
	}
}
