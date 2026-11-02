package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	tockaCharID = "char_4244_tocka"
)

// TockaSourceLevel 保存特定等级/阶段的原始证据
type TockaSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// TockaTalentSource 保存天赋组与候选原文
type TockaTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// TockaSourceSpec 声明冻河（char_4244_tocka）的机制来源证据与主战斗循环消费状态。
//
// 这里**只存原文**：天赋/技能的数值一律由 decodeTockaRuntimeConfig 从这些 Raw 里解析。
// 规格层不手写任何一个硬编码数值。
type TockaSourceSpec struct {
	ConsumerImplemented bool                       `json:"consumer_implemented"`
	Elite               int                        `json:"elite"`
	Level               int                        `json:"level"`
	Potential           int                        `json:"potential"`
	Slot                int                        `json:"slot"`
	SkillLevel          int                        `json:"skill_level"`
	Talents             []TockaTalentSource        `json:"talents"`
	OperatorSkill       TockaSourceLevel           `json:"operator_skill"`
	RawSlot             json.RawMessage            `json:"raw_slot"`
	Module              *TockaSourceLevel          `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage          `json:"module_candidates,omitempty"`
	ModuleKind          string                     `json:"module_kind,omitempty"`
	TraitOverride       json.RawMessage            `json:"trait_override,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	Unresolved          []string                   `json:"unresolved"`
	RNGSeed             uint64                     `json:"rng_seed,omitempty"`
}

func tockaRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("tocka source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func tockaSourceLevel(id string, level int, raw json.RawMessage, field string) (TockaSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return TockaSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return TockaSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return TockaSourceLevel{}, fmt.Errorf("tocka source: %s %s level %d unavailable", id, field, level)
	}
	return TockaSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildTockaSourceSpec(st *OperatorStats, slot, skillLevel int) (*TockaSourceSpec, error) {
	if st == nil || st.CharID != tockaCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if st.Elite < 0 || st.Elite > 2 {
		return nil, fmt.Errorf("tocka source: elite %d out of range [0, 2]", st.Elite)
	}
	if st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("tocka source: potential %d out of range [1, 6]", st.Potential)
	}
	if slot < 1 || slot > 3 {
		return nil, fmt.Errorf("tocka source: slot %d out of range [1, 3]", slot)
	}
	if skillLevel < 1 || skillLevel > 10 {
		return nil, fmt.Errorf("tocka source: skill level %d out of range [1, 10]", skillLevel)
	}

	evidence := make(map[string]json.RawMessage)
	charRecs, err := tockaRawRecords("character_table", tockaCharID)
	if err != nil {
		return nil, err
	}
	charRaw := charRecs[tockaCharID]
	evidence["character"] = append(json.RawMessage(nil), charRaw...)

	var charFields struct {
		Talents []struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"talents"`
		Skills []struct {
			SkillID string `json:"skillId"`
		} `json:"skills"`
	}
	if err := json.Unmarshal(charRaw, &charFields); err != nil {
		return nil, err
	}
	if slot > len(charFields.Skills) {
		return nil, fmt.Errorf("tocka source: slot %d not found in character_table", slot)
	}
	skillID := charFields.Skills[slot-1].SkillID

	skillRecs, err := tockaRawRecords("skill_table", skillID)
	if err != nil {
		return nil, err
	}
	skillRaw := skillRecs[skillID]
	evidence["skill"] = append(json.RawMessage(nil), skillRaw...)

	skillLevelData, err := tockaSourceLevel(skillID, skillLevel, skillRaw, "levels")
	if err != nil {
		return nil, err
	}

	out := &TockaSourceSpec{
		ConsumerImplemented: true,
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		OperatorSkill:       skillLevelData,
		Evidence:            evidence,
		Unresolved:          make([]string, 0),
		RNGSeed:             defaultProbRNGSeed,
	}

	// 映射天赋：候选匹配当前精英与潜能
	potIndex := st.Potential - 1
	for groupIdx, tGroup := range charFields.Talents {
		bestCandIdx := -1
		var bestCandRaw json.RawMessage
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

			phaseNum := 0
			switch cond.UnlockCondition.Phase {
			case "PHASE_1":
				phaseNum = 1
			case "PHASE_2":
				phaseNum = 2
			}

			if st.Elite >= phaseNum && potIndex >= cond.RequiredPotentialRank {
				if bestCandIdx == -1 || candIdx > bestCandIdx {
					bestCandIdx = candIdx
					bestCandRaw = candRaw
				}
			}
		}

		if bestCandIdx >= 0 {
			out.Talents = append(out.Talents, TockaTalentSource{
				Group:     groupIdx,
				Candidate: bestCandIdx,
				Raw:       append(json.RawMessage(nil), bestCandRaw...),
			})
		}
	}

	return out, nil
}

func tockaRemainingGapsFromSpec(source *TockaSourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	var gaps []mechanisms.Gap
	return gaps
}
