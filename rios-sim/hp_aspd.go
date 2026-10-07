package main

import (
	"encoding/json"
	"fmt"
	"math"
	"rios-sim/mechanisms"
)

// HPAttackSpeedSpec is owner-local and uses the current maxHP, not the deploy
// snapshot. The comparison is explicitly strict (above, not at least).
type HPAttackSpeedSpec struct {
	AboveRatio float64 `json:"above_ratio"`
	Bonus      float64 `json:"bonus"`
}

func validHPAttackSpeed(h *HPAttackSpeedSpec) bool {
	return h != nil && h.AboveRatio > 0 && h.AboveRatio < 1 && !math.IsNaN(h.AboveRatio) && h.Bonus > 0 && !math.IsNaN(h.Bonus) && !math.IsInf(h.Bonus, 0)
}
func (o *operator) hpAttackSpeed() float64 {
	h := o.spec.HPAttackSpeed
	if h != nil && o.alive() && o.hp > o.maxHP()*h.AboveRatio {
		return h.Bonus
	}
	return 0
}
func exactHPModuleCandidate(charID, moduleID string, ml, pi, ci int, raw json.RawMessage, c moduleSpeedCandidate) bool {
	owners := map[string]string{"uniequip_002_demetr": "char_4037_demetr", "uniequip_003_chyue": "char_2024_chyue"}
	if owners[moduleID] != charID || owners[moduleID] == "" || ml < 1 || ml > 3 || pi != 0 || ci != 0 {
		return false
	}
	if c.UnlockCondition.Phase != "PHASE_2" || c.UnlockCondition.Level != 60 || c.RequiredPotentialRank != 0 || c.AdditionalDescription != nil || c.OverrideDescription == nil || mechanismText(*c.OverrideDescription) != "能够阻挡一个敌人，生命值高于50%时攻击速度+{attack_speed}" || c.Description != nil || c.PrefabKey != nil || c.RangeID != nil || len(c.Blackboard) != 2 {
		return false
	}
	var p struct {
		Target  string `json:"target"`
		IsToken bool   `json:"isToken"`
		ResKey  string `json:"resKey"`
		Game    any    `json:"validInGameTag"`
		Map     any    `json:"validInMapTag"`
	}
	suffix := "demetr_equip_1"
	if moduleID == "uniequip_003_chyue" {
		suffix = "chyue_equip_2"
	}
	if json.Unmarshal(raw, &p) != nil || p.Target != "TRAIT" || p.IsToken || p.Game != nil || p.Map != nil || p.ResKey != fmt.Sprintf("%s_%d_p1", suffix, ml) {
		return false
	}
	expected := map[string]float64{"attack_speed": 10, "hp_ratio": .5}
	for _, braw := range c.Blackboard {
		var b struct {
			Key   string   `json:"key"`
			Value *float64 `json:"value"`
			Text  *string  `json:"valueStr"`
		}
		if json.Unmarshal(braw, &b) != nil || b.Value == nil || b.Text != nil {
			return false
		}
		want, ok := expected[b.Key]
		if !ok || *b.Value != want {
			return false
		}
		delete(expected, b.Key)
	}
	return len(expected) == 0
}

// Find just the exact fixed HP module rule. The general module scan owns all
// unclaimed gaps and shares this predicate, including candidate unlock gates.
func hpModuleSpeed(st *OperatorStats) (*HPAttackSpeedSpec, error) {
	parts, err := moduleParts(st.Module, st.ModuleLevel)
	if err != nil {
		return nil, err
	}
	var result *HPAttackSpeedSpec
	for pi, raw := range parts {
		var p struct {
			Bundle struct {
				Candidates []moduleSpeedCandidate `json:"candidates"`
			} `json:"overrideTraitDataBundle"`
		}
		if err := json.Unmarshal(raw, &p); err != nil {
			return nil, err
		}
		for ci, c := range p.Bundle.Candidates {
			if phaseOf(c.UnlockCondition.Phase) > st.Elite || c.UnlockCondition.Level > st.Level || c.RequiredPotentialRank > st.Potential-1 {
				continue
			}
			if exactHPModuleCandidate(st.CharID, st.Module, st.ModuleLevel, pi, ci, raw, c) {
				if result != nil {
					return nil, fmt.Errorf("重复生命阈值攻速来源")
				}
				result = &HPAttackSpeedSpec{AboveRatio: .5, Bonus: 10}
			}
		}
	}
	return result, nil
}
func hpTimingGaps(op OperatorSpec) []mechanisms.Gap {
	if op.HPAttackSpeed == nil {
		return nil
	}
	reason := ""
	if !validHPAttackSpeed(op.HPAttackSpeed) {
		reason = "生命阈值攻速规则无效"
	} else if !validAttackTiming(op.AttackTiming) || (op.Active != nil && !validAttackTiming(op.Active.AttackTiming)) {
		reason = "生命阈值攻速缺少有效原始计算上下文"
	}
	finiteCap := func(v float64) bool { return v > 0 && !math.IsNaN(v) && !math.IsInf(v, 0) }
	if !finiteCap(op.MaxHP) || (op.Active != nil && op.Active.MaxHP != nil && !finiteCap(*op.Active.MaxHP)) {
		reason = "生命阈值攻速缺少有效生命上限"
	}
	if reason == "" {
		return nil
	}
	return []mechanisms.Gap{{ID: "runtime.hp_attack_speed", Status: "unimplemented", Source: "operator_spec", Operator: op.Name, CharID: op.CharID, Key: "hp_attack_speed", Reason: reason}}
}
