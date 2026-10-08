package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func exactEntelechiaHealRule(t *testing.T) *FriendlyHealRestriction {
	t.Helper()
	chdirRepoRootForData(t)
	r, e := entelechiaFriendlyHealRestriction(&OperatorStats{CharID: "char_4010_etlchi", Elite: 2, Level: 60, Potential: 1})
	if e != nil || r == nil {
		t.Fatal("missing exact restriction", e)
	}
	return r
}
func TestEntelechiaFriendlyHealProductionAndRawRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	for _, pot := range []int{1, 4, 5, 6} {
		for ml := 0; ml <= 3; ml++ {
			module := "uniequip_003_etlchi"
			row := DeployRow{Skill: 1, SkillLevel: 7, PlanIdx: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: "char_4010_etlchi", Elite: 2, Level: 60, Potential: pot}}
			if ml > 0 {
				row.Entry.Module = &module
				row.Entry.ModuleLevel = &ml
			}
			out, e := buildOperatorOut(row, map[string]int{}, "")
			if e != nil {
				t.Fatal(e)
			}
			b, e := json.Marshal(out)
			if e != nil {
				t.Fatal(e)
			}
			var op OperatorSpec
			if e = json.Unmarshal(b, &op); e != nil {
				t.Fatal(e)
			}
			if !validFriendlyHealRestriction(op.CharID, op.FriendlyHealRestriction) {
				t.Fatal("production JSON restriction lost")
			}
			requireSemanticGap(t, op.Placeholders, "trait.blackboard.value", "trait:0")
			if ml > 0 {
				requireSemanticGap(t, op.Placeholders, "module.conditional_attack_speed", module)
			}
			spec := deploymentPrimitiveSpec(1)
			spec.Operators = []OperatorSpec{op}
			n := 0
			for _, g := range specMechanismGaps(spec) {
				if g.ID == "trait.blackboard.value" {
					n++
				}
			}
			if n != 1 {
				t.Fatalf("PlanIdx duplicate trait gap %d", n)
			}
			op.Placeholders = nil
			spec.Operators = []OperatorSpec{op}
			gap := requireSemanticGap(t, specMechanismGaps(spec), "trait.blackboard.value", "trait:0")
			if gap.Description == "" || len(gap.RawBlackboard) != 1 || string(gap.RawSource) != string(op.FriendlyHealRestriction.Trait) {
				t.Fatal("raw trait evidence lost")
			}
			v, e := runSim(spec)
			var inc *mechanisms.IncompleteError
			if v != nil || !errors.As(e, &inc) {
				t.Fatal("raw valid restriction bypassed remaining trait")
			}
		}
	}
}
func TestEntelechiaFriendlyHealSelectionConsumerAndSelfRecovery(t *testing.T) {
	rule := exactEntelechiaHealRule(t)
	medic := hpSpeedUnit()
	medic.spec.HPAttackSpeed = nil
	medic.spec.Heals = true
	medic.hp = 1000
	denied := hpSpeedUnit()
	denied.spec.CharID = "char_4010_etlchi"
	denied.spec.FriendlyHealRestriction = rule
	denied.cell = [2]float64{1, 0}
	denied.hp = 100
	ally := hpSpeedUnit()
	ally.cell = [2]float64{1, 0}
	ally.hp = 300
	if got := pickHeals(medic, []*operator{denied, ally}, 2); len(got) != 1 || got[0] != ally {
		t.Fatal("restriction did not exclude medical target")
	}
	v := &Verdict{}
	if e := operatorsAttack([]*operator{medic, denied, ally}, nil, 1, 1, &Spec{}, v); e != nil {
		t.Fatal(e)
	}
	if denied.hp != 100 || ally.hp != 400 {
		t.Fatalf("medical attack healed forbidden or missed ally: %v %v", denied.hp, ally.hp)
	}
	// Explicit character-healing entry is guarded even if a caller bypasses selection.
	if got := denied.healFromCharacter(medic, 100, v); got != 0 || denied.hp != 100 || v.FriendlyHealsRejected != 1 {
		t.Fatal("direct medical rejection missing")
	}
	if got := ally.healFromCharacter(medic, 100, v); got != 100 || v.FriendlyHealsRejected != 1 {
		t.Fatal("allowed control incorrectly rejected")
	}
	if got := denied.heal(50); got != 50 || denied.hp != 150 {
		t.Fatal("source-free self/environment recovery incorrectly blocked")
	}
	// Deterministic additional-target path (probability 1): no stochastic approximation.
	second := hpSpeedUnit()
	second.cell = [2]float64{1, 0}
	second.hp = 500
	medic.spec.TalentExtraHealProb = 1
	medic.attackTimer = 0
	if e := operatorsAttack([]*operator{medic, denied, ally, second}, nil, 1, 2, &Spec{}, v); e != nil {
		t.Fatal(e)
	}
	if denied.hp != 150 || ally.hp != 600 || second.hp != 600 || v.FriendlyHealsRejected != 1 {
		t.Fatalf("extra target selection/recovery wrong %v %v %v counter%d", denied.hp, ally.hp, second.hp, v.FriendlyHealsRejected)
	}
	self := selfHealUnit(100)
	self.spec.CharID = "char_4010_etlchi"
	self.spec.FriendlyHealRestriction = rule
	cost := 0.0
	selfVerdict := &Verdict{}
	activate(self, 0, &Spec{CostMax: 99}, &cost, selfVerdict, false)
	if self.hp != 500 || len(eventsOf(selfVerdict, "self_heal", "self")) != 1 || selfVerdict.FriendlyHealsRejected != 0 {
		t.Fatal("actual self skill recovery blocked")
	}
	medic.hp = 500
	medic.spec.Range = [][2]int{{0, 0}}
	if got := pickHeals(medic, []*operator{medic}, 1); len(got) != 1 || got[0] != medic {
		t.Fatal("ordinary medic self target lost")
	}
}
func TestEntelechiaFriendlyHealInvalidSourceRefused(t *testing.T) {
	rule := exactEntelechiaHealRule(t)
	for _, mutation := range []func(*FriendlyHealRestriction){func(r *FriendlyHealRestriction) { r.Trait = json.RawMessage(`{}`) }, func(r *FriendlyHealRestriction) {
		var p map[string]any
		if e := json.Unmarshal(r.Trait, &p); e != nil {
			t.Fatal(e)
		}
		p["requiredPotentialRank"] = 1
		r.Trait, _ = json.Marshal(p)
	}} {
		bad := *rule
		mutation(&bad)
		if validFriendlyHealRestriction("char_4010_etlchi", &bad) {
			t.Fatal("mutated restriction accepted")
		}
		op := hpSpeedUnit()
		op.spec.CharID = "char_4010_etlchi"
		op.spec.FriendlyHealRestriction = &bad
		spec := deploymentPrimitiveSpec(1)
		spec.Operators = []OperatorSpec{op.spec}
		requireSemanticGap(t, specMechanismGaps(spec), "runtime.friendly_heal_restriction", "")
		v, e := runSim(spec)
		var inc *mechanisms.IncompleteError
		if v != nil || !errors.As(e, &inc) {
			t.Fatal("invalid raw restriction bypassed guard")
		}
	}
	if validFriendlyHealRestriction("char_4182_oblvns", rule) {
		t.Fatal("wrong owner accepted")
	}
}
