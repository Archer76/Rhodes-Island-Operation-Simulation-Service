package main

import (
	"encoding/json"
	"fmt"
)

// TyphonRuntimeConfig 将提丰的所有机制黑板键映射为强类型配置。
// 数值全部提取自 spec 中的原始 RawMessage，严禁硬编码。
type TyphonRuntimeConfig struct {
	// 第一天赋「锐如兽牙」
	T1Unlocked     bool    `json:"t1_unlocked"`
	T1DefPenetrate float64 `json:"t1_def_penetrate"`
	T1Duration     float64 `json:"t1_duration"`
	T1MaxStackCnt  int     `json:"t1_max_stack_cnt"`

	// 第二天赋「重如沼泥」
	T2Unlocked  bool    `json:"t2_unlocked"`
	T2AtkScale  float64 `json:"t2_atk_scale"`
	T2Sluggish  float64 `json:"t2_sluggish"`
	T2MaxStacks int     `json:"t2_max_stacks"` // 模组 Y 增加的层数（若有）

	// 模组 X 特性追加（对重量 >= min_weight 敌人攻击力提升至 atk_scale）
	ModXAtkScale  float64 `json:"mod_x_atk_scale"`
	ModXMinWeight float64 `json:"mod_x_min_weight"`

	// 模组 Y 特性追加（远距离增伤）
	ModYDamageScale float64 `json:"mod_y_damage_scale"`
	ModYMinDist     float64 `json:"mod_y_min_dist"`
	ModYMaxDist     float64 `json:"mod_y_max_dist"`

	// 技能槽与通用属性
	Slot         int     `json:"slot"`
	SkillLevel   int     `json:"skill_level"`
	SPType       string  `json:"sp_type"`
	SPCost       int     `json:"sp_cost"`
	InitSP       int     `json:"init_sp"`
	MaxCharge    int     `json:"max_charge"`
	Duration     float64 `json:"duration"`
	SkillRangeID string  `json:"skill_range_id"`

	// 技能 1「迅捷打击·γ型」
	S1Atk         float64 `json:"s1_atk"`
	S1AttackSpeed float64 `json:"s1_attack_speed"`

	// 技能 2「冰原秩序」
	S2Atk           float64 `json:"s2_atk"`
	S2AttackProb    float64 `json:"s2_attack_prob"`
	S2AttackStun    float64 `json:"s2_attack_stun"`
	S2FirstDuration float64 `json:"s2_first_duration"`

	// 技能 3「永恒狩猎」
	S3BaseAttackTime float64 `json:"s3_base_attack_time"`
	S3Stun           float64 `json:"s3_stun"`
	S3AtkScale       float64 `json:"s3_atk_scale"`
	S3TriggerTime    int     `json:"s3_trigger_time"`
	S3MaxHitNum      int     `json:"s3_max_hit_num"`

	// 确定性随机数 Seed
	RNGSeed uint64 `json:"rng_seed"`

	// 键审计
	ConsumedKeys []string `json:"consumed_keys"`
	UnusedKeys   []string `json:"unused_keys"`
	Unresolved   []string `json:"unresolved"`
}

