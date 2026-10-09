package main

import (
	"math"
	"strings"
	"testing"
)

func TestEntelechiaPulseInvalidTimeNoEffects(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1})
		if e != nil || r == nil {
			t.Fatal(e)
		}
		for _, now := range []float64{-1, math.NaN(), math.Inf(1), math.Inf(-1)} {
			o := selfHealUnit(100)
			o.spec.CharID = "char_4010_etlchi"
			o.spec.ExactModuleTalent = r
			target := countedEnemy(1)
			target.hp = 10
			target.spec.HP = 1000
			target.rebornAt = -1
			target.deathTime = -1
			v := &Verdict{DamageDealt: 7, Events: []Event{{T: 0, Kind: "sentinel"}}}
			hp := o.hp
			if got, e := o.consumeEntelechiaDOTPulse(now, target, v); e == nil || !strings.Contains(e.Error(), "时间非法") || got != 0 || target.hp != 10 || target.deathTime != -1 || o.hp != hp || v.DamageDealt != 7 || len(v.Events) != 1 {
				t.Fatal("invalid time applied DOT", now, got, e)
			}
			if got, e := o.consumeEntelechiaRecoveryPulse(now, true, v); e == nil || !strings.Contains(e.Error(), "时间非法") || got != 0 || o.hp != hp || len(v.Events) != 1 {
				t.Fatal("invalid time applied recovery", now, got, e)
			}
			// No-effect branches must not silently accept an invalid timestamp.
			if _, e := o.consumeEntelechiaRecoveryPulse(now, false, nil); e == nil {
				t.Fatal("absent effect accepted invalid time")
			}
			if _, e := o.consumeEntelechiaDOTPulse(now, nil, nil); e == nil {
				t.Fatal("absent target accepted invalid time")
			}
		}
		// Valid zero is a local-event boundary, not proof the game schedules a first tick here.
		o := selfHealUnit(100)
		o.spec.CharID = "char_4010_etlchi"
		o.spec.ExactModuleTalent = r
		target := countedEnemy(1)
		target.hp = 10
		target.spec.HP = 1000
		target.rebornAt = -1
		target.deathTime = -1
		v := &Verdict{}
		if got, e := o.consumeEntelechiaDOTPulse(0, target, v); e != nil || got != 10 || target.deathTime != 0 || len(v.Events) != 2 || v.Events[0].T != 0 {
			t.Fatal("valid time control did not kill", got, e)
		}
		if got, e := o.consumeEntelechiaRecoveryPulse(0, true, v); e != nil || got <= 0 || v.Events[len(v.Events)-1].T != 0 {
			t.Fatal("valid time control did not heal", got, e)
		}
	}
}
