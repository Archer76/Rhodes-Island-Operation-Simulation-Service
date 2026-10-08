package main

import (
	"encoding/json"
	"fmt"
)

// Recognize ONLY the attack-speed part. This predicate deliberately does not
// remove the candidate gap: atk_scale/value semantics remain unclaimed.
func exactCountModuleCandidate(st *OperatorStats, pi, ci int, raw json.RawMessage, c moduleSpeedCandidate) bool {
	suffix := "etlchi_equip_2"
	desc := "攻击范围内存在2名及以上敌人时攻击速度+{attack_speed}"
	expected := map[string]float64{"attack_speed": 12, "cnt": 2, "value": 50}
	switch st.Module {
	case "uniequip_002_oblvns":
		if st.CharID != "char_4182_oblvns" {
			return false
		}
		suffix = "oblvns_equip_1"
		desc = "攻击范围内存在2名及以上敌人时攻击速度+12"
		expected = map[string]float64{"attack_speed": 12, "atk_scale": .8}
	case "uniequip_003_etlchi":
		if st.CharID != "char_4010_etlchi" {
			return false
		}
	default:
		return false
	}
	if st.ModuleLevel < 1 || st.ModuleLevel > 3 || pi != 0 || ci != 0 || c.UnlockCondition.Phase != "PHASE_2" || c.UnlockCondition.Level != 60 || st.Elite < 2 || st.Level < 60 || st.Potential < 1 || c.RequiredPotentialRank != 0 || c.AdditionalDescription == nil || mechanismText(*c.AdditionalDescription) != desc || c.OverrideDescription != nil || c.Description != nil || c.PrefabKey != nil || c.RangeID != nil || len(c.Blackboard) != len(expected) {
		return false
	}
	var p struct {
		Target string `json:"target"`
		Token  bool   `json:"isToken"`
		ResKey string `json:"resKey"`
		Game   any    `json:"validInGameTag"`
		Map    any    `json:"validInMapTag"`
	}
	if json.Unmarshal(raw, &p) != nil || p.Target != "TRAIT" || p.Token || p.Game != nil || p.Map != nil || p.ResKey != fmt.Sprintf("%s_%d_p1", suffix, st.ModuleLevel) {
		return false
	}
	for _, r := range c.Blackboard {
		var b struct {
			Key   string   `json:"key"`
			Value *float64 `json:"value"`
			Text  *string  `json:"valueStr"`
		}
		if json.Unmarshal(r, &b) != nil || b.Value == nil || b.Text != nil {
			return false
		}
		v, ok := expected[b.Key]
		if !ok || *b.Value != v {
			return false
		}
		delete(expected, b.Key)
	}
	return len(expected) == 0
}
func countModuleSpeed(st *OperatorStats) (*EnemyCountASPD, error) {
	parts, err := moduleParts(st.Module, st.ModuleLevel)
	if err != nil {
		return nil, err
	}
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
			if exactCountModuleCandidate(st, pi, ci, raw, c) {
				scope := "current"
				if st.Module == "uniequip_002_oblvns" {
					scope = "base"
				}
				return &EnemyCountASPD{Scope: scope, Minimum: 2, Bonus: 12}, nil
			}
		}
	}
	return nil, nil
}
