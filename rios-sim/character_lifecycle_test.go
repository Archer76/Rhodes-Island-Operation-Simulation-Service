package main

import "testing"

func TestCountSakikoSkillTickEndsRangedExemption(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		rule, e := sakikoSkillRangedExemption(&OperatorStats{CharID: "char_4182_oblvns", Module: "uniequip_002_oblvns", ModuleLevel: ml, Elite: 2, Level: 60, Potential: 1})
		if e != nil || rule == nil {
			t.Fatal(e)
		}
		for _, mode := range []string{"duration", "ammo"} {
			op := hpSpeedUnit()
			op.spec.HPAttackSpeed = nil
			op.spec.CharID = "char_4182_oblvns"
			op.spec.RangedAtkScale = .8
			op.spec.SkillRangedExemption = rule
			op.spec.Skill = &SkillSpec{SPType: spAuto, SPCost: 10, Duration: 1}
			op.sp = 10
			if mode == "ammo" {
				op.spec.Skill.Infinite = true
				op.spec.Skill.Ammo = 1
			}
			cost := 0.0
			v := &Verdict{}
			activate(op, 0, &Spec{CostMax: 99}, &cost, v, false)
			if !op.skillActive || op.rangedScaleFor(countedEnemy(1)) != 1 {
				t.Fatal("activation did not authorize exemption")
			}
			target := countedEnemy(1)
			target.spec.DEF = 30
			if e := operatorsAttack([]*operator{op}, []*enemy{target}, 1, .5, &Spec{}, v); e != nil {
				t.Fatal(e)
			}
			if v.DamageDealt != 70 || v.SkillRangedExemptions != 1 {
				t.Fatal("active attack witness missing")
			}
			skillTick([]*operator{op}, 1, 1, &Spec{CostMax: 99}, &cost, v)
			if op.skillActive || op.skillTimer != 0 || op.ammoLeft != 0 || op.rangedScaleFor(target) != .8 {
				t.Fatal("actual skill end not restored", mode)
			}
			if e := operatorsAttack([]*operator{op}, []*enemy{target}, 1, 2, &Spec{}, v); e != nil {
				t.Fatal(e)
			}
			if v.DamageDealt != 120 || target.hp != 880 || v.SkillRangedExemptions != 1 {
				t.Fatal("post-skill damage/count wrong", mode)
			}
		}
	}
}

func TestEntelechiaRestrictionPreservesRegenSpeedChannel(t *testing.T) {
	rule := exactEntelechiaHealRule(t)
	for _, restricted := range []bool{false, true} {
		owner := hpSpeedUnit()
		owner.spec.HPAttackSpeed = nil
		owner.deploySeq = 1
		owner.spec.RegenAura = &RegenAuraSpec{HPPerSec: 10, Duration: 2}
		target := hpSpeedUnit()
		target.cell = [2]float64{1, 0}
		target.hp = 100
		target.spec.CharID = "char_4010_etlchi"
		if restricted {
			target.spec.FriendlyHealRestriction = rule
		}
		ops := []*operator{owner, target}
		regenAuraTick(ops, 1)
		if target.hp != 110 || target.regenLeft != 1 || target.regenPerSec != 10 || !target.hasRegenGrant(1) {
			t.Fatal("regen grant/first consumption lost")
		}
		regenAuraTick(ops, 1)
		if target.hp != 120 || target.regenLeft != 0 || target.regenPerSec != 0 {
			t.Fatal("regen expiration wrong")
		}
		regenAuraTick(ops, 1)
		if target.hp != 120 {
			t.Fatal("same aura reapplied")
		}
		v := &Verdict{}
		got := target.healFromCharacter(owner, 100, v)
		if restricted {
			if got != 0 || target.hp != 120 || v.FriendlyHealsRejected != 1 {
				t.Fatal("direct heal confused with regen")
			}
		} else {
			if got != 100 || target.hp != 220 || v.FriendlyHealsRejected != 0 {
				t.Fatal("ordinary control lost")
			}
		}
	}
}
