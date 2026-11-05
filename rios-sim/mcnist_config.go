package main

import (
	"encoding/json"
	"fmt"
)

// McnistRuntimeConfig 将机械师全量黑板键解析为强类型字段
type McnistRuntimeConfig struct {
	Elite      int `json:"elite"`
	Level      int `json:"level"`
	Potential  int `json:"potential"`
	Slot       int `json:"slot"`
	SkillLevel int `json:"skill_level"`

	// 第一天赋【结构性原理】
	TokenDuration float64 `json:"token_duration"` // 20s (E1) / 30s (E2)

	// 第二天赋【生命方程】
	LifeEquationHPRatio float64 `json:"life_equation_hp_ratio"` // 0.3 / 0.4 (Pot5)

	// 技能一【聚类分析】
	S1AtkScale        float64 `json:"s1_atk_scale"`        // attack@atk_scale (0.8~1.55)
	S1Times           int     `json:"s1_times"`            // attack@times (5)
	S1Interval        float64 `json:"s1_interval"`         // attack@interval (0.2)
	S1TriggerTime     int     `json:"s1_trigger_time"`     // attack@trigger_time (3)
	S1BaseAttackTime  float64 `json:"s1_base_attack_time"` // base_attack_time (1.3)
	S1ProjectileDelay float64 `json:"s1_projectile_delay"` // attack@projectile_delay_time (1.3)
	S1ProjectileRange float64 `json:"s1_projectile_range"` // attack@projectile_range (1.1)

	// 技能二【协防术式】
	S2Atk         float64 `json:"s2_atk"`          // atk (+0.6~+1.5)
	S2HPRatio     float64 `json:"s2_hp_ratio"`     // hp_ratio (0.1)
	S2TriggerTime int     `json:"s2_trigger_time"` // trigger_time (5~8)
	S2AtkScale    float64 `json:"s2_atk_scale"`    // atk_scale (2.0)
	S2RangeRadius float64 `json:"s2_range_radius"` // range_radius (1.5)
	S2TrembleSec  float64 `json:"s2_tremble_sec"`  // not_combat (2.0~3.0)

	// 技能三【工程学十字星】
	S3Atk             float64  `json:"s3_atk"`               // atk (+1.0~+2.8)
	S3BaseAttackTime  float64  `json:"s3_base_attack_time"`  // base_attack_time (2.3)
	S3CrossAtkScale   float64  `json:"s3_cross_atk_scale"`   // attack@atk_scale (2.0~2.6)
	S3DashAtkScale    float64  `json:"s3_dash_atk_scale"`    // atk_scale (3.0)
	S3ProjectileRange float64  `json:"s3_projectile_range"`  // projectile_range (1.5)
	S3AttackProjRange float64  `json:"s3_attack_proj_range"` // attack@projectile_range (0.0)
	S3CrossRangeCells [][2]int `json:"s3_cross_range_cells"` // x-6 十字 9 格

	// 模组面板加成
	ModuleAtk float64 `json:"module_atk"`
	ModuleDef float64 `json:"module_def"`

	// 审计追踪
	UnusedKeys []string `json:"unused_keys,omitempty"`
}

type mcnistBBItem struct {
	Key      string   `json:"key"`
	Value    *float64 `json:"value"`
	ValueStr *string  `json:"valueStr"`
}

func parseMcnistBB(raw json.RawMessage) (map[string]float64, map[string]string) {
	nums := make(map[string]float64)
	strs := make(map[string]string)
	if len(raw) == 0 {
		return nums, strs
	}
	var node struct {
		Blackboard []mcnistBBItem `json:"blackboard"`
	}
	if err := json.Unmarshal(raw, &node); err == nil && len(node.Blackboard) > 0 {
		for _, it := range node.Blackboard {
			if it.Value != nil {
				nums[it.Key] = *it.Value
			}
			if it.ValueStr != nil {
				strs[it.Key] = *it.ValueStr
			}
		}
		return nums, strs
	}
	var list []mcnistBBItem
	if err := json.Unmarshal(raw, &list); err == nil {
		for _, it := range list {
			if it.Value != nil {
				nums[it.Key] = *it.Value
			}
			if it.ValueStr != nil {
				strs[it.Key] = *it.ValueStr
			}
		}
	}
	return nums, strs
}

func (c *McnistRuntimeConfig) consume(nums map[string]float64, strs map[string]string, keys ...string) map[string]bool {
	used := make(map[string]bool, len(keys))
	for _, k := range keys {
		if _, ok := nums[k]; ok {
			used[k] = true
		}
		if _, ok := strs[k]; ok {
			used[k] = true
		}
	}
	return used
}

