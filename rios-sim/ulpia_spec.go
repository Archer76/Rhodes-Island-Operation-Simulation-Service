package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	ulpiaCharID    = "char_4145_ulpia"
	ulpiaModule1ID = "uniequip_002_ulpia" // 模组X: 乌尔比安的新晨 (CRU-X)
	ulpiaModule2ID = "uniequip_003_ulpia" // 模组Y: 往前路去 (CRU-Y)
)

// UlpiaSourceLevel 保存特定等级/阶段的原始证据
type UlpiaSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// UlpiaTalentSource 保存天赋组与候选原文
type UlpiaTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// UlpiaSourceSpec 声明乌尔比安（char_4145_ulpia）的机制来源证据与主战斗循环消费状态。
//
// 严格遵循 docs/operator-mechanics-workflow.md：
// 这里只存 gamedata 原文，不手写任何一个硬编码数值。
type UlpiaSourceSpec struct {
	ConsumerImplemented bool                 `json:"consumer_implemented"`
	Elite               int                  `json:"elite"`
	Level               int                  `json:"level"`
	Potential           int                  `json:"potential"`
	Slot                int                  `json:"slot"`
	SkillLevel          int                  `json:"skill_level"`
	Talents             []UlpiaTalentSource  `json:"talents"`
	OperatorSkill       UlpiaSourceLevel     `json:"operator_skill"`
	RawSlot             json.RawMessage      `json:"raw_slot"`
	Module              *UlpiaSourceLevel    `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage    `json:"module_candidates,omitempty"`
	TraitOverride       json.RawMessage      `json:"trait_override,omitempty"`
	SkillRangeAbsCells  [][2]int             `json:"skill_range_abs_cells,omitempty"`
	Evidence            map[string]json.RawMessage `json:"evidence"`
	Unresolved          []string             `json:"unresolved"`
}

func ulpiaRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
	blob, err := os.ReadFile(filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel", table+".json"))
	if err != nil {
		return nil, err
	}
	var records map[string]json.RawMessage
	if err := json.Unmarshal(blob, &records); err != nil {
		return nil, fmt.Errorf("ulpia: unmarshal %s: %w", table, err)
	}
	out := make(map[string]json.RawMessage, len(ids))
	for _, id := range ids {
		raw, ok := records[id]
		if !ok {
			return nil, fmt.Errorf("ulpia: %s not in %s", id, table)
		}
		out[id] = raw
	}
	return out, nil
}

func ulpiaSourceLevel(id string, level int, raw json.RawMessage, field string) (UlpiaSourceLevel, error) {
	var row struct {
		Levels []json.RawMessage `json:"levels"`
		Phases []json.RawMessage `json:"phases"`
	}
	if err := json.Unmarshal(raw, &row); err != nil {
		return UlpiaSourceLevel{}, err
	}
	var rows []json.RawMessage
	switch field {
	case "levels":
		rows = row.Levels
	case "phases":
		rows = row.Phases
	default:
		return UlpiaSourceLevel{}, fmt.Errorf("ulpia source: unsupported field %s", field)
	}
	if level <= 0 || level > len(rows) {
		return UlpiaSourceLevel{}, fmt.Errorf("ulpia source: %s %s level %d unavailable", id, field, level)
	}
	return UlpiaSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

// buildUlpiaSourceSpec 为乌尔比安构建全量原始证据链。
func buildUlpiaSourceSpec(st *OperatorStats, slot, skillLevel int) (*UlpiaSourceSpec, error) {
	if st == nil || st.CharID != ulpiaCharID {
		return nil, nil
	}
	if slot < 1 || slot > 3 {
		return nil, fmt.Errorf("ulpia spec: slot %d out of range [1,3]", slot)
	}
	if st.Elite < 0 || st.Elite > 2 || st.Level < 1 || st.Level > 90 || st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("ulpia spec: invalid training E%d L%d P%d", st.Elite, st.Level, st.Potential)
	}
	if slot == 2 && st.Elite < 1 {
		return nil, fmt.Errorf("ulpia spec: slot %d locked at elite %d", slot, st.Elite)
	}
	if slot == 3 && st.Elite < 2 {
		return nil, fmt.Errorf("ulpia spec: slot %d locked at elite %d", slot, st.Elite)
	}
	if skillLevel < 1 || skillLevel > 10 {
		return nil, fmt.Errorf("ulpia spec: skill level %d out of range [1,10]", skillLevel)
	}
	if skillLevel > 7 && st.Elite < 2 {
		return nil, fmt.Errorf("ulpia spec: skill mastery requires elite 2, got elite %d", st.Elite)
	}

	charRecords, err := ulpiaRawRecords("character_table", ulpiaCharID)
	if err != nil {
		return nil, err
	}
	charRaw := charRecords[ulpiaCharID]
	var char struct {
		Skills []struct {
			SkillID string `json:"skillId"`
		} `json:"skills"`
	}
	if err := json.Unmarshal(charRaw, &char); err != nil {
		return nil, fmt.Errorf("ulpia spec: unmarshal char: %w", err)
	}
	if slot > len(char.Skills) {
		return nil, fmt.Errorf("ulpia spec: slot %d > total %d", slot, len(char.Skills))
	}
	slotData := char.Skills[slot-1]
	rawSlot, err := json.Marshal(slotData)
	if err != nil {
		return nil, fmt.Errorf("ulpia spec: slot %d skillId: %w", slot, err)
	}

	skillRecords, err := ulpiaRawRecords("skill_table", slotData.SkillID)
	if err != nil {
		return nil, err
	}
	skillRaw := skillRecords[slotData.SkillID]
	skillLvl, err := ulpiaSourceLevel(slotData.SkillID, skillLevel, skillRaw, "levels")
	if err != nil {
		return nil, err
	}

	evidence := map[string]json.RawMessage{
		"character_table:" + ulpiaCharID: charRaw,
		"skill_table:" + slotData.SkillID: skillRaw,
	}

	out := &UlpiaSourceSpec{
		ConsumerImplemented: true,
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		OperatorSkill:       skillLvl,
		RawSlot:             rawSlot,
		Evidence:            evidence,
	}

	// 模组提取（若有装备且在 E2）
	if st.Module != "" && st.ModuleLevel > 0 {
		modID := st.Module
		if modID != ulpiaModule1ID && modID != ulpiaModule2ID {
			return nil, fmt.Errorf("ulpia spec: unsupported module %s", modID)
		}
		if st.Elite < 2 {
			return nil, fmt.Errorf("ulpia spec: module %s requires elite 2, got elite %d", modID, st.Elite)
		}
		if st.ModuleLevel < 1 || st.ModuleLevel > 3 {
			return nil, fmt.Errorf("ulpia spec: module level %d out of range [1,3]", st.ModuleLevel)
		}
		modRecords, err := ulpiaRawRecords("battle_equip_table", modID)
		if err != nil {
			return nil, err
		}
		evidence["battle_equip_table:"+modID] = modRecords[modID]
		modLvl, err := ulpiaSourceLevel(modID, st.ModuleLevel, modRecords[modID], "phases")
		if err != nil {
			return nil, err
		}
		out.Module = &modLvl

		// 解析 parts: overrideTraitDataBundle 与 addOrOverrideTalentDataBundle
		var phase struct {
			Parts []struct {
				Target                     string `json:"target"`
				OverrideTraitDataBundle    *struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"overrideTraitDataBundle"`
				AddOrOverrideTalentDataBundle *struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"addOrOverrideTalentDataBundle"`
			} `json:"parts"`
		}
		if err := json.Unmarshal(modLvl.Raw, &phase); err != nil {
			return nil, fmt.Errorf("ulpia spec: module phase unmarshal: %w", err)
		}
		for _, part := range phase.Parts {
			if part.Target == "TRAIT" && part.OverrideTraitDataBundle != nil && len(part.OverrideTraitDataBundle.Candidates) > 0 {
				out.TraitOverride = part.OverrideTraitDataBundle.Candidates[0]
			}
			if (part.Target == "TALENT" || part.Target == "TALENT_DATA_ONLY") && part.AddOrOverrideTalentDataBundle != nil {
				out.ModuleCandidates = append(out.ModuleCandidates, part.AddOrOverrideTalentDataBundle.Candidates...)
			}
		}
	}

	// 天赋提取：解析 character_table 的 talents
	var charTalents struct {
		Talents []struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"talents"`
	}
	if err := json.Unmarshal(charRaw, &charTalents); err != nil {
		return nil, fmt.Errorf("ulpia spec: unmarshal talents: %w", err)
	}

	for gIdx, group := range charTalents.Talents {
		var selected json.RawMessage
		candIdx := -1
		for cIdx, candRaw := range group.Candidates {
			var cond struct {
				UnlockCondition struct {
					Phase string `json:"phase"`
					Level int    `json:"level"`
				} `json:"unlockCondition"`
				RequiredPotentialRank int `json:"requiredPotentialRank"`
			}
			if err := json.Unmarshal(candRaw, &cond); err != nil {
				return nil, fmt.Errorf("ulpia spec: talent cond unmarshal: %w", err)
			}
			reqPhase := 0
			switch cond.UnlockCondition.Phase {
			case "PHASE_1":
				reqPhase = 1
			case "PHASE_2":
				reqPhase = 2
			}
			if st.Elite < reqPhase || (st.Elite == reqPhase && st.Level < cond.UnlockCondition.Level) {
				continue
			}
			// 游戏内潜能 1-6 对应 requiredPotentialRank 0-5
			if (st.Potential - 1) < cond.RequiredPotentialRank {
				continue
			}
			selected = candRaw
			candIdx = cIdx
		}
		if selected != nil && candIdx >= 0 {
			out.Talents = append(out.Talents, UlpiaTalentSource{
				Group:     gIdx,
				Candidate: candIdx,
				Raw:       selected,
			})
		}
	}

	return out, nil
}

