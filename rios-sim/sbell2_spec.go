package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	sbell2CharID    = "char_1046_sbell2"
	sbell2YModuleID = "uniequip_002_sbell2"
)

// Sbell2SourceLevel 保存特定等级/阶段的原始证据
type Sbell2SourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// Sbell2TalentSource 保存天赋组与候选原文
type Sbell2TalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// Sbell2SourceSpec 声明圣聆初雪（char_1046_sbell2）的机制来源证据与主战斗循环消费状态。
type Sbell2SourceSpec struct {
	ConsumerImplemented bool                       `json:"consumer_implemented"`
	Elite               int                        `json:"elite"`
	Level               int                        `json:"level"`
	Potential           int                        `json:"potential"`
	Slot                int                        `json:"slot"`
	SkillLevel          int                        `json:"skill_level"`
	Talents             []Sbell2TalentSource       `json:"talents"`
	OperatorSkill       Sbell2SourceLevel          `json:"operator_skill"`
	RawSlot             json.RawMessage            `json:"raw_slot"`
	Module              *Sbell2SourceLevel         `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage          `json:"module_candidates,omitempty"`
	ModuleKind          string                     `json:"module_kind,omitempty"`
	TraitOverride       json.RawMessage            `json:"trait_override,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	Unresolved          []string                   `json:"unresolved"`
	RNGSeed             uint64                     `json:"rng_seed,omitempty"`
}

