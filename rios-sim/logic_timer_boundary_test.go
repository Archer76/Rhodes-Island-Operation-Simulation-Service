package main

import "testing"

// All four consumers must fire on the boundary, not merely sometime afterward.
// The preceding update is a negative control; 2 seconds also guards the already
// correct case while .5, 1 and 9 expose the previous accumulation error.
func TestLogicTimerExactFrameBoundaries(t *testing.T) {
	for _, tc := range []struct {
		seconds float64
		frames  int
	}{{.5, 15}, {1, 30}, {2, 60}, {9, 270}} {
		t.Run(framedBoundaryName(tc.frames), func(t *testing.T) {
			sp := hpSpeedUnit()
			sp.spec.HPAttackSpeed = nil
			sp.spec.Skill = &SkillSpec{SPType: spAuto, SPCost: tc.seconds, Increment: 1, AutoTrigger: true, Duration: 100, MaxCharge: 1}
			shield := hpSpeedUnit()
			shield.spec.HPAttackSpeed = nil
			shield.shieldInterval = tc.seconds
			shield.shieldMaxLayers = 3
			active := hpSpeedUnit()
			active.spec.HPAttackSpeed = nil
			active.spec.Skill = &SkillSpec{Duration: tc.seconds}
			active.skillActive = true
			active.skillTimer = tc.seconds
			target := hpSpeedUnit()
			target.spec.HPAttackSpeed = nil
			foe := &enemy{hp: 1000, spec: SpawnSpec{Interval: tc.seconds, ATK: 1, DamageType: "physical"}, blockedBy: target}
			cost := 0.0
			for update := 1; update <= tc.frames; update++ {
				now := float64(update-1) * gameLogicDT
				skillTickFrame([]*operator{sp, shield, active}, now, &Spec{}, &cost, &Verdict{})
				enemiesAttackFrame([]*operator{target}, []*enemy{foe}, now, &Spec{}, &Verdict{})
				if update < tc.frames {
					if sp.skillActive || shield.shieldLayers != 0 || !active.skillActive || foe.hits != 0 {
						t.Fatalf("early event at update %d", update)
					}
				} else {
					if !sp.skillActive {
						t.Error("SP activation missed exact boundary")
					}
					if shield.shieldLayers != 1 {
						t.Errorf("shield layers=%d at boundary", shield.shieldLayers)
					}
					if active.skillActive {
						t.Error("skill remained active beyond duration")
					}
					if foe.hits != 1 {
						t.Errorf("enemy hits=%d at boundary", foe.hits)
					}
				}
			}
		})
	}
}
func framedBoundaryName(n int) string {
	switch n {
	case 15:
		return "half-second"
	case 30:
		return "one-second"
	case 60:
		return "two-seconds-control"
	case 270:
		return "nine-seconds"
	}
	return "other"
}
