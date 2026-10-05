package main

import (
	"encoding/json"
	"fmt"
	"math"
	"testing"
)

func costPrimitive(init, cap, period float64) *Spec {
	s := deploymentPrimitiveSpec(5)
	s.FPS = 4
	s.CostInit = init
	s.CostMax = cap
	s.CostTime = period
	return s
}
func addCostPrimitive(s *Spec, id string, cost int, at float64, automatic bool) {
	addDeploymentPrimitive(s, id, id, [2]int{len(s.Operators), 0}, at, 0)
	i := len(s.Deploys) - 1
	s.Deploys[i].Cost = cost
	s.Deploys[i].WaitForCost = automatic
}
func costDeployTimes(v *Verdict) map[string]float64 {
	out := map[string]float64{}
	for _, e := range v.Events {
		if e.Kind == "deploy" {
			out[e.Who] = e.T
		}
	}
	return out
}
func runCostPrimitive(t *testing.T, s *Spec) *Verdict {
	t.Helper()
	v, err := runSim(s)
	if err != nil {
		t.Fatal(err)
	}
	return v
}
func assertCostTime(t *testing.T, v *Verdict, id string, want float64) {
	t.Helper()
	got, ok := costDeployTimes(v)[id]
	if !ok || math.Abs(got-want) > 1e-9 {
		t.Fatalf("%s deploy got %v present %v want %v; denied=%v rejected=%v", id, got, ok, want, v.CostDenied, v.DeployRejected)
	}
}

func TestCostInitialBonusUniqueAndSourceClaims(t *testing.T) {
	chdirRepoRootForData(t)
	entry := LoadoutEntry{CharID: "char_102_texas", Elite: 2, Level: 90, Potential: 6}
	rows := []DeployRow{{PlanIdx: 0, Entry: entry}, {PlanIdx: 1, Entry: entry}}
	one, err := squadInitialCostBonus(rows[:1])
	if err != nil {
		t.Fatal(err)
	}
	if one != 2 {
		t.Fatalf("real Texas bonus not exercised: %v", one)
	}
	both, err := squadInitialCostBonus(rows)
	if err != nil || both != one {
		t.Fatalf("duplicate bonus: %v %v", both, err)
	}
	rows[1].Entry.Level = 1
	if _, err := squadInitialCostBonus(rows); err == nil {
		t.Fatal("conflicting initial-cost loadouts accepted")
	}
	source := resolvedTalent{Blackboard: map[string]any{"cost": 3.0, "$marker": "meta"}}
	if gaps := talentMechanismGaps([]resolvedTalent{source}, "x", "X"); len(gaps) != 0 {
		t.Fatal("exact initial cost source falsely refused", gaps)
	}
	source.Blackboard["unknown"] = 1.0
	if gaps := talentMechanismGaps([]resolvedTalent{source}, "x", "X"); len(gaps) == 0 {
		t.Fatal("mixed unknown talent falsely claimed")
	}
}

func TestCostAutomaticUsesEnvironmentAndDiscreteBalance(t *testing.T) {
	for _, c := range []struct {
		scale string
		want  float64
	}{{"0.5", 3.75}, {"2", 0.75}} {
		t.Run(c.scale, func(t *testing.T) {
			env := StageEnv(StageOptions{CostIncreaseTime: 1, MaxCost: 2}, []Rune{{Key: "cbuff_cost_recovery", Blackboard: []BlackboardEntry{{Key: "scale", Value: json.RawMessage(c.scale)}}}}, "NORMAL")
			s := costPrimitive(env.CostInit, env.CostMax, env.CostTime)
			addCostPrimitive(s, "A", 2, 0, true)
			v := runCostPrimitive(t, s)
			assertCostTime(t, v, "A", c.want)
			if len(v.CostDenied) > 0 {
				t.Fatal(v.CostDenied)
			}
		})
	}
	s := costPrimitive(0.5, 99, 1)
	addCostPrimitive(s, "A", 1, 0, true)
	assertCostTime(t, runCostPrimitive(t, s), "A", 0.75)
	s = costPrimitive(0, 99, 0.25)
	addCostPrimitive(s, "A", 1, 0, true)
	assertCostTime(t, runCostPrimitive(t, s), "A", 0)
}

