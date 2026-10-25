package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const (
	logosCharID    = "char_4133_logos"
	logosModule1ID = "uniequip_002_logos" // 模组X: 来自河谷的笔盒
	logosModule2ID = "uniequip_003_logos" // 模组Y: 《语义范式百科》
)

// LogosSourceLevel 保存特定等级/阶段的原始证据
type LogosSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}

// LogosTalentSource 保存天赋组与候选原文
type LogosTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}

// LogosSourceSpec 声明逻各斯（char_4133_logos）的机制来源证据与主战斗循环消费状态。
//
// 严格遵循 docs/operator-mechanics-workflow.md：
// 这里只存 gamedata 原文，不手写任何一个硬编码数值。
type LogosSourceSpec struct {
	ConsumerImplemented bool                `json:"consumer_implemented"`
	Elite               int                 `json:"elite"`
	Level               int                 `json:"level"`
	Potential           int                 `json:"potential"`
	Slot                int                 `json:"slot"`
	SkillLevel          int                 `json:"skill_level"`
	Talents             []LogosTalentSource `json:"talents"`
	OperatorSkill       LogosSourceLevel    `json:"operator_skill"`
	RawSlot             json.RawMessage     `json:"raw_slot"`
	Module              *LogosSourceLevel   `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage   `json:"module_candidates,omitempty"`
	TraitOverride       json.RawMessage     `json:"trait_override,omitempty"`
	// SkillRangeAbsCells 是技能范围（`rangeId`，如 3-3 / 3-4）在该次部署的
	// **绝对格**。它在建规格时按部署朝向算一次：运行期没有朝向（`operator`
	// 只带绝对格 `Range`），重算就是第二套旋转口径。
	SkillRangeAbsCells [][2]int `json:"skill_range_abs_cells,omitempty"`
	// RNGSeed 是概率事件（第一天赋「语汇演化」）的**采样种子**。
	//
	// 博士 2026-10-25 裁定：概率事件走「规格内固定 seed 的确定性伪随机逐次抽取」。
	// 因此种子必须住在**规格**里：
	//   - 同一份 spec 反序列化后必然得到同一条序列（不依赖进程、时间、调用顺序）；
	//   - 搜索侧所有计划共用同一个 seed，判决才可比；
	//   - 换 seed 只是换一条同样合法的时间线，不是"换胜率"。
	//
	// 规格没写（0）时按 `logosDefaultRNGSeed`（写死的 1）走——**不是**隐式随机。
	RNGSeed    uint64                     `json:"rng_seed,omitempty"`
	Evidence   map[string]json.RawMessage `json:"evidence"`
	Unresolved []string                   `json:"unresolved"`
}

func logosRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
	blob, err := os.ReadFile(filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel", table+".json"))
	if err != nil {
		return nil, err
	}
	var records map[string]json.RawMessage
	if err := json.Unmarshal(blob, &records); err != nil {
		return nil, fmt.Errorf("logos: unmarshal %s: %w", table, err)
	}
	out := make(map[string]json.RawMessage, len(ids))
	for _, id := range ids {
		raw, ok := records[id]
		if !ok {
			return nil, fmt.Errorf("logos: %s not in %s", id, table)
		}
		out[id] = raw
	}
	return out, nil
}

func logosSourceLevel(id string, level int, raw json.RawMessage, field string) (LogosSourceLevel, error) {
	var row struct {
		Levels []json.RawMessage `json:"levels"`
		Phases []json.RawMessage `json:"phases"`
	}
	if err := json.Unmarshal(raw, &row); err != nil {
		return LogosSourceLevel{}, err
	}
	var rows []json.RawMessage
	switch field {
	case "levels":
		rows = row.Levels
	case "phases":
		rows = row.Phases
	default:
		return LogosSourceLevel{}, fmt.Errorf("logos source: unsupported field %s", field)
	}
	if level <= 0 || level > len(rows) {
		return LogosSourceLevel{}, fmt.Errorf("logos source: %s %s level %d unavailable", id, field, level)
	}
	return LogosSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

// buildLogosSourceSpec 为逻各斯构建全量原始证据链。
func buildLogosSourceSpec(st *OperatorStats, slot, skillLevel int) (*LogosSourceSpec, error) {
	if st == nil || st.CharID != logosCharID {
		return nil, nil
	}
	// 计划里的槽号 `0` **不等于「不用技能」**：与 `skillbind.go` 同一口径，
	// 未指定时按技 1。这一条不统一，同一个干员在两处会绑到不同的技能上。
	if slot == 0 {
		slot = 1
	}
	if slot < 1 || slot > 3 {
		return nil, fmt.Errorf("logos spec: slot %d out of range [1,3]", slot)
	}
	if st.Elite < 0 || st.Elite > 2 || st.Level < 1 || st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("logos spec: invalid training E%d L%d P%d", st.Elite, st.Level, st.Potential)
	}
	if slot > st.Elite+1 {
		return nil, fmt.Errorf("logos spec: slot %d locked at elite %d", slot, st.Elite)
	}
	if skillLevel < 1 || skillLevel > 10 {
		return nil, fmt.Errorf("logos spec: skill level %d out of range [1,10]", skillLevel)
	}
	if skillLevel > 7 && st.Elite < 2 {
		return nil, fmt.Errorf("logos spec: skill mastery requires elite 2, got elite %d", st.Elite)
	}

	charRecords, err := logosRawRecords("character_table", logosCharID)
	if err != nil {
		return nil, err
	}
	charRaw := charRecords[logosCharID]

	var char struct {
		Skills  []json.RawMessage `json:"skills"`
		Talents []json.RawMessage `json:"talents"`
	}
	if err := json.Unmarshal(charRaw, &char); err != nil {
		return nil, fmt.Errorf("logos spec: unmarshal char: %w", err)
	}
	if slot > len(char.Skills) {
		return nil, fmt.Errorf("logos spec: slot %d > total %d", slot, len(char.Skills))
	}

	var slotData struct {
		SkillID string `json:"skillId"`
	}
	if err := json.Unmarshal(char.Skills[slot-1], &slotData); err != nil {
		return nil, fmt.Errorf("logos spec: slot %d skillId: %w", slot, err)
	}

	skillRecords, err := logosRawRecords("skill_table", slotData.SkillID)
	if err != nil {
		return nil, err
	}
	skillRaw := skillRecords[slotData.SkillID]
	skillLvl, err := logosSourceLevel(slotData.SkillID, skillLevel, skillRaw, "levels")
	if err != nil {
		return nil, err
	}

	out := &LogosSourceSpec{
		ConsumerImplemented: true,
		Elite:               st.Elite,
		Level:               st.Level,
		Potential:           st.Potential,
		Slot:                slot,
		SkillLevel:          skillLevel,
		OperatorSkill:       skillLvl,
		RawSlot:             char.Skills[slot-1],
		// 种子落在规格里，且**每次建规格都显式写死同一个默认值**：
		// 靠 `omitempty` 留空会让"没写"与"写了 0"两种输入在 JSON 上长得一样，
		// 而读规格的人无从判断这条时间线是用哪个 seed 采出来的。
		RNGSeed: logosDefaultRNGSeed,
		Evidence: map[string]json.RawMessage{
			"character_table": charRaw,
			"skill_table":     skillRaw,
		},
	}

	// 统一调用权威 resolveTalents
	for _, t := range resolveTalents(char.Talents, st.Elite, st.Level, st.Potential) {
		out.Talents = append(out.Talents, LogosTalentSource{
			Group:     t.GroupIndex,
			Candidate: t.CandidateIndex,
			Raw:       t.RawSource,
		})
	}

	// 模组提取（若装备了模组）
	modID := st.Module
	if modID != "" && st.ModuleLevel > 0 {
		modRecords, err := logosRawRecords("battle_equip_table", modID)
		if err != nil {
			return nil, err
		}
		out.Evidence["battle_equip_table"] = modRecords[modID]
		modLvl, err := logosSourceLevel(modID, st.ModuleLevel, modRecords[modID], "phases")
		if err != nil {
			return nil, err
		}
		out.Module = &modLvl

		var phase struct {
			Parts []struct {
				Target                  string `json:"target"`
				OverrideTraitDataBundle struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"overrideTraitDataBundle"`
				AddOrOverrideTalentDataBundle struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"addOrOverrideTalentDataBundle"`
			} `json:"parts"`
		}
		if err := json.Unmarshal(modLvl.Raw, &phase); err != nil {
			return nil, fmt.Errorf("logos spec: module phase unmarshal: %w", err)
		}
		for _, part := range phase.Parts {
			for _, cand := range part.OverrideTraitDataBundle.Candidates {
				var c moduleSpeedCandidate
				if err := json.Unmarshal(cand, &c); err == nil {
					if phaseOf(c.UnlockCondition.Phase) <= st.Elite && c.UnlockCondition.Level <= st.Level && c.RequiredPotentialRank <= st.Potential-1 {
						out.TraitOverride = cand
					}
				}
			}
			var best json.RawMessage
			rank := -1
			for _, cand := range part.AddOrOverrideTalentDataBundle.Candidates {
				var c moduleSpeedCandidate
				if err := json.Unmarshal(cand, &c); err != nil {
					continue
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

	// 语义待证项随证据一起走：`Unresolved` 的内容在配置层按技能槽产出
	// （不同槽的口径不一样），这里解一次搬进规格，免得证据链里留一个空栏。
	if cfg, err := decodeLogosRuntimeConfig(out); err == nil {
		out.Unresolved = cfg.Unresolved
	}

	return out, nil
}

// attachLogosSkillRange 把技能 `rangeId` 折成这次部署的**绝对格**。
//
// 为什么在建规格时算：`operator` 运行期只带绝对格（`spec.Range`），没有朝向。
// 运行期再按相对格旋转一次就是第二套旋转/平移口径——两套口径迟早对不上，
// 而对不上的症状是"范围里明明有人却打不到"，很难看出是范围算错了。
//
// 取不到 `rangeId`（技能二没有范围改写）就什么都不做。取到了但表里没有
// **大声失败**：静默跳过会让"范围扩大"悄悄失效。
func attachLogosSkillRange(spec *LogosSourceSpec, direction string, pos [2]int) error {
	if spec == nil {
		return nil
	}
	cfg, err := decodeLogosRuntimeConfig(spec)
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
		return fmt.Errorf("logos spec: skill range %s: %w", cfg.SkillRangeID, err)
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

// logosRemainingGapsFromSpec 收集并上报**没有运行期消费者**的机制。
//
// 与黍同一个纪律：豁免必须是「已消费」的断言，不是「这一支我写了个空 else」。
//
// ★ 第一天赋「语汇演化」**不在这里**了：博士 2026-10-25 裁定 V-2「概率机制的结果
// 语义」——「只要是能精准判定的都精准判定，很难做精准的才用期望值」。它的
// `prob` / `atk_scale` / `sluggish` / 模组 `emit_count` 现在都是**精确抽样**的
// 离散事件（`logosTalent1OnAttack`），因此不再有概率缺口。
// 原来那条 `logos.talent1.prob_v2`（"在等 V-2 裁定"）随裁定一起撤销。
//
// 仍然具名上报的是**另外三类**，它们都不是概率问题：
//
//   - 技能三的 `projectile_move_scale`（敌方子弹减速/清空）：本仓没有敌方弹道实体；
//   - 模组X 的 `element_atk_scale`：需要"目标处于凋亡损伤爆发期间"，而元素损伤
//     没有战斗调用点，这个条件判不出来；
//   - 两个模组的隐藏天赋：元素损伤未接线、敌人没有精英/领袖分类。
func logosRemainingGapsFromSpec(source *LogosSourceSpec, opName string, instance int) []mechanisms.Gap {
	if source == nil {
		return nil
	}
	cfg, err := decodeLogosRuntimeConfig(source)
	if err != nil {
		return []mechanisms.Gap{{
			ID: "logos.config.decode", CharID: logosCharID, Operator: opName,
			Source: "skill", Status: "incomplete", Instance: instance,
			Reason: fmt.Sprintf("逻各斯的配置解码失败：%v", err),
		}}
	}
	var gaps []mechanisms.Gap
	add := func(id, source, key, reason string) {
		gaps = append(gaps, mechanisms.Gap{
			ID: id, CharID: logosCharID, Operator: opName,
			Source: source, SourceID: source + ":logos", Key: key,
			Status: "unidentified", Instance: instance, Reason: reason,
		})
	}

	// 未消费的黑板键（配置层逐条记下来的）。
	for _, key := range cfg.UnusedKeys {
		add("logos.unknown_key."+key, "skill", key,
			"逻各斯的该黑板键没有运行期消费者；未消费即具名登记，不作静默忽略")
	}

	// 技能三：敌方子弹减速/清空没有落点。
	if cfg.Slot == 3 && cfg.S3ProjectileMoveScale > 0 {
		add("logos.skill3.projectile", "skill", "projectile_move_scale",
			"技能三「延异视阈」的「使范围内敌方子弹飞行速度大幅降低、技能结束时全部清除」未建模："+
				"本仓没有敌方弹道实体，该键没有落点")
	}

	// 第一天赋的**元素条件分支**（只有模组X 会给这个键）：
	// 概率那一半已精确建模，这一半缺的是"凋亡损伤爆发期间"这个状态。
	if cfg.Talent1ElementScale > 0 {
		add("logos.talent1.element_conditional", "talent", "element_atk_scale",
			"第一天赋（模组X 改写）的「若该随机目标处于凋亡损伤爆发期间则同时造成元素伤害」未建模："+
				"元素损伤状态机存在但没有战斗调用点，判不出「爆发期间」这个条件；概率那一半已按 seed 精确抽样")
	}

	// 模组隐藏天赋各自的落点缺口。
	if cfg.ModTraitEPDamageRatio > 0 {
		add("logos.module.trait_ep_damage", "module", "ep_damage_ratio",
			"模组「来自河谷的笔盒」的隐藏天赋「造成法术伤害时附带 N% 的凋亡损伤」未接线："+
				"元素损伤状态机（`element.go`）已存在但尚无战斗调用点，本档不冒充已消费")
	}
	if cfg.ModTraitSP != 0 {
		add("logos.module.trait_sp", "module", "sp",
			"模组「《语义范式百科》」的「普通攻击命中精英或领袖敌人时获得 N 点技力」未接线："+
				"敌人规格里没有精英/领袖分类字段，找不到判据")
	}
	return gaps
}
