package main

import (
	"encoding/json"
	"fmt"
)

// DminonRuntimeConfig 将国度的所有机制黑板键映射为强类型配置。
// 数值全部提取自 spec 中的原始 RawMessage，严禁手写硬编码。
type DminonRuntimeConfig struct {
	// 第一天赋【实质坍缩】
	T1AttackSpeed float64 `json:"t1_attack_speed"` // 地面敌人攻速减值（负数，如 -15.0）
	T1AtkScale    float64 `json:"t1_atk_scale"`    // 每秒法术伤害比例（如 0.13）
	T1Interval    float64 `json:"t1_interval"`     // DoT 触发间隔，固定 1.0s

	// 第二天赋【此身为界】
	T2Unlocked bool    `json:"t2_unlocked"`
	T2AtkScale float64 `json:"t2_atk_scale"` // 退场法术伤害倍率（5.0，潜5为 6.0）
	T2Stun     float64 `json:"t2_stun"`      // 眩晕时间（5.0s）

	// 模组 AMB-X 特性改写
	TraitMoveSpeed float64 `json:"trait_move_speed"` // 攻击范围内敌人移速 -20%（-0.2）
	TraitDodgeProb float64 `json:"trait_dodge_prob"` // 伏击客基础 50% 物理与法术闪避

	// 技能槽与通用属性
	Slot            int      `json:"slot"`
	SkillLevel      int      `json:"skill_level"`
	SPType          string   `json:"sp_type"`
	SPCost          int      `json:"sp_cost"`
	InitSP          int      `json:"init_sp"`
	MaxCharge       int      `json:"max_charge"`
	Duration        float64  `json:"duration"`
	SkillRangeID    string   `json:"skill_range_id"`
	SkillRangeCells [][2]int `json:"skill_range_cells,omitempty"`

	// 技能一【停步】
	S1AttackSpeed float64 `json:"s1_attack_speed"` // 攻速加成
	S1Sluggish    float64 `json:"s1_sluggish"`     // 踏入停顿时间

	// 技能二【受戮】
	S2Atk         float64 `json:"s2_atk"`          // 攻击力提升比例
	S2AttackSpeed float64 `json:"s2_attack_speed"` // 第二次及以后使用攻速加成

	// 技能三【无人之国度】
	S3Atk         float64 `json:"s3_atk"`           // 攻击力提升比例
	S3AttackSpeed float64 `json:"s3_attack_speed"`  // 攻击速度加成
	S3AoeAtkScale float64 `json:"s3_aoe_atk_scale"` // 受击反击物理伤害倍率
	S3CounterCD   float64 `json:"s3_counter_cd"`    // 反击冷却时间 (0.5s)

	// 确定性随机数 Seed
	RNGSeed uint64 `json:"rng_seed"`

	// 键审计
	ConsumedKeys []string `json:"consumed_keys"`
	UnusedKeys   []string `json:"unused_keys"`
	Unresolved   []string `json:"unresolved"`
}

