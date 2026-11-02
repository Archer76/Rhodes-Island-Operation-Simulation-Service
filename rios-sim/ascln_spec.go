package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	asclnCharID = "char_4132_ascln"
	asclnXModuleID = "uniequip_002_ascln"
	asclnYModuleID = "uniequip_003_ascln"
)

// AsclnSourceLevel 保存特定等级/阶段的原始证据
type AsclnSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// AsclnTalentSource 保存天赋组与候选原文
type AsclnTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// AsclnSourceSpec 声明阿斯卡纶（char_4132_ascln）的机制来源证据与主战斗循环消费状态。
//
// 这里**只存原文**：天赋/模组/技能的数值一律由 decodeAsclnRuntimeConfig 从这些 Raw 里解析。
// 规格层不手写任何一个硬编码数值。
type AsclnSourceSpec struct {
	ConsumerImplemented bool                `json:"consumer_implemented"`
	Elite               int                 `json:"elite"`
	Level               int                 `json:"level"`
	Potential           int                 `json:"potential"`
	Slot                int                 `json:"slot"`
	SkillLevel          int                 `json:"skill_level"`
	Talents             []AsclnTalentSource `json:"talents"`
	OperatorSkill       AsclnSourceLevel    `json:"operator_skill"`
	RawSlot             json.RawMessage     `json:"raw_slot"`
	Module              *AsclnSourceLevel   `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage   `json:"module_candidates,omitempty"`
	ModuleKind          string              `json:"module_kind,omitempty"`
	TraitOverride       json.RawMessage     `json:"trait_override,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	Unresolved          []string            `json:"unresolved"`
	RNGSeed             uint64              `json:"rng_seed,omitempty"`
}

func asclnRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("ascln source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func asclnSourceLevel(id string, level int, raw json.RawMessage, field string) (AsclnSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return AsclnSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return AsclnSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return AsclnSourceLevel{}, fmt.Errorf("ascln source: %s %s level %d unavailable", id, field, level)
	}
	return AsclnSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildAsclnSourceSpec(st *OperatorStats, slot, skillLevel int) (*AsclnSourceSpec, error) {
	if st == nil {
		return nil, fmt.Errorf("ascln source: OperatorStats is nil")
	}
	if st.CharID != asclnCharID {
		return nil, fmt.Errorf("ascln source: expected %s, got %s", asclnCharID, st.CharID)
	}
	if st.Elite < 0 || st.Elite > 2 {
		return nil, fmt.Errorf("ascln source: elite %d out of range [0, 2]", st.Elite)
	}
	if st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("ascln source: potential %d out of range [1, 6]", st.Potential)
	}
	if slot < 1 || slot > 3 {
		return nil, fmt.Errorf("ascln source: slot %d out of range [1, 3]", slot)
	}
	if (slot == 2 && st.Elite < 1) || (slot == 3 && st.Elite < 2) {
		return nil, fmt.Errorf("ascln source: slot %d locked at elite %d", slot, st.Elite)
	}
	if skillLevel < 1 || skillLevel > 10 {
		return nil, fmt.Errorf("ascln source: skill level %d out of range [1, 10]", skillLevel)
	}

	charRecs, err := asclnRawRecords("character_table", asclnCharID)
	if err != nil {
		return nil, err
	}
	rawChar := charRecs[asclnCharID]

	var charFields struct {
		Skills []struct {
			SkillID string `json:"skillId"`
		} `json:"skills"`
		Talents []struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"talents"`
	}
	if err := json.Unmarshal(rawChar, &charFields); err != nil {
		return nil, err
	}
	if slot > len(charFields.Skills) {
		return nil, fmt.Errorf("ascln source: slot %d exceeds skills count %d", slot, len(charFields.Skills))
	}
	selectedSkillID := charFields.Skills[slot-1].SkillID

	skillRecs, err := asclnRawRecords("skill_table", selectedSkillID)
	if err != nil {
		return nil, err
	}
	skillLvl, err := asclnSourceLevel(selectedSkillID, skillLevel, skillRecs[selectedSkillID], "levels")
	if err != nil {
		return nil, err
	}

	evidence := map[string]json.RawMessage{
		"character": append(json.RawMessage(nil), rawChar...),
		"skill":     append(json.RawMessage(nil), skillRecs[selectedSkillID]...),
	}

	out := &AsclnSourceSpec{
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
			reqPhase := 0
			switch cond.UnlockCondition.Phase {
			case "PHASE_1":
				reqPhase = 1
			case "PHASE_2":
				reqPhase = 2
			}
			if st.Elite >= reqPhase && st.Level >= cond.UnlockCondition.Level && potIndex >= cond.RequiredPotentialRank {
				matchedCand = candRaw
				candIdxMatched = candIdx
			}
		}
		if matchedCand != nil {
			out.Talents = append(out.Talents, AsclnTalentSource{
				Group:     groupIdx,
				Candidate: candIdxMatched,
				Raw:       append(json.RawMessage(nil), matchedCand...),
			})
		}
	}

	modID := st.Module
	if modID != "" && st.ModuleLevel > 0 {
		if modID != asclnXModuleID && modID != asclnYModuleID {
			return nil, fmt.Errorf("ascln source: unrecognized module id %s", modID)
		}
		modKind := "X"
		if modID == asclnYModuleID {
			modKind = "Y"
		}
		out.ModuleKind = modKind

		equipRecs, err := asclnRawRecords("battle_equip_table", modID)
		if err != nil {
			return nil, err
		}
		modRaw := equipRecs[modID]
		evidence["module"] = append(json.RawMessage(nil), modRaw...)

		modLvl, err := asclnSourceLevel(modID, st.ModuleLevel, modRaw, "phases")
		if err != nil {
			return nil, err
		}
		out.Module = &modLvl

		var phaseFields struct {
			Parts []struct {
				OverrideTraitDataBundle struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"overrideTraitDataBundle"`
				AddOrOverrideTalentDataBundle struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"addOrOverrideTalentDataBundle"`
			} `json:"parts"`
		}
		if err := json.Unmarshal(modLvl.Raw, &phaseFields); err == nil {
			for _, part := range phaseFields.Parts {
				if len(part.OverrideTraitDataBundle.Candidates) > 0 {
					out.TraitOverride = append(json.RawMessage(nil), part.OverrideTraitDataBundle.Candidates[0]...)
				}
				for _, candRaw := range part.AddOrOverrideTalentDataBundle.Candidates {
					out.ModuleCandidates = append(out.ModuleCandidates, append(json.RawMessage(nil), candRaw...))
				}
			}
		}
	}

	return out, nil
}

func asclnRemainingGapsFromSpec(source *AsclnSourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	var gaps []mechanisms.Gap
	return gaps
}
