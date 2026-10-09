package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

const wisdelCharID = "char_1035_wisdel"
const wisdelModuleID = "uniequip_002_wisdel"
const wisdelTokenID = "token_10035_wisdel_wward"

type WisdelSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

type WisdelTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

type WisdelSourceSpec struct {
	ConsumerImplemented bool                       `json:"consumer_implemented"`
	Elite               int                        `json:"elite"`
	Level               int                        `json:"level"`
	Potential           int                        `json:"potential"`
	Slot                int                        `json:"slot"`
	SkillLevel          int                        `json:"skill_level"`
	Talents             []WisdelTalentSource       `json:"talents"`
	OperatorSkill       WisdelSourceLevel          `json:"operator_skill"`
	RawSlot             json.RawMessage            `json:"raw_slot"`
	Module              *WisdelSourceLevel         `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage          `json:"module_candidates,omitempty"`
	TokenSkill          *WisdelSourceLevel         `json:"token_skill,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	UserRulings         map[string]string          `json:"user_rulings"`
	Unresolved          []string                   `json:"unresolved"`
}

func wisdelRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("wisdel source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func wisdelSourceLevel(id string, level int, raw json.RawMessage, field string) (WisdelSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return WisdelSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return WisdelSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return WisdelSourceLevel{}, fmt.Errorf("wisdel source: %s %s level %d unavailable", id, field, level)
	}
	return WisdelSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildWisdelSourceSpec(st *OperatorStats, slot, skillLevel int) (*WisdelSourceSpec, error) {
	if st.CharID != wisdelCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if slot < 1 || slot > 3 || st.Elite < 0 || st.Elite > 2 || st.Level < 1 || st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("wisdel source: invalid training or slot")
	}
	if slot > st.Elite+1 {
		return nil, fmt.Errorf("wisdel source: slot %d locked at E%d", slot, st.Elite)
	}

	chars, err := wisdelRawRecords("character_table", wisdelCharID, wisdelTokenID)
	if err != nil {
		return nil, err
	}
	skills, err := wisdelRawRecords("skill_table", "skchr_wisdel_1", "skchr_wisdel_2", "skchr_wisdel_3", "sktok_wisdel_wward")
	if err != nil {
		return nil, err
	}

	var char struct {
		Skills []struct {
			SkillID string `json:"skillId"`
		} `json:"skills"`
		Talents []struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"talents"`
	}
	if err := json.Unmarshal(chars[wisdelCharID], &char); err != nil {
		return nil, err
	}
	if slot-1 >= len(char.Skills) {
		return nil, fmt.Errorf("wisdel source: slot %d unavailable", slot)
	}

	skillRef := char.Skills[slot-1]
	rawSkill, ok := skills[skillRef.SkillID]
	if !ok {
		return nil, fmt.Errorf("wisdel source: missing skill %s", skillRef.SkillID)
	}
	selectedSkill, err := wisdelSourceLevel(skillRef.SkillID, skillLevel, rawSkill, "levels")
	if err != nil {
		return nil, err
	}

	tokenSkillRef := "sktok_wisdel_wward"
	rawTokenSkill, ok := skills[tokenSkillRef]
	var tokenSkillLevel *WisdelSourceLevel
	if ok {
		tokLvl, err := wisdelSourceLevel(tokenSkillRef, skillLevel, rawTokenSkill, "levels")
		if err == nil {
			tokenSkillLevel = &tokLvl
		}
	}

	out := &WisdelSourceSpec{
		ConsumerImplemented: true,
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		OperatorSkill:       selectedSkill,
		RawSlot:             append(json.RawMessage(nil), rawSkill...),
		TokenSkill:          tokenSkillLevel,
		Evidence:            make(map[string]json.RawMessage),
		UserRulings: map[string]string{
			"damage_type":      "physical_bombarder_with_aftershock",
			"talent1_mark":     "shadow_mark_on_main_target_aftershock_explodes",
			"talent2_ward":     "summon_ward_on_deploy_camou_in_adjacent_range",
			"ammo_skill3":      "6_ammo_100_percent_explosion_prob_summon_wards",
			"overdrive_skill2": "4_shot_overdrive_random_targeting",
		},
		Unresolved: make([]string, 0),
	}
	out.Evidence[wisdelCharID] = chars[wisdelCharID]
	out.Evidence[wisdelTokenID] = chars[wisdelTokenID]
	out.Evidence[skillRef.SkillID] = rawSkill
	if ok {
		out.Evidence[tokenSkillRef] = rawTokenSkill
	}

	for gIdx, group := range char.Talents {
		var selectedCand int = -1
		var selectedRaw json.RawMessage
		for cIdx, candRaw := range group.Candidates {
			var cand struct {
				UnlockCondition struct {
					Phase string `json:"phase"`
					Level int    `json:"level"`
				} `json:"unlockCondition"`
				RequiredPotentialRank int `json:"requiredPotentialRank"`
			}
			if err := json.Unmarshal(candRaw, &cand); err != nil {
				return nil, err
			}
			pReq := 0
			switch cand.UnlockCondition.Phase {
			case "PHASE_1":
				pReq = 1
			case "PHASE_2":
				pReq = 2
			}
			if st.Elite >= pReq && st.Level >= cand.UnlockCondition.Level && (st.Potential-1) >= cand.RequiredPotentialRank {
				selectedCand = cIdx
				selectedRaw = candRaw
			}
		}
		if selectedCand >= 0 {
			out.Talents = append(out.Talents, WisdelTalentSource{
				Group:     gIdx,
				Candidate: selectedCand,
				Raw:       append(json.RawMessage(nil), selectedRaw...),
			})
		}
	}

	if st.Module == wisdelModuleID && st.ModuleLevel > 0 {
		battleEquip, err := wisdelRawRecords("battle_equip_table", wisdelModuleID)
		if err == nil {
			out.Evidence[wisdelModuleID] = battleEquip[wisdelModuleID]
			modLvl, err := wisdelSourceLevel(wisdelModuleID, st.ModuleLevel, battleEquip[wisdelModuleID], "phases")
			if err == nil {
				out.Module = &modLvl
				var phase struct {
					Parts []struct {
						Target                     string            `json:"target"`
						AddOrOverrideTalentBundle  *struct {
							Candidates []json.RawMessage `json:"candidates"`
						} `json:"addOrOverrideTalentDataBundle,omitempty"`
						OverrideTraitBundle        *struct {
							Candidates []json.RawMessage `json:"candidates"`
						} `json:"overrideTraitDataBundle,omitempty"`
					} `json:"parts"`
				}
				if err := json.Unmarshal(modLvl.Raw, &phase); err == nil {
					for _, part := range phase.Parts {
						if part.OverrideTraitBundle != nil {
							for _, cand := range part.OverrideTraitBundle.Candidates {
								out.ModuleCandidates = append(out.ModuleCandidates, append(json.RawMessage(nil), cand...))
							}
						}
						if part.AddOrOverrideTalentBundle != nil {
							for _, cand := range part.AddOrOverrideTalentBundle.Candidates {
								out.ModuleCandidates = append(out.ModuleCandidates, append(json.RawMessage(nil), cand...))
							}
						}
					}
				}
			}
		}
	}

	return out, nil
}
