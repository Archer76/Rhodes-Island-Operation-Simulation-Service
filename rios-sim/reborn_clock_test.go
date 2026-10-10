package main

import (
	"math"
	"testing"
)

func TestRebornProductionDeadlineFromNonzeroFrame(t *testing.T) {
	for _, tc := range []struct {
		delay     float64
		wantFrame int
	}{{1, 32}, {math.Nextafter(1, math.Inf(1)), 33}} {
		s := deploymentPrimitiveSpec(2)
		addDeploymentPrimitive(s, "clock-hit", "clock-hit", [2]int{0, 0}, 0, 0)
		s.Operators[0].ATK = 100
		s.Operators[0].AttackInterval = 1.0 / 30
		s.Operators[0].Range = [][2]int{{0, 0}}
		s.Spawns = []SpawnSpec{{Name: "reborn-clock", Time: 1.0 / 30, HP: 1, ATK: 0, Interval: 100, MoveSpeed: 0, RebornLeft: 1, RebornDelay: tc.delay, RebornHPRatio: 1, Legs: []LegSpec{{Kind: "wait", Seconds: 10}}, LifeCost: 1}}
		s.Spawns[0].RebornSummons = []RebornSummonSpec{{Interval: 1, Count: 1, Template: &SpawnSpec{Name: "reborn-summon-clock", HP: 1000, MoveSpeed: 0, Interval: 100}, Paths: map[string][][2]float64{"0,0": {{0, 0}, {10, 0}}}}}
		v, err := runSim(s)
		if err != nil {
			t.Fatal(err)
		}
		count := 0
		summons := 0
		for _, e := range v.Events {
			if e.Kind == "summon" {
				summons++
				if e.T != 32*gameLogicDT {
					t.Fatalf("summon late/early at %g", e.T)
				}
			}
			if e.Kind == "reborn" {
				count++
				if e.T != float64(tc.wantFrame)*gameLogicDT {
					t.Fatalf("delay=%g event=%g want frame%d", tc.delay, e.T, tc.wantFrame)
				}
			}
		}
		if summons != 1 {
			t.Fatalf("summons=%d want1", summons)
		}
		if count != 1 {
			t.Fatalf("reborn not exercised: %d events=%v", count, v.Events)
		}
	}
}