func TestCostAutomaticOrderAndIndependentExplicit(t *testing.T) {
	s := costPrimitive(0, 99, 1)
	addCostPrimitive(s, "A", 3, 0, true)
	addCostPrimitive(s, "B", 1, 0, true)
	addCostPrimitive(s, "C", 1, 0.75, false)
	v := runCostPrimitive(t, s)
	assertCostTime(t, v, "C", 0.75)
	assertCostTime(t, v, "A", 3.75)
	assertCostTime(t, v, "B", 4.75)
	// At the same frame plan order decides which request spends the available DP.
	s = costPrimitive(1, 99, 100)
	addCostPrimitive(s, "A", 1, 0, true)
	addCostPrimitive(s, "B", 1, 0, false)
	v = runCostPrimitive(t, s)
	assertCostTime(t, v, "A", 0)
	if len(v.CostDenied) != 1 {
		t.Fatal("explicit denial missing", v)
	}
	s = costPrimitive(1, 99, 100)
	addCostPrimitive(s, "B", 1, 0, false)
	addCostPrimitive(s, "A", 1, 0, true)
	v = runCostPrimitive(t, s)
	assertCostTime(t, v, "B", 0)
	if _, ok := costDeployTimes(v)["A"]; ok || len(v.DeployRejected) != 1 {
		t.Fatal("automatic wait lost", v)
	}
}

func TestCostCapAndExplicitDenial(t *testing.T) {
	s := costPrimitive(0, 2, 1)
	addCostPrimitive(s, "A", 3, 0, true)
	v := runCostPrimitive(t, s)
	if v.Deployed != 0 || len(v.DeployRejected) != 1 || len(v.CostDenied) != 0 {
		t.Fatal("unexecuted automatic request not named", v)
	}
	s = costPrimitive(0, 3, 1)
	addCostPrimitive(s, "A", 3, 0, true)
	assertCostTime(t, runCostPrimitive(t, s), "A", 2.75)
	s = costPrimitive(0, 99, 1)
	addCostPrimitive(s, "A", 1, 0.5, false)
	v = runCostPrimitive(t, s)
	if v.Deployed != 0 || len(v.CostDenied) != 1 {
		t.Fatal("explicit deadline silently retried", v)
	}
	// Initial cost remains intentionally un-clamped, matching the established rule.
	s = costPrimitive(4, 2, 100)
	addCostPrimitive(s, "A", 3, 0, true)
	assertCostTime(t, runCostPrimitive(t, s), "A", 0)
}

func TestCostAutomaticKillAwardAndGuard(t *testing.T) {
	s := costPrimitive(0, 99, 100)
	addCostPrimitive(s, "killer", 0, 0, false)
	s.Operators[0].ATK = 10
	s.Operators[0].Range = [][2]int{{0, 0}}
	s.Operators[0].DamageType = "physical"
	s.Spawns = append([]SpawnSpec{{Time: 0, Name: "target", HP: 1, KillCost: 3, Interval: 1, LifeCost: 1, Legs: []LegSpec{{Kind: "wait", Seconds: 10}}}}, s.Spawns...)
	addCostPrimitive(s, "waiter", 3, 0, true)
	v := runCostPrimitive(t, s)
	killTime := -1.0
	for _, event := range v.Events {
		if event.Kind == "kill" && event.Who == "target" {
			killTime = event.T
		}
	}
	if killTime < 0 {
		t.Fatalf("kill event not exercised: %v", v.Events)
	}
	assertCostTime(t, v, "waiter", killTime+0.25)
	if v.Kills != 1 {
		t.Fatalf("kill award path unexercised %v", v)
	}
	s = costPrimitive(0, 1, 100)
	addCostPrimitive(s, "blocked", 3, 0, true)
	s.Operators[0].Active = &Profile{DodgePhys: 0.5}
	if v, err := runSim(s); v != nil || err == nil {
		t.Fatal("waiting bypassed incomplete guard")
	}
}