func decodeDminonRuntimeConfig(s *DminonSourceSpec) (*DminonRuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("dminon config: source spec is nil")
	}

	cfg := &DminonRuntimeConfig{
		Slot:           s.Slot,
		SkillLevel:     s.SkillLevel,
		T1Interval:     1.0,
		TraitDodgeProb: 0.50, // 伏击客基础特性 50% 双闪
		RNGSeed:        s.RNGSeed,
		ConsumedKeys:   make([]string, 0),
		UnusedKeys:     make([]string, 0),
	}
	if cfg.RNGSeed == 0 {
		cfg.RNGSeed = defaultProbRNGSeed
	}

	consumed := make(map[string]bool)

	// 1. 解析第一天赋【实质坍缩】 (Group 0)
	for _, t := range s.Talents {
		if t.Group == 0 {
			var cand struct {
				Blackboard json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(t.Raw, &cand); err == nil {
				nums, _, _ := parseRawBlackboard(cand.Blackboard)
				for k, v := range nums {
					switch k {
					case "attack_speed":
						cfg.T1AttackSpeed = v
						consumed["talent.0.attack_speed"] = true
					case "atk_scale":
						cfg.T1AtkScale = v
						consumed["talent.0.atk_scale"] = true
					}
				}
			}
		} else if t.Group == 1 {
			// 2. 解析第二天赋【此身为界】 (Group 1)
			cfg.T2Unlocked = true
			var cand struct {
				Blackboard json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(t.Raw, &cand); err == nil {
				nums, _, _ := parseRawBlackboard(cand.Blackboard)
				for k, v := range nums {
					switch k {
					case "atk_scale":
						cfg.T2AtkScale = v
						consumed["talent.1.atk_scale"] = true
					case "stun":
						cfg.T2Stun = v
						consumed["talent.1.stun"] = true
					}
				}
			}
		}
	}

	// 3. 模组升级覆盖 (AMB-X)
	if s.Module != nil {
		for i, candRaw := range s.ModuleCandidates {
			var modCand struct {
				TalentIndex int             `json:"talentIndex"`
				Blackboard  json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(candRaw, &modCand); err == nil {
				nums, _, _ := parseRawBlackboard(modCand.Blackboard)
				if modCand.TalentIndex == -1 {
					if ms, ok := nums["move_speed"]; ok {
						cfg.TraitMoveSpeed = ms
						consumed[fmt.Sprintf("module.cand.%d.move_speed", i)] = true
					}
				} else if modCand.TalentIndex == 0 {
					for k, v := range nums {
						switch k {
						case "attack_speed":
							cfg.T1AttackSpeed = v
							consumed[fmt.Sprintf("module.cand.%d.attack_speed", i)] = true
						case "atk_scale":
							cfg.T1AtkScale = v
							consumed[fmt.Sprintf("module.cand.%d.atk_scale", i)] = true
						}
					}
				}
			}
		}

		if len(s.TraitOverride) > 0 {
			var to struct {
				Blackboard json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(s.TraitOverride, &to); err == nil {
				nums, _, _ := parseRawBlackboard(to.Blackboard)
				for k, v := range nums {
					if k == "move_speed" {
						cfg.TraitMoveSpeed = v
						consumed["module.trait.move_speed"] = true
					}
				}
			}
		}
	}

	// 4. 解析技能数据
	if len(s.OperatorSkill.Raw) > 0 {
		var skLevel struct {
			SkillType  string          `json:"skillType"`
			SpData     json.RawMessage `json:"spData"`
			Duration   float64         `json:"duration"`
			Blackboard json.RawMessage `json:"blackboard"`
			RangeID    *string         `json:"rangeId"`
		}
		if err := json.Unmarshal(s.OperatorSkill.Raw, &skLevel); err != nil {
			return nil, fmt.Errorf("dminon config: failed to unmarshal skill raw: %w", err)
		}
		cfg.Duration = skLevel.Duration
		if skLevel.RangeID != nil {
			cfg.SkillRangeID = *skLevel.RangeID
		}

		var sp struct {
			SpType    string `json:"spType"`
			SpCost    int    `json:"spCost"`
			InitSp    int    `json:"initSp"`
			MaxCharge int    `json:"maxChargeTime"`
		}
		if err := json.Unmarshal(skLevel.SpData, &sp); err == nil {
			cfg.SPType = sp.SpType
			cfg.SPCost = sp.SpCost
			cfg.InitSP = sp.InitSp
			cfg.MaxCharge = sp.MaxCharge
			if cfg.MaxCharge <= 0 {
				cfg.MaxCharge = 1
			}
		}

		nums, _, _ := parseRawBlackboard(skLevel.Blackboard)
		switch cfg.Slot {
		case 1:
			for k, v := range nums {
				switch k {
				case "attack_speed":
					cfg.S1AttackSpeed = v
					consumed["skill.1.attack_speed"] = true
				case "sluggish":
					cfg.S1Sluggish = v
					consumed["skill.1.sluggish"] = true
				default:
					cfg.UnusedKeys = append(cfg.UnusedKeys, "skill.1."+k)
				}
			}
		case 2:
			for k, v := range nums {
				switch k {
				case "atk":
					cfg.S2Atk = v
					consumed["skill.2.atk"] = true
				case "attack_speed":
					cfg.S2AttackSpeed = v
					consumed["skill.2.attack_speed"] = true
				default:
					cfg.UnusedKeys = append(cfg.UnusedKeys, "skill.2."+k)
				}
			}
		case 3:
			for k, v := range nums {
				switch k {
				case "atk":
					cfg.S3Atk = v
					consumed["skill.3.atk"] = true
				case "attack_speed":
					cfg.S3AttackSpeed = v
					consumed["skill.3.attack_speed"] = true
				case "attack@aoe_atk_scale":
					cfg.S3AoeAtkScale = v
					consumed["skill.3.attack@aoe_atk_scale"] = true
				case "attack@cd":
					cfg.S3CounterCD = v
					consumed["skill.3.attack@cd"] = true
				default:
					cfg.UnusedKeys = append(cfg.UnusedKeys, "skill.3."+k)
				}
			}
		}
	}

	// 5. 若有技能范围改写，提取 range_table 相对格
	if cfg.SkillRangeID != "" {
		ranges, err := dminonRawRecords("range_table", cfg.SkillRangeID)
		if err == nil && len(ranges[cfg.SkillRangeID]) > 0 {
			var rf struct {
				Grids []struct {
					Row int `json:"row"`
					Col int `json:"col"`
				} `json:"grids"`
			}
			if err := json.Unmarshal(ranges[cfg.SkillRangeID], &rf); err == nil {
				cfg.SkillRangeCells = make([][2]int, 0, len(rf.Grids))
				for _, g := range rf.Grids {
					cfg.SkillRangeCells = append(cfg.SkillRangeCells, [2]int{g.Col, g.Row})
				}
			}
		}
	}

	for k := range consumed {
		cfg.ConsumedKeys = append(cfg.ConsumedKeys, k)
	}

	return cfg, nil
}
