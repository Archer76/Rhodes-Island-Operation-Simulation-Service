package main

import (
	"encoding/json"
	"errors"
	"math"
	"rios-sim/mechanisms"
	"strings"
	"testing"
)

func TestSelfHealExactSourcesAndOtherSemantics(t *testing.T) {
	chdirRepoRootForData(t)
	for _, c := range []struct {
		char, id string
		ratios   []float64
	}{
		{"char_209_ardign", "skcom_heal_self[1]", []float64{.2, .23, .25, .3, .32, .35, .4}},
		{"char_289_gyuki", "skcom_heal_self[2]", []float64{.2, .23, .26, .3, .33, .36, .4, .43, .46, .5}},
		{"char_333_sidero", "skcom_heal_self[3]", []float64{.3, .33, .36, .4, .43, .47, .5, .55, .6, .7}},
	} {
		for index, want := range c.ratios {
			level := index + 1
			meta, err := SkillMetaFor(c.id, level)
			if err != nil {
				t.Fatal(err)
			}
			ratio, ok := instantSelfHealRatio(*meta)
			if !ok || ratio != want {
				t.Fatalf("source %s/%d not claimed: ratio=%g ok=%t meta=%+v", c.id, level, ratio, ok, *meta)
			}
			if gaps := skillMechanismGaps(*meta, c.char, c.char, 1, ""); len(gaps) != 0 {
				t.Fatalf("complete source blocked %+v", gaps)
			}
			sk, _, _, err := bindSkillAtLevelWithInputs(c.char, 1, level, 100, 100, 0, 1000, 0, 1, "PHYSICAL", nil)
			if err != nil {
				t.Fatal(err)
			}
			if sk.SelfHealMaxHPRatio != want {
				t.Fatalf("binding lost ratio %+v", sk)
			}
		}
	}
	for _, id := range []string{"skchr_rdoc_1", "skchr_thorn2_2", "skchr_tiger_2"} {
		meta, err := SkillMetaFor(id, 7)
		if err != nil {
			t.Fatal(err)
		}
		if _, ok := instantSelfHealRatio(*meta); ok {
			t.Fatalf("different semantics claimed %s", id)
		}
		gaps := skillMechanismGaps(*meta, "x", "x", 1, "")
		if len(gaps) == 0 {
			t.Fatalf("unsupported source silently accepted %s", id)
		}
	}
	meta, err := SkillMetaFor("skcom_heal_self[2]", 7)
	if err != nil {
		t.Fatal(err)
	}
	for _, ratio := range []float64{0, -.1, math.NaN(), math.Inf(1), 1.1} {
		changed := *meta
		changed.Blackboard = map[string]any{"heal_scale": ratio}
		if _, ok := instantSelfHealRatio(changed); ok {
			t.Fatalf("invalid ratio claimed %g", ratio)
		}
		if len(skillMechanismGaps(changed, "x", "x", 1, "")) == 0 {
			t.Fatal("changed invalid source lost gap")
		}
	}
}

func TestSelfHealSourceMutationRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	meta, err := SkillMetaFor("skcom_heal_self[2]", 7)
	if err != nil {
		t.Fatal(err)
	}
	zero := 0.0
	second := 1.0
	empty := ""
	base := "x-1"
	for _, mutate := range []func(*SkillMeta){
		func(m *SkillMeta) { m.RangeID = &empty }, func(m *SkillMeta) { m.RangeID = &base },
		func(m *SkillMeta) { m.Duration = &second }, func(m *SkillMeta) { m.Duration = nil },
		func(m *SkillMeta) { m.DurationType = "AMMO" }, func(m *SkillMeta) { m.SkillType = "AUTO" },
		func(m *SkillMeta) { m.RawDescription += "且攻击力提高" },
		func(m *SkillMeta) {
			m.BlackboardEntries = 2
			m.RawBlackboard = append(cloneRawBlackboard(m.RawBlackboard), m.RawBlackboard[0])
		},
		func(m *SkillMeta) { m.Blackboard = map[string]any{"heal_scale": .4, "atk": .1} },
		func(m *SkillMeta) { m.RawBlackboard = []json.RawMessage{json.RawMessage(`{"key":"atk","value":0.4}`)} },
	} {
		changed := *meta
		mutate(&changed)
		if _, ok := instantSelfHealRatio(changed); ok {
			t.Fatalf("mutated source claimed %+v", changed)
		}
		requireSemanticGap(t, skillMechanismGaps(changed, "x", "x", 1, "x-1"), "skill.heal_scale", changed.SkillID)
	}
	changed := *meta
	changed.Duration = &zero
	if _, ok := instantSelfHealRatio(changed); !ok {
		t.Fatal("exact source negative control failed")
	}
}

