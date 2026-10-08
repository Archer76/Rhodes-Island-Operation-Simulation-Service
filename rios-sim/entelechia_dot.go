package main

import (
	"fmt"
	"reflect"
)

// An explicitly supplied periodic-damage event, not a scheduler or effect store.
// Public talent notes exclude this DoT from steal/reapplication and reaper heals.
// Unknown first tick, refresh phase and death/retreat persistence remain refused.
func (o *operator) consumeEntelechiaDOTPulse(t float64, target *enemy, v *Verdict) (float64, error) {
	if o.spec.CharID != "char_4010_etlchi" || o.spec.ExactModuleTalent == nil {
		return 0, fmt.Errorf("萃血持续伤害事件缺少精确升级来源")
	}
	r := o.spec.ExactModuleTalent
	p, e := resolveExactCountModuleTalentPart(&OperatorStats{CharID: o.spec.CharID, Module: r.ModuleID, ModuleLevel: r.ModuleLevel, Elite: r.Elite, Level: r.Level, Potential: r.Potential}, r.RawPart)
	if e != nil || p == nil || !reflect.DeepEqual(p, r) {
		return 0, fmt.Errorf("萃血持续伤害事件来源或派生载荷不一致")
	}
	// Source absence does not decide scheduled effects after death/retreat.
	if !o.alive() {
		return 0, fmt.Errorf("萃血持续伤害来源离场后的效果存续未证")
	}
	if target == nil || !target.alive() {
		return 0, nil
	}
	dmg := resolveDamage(bbValue(p.Blackboard, "magic_value", 0), "MAGIC", 1, target.spec.DEF, target.res(), 0)
	got := target.take(dmg, o)
	if v != nil {
		v.DamageDealt += got
		v.Events = append(v.Events, Event{T: t, Kind: "entelechia_dot_pulse", Who: o.spec.Name})
		if got > 0 && !target.alive() && !target.pendingReborn() {
			target.deathTime = t
			v.Events = append(v.Events, Event{T: t, Kind: "kill", Who: target.spec.Name})
		}
	}
	return got, nil
}