func attachUlpiaSkillRange(spec *UlpiaSourceSpec, direction string, pos [2]int) error {
	if spec == nil {
		return nil
	}
	cfg, err := decodeUlpiaRuntimeConfig(spec)
	if err != nil {
		return err
	}
	if cfg.SkillRangeID == "" || len(cfg.SkillRangeCells) == 0 {
		return nil
	}
	rel := make([]Cell, 0, len(cfg.SkillRangeCells))
	for _, c := range cfg.SkillRangeCells {
		rel = append(rel, Cell{c[0], c[1]})
	}
	fp, err := Footprint(rel, direction, pos[0], pos[1])
	if err != nil {
		return fmt.Errorf("ulpia spec: skill range %s: %w", cfg.SkillRangeID, err)
	}
	out := make([][2]int, 0, len(fp))
	seen := map[[2]int]bool{}
	for _, c := range fp {
		v := [2]int{c[0], c[1]}
		if seen[v] {
			continue
		}
		seen[v] = true
		out = append(out, v)
	}
	sortRangeCells(out)
	spec.SkillRangeAbsCells = out
	return nil
}

// ulpiaRemainingGapsFromSpec 收集并上报乌尔比安没有运行期消费者的机制。
//
// 零近似原则：
// 1. 技能一的 force 属于位移机制（roadmap M-X2），本仓无位移实体系统，必须具名 Gap 拒判。
// 2. 技能三的船锚投掷、落点部署检测与干员位移/返回属于位移与复杂实体机制（roadmap M-X2），具名 Gap 拒判。
// 3. 第二天赋中对其他【深海猎人】干员的增益（ulpia_t_1[abyssal].*），因目前无跨干员深海猎人阵营全局广播，未消费具名上报。
func ulpiaRemainingGapsFromSpec(source *UlpiaSourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	cfg, err := decodeUlpiaRuntimeConfig(source)
	if err != nil {
		return []mechanisms.Gap{{
			ID: "ulpia.config.decode", CharID: ulpiaCharID, Operator: opName,
			Source: "skill", Status: "incomplete", Instance: instance,
			Reason: fmt.Sprintf("乌尔比安的配置解码失败：%v", err),
		}}
	}
	var gaps []mechanisms.Gap
	add := func(id, source, key, reason string) {
		gaps = append(gaps, mechanisms.Gap{
			ID: id, CharID: ulpiaCharID, Operator: opName,
			Source: source, SourceID: source + ":ulpia", Key: key,
			Status: "unimplemented", Instance: instance, Reason: reason,
		})
	}

	// 未消费黑板键
	for _, key := range cfg.UnusedKeys {
		add("ulpia.unknown_key."+key, "skill", key,
			"乌尔比安的该黑板键没有运行期消费者；未消费即具名登记，不作静默忽略")
	}

	// 技能一：force 位移拖拽
	if cfg.Slot == 1 && cfg.S1Force > 0 {
		add("ulpia.skill1.displacement_force", "skill", "force",
			"技能一「必须促成的接触」的「船锚拖拽敌人至面前」包含位移力度（force），属 roadmap M-X2 位移实体缺口；"+
				"按零近似原则严禁以原地攻击假装实现，必须具名拒判")
	}

	// 技能三：船锚位移与落点转移
	if cfg.Slot == 3 {
		add("ulpia.skill3.projectile_displacement", "skill", "projectile_range",
			"技能三「必须开辟的通路」的「投出船锚、若停留位置可部署则位移到该位置、技能结束返回原位」包含复杂位移与外部实体，"+
				"属 roadmap M-X2 位移机制；按零近似原则具名拒判")
	}

	// 第二天赋：深海猎人全队光环增益
	if cfg.Talent2Enabled && cfg.Talent2AbyssalMaxHP > 0 {
		add("ulpia.talent2.abyssal_aura", "talent", "ulpia_t_1[abyssal].max_hp",
			"第二天赋「血脉的哺养」对其他【深海猎人】干员的增益效果（ulpia_t_1[abyssal].*）尚未接入跨干员阵营广播，具名上报")
	}

	return gaps
}
