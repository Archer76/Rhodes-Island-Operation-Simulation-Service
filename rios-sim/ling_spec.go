package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

const lingCharID = "char_2023_ling"
const lingModuleID = "uniequip_002_ling"

const (
	lingTokenSoul1 = "token_10020_ling_soul1" // “清平” (S1)
	lingTokenSoul2 = "token_10020_ling_soul2" // “逍遥” (S2)
	lingTokenSoul3 = "token_10020_ling_soul3" // “弦惊” (S3)
)

type LingSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

type LingTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

type LingSourceSpec struct {
	ConsumerImplemented bool                       `json:"consumer_implemented"`
	Elite               int                        `json:"elite"`
	Level               int                        `json:"level"`
	Potential           int                        `json:"potential"`
	Slot                int                        `json:"slot"`
	SkillLevel          int                        `json:"skill_level"`
	Talents             []LingTalentSource         `json:"talents"`
	OperatorSkill       LingSourceLevel            `json:"operator_skill"`
	TokenKey            string                     `json:"token_key"`
	TokenSkill          LingSourceLevel            `json:"token_skill"`
	RawSlot             json.RawMessage            `json:"raw_slot"`
	Module              *LingSourceLevel           `json:"module,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	UserRulings         map[string]string          `json:"user_rulings"`
	Unresolved          []string                   `json:"unresolved"`
}

func lingRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("ling source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func lingSourceLevel(id string, level int, raw json.RawMessage, field string) (LingSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return LingSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return LingSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return LingSourceLevel{}, fmt.Errorf("ling source: %s %s level %d unavailable", id, field, level)
	}
	return LingSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildLingSourceSpec(st *OperatorStats, slot, skillLevel int) (*LingSourceSpec, error) {
	if st.CharID != lingCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if slot < 1 || slot > 3 || st.Elite < 0 || st.Elite > 2 || st.Level < 1 || st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("ling source: invalid training or slot")
	}
	if slot > st.Elite+1 {
		return nil, fmt.Errorf("ling source: slot %d locked at E%d", slot, st.Elite)
	}

	chars, err := lingRawRecords("character_table", lingCharID, lingTokenSoul1, lingTokenSoul2, lingTokenSoul3)
	if err != nil {
		return nil, err
	}
	skills, err := lingRawRecords("skill_table", "skchr_ling_1", "skchr_ling_2", "skchr_ling_3", "sktok_ling_soul1", "sktok_ling_soul2", "sktok_ling_soul3")
	if err != nil {
		return nil, err
	}

	var char struct {
		Skills []json.RawMessage `json:"skills"`
		Talents []struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"talents"`
	}
	if err := json.Unmarshal(chars[lingCharID], &char); err != nil {
		return nil, err
	}
	if slot > len(char.Skills) {
		return nil, fmt.Errorf("ling source: slot %d unavailable", slot)
	}

	var skillRef struct {
		SkillID          string `json:"skillId"`
		OverrideTokenKey string `json:"overrideTokenKey"`
	}
	if err := json.Unmarshal(char.Skills[slot-1], &skillRef); err != nil {
		return nil, err
	}
	rawSkill, ok := skills[skillRef.SkillID]
	if !ok {
		return nil, fmt.Errorf("ling source: missing skill %s", skillRef.SkillID)
	}
	selectedSkill, err := lingSourceLevel(skillRef.SkillID, skillLevel, rawSkill, "levels")
	if err != nil {
		return nil, err
	}

	// 对应召唤物专属技能
	tokenSkillID := fmt.Sprintf("sktok_ling_soul%d", slot)
	rawTokenSkill, ok := skills[tokenSkillID]
	if !ok {
		return nil, fmt.Errorf("ling source: missing token skill %s", tokenSkillID)
	}
	selectedTokenSkill, err := lingSourceLevel(tokenSkillID, skillLevel, rawTokenSkill, "levels")
	if err != nil {
		return nil, err
	}

	out := &LingSourceSpec{
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		TokenKey:            skillRef.OverrideTokenKey,
		RawSlot:             char.Skills[slot-1],
		Evidence:            map[string]json.RawMessage{},
		UserRulings:         map[string]string{},
		ConsumerImplemented: true,
	}
	out.Evidence[lingCharID] = chars[lingCharID]
	out.Evidence[lingTokenSoul1] = chars[lingTokenSoul1]
	out.Evidence[lingTokenSoul2] = chars[lingTokenSoul2]
	out.Evidence[lingTokenSoul3] = chars[lingTokenSoul3]
	for k, v := range skills {
		out.Evidence[k] = v
	}
	out.OperatorSkill = selectedSkill
	out.TokenSkill = selectedTokenSkill

	// 天赋解析
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
			out.Talents = append(out.Talents, LingTalentSource{
				Group:     gIdx,
				Candidate: selectedCand,
				Raw:       selectedRaw,
			})
		}
	}

	// 模组解析
	if st.Module == lingModuleID && st.ModuleLevel > 0 {
		battleEquip, err := lingRawRecords("battle_equip_table", lingModuleID)
		if err == nil {
			out.Evidence[lingModuleID] = battleEquip[lingModuleID]
			modLvl, err := lingSourceLevel(lingModuleID, st.ModuleLevel, battleEquip[lingModuleID], "phases")
			if err == nil {
				out.Module = &modLvl
			}
		}
	}

	return out, nil
}
