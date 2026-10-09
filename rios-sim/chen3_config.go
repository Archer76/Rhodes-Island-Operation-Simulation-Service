package main

import (
	"encoding/json"
	"fmt"
)

type chen3RuntimeConfig struct {
	Slot       int
	SkillLevel int

	// Skill 1
	S1AtkScale float64 // atk buff (e.g. 1.2 at M3)

	// Skill 2
	S2AtkScale       float64 // atk_scale per strike (e.g. 4.8 at M3)
	S2Strikes        int     // 10
	S2Duration       float64 // 6.0
	S2RespawnAtk     float64 // chen3_s2[respawn_buff].atk (e.g. 3.0 at M3)
	S2RespawnProb    float64 // chen3_s2[respawn_buff].prob (e.g. 0.6 at M3)

	// Skill 3
	S3Duration             float64 // 20.0
	S3AtkScale             float64 // attack@atk_scale (e.g. 2.1 at M3)
	S3MaxTarget            int     // attack@max_target (e.g. 4 at M3)
	S3HPRatio              float64 // hp_ratio (0.06)
	S3ProjectileMinAtkScale float64 // projectile_min_atk_scale (e.g. 5.8 at M3)
	S3QiSpeed              float64 // 1.2 grids/s

	// Talent 1 (形意洞照)
	Talent1Atk  float64 // atk%
	Talent1ASPD float64 // attack_speed
	Talent1Weak bool    // 弱点伤害

	// Talent 2 (寒暑觉知)
	Talent2Interval   float64 // stack_time (7.0 or 6.0 with module)
	Talent2HealMinAtk float64 // heal_atk_scale_min (30.0 ~ 55.0)
	Talent2HealMaxAtk float64 // heal_atk_scale_max (160.0 ~ 205.0)

	// Module Trait (未阻挡攻速)
	ModuleUnblockedASPD float64 // 8.0
}

func chen3StrictBB(raw json.RawMessage) (map[string]float64, error) {
	var row struct {
		Blackboard []struct {
			Key      string   `json:"key"`
			Value    *float64 `json:"value"`
			ValueStr *string  `json:"valueStr"`
		} `json:"blackboard"`
	}
	if err := json.Unmarshal(raw, &row); err != nil {
		return nil, err
	}
	out := make(map[string]float64, len(row.Blackboard))
	for _, r := range row.Blackboard {
		if r.Key == "" || r.Value == nil {
			return nil, fmt.Errorf("invalid chen3 blackboard entry")
		}
		if _, ok := out[r.Key]; ok {
			return nil, fmt.Errorf("duplicate chen3 key %s", r.Key)
		}
		out[r.Key] = *r.Value
	}
	return out, nil
}

