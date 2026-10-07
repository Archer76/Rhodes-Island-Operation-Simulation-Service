package main

import (
	"encoding/json"
	"fmt"
	"math"
	"rios-sim/mechanisms"
	"strings"
)

// AttackTimingSpec preserves the unrounded, unclamped calculation inputs.
// Do not reconstruct these from an already folded interval snapshot.
type AttackTimingSpec struct {
	BaseAttackTime float64 `json:"base_attack_time"`
	ASPD           float64 `json:"aspd"`
}

func validAttackTiming(t *AttackTimingSpec) bool {
	return t != nil && t.BaseAttackTime > 0 && !math.IsNaN(t.BaseAttackTime) && !math.IsInf(t.BaseAttackTime, 0) && !math.IsNaN(t.ASPD) && !math.IsInf(t.ASPD, 0)
}
func timingInterval(t *AttackTimingSpec, bonus float64) float64 {
	return math.Max(opsMinInterval, t.BaseAttackTime*100/math.Max(opsAspdMin, t.ASPD+bonus))
}
func (o *operator) freeAttackSpeed() float64 {
	for _, e := range o.blocking {
		if e != nil && e.hp > 0 && !e.leaked && !e.offMap && e.blockedBy == o {
			return 0
		}
	}
	return o.spec.AttackSpeedWhenFree
}

type moduleSpeedCandidate struct {
	AdditionalDescription *string `json:"additionalDescription"`
	OverrideDescription   *string `json:"overrideDescripton"`
	Description           *string `json:"description"`
	PrefabKey             *string `json:"prefabKey"`
	RangeID               *string `json:"rangeId"`
	UnlockCondition       struct {
		Phase any `json:"phase"`
		Level int `json:"level"`
	} `json:"unlockCondition"`
	RequiredPotentialRank int               `json:"requiredPotentialRank"`
	Blackboard            []json.RawMessage `json:"blackboard"`
}

func (c moduleSpeedCandidate) text() string {
	text := ""
	for _, s := range []*string{c.AdditionalDescription, c.OverrideDescription, c.Description} {
		if s != nil {
			text += *s
		}
	}
	return text
}
func exactFreeModuleCandidate(charID, moduleID string, moduleLevel, partIndex, candidateIndex int, rawPart json.RawMessage, c moduleSpeedCandidate) bool {
	owners := map[string]struct {
		CharID string
		Level  int
	}{
		"uniequip_002_surtr": {"char_350_surtr", 60}, "uniequip_002_siege2": {"char_1019_siege2", 60}, "uniequip_002_amiya2": {"char_1001_amiya2", 50}, "uniequip_002_frncat": {"char_185_frncat", 40}, "uniequip_002_chen3": {"char_1050_chen3", 60},
	}
	owner, ok := owners[moduleID]
	if !ok || owner.CharID != charID || moduleLevel < 1 || moduleLevel > 3 || partIndex != 0 || candidateIndex != 0 {
		return false
	}
	if c.UnlockCondition.Phase != "PHASE_2" || c.UnlockCondition.Level != owner.Level || c.RequiredPotentialRank != 0 || c.AdditionalDescription == nil || mechanismText(*c.AdditionalDescription) != "未阻挡敌人时攻击速度+{attack_speed}" || c.OverrideDescription != nil || c.Description != nil || c.PrefabKey != nil || c.RangeID != nil || len(c.Blackboard) != 1 {
		return false
	}
	var part struct {
		Target    string `json:"target"`
		IsToken   bool   `json:"isToken"`
		ResKey    string `json:"resKey"`
		ValidGame any    `json:"validInGameTag"`
		ValidMap  any    `json:"validInMapTag"`
	}
	if json.Unmarshal(rawPart, &part) != nil || part.Target != "TRAIT" || part.IsToken || part.ValidGame != nil || part.ValidMap != nil || part.ResKey != fmt.Sprintf("%s_equip_1_%d_p1", strings.TrimPrefix(moduleID, "uniequip_002_"), moduleLevel) {
		return false
	}
	var b struct {
		Key      string   `json:"key"`
		Value    *float64 `json:"value"`
		ValueStr *string  `json:"valueStr"`
	}
	return json.Unmarshal(c.Blackboard[0], &b) == nil && b.Key == "attack_speed" && b.Value != nil && *b.Value == 8 && b.ValueStr == nil
}

// Scan selected module parts with source identity intact. Exact traits return a
// runtime bonus. Unclaimed conditional/hidden attack-speed sources stay gaps.
func conditionalModuleSpeed(st *OperatorStats) (float64, []mechanisms.Gap, error) {
	parts, err := moduleParts(st.Module, st.ModuleLevel)
	if err != nil {
		return 0, nil, err
	}
	var bonus float64
	var gaps []mechanisms.Gap
	for pi, raw := range parts {
		var part struct {
			Trait struct {
				Candidates []json.RawMessage `json:"candidates"`
			} `json:"overrideTraitDataBundle"`
			Talent struct {
				Candidates []json.RawMessage `json:"candidates"`
			} `json:"addOrOverrideTalentDataBundle"`
		}
		if err := json.Unmarshal(raw, &part); err != nil {
			return 0, nil, err
		}
		for _, bundle := range []struct {
			Name       string
			Candidates []json.RawMessage
		}{{"trait", part.Trait.Candidates}, {"talent", part.Talent.Candidates}} {
			for ci, craw := range bundle.Candidates {
				var c moduleSpeedCandidate
				if err := json.Unmarshal(craw, &c); err != nil {
					return 0, nil, err
				}
				if phaseOf(c.UnlockCondition.Phase) > st.Elite || c.UnlockCondition.Level > st.Level || c.RequiredPotentialRank > st.Potential-1 {
					continue
				}
				speed := false
				for _, braw := range c.Blackboard {
					var b struct {
						Key string `json:"key"`
					}
					if err := json.Unmarshal(braw, &b); err != nil {
						return 0, nil, err
					}
					if strings.Contains(b.Key, "attack_speed") {
						speed = true
					}
				}
				if !speed {
					continue
				}
				if bundle.Name == "trait" && exactFreeModuleCandidate(st.CharID, st.Module, st.ModuleLevel, pi, ci, raw, c) {
					bonus += 8
					continue
				}
				if bundle.Name == "trait" && exactHPModuleCandidate(st.CharID, st.Module, st.ModuleLevel, pi, ci, raw, c) {
					continue
				}
				// Missing a condition regex is not proof of an unconditional source.
				gaps = append(gaps, mechanisms.Gap{ID: "module.conditional_attack_speed", Status: "unimplemented", Source: "module", CharID: st.CharID, Operator: st.Name, SourceID: st.Module, Key: "attack_speed", Description: c.text(), RawBlackboard: cloneRawBlackboard(c.Blackboard), RawSource: append(json.RawMessage(nil), raw...), RawSlot: append(json.RawMessage(nil), craw...), Slot: pi, Level: st.ModuleLevel, Instance: ci, Reason: "模组攻速来源或条件尚无精确战斗消费者"})
			}
		}
	}
	return bonus, gaps, nil
}
