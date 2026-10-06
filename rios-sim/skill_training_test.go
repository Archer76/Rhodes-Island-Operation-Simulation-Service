package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"rios-sim/core"
	"rios-sim/mechanisms"
	"testing"
)

func quartzRoster(t *testing.T, level, mastery int) RosterRead {
	t.Helper()
	rs, err := core.ParseRoster(json.RawMessage(fmt.Sprintf(`[{"name":"石英","charId":"char_4063_quartz","elite":2,"level":1,"potential":1,"mainSkillLvl":%d,"mastery":{"skcom_atk_up[2]":%d,"skchr_quartz_2":%d}}]`, level, mastery, mastery)))
	if err != nil {
		t.Fatal(err)
	}
	return rs
}
func TestTrainingRealBindingCacheAndGaps(t *testing.T) {
	chdirRepoRootForData(t)
	inputs := &buildInputs{}
	for _, request := range []int{0, 3, 1, 2, 0, 2, 3} {
		rs := quartzRoster(t, 7, request)
		d := DeployOrder{Operator: "石英", Position: [2]int{3, 5}, Direction: "Up"}
		slot, level, mastery, err := resolveDeploymentSkill(d, rs, "char_4063_quartz", inputs)
		if err != nil || slot != 1 || level != 7+request || mastery != request {
			t.Fatalf("resolve=%d/%d/%d %v", slot, level, mastery, err)
		}
		sk, active, unknown, err := bindSkillAtLevelWithInputs("char_4063_quartz", slot, level, 100, 0, 0, 1000, 100, 2.5, "physical", inputs)
		wantAtk := []float64{150, 160, 170, 180}[request]
		if err != nil || len(unknown) != 0 || active.ATK != wantAtk || sk.Duration != 25 {
			t.Fatalf("binding level%d: %+v %+v %v %v", level, sk, active, unknown, err)
		}
		wantSP, wantInit := 37.0, 5.0
		if request == 3 {
			wantSP, wantInit = 35, 10
		}
		if sk.SPCost != wantSP || sk.InitSP != wantInit {
			t.Fatalf("state level%d %+v", level, sk)
		}
		row := DeployRow{Operator: "石英", Entry: LoadoutEntry{CharID: "char_4063_quartz", Elite: 2}, Skill: 2, SkillLevel: level, Mastery: request}
		gaps, err := operatorMechanismGapsWithInputs(row, &OperatorStats{Name: "石英"}, nil, inputs)
		meta, metaErr := inputs.skillMeta("skchr_quartz_2", level)
		if err != nil || metaErr != nil || len(gaps) == 0 {
			t.Fatalf("gaps=%v err=%v/%v", gaps, err, metaErr)
		}
		for _, gap := range gaps {
			if gap.Source == "skill" && (gap.SourceID != meta.SkillID || gap.Level != level || !reflect.DeepEqual(gap.RawBlackboard, meta.RawBlackboard)) {
				t.Fatalf("lost actual source %+v", gap)
			}
		}
		v, err := runSim(&Spec{Placeholders: gaps})
		var incomplete *mechanisms.IncompleteError
		if v != nil || !errors.As(err, &incomplete) {
			t.Fatalf("unimplemented got verdict %v/%v", v, err)
		}
	}
	if len(inputs.skills) != 8 {
		t.Fatalf("cache keys=%d want8", len(inputs.skills))
	}
	// Independent request and ordinary level below7 use actual data, not a7 fallback.
	rs := quartzRoster(t, 4, 0)
	_, level, _, err := resolveDeploymentSkill(DeployOrder{Operator: "石英"}, rs, "char_4063_quartz", &buildInputs{})
	if err != nil || level != 4 {
		t.Fatalf("ordinary %d %v", level, err)
	}
}

