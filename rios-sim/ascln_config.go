package main

import (
	"encoding/json"
	"fmt"
)

// AsclnRuntimeConfig 将阿斯卡纶的所有机制黑板键映射为强类型配置。
// 数值全部提取自 spec 中的原始 RawMessage，严禁硬编码。
type AsclnRuntimeConfig struct {
	// 第一天赋「密林低语」
	T1MoveSpeed      float64 `json:"t1_move_speed"`
	T1AtkRatio       float64 `json:"t1_atk_ratio"`
	T1MaxStackCnt    int     `json:"t1_max_stack_cnt"`
	T1DebuffDuration float64 `json:"t1_debuff_duration"`
	T1Interval       float64 `json:"t1_interval"`
	T1OnKillHpRatio  float64 `json:"t1_on_kill_hp_ratio"` // Y 模组击倒回复

	// 第二天赋「暗影遮蔽」
	T2Unlocked       bool    `json:"t2_unlocked"`
	T2AttackSpeed    float64 `json:"t2_attack_speed"`
	T2AttackSpeedAdd float64 `json:"t2_attack_speed_add"`
	T2Cnt            int     `json:"t2_cnt"`

	// 模组特性改写
	TraitDodgeProb  float64 `json:"trait_dodge_prob"`  // Y 模组提升至 0.65 (基础 0.50)
	TraitMoveSpeed  float64 `json:"trait_move_speed"`  // X 模组特性范围内移速 -0.20

	// 技能槽与通用属性
	Slot         int     `json:"slot"`
	SkillLevel   int     `json:"skill_level"`
	SPType       string  `json:"sp_type"`
	SPCost       int     `json:"sp_cost"`
	InitSP       int     `json:"init_sp"`
	MaxCharge    int     `json:"max_charge"`
	Duration     float64 `json:"duration"`
	SkillRangeID string  `json:"skill_range_id"`

	// 技能 1「无声收割」
	S1AtkScale float64 `json:"s1_atk_scale"`
	S1Cnt      int     `json:"s1_cnt"`

	// 技能 2「荆棘束缚」
	S2Atk         float64 `json:"s2_atk"`
	S2MoveSpeed   float64 `json:"s2_move_speed"`
	S2RangeRadius float64 `json:"s2_range_radius"`

	// 技能 3「尽头余烬」
	S3Atk                 float64 `json:"s3_atk"`
	S3BaseAttackTime      float64 `json:"s3_base_attack_time"`
	S3TauntLevel          float64 `json:"s3_taunt_level"`
	S3DamageHitratePhys   float64 `json:"s3_damage_hitrate_physical"`
	S3DamageHitrateMag    float64 `json:"s3_damage_hitrate_magical"`
	S3AttackHpRatio       float64 `json:"s3_attack_hp_ratio"`

	// 确定性随机数 Seed
	RNGSeed uint64 `json:"rng_seed"`

	// 键审计
	ConsumedKeys []string `json:"consumed_keys"`
	UnusedKeys   []string `json:"unused_keys"`
	Unresolved   []string `json:"unresolved"`
}