func sbell2RawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
	blob, err := os.ReadFile(filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel", table+".json"))
	if err != nil {
		return nil, err
	}
	var records map[string]json.RawMessage
	if err := json.Unmarshal(blob, &records); err != nil {
		return nil, err
	}
	out := make(map[string]json.RawMessage, len(ids))
	for _, id := range ids {
		raw, ok := records[id]
		if !ok || string(raw) == "null" {
			return nil, fmt.Errorf("sbell2 source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func sbell2SourceLevel(id string, level int, raw json.RawMessage, field string) (Sbell2SourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return Sbell2SourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return Sbell2SourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return Sbell2SourceLevel{}, fmt.Errorf("sbell2 source: %s %s level %d unavailable", id, field, level)
	}
	return Sbell2SourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildSbell2SourceSpec(st *OperatorStats, slot, skillLevel int) (*Sbell2SourceSpec, error) {
	if st == nil || st.CharID != sbell2CharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if st.Elite < 0 || st.Elite > 2 {
		return nil, fmt.Errorf("sbell2 source: elite %d out of range [0, 2]", st.Elite)
	}
	if st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("sbell2 source: potential %d out of range [1, 6]", st.Potential)
	}
	if slot < 1 || slot > 3 {
		return nil, fmt.Errorf("sbell2 source: slot %d out of range [1, 3]", slot)
	}
	if (slot == 2 && st.Elite < 1) || (slot == 3 && st.Elite < 2) {
		return nil, fmt.Errorf("sbell2 source: slot %d locked at elite %d", slot, st.Elite)
	}
	if skillLevel < 1 || skillLevel > 10 {
		return nil, fmt.Errorf("sbell2 source: skill level %d out of range [1, 10]", skillLevel)
	}

	charRecs, err := sbell2RawRecords("character_table", sbell2CharID)
	if err != nil {
		return nil, err
	}
	rawChar := charRecs[sbell2CharID]

	var charFields struct {
		Skills []struct {
			SkillID string `json:"skillId"`
		} `json:"skills"`
		Talents []struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"talents"`
		Trait struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"trait"`
	}
	if err := json.Unmarshal(rawChar, &charFields); err != nil {
		return nil, err
	}
	if slot > len(charFields.Skills) {
		return nil, fmt.Errorf("sbell2 source: slot %d exceeds skills count %d", slot, len(charFields.Skills))
	}
	selectedSkillID := charFields.Skills[slot-1].SkillID

	skillRecs, err := sbell2RawRecords("skill_table", selectedSkillID)
	if err != nil {
		return nil, err
	}
	skillLvl, err := sbell2SourceLevel(selectedSkillID, skillLevel, skillRecs[selectedSkillID], "levels")
	if err != nil {
		return nil, err
	}

	evidence := map[string]json.RawMessage{
		"character": append(json.RawMessage(nil), rawChar...),
		"skill":     append(json.RawMessage(nil), skillRecs[selectedSkillID]...),
	}

	out := &Sbell2SourceSpec{
		ConsumerImplemented: true,
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		OperatorSkill:       skillLvl,
		Evidence:            evidence,
	}

	potIndex := st.Potential - 1
	for groupIdx, tGroup := range charFields.Talents {
		var matchedCand json.RawMessage
		candIdxMatched := -1
		for candIdx, candRaw := range tGroup.Candidates {
			var cond struct {
				UnlockCondition struct {
					Phase string `json:"phase"`
					Level int    `json:"level"`
				} `json:"unlockCondition"`
				RequiredPotentialRank int `json:"requiredPotentialRank"`
			}
			if err := json.Unmarshal(candRaw, &cond); err != nil {
				continue
			}
			phaseReq := 0
			switch cond.UnlockCondition.Phase {
			case "PHASE_1":
				phaseReq = 1
			case "PHASE_2":
				phaseReq = 2
			}
			if st.Elite >= phaseReq && st.Level >= cond.UnlockCondition.Level && potIndex >= cond.RequiredPotentialRank {
				matchedCand = candRaw
				candIdxMatched = candIdx
			}
		}
		if matchedCand != nil {
			out.Talents = append(out.Talents, Sbell2TalentSource{
				Group:     groupIdx,
				Candidate: candIdxMatched,
				Raw:       append(json.RawMessage(nil), matchedCand...),
			})
		}
	}

	// 模组处理
	if st.Module != "" && st.ModuleLevel > 0 {
		modID := st.Module
		if modID != sbell2YModuleID {
			return nil, fmt.Errorf("sbell2 source: unrecognized module id %s", modID)
		}
		out.ModuleKind = "Y"
		equipRecs, err := sbell2RawRecords("battle_equip_table", modID)
		if err != nil {
			return nil, err
		}
		modRaw := equipRecs[modID]
		evidence["module"] = append(json.RawMessage(nil), modRaw...)
		modLvl, err := sbell2SourceLevel(modID, st.ModuleLevel, modRaw, "phases")
		if err != nil {
			return nil, err
		}
		out.Module = &modLvl

		var phaseObj struct {
			Parts []struct {
				Target                  string `json:"target"`
				ResKey                  string `json:"resKey"`
				IsToken                 bool   `json:"isToken"`
				OverrideTraitDataBundle struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"overrideTraitDataBundle"`
				AddOrOverrideTalentDataBundle struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"addOrOverrideTalentDataBundle"`
			} `json:"parts"`
		}
		if err := json.Unmarshal(modLvl.Raw, &phaseObj); err == nil {
			for _, p := range phaseObj.Parts {
				if len(p.OverrideTraitDataBundle.Candidates) > 0 {
					out.TraitOverride = append(json.RawMessage(nil), p.OverrideTraitDataBundle.Candidates[0]...)
				}
				if len(p.AddOrOverrideTalentDataBundle.Candidates) > 0 {
					for _, c := range p.AddOrOverrideTalentDataBundle.Candidates {
						out.ModuleCandidates = append(out.ModuleCandidates, append(json.RawMessage(nil), c...))
					}
				}
			}
		}
	}

	return out, nil
}

func sbell2RemainingGapsFromSpec(source *Sbell2SourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	cfg, err := decodeSbell2RuntimeConfig(source)
	if err != nil {
		return []mechanisms.Gap{{
			ID:       "sbell2.config.decode_failed",
			Status:   "unimplemented",
			Source:   "sbell2",
			Operator: opName,
			CharID:   sbell2CharID,
			Key:      "error",
			Reason:   fmt.Sprintf("圣聆初雪运行时配置解析失败: %v", err),
			Instance: instance,
		}}
	}

	var gaps []mechanisms.Gap
	add := func(id, source, key, reason string) {
		gaps = append(gaps, mechanisms.Gap{
			ID:       id,
			Status:   "unimplemented",
			Source:   source,
			Operator: opName,
			CharID:   sbell2CharID,
			Key:      key,
			Reason:   reason,
			Instance: instance,
		})
	}

	for _, key := range cfg.UnusedKeys {
		add("sbell2.unknown_key."+key, "skill", key,
			"圣聆初雪的该黑板键没有运行期消费者；未消费即具名登记，不作静默忽略")
	}

	return gaps
}