func TestSelfHealUnsupportedProductionRefuses(t *testing.T) {
	chdirRepoRootForData(t)
	roster := writeTempRoster(t, `[{"name":"因陀罗","charId":"char_155_tiger","elite":2,"level":1,"potential":1}]`)
	plan := json.RawMessage(`{"stage":"main_01-07","deploys":[{"operator":"因陀罗","position":[3,5],"direction":"Up","skill":2}]}`)
	built, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	blob, err := json.Marshal(built.Spec)
	if err != nil {
		t.Fatal(err)
	}
	var spec Spec
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	requireSemanticGap(t, spec.Placeholders, "skill.heal_scale", "skchr_tiger_2")
	if spec.Operators[0].Skill.SelfHealMaxHPRatio != 0 {
		t.Fatal("lifesteal bound as maxHP self-heal")
	}
	v, err := runSim(&spec)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatalf("unsupported source verdict %v/%v", v, err)
	}
}

func selfHealUnit(hp float64) *operator {
	return &operator{hp: hp, spec: OperatorSpec{Name: "self", MaxHP: 1000, Skill: &SkillSpec{SPType: spAuto, SPCost: 10, SelfHealMaxHPRatio: .4}}, sp: 10}
}

func TestSelfHealActivationExactHPAndNoRevival(t *testing.T) {
	for _, c := range []struct{ hp, want float64 }{{100, 500}, {900, 1000}, {1000, 1000}} {
		op := selfHealUnit(c.hp)
		cost := 0.0
		verdict := &Verdict{}
		activate(op, 0, &Spec{CostMax: 99}, &cost, verdict, false)
		if op.hp != c.want || op.sp != 0 || len(eventsOf(verdict, "self_heal", "self")) != 1 {
			t.Fatalf("hp=%g want=%g sp=%g events=%+v", op.hp, c.want, op.sp, verdict.Events)
		}
		detail := verdict.Events[0].Heal
		if detail == nil || detail.Want != 400 || detail.Got != c.want-c.hp || detail.HPAfter != c.want || detail.MaxHP != 1000 {
			t.Fatalf("wrong actual recovery witness %+v", detail)
		}
		deactivate(op)
		if op.hp != c.want {
			t.Fatal("deactivation healed")
		}
	}
	for _, c := range []struct {
		hp        float64
		retreated bool
	}{{0, false}, {100, true}} {
		op := selfHealUnit(c.hp)
		op.retreated = c.retreated
		cost := 0.0
		v := &Verdict{}
		activate(op, 0, &Spec{CostMax: 99}, &cost, v, false)
		if op.hp != c.hp || op.sp != 10 || op.skillActive || len(v.Events) != 0 {
			t.Fatalf("revived or consumed dead activation %+v", op)
		}
	}
	// Explicit raw-spec combination: activation first applies the active cap.
	// No audited real self-heal family currently has a simultaneous max-HP buff.
	op := selfHealUnit(100)
	cap := 2000.0
	op.spec.Active = &Profile{MaxHP: &cap}
	cost := 0.0
	v := &Verdict{}
	activate(op, 0, &Spec{CostMax: 99}, &cost, v, false)
	if op.hp != 1900 {
		t.Fatalf("dynamic cap/order lost hp=%g", op.hp)
	}
	deactivate(op)
	if op.hp != 1000 {
		t.Fatal("cap revert lost")
	}
}

func TestSelfHealOnlySuccessfulActivation(t *testing.T) {
	op := selfHealUnit(100)
	op.autoSkill = true
	op.spec.Skill.Increment = 0
	cost := 0.0
	v := &Verdict{}
	spec := &Spec{CostMax: 99}
	for i := 0; i < 60; i++ {
		skillTick([]*operator{op}, 1.0/30, float64(i)/30, spec, &cost, v)
	}
	if op.hp != 500 || len(eventsOf(v, "self_heal", "self")) != 1 {
		t.Fatalf("healed per frame hp=%g events=%+v", op.hp, v.Events)
	}
	disabled := selfHealUnit(100)
	disabled.spec.Skill = nil
	v = &Verdict{}
	skillTick([]*operator{disabled}, 1, 1, spec, &cost, v)
	if disabled.hp != 100 || len(v.Events) != 0 {
		t.Fatal("no skill healed")
	}
	manual := selfHealUnit(100)
	v = &Verdict{}
	skillTick([]*operator{manual}, 1, 1, spec, &cost, v)
	if manual.hp != 100 || len(v.Events) != 0 {
		t.Fatal("no activation request healed")
	}
}