func (c *McnistRuntimeConfig) auditBlackboard(nums map[string]float64, strs map[string]string, used map[string]bool) {
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

// decodeMcnistRuntimeConfig 从 McnistSourceSpec 的 gamedata 原文解析强类型配置
func decodeMcnistRuntimeConfig(s *McnistSourceSpec) (*McnistRuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("decodeMcnistRuntimeConfig: spec is nil")
	}

	cfg := &McnistRuntimeConfig{
		Elite:      s.Elite,
		Level:      s.Level,
		Potential:  s.Potential,
		Slot:       s.Slot,
		SkillLevel: s.SkillLevel,
		S3CrossRangeCells: [][2]int{
			{-2, 0}, {-1, 0}, {0, -2}, {0, -1}, {0, 0}, {0, 1}, {0, 2}, {1, 0}, {2, 0},
		},
	}

	// 1. 第一天赋【结构性原理】默认持续时间
	if s.Elite >= 2 {
		cfg.TokenDuration = 30.0
	} else if s.Elite >= 1 {
		cfg.TokenDuration = 20.0
	}

	// 检查召唤物原始天赋表中的 skill@duration
	if rawTokChar, ok := s.Evidence["token_character"]; ok {
		var tokNode struct {
			Talents []struct {
				Candidates []struct {
					Blackboard []mcnistBBItem `json:"blackboard"`
					UnlockCond struct {
						Phase string `json:"phase"`
					} `json:"unlockCondition"`
				} `json:"candidates"`
			} `json:"talents"`
		}
		if err := json.Unmarshal(rawTokChar, &tokNode); err == nil {
			for _, t := range tokNode.Talents {
				for _, cand := range t.Candidates {
					phaseNum := 0
					switch cand.UnlockCond.Phase {
					case "PHASE_1":
						phaseNum = 1
					case "PHASE_2":
						phaseNum = 2
					}
					if s.Elite >= phaseNum {
						for _, b := range cand.Blackboard {
							if b.Key == "skill@duration" && b.Value != nil {
								cfg.TokenDuration = *b.Value
							}
						}
					}
				}
			}
		}
	}

	// 2. 第二天赋【生命方程】
	if s.Elite >= 2 {
		if s.Potential >= 5 {
			cfg.LifeEquationHPRatio = 0.4
		} else {
			cfg.LifeEquationHPRatio = 0.3
		}
	}
	for _, t := range s.Talents {
		nums, strs := parseMcnistBB(t.Raw)
		if v, ok := nums["hp_ratio"]; ok {
			cfg.LifeEquationHPRatio = v
			used := cfg.consume(nums, strs, "hp_ratio")
			cfg.auditBlackboard(nums, strs, used)
		}
	}

	// 3. 技能黑板解析
	nums, strs := parseMcnistBB(s.OperatorSkill.Raw)
	switch s.Slot {
	case 1:
		cfg.S1AtkScale = nums["attack@atk_scale"]
		cfg.S1Times = int(nums["attack@times"])
		cfg.S1Interval = nums["attack@interval"]
		cfg.S1TriggerTime = int(nums["attack@trigger_time"])
		cfg.S1BaseAttackTime = nums["base_attack_time"]
		cfg.S1ProjectileDelay = nums["attack@projectile_delay_time"]
		cfg.S1ProjectileRange = nums["attack@projectile_range"]
		used := cfg.consume(nums, strs,
			"attack@atk_scale", "attack@times", "attack@interval",
			"attack@trigger_time", "base_attack_time",
			"attack@projectile_delay_time", "attack@projectile_range",
		)
		cfg.auditBlackboard(nums, strs, used)

	case 2:
		cfg.S2Atk = nums["atk"]
		cfg.S2HPRatio = nums["hp_ratio"]
		cfg.S2TriggerTime = int(nums["trigger_time"])
		cfg.S2AtkScale = nums["atk_scale"]
		cfg.S2RangeRadius = nums["range_radius"]
		cfg.S2TrembleSec = nums["not_combat"]
		used := cfg.consume(nums, strs,
			"atk", "hp_ratio", "trigger_time",
			"atk_scale", "range_radius", "not_combat",
		)
		cfg.auditBlackboard(nums, strs, used)

	case 3:
		cfg.S3Atk = nums["atk"]
		cfg.S3BaseAttackTime = nums["base_attack_time"]
		cfg.S3CrossAtkScale = nums["attack@atk_scale"]
		cfg.S3DashAtkScale = nums["atk_scale"]
		cfg.S3ProjectileRange = nums["projectile_range"]
		cfg.S3AttackProjRange = nums["attack@projectile_range"]
		used := cfg.consume(nums, strs,
			"atk", "base_attack_time", "attack@atk_scale",
			"atk_scale", "projectile_range", "attack@projectile_range",
		)
		cfg.auditBlackboard(nums, strs, used)
	}

	// 4. 模组面板解析
	if s.Module != nil {
		var modPhase struct {
			AttributeBlackboard []mcnistBBItem `json:"attributeBlackboard"`
		}
		if err := json.Unmarshal(s.Module.Raw, &modPhase); err == nil && len(modPhase.AttributeBlackboard) > 0 {
			for _, b := range modPhase.AttributeBlackboard {
				if b.Key == "atk" && b.Value != nil {
					cfg.ModuleAtk = *b.Value
				}
				if b.Key == "def" && b.Value != nil {
					cfg.ModuleDef = *b.Value
				}
			}
		}
	}

	return cfg, nil
}