func TestCostAutomaticRejectionsDoNotBlockLaterQueue(t *testing.T) {
	s := costPrimitive(3, 99, 100)
	addCostPrimitive(s, "A", 0, 0, false)
	addCostPrimitive(s, "A", 1, 0, true)
	addCostPrimitive(s, "B", 1, 0, true)
	v := runCostPrimitive(t, s)
	assertCostTime(t, v, "B", 0)
	if len(v.DeployRejected) != 1 || v.DeployRejected[0][2] != "同一干员已在场" {
		t.Fatal(v.DeployRejected)
	}
	s = costPrimitive(3, 99, 100)
	s.DeployLimit = 1
	addCostPrimitive(s, "A", 0, 0, false)
	addCostPrimitive(s, "B", 1, 0, true)
	addCostPrimitive(s, "C", 1, 0, true)
	v = runCostPrimitive(t, s)
	if len(v.DeployRejected) != 2 {
		t.Fatal("full field requests retried/blocked", v.DeployRejected)
	}
}

func TestCostAutomaticSnowUsesActualOwnerNotPlanTime(t *testing.T) {
	for _, init := range []float64{0, 1} {
		t.Run(fmt.Sprint(init), func(t *testing.T) {
			s := costPrimitive(init, 99, 100)
			s.MaxTime = 1
			addCostPrimitive(s, "non-owner", 0, 0, false)
			addCostPrimitive(s, "snow-owner", 1, 0, true)
			s.Mechanisms = []string{"snow.field"}
			s.MechConfig = map[string]json.RawMessage{"snow.field": json.RawMessage(`{"fields":[{"owner":"snow-owner","char_id":"snow-owner","cell":[1,0],"operator_index":1,"ground":[[1,0]],"interval":0.5,"max_layers":5}]}`)}
			v := runCostPrimitive(t, s)
			state := v.MechState["snow.field"].(map[string]any)
			fields := state["fields"].([]map[string]any)
			cells := fields[0]["cells"].([]string)
			if init == 0 {
				if len(cells) != 0 {
					t.Fatal("undeployed owner generated snow", cells)
				}
			} else {
				assertCostTime(t, v, "snow-owner", 0)
				if len(cells) != 1 || cells[0] != "1,0=2" {
					t.Fatal("wrong owner snow", cells)
				}
			}
		})
	}
}

func TestCostPlanOrderForSameFrameAndLegacyTimeOrder(t *testing.T) {
	s := costPrimitive(1, 99, 100)
	addCostPrimitive(s, "plan-first", 1, 0.2, false)
	addCostPrimitive(s, "earlier-deadline", 1, 0.1, false)
	for i := range s.Deploys {
		s.Deploys[i].PlanOrder = true
	}
	v := runCostPrimitive(t, s)
	assertCostTime(t, v, "plan-first", 0.25)
	if len(v.CostDenied) != 1 {
		t.Fatal(v.CostDenied)
	}
	for i := range s.Deploys {
		s.Deploys[i].PlanOrder = false
	}
	v = runCostPrimitive(t, s)
	assertCostTime(t, v, "earlier-deadline", 0.25)
}

func TestCostAutomaticUsesSkillAndRetreatOnNextFrame(t *testing.T) {
	s := costPrimitive(0, 99, 100)
	addCostPrimitive(s, "giver", 0, 0, false)
	s.Operators[0].Skill = &SkillSpec{SPType: spAuto, SPCost: 1, InitSP: 1, MaxCharge: 1, Duration: 1, CostGain: 3}
	s.SkillUses = []SkillUseSpec{{Time: 0.5, Cell: s.Operators[0].Cell}}
	addCostPrimitive(s, "waiter", 3, 0, true)
	v := runCostPrimitive(t, s)
	assertCostTime(t, v, "waiter", 0.75)
	s = costPrimitive(3, 99, 100)
	addCostPrimitive(s, "giver", 3, 0, false)
	s.Operators[0].RetreatRefund = true
	s.Retreats = []RetreatSpec{{Time: 0.5, Operator: "giver"}}
	addCostPrimitive(s, "waiter", 3, 0, true)
	v = runCostPrimitive(t, s)
	assertCostTime(t, v, "waiter", 0.75)
}
