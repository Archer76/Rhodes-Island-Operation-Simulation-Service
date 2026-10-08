package main

import (
	"strings"
	"testing"
)

func TestEntelechiaDOTPulseActualDamageAndNoRecursiveRecovery(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		for _, pot := range []int{1, 5} {
			for _, res := range []float64{0, 50} {
				r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: ml, Elite: 2, Level: 60, Potential: pot})
				if e != nil || r == nil {
					t.Fatal(e)
				}
				o := selfHealUnit(100)
				o.spec.CharID = "char_4010_etlchi"
				o.spec.ExactModuleTalent = r
				target := countedEnemy(1)
				target.spec.HP = 1000
				target.rebornAt = -1
				target.spec.DEF = 9999
				target.spec.RES = res
				amount := 350.0
				if ml == 3 {
					amount = 450
				}
				if pot == 5 {
					amount += 50
				}
				want := amount * (1 - res/100)
				v := &Verdict{}
				got, e := o.consumeEntelechiaDOTPulse(2, target, v)
				if e != nil || got != want || target.hp != 1000-want || v.DamageDealt != want || target.lastHitBy != o {
					t.Fatal("periodic magical damage wrong", got, e)
				}
				if o.hp != 100 || o.spec.MaxHP != 1000 || target.spec.HP != 1000 || len(v.Events) != 1 || v.Events[0].Kind != "entelechia_dot_pulse" || v.Events[0].T != 2 {
					t.Fatal("DoT recursively stole/healed or event wrong")
				}
				target.hp = 10
				got, e = o.consumeEntelechiaDOTPulse(3, target, v)
				if e != nil || got != 10 || target.hp != 0 || target.deathTime != 3 || len(v.Events) != 3 || v.Events[2].Kind != "kill" {
					t.Fatal("kill/actual cap wrong")
				}
			}
		}
	}
}
func TestEntelechiaDOTPulseRefusesUnprovedSourceLifetime(t *testing.T) {
	chdirRepoRootForData(t)
	r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: 3, Elite: 2, Level: 60, Potential: 5})
	if e != nil || r == nil {
		t.Fatal(e)
	}
	for _, mode := range []string{"dead", "retreated", "wrong_source", "invincible", "dead_target"} {
		o := selfHealUnit(100)
		o.spec.CharID = "char_4010_etlchi"
		clone := *r
		o.spec.ExactModuleTalent = &clone
		target := countedEnemy(1)
		switch mode {
		case "dead":
			o.hp = 0
		case "retreated":
			o.retreated = true
		case "wrong_source":
			clone.CandidateIndex = 9
		case "invincible":
			target.invincible = true
		case "dead_target":
			target.hp = 0
		}
		before := target.hp
		v := &Verdict{}
		got, e := o.consumeEntelechiaDOTPulse(1, target, v)
		invalid := mode == "dead" || mode == "retreated" || mode == "wrong_source"
		if (e != nil) != invalid || got != 0 || target.hp != before || v.DamageDealt != 0 {
			t.Fatal("guard changed state", mode, e)
		}
		if (mode == "dead" || mode == "retreated") && (e == nil || !strings.Contains(e.Error(), "存续未证")) {
			t.Fatal("lifetime ambiguity silently ignored")
		}
	}
}
