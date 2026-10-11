package main

import (
	"math"
	"testing"
)

func TestRedeployDeadlineFrameOriginAndStrictOffset(t *testing.T) {
	for _, tc := range []struct {
		name     string
		start    int
		duration float64
		at       int
		allowed  bool
	}{{"one-boundary", 14, 1, 44, true}, {"one-before", 14, 1, 43, false}, {"seventy-boundary", 251, 70, 2351, true}, {"upper-offset", 60, math.Nextafter(1, math.Inf(1)), 90, false}, {"upper-next-frame", 60, math.Nextafter(1, math.Inf(1)), 91, true}} {
		t.Run(tc.name, func(t *testing.T) {
			s := deploymentPrimitiveSpec(float64(tc.at) / 30)
			addDeploymentPrimitive(s, "cd", "cd", [2]int{0, 0}, 0, tc.duration)
			s.Retreats = []RetreatSpec{{Operator: "cd", Time: float64(tc.start) / 30}}
			s.Deploys = append(s.Deploys, DeploySpec{Index: 0, CharID: "cd", Time: float64(tc.at) / 30, Cost: 1})
			v, err := runSim(s)
			if err != nil {
				t.Fatal(err)
			}
			if (v.Deployed == 2) != tc.allowed {
				t.Fatalf("deployed=%d allowed=%v rejected=%v", v.Deployed, tc.allowed, v.DeployRejected)
			}
			if tc.allowed {
				for _, e := range v.Events {
					if e.Kind == "deploy" && e.T != 0 && e.T != float64(tc.at)/30 {
						t.Fatalf("deployment time=%g", e.T)
					}
				}
			}
			if !tc.allowed && len(v.DeployRejected) != 1 {
				t.Fatalf("missing rejection: %v", v.DeployRejected)
			}
		})
	}
}
