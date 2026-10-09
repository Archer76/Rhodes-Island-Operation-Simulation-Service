package main

import (
	"math"
	"testing"
)

func TestEntelechiaStealSourceIdentityChangeRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: 3, Elite: 2, Level: 60, Potential: 1})
	if e != nil {
		t.Fatal(e)
	}
	o := selfHealUnit(100)
	o.spec.CharID = "char_4010_etlchi"
	o.spec.ExactModuleTalent = r
	s, e := newEntelechiaStealStore(o)
	if e != nil {
		t.Fatal(e)
	}
	target := countedEnemy(1)
	target.spec.HP = 1000
	target.hp = 500
	o.spec.CharID = "char_4182_oblvns"
	if got, e := s.beforeDamage(1, target, entelechiaStealEligible, true); e == nil || got != 0 || o.hp != 100 || o.spec.MaxHP != 1000 || target.hp != 500 || target.spec.HP != 1000 || s.amount != 0 || len(s.targets) != 0 {
		t.Fatal("changed owner identity authorized theft", got, e)
	}
}
func TestEntelechiaStealRealMaxHPRatiosAndCaps(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		for _, pot := range []int{1, 5} {
			r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: ml, Elite: 2, Level: 60, Potential: pot})
			if e != nil {
				t.Fatal(e)
			}
			o := selfHealUnit(100)
			o.spec.CharID = "char_4010_etlchi"
			o.spec.ExactModuleTalent = r
			s, e := newEntelechiaStealStore(o)
			if e != nil {
				t.Fatal(e)
			}
			target := countedEnemy(1)
			target.spec.HP = 1000
			target.hp = 500
			step, cap := 100.0, 1800.0
			if ml == 3 {
				step, cap = 120, 2160
			}
			for i := 1; i <= 20; i++ {
				got, e := s.beforeDamage(float64(i), target, entelechiaStealEligible, true)
				amount := math.Min(float64(i)*step, cap)
				prev := math.Min(float64(i-1)*step, cap)
				if e != nil || got != amount-prev || o.spec.MaxHP != 1000+amount || math.Abs(o.hp/(1000+amount)-.1) > 1e-15 || target.spec.HP != math.Max(1, 1000-amount) || math.Abs(target.hp/target.spec.HP-.5) > 1e-15 {
					t.Fatal(i, got, e, o.spec.MaxHP, o.hp, target.spec.HP, target.hp)
				}
			}
			// Enemy at minimum still receives independent debuff counter while own gain
			// has already capped; a different target has its own independent cap.
			next := countedEnemy(1)
			next.spec.HP = 2000
			next.hp = 1000
			if got, e := s.beforeDamage(21, next, entelechiaStealEligible, true); e != nil || got != 0 || next.spec.HP != 2000-step || next.hp != (2000-step)/2 {
				t.Fatal("per-target independent channel wrong", got, e)
			}
			// Recovery consumes the new real maximum, rather than the original panel.
			v := &Verdict{}
			beforeHP := o.hp
			heal, e := o.consumeEntelechiaRecoveryPulse(22, true, v)
			ratio := .025
			if ml == 3 {
				ratio = .035
			}
			wantHeal := (1000 + cap) * ratio
			wantHP := math.Min(1000+cap, beforeHP+wantHeal)
			if e != nil || len(v.Events) != 1 || v.Events[0].Heal == nil || v.Events[0].Heal.Want != wantHeal || heal != wantHP-beforeHP || o.hp != wantHP {
				t.Fatal("stolen max not consumed by recovery", heal, e)
			}
		}
	}
}
func TestEntelechiaStealClassificationAndChannelRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: 3, Elite: 2, Level: 60, Potential: 1})
	if e != nil {
		t.Fatal(e)
	}
	o := selfHealUnit(100)
	o.spec.CharID = "char_4010_etlchi"
	o.spec.ExactModuleTalent = r
	s, e := newEntelechiaStealStore(o)
	if e != nil {
		t.Fatal(e)
	}
	target := countedEnemy(1)
	target.spec.HP = 1000
	target.hp = 500
	for _, c := range []entelechiaStealTargetClass{entelechiaStealDevice, entelechiaStealSpecialHP, entelechiaStealHeartCandle} {
		if got, e := s.beforeDamage(1, target, c, true); e != nil || got != 0 || o.spec.MaxHP != 1000 || target.spec.HP != 1000 || o.hp != 100 || target.hp != 500 {
			t.Fatal("excluded class stole", got, e)
		}
	}
	for _, bad := range []struct {
		time      float64
		class     entelechiaStealTargetClass
		exclusive bool
	}{{1, entelechiaStealUnknown, true}, {math.NaN(), entelechiaStealEligible, true}, {1, entelechiaStealEligible, false}} {
		if _, e := s.beforeDamage(bad.time, target, bad.class, bad.exclusive); e == nil || o.spec.MaxHP != 1000 || target.spec.HP != 1000 || len(s.targets) != 0 {
			t.Fatal("unknown channel accepted")
		}
	}
	if _, e := s.beforeDamage(2, target, entelechiaStealEligible, true); e != nil {
		t.Fatal(e)
	}
	target.spec.HP++
	if _, e := s.beforeDamage(3, target, entelechiaStealEligible, true); e == nil {
		t.Fatal("external target max change accepted")
	}
}
