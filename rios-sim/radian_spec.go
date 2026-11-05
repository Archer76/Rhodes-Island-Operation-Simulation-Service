package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

const radianCharID = "char_4195_radian"

const (
	radianTokenTower1 = "token_10051_radian_tower1" // 戴乌 (S1)
	radianTokenTower2 = "token_10052_radian_tower2" // 鳞地 (S2)
	radianTokenTower3 = "token_10053_radian_tower3" // 棱镜塔 (S3)
)

type RadianSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

type RadianTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

type RadianSourceSpec struct {
	ConsumerImplemented bool                       `json:"consumer_implemented"`
	Elite               int                        `json:"elite"`
	Level               int                        `json:"level"`
	Potential           int                        `json:"potential"`
	Slot                int                        `json:"slot"`
	SkillLevel          int                        `json:"skill_level"`
	Talents             []RadianTalentSource       `json:"talents"`
	OperatorSkill       RadianSourceLevel          `json:"operator_skill"`
	TokenKey            string                     `json:"token_key"`
	TokenSkill          RadianSourceLevel          `json:"token_skill"`
	RawSlot             json.RawMessage            `json:"raw_slot"`
	Module              *RadianSourceLevel         `json:"module,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	UserRulings         map[string]string          `json:"user_rulings"`
	Unresolved          []string                   `json:"unresolved"`
}

func radianRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("radian source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func radianSourceLevel(id string, level int, raw json.RawMessage, field string) (RadianSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return RadianSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return RadianSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return RadianSourceLevel{}, fmt.Errorf("radian source: %s %s level %d unavailable", id, field, level)
	}
	return RadianSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildRadianSourceSpec(st *OperatorStats, slot, skillLevel int) (*RadianSourceSpec, error) {
	if st.CharID != radianCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if slot < 1 || slot > 3 || st.Elite < 0 || st.Elite > 2 || st.Level < 1 || st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("radian source: invalid training or slot")
	}
	if slot > st.Elite+1 {
		return nil, fmt.Errorf("radian source: slot %d locked at E%d", slot, st.Elite)
	}

	chars, err := radianRawRecords("character_table", radianCharID, radianTokenTower1, radianTokenTower2, radianTokenTower3)
	if err != nil {
		return nil, err
	}
	skills, err := radianRawRecords("skill_table", "skchr_radian_1", "skchr_radian_2", "skchr_radian_3", "sktok_radian_1", "sktok_radian_2", "sktok_radian_3")
	if err != nil {
		return nil, err
	}

	var char struct {
		Skills []json.RawMessage `json:"skills"`
		Talents []struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"talents"`
	}
	if err := json.Unmarshal(chars[radianCharID], &char); err != nil {
		return nil, err
	}
	if slot > len(char.Skills) {
		return nil, fmt.Errorf("radian source: slot %d unavailable", slot)
	}

	var skillRef struct {
		SkillID          string `json:"skillId"`
		OverrideTokenKey string `json:"overrideTokenKey"`
	}
	if err := json.Unmarshal(char.Skills[slot-1], &skillRef); err != nil {
		return nil, err
	}
	// overrideTokenKey 对应技能装配的召唤物
	tokenKey := skillRef.OverrideTokenKey
	if tokenKey == "" {
		switch slot {
		case 1:
			tokenKey = radianTokenTower1
		case 2:
			tokenKey = radianTokenTower2
		case 3:
			tokenKey = radianTokenTower3
		}
	}

	rawSkill, ok := skills[skillRef.SkillID]
	if !ok {
		return nil, fmt.Errorf("radian source: missing skill %s", skillRef.SkillID)
	}
	selectedSkill, err := radianSourceLevel(skillRef.SkillID, skillLevel, rawSkill, "levels")
	if err != nil {
		return nil, err
	}

	// 对应召唤物技能 sktok_radian_1 / 2 / 3
	tokenSkillID := fmt.Sprintf("sktok_radian_%d", slot)
	rawTokenSkill, ok := skills[tokenSkillID]
	if !ok {
		return nil, fmt.Errorf("radian source: missing token skill %s", tokenSkillID)
	}
	selectedTokenSkill, err := radianSourceLevel(tokenSkillID, skillLevel, rawTokenSkill, "levels")
	if err != nil {
		return nil, err
	}

	out := &RadianSourceSpec{
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		TokenKey:            tokenKey,
		RawSlot:             char.Skills[slot-1],
		Evidence:            map[string]json.RawMessage{},
		UserRulings:         map[string]string{},
		ConsumerImplemented: true,
	}
	out.Evidence[radianCharID] = chars[radianCharID]
	out.Evidence[radianTokenTower1] = chars[radianTokenTower1]
	out.Evidence[radianTokenTower2] = chars[radianTokenTower2]
	out.Evidence[radianTokenTower3] = chars[radianTokenTower3]
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
			out.Talents = append(out.Talents, RadianTalentSource{
				Group:     gIdx,
				Candidate: selectedCand,
				Raw:       selectedRaw,
			})
		}
	}

	return out, nil
}
