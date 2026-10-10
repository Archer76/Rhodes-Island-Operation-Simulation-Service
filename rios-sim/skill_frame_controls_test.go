package main

import (
	"math"
	"testing"
)

func TestSkillFrameDurationNotRoundedAndStrictNeighbor(t *testing.T) {
	for _, tc := range []struct {
		duration float64
		frames   int
	}{{.51, 16}, {.5, 15}, {math.Nextafter(.5, math.Inf(1)), 16}} {
		op := hpSpeedUnit()
		op.spec.Skill = &SkillSpec{Duration: tc.duration}
		op.skillActive = true
		op.skillTimer = tc.duration
		cost := 0.0
		for i := 1; i <= tc.frames; i++ {
			skillTickFrame([]*operator{op}, float64(i-1)/30, &Spec{}, &cost, &Verdict{})
			if op.skillActive != (i < tc.frames) {
				t.Fatalf("duration=%g update=%d active=%v", tc.duration, i, op.skillActive)
			}
		}
	}
}
func TestSkillFrameDynamicRateChargeCapAndSpend(t *testing.T) {
	op := hpSpeedUnit()
	op.spec.Skill = &SkillSpec{SPType: spAuto, SPCost: 1, Increment: 1, Duration: 10, MaxCharge: 2}
	cost := 0.0
	s := &Spec{}
	v := &Verdict{}
	for i := 0; i < 15; i++ {
		skillTickFrame([]*operator{op}, float64(i)/30, s, &cost, v)
	}
	op.spec.Skill.Increment = 0
	for i := 15; i < 30; i++ {
		skillTickFrame([]*operator{op}, float64(i)/30, s, &cost, v)
	}
	if op.sp != .5 {
		t.Fatal("zero rate moved SP", op.sp)
	}
	op.spec.Skill.Increment = 3
	for i := 30; i < 45; i++ {
		skillTickFrame([]*operator{op}, float64(i)/30, s, &cost, v)
	}
	if op.sp != 2 {
		t.Fatal("charge cap not reached", op.sp)
	}
	op.skillReq = true
	skillTickFrame([]*operator{op}, 1.5, s, &cost, v)
	if !op.skillActive || op.sp != 1 {
		t.Fatal("activation did not spend exactly one charge", op.sp)
	}
	for i := 0; i < 10; i++ {
		skillTickFrame([]*operator{op}, 1.6+float64(i)/30, s, &cost, v)
	}
	if op.sp != 2 {
		t.Fatal("active multi-charge recovery missing", op.sp)
	}
}
