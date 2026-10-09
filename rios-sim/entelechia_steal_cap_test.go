package main

import (
	"math"
	"testing"
)

func TestEntelechiaStealSecondTargetCapAndNoHPDrift(t *testing.T) {
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
		first := countedEnemy(1)
		first.spec.HP = 5000
		first.hp = 2500
		step, cap := 100.0, 1800.0
		if ml == 3 {
			step, cap = 120, 2160
		}
		for i := 1; i <= 18; i++ {
			if _, e = s.beforeDamage(float64(i), first, entelechiaStealEligible, true); e != nil {
				t.Fatal(e)
			}
		}
		second := countedEnemy(1)
		second.spec.HP = 5000
		second.hp = 2500
		// Find a definite rounding-sensitive valid HP for this exact capped maximum.
		// Positive control proves the old unconditional expression would change it.
		probe := 1.0
		for i := 1; i < 10000 && probe/o.spec.MaxHP*o.spec.MaxHP == probe; i++ {
			probe = float64(i) / 7
		}
		if probe/o.spec.MaxHP*o.spec.MaxHP == probe {
			t.Fatal("no rounding-sensitive witness; guard not exercised")
		}
		o.hp = probe
		ownBits := math.Float64bits(o.hp)
		for i := 1; i <= 20; i++ {
			got, e := s.beforeDamage(float64(18+i), second, entelechiaStealEligible, true)
			wantAmount := math.Min(float64(i)*step, cap)
			if e != nil || got != 0 || math.Float64bits(o.hp) != ownBits || s.targets[second].amount != wantAmount || second.spec.HP != 5000-wantAmount {
				t.Fatal("second target cap or no-change owner failed", i, got, e)
			}
		}
		if s.targets[first].amount != cap || s.targets[second].amount != cap || first.spec.HP != 5000-cap || second.spec.HP != 5000-cap {
			t.Fatal("per-target cap not independently exercised")
		}
		// Repeat at both caps with independently rounding-sensitive enemy HP.
		enemyProbe := 1.0
		for i := 1; i < 10000 && enemyProbe/second.spec.HP*second.spec.HP == enemyProbe; i++ {
			enemyProbe = float64(i) / 7
		}
		if enemyProbe/second.spec.HP*second.spec.HP == enemyProbe {
			t.Fatal("enemy drift witness absent")
		}
		second.hp = enemyProbe
		enemyBits := math.Float64bits(second.hp)
		if got, e := s.beforeDamage(40, second, entelechiaStealEligible, true); e != nil || got != 0 || math.Float64bits(second.hp) != enemyBits || math.Float64bits(o.hp) != ownBits {
			t.Fatal("capped event changed HP", got, e)
		}
	}
}
