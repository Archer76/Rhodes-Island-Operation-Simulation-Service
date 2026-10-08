package main

import (
	"encoding/json"
	"fmt"
	"math"
	"rios-sim/mechanisms"
)

// EnemyCountASPD explicitly specifies the source's geometry. Base is the
// Sakiko exception; current follows the active profile's attack range.
type EnemyCountASPD struct {
	Scope   string  `json:"scope"`
	Minimum int     `json:"minimum"`
	Bonus   float64 `json:"bonus"`
}

// CountVisibility is presence-bearing: missing is UNKNOWN, not visible.
// This describes counting only, not ordinary targeting or damage immunity.
type CountVisibility struct {
	Hidden     bool `json:"hidden"`
	Camouflage bool `json:"camouflage"`
}

func (v *CountVisibility) UnmarshalJSON(raw []byte) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return err
	}
	var hidden, camo *bool
	if err := json.Unmarshal(fields["hidden"], &hidden); err != nil {
		return fmt.Errorf("计数hidden状态必须显式提供: %w", err)
	}
	if err := json.Unmarshal(fields["camouflage"], &camo); err != nil {
		return fmt.Errorf("计数camouflage状态必须显式提供: %w", err)
	}
	if hidden == nil || camo == nil {
		return fmt.Errorf("计数状态不能为null")
	}
	v.Hidden = *hidden
	v.Camouflage = *camo
	return nil
}
func validCountRule(r *EnemyCountASPD) bool {
	return r != nil && (r.Scope == "current" || r.Scope == "base") && r.Minimum > 0 && r.Bonus > 0 && !math.IsNaN(r.Bonus) && !math.IsInf(r.Bonus, 0)
}
func countRuleGap(o OperatorSpec, reason string) mechanisms.Gap {
	return mechanisms.Gap{ID: "runtime.enemy_count_attack_speed", Status: "unimplemented", Source: "operator_spec", CharID: o.CharID, Operator: o.Name, Key: "enemy_count_attack_speed", Reason: reason}
}
func sceneUsesCount(spec *Spec) bool {
	for _, o := range spec.Operators {
		if o.EnemyCountAttackSpeed != nil {
			return true
		}
	}
	return false
}
func countVisibilityGap(e SpawnSpec, index int) mechanisms.Gap {
	raw, err := json.Marshal(cloneEnemySources(e.RawSources))
	reason := "敌数攻速缺少完整隐匿/迷彩状态消费者，不能从原始来源默认可计数"
	if err != nil {
		reason += "；原始来源JSON损坏无法编码: " + err.Error()
	}
	return mechanisms.Gap{ID: "runtime.enemy_count_visibility", Status: "unimplemented", Source: "enemy_spec", SourceID: e.EnemyID, Operator: e.Name, Level: e.Level, Instance: index, RawSource: raw, Reason: reason}
}
func countTimingGaps(spec *Spec) []mechanisms.Gap {
	var gaps []mechanisms.Gap
	enabled := false
	for _, o := range spec.Operators {
		if o.EnemyCountAttackSpeed == nil {
			continue
		}
		enabled = true
		if !validCountRule(o.EnemyCountAttackSpeed) || !validAttackTiming(o.AttackTiming) || (o.Active != nil && !validAttackTiming(o.Active.AttackTiming)) {
			gaps = append(gaps, countRuleGap(o, "敌数攻速缺少有效规则或原始计算上下文"))
		}
	}
	if enabled {
		for i, e := range spec.Spawns {
			if e.CountVisibility == nil {
				gaps = append(gaps, countVisibilityGap(e, i))
			}
		}
	}
	return gaps
}

// intervalForEnemies receives an explicit scene. A nil slice is a valid empty
// scene; unlike interval(), it is not an omitted context. Read per operator so
// same-frame preceding kills are immediately reflected.
func (o *operator) intervalForEnemies(enemies []*enemy) (float64, error) {
	r := o.spec.EnemyCountAttackSpeed
	if r == nil {
		return o.interval(), nil
	}
	if !validCountRule(r) {
		return 0, fmt.Errorf("无效敌数攻速规则")
	}
	cells := o.targetRange()
	if r.Scope == "base" {
		cells = o.spec.Range
	}
	n := 0
	for _, e := range enemies {
		if e == nil || e.hp <= 0 || e.leaked || e.offMap {
			continue
		}
		visibility := e.spec.CountVisibility
		if visibility == nil {
			return 0, &mechanisms.IncompleteError{Placeholders: []mechanisms.Gap{countVisibilityGap(e.spec, e.index)}}
		}
		if visibility.Hidden || visibility.Camouflage {
			continue
		}
		cell := [2]int{int(math.RoundToEven(e.position[0])), int(math.RoundToEven(e.position[1]))}
		if inCells(cells, cell) {
			n++
		}
	}
	timing := o.spec.AttackTiming
	if p := o.profile(); p != nil {
		timing = p.AttackTiming
	}
	if !validAttackTiming(timing) {
		return 0, fmt.Errorf("敌数攻速缺少原始计算上下文")
	}
	bonus := o.freeAttackSpeed() + o.hpAttackSpeed()
	if n >= r.Minimum {
		bonus += r.Bonus
	}
	return timingInterval(timing, bonus), nil
}
