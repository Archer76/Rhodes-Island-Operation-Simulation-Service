package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"rios-sim/mechanisms"
	"strings"
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

// SkillRangedExemption preserves the full module part identity. It claims only
// the explicit active-skill ranged penalty exemption, not the note subsystem.
type SkillRangedExemption struct {
	ModuleID    string          `json:"module_id"`
	ModuleLevel int             `json:"module_level"`
	Part        json.RawMessage `json:"part"`
}

func validSkillRangedExemption(charID string, r *SkillRangedExemption) bool {
	if r == nil || charID != "char_4182_oblvns" || r.ModuleID != "uniequip_002_oblvns" {
		return false
	}
	want := map[int]string{2: "13dbd63de1baf7b6e5c944aeda777a96bfa7da94b32e8f17ab81d4fa373f90c1", 3: "150880c247b986ed398106372cec1dbc868bb82cd9b3f8026c11f7247915b44e"}[r.ModuleLevel]
	if want == "" {
		return false
	}
	var part any
	if json.Unmarshal(r.Part, &part) != nil {
		return false
	}
	canonical, err := json.Marshal(part)
	return err == nil && fmt.Sprintf("%x", sha256.Sum256(canonical)) == want
}

func sakikoSkillRangedExemption(st *OperatorStats) (*SkillRangedExemption, error) {
	if st.CharID != "char_4182_oblvns" || st.Module != "uniequip_002_oblvns" || st.ModuleLevel < 2 || st.ModuleLevel > 3 || st.Elite < 2 || st.Level < 60 || st.Potential < 1 {
		return nil, nil
	}
	parts, err := moduleParts(st.Module, st.ModuleLevel)
	if err != nil {
		return nil, err
	}
	if len(parts) < 2 {
		return nil, nil
	}
	r := &SkillRangedExemption{ModuleID: st.Module, ModuleLevel: st.ModuleLevel, Part: append(json.RawMessage(nil), parts[1]...)}
	if !validSkillRangedExemption(st.CharID, r) {
		return nil, nil
	}
	return r, nil
}

func (o *operator) rangedScaleFor(target *enemy) float64 {
	if target.blockedBy == o {
		return 1
	}
	if o.skillActive && validSkillRangedExemption(o.spec.CharID, o.spec.SkillRangedExemption) {
		return 1
	}
	if o.spec.RangedAtkScale > 0 {
		return o.spec.RangedAtkScale
	}
	return 1
}

// countCharacterModuleGaps guards the non-ASPD bundles of these two exact
// module owners. The existing producer resolves base character talents only;
// equal numeric keys in a base talent do not consume a module upgrade. This is
// an eligible-source inventory, not an effective-talent override resolver.
func countCharacterModuleGaps(st *OperatorStats) ([]mechanisms.Gap, error) {
	if !(st.CharID == "char_4182_oblvns" && st.Module == "uniequip_002_oblvns" || st.CharID == "char_4010_etlchi" && st.Module == "uniequip_003_etlchi") {
		return nil, nil
	}
	parts, err := moduleParts(st.Module, st.ModuleLevel)
	if err != nil {
		return nil, err
	}
	var gaps []mechanisms.Gap
	for pi, raw := range parts {
		var part struct {
			Talent struct {
				Candidates []json.RawMessage `json:"candidates"`
			} `json:"addOrOverrideTalentDataBundle"`
		}
		if err := json.Unmarshal(raw, &part); err != nil {
			return nil, err
		}
		for ci, craw := range part.Talent.Candidates {
			var c struct {
				Name               string  `json:"name"`
				Description        *string `json:"description"`
				UpgradeDescription *string `json:"upgradeDescription"`
				UnlockCondition    struct {
					Phase any `json:"phase"`
					Level int `json:"level"`
				} `json:"unlockCondition"`
				RequiredPotentialRank int               `json:"requiredPotentialRank"`
				Blackboard            []json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(craw, &c); err != nil {
				return nil, err
			}
			if phaseOf(c.UnlockCondition.Phase) > st.Elite || c.UnlockCondition.Level > st.Level || c.RequiredPotentialRank > st.Potential-1 {
				continue
			}
			var desc []string
			for _, s := range []*string{c.Description, c.UpgradeDescription} {
				if s != nil {
					desc = append(desc, *s)
				}
			}
			// Even an empty hidden prefab can alter battle behaviour. Preserve it
			// rather than treating an empty BB as a proven no-op.
			gaps = append(gaps, mechanisms.Gap{ID: "module.talent_override", Status: "unimplemented", Source: "module", CharID: st.CharID, Operator: st.Name, SourceID: st.Module, SourceName: c.Name, Key: fmt.Sprintf("parts[%d].addOrOverrideTalentDataBundle.candidates[%d]", pi, ci), Description: strings.Join(desc, "\n"), RawBlackboard: cloneRawBlackboard(c.Blackboard), RawSource: append(json.RawMessage(nil), raw...), RawSlot: append(json.RawMessage(nil), craw...), Slot: pi, Level: st.ModuleLevel, Instance: ci, Reason: "该人物模组天赋及隐藏行为来源尚无完整覆盖与战斗消费者；基础天赋同名键不能代为认领"})
		}
	}
	return gaps, nil
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
