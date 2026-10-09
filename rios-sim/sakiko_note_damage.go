package main

import (
	"fmt"
	"math"
	"reflect"
)

// Explicit damage event, not a note inventory or projectile scheduler. Current
// count includes the hitting note (public talent notes). Other penetration is
// supplied explicitly; this local ordinary-attribute path excludes range overrides.
func (o *operator) consumeSakikoNoteDamage(t float64, target *enemy, raw float64, kind string, count int, otherDefPen, otherResPen float64) (float64, error) {
	if o.spec.CharID != "char_4182_oblvns" || o.spec.ExactModuleTalent == nil {
		return 0, fmt.Errorf("祥子音符穿透缺少精确升级来源")
	}
	r := o.spec.ExactModuleTalent
	p, e := resolveExactCountModuleTalentPart(&OperatorStats{CharID: o.spec.CharID, Module: r.ModuleID, ModuleLevel: r.ModuleLevel, Elite: r.Elite, Level: r.Level, Potential: r.Potential}, r.RawPart)
	if e != nil || p == nil || !reflect.DeepEqual(p, r) {
		return 0, fmt.Errorf("祥子音符穿透来源或派生载荷不一致")
	}
	if !o.alive() {
		return 0, fmt.Errorf("祥子离场后的穿透授出存续未证")
	}
	if math.IsNaN(t) || math.IsInf(t, 0) || t < 0 || count < 0 || math.IsNaN(raw) || math.IsInf(raw, 0) || raw < 0 {
		return 0, fmt.Errorf("祥子音符数量或缓存伤害非法")
	}
	for _, v := range []float64{otherDefPen, otherResPen} {
		if math.IsNaN(v) || math.IsInf(v, 0) || v < 0 || v > 1 {
			return 0, fmt.Errorf("祥子外来百分比穿透非法")
		}
	}
	if kind != "PHYSICAL" && kind != "MAGIC" && kind != "TRUE" {
		return 0, fmt.Errorf("祥子音符伤害类型未定义")
	}
	if target == nil || !target.alive() {
		return 0, nil
	}
	n := math.Min(float64(count), bbValue(p.Blackboard, "max_cnt", 0))
	defPen := math.Min(1, otherDefPen+n*bbValue(p.Blackboard, "def_penetrate_ratio", 0))
	resPen := math.Min(1, otherResPen+n*bbValue(p.Blackboard, "magic_resist_penetrate_ratio", 0))
	dmg := resolveDamage(raw, kind, 1, target.spec.DEF*(1-defPen), target.res()*(1-resPen), 0)
	got := target.take(dmg, o)
	if got > 0 && !target.alive() && !target.pendingReborn() {
		target.deathTime = t
	}
	return got, nil
}
