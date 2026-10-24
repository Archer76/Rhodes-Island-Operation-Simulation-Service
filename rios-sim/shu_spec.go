package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	shuCharID   = "char_2025_shu"
	shuModuleID = "uniequip_002_shu"
)

// ShuSourceLevel 保存特定等级/阶段的原始证据
type ShuSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// ShuTalentSource 保存天赋组与候选原文
type ShuTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// ShuSourceSpec 声明黍（char_2025_shu）的机制来源证据与主战斗循环消费状态。
//
// 这里**只存原文**：天赋/模组/技能的数值一律由 `decodeShuRuntimeConfig`
// 从这些 Raw 里解析。规格层不写死任何一个数——这是 docs/operator-mechanics-workflow.md
// 第一条纪律（不手写硬编码数值）。
type ShuSourceSpec struct {
	ConsumerImplemented bool              `json:"consumer_implemented"`
	Elite               int               `json:"elite"`
	Level               int               `json:"level"`
	Potential           int               `json:"potential"`
	Slot                int               `json:"slot"`
	SkillLevel          int               `json:"skill_level"`
	Talents             []ShuTalentSource `json:"talents"`
	OperatorSkill       ShuSourceLevel    `json:"operator_skill"`
	RawSlot             json.RawMessage   `json:"raw_slot"`
	Module              *ShuSourceLevel   `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage `json:"module_candidates,omitempty"`
	// TraitOverride 是模组对**职业特性**的覆写原文（黍的模组：治疗生命低于
	// 50% 的友方时治疗量提升 15%）。它住 `parts[].overrideTraitDataBundle`，
	// 与 `ModuleCandidates`（talent 改写）不是同一个包。
	TraitOverride json.RawMessage            `json:"trait_override,omitempty"`
	Evidence      map[string]json.RawMessage `json:"evidence"`
	Unresolved    []string                   `json:"unresolved"`
}

func shuRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
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
			return nil, fmt.Errorf("shu source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func shuSourceLevel(id string, level int, raw json.RawMessage, field string) (ShuSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return ShuSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return ShuSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return ShuSourceLevel{}, fmt.Errorf("shu source: %s %s level %d unavailable", id, field, level)
	}
	return ShuSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildShuSourceSpec(st *OperatorStats, slot, skillLevel int) (*ShuSourceSpec, error) {
	if st.CharID != shuCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if slot < 1 || slot > 3 || st.Elite < 0 || st.Elite > 2 || st.Level < 1 || st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("shu source: invalid training or slot")
	}
	if slot > st.Elite+1 {
		return nil, fmt.Errorf("shu source: slot %d locked at E%d", slot, st.Elite)
	}

	chars, err := shuRawRecords("character_table", shuCharID)
	if err != nil {
		return nil, err
	}
	skillIDs := []string{"skchr_shu_1", "skchr_shu_2", "skchr_shu_3"}
	skills, err := shuRawRecords("skill_table", skillIDs...)
	if err != nil {
		return nil, err
	}
	modules, err := shuRawRecords("battle_equip_table", shuModuleID)
	if err != nil {
		return nil, err
	}

	var char struct {
		Talents []json.RawMessage `json:"talents"`
		Skills  []json.RawMessage `json:"skills"`
	}
	if err := json.Unmarshal(chars[shuCharID], &char); err != nil {
		return nil, err
	}
	if len(char.Skills) != 3 {
		return nil, fmt.Errorf("shu source: expected three raw skill slots")
	}

	out := &ShuSourceSpec{
		ConsumerImplemented: true,
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		RawSlot:             char.Skills[slot-1],
		Evidence:            map[string]json.RawMessage{},
		Unresolved:          []string{},
	}

	for _, records := range []map[string]json.RawMessage{chars, skills, modules} {
		for id, raw := range records {
			out.Evidence[id] = raw
		}
	}

	for _, t := range resolveTalents(char.Talents, st.Elite, st.Level, st.Potential) {
		out.Talents = append(out.Talents, ShuTalentSource{Group: t.GroupIndex, Candidate: t.CandidateIndex, Raw: t.RawSource})
	}

	out.OperatorSkill, err = shuSourceLevel(skillIDs[slot-1], skillLevel, skills[skillIDs[slot-1]], "levels")
	if err != nil {
		return nil, err
	}

	if st.Module != "" && st.ModuleLevel > 0 {
		if st.Module != shuModuleID || st.ModuleLevel > 3 || st.Elite != 2 || st.Level < 60 {
			return nil, fmt.Errorf("shu source: module %s level %d locked or unsupported", st.Module, st.ModuleLevel)
		}
		selected, err := shuSourceLevel(shuModuleID, st.ModuleLevel, modules[shuModuleID], "phases")
		if err != nil {
			return nil, err
		}
		out.Module = &selected
		var phase struct {
			Parts []json.RawMessage `json:"parts"`
		}
		if err := json.Unmarshal(selected.Raw, &phase); err != nil {
			return nil, err
		}
		for _, raw := range phase.Parts {
			var part struct {
				Trait struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"overrideTraitDataBundle"`
				Talent struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"addOrOverrideTalentDataBundle"`
			}
			if err := json.Unmarshal(raw, &part); err != nil {
				return nil, err
			}
			// 特性覆写：取当前精英/等级/潜能可用的那一档（模组对特性只写
			// 一条候选，仍按同一套门槛筛选，避免把未解锁的档吃进来）。
			var bestTrait json.RawMessage
			traitRank := -1
			for _, cand := range part.Trait.Candidates {
				var c moduleSpeedCandidate
				if err := json.Unmarshal(cand, &c); err != nil {
					return nil, err
				}
				if phaseOf(c.UnlockCondition.Phase) <= st.Elite && c.UnlockCondition.Level <= st.Level && c.RequiredPotentialRank <= st.Potential-1 && c.RequiredPotentialRank > traitRank {
					bestTrait = cand
					traitRank = c.RequiredPotentialRank
				}
			}
			if bestTrait != nil {
				out.TraitOverride = bestTrait
			}
			var best json.RawMessage
			rank := -1
			for _, cand := range part.Talent.Candidates {
				var c moduleSpeedCandidate
				if err := json.Unmarshal(cand, &c); err != nil {
					return nil, err
				}
				if phaseOf(c.UnlockCondition.Phase) <= st.Elite && c.UnlockCondition.Level <= st.Level && c.RequiredPotentialRank <= st.Potential-1 && c.RequiredPotentialRank > rank {
					best = cand
					rank = c.RequiredPotentialRank
				}
			}
			if best != nil {
				out.ModuleCandidates = append(out.ModuleCandidates, best)
			}
		}
	}

	return out, nil
}

// shuRemainingGapsFromSpec 列出黍机制里**尚未被运行期消费**的黑板键。
//
// 它存在的理由与 `specMechanismGaps` 里其余分支同族：豁免必须是"已消费"的
// 断言，而不是"这条分支我写了个空 else"。返回空表示当前训练档下所有黑板键
// 都有归宿。
//
// ⚠ `Unresolved`（传送触发频率、技能三治疗人数等语义待证项）**不**在这里
// 生成 Gap：它们是"口径待证"，不是"机制没建"。报成 Gap 会让整场拒跑，
// 把"已建模但口径待核"错变成"不能模拟"。这些项落进机制文档的裁决栏。
func shuRemainingGapsFromSpec(source *ShuSourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	cfg, err := decodeShuRuntimeConfig(source)
	if err != nil {
		return []mechanisms.Gap{{
			ID: "shu.config.decode", CharID: shuCharID, Operator: opName,
			Source: "skill", Status: "incomplete", Instance: instance,
			Reason: fmt.Sprintf("黍的配置解码失败：%v", err),
		}}
	}
	var gaps []mechanisms.Gap
	for _, key := range cfg.UnusedKeys {
		gaps = append(gaps, mechanisms.Gap{
			ID: "shu.unknown_key." + key, CharID: shuCharID, Operator: opName,
			Source: "skill", SourceID: "skill:slot", Key: key,
			Status: "unidentified", Instance: instance,
			Reason: "黍的该黑板键没有运行期消费者；未消费即具名登记，不作静默忽略",
		})
	}
	return gaps
}
