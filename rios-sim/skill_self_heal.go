package main

import (
	"encoding/json"
	"math"
)

// These three shared skills are the audited instant, own-max-HP heal family.
// heal_scale is also used for lifesteal, ally healing and enemy healing reduction:
// neither the key nor the generic numeric parser is a sufficient claim.
func instantSelfHealRatio(meta SkillMeta) (float64, bool) {
	switch meta.SkillID {
	case "skcom_heal_self[1]", "skcom_heal_self[2]", "skcom_heal_self[3]":
	default:
		return 0, false
	}
	ratio, ok := toFloat(meta.Blackboard["heal_scale"])
	if !ok || math.IsNaN(ratio) || math.IsInf(ratio, 0) || ratio <= 0 || ratio > 1 {
		return 0, false
	}
	if meta.RangeID != nil || meta.BlackboardEntries != 1 || len(meta.RawBlackboard) != 1 {
		return 0, false
	}
	var entry struct {
		Key      string  `json:"key"`
		Value    float64 `json:"value"`
		ValueStr *string `json:"valueStr"`
	}
	if json.Unmarshal(meta.RawBlackboard[0], &entry) != nil || entry.Key != "heal_scale" || entry.Value != ratio || entry.ValueStr != nil {
		return 0, false
	}
	if meta.SkillType != "MANUAL" || meta.DurationType != "NONE" || meta.Duration == nil || *meta.Duration != 0 {
		return 0, false
	}
	text := mechanismText(meta.RawDescription)
	if text != "立即恢复最大生命的{heal_scale:0%}" {
		return 0, false
	}
	// This exact family has a single effect. Changed source payloads stay blocked.
	if len(meta.Blackboard) != 1 {
		return 0, false
	}
	return ratio, true
}
