package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	dminonCharID    = "char_4246_dminon"
	dminonXModuleID = "uniequip_002_dminon"
)

// DminonSourceLevel 保存特定等级/阶段的原始证据
type DminonSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// DminonTalentSource 保存天赋组与候选原文
type DminonTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// DminonSourceSpec 声明国度（char_4246_dminon）的机制来源证据与主战斗循环消费状态。
//
// 规格层只存原文与绝对格缓存：天赋/模组/技能的数值一律由 decodeDminonRuntimeConfig 解析。
// 严禁手写硬编码数值。
type DminonSourceSpec struct {
	ConsumerImplemented bool                       `json:"consumer_implemented"`
	Elite               int                        `json:"elite"`
	Level               int                        `json:"level"`
	Potential           int                        `json:"potential"`
	Slot                int                        `json:"slot"`
	SkillLevel          int                        `json:"skill_level"`
	Talents             []DminonTalentSource       `json:"talents"`
	OperatorSkill       DminonSourceLevel          `json:"operator_skill"`
	Module              *DminonSourceLevel         `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage          `json:"module_candidates,omitempty"`
	ModuleKind          string                     `json:"module_kind,omitempty"`
	TraitOverride       json.RawMessage            `json:"trait_override,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	SkillRangeAbsCells  [][2]int                   `json:"skill_range_abs_cells,omitempty"`
	BaseRangeAbsCells   [][2]int                   `json:"base_range_abs_cells,omitempty"`
	Unresolved          []string                   `json:"unresolved"`
	RNGSeed             uint64                     `json:"rng_seed,omitempty"`
}

func dminonRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("dminon source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func dminonSourceLevel(id string, level int, raw json.RawMessage, field string) (DminonSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return DminonSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return DminonSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return DminonSourceLevel{}, fmt.Errorf("dminon source: %s %s level %d unavailable", id, field, level)
	}
	return DminonSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildDminonSourceSpec(st *OperatorStats, slot, skillLevel int) (*DminonSourceSpec, error) {
	if st == nil || st.CharID != dminonCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if st.Elite < 0 || st.Elite > 2 {
		return nil, fmt.Errorf("dminon source: elite %d out of range [0, 2]", st.Elite)
	}
	if st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("dminon source: potential %d out of range [1, 6]", st.Potential)
	}
	if slot < 1 || slot > 3 {
		return nil, fmt.Errorf("dminon source: slot %d out of range [1, 3]", slot)
	}
	if (slot == 2 && st.Elite < 1) || (slot == 3 && st.Elite < 2) {
		return nil, fmt.Errorf("dminon source: slot %d locked at elite %d", slot, st.Elite)
	}
	if skillLevel < 1 || skillLevel > 10 {
		return nil, fmt.Errorf("dminon source: skill level %d out of range [1, 10]", skillLevel)
	}

	charRecs, err := dminonRawRecords("character_table", dminonCharID)
	if err != nil {
		return nil, err
	}
	rawChar := charRecs[dminonCharID]

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
		return nil, fmt.Errorf("dminon source: slot %d exceeds skills count %d", slot, len(charFields.Skills))
	}
	selectedSkillID := charFields.Skills[slot-1].SkillID

	skillRecs, err := dminonRawRecords("skill_table", selectedSkillID)
	if err != nil {
		return nil, err
	}
	skillLvl, err := dminonSourceLevel(selectedSkillID, skillLevel, skillRecs[selectedSkillID], "levels")
	if err != nil {
		return nil, err
	}

	evidence := map[string]json.RawMessage{
		"character": append(json.RawMessage(nil), rawChar...),
		"skill":     append(json.RawMessage(nil), skillRecs[selectedSkillID]...),
	}

	out := &DminonSourceSpec{
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
			out.Talents = append(out.Talents, DminonTalentSource{
				Group:     groupIdx,
				Candidate: candIdxMatched,
				Raw:       append(json.RawMessage(nil), matchedCand...),
			})
		}
	}

	modID := st.Module
	if modID != "" && st.ModuleLevel > 0 {
		if modID != dminonXModuleID {
			return nil, fmt.Errorf("dminon source: unrecognized module id %s", modID)
		}
		out.ModuleKind = "X"

		equipRecs, err := dminonRawRecords("battle_equip_table", modID)
		if err != nil {
			return nil, err
		}
		modRaw := equipRecs[modID]
		evidence["module"] = append(json.RawMessage(nil), modRaw...)

		modLvl, err := dminonSourceLevel(modID, st.ModuleLevel, modRaw, "phases")
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

// attachDminonSkillRange 将常态范围与技能范围折算为绝对格缓存
func attachDminonSkillRange(spec *DminonSourceSpec, direction string, pos [2]int) error {
	if spec == nil {
		return nil
	}
	cfg, err := decodeDminonRuntimeConfig(spec)
	if err != nil {
		return err
	}

	// 1. 常态攻击范围 y-1
	baseRangeID := "y-1"
	baseRecs, err := dminonRawRecords("range_table", baseRangeID)
	if err == nil && len(baseRecs[baseRangeID]) > 0 {
		var rf struct {
			Grids []struct {
				Row int `json:"row"`
				Col int `json:"col"`
			} `json:"grids"`
		}
		if err := json.Unmarshal(baseRecs[baseRangeID], &rf); err == nil {
			rel := make([]Cell, 0, len(rf.Grids))
			for _, g := range rf.Grids {
				rel = append(rel, Cell{g.Col, g.Row})
			}
			fp, err := Footprint(rel, direction, pos[0], pos[1])
			if err == nil {
				out := make([][2]int, 0, len(fp))
				seen := map[[2]int]bool{}
				for _, c := range fp {
					v := [2]int{c[0], c[1]}
					if !seen[v] {
						seen[v] = true
						out = append(out, v)
					}
				}
				sortRangeCells(out)
				spec.BaseRangeAbsCells = out
			}
		}
	}

	// 2. 技能范围（若有）
	if cfg.SkillRangeID != "" && len(cfg.SkillRangeCells) > 0 {
		rel := make([]Cell, 0, len(cfg.SkillRangeCells))
		for _, c := range cfg.SkillRangeCells {
			rel = append(rel, Cell{c[0], c[1]})
		}
		fp, err := Footprint(rel, direction, pos[0], pos[1])
		if err != nil {
			return fmt.Errorf("dminon spec: skill range %s: %w", cfg.SkillRangeID, err)
		}
		out := make([][2]int, 0, len(fp))
		seen := map[[2]int]bool{}
		for _, c := range fp {
			v := [2]int{c[0], c[1]}
			if !seen[v] {
				seen[v] = true
				out = append(out, v)
			}
		}
		sortRangeCells(out)
		spec.SkillRangeAbsCells = out
	}
	return nil
}

func dminonRemainingGapsFromSpec(source *DminonSourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	var gaps []mechanisms.Gap
	return gaps
}
