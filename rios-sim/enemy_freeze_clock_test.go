package main

import (
	"math"
	"testing"
)

// Lethal first hit invokes the production blessing writer at frame0; its
// deferred range freeze applies at frame1. The next lethal hit witnesses
// the actual post-decrement enemy attack gate rather than a timer-only view.
func TestEnemyFreezeProductionAttackBoundary(t *testing.T) {
	for _, tc := range []struct {
		name     string
		duration float64
		updates  int
	}{{"one", 1, 30}, {"half", .5, 15}, {"non-grid", .51, 16}, {"upper", math.Nextafter(1, math.Inf(1)), 31}} {
		t.Run(tc.name, func(t *testing.T) {
			s := deploymentPrimitiveSpec(2)
			addDeploymentPrimitive(s, "freeze-target", "freeze-target", [2]int{0, 0}, 0, 0)
			s.Operators[0].BlockCnt = 1
			s.Operators[0].Range = [][2]int{{0, 0}}
			s.Operators[0].BlessingSave = tc.duration
			s.Spawns = []SpawnSpec{{Name: "freeze-attacker", Time: 0, HP: 10000, ATK: 2000, Interval: 1.0 / 30, MoveSpeed: 0, DamageType: "physical", Legs: []LegSpec{{Kind: "wait", Seconds: 10}}, LifeCost: 1}}
			v, err := runSim(s)
			if err != nil {
				t.Fatal(err)
			}
			death := 0
			blessing := 0
			for _, e := range v.Events {
				if e.Kind == "mech" {
					blessing++
				}
				if e.Kind == "death" && e.Who == "freeze-target" {
					death++
					want := float64(1+tc.updates) / 30
					if e.T != want {
						t.Errorf("enemy resumed at=%g want=%g", e.T, want)
					}
				}
			}
			if death != 1 || blessing != 1 {
				t.Fatalf("witness not exercised death=%d blessing=%d events=%v", death, blessing, v.Events)
			}
		})
	}
}
