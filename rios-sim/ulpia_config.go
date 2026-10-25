package main

import (
	"encoding/json"
	"fmt"
)

// UlpiaRuntimeConfig 把乌尔比安的全部黑板键解析为强类型字段。
// 遵循零硬编码原则，全部数值来自 gamedata 原文。
type UlpiaRuntimeConfig struct {
	// ---- 天赋一「本性的坚守」（E1 解锁） ----
	Talent1Enabled bool    `json:"talent1_enabled"`
	Talent1HPRatio float64 `json:"talent1_hp_ratio"` // 生命值百分比阈值，如 0.5 或 0.6(模组X3)
	Talent1Value1  float64 `json:"talent1_value1"`   // 受击治疗常态点数，如 80 / 100 / 120 / 130
	Talent1Value2  float64 `json:"talent1_value2"`   // 受击治疗低于阈值点数，如 120 / 160 / 170 / 175

	// ---- 天赋二「血脉的哺养」（E2 解锁） ----
	Talent2Enabled          bool    `json:"talent2_enabled"`
	Talent2MaxStackCnt      int     `json:"talent2_max_stack_cnt"`      // max_stack_cnt: 9 / 10(潜5)
	Talent2MaxHPPerStack    float64 `json:"talent2_max_hp_per_stack"`   // max_hp: 120 / 140 / 150
	Talent2AtkPerStack      float64 `json:"talent2_atk_per_stack"`      // atk: 30 / 35 / 38
	Talent2AbyssalMaxHP     float64 `json:"talent2_abyssal_max_hp"`     // ulpia_t_1[abyssal].max_hp: 60 / 77 / 90
	Talent2AbyssalAtk       float64 `json:"talent2_abyssal_atk"`        // ulpia_t_1[abyssal].atk: 15 / 19.25 / 22.8
	Talent2AbyssalMaxStack  int     `json:"talent2_abyssal_max_stack"`  // ulpia_t_1[abyssal].max_stack_cnt: 9 / 10
	Talent2ModAddBlockCnt   int     `json:"talent2_mod_add_block_cnt"`  // block_cnt: 1 (模组Y2/Y3)
	Talent2ModAddBlockStack int     `json:"talent2_mod_add_block_stack"`// add_block_cnt_stack_cnt: 9 (模组Y2/Y3)

	// ---- 模组特性覆写 ----
	ModTraitHealScale   float64 `json:"mod_trait_heal_scale"`   // 模组X: 受治疗效果提升 (1.2)
	ModTraitDamageScale float64 `json:"mod_trait_damage_scale"` // 模组Y: 对被阻挡敌人伤害提升 (1.1)

	// ---- 技能公共字段 ----
	Slot            int      `json:"slot"`
	SkillLevel      int      `json:"skill_level"`
	SPType          string   `json:"sp_type"`
	SPCost          int      `json:"sp_cost"`
	InitSP          int      `json:"init_sp"`
	Duration        float64  `json:"duration"`
	SkillRangeID    string   `json:"skill_range_id"`
	SkillRangeCells [][2]int `json:"skill_range_cells,omitempty"`

	// ---- 技能一「必须促成的接触」 ----
	S1AtkScale  float64 `json:"s1_atk_scale"`  // atk_scale: 2.7
	S1MaxTarget int     `json:"s1_max_target"` // max_target: 2
	S1Force     float64 `json:"s1_force"`      // force: 1.0 (位移拉拽，Gap)

	// ---- 技能二「必须维系的界限」 ----
	S2TalentScale float64 `json:"s2_talent_scale"` // talent_scale: 2.0 (第一天赋治疗效果提升至2.0倍)
	S2AtkRatio    float64 `json:"s2_atk_ratio"`    // atk: 1.6 (攻击力 +160%)
	S2MaxHPRatio  float64 `json:"s2_max_hp_ratio"` // max_hp: 0.6 (生命上限 +60%)
	S2BlockCnt    int     `json:"s2_block_cnt"`    // block_cnt: 1 (阻挡数 +1)

	// ---- 技能三「必须开辟的通路」 ----
	S3MaxHPRatio       float64 `json:"s3_max_hp_ratio"`       // max_hp: 0.8
	S3AtkRatio          float64 `json:"s3_atk_ratio"`          // atk: 2.6
	S3AtkScale         float64 `json:"s3_atk_scale"`          // atk_scale: 1.6
	S3StunDuration     float64 `json:"s3_stun_duration"`     // stun: 6.0
	S3ProjectileRange  float64 `json:"s3_projectile_range"`  // projectile_range: 1.8 (船锚位移与落点转移，Gap)

	// ---- 审计 ----
	ConsumedKeys []string `json:"consumed_keys"`
	UnusedKeys   []string `json:"unused_keys"`
	Unresolved   []string `json:"unresolved"`
}

