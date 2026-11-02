package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	typhonCharID    = "char_2012_typhon"
	typhonXModuleID = "uniequip_002_typhon"
	typhonYModuleID = "uniequip_003_typhon"
)

// TyphonSourceLevel 保存特定等级/阶段的原始证据
type TyphonSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// TyphonTalentSource 保存天赋组与候选原文
type TyphonTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// TyphonSourceSpec 声明提丰（char_2012_typhon）的机制来源证据与主战斗循环消费状态。
//
// 这里只存原文：天赋/模组/技能的数值一律由 decodeTyphonRuntimeConfig 从这些 Raw 里解析。
// 规格层不手写任何一个硬编码数值。
type TyphonSourceSpec struct {
	ConsumerImplemented bool                       `json:"consumer_implemented"`
	Elite               int                        `json:"elite"`
	Level               int                        `json:"level"`
	Potential           int                        `json:"potential"`
	Slot                int                        `json:"slot"`
	SkillLevel          int                        `json:"skill_level"`
	Talents             []TyphonTalentSource       `json:"talents"`
	OperatorSkill       TyphonSourceLevel          `json:"operator_skill"`
	RawSlot             json.RawMessage            `json:"raw_slot"`
	Module              *TyphonSourceLevel         `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage          `json:"module_candidates,omitempty"`
	ModuleKind          string                     `json:"module_kind,omitempty"`
	TraitOverride       json.RawMessage            `json:"trait_override,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	Unresolved          []string                   `json:"unresolved"`
	RNGSeed             uint64                     `json:"rng_seed,omitempty"`
}

func typhonRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("typhon source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func typhonSourceLevel(id string, level int, raw json.RawMessage, field string) (TyphonSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return TyphonSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return TyphonSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return TyphonSourceLevel{}, fmt.Errorf("typhon source: %s %s level %d unavailable", id, field, level)
	}
	return TyphonSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildTyphonSourceSpec(st *OperatorStats, slot, skillLevel int) (*TyphonSourceSpec, error) {
	if st == nil || st.CharID != typhonCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if st.Elite < 0 || st.Elite > 2 {
		return nil, fmt.Errorf("typhon source: elite %d out of range [0, 2]", st.Elite)
	}
	if st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("typhon source: potential %d out of range [1, 6]", st.Potential)
	}
	if slot < 1 || slot > 3 {
		return nil, fmt.Errorf("typhon source: slot %d out of range [1, 3]", slot)
	}
	if (slot == 2 && st.Elite < 1) || (slot == 3 && st.Elite < 2) {
		return nil, fmt.Errorf("typhon source: slot %d locked at elite %d", slot, st.Elite)
	}
	if skillLevel < 1 || skillLevel > 10 {
		return nil, fmt.Errorf("typhon source: skill level %d out of range [1, 10]", skillLevel)
	}

	charRecs, err := typhonRawRecords("character_table", typhonCharID)
	if err != nil {
		return nil, err
	}
	rawChar := charRecs[typhonCharID]

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
		return nil, fmt.Errorf("typhon source: slot %d exceeds skills count %d", slot, len(charFields.Skills))
	}
	selectedSkillID := charFields.Skills[slot-1].SkillID

	skillRecs, err := typhonRawRecords("skill_table", selectedSkillID)
	if err != nil {
		return nil, err
	}
	skillLvl, err := typhonSourceLevel(selectedSkillID, skillLevel, skillRecs[selectedSkillID], "levels")
	if err != nil {
		return nil, err
	}

	evidence := map[string]json.RawMessage{
		"character": append(json.RawMessage(nil), rawChar...),
		"skill":     append(json.RawMessage(nil), skillRecs[selectedSkillID]...),
	}

	out := &TyphonSourceSpec{
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
			out.Talents = append(out.Talents, TyphonTalentSource{
				Group:     groupIdx,
				Candidate: candIdxMatched,
				Raw:       append(json.RawMessage(nil), matchedCand...),
			})
		}
	}

	modID := st.Module
	if modID != "" && st.ModuleLevel > 0 {
		if modID != typhonXModuleID && modID != typhonYModuleID {
			return nil, fmt.Errorf("typhon source: unrecognized module id %s", modID)
		}
		modKind := "X"
		if modID == typhonYModuleID {
			modKind = "Y"
		}
		out.ModuleKind = modKind

		equipRecs, err := typhonRawRecords("battle_equip_table", modID)
		if err != nil {
			return nil, err
		}
		modRaw := equipRecs[modID]
		evidence["module"] = append(json.RawMessage(nil), modRaw...)

		modLvl, err := typhonSourceLevel(modID, st.ModuleLevel, modRaw, "phases")
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
					var bestTrait json.RawMessage
					bestRank := -1
					for _, candRaw := range part.OverrideTraitDataBundle.Candidates {
						var cond struct {
							RequiredPotentialRank int `json:"requiredPotentialRank"`
						}
						if err := json.Unmarshal(candRaw, &cond); err == nil {
							if cond.RequiredPotentialRank <= potIndex && cond.RequiredPotentialRank > bestRank {
								bestTrait = candRaw
								bestRank = cond.RequiredPotentialRank
							}
						}
					}
					if bestTrait != nil {
						out.TraitOverride = append(json.RawMessage(nil), bestTrait...)
					}
				}
				bestByIndex := map[string]json.RawMessage{}
				bestRankByIndex := map[string]int{}
				for _, candRaw := range part.AddOrOverrideTalentDataBundle.Candidates {
					var cond struct {
						TalentIndex           int  `json:"talentIndex"`
						IsHideTalent          bool `json:"isHideTalent"`
						RequiredPotentialRank int  `json:"requiredPotentialRank"`
					}
					if err := json.Unmarshal(candRaw, &cond); err == nil {
						if cond.RequiredPotentialRank <= potIndex {
							k := fmt.Sprintf("%d:%t", cond.TalentIndex, cond.IsHideTalent)
							if rank, ok := bestRankByIndex[k]; !ok || cond.RequiredPotentialRank > rank {
								bestByIndex[k] = candRaw
								bestRankByIndex[k] = cond.RequiredPotentialRank
							}
						}
					}
				}
				for _, candRaw := range bestByIndex {
					out.ModuleCandidates = append(out.ModuleCandidates, append(json.RawMessage(nil), candRaw...))
				}
			}
		}
	}

	return out, nil
}

func typhonRemainingGapsFromSpec(source *TyphonSourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	var gaps []mechanisms.Gap
	return gaps
}