func decodeAsclnRuntimeConfig(s *AsclnSourceSpec) (*AsclnRuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("ascln config: source spec is nil")
	}

	cfg := &AsclnRuntimeConfig{
		Slot:            s.Slot,
		SkillLevel:      s.SkillLevel,
		T1MaxStackCnt:   3,
		T1Interval:      1.0,
		TraitDodgeProb:  0.50, // 伏击客基础特性 50% 双闪
		RNGSeed:         s.RNGSeed,
		ConsumedKeys:    make([]string, 0),
		UnusedKeys:      make([]string, 0),
	}
	if cfg.RNGSeed == 0 {
		cfg.RNGSeed = defaultProbRNGSeed
	}

	consumed := make(map[string]bool)

	// 1. 解析第一天赋 (Group 0)
	for _, t := range s.Talents {
		if t.Group == 0 {
			var cand struct {
				Blackboard json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(t.Raw, &cand); err == nil {
				nums, _, _ := parseRawBlackboard(cand.Blackboard)
				for k, v := range nums {
					switch k {
					case "move_speed":
						cfg.T1MoveSpeed = v
						consumed["talent.0.move_speed"] = true
					case "atk_ratio":
						cfg.T1AtkRatio = v
						consumed["talent.0.atk_ratio"] = true
					case "max_stack_cnt":
						cfg.T1MaxStackCnt = int(v)
						consumed["talent.0.max_stack_cnt"] = true
					case "debuff_duration":
						cfg.T1DebuffDuration = v
						consumed["talent.0.debuff_duration"] = true
					case "interval":
						cfg.T1Interval = v
						consumed["talent.0.interval"] = true
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
					case "attack_speed":
						cfg.T2AttackSpeed = v
						consumed["talent.1.attack_speed"] = true
					case "attack_speed_add":
						cfg.T2AttackSpeedAdd = v
						consumed["talent.1.attack_speed_add"] = true
					case "cnt":
						cfg.T2Cnt = int(v)
						consumed["talent.1.cnt"] = true
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
			if p, ok := nums["prob"]; ok {
				cfg.TraitDodgeProb = p
				consumed["module.trait.prob"] = true
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
				if ms, ok := nums["move_speed"]; ok {
					cfg.TraitMoveSpeed = ms
					consumed["module.trait.move_speed"] = true
				}
			} else if mc.TalentIndex == 0 {
				for k, v := range nums {
					switch k {
					case "move_speed":
						cfg.T1MoveSpeed = v
						consumed["module.t1.move_speed"] = true
					case "atk_ratio":
						cfg.T1AtkRatio = v
						consumed["module.t1.atk_ratio"] = true
					case "max_stack_cnt":
						cfg.T1MaxStackCnt = int(v)
						consumed["module.t1.max_stack_cnt"] = true
					case "debuff_duration":
						cfg.T1DebuffDuration = v
						consumed["module.t1.debuff_duration"] = true
					case "interval":
						cfg.T1Interval = v
						consumed["module.t1.interval"] = true
					case "hp_ratio":
						cfg.T1OnKillHpRatio = v
						consumed["module.t1.hp_ratio"] = true
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
		return nil, fmt.Errorf("ascln config: failed to unmarshal skill raw: %w", err)
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
		case "atk_scale":
			cfg.S1AtkScale = v
			consumed["skill.atk_scale"] = true
		case "cnt":
			cfg.S1Cnt = int(v)
			consumed["skill.cnt"] = true
		case "atk":
			if s.Slot == 2 {
				cfg.S2Atk = v
			} else if s.Slot == 3 {
				cfg.S3Atk = v
			}
			consumed["skill.atk"] = true
		case "move_speed":
			cfg.S2MoveSpeed = v
			consumed["skill.move_speed"] = true
		case "range_radius":
			cfg.S2RangeRadius = v
			consumed["skill.range_radius"] = true
		case "base_attack_time":
			cfg.S3BaseAttackTime = v
			consumed["skill.base_attack_time"] = true
		case "taunt_level":
			cfg.S3TauntLevel = v
			consumed["skill.taunt_level"] = true
		case "attack@damage_hitrate_physical":
			cfg.S3DamageHitratePhys = v
			consumed["skill.attack@damage_hitrate_physical"] = true
		case "attack@damage_hitrate_magical":
			cfg.S3DamageHitrateMag = v
			consumed["skill.attack@damage_hitrate_magical"] = true
		case "attack@hp_ratio":
			cfg.S3AttackHpRatio = v
			consumed["skill.attack@hp_ratio"] = true
		default:
			cfg.UnusedKeys = append(cfg.UnusedKeys, k)
		}
	}

	for k := range consumed {
		cfg.ConsumedKeys = append(cfg.ConsumedKeys, k)
	}

	return cfg, nil
}
