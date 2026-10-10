package main

import (
	"math"
	"testing"
)

func TestDeployTalentSPDoesNotRoundShortValueToReady(t *testing.T) {
	for _, gain := range []float64{math.Ldexp(1, -54), math.Ldexp(1, -53)} {
		s := deploymentPrimitiveSpec(1)
		addDeploymentPrimitive(s, "deploy-sp", "deploy-sp", [2]int{0, 0}, 0, 0)
		s.Operators[0].Skill = &SkillSpec{SPType: spAttack, SPCost: 1, InitSP: math.Nextafter(1, 0), Increment: 0, AutoTrigger: true, Duration: 10, MaxCharge: 1}
		s.Operators[0].TalentDeploySP = gain
		v, err := runSim(s)
		if err != nil {
			t.Fatal(err)
		}
		count := 0
		for _, e := range v.Events {
			if e.Kind == "skill" {
				count++
			}
		}
		want := 0
		if gain == math.Ldexp(1, -53) {
			want = 1
		}
		if count != want {
			t.Fatalf("talent gain=%g skill count=%d want%d", gain, count, want)
		}
	}
}
