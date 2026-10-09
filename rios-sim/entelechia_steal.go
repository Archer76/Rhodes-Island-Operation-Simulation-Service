package main

import (
	"fmt"
	"math"
	"reflect"
)

// Explicit ordinary successful-damage-before event. Eligibility classification
// is certified by caller, not inferred from names. No generic attack hook yet.
type entelechiaStealTargetClass uint8

const (
	entelechiaStealUnknown entelechiaStealTargetClass = iota
	entelechiaStealEligible
	entelechiaStealDevice
	entelechiaStealSpecialHP
	entelechiaStealHeartCandle
)

type entelechiaStealTarget struct{ base, expected, amount float64 }

// Exclusive single-source attribute channel. Other MAX_HP changes and skill
// profiles must be integrated as final-add channels before this can be general.
type entelechiaStealStore struct {
	owner                  *operator
	source                 *ExactModuleTalent
	base, expected, amount float64
	targets                map[*enemy]entelechiaStealTarget
}

func newEntelechiaStealStore(o *operator) (*entelechiaStealStore, error) {
	if o == nil || o.spec.CharID != "char_4010_etlchi" || o.spec.ExactModuleTalent == nil {
		return nil, fmt.Errorf("萃血偷取缺少精确来源")
	}
	p := o.spec.ExactModuleTalent
	r, e := resolveExactCountModuleTalentPart(&OperatorStats{CharID: o.spec.CharID, Module: p.ModuleID, ModuleLevel: p.ModuleLevel, Elite: p.Elite, Level: p.Level, Potential: p.Potential}, p.RawPart)
	if e != nil || r == nil || !reflect.DeepEqual(r, p) {
		return nil, fmt.Errorf("萃血偷取来源载荷不一致")
	}
	if o.spec.Active != nil || !o.alive() || !validEntelechiaHP(o.spec.MaxHP, o.hp) {
		return nil, fmt.Errorf("萃血偷取其它生命上限通道或来源状态未覆盖")
	}
	return &entelechiaStealStore{owner: o, source: r, base: o.spec.MaxHP, expected: o.spec.MaxHP, targets: map[*enemy]entelechiaStealTarget{}}, nil
}
func validEntelechiaHP(max, hp float64) bool {
	return !math.IsNaN(max) && !math.IsInf(max, 0) && max >= 1 && !math.IsNaN(hp) && !math.IsInf(hp, 0) && hp > 0 && hp <= max
}

// Mutates real maxima and ratio-preserved HP; this is not damage or healing.
// Caller certifies exclusive target MAX_HP channel and no bound overwrite.
func (s *entelechiaStealStore) beforeDamage(t float64, target *enemy, class entelechiaStealTargetClass, exclusive bool) (float64, error) {
	if math.IsNaN(t) || math.IsInf(t, 0) || t < 0 {
		return 0, fmt.Errorf("萃血偷取事件时间非法")
	}
	if s.owner == nil || s.owner.spec.CharID != "char_4010_etlchi" || !s.owner.alive() || !reflect.DeepEqual(s.source, s.owner.spec.ExactModuleTalent) {
		return 0, fmt.Errorf("萃血偷取来源离场或变更后的效果未证")
	}
	if class < entelechiaStealEligible || class > entelechiaStealHeartCandle {
		return 0, fmt.Errorf("萃血偷取目标排除条件未证")
	}
	if class != entelechiaStealEligible {
		return 0, nil
	}
	if !exclusive || s.owner.spec.Active != nil || s.owner.spec.MaxHP != s.expected {
		return 0, fmt.Errorf("萃血偷取多来源或其它上限通道未覆盖")
	}
	if target == nil || !target.alive() {
		return 0, fmt.Errorf("萃血偷取目标不存在或已离场")
	}
	entry, ok := s.targets[target]
	if !ok {
		entry = entelechiaStealTarget{base: target.spec.HP, expected: target.spec.HP}
	}
	if target.spec.HP != entry.expected || !validEntelechiaHP(target.spec.HP, target.hp) || !validEntelechiaHP(s.expected, s.owner.hp) {
		return 0, fmt.Errorf("萃血偷取上限通道变更或血量非法")
	}
	step, cap := bbValue(s.source.Blackboard, "attack@steal_hp", 0), bbValue(s.source.Blackboard, "attack@steal_hp_max", 0)
	own := math.Min(cap, s.amount+step)
	enemyAmount := math.Min(cap, entry.amount+step)
	ownMax := s.base + own
	enemyMax := math.Max(1, entry.base-enemyAmount)
	ownHP, enemyHP := s.owner.hp, target.hp
	// Only a real attribute change resizes HP; capped/no-change events must not
	// introduce a divide-then-multiply rounding update.
	if ownMax != s.expected {
		ownHP = s.owner.hp / s.expected * ownMax
	}
	if enemyMax != entry.expected {
		enemyHP = target.hp / entry.expected * enemyMax
	}
	if !validEntelechiaHP(ownMax, ownHP) || !validEntelechiaHP(enemyMax, enemyHP) {
		return 0, fmt.Errorf("萃血偷取结果血量非法")
	}
	delta := own - s.amount
	s.owner.spec.MaxHP = ownMax
	s.owner.hp = ownHP
	s.amount = own
	s.expected = ownMax
	target.spec.HP = enemyMax
	target.hp = enemyHP
	entry.amount = enemyAmount
	entry.expected = enemyMax
	s.targets[target] = entry
	return delta, nil
}
