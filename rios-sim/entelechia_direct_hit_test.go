package main

import (
	"math"
	"testing"
)

func TestEntelechiaDirectHitStealsBeforeRealDamage(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1})
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
		target.hp = 100
		target.rebornAt = -1
		target.deathTime = -1
		step := 100.0
		if ml == 3 {
			step = 120
		}
		got, e := s.applyDirectHit(2, target, 90, entelechiaStealEligible, true)
		want := 100 / 1000.0 * (1000 - step)
		if e != nil || got != want || target.hp != 0 || target.deathTime != 2 || target.spec.HP != 1000-step || o.spec.MaxHP != 1000+step || s.amount != step {
			t.Fatal("steal occurred after damage or absent", got, want, e)
		}
		// Excluded targets still take damage, without attribution to the steal channel.
		excluded := countedEnemy(1)
		excluded.spec.HP = 1000
		excluded.hp = 100
		got, e = s.applyDirectHit(3, excluded, 10, entelechiaStealSpecialHP, true)
		if e != nil || got != 10 || excluded.hp != 90 || excluded.spec.HP != 1000 || s.amount != step {
			t.Fatal("excluded target stole or lost direct damage", got, e)
		}
		// Separate DoT pulse consumes selected raw, never recursively invokes this store.
		dot := countedEnemy(1)
		dot.spec.HP = 1000
		dot.hp = 1000
		dot.rebornAt = -1
		before := s.amount
		max := o.spec.MaxHP
		if _, e = o.consumeEntelechiaDOTPulse(4, dot, nil); e != nil || s.amount != before || o.spec.MaxHP != max || dot.spec.HP != 1000 {
			t.Fatal("DOT recursively stole", e)
		}
	}
}
func TestEntelechiaDirectHitRefusalAndCancellation(t *testing.T) {
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
	target.invincible = true
	if got, e := s.applyDirectHit(1, target, 100, entelechiaStealEligible, true); e != nil || got != 0 || s.amount != 0 || target.hp != 500 {
		t.Fatal("cancelled damage stole", got, e)
	}
	target.invincible = false
	if got, e := s.applyDirectHit(1, target, 0, entelechiaStealEligible, true); e != nil || got != 0 || s.amount != 0 {
		t.Fatal("zero damage stole")
	}
	for _, damage := range []float64{-1, math.NaN(), math.Inf(1)} {
		if _, e := s.applyDirectHit(1, target, damage, entelechiaStealEligible, true); e == nil || target.hp != 500 || o.hp != 100 || s.amount != 0 {
			t.Fatal("bad damage mutated")
		}
	}
	if _, e := s.applyDirectHit(1, target, 100, entelechiaStealUnknown, true); e == nil || target.hp != 500 || s.amount != 0 {
		t.Fatal("unknown classification bypassed")
	}
}