func TestTrainingCandidatesPlanBuildSaveAndCombat(t *testing.T) {
	chdirRepoRootForData(t)
	for mastery := 0; mastery <= 3; mastery++ {
		rs := quartzRoster(t, 7, mastery)
		inputs := newBuildInputs("main_01-07", "", "")
		inputs.roster = &rs
		cands, err := CandidatesFor("main_01-07", "", "", CandidatesQuery{inputs: inputs, Operators: []string{"石英"}, PerOp: 1})
		if err != nil || len(cands.Rows) != 1 {
			t.Fatalf("candidates %+v %v", cands, err)
		}
		c := cands.Rows[0]
		if c.Skill != 1 || c.Mastery != mastery || c.SkillLevel != 7+mastery {
			t.Fatalf("candidate %+v", c)
		}
		plan := planFromState("main_01-07", cands.Rows, &rs)
		plan.Deploys[0].AutoSkill = true // exercise skill activation, not merely base attacks
		blob, err := json.Marshal(plan)
		if err != nil {
			t.Fatal(err)
		}
		var obj map[string]json.RawMessage
		if err := json.Unmarshal(blob, &obj); err != nil {
			t.Fatal(err)
		}
		saved, err := core.ParsePlan(obj)
		if err != nil {
			t.Fatal(err)
		}
		built, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: blob, AllowSkills: true, inputs: inputs})
		if err != nil {
			t.Fatal(err)
		}
		rebuilt, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: mustJSON(saved), AllowSkills: true})
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(built.Spec.Operators, rebuilt.Spec.Operators) {
			t.Fatal("saved plan lost training")
		}
		if len(built.Spec.Placeholders) != 0 {
			t.Fatalf("positive incomplete %v", built.Spec.Placeholders)
		}
		var spec Spec
		if err := json.Unmarshal(mustJSON(built.Spec), &spec); err != nil {
			t.Fatal(err)
		}
		v, err := runSim(&spec)
		if err != nil || v == nil {
			t.Fatalf("combat %v %v", v, err)
		}
		// Paired negative control: disable automatic skill on the identical spec.
		for i := range spec.Deploys {
			spec.Deploys[i].AutoSkill = false
		}
		base, err := runSim(&spec)
		if err != nil || base == nil || v.DamageDealt == base.DamageDealt {
			t.Fatalf("skill did not change combat: mastery%d active=%g base=%v err=%v", mastery, v.DamageDealt, base, err)
		}
		t.Logf("mastery=%d actualLevel=%d won=%v damage=%g kills=%d elapsed=%g", mastery, 7+mastery, v.Won, v.DamageDealt, v.Kills, v.Elapsed)
	}
}

func TestTrainingNegativeControls(t *testing.T) {
	chdirRepoRootForData(t)
	rs := quartzRoster(t, 7, 3)
	for _, d := range []DeployOrder{{Operator: "石英", Mastery: 0, MasterySet: true}, {Operator: "石英", Mastery: 1}, {Operator: "石英", Mastery: 4}, {Operator: "石英", Skill: 3}} {
		if _, _, _, err := resolveDeploymentSkill(d, rs, "char_4063_quartz", nil); err == nil {
			t.Fatalf("accepted %+v", d)
		}
	}
	for _, row := range []DeployRow{{Entry: LoadoutEntry{CharID: "char_4063_quartz"}, Mastery: -1}, {Entry: LoadoutEntry{CharID: "char_4063_quartz"}, Mastery: 3, SkillLevel: 7}, {Entry: LoadoutEntry{CharID: "char_500_noirc"}, Mastery: 1}, {Entry: LoadoutEntry{CharID: "char_500_noirc"}, Skill: 1}} {
		if _, err := deployRowSkillLevel(row); err == nil {
			t.Fatalf("accepted row %+v", row)
		}
	}
	if _, _, _, err := resolveDeploymentSkill(DeployOrder{Operator: "玫兰莎", Mastery: 1}, RosterRead{}, "char_208_melan", nil); err == nil {
		t.Fatal("unavailable mastery fell back7")
	}
	for _, raw := range []string{`{"skills":{"X":[1]}}`, `{"skills":{"X":[1,2,3]}}`, `{"skills":{"X":[1,1.5]}}`, `{"skills":{"X":[1,4]}}`, `{"skills":{"X":[null,null]}}`} {
		var q SolveQuery
		if err := json.Unmarshal([]byte(raw), &q); err == nil {
			t.Fatalf("accepted %s", raw)
		}
	}
	for _, raw := range []string{`{"stage":"s","deploys":[{"operator":"石英","position":[1,1],"skill":1.5}]}`, `{"stage":"s","deploys":[{"operator":"石英","position":[1,1],"skill":-0.5}]}`} {
		var obj map[string]json.RawMessage
		if err := json.Unmarshal([]byte(raw), &obj); err != nil {
			t.Fatal(err)
		}
		if _, err := core.ParsePlan(obj); err == nil {
			t.Fatalf("fractional slot accepted %s", raw)
		}
	}
	var q SolveQuery
	if err := json.Unmarshal([]byte(`{"skills":{"X":[1,3]}}`), &q); err != nil {
		t.Fatal(err)
	}
}
