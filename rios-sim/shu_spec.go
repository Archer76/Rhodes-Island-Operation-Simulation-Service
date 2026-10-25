package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	shuCharID = "char_2025_shu"
	// 黍有两个专属模组：X「钦天司时」（uniequip_002）与 Y「好时节」
	// （uniequip_003）。两者都改写天赋，但改写的组不同（X 改天赋一、
	// Y 改天赋二 + 一条 talentIndex=-1 的隐藏候选），不能混档。
	shuXModuleID = "uniequip_002_shu"
	shuYModuleID = "uniequip_003_shu"
	// shuModuleID 保留给「默认 X 模组」的旧调用与测试。
	shuModuleID = shuXModuleID
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
	// ModuleKind 是模组档（"X"/"Y"），与 `Module.ID` 一起决定「哪些 part
	// 的 talentIndex 属于本模组」——分派时按它精确校验，交叉即拒收。
	ModuleKind string `json:"module_kind,omitempty"`
	// ModuleSeasonCandidates 是 Y 模组对**第二天赋**（talentIndex=1）的改写
	// 候选原文（max_hp/attack_speed/atk/interval/sp）。
	ModuleSeasonCandidates []json.RawMessage `json:"module_season_candidates,omitempty"`
	// ModuleConditionalAtk 是 Y 模组里 talentIndex=-1 的隐藏候选原文
	// （isHideTalent、黑板只有 atk）。数值与天赋描述里的「三条件达成两种
	// 额外 +3%/+5%」一一对应；语义在数据里没有明写，只存原文。
	ModuleConditionalAtk json.RawMessage `json:"module_conditional_atk,omitempty"`
	// TraitOverride 是模组对**职业特性**的覆写原文（X：治疗生命低于
	// 50% 的友方时治疗量提升 15%；Y：受到的伤害减少 15%）。它住
	// `parts[].overrideTraitDataBundle`，与 talent 改写不是同一个包。
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
	modules, err := shuRawRecords("battle_equip_table", shuXModuleID, shuYModuleID)
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
		kind := ""
		switch st.Module {
		case shuXModuleID:
			kind = "X"
		case shuYModuleID:
			kind = "Y"
		}
		if kind == "" || st.ModuleLevel > 3 || st.Elite != 2 || st.Level < 60 {
			return nil, fmt.Errorf("shu source: module %s level %d locked or unsupported", st.Module, st.ModuleLevel)
		}
		selected, err := shuSourceLevel(st.Module, st.ModuleLevel, modules[st.Module], "phases")
		if err != nil {
			return nil, err
		}
		out.Module = &selected
		out.ModuleKind = kind
		var phase struct {
			Parts []json.RawMessage `json:"parts"`
		}
		if err := json.Unmarshal(selected.Raw, &phase); err != nil {
			return nil, err
		}
		for _, raw := range phase.Parts {
			var part struct {
				Target string `json:"target"`
				Trait  struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"overrideTraitDataBundle"`
				Talent struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"addOrOverrideTalentDataBundle"`
			}
			if err := json.Unmarshal(raw, &part); err != nil {
				return nil, err
			}
			if part.Target == "TRAIT" {
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
				continue
			}
			if part.Target != "TALENT_DATA_ONLY" && part.Target != "TALENT" {
				out.Unresolved = append(out.Unresolved,
					fmt.Sprintf("%s Lv%d：未识别的 part target %q", st.Module, st.ModuleLevel, part.Target))
				continue
			}
			// 每个 talentIndex 取 requiredPotentialRank 最高的那一档（与 X 模组
			// 原来的选法一致），再按「模块 × talentIndex」精确分派。
			bestByIndex := map[int]json.RawMessage{}
			bestRankByIndex := map[int]int{}
			for _, cand := range part.Talent.Candidates {
				var c struct {
					TalentIndex           int  `json:"talentIndex"`
					IsHideTalent          bool `json:"isHideTalent"`
					UnlockCondition       struct {
						Phase any `json:"phase"`
						Level int `json:"level"`
					} `json:"unlockCondition"`
					RequiredPotentialRank int               `json:"requiredPotentialRank"`
					Blackboard            []json.RawMessage `json:"blackboard"`
				}
				if err := json.Unmarshal(cand, &c); err != nil {
					return nil, err
				}
				if phaseOf(c.UnlockCondition.Phase) > st.Elite || c.UnlockCondition.Level > st.Level ||
					c.RequiredPotentialRank > st.Potential-1 {
					continue
				}
				idx := c.TalentIndex
				if prev, ok := bestRankByIndex[idx]; !ok || c.RequiredPotentialRank > prev {
					bestByIndex[idx] = cand
					bestRankByIndex[idx] = c.RequiredPotentialRank
				}
			}
			for idx, cand := range bestByIndex {
				switch {
				case kind == "X" && idx == 0:
					// X：第一天赋「百谷长青」覆盖（播种回血与庇护）。
					out.ModuleCandidates = append(out.ModuleCandidates, cand)
				case kind == "Y" && idx == 1:
					// Y：第二天赋「天有四时」覆盖（max_hp/attack_speed/atk/
					// interval/sp）。
					out.ModuleSeasonCandidates = append(out.ModuleSeasonCandidates, cand)
				case kind == "Y" && idx == -1:
					// Y：talentIndex=-1 的隐藏候选（isHideTalent），黑板只有
					// `atk`；数值与天赋描述里的「三条件达成两种额外 +3%/+5%」
					// 一一对应。语义未在数据里明写，只存原文、由配置层按条件
					// 判定，语义登记在 Unresolved。
					out.ModuleConditionalAtk = append(json.RawMessage(nil), cand...)
				default:
					return nil, fmt.Errorf(
						"shu source: %s Lv%d 出现不属于该模组的 talentIndex=%d（拒绝交叉档）",
						st.Module, st.ModuleLevel, idx)
				}
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