func decodeChen3RuntimeConfig(s *Chen3SourceSpec) (chen3RuntimeConfig, error) {
	if s == nil || s.Slot < 1 || s.Slot > 3 {
		return chen3RuntimeConfig{}, fmt.Errorf("invalid chen3 source spec")
	}
	cfg := chen3RuntimeConfig{
		Slot:       s.Slot,
		SkillLevel: s.SkillLevel,
		S3QiSpeed:  1.2,
		S2Strikes:  10,
	}

	// 解析技能
	bb, err := chen3StrictBB(s.OperatorSkill.Raw)
	if err != nil {
		return cfg, err
	}

	switch s.Slot {
	case 1:
		val, ok := bb["atk"]
		if !ok {
			return cfg, fmt.Errorf("missing atk in chen3 s1")
		}
		cfg.S1AtkScale = val
	case 2:
		atkScale, ok := bb["atk_scale"]
		if !ok {
			return cfg, fmt.Errorf("missing atk_scale in chen3 s2")
		}
		respawnAtk, ok := bb["chen3_s2[respawn_buff].atk"]
		if !ok {
			return cfg, fmt.Errorf("missing chen3_s2[respawn_buff].atk in chen3 s2")
		}
		respawnProb, ok := bb["chen3_s2[respawn_buff].prob"]
		if !ok {
			return cfg, fmt.Errorf("missing chen3_s2[respawn_buff].prob in chen3 s2")
		}
		cfg.S2AtkScale = atkScale
		cfg.S2RespawnAtk = respawnAtk
		cfg.S2RespawnProb = respawnProb
		cfg.S2Duration = 6.0
	case 3:
		atkScale, ok := bb["attack@atk_scale"]
		if !ok {
			return cfg, fmt.Errorf("missing attack@atk_scale in chen3 s3")
		}
		maxTarget, ok := bb["attack@max_target"]
		if !ok {
			return cfg, fmt.Errorf("missing attack@max_target in chen3 s3")
		}
		hpRatio, ok := bb["hp_ratio"]
		if !ok {
			return cfg, fmt.Errorf("missing hp_ratio in chen3 s3")
		}
		minAtkScale, ok := bb["projectile_min_atk_scale"]
		if !ok {
			return cfg, fmt.Errorf("missing projectile_min_atk_scale in chen3 s3")
		}
		cfg.S3AtkScale = atkScale
		cfg.S3MaxTarget = int(maxTarget)
		cfg.S3HPRatio = hpRatio
		cfg.S3ProjectileMinAtkScale = minAtkScale
		cfg.S3Duration = 20.0
	}

	// 解析天赋
	for _, t := range s.Talents {
		tbb, err := chen3StrictBB(t.Raw)
		if err != nil {
			return cfg, err
		}
		if t.Group == 0 {
			// 第一天赋 形意洞照
			if v, ok := tbb["atk"]; ok {
				cfg.Talent1Atk = v
			}
			if v, ok := tbb["attack_speed"]; ok {
				cfg.Talent1ASPD = v
			}
			cfg.Talent1Weak = true
		} else if t.Group == 1 {
			// 第二天赋 寒暑觉知
			if v, ok := tbb["stack_time"]; ok {
				cfg.Talent2Interval = v
			}
			if v, ok := tbb["heal_atk_scale_min"]; ok {
				cfg.Talent2HealMinAtk = v
			}
			if v, ok := tbb["heal_atk_scale_max"]; ok {
				// excel 中可能是 161.0 表示 160% 或是上限
				cfg.Talent2HealMaxAtk = v
			}
		}
	}

	// 模组覆写解析
	if s.Module != nil {
		var phase struct {
			Parts []struct {
				Target string `json:"target"`
				OverrideTraitDataBundle struct {
					Candidates []struct {
						Blackboard []struct {
							Key   string   `json:"key"`
							Value *float64 `json:"value"`
						} `json:"blackboard"`
					} `json:"candidates"`
				} `json:"overrideTraitDataBundle"`
				AddOrOverrideTalentDataBundle struct {
					Candidates []struct {
						Blackboard []struct {
							Key   string   `json:"key"`
							Value *float64 `json:"value"`
						} `json:"blackboard"`
					} `json:"candidates"`
				} `json:"addOrOverrideTalentDataBundle"`
			} `json:"parts"`
		}
		if err := json.Unmarshal(s.Module.Raw, &phase); err == nil {
			for _, part := range phase.Parts {
				if part.Target == "TRAIT" {
					for _, c := range part.OverrideTraitDataBundle.Candidates {
						for _, b := range c.Blackboard {
							if b.Key == "attack_speed" && b.Value != nil {
								cfg.ModuleUnblockedASPD = *b.Value
							}
						}
					}
				} else if part.Target == "TALENT_DATA_ONLY" {
					// 挑选符合当前潜能的 candidate
					pRank := s.Potential - 1
					candIdx := 0
					if pRank >= 2 && len(part.AddOrOverrideTalentDataBundle.Candidates) > 1 {
						candIdx = 1
					}
					if candIdx < len(part.AddOrOverrideTalentDataBundle.Candidates) {
						c := part.AddOrOverrideTalentDataBundle.Candidates[candIdx]
						for _, b := range c.Blackboard {
							if b.Value != nil {
								switch b.Key {
								case "stack_time":
									cfg.Talent2Interval = *b.Value
								case "heal_atk_scale_min":
									cfg.Talent2HealMinAtk = *b.Value
								case "heal_atk_scale_max":
									cfg.Talent2HealMaxAtk = *b.Value
								}
							}
						}
					}
				}
			}
		}
	}

	return cfg, nil
}
