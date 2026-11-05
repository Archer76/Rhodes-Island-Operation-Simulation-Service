package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	mcnistCharID    = "char_4230_mcnist"
	mcnistTokenID   = "token_10069_mcnist_mcgraf"
	mcnistModule1ID = "uniequip_001_mcnist"
	mcnistModule2ID = "uniequip_002_mcnist"
)

// McnistSourceLevel 保存特定等级/阶段的原始证据
type McnistSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// McnistTalentSource 保存天赋组与候选原文
type McnistTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// McnistSourceSpec 声明机械师（char_4230_mcnist）机制来源证据与主战斗循环消费状态。
type McnistSourceSpec struct {
	ConsumerImplemented bool                       `json:"consumer_implemented"`
	Elite               int                        `json:"elite"`
	Level               int                        `json:"level"`
	Potential           int                        `json:"potential"`
	Slot                int                        `json:"slot"`
	SkillLevel          int                        `json:"skill_level"`
	Talents             []McnistTalentSource       `json:"talents"`
	OperatorSkill       McnistSourceLevel          `json:"operator_skill"`
	RawSlot             json.RawMessage            `json:"raw_slot"`
	Module              *McnistSourceLevel         `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage          `json:"module_candidates,omitempty"`
	TokenKey            string                     `json:"token_key"`
	TokenSkill          *McnistSourceLevel         `json:"token_skill,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	UserRulings         map[string]string          `json:"user_rulings"`
	Unresolved          []string                   `json:"unresolved"`
}

func mcnistRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
	blob, err := os.ReadFile(filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel", table+".json"))
	if err != nil {
		return nil, err
	}
	var records map[string]json.RawMessage
	if err := json.Unmarshal(blob, &records); err != nil {
		return nil, fmt.Errorf("mcnist: unmarshal %s: %w", table, err)
	}
	out := make(map[string]json.RawMessage, len(ids))
	for _, id := range ids {
		raw, ok := records[id]
		if !ok || string(raw) == "null" {
			return nil, fmt.Errorf("mcnist: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func mcnistSourceLevel(id string, level int, raw json.RawMessage, field string) (McnistSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return McnistSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return McnistSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return McnistSourceLevel{}, fmt.Errorf("mcnist source: %s %s level %d unavailable", id, field, level)
	}
	return McnistSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func mcnistRemainingGapsFromSpec(source *McnistSourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	var gaps []mechanisms.Gap
	return gaps
}

// buildMcnistSourceSpec 构建机械师的全量原始证据链
func buildMcnistSourceSpec(st *OperatorStats, slot, skillLevel int) (*McnistSourceSpec, error) {
	if st == nil || st.CharID != mcnistCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if slot < 1 || slot > 3 || st.Elite < 0 || st.Elite > 2 || st.Level < 1 || st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("mcnist source: invalid training or slot")
	}
	if slot > st.Elite+1 {
		return nil, fmt.Errorf("mcnist source: slot %d locked at E%d", slot, st.Elite)
	}

	chars, err := mcnistRawRecords("character_table", mcnistCharID, mcnistTokenID)
	if err != nil {
		return nil, err
	}
	skills, err := mcnistRawRecords("skill_table", "skchr_mcnist_1", "skchr_mcnist_2", "skchr_mcnist_3", "sktok_mcgraf_1", "sktok_mcgraf_2", "sktok_mcgraf_3")
	if err != nil {
		return nil, err
	}

	var opRow struct {
		Skills  []json.RawMessage `json:"skills"`
		Talents []json.RawMessage `json:"talents"`
	}
	if err := json.Unmarshal(chars[mcnistCharID], &opRow); err != nil {
		return nil, err
	}
	if slot < 1 || slot > len(opRow.Skills) {
		return nil, fmt.Errorf("mcnist source: slot %d unavailable", slot)
	}
	rawSlot := append(json.RawMessage(nil), opRow.Skills[slot-1]...)

	var slotMeta struct {
		SkillID string `json:"skillId"`
	}
	if err := json.Unmarshal(rawSlot, &slotMeta); err != nil {
		return nil, err
	}
	skillRaw, ok := skills[slotMeta.SkillID]
	if !ok {
		return nil, fmt.Errorf("mcnist source: skill %s missing", slotMeta.SkillID)
	}
	opSkillLevel, err := mcnistSourceLevel(slotMeta.SkillID, skillLevel, skillRaw, "levels")
	if err != nil {
		return nil, err
	}

	evidence := map[string]json.RawMessage{
		"character":       chars[mcnistCharID],
		"token_character": chars[mcnistTokenID],
		"skill":           opSkillLevel.Raw,
	}

	talents := make([]McnistTalentSource, 0, len(opRow.Talents))
	for gIdx, gRaw := range opRow.Talents {
		var group struct {
			Candidates []json.RawMessage `json:"candidates"`
		}
		if err := json.Unmarshal(gRaw, &group); err != nil {
			return nil, err
		}
		bestCandIdx := -1
		var bestCandRaw json.RawMessage
		for candIdx, candRaw := range group.Candidates {
			var cond struct {
				UnlockCond struct {
					Phase string `json:"phase"`
					Level int    `json:"level"`
				} `json:"unlockCondition"`
				RequiredPotentialRank int `json:"requiredPotentialRank"`
			}
			if err := json.Unmarshal(candRaw, &cond); err != nil {
				continue
			}

			phaseNum := 0
			switch cond.UnlockCond.Phase {
			case "PHASE_1":
				phaseNum = 1
			case "PHASE_2":
				phaseNum = 2
			}

			if st.Elite >= phaseNum && (st.Potential-1) >= cond.RequiredPotentialRank {
				if bestCandIdx == -1 || candIdx > bestCandIdx {
					bestCandIdx = candIdx
					bestCandRaw = candRaw
				}
			}
		}
		if bestCandIdx >= 0 {
			talents = append(talents, McnistTalentSource{
				Group:     gIdx,
				Candidate: bestCandIdx,
				Raw:       append(json.RawMessage(nil), bestCandRaw...),
			})
			evidence[fmt.Sprintf("talent_%d_%d", gIdx, bestCandIdx)] = bestCandRaw
		}
	}

	var moduleLevel *McnistSourceLevel
	var moduleCandidates []json.RawMessage
	if st.Module != "" && st.ModuleLevel > 0 {
		equips, err := mcnistRawRecords("battle_equip_table", st.Module)
		if err == nil {
			lvl, err := mcnistSourceLevel(st.Module, st.ModuleLevel, equips[st.Module], "phases")
			if err == nil {
				moduleLevel = &lvl
				evidence["module"] = lvl.Raw

				var phase struct {
					Parts []struct {
						Bundle struct {
							Candidates []json.RawMessage `json:"candidates"`
						} `json:"addOrOverrideTalentDataBundle"`
					} `json:"parts"`
				}
				if err := json.Unmarshal(lvl.Raw, &phase); err == nil {
					for _, part := range phase.Parts {
						for _, cand := range part.Bundle.Candidates {
							if len(cand) > 0 {
								moduleCandidates = append(moduleCandidates, cand)
							}
						}
					}
				}
			}
		}
	}

	// 召唤物对应技能（sktok_mcgraf_1, 2, 3）
	tokenSkillID := fmt.Sprintf("sktok_mcgraf_%d", slot)
	var tokenSkillLevel *McnistSourceLevel
	if tokRaw, ok := skills[tokenSkillID]; ok {
		tokLvl, err := mcnistSourceLevel(tokenSkillID, skillLevel, tokRaw, "levels")
		if err == nil {
			tokenSkillLevel = &tokLvl
			evidence["token_skill"] = tokLvl.Raw
		}
	}

	out := &McnistSourceSpec{
		ConsumerImplemented: true,
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		Talents:             talents,
		OperatorSkill:       opSkillLevel,
		RawSlot:             rawSlot,
		Module:              moduleLevel,
		ModuleCandidates:    moduleCandidates,
		TokenKey:            mcnistTokenID,
		TokenSkill:          tokenSkillLevel,
		Evidence:            evidence,
		UserRulings: map[string]string{
			"overkill_protection": "第二天赋生命方程屏障抵挡单次超额伤害，剩余屏障归零且本体不受超额伤害",
			"barrier_stack":       "自身与召唤物各持有一组独立屏障，二技能重装填与破裂伤害独立计算",
			"s3_dash":             "三技能开启时结构性原理朝部署朝向冲锋至阻挡/高台地块重置并施加虚弱衰减光环",
		},
		Unresolved: nil,
	}
	return out, nil
}
