package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	oxiCharID = "char_4247_oxi"
)

// OxiSourceLevel 保存特定等级/阶段的原始证据
type OxiSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// OxiTalentSource 保存天赋组与候选原文
type OxiTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// OxiSourceSpec 声明塔露拉（char_4247_oxi）的机制来源证据与主战斗循环消费状态。
//
// 这里只存原文：天赋/技能的数值一律由 decodeOxiRuntimeConfig 从这些 Raw 里解析。
// 规格层不手写任何一个硬编码数值。
type OxiSourceSpec struct {
	ConsumerImplemented bool                       `json:"consumer_implemented"`
	Elite               int                        `json:"elite"`
	Level               int                        `json:"level"`
	Potential           int                        `json:"potential"`
	Slot                int                        `json:"slot"`
	SkillLevel          int                        `json:"skill_level"`
	Talents             []OxiTalentSource          `json:"talents"`
	OperatorSkill       OxiSourceLevel             `json:"operator_skill"`
	RawSlot             json.RawMessage            `json:"raw_slot"`
	Module              *OxiSourceLevel            `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage          `json:"module_candidates,omitempty"`
	ModuleKind          string                     `json:"module_kind,omitempty"`
	TraitOverride       json.RawMessage            `json:"trait_override,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	Unresolved          []string                   `json:"unresolved"`
	RNGSeed             uint64                     `json:"rng_seed,omitempty"`
}

func oxiRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("oxi source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func oxiSourceLevel(id string, level int, raw json.RawMessage, field string) (OxiSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return OxiSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return OxiSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return OxiSourceLevel{}, fmt.Errorf("oxi source: %s %s level %d unavailable", id, field, level)
	}
	return OxiSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildOxiSourceSpec(st *OperatorStats, slot, skillLevel int) (*OxiSourceSpec, error) {
	if st == nil || st.CharID != oxiCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if st.Elite < 0 || st.Elite > 2 {
		return nil, fmt.Errorf("oxi source: elite %d out of range [0, 2]", st.Elite)
	}
	if st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("oxi source: potential %d out of range [1, 6]", st.Potential)
	}
	if slot < 1 || slot > 3 {
		return nil, fmt.Errorf("oxi source: slot %d out of range [1, 3]", slot)
	}
	if (slot == 2 && st.Elite < 1) || (slot == 3 && st.Elite < 2) {
		return nil, fmt.Errorf("oxi source: slot %d locked at elite %d", slot, st.Elite)
	}
	if skillLevel < 1 || skillLevel > 10 {
		return nil, fmt.Errorf("oxi source: skill level %d out of range [1, 10]", skillLevel)
	}

	charRecs, err := oxiRawRecords("character_table", oxiCharID)
	if err != nil {
		return nil, err
	}
	rawChar := charRecs[oxiCharID]

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
		return nil, fmt.Errorf("oxi source: slot %d exceeds skills count %d", slot, len(charFields.Skills))
	}
	selectedSkillID := charFields.Skills[slot-1].SkillID

	skillRecs, err := oxiRawRecords("skill_table", selectedSkillID)
	if err != nil {
		return nil, err
	}
	skillLvl, err := oxiSourceLevel(selectedSkillID, skillLevel, skillRecs[selectedSkillID], "levels")
	if err != nil {
		return nil, err
	}

	evidence := map[string]json.RawMessage{
		"character": append(json.RawMessage(nil), rawChar...),
		"skill":     append(json.RawMessage(nil), skillRecs[selectedSkillID]...),
	}

	out := &OxiSourceSpec{
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
			out.Talents = append(out.Talents, OxiTalentSource{
				Group:     groupIdx,
				Candidate: candIdxMatched,
				Raw:       append(json.RawMessage(nil), matchedCand...),
			})
		}
	}

	if st.Module != "" && st.ModuleLevel > 0 {
		return nil, fmt.Errorf("oxi source: unrecognized module id %s (oxi has no modules yet)", st.Module)
	}

	return out, nil
}

func oxiRemainingGapsFromSpec(source *OxiSourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	var gaps []mechanisms.Gap
	return gaps
}
