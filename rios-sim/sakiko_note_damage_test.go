package main

import (
	"math"
	"testing"
)

func TestCountSakikoNotePenetrationRealDamage(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		p, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1})
		if e != nil || p == nil {
			t.Fatal(e)
		}
		o := selfHealUnit(100)
		o.spec.CharID = "char_4182_oblvns"
		o.spec.ExactModuleTalent = p
		for _, n := range []int{0, 1, 12, 30} {
			for _, kind := range []string{"PHYSICAL", "MAGIC", "TRUE"} {
				target := countedEnemy(1)
				target.spec.HP = 1000
				target.hp = 1000
				target.rebornAt = -1
				target.spec.DEF = 100
				target.spec.RES = 50
				got, e := o.consumeSakikoNoteDamage(3, target, 200, kind, n, 0, 0)
				cnt := math.Min(float64(n), 12)
				dp, rp := .04, .02
				if ml == 3 {
					dp, rp = .05, .025
				}
				want := 200.0
				switch kind {
				case "PHYSICAL":
					want = 200 - 100*(1-cnt*dp)
				case "MAGIC":
					want = 200 * (100 - 50*(1-cnt*rp)) / 100
				}
				if e != nil || got != want || target.hp != 1000-want {
					t.Fatal(ml, n, kind, got, want, e)
				}
				if target.spec.DEF != 100 || target.res() != 50 {
					t.Fatal("penetration mutated target attributes")
				}
			}
		}
		target := countedEnemy(1)
		target.spec.HP = 1000
		target.hp = 1000
		target.rebornAt = -1
		target.spec.DEF = 100
		got, e := o.consumeSakikoNoteDamage(4, target, 200, "PHYSICAL", 12, .8, 0)
		if e != nil || got != 200 {
			t.Fatal("additive penetration clamp failed", got, e)
		}
		target.hp = 10
		got, e = o.consumeSakikoNoteDamage(7, target, 200, "TRUE", 0, 0, 0)
		if e != nil || got != 10 || target.deathTime != 7 {
			t.Fatal("real kill state missing", got, e)
		}
	}
}
func TestCountSakikoNoteDamageSourceAndCountRefusal(t *testing.T) {
	chdirRepoRootForData(t)
	p, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: 3, Elite: 2, Level: 60, Potential: 1})
	if e != nil || p == nil {
		t.Fatal(e)
	}
	o := selfHealUnit(100)
	o.spec.CharID = "char_4182_oblvns"
	o.spec.ExactModuleTalent = p
	target := countedEnemy(1)
	hp := target.hp
	if _, e = o.consumeSakikoNoteDamage(1, target, 200, "PHYSICAL", -1, 0, 0); e == nil || target.hp != hp {
		t.Fatal("invalid count mutated target")
	}
	old := p.UpgradeDescription
	p.UpgradeDescription = "tampered"
	if _, e = o.consumeSakikoNoteDamage(1, target, 200, "PHYSICAL", 1, 0, 0); e == nil || target.hp != hp {
		t.Fatal("source tamper authorized")
	}
	p.UpgradeDescription = old
	if _, e = o.consumeSakikoNoteDamage(1, target, 200, "magical", 1, 0, 0); e == nil || target.hp != hp {
		t.Fatal("unknown type authorized")
	}
	o.hp = 0
	if _, e = o.consumeSakikoNoteDamage(1, target, 200, "PHYSICAL", 1, 0, 0); e == nil {
		t.Fatal("source absence persistence assumed")
	}
}
