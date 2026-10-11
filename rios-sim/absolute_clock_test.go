package main

import (
	"math"
	"testing"
)

func TestAbsoluteFrame23ProductionRequests(t *testing.T) {
	for _, tc := range []struct {
		name  string
		at    float64
		frame int
	}{{"grid", 23.0 / 30, 23}, {"upper", math.Nextafter(23.0/30, math.Inf(1)), 24}, {"lower", math.Nextafter(23.0/30, 0), 23}} {
		t.Run(tc.name, func(t *testing.T) {
			s := deploymentPrimitiveSpec(2)
			addDeploymentPrimitive(s, "absolute-deploy", "absolute-deploy", [2]int{0, 0}, tc.at, 0)
			addDeploymentPrimitive(s, "absolute-retreat", "absolute-retreat", [2]int{1, 0}, 0, 0)
			s.Retreats = []RetreatSpec{{Operator: "absolute-retreat", Time: tc.at}}
			s.Spawns = append([]SpawnSpec{{Name: "absolute-spawn", Time: tc.at, HP: 1000, ATK: 0, MoveSpeed: 0, Interval: 1, Legs: []LegSpec{{Kind: "wait", Seconds: 10}}, LifeCost: 1}}, s.Spawns...)
			v, err := runSim(s)
			if err != nil {
				t.Fatal(err)
			}
			found := map[string]bool{}
			for _, e := range v.Events {
				if e.Who == "absolute-deploy" && e.Kind == "deploy" || e.Who == "absolute-retreat" && e.Kind == "retreat" || e.Who == "absolute-spawn" && e.Kind == "spawn" {
					found[e.Kind] = true
					if e.T != float64(tc.frame)/30 {
						t.Errorf("%s t=%.17g want frame%d canonical %.17g", e.Kind, e.T, tc.frame, float64(tc.frame)/30)
					}
				}
			}
			for _, kind := range []string{"deploy", "retreat", "spawn"} {
				if !found[kind] {
					t.Errorf("%s not exercised", kind)
				}
			}
		})
	}
}