func decodeTyphonRuntimeConfig(s *TyphonSourceSpec) (*TyphonRuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("typhon config: source spec is nil")
	}

	cfg := &TyphonRuntimeConfig{
		Slot:         s.Slot,
		SkillLevel:   s.SkillLevel,
		RNGSeed:      s.RNGSeed,
		ConsumedKeys: make([]string, 0),
		UnusedKeys:   make([]string, 0),
	}
	if cfg.RNGSeed == 0 {
		cfg.RNGSeed = defaultProbRNGSeed
	}

	consumed := make(map[string]bool)

	// 1. 解析天赋
	for _, t := range s.Talents {
		if t.Group == 0 {
			cfg.T1Unlocked = true
			var cand struct {
				Blackboard json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(t.Raw, &cand); err == nil {
				nums, _, _ := parseRawBlackboard(cand.Blackboard)
				for k, v := range nums {
					switch k {
					case "def_penetrate":
						cfg.T1DefPenetrate = v
						consumed["talent.0.def_penetrate"] = true
					case "duration":
						cfg.T1Duration = v
						consumed["talent.0.duration"] = true
					case "max_stack_cnt":
						cfg.T1MaxStackCnt = int(v)
						consumed["talent.0.max_stack_cnt"] = true
					default:
						cfg.UnusedKeys = append(cfg.UnusedKeys, "talent.0."+k)
					}
				}
			}
		} else if t.Group == 1 {
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
					case "sluggish":
						cfg.T2Sluggish = v
						consumed["talent.1.sluggish"] = true
					default:
						cfg.UnusedKeys = append(cfg.UnusedKeys, "talent.1."+k)
					}
				}
			}
		}
	}

	// 2. 解析模组候选与特性覆盖
	if len(s.TraitOverride) > 0 {
		var tr struct {
			Blackboard json.RawMessage `json:"blackboard"`
		}
		if err := json.Unmarshal(s.TraitOverride, &tr); err == nil {
			nums, _, _ := parseRawBlackboard(tr.Blackboard)
			for k, v := range nums {
				switch k {
				case "atk_scale":
					cfg.ModXAtkScale = v
					consumed["module.trait.atk_scale"] = true
				case "value":
					cfg.ModXMinWeight = v
					consumed["module.trait.value"] = true
				case "damage_scale":
					cfg.ModYDamageScale = v
					consumed["module.trait.damage_scale"] = true
				case "min_dist":
					cfg.ModYMinDist = v
					consumed["module.trait.min_dist"] = true
				case "max_dist":
					cfg.ModYMaxDist = v
					consumed["module.trait.max_dist"] = true
				default:
					cfg.UnusedKeys = append(cfg.UnusedKeys, "module.trait."+k)
				}
			}
		}
	}
	for _, mCandRaw := range s.ModuleCandidates {
		var mc struct {
			TalentIndex int             `json:"talentIndex"`
			Blackboard  json.RawMessage `json:"blackboard"`
		}
		if err := json.Unmarshal(mCandRaw, &mc); err == nil {
			nums, _, _ := parseRawBlackboard(mc.Blackboard)
			if mc.TalentIndex == -1 {
				for k, v := range nums {
					switch k {
					case "atk_scale":
						cfg.ModXAtkScale = v
						consumed["module.trait.atk_scale"] = true
					case "value":
						cfg.ModXMinWeight = v
						consumed["module.trait.value"] = true
					case "damage_scale":
						cfg.ModYDamageScale = v
						consumed["module.trait.damage_scale"] = true
					case "min_dist":
						cfg.ModYMinDist = v
						consumed["module.trait.min_dist"] = true
					case "max_dist":
						cfg.ModYMaxDist = v
						consumed["module.trait.max_dist"] = true
					default:
						cfg.UnusedKeys = append(cfg.UnusedKeys, "module.trait."+k)
					}
				}
			} else if mc.TalentIndex == 0 {
				for k, v := range nums {
					switch k {
					case "def_penetrate":
						cfg.T1DefPenetrate = v
						consumed["module.t1.def_penetrate"] = true
					case "duration":
						cfg.T1Duration = v
						consumed["module.t1.duration"] = true
					case "max_stack_cnt":
						cfg.T1MaxStackCnt = int(v)
						consumed["module.t1.max_stack_cnt"] = true
					case "atk_scale":
						cfg.ModXAtkScale = v
						consumed["module.trait.atk_scale"] = true
					case "value":
						cfg.ModXMinWeight = v
						consumed["module.trait.value"] = true
					default:
						cfg.UnusedKeys = append(cfg.UnusedKeys, "module.t1."+k)
					}
				}
			} else if mc.TalentIndex == 1 {
				for k, v := range nums {
					switch k {
					case "atk_scale":
						cfg.T2AtkScale = v
						consumed["module.t2.atk_scale"] = true
					case "sluggish":
						cfg.T2Sluggish = v
						consumed["module.t2.sluggish"] = true
					case "max_stack_cnt":
						cfg.T2MaxStacks = int(v)
						consumed["module.t2.max_stack_cnt"] = true
					default:
						cfg.UnusedKeys = append(cfg.UnusedKeys, "module.t2."+k)
					}
				}
			}
		}
	}

	// 3. 解析技能
	var skFields struct {
		SpData struct {
			SpType        string `json:"spType"`
			SpCost        int    `json:"spCost"`
			InitSp        int    `json:"initSp"`
			MaxChargeTime int    `json:"maxChargeTime"`
		} `json:"spData"`
		Duration   float64         `json:"duration"`
		RangeID    *string         `json:"rangeId"`
		Blackboard json.RawMessage `json:"blackboard"`
	}
	if err := json.Unmarshal(s.OperatorSkill.Raw, &skFields); err != nil {
		return nil, fmt.Errorf("typhon config: failed to unmarshal skill raw: %w", err)
	}

	cfg.SPType = skFields.SpData.SpType
	cfg.SPCost = skFields.SpData.SpCost
	cfg.InitSP = skFields.SpData.InitSp
	cfg.MaxCharge = skFields.SpData.MaxChargeTime
	cfg.Duration = skFields.Duration
	if skFields.RangeID != nil {
		cfg.SkillRangeID = *skFields.RangeID
	}

	nums, _, _ := parseRawBlackboard(skFields.Blackboard)
	for k, v := range nums {
		switch k {
		case "atk":
			if s.Slot == 1 {
				cfg.S1Atk = v
			} else if s.Slot == 2 {
				cfg.S2Atk = v
			}
			consumed["skill.atk"] = true
		case "attack_speed":
			cfg.S1AttackSpeed = v
			consumed["skill.attack_speed"] = true
		case "attack@prob":
			cfg.S2AttackProb = v
			consumed["skill.attack@prob"] = true
		case "attack@stun":
			cfg.S2AttackStun = v
			consumed["skill.attack@stun"] = true
		case "first_duration":
			cfg.S2FirstDuration = v
			consumed["skill.first_duration"] = true
		case "base_attack_time":
			cfg.S3BaseAttackTime = v
			consumed["skill.base_attack_time"] = true
		case "attack@s3_stun":
			cfg.S3Stun = v
			consumed["skill.attack@s3_stun"] = true
		case "attack@s3_atk_scale":
			cfg.S3AtkScale = v
			consumed["skill.attack@s3_atk_scale"] = true
		case "attack@s3_trigger_time":
			cfg.S3TriggerTime = int(v)
			consumed["skill.attack@s3_trigger_time"] = true
		case "attack@s3_max_hit_num":
			cfg.S3MaxHitNum = int(v)
			consumed["skill.attack@s3_max_hit_num"] = true
		default:
			cfg.UnusedKeys = append(cfg.UnusedKeys, k)
		}
	}

	for k := range consumed {
		cfg.ConsumedKeys = append(cfg.ConsumedKeys, k)
	}

	return cfg, nil
}
