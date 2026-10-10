package main

import "testing"

func TestRedeploySameIndexAdvancesClockOnce(t *testing.T) {
	s := deploymentPrimitiveSpec(2)
	addDeploymentPrimitive(s, "clock-op", "clock-op", [2]int{0, 0}, 0, 0)
	s.Operators[0].Skill = &SkillSpec{SPType: spAuto, SPCost: 1, Increment: 1, AutoTrigger: true, Duration: 10, MaxCharge: 1}
	s.Retreats = []RetreatSpec{{Time: .5, Operator: "clock-op"}}
	s.Deploys = append(s.Deploys, DeploySpec{Index: 0, CharID: "clock-op", Time: 1, Cost: 1})
	v, err := runSim(s)
	if err != nil {
		t.Fatal(err)
	}
	deploys, skills := 0, 0
	for _, e := range v.Events {
		if e.Kind == "deploy" {
			deploys++
		}
		if e.Kind == "skill" {
			skills++
			if e.T != 59.0/30 {
				t.Fatalf("repeated timer advance: activation=%g want=%g", e.T, 59.0/30)
			}
		}
	}
	if v.Deployed != 2 {
		t.Fatalf("deployment count=%d want2", v.Deployed)
	}
	if deploys != 2 || skills != 1 {
		t.Fatalf("deploys=%d skills=%d", deploys, skills)
	}
}
