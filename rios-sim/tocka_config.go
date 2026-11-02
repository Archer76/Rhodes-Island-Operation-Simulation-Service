package main

import (
	"encoding/json"
	"fmt"
)

// TockaRuntimeConfig 将冻河的所有机制黑板键映射为强类型配置。
// 数值全部提取自 spec 中的原始 RawMessage，严禁硬编码。
type TockaRuntimeConfig struct {
	// 第一天赋「夜的哑然」
	T1Unlocked  bool    `json:"t1_unlocked"`
	T1SP        float64 `json:"t1_sp"`
	T1HealScale float64 `json:"t1_heal_scale"`

	// 第二天赋「雪的印痕」
	T2Unlocked        bool    `json:"t2_unlocked"`
	T2BuffDuration    float64 `json:"t2_buff_duration"`
	T2MagicAtkScale   float64 `json:"t2_magic_atk_scale"`
	T2ProjectileRange float64 `json:"t2_projectile_range"`
	T2Atk             float64 `json:"t2_atk"`

	// 技能槽与通用属性
	Slot       int     `json:"slot"`
	SkillLevel int     `json:"skill_level"`
	SPType     string  `json:"sp_type"`
	SPCost     int     `json:"sp_cost"`
	InitSP     int     `json:"init_sp"`
	Duration   float64 `json:"duration"`

	// 技能 1「一无所有之人」
	S1ShieldAtkScale float64 `json:"s1_shield_atk_scale"`
	S1ShieldTime     float64 `json:"s1_shield_time"`
	S1Stun           float64 `json:"s1_stun"`
	S1MaxTarget      int     `json:"s1_max_target"`

	// 技能 2「意欲呼啸之心」
	S2AttackSpeed  float64 `json:"s2_attack_speed"`
	S2BuffDuration float64 `json:"s2_buff_duration"`
	S2MaxTarget    int     `json:"s2_max_target"`

	// 技能 3「踽踽独行之春」
	S3AttackSpeed       float64 `json:"s3_attack_speed"`
	S3AttackMaxTarget   int     `json:"s3_attack_max_target"`
	S3AttackAtkScale    float64 `json:"s3_attack_atk_scale"`
	S3AttackStun        float64 `json:"s3_attack_stun"`
	S3BonusInitAtk      float64 `json:"s3_bonus_init_atk"`
	S3BonusDuration     float64 `json:"s3_bonus_duration"`
	S3BonusAtkDecPerSec float64 `json:"s3_bonus_atk_dec_per_sec"`
	S3BonusSP           float64 `json:"s3_bonus_sp"`

	// 随机数 Seed
	RNGSeed uint64 `json:"rng_seed"`

	// 键审计
	ConsumedKeys []string `json:"consumed_keys"`
	UnusedKeys   []string `json:"unused_keys"`
	Unresolved   []string `json:"unresolved"`
}

func decodeTockaRuntimeConfig(s *TockaSourceSpec) (*TockaRuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("tocka config: source spec is nil")
	}

	cfg := &TockaRuntimeConfig{
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

	// 1. 解析第一天赋 (Group 0)
	for _, t := range s.Talents {
		if t.Group == 0 {
			var cand struct {
				Blackboard json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(t.Raw, &cand); err == nil {
				nums, _, _ := parseRawBlackboard(cand.Blackboard)
				cfg.T1Unlocked = true
				for k, v := range nums {
					switch k {
					case "sp":
						cfg.T1SP = v
						consumed["talent.0.sp"] = true
					case "heal_scale":
						cfg.T1HealScale = v
						consumed["talent.0.heal_scale"] = true
					}
				}
			}
		} else if t.Group == 1 {
			// 2. 解析第二天赋 (Group 1)
			var cand struct {
				Blackboard json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(t.Raw, &cand); err == nil {
				nums, _, _ := parseRawBlackboard(cand.Blackboard)
				cfg.T2Unlocked = true
				for k, v := range nums {
					switch k {
					case "attack@t2_buff_duration":
						cfg.T2BuffDuration = v
						consumed["talent.1.attack@t2_buff_duration"] = true
					case "attack@t2_magic_atk_scale":
						cfg.T2MagicAtkScale = v
						consumed["talent.1.attack@t2_magic_atk_scale"] = true
					case "attack@projectile_range":
						cfg.T2ProjectileRange = v
						consumed["talent.1.attack@projectile_range"] = true
					case "attack@t2_atk":
						cfg.T2Atk = v
						consumed["talent.1.attack@t2_atk"] = true
					}
				}
			}
		}
	}

	// 3. 解析当前技能等级
	var sLvl struct {
		SPData struct {
			SPType string `json:"spType"`
			SPCost int    `json:"spCost"`
			InitSP int    `json:"initSp"`
		} `json:"spData"`
		Duration   float64         `json:"duration"`
		Blackboard json.RawMessage `json:"blackboard"`
	}
	if err := json.Unmarshal(s.OperatorSkill.Raw, &sLvl); err == nil {
		cfg.SPType = sLvl.SPData.SPType
		cfg.SPCost = sLvl.SPData.SPCost
		cfg.InitSP = sLvl.SPData.InitSP
		cfg.Duration = sLvl.Duration

		nums, _, _ := parseRawBlackboard(sLvl.Blackboard)
		prefix := fmt.Sprintf("skill.%d.", s.Slot)
		for k, v := range nums {
			switch k {
			// S1
			case "shield_atk_scale":
				cfg.S1ShieldAtkScale = v
				consumed[prefix+"shield_atk_scale"] = true
			case "shield_time":
				cfg.S1ShieldTime = v
				consumed[prefix+"shield_time"] = true
			case "stun":
				cfg.S1Stun = v
				consumed[prefix+"stun"] = true
			case "max_target":
				if s.Slot == 1 {
					cfg.S1MaxTarget = int(v)
				} else if s.Slot == 2 {
					cfg.S2MaxTarget = int(v)
				}
				consumed[prefix+"max_target"] = true

			// S2
			case "attack_speed":
				if s.Slot == 2 {
					cfg.S2AttackSpeed = v
				} else if s.Slot == 3 {
					cfg.S3AttackSpeed = v
				}
				consumed[prefix+"attack_speed"] = true
			case "buff_duration":
				cfg.S2BuffDuration = v
				consumed[prefix+"buff_duration"] = true

			// S3
			case "attack@max_target":
				cfg.S3AttackMaxTarget = int(v)
				consumed[prefix+"attack@max_target"] = true
			case "attack@atk_scale":
				cfg.S3AttackAtkScale = v
				consumed[prefix+"attack@atk_scale"] = true
			case "attack@stun":
				cfg.S3AttackStun = v
				consumed[prefix+"attack@stun"] = true
			case "bonus_init_atk":
				cfg.S3BonusInitAtk = v
				consumed[prefix+"bonus_init_atk"] = true
			case "bonus_duration":
				cfg.S3BonusDuration = v
				consumed[prefix+"bonus_duration"] = true
			case "bonus_atk_dec_per_sec":
				cfg.S3BonusAtkDecPerSec = v
				consumed[prefix+"bonus_atk_dec_per_sec"] = true
			case "bonus_sp":
				cfg.S3BonusSP = v
				consumed[prefix+"bonus_sp"] = true
			}
		}
	}

	for k := range consumed {
		cfg.ConsumedKeys = append(cfg.ConsumedKeys, k)
	}

	return cfg, nil
}
