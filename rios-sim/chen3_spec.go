package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

const chen3CharID = "char_1050_chen3"
const chen3ModuleID = "uniequip_002_chen3"

type Chen3SourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

type Chen3TalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

type Chen3SourceSpec struct {
	ConsumerImplemented bool                `json:"consumer_implemented"`
	Elite               int                 `json:"elite"`
	Level               int                 `json:"level"`
	Potential           int                 `json:"potential"`
	Slot                int                 `json:"slot"`
	SkillLevel          int                 `json:"skill_level"`
	Talents             []Chen3TalentSource `json:"talents"`
	OperatorSkill       Chen3SourceLevel    `json:"operator_skill"`
	RawSlot             json.RawMessage     `json:"raw_slot"`
	Module              *Chen3SourceLevel   `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage   `json:"module_candidates,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	UserRulings         map[string]string          `json:"user_rulings"`
	Unresolved          []string                   `json:"unresolved"`
}

func chen3RawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("chen3 source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func chen3SourceLevel(id string, level int, raw json.RawMessage, field string) (Chen3SourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return Chen3SourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return Chen3SourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return Chen3SourceLevel{}, fmt.Errorf("chen3 source: %s %s level %d unavailable", id, field, level)
	}
	return Chen3SourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildChen3SourceSpec(st *OperatorStats, slot, skillLevel int) (*Chen3SourceSpec, error) {
	if st.CharID != chen3CharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if slot < 1 || slot > 3 || st.Elite < 0 || st.Elite > 2 || st.Level < 1 || st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("chen3 source: invalid training or slot")
	}
	if slot > st.Elite+1 {
		return nil, fmt.Errorf("chen3 source: slot %d locked at E%d", slot, st.Elite)
	}

	chars, err := chen3RawRecords("character_table", chen3CharID)
	if err != nil {
		return nil, err
	}
	skills, err := chen3RawRecords("skill_table", "skchr_chen3_1", "skchr_chen3_2", "skchr_chen3_3")
	if err != nil {
		return nil, err
	}

	var char struct {
		Skills []json.RawMessage `json:"skills"`
		Talents []struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"talents"`
	}
	if err := json.Unmarshal(chars[chen3CharID], &char); err != nil {
		return nil, err
	}
	if slot > len(char.Skills) {
		return nil, fmt.Errorf("chen3 source: slot %d unavailable", slot)
	}

	var skillRef struct {
		SkillID string `json:"skillId"`
	}
	if err := json.Unmarshal(char.Skills[slot-1], &skillRef); err != nil {
		return nil, err
	}
	rawSkill, ok := skills[skillRef.SkillID]
	if !ok {
		return nil, fmt.Errorf("chen3 source: missing skill %s", skillRef.SkillID)
	}
	selectedSkill, err := chen3SourceLevel(skillRef.SkillID, skillLevel, rawSkill, "levels")
	if err != nil {
		return nil, err
	}

	out := &Chen3SourceSpec{
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		RawSlot:             char.Skills[slot-1],
		Evidence:            map[string]json.RawMessage{},
		UserRulings:         map[string]string{},
		ConsumerImplemented: true,
	}
	out.Evidence[chen3CharID] = chars[chen3CharID]
	for k, v := range skills {
		out.Evidence[k] = v
	}
	out.OperatorSkill = selectedSkill

	// Talents resolution
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
			out.Talents = append(out.Talents, Chen3TalentSource{
				Group:     gIdx,
				Candidate: selectedCand,
				Raw:       selectedRaw,
			})
		}
	}

	// Module resolution
	if st.Module == chen3ModuleID && st.ModuleLevel > 0 {
		battleEquip, err := chen3RawRecords("battle_equip_table", chen3ModuleID)
		if err == nil {
			out.Evidence[chen3ModuleID] = battleEquip[chen3ModuleID]
			modLvl, err := chen3SourceLevel(chen3ModuleID, st.ModuleLevel, battleEquip[chen3ModuleID], "phases")
			if err == nil {
				out.Module = &modLvl
			}
		}
	}

	return out, nil
}
