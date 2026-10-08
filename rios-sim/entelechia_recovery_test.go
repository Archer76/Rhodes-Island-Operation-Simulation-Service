package main

import (
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func TestEntelechiaExactOwnRecoveryPulseAndRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	rule := exactEntelechiaHealRule(t)
	for _, ml := range []int{2, 3} {
		for _, pot := range []int{1, 5} {
			for _, hp := range []float64{100, 990, 1000} {
				source, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: ml, Elite: 2, Level: 60, Potential: pot})
				if e != nil || source == nil {
					t.Fatal(e)
				}
				op := selfHealUnit(hp)
				op.spec.CharID = "char_4010_etlchi"
				op.spec.ExactModuleTalent = source
				op.spec.FriendlyHealRestriction = rule
				v := &Verdict{}
				if got, e := op.consumeEntelechiaRecoveryPulse(1, false, v); e != nil || got != 0 || op.hp != hp || len(v.Events) != 0 {
					t.Fatal("absent effect healed")
				}
				amount := 25.0
				if ml == 3 {
					amount = 35
				}
				want := amount
				if hp+amount > 1000 {
					want = 1000 - hp
				}
				got, e := op.consumeEntelechiaRecoveryPulse(2, true, v)
				if e != nil || got != want || op.hp != hp+want || v.FriendlyHealsRejected != 0 || len(v.Events) != 1 {
					t.Fatal("own recovery pulse incorrectly consumed", got, e)
				}
				h := v.Events[0].Heal
				if h == nil || h.Want != amount || h.Got != want || h.HPAfter != op.hp || h.MaxHP != 1000 {
					t.Fatal("pulse actual recovery witness missing")
				}
				// Selected source is still incomplete and cannot authorize character verdicts.
				spec := deploymentPrimitiveSpec(1)
				spec.Operators = []OperatorSpec{op.spec}
				out, e := runSim(spec)
				var inc *mechanisms.IncompleteError
				if out != nil || !errors.As(e, &inc) {
					t.Fatal("pulse helper erased lifecycle refusal")
				}
			}
		}
	}
}
func TestEntelechiaOwnRecoveryPulseGuards(t *testing.T) {
	chdirRepoRootForData(t)
	r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: 3, Elite: 2, Level: 60, Potential: 5})
	if e != nil || r == nil {
		t.Fatal(e)
	}
	for _, mode := range []string{"dead", "retreated", "wrong_owner", "wrong_derived", "missing_source"} {
		op := selfHealUnit(100)
		op.spec.CharID = "char_4010_etlchi"
		copy := *r
		op.spec.ExactModuleTalent = &copy
		switch mode {
		case "dead":
			op.hp = 0
		case "retreated":
			op.retreated = true
		case "wrong_owner":
			op.spec.CharID = "char_4182_oblvns"
		case "wrong_derived":
			copy.Blackboard = map[string]any{}
		case "missing_source":
			op.spec.ExactModuleTalent = nil
		}
		before := op.hp
		v := &Verdict{}
		got, e := op.consumeEntelechiaRecoveryPulse(1, true, v)
		if got != 0 || op.hp != before || len(v.Events) != 0 {
			t.Fatal("guard mutated state", mode)
		}
		invalid := mode == "wrong_owner" || mode == "wrong_derived" || mode == "missing_source"
		if (e != nil) != invalid {
			t.Fatal("guard error boundary wrong", mode, e)
		}
	}
}
