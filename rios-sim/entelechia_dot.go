package main

import (
	"fmt"
	"math"
	"reflect"
)

// An explicitly supplied periodic-damage event, not a scheduler or effect store.
// Public talent notes exclude this DoT from steal/reapplication and reaper heals.
// Unknown first tick, refresh phase and death/retreat persistence remain refused.
func (o *operator) consumeEntelechiaDOTPulse(t float64, target *enemy, v *Verdict) (float64, error) {
	if math.IsNaN(t) || math.IsInf(t, 0) || t < 0 {
		return 0, fmt.Errorf("萃血持续伤害脉冲时间非法")
	}
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
	raw := bbValue(p.Blackboard, "magic_value", 0)
	resBefore := target.res()
	dmg := resolveDamage(raw, "MAGIC", 1, target.spec.DEF, resBefore, 0)
	got := target.take(dmg, o)
	killed := got > 0 && !target.alive() && !target.pendingReborn()
	if killed {
		target.deathTime = t
	}
	if v != nil {
		v.DamageDealt += got
		v.Events = append(v.Events, Event{T: t, Kind: "entelechia_dot_pulse", Who: o.spec.Name, Damage: &DamageEventDetail{Target: target.spec.Name, TargetIndex: target.index, DamageType: "MAGIC", ResBefore: resBefore, Raw: raw, Resolved: dmg, Dealt: got, HPAfter: target.hp, ModuleID: p.ModuleID, ModuleLevel: p.ModuleLevel, CandidateIndex: p.CandidateIndex}})
		if killed {
			v.Events = append(v.Events, Event{T: t, Kind: "kill", Who: target.spec.Name})
		}
	}
	return got, nil
}
