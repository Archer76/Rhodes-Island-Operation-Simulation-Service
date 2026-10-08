package main

import (
	"fmt"
	"reflect"
)

// Consume exactly one explicitly scheduled own-recovery pulse. No dt scaling,
// effect discovery, tick scheduling or expiry inference is authorized here.
// Public condition: https://prts.wiki/w/隐德来希#天赋 . Lifecycle remains refused.
func (o *operator) consumeEntelechiaRecoveryPulse(t float64, hasEffect bool, v *Verdict) (float64, error) {
	if o.spec.CharID != "char_4010_etlchi" || o.spec.ExactModuleTalent == nil {
		return 0, fmt.Errorf("萃血恢复脉冲缺少精确隐德来希升级来源")
	}
	r := o.spec.ExactModuleTalent
	picked, e := resolveExactCountModuleTalentPart(&OperatorStats{CharID: o.spec.CharID, Module: r.ModuleID, ModuleLevel: r.ModuleLevel, Elite: r.Elite, Level: r.Level, Potential: r.Potential}, r.RawPart)
	if e != nil || picked == nil || !reflect.DeepEqual(picked, r) {
		return 0, fmt.Errorf("萃血恢复脉冲来源或派生载荷不一致")
	}
	if !hasEffect || !o.alive() {
		return 0, nil
	}
	want := o.maxHP() * bbValue(picked.Blackboard, "hp_recovery_per_sec_by_max_hp_ratio", 0)
	got := o.heal(want)
	if v != nil {
		v.Events = append(v.Events, Event{T: t, Kind: "entelechia_recovery_pulse", Who: o.spec.Name, Heal: &HealEventDetail{Want: want, Got: got, HPAfter: o.hp, MaxHP: o.maxHP()}})
	}
	return got, nil
}