func (c *UlpiaRuntimeConfig) consume(nums map[string]float64, strs map[string]string, keys ...string) map[string]bool {
	used := map[string]bool{}
	for _, k := range keys {
		if _, ok := nums[k]; ok {
			used[k] = true
			c.ConsumedKeys = append(c.ConsumedKeys, k)
		}
		if _, ok := strs[k]; ok {
			used[k] = true
			c.ConsumedKeys = append(c.ConsumedKeys, k)
		}
	}
	return used
}

func (c *UlpiaRuntimeConfig) auditBlackboard(nums map[string]float64, strs map[string]string, used map[string]bool) {
	for k := range nums {
		if !used[k] {
			c.UnusedKeys = append(c.UnusedKeys, k)
		}
	}
	for k := range strs {
		if !used[k] {
			c.UnusedKeys = append(c.UnusedKeys, k)
		}
	}
}

// decodeUlpiaRuntimeConfig 从 UlpiaSourceSpec 的 gamedata 原文中解析出强类型运行期配置
func decodeUlpiaRuntimeConfig(s *UlpiaSourceSpec) (*UlpiaRuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("ulpia config: source is nil")
	}
	cfg := &UlpiaRuntimeConfig{
		Slot:       s.Slot,
		SkillLevel: s.SkillLevel,
	}

	// 1. 解析天赋
	for _, t := range s.Talents {
		var cand struct {
			Name       string          `json:"name"`
			Blackboard json.RawMessage `json:"blackboard"`
		}
		if err := json.Unmarshal(t.Raw, &cand); err != nil {
			return nil, fmt.Errorf("ulpia config: unmarshal talent candidate: %w", err)
		}
		nums, strs, err := parseRawBlackboard(cand.Blackboard)
		if err != nil {
			return nil, fmt.Errorf("ulpia config: parse talent blackboard: %w", err)
		}
		switch t.Group {
		case 0: // 天赋一：本性的坚守
			cfg.Talent1Enabled = true
			used := cfg.consume(nums, strs, "hp_ratio", "value1", "value2")
			cfg.Talent1HPRatio = nums["hp_ratio"]
			cfg.Talent1Value1 = nums["value1"]
			cfg.Talent1Value2 = nums["value2"]
			cfg.auditBlackboard(nums, strs, used)

		case 1: // 天赋二：血脉的哺养
			cfg.Talent2Enabled = true
			used := cfg.consume(nums, strs,
				"max_stack_cnt", "max_hp", "atk",
				"ulpia_t_1[abyssal].max_hp",
				"ulpia_t_1[abyssal].atk",
				"ulpia_t_1[abyssal].max_stack_cnt",
			)
			cfg.Talent2MaxStackCnt = int(nums["max_stack_cnt"])
			cfg.Talent2MaxHPPerStack = nums["max_hp"]
			cfg.Talent2AtkPerStack = nums["atk"]
			cfg.Talent2AbyssalMaxHP = nums["ulpia_t_1[abyssal].max_hp"]
			cfg.Talent2AbyssalAtk = nums["ulpia_t_1[abyssal].atk"]
			cfg.Talent2AbyssalMaxStack = int(nums["ulpia_t_1[abyssal].max_stack_cnt"])
			cfg.auditBlackboard(nums, strs, used)

		case 2: // 天赋三：空黑板
			cfg.auditBlackboard(nums, strs, nil)
		}
	}

	// 2. 模组升级改写天赋与特性
	if len(s.TraitOverride) > 0 {
		var to struct {
			Blackboard json.RawMessage `json:"blackboard"`
		}
		if err := json.Unmarshal(s.TraitOverride, &to); err == nil && len(to.Blackboard) > 0 {
			nums, strs, err := parseRawBlackboard(to.Blackboard)
			if err == nil {
				used := cfg.consume(nums, strs, "heal_scale", "damage_scale")
				if v, ok := nums["heal_scale"]; ok {
					cfg.ModTraitHealScale = v
				}
				if v, ok := nums["damage_scale"]; ok {
					cfg.ModTraitDamageScale = v
				}
				cfg.auditBlackboard(nums, strs, used)
			}
		}
	}

	for _, candRaw := range s.ModuleCandidates {
		var cand struct {
			TalentIndex int             `json:"talentIndex"`
			Name        string          `json:"name"`
			Blackboard  json.RawMessage `json:"blackboard"`
		}
		if err := json.Unmarshal(candRaw, &cand); err != nil {
			continue
		}
		if len(cand.Blackboard) == 0 {
			continue
		}
		nums, strs, err := parseRawBlackboard(cand.Blackboard)
		if err != nil {
			continue
		}
		switch cand.TalentIndex {
		case 0: // 模组X 改写天赋一
			used := cfg.consume(nums, strs, "hp_ratio", "value1", "value2")
			if v, ok := nums["hp_ratio"]; ok {
				cfg.Talent1HPRatio = v
			}
			if v, ok := nums["value1"]; ok {
				cfg.Talent1Value1 = v
			}
			if v, ok := nums["value2"]; ok {
				cfg.Talent1Value2 = v
			}
			cfg.auditBlackboard(nums, strs, used)

		case 1: // 模组Y 改写天赋二
			used := cfg.consume(nums, strs,
				"max_stack_cnt", "max_hp", "atk",
				"ulpia_t_1[abyssal].max_hp",
				"ulpia_t_1[abyssal].atk",
				"ulpia_t_1[abyssal].max_stack_cnt",
				"block_cnt", "add_block_cnt_stack_cnt",
			)
			if v, ok := nums["max_stack_cnt"]; ok {
				cfg.Talent2MaxStackCnt = int(v)
			}
			if v, ok := nums["max_hp"]; ok {
				cfg.Talent2MaxHPPerStack = v
			}
			if v, ok := nums["atk"]; ok {
				cfg.Talent2AtkPerStack = v
			}
			if v, ok := nums["ulpia_t_1[abyssal].max_hp"]; ok {
				cfg.Talent2AbyssalMaxHP = v
			}
			if v, ok := nums["ulpia_t_1[abyssal].atk"]; ok {
				cfg.Talent2AbyssalAtk = v
			}
			if v, ok := nums["ulpia_t_1[abyssal].max_stack_cnt"]; ok {
				cfg.Talent2AbyssalMaxStack = int(v)
			}
			if v, ok := nums["block_cnt"]; ok {
				cfg.Talent2ModAddBlockCnt = int(v)
			}
			if v, ok := nums["add_block_cnt_stack_cnt"]; ok {
				cfg.Talent2ModAddBlockStack = int(v)
			}
			cfg.auditBlackboard(nums, strs, used)
		}
	}

	// 3. 解析技能
	var skillLevel struct {
		Name         string          `json:"name"`
		RangeID      string          `json:"rangeId"`
		Duration     float64         `json:"duration"`
		DurationType any             `json:"durationType"`
		Blackboard   json.RawMessage `json:"blackboard"`
		SPData       struct {
			SPType string `json:"spType"`
			SPCost int    `json:"spCost"`
			InitSP int    `json:"initSp"`
		} `json:"spData"`
	}
	if err := json.Unmarshal(s.OperatorSkill.Raw, &skillLevel); err != nil {
		return nil, fmt.Errorf("ulpia config: unmarshal skill: %w", err)
	}

	cfg.SPType = skillLevel.SPData.SPType
	cfg.SPCost = skillLevel.SPData.SPCost
	cfg.InitSP = skillLevel.SPData.InitSP
	cfg.Duration = skillLevel.Duration
	cfg.SkillRangeID = skillLevel.RangeID

	// 技能范围解析
	if cfg.SkillRangeID != "" {
		ranges, err := ulpiaRawRecords("range_table", cfg.SkillRangeID)
		if err != nil {
			return nil, fmt.Errorf("ulpia config: range %s: %w", cfg.SkillRangeID, err)
		}
		var r struct {
			Grids []struct {
				Row int `json:"row"`
				Col int `json:"col"`
			} `json:"grids"`
		}
		if err := json.Unmarshal(ranges[cfg.SkillRangeID], &r); err != nil {
			return nil, fmt.Errorf("ulpia config: range %s: %w", cfg.SkillRangeID, err)
		}
		cfg.SkillRangeCells = make([][2]int, 0, len(r.Grids))
		for _, g := range r.Grids {
			cfg.SkillRangeCells = append(cfg.SkillRangeCells, [2]int{g.Col, g.Row})
		}
	}

	nums, strs, err := parseRawBlackboard(skillLevel.Blackboard)
	if err != nil {
		return nil, fmt.Errorf("ulpia config: parse skill blackboard: %w", err)
	}

	switch s.Slot {
	case 1: // skchr_ulpia_1: 必须促成的接触
		used := cfg.consume(nums, strs, "atk_scale", "max_target", "force")
		cfg.S1AtkScale = nums["atk_scale"]
		cfg.S1MaxTarget = int(nums["max_target"])
		cfg.S1Force = nums["force"]
		cfg.auditBlackboard(nums, strs, used)

	case 2: // skchr_ulpia_2: 必须维系的界限
		used := cfg.consume(nums, strs, "talent_scale", "atk", "max_hp", "block_cnt")
		cfg.S2TalentScale = nums["talent_scale"]
		cfg.S2AtkRatio = nums["atk"]
		cfg.S2MaxHPRatio = nums["max_hp"]
		cfg.S2BlockCnt = int(nums["block_cnt"])
		cfg.auditBlackboard(nums, strs, used)

	case 3: // skchr_ulpia_3: 必须开辟的通路
		used := cfg.consume(nums, strs, "max_hp", "atk", "atk_scale", "stun", "projectile_range")
		cfg.S3MaxHPRatio = nums["max_hp"]
		cfg.S3AtkRatio = nums["atk"]
		cfg.S3AtkScale = nums["atk_scale"]
		cfg.S3StunDuration = nums["stun"]
		cfg.S3ProjectileRange = nums["projectile_range"]
		cfg.auditBlackboard(nums, strs, used)

	default:
		return nil, fmt.Errorf("ulpia config: unsupported slot %d", s.Slot)
	}

	return cfg, nil
}
