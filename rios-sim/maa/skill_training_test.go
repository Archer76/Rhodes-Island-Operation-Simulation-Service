package maa

import (
	"rios-sim/core"
	"testing"
)

func TestTrainingMaaActualAndConflict(t *testing.T) {
	for mastery := 0; mastery <= 3; mastery++ {
		roster := &core.RosterRead{Entries: []core.RosterEntry{{Name: "石英", CharID: "char_4063_quartz", Elite: 2, Level: 1, SkillLevel: ptr(4), Mastery: map[string]int{"skcom_atk_up[2]": mastery}}}}
		plan := core.PlayPlan{Deploys: []core.DeployOrder{{Operator: "石英", Direction: "Right"}}}
		want := 4
		if mastery > 0 {
			want = 7 + mastery
		}
		ops, err := UsedOperators(plan, roster, nil)
		if err != nil || ops[0].Skill != 1 || ops[0].Mastery != mastery || ops[0].SkillLevel != want {
			t.Fatalf("display %v %v", ops, err)
		}
		job, err := ToMaa(plan, roster, nil, nil, MaaOptions{})
		if err != nil || job.Opers[0].Requirements.SkillLevel != want || job.Opers[0].Skill != 1 {
			t.Fatalf("export %v %v", job, err)
		}
		plan.Deploys[0].MasterySet = true
		plan.Deploys[0].Mastery = (mastery + 1) % 4
		if _, err := ToMaa(plan, roster, nil, nil, MaaOptions{}); err == nil {
			t.Fatal("roster conflict accepted")
		}
	}
	for _, dep := range []core.DeployOrder{{Operator: "玫兰莎", Skill: 1, Mastery: 1}, {Operator: "黑角", Skill: 1}, {Operator: "黑角", Mastery: 1}, {Operator: "石英", Skill: 3}, {Operator: "石英", Mastery: -1}} {
		if _, err := ToMaa(core.PlayPlan{Deploys: []core.DeployOrder{dep}}, nil, nil, nil, MaaOptions{}); err == nil {
			t.Fatalf("unavailable accepted %+v", dep)
		}
	}
	plan := core.PlayPlan{Deploys: []core.DeployOrder{{Operator: "石英", Skill: 1, Mastery: 1}, {Operator: "石英", Skill: 1, Mastery: 2}}}
	if _, err := ToMaa(plan, nil, nil, nil, MaaOptions{}); err == nil {
		t.Fatal("duplicate training merged")
	}
}
