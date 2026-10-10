package main

import (
	"math"
	"testing"
)

func TestManualSkillFirstNotEarlierFrame(t *testing.T) {
	for _, tc := range []struct {
		at    float64
		frame int
	}{{gameLogicDT / 2, 1}, {.51, 16}, {.5, 15}, {math.Nextafter(.5, math.Inf(1)), 16}} {
		s := deploymentPrimitiveSpec(1)
		addDeploymentPrimitive(s, "manual-clock", "manual-clock", [2]int{0, 0}, 0, 0)
		s.Operators[0].Skill = &SkillSpec{SPType: spAuto, SPCost: 1, InitSP: 1, MaxCharge: 1, Duration: 10}
		s.SkillUses = []SkillUseSpec{{Time: tc.at, Cell: [2]int{0, 0}}}
		v, err := runSim(s)
		if err != nil {
			t.Fatal(err)
		}
		count := 0
		for _, e := range v.Events {
			if e.Kind == "skill" {
				count++
				if e.T != float64(tc.frame)*gameLogicDT {
					t.Fatalf("request=%g event=%g wantFrame=%d", tc.at, e.T, tc.frame)
				}
			}
		}
		if count != 1 {
			t.Fatalf("request=%g count=%d", tc.at, count)
		}
	}
}
