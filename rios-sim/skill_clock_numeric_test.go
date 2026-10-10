package main

import (
	"math"
	"testing"
)

func TestEventSPUsesExactInputAndStrictReadiness(t *testing.T) {
	for _, kind := range []string{spAttack, spHit} {
		op := hpSpeedUnit()
		op.spec.Skill = &SkillSpec{SPType: kind, SPCost: 1, Increment: .1, AutoTrigger: true, Duration: 1}
		cost := 0.0
		for i := 1; i <= 10; i++ {
			if kind == spAttack {
				spOnAttack(op)
			} else {
				spOnHit(op, 1)
			}
			skillTickFrame([]*operator{op}, float64(i)/30, &Spec{}, &cost, &Verdict{})
			if op.skillActive != (i == 10) {
				t.Fatalf("%s gain%d SP=%g active=%v", kind, i, op.sp, op.skillActive)
			}
		}
	}
	op := hpSpeedUnit()
	op.spec.Skill = &SkillSpec{SPType: spAttack, SPCost: 1, Increment: 0, AutoTrigger: true, Duration: 1}
	op.sp = math.Nextafter(1, 0)
	cost := 0.0
	skillTickFrame([]*operator{op}, 0, &Spec{}, &cost, &Verdict{})
	if op.skillActive {
		t.Fatal("one ULP short SP accepted")
	}
}