func TestSelfHealRedeploymentAndWitnessJSON(t *testing.T) {
	spec := deploymentPrimitiveSpec(3)
	addDeploymentPrimitive(spec, "char_self", "self", [2]int{3, 5}, 0, 0)
	addDeploymentPrimitive(spec, "char_self", "self", [2]int{3, 5}, 2, 0)
	for i := range spec.Operators {
		spec.Operators[i].Skill = &SkillSpec{SPType: spAuto, SPCost: 10, InitSP: 10, SelfHealMaxHPRatio: .4}
		spec.Deploys[i].AutoSkill = true
	}
	spec.Retreats = []RetreatSpec{{Time: 1, Operator: "self"}}
	v, err := runSim(spec)
	if err != nil {
		t.Fatal(err)
	}
	if len(eventsOf(v, "self_heal", "self")) != 2 {
		t.Fatalf("redeployment did not rearm instant heal %+v", v.Events)
	}
	blob, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(blob), `"got":0`) {
		t.Fatal("full HP zero recovery witness missing")
	}
	var roundtrip Verdict
	if err := json.Unmarshal(blob, &roundtrip); err != nil {
		t.Fatal(err)
	}
	for _, e := range roundtrip.Events {
		if e.Kind == "self_heal" && (e.Heal == nil || e.Heal.Got != 0 || e.Heal.Want != 400) {
			t.Fatalf("witness JSON lost %+v", e)
		}
	}
	old, err := json.Marshal(Event{T: 0, Kind: "skill", Who: "self"})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(old), "heal") {
		t.Fatalf("old event schema changed %s", old)
	}
}

func TestSelfHealProductionSpecAndRuntime(t *testing.T) {
	chdirRepoRootForData(t)
	roster := writeTempRoster(t, `[{"name":"卡缇","charId":"char_209_ardign","elite":1,"level":55,"potential":1}]`)
	rs, err := ReadRoster(roster)
	if err != nil {
		t.Fatal(err)
	}
	inputs := newBuildInputs("main_01-07", "", "")
	inputs.roster = &rs
	cands, err := CandidatesFor("main_01-07", "", "", CandidatesQuery{inputs: inputs, Operators: []string{"卡缇"}, PerOp: 1})
	if err != nil || len(cands.Rows) != 1 {
		t.Fatalf("candidate %v/%v", cands, err)
	}
	selected := planFromState("main_01-07", cands.Rows, &rs)
	selected.Deploys[0].AutoSkill = true
	plan, err := json.Marshal(selected)
	if err != nil {
		t.Fatal(err)
	}
	built, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	blob, err := json.Marshal(built.Spec)
	if err != nil {
		t.Fatal(err)
	}
	var spec Spec
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	if len(spec.Placeholders) != 0 || spec.Operators[0].Skill.SelfHealMaxHPRatio != .4 {
		t.Fatalf("production source blocked/lost %+v", spec.Placeholders)
	}
	// Force only activation intent, not remove any source/gap. Same genuine spec.
	for i := range spec.Deploys {
		spec.Deploys[i].AutoSkill = true
	}
	v, err := runSim(&spec)
	if err != nil {
		t.Fatal(err)
	}
	if len(eventsOf(v, "self_heal", "卡缇")) == 0 {
		t.Fatal("bound instant recovery never activated")
	}
	actual := 0.0
	for _, event := range v.Events {
		if event.Kind == "self_heal" && event.Who == "卡缇" {
			if event.Heal == nil {
				t.Fatal("runtime witness missing")
			}
			actual += event.Heal.Got
		}
	}
	if actual <= 0 {
		t.Fatal("real battle self heal recovered no HP")
	}
	t.Logf("real C ardign heal activations=%d actualHP=%g deaths=%d", len(eventsOf(v, "self_heal", "卡缇")), actual, v.OperatorDeaths)
	for i := range spec.Deploys {
		spec.Deploys[i].AutoSkill = false
	}
	baseline, err := runSim(&spec)
	if err != nil {
		t.Fatal(err)
	}
	if len(eventsOf(baseline, "self_heal", "卡缇")) != 0 {
		t.Fatal("manual skill activated without request")
	}
}
