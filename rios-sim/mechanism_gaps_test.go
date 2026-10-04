package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"strings"
	"testing"
)

func TestMechanismSkillSourceAndRawPreservation(t *testing.T) {
	raw := []json.RawMessage{json.RawMessage(`{"key":"future","value":null,"valueStr":"token"}`)}
	meta := SkillMeta{SkillID: "selected", Name: "selected skill", Level: 7, Blackboard: map[string]any{"atk": .2, "future": 0, "$future": "token"}, RawBlackboard: raw}
	gaps := skillMechanismGaps(meta, "char_x", "X", 1, "1-1")
	if len(gaps) != 2 {
		t.Fatalf("gaps=%+v", gaps)
	}
	for _, g := range gaps {
		if g.SourceID != "selected" || g.CharID != "char_x" || len(g.RawBlackboard) != 1 || string(g.RawBlackboard[0]) != string(raw[0]) {
			t.Fatalf("lost source: %+v", g)
		}
	}
	meta.Blackboard = map[string]any{"atk": .2, "def": .1, "cost": 4}
	if g := skillMechanismGaps(meta, "char_x", "X", 1, "1-1"); len(g) != 0 {
		t.Fatalf("supported keys blocked: %+v", g)
	}
	meta.Blackboard = map[string]any{"heal_scale": .1}
	if g := skillMechanismGaps(meta, "char_x", "X", 1, "1-1"); len(g) != 1 || g[0].Status != "unimplemented" {
		t.Fatalf("recognized but unconsumed: %+v", g)
	}
}

func TestMechanismTalentPreciseClaimsAndProbability(t *testing.T) {
	shield := resolvedTalent{Name: "shield", Description: "获得一层护盾，护盾破裂时恢复生命", Blackboard: map[string]any{"max_times": 3, "times": 1, "interval": 9, "hp_ratio": .2, "sp": 2}}
	if g := talentMechanismGaps([]resolvedTalent{shield}, "x", "X"); len(g) != 0 {
		t.Fatalf("shield blocked: %+v", g)
	}
	proc := resolvedTalent{Name: "proc", GroupIndex: 2, CandidateIndex: 1, Blackboard: map[string]any{"prob": .2, "atk_scale": 1.5}}
	g := talentMechanismGaps([]resolvedTalent{proc}, "x", "X")
	if len(g) != 1 || g[0].Status != "unimplemented" || g[0].SourceID != "talent:2:1" {
		t.Fatalf("probability gap: %+v", g)
	}
	proc.Blackboard["prob"] = 1.0
	if g := talentMechanismGaps([]resolvedTalent{proc}, "x", "X"); len(g) != 0 {
		t.Fatalf("deterministic endpoint blocked: %+v", g)
	}
}

func TestMechanismNoVerdictForIncompleteRawSpec(t *testing.T) {
	spec := Spec{Placeholders: []mechanisms.Gap{{ID: "missing", Status: "unimplemented", Source: "skill", Reason: "not built"}}}
	v, err := runSim(&spec)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) || len(incomplete.Placeholders) != 1 {
		t.Fatalf("verdict=%+v err=%v", v, err)
	}
	spec = Spec{Operators: []OperatorSpec{{Name: "X", TalentExtraHealProb: .07}}}
	v, err = runSim(&spec)
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatalf("raw expectation bypassed: %v %v", v, err)
	}
}

func TestMechanismMergePreservesDeployInstances(t *testing.T) {
	a := mechanisms.Gap{ID: "missing", Operator: "X", Instance: 0}
	b := a
	b.Instance = 1
	if gaps := mechanisms.Merge([]mechanisms.Gap{a, b, a}); len(gaps) != 2 {
		t.Fatalf("instance lost: %+v", gaps)
	}
}

func TestMechanismRawProbabilityCannotBypass(t *testing.T) {
	spec := Spec{Operators: []OperatorSpec{{Name: "X", Active: &Profile{DodgePhys: .2}}}}
	if len(specMechanismGaps(&spec)) != 1 {
		t.Fatal("active dodge bypass")
	}
	spec.Operators[0] = OperatorSpec{Name: "X", TalentProcFactor: 1.5, TalentProcProbabilities: []float64{1}, TalentProcScales: []float64{1.5}}
	if g := specMechanismGaps(&spec); len(g) != 0 {
		t.Fatalf("deterministic source blocked: %+v", g)
	}
	for _, factor := range []float64{0, 1} {
		bad := Spec{Operators: []OperatorSpec{{TalentProcFactor: factor, TalentProcProbabilities: []float64{.5, .5}, TalentProcScales: []float64{3, 0}}}}
		if len(specMechanismGaps(&bad)) == 0 {
			t.Fatalf("neutral expectation bypass: %v", factor)
		}
	}
	zero := Spec{Operators: []OperatorSpec{{TalentProcFactor: 0, TalentProcProbabilities: []float64{1}, TalentProcScales: []float64{0}}}}
	if len(specMechanismGaps(&zero)) == 0 {
		t.Fatal("zero damage factor sentinel bypass")
	}
	duplicate := []resolvedTalent{{Name: "A", Blackboard: map[string]any{"prob": 1.0, "duration": 3.0}}, {Name: "B", GroupIndex: 1, Blackboard: map[string]any{"prob": 1.0, "duration": 5.0}}}
	if len(talentMechanismGaps(duplicate, "x", "X")) == 0 {
		t.Fatal("first-only heal dodge lost second source")
	}
	spec.Operators[0].TalentProcProbabilities[0] = 0
	if len(specMechanismGaps(&spec)) == 0 {
		t.Fatal("inconsistent source accepted")
	}
}

func TestMechanismProductionChainAndIncompleteSolve(t *testing.T) {
	chdirRepoRootForData(t)
	roster := writeTempRoster(t, `[{"name":"克洛丝","charId":"char_124_kroos","elite":1,"level":55,"potential":6}]`)
	q := SolveQuery{Roster: roster, Operators: []string{"克洛丝"}, PerOp: 1, MaxOps: 1}
	out, err := Solve("main_01-07", "", q)
	if err != nil || out.Status != "incomplete" || out.Stars != -1 || len(out.Verdict) != 0 || len(out.Placeholders) == 0 || out.Covered.Incomplete == 0 || out.Covered.SimFailed != 0 {
		t.Fatalf("not distinct incomplete: %+v err=%v", out, err)
	}
	plan := json.RawMessage(`{"stage":"main_01-07","deploys":[{"operator":"克洛丝","position":[3,5],"direction":"Up"}]}`)
	built, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	blob, _ := json.Marshal(built.Spec)
	var spec Spec
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	if len(spec.Placeholders) == 0 || len(spec.Operators[0].Placeholders) == 0 {
		t.Fatal("buildspec dropped gaps")
	}
	v, err := runSim(&spec)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatalf("incomplete verdict: %v %v", v, err)
	}
}

func TestMechanismExcludedCandidateKeepsCompletePlan(t *testing.T) {
	chdirRepoRootForData(t)
	roster := writeTempRoster(t, `[{"name":"克洛丝","charId":"char_124_kroos","elite":1,"level":55,"potential":6},{"name":"玫兰莎","charId":"char_208_melan","elite":1,"level":55,"potential":6}]`)
	out, err := Solve("main_01-07", "", SolveQuery{Roster: roster, Operators: []string{"克洛丝", "玫兰莎"}, PerOp: 1, MaxOps: 1})
	if err != nil || out.Status != "complete" || len(out.Plan) == 0 || len(out.Verdict) == 0 || out.Covered.Incomplete == 0 || out.Evaluated == 0 || len(out.Placeholders) == 0 {
		t.Fatalf("complete plan excluded: %+v err=%v", out, err)
	}
}

func TestMechanismResolveOnlyUnlockedAndRaw(t *testing.T) {
	groups := []json.RawMessage{json.RawMessage(`{"candidates":[{"name":"locked","unlockCondition":{"phase":"PHASE_2","level":1},"blackboard":[{"key":"future","value":5}]},{"name":"unlocked","unlockCondition":{"phase":"PHASE_1","level":1},"blackboard":[{"key":"atk","value":0.1}]}]}`)}
	ts := resolveTalents(groups, 1, 30, 1)
	if len(ts) != 1 || ts[0].Name != "unlocked" || ts[0].CandidateIndex != 1 || len(ts[0].RawBlackboard) != 1 {
		t.Fatalf("resolved=%+v", ts)
	}
	if gaps := talentMechanismGaps(ts, "x", "X"); len(gaps) != 0 {
		t.Fatalf("locked talent blocked: %+v", gaps)
	}
}
