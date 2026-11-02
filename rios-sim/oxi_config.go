package main

import (
	"encoding/json"
	"fmt"
	"sort"
)

// OxiRuntimeConfig 将塔露拉的所有机制黑板键映射为强类型配置。
// 数值全部提取自 spec 中的原始 RawMessage，严禁硬编码。
type OxiRuntimeConfig struct {
	// 第一天赋「绝不妥协」
	T1ArcaneIdleDelay    float64 `json:"t1_arcane_idle_delay"`
	T1ArcaneStepInterval float64 `json:"t1_arcane_step_interval"`
	T1ArcaneStep         float64 `json:"t1_arcane_step"`
	T1ArcaneMax          float64 `json:"t1_arcane_max"`
	T1EpDamageRatio      float64 `json:"t1_ep_damage_ratio"`

	// 第二天赋「我即火焰」
	T2Unlocked      bool    `json:"t2_unlocked"`
	T2FieldDuration float64 `json:"t2_field_duration"`
	T2FieldInterval float64 `json:"t2_field_interval"`
	T2FieldAtkScale float64 `json:"t2_field_atk_scale"`
	T2MaxCount      int     `json:"t2_max_count"`

	// 技能槽与通用属性
	Slot         int     `json:"slot"`
	SkillLevel   int     `json:"skill_level"`
	SPType       string  `json:"sp_type"`
	SPCost       int     `json:"sp_cost"`
	InitSP       int     `json:"init_sp"`
	MaxCharge    int     `json:"max_charge"`
	Duration     float64 `json:"duration"`
	SkillRangeID string  `json:"skill_range_id"`

	// 技能 1「照霁白夜」
	S1AtkScale float64 `json:"s1_atk_scale"`
	S1Fear     float64 `json:"s1_fear"`

	// 技能 2「阻断骤雪」
	S2SkillDuration      float64 `json:"s2_skill_duration"`
	S2DamageRemaining    float64 `json:"s2_damage_remaining_scale"`
	S2DamageResistance   float64 `json:"s2_damage_resistance"`
	S2ShelterHoldDur     float64 `json:"s2_shelter_hold_duration"`
	S2RetaliateAtkScale  float64 `json:"s2_retaliate_atk_scale"`
	S2HealRatio          float64 `json:"s2_heal_ratio"`
	S2Atk                float64 `json:"s2_atk"`
	S2Def                float64 `json:"s2_def"`
	S2MaxStackCnt        int     `json:"s2_max_stack_cnt"`
	S2StackDuration      float64 `json:"s2_stack_duration"`
	S2AbilityRangeRadius float64 `json:"s2_ability_range_radius"`
	S2BuffedAtkScale     float64 `json:"s2_buffed_attack_atk_scale"`

	// 技能 3「日冕重烈」
	S3Atk                 float64 `json:"s3_atk"`
	S3HeatwaveAtkScale    float64 `json:"s3_heatwave_atk_scale"`
	S3NormalInterval      float64 `json:"s3_normal_interval"`
	S3OverloadInterval    float64 `json:"s3_overload_interval"`
	S3WaveSpeed           float64 `json:"s3_wave_speed"`
	S3NormalHalfWidth     float64 `json:"s3_normal_half_width"`
	S3OverloadHalfWidth   float64 `json:"s3_overload_half_width"`
	S3ProjectileRange     float64 `json:"s3_projectile_range"`
	S3RangeRadius         float64 `json:"s3_range_radius"`
	S3RandomBirthDelay    float64 `json:"s3_random_birth_delay"`
	S3WaveExitDistance    float64 `json:"s3_wave_exit_distance"`
	S3SameWaveRepeatScale float64 `json:"s3_same_wave_repeat_damage_scale"`

	// 确定性随机数 Seed
	RNGSeed uint64 `json:"rng_seed"`

	// 键审计
	ConsumedKeys []string `json:"consumed_keys"`
	UnusedKeys   []string `json:"unused_keys"`
	Unresolved   []string `json:"unresolved"`
}

func decodeOxiRuntimeConfig(s *OxiSourceSpec) (*OxiRuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("oxi config: source spec is nil")
	}

	cfg := &OxiRuntimeConfig{
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
				for k, v := range nums {
					switch k {
					case "arcane_idle_delay":
						cfg.T1ArcaneIdleDelay = v
						consumed["talent.0.arcane_idle_delay"] = true
					case "arcane_step_interval":
						cfg.T1ArcaneStepInterval = v
						consumed["talent.0.arcane_step_interval"] = true
					case "arcane_step":
						cfg.T1ArcaneStep = v
						consumed["talent.0.arcane_step"] = true
					case "arcane_max":
						cfg.T1ArcaneMax = v
						consumed["talent.0.arcane_max"] = true
					case "ep_damage_ratio":
						cfg.T1EpDamageRatio = v
						consumed["talent.0.ep_damage_ratio"] = true
					}
				}
			}
		} else if t.Group == 1 {
			// 第二天赋 (Group 1)
			cfg.T2Unlocked = true
			var cand struct {
				Blackboard json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(t.Raw, &cand); err == nil {
				nums, _, _ := parseRawBlackboard(cand.Blackboard)
				for k, v := range nums {
					switch k {
					case "field_duration":
						cfg.T2FieldDuration = v
						consumed["talent.1.field_duration"] = true
					case "field_interval":
						cfg.T2FieldInterval = v
						consumed["talent.1.field_interval"] = true
					case "field_atk_scale":
						cfg.T2FieldAtkScale = v
						consumed["talent.1.field_atk_scale"] = true
					case "max_count":
						cfg.T2MaxCount = int(v)
						consumed["talent.1.max_count"] = true
					}
				}
			}
		}
	}

	// 2. 解析技能
	if len(s.OperatorSkill.Raw) > 0 {
		var skFields struct {
			SPData struct {
				SPType    string `json:"spType"`
				SPCost    int    `json:"spCost"`
				InitSP    int    `json:"initSp"`
				MaxCharge int    `json:"maxCharge"`
			} `json:"spData"`
			Duration     float64         `json:"duration"`
			RangeID      string          `json:"rangeId"`
			Blackboard   json.RawMessage `json:"blackboard"`
		}
		if err := json.Unmarshal(s.OperatorSkill.Raw, &skFields); err != nil {
			return nil, fmt.Errorf("oxi config: failed to unmarshal skill raw: %w", err)
		}
		cfg.SPType = skFields.SPData.SPType
		cfg.SPCost = skFields.SPData.SPCost
		cfg.InitSP = skFields.SPData.InitSP
		cfg.MaxCharge = skFields.SPData.MaxCharge
		cfg.Duration = skFields.Duration
		cfg.SkillRangeID = skFields.RangeID

		nums, _, _ := parseRawBlackboard(skFields.Blackboard)
		for k, v := range nums {
			switch k {
			// 技能 1「照霁白夜」
			case "atk_scale":
				if s.Slot == 1 {
					cfg.S1AtkScale = v
					consumed["skill.1.atk_scale"] = true
				}
			case "fear":
				if s.Slot == 1 {
					cfg.S1Fear = v
					consumed["skill.1.fear"] = true
				}

			// 技能 2「阻断骤雪」
			case "skill_duration":
				if s.Slot == 2 {
					cfg.S2SkillDuration = v
					consumed["skill.2.skill_duration"] = true
				}
			case "damage_remaining_scale":
				if s.Slot == 2 {
					cfg.S2DamageRemaining = v
					consumed["skill.2.damage_remaining_scale"] = true
				}
			case "damage_resistance":
				if s.Slot == 2 {
					cfg.S2DamageResistance = v
					consumed["skill.2.damage_resistance"] = true
				}
			case "shelter_hold_duration":
				if s.Slot == 2 {
					cfg.S2ShelterHoldDur = v
					consumed["skill.2.shelter_hold_duration"] = true
				}
			case "retaliate_atk_scale":
				if s.Slot == 2 {
					cfg.S2RetaliateAtkScale = v
					consumed["skill.2.retaliate_atk_scale"] = true
				}
			case "heal_ratio":
				if s.Slot == 2 {
					cfg.S2HealRatio = v
					consumed["skill.2.heal_ratio"] = true
				}
			case "atk":
				if s.Slot == 2 {
					cfg.S2Atk = v
					consumed["skill.2.atk"] = true
				} else if s.Slot == 3 {
					cfg.S3Atk = v
					consumed["skill.3.atk"] = true
				}
			case "def":
				if s.Slot == 2 {
					cfg.S2Def = v
					consumed["skill.2.def"] = true
				}
			case "max_stack_cnt":
				if s.Slot == 2 {
					cfg.S2MaxStackCnt = int(v)
					consumed["skill.2.max_stack_cnt"] = true
				}
			case "stack_duration":
				if s.Slot == 2 {
					cfg.S2StackDuration = v
					consumed["skill.2.stack_duration"] = true
				}
			case "ability_range_radius":
				if s.Slot == 2 {
					cfg.S2AbilityRangeRadius = v
					consumed["skill.2.ability_range_radius"] = true
				}
			case "attack@buffed_attack_atk_scale":
				if s.Slot == 2 {
					cfg.S2BuffedAtkScale = v
					consumed["skill.2.attack@buffed_attack_atk_scale"] = true
				}

			// 技能 3「日冕重烈」
			case "heatwave_atk_scale":
				if s.Slot == 3 {
					cfg.S3HeatwaveAtkScale = v
					consumed["skill.3.heatwave_atk_scale"] = true
				}
			case "normal_interval":
				if s.Slot == 3 {
					cfg.S3NormalInterval = v
					consumed["skill.3.normal_interval"] = true
				}
			case "overload_interval":
				if s.Slot == 3 {
					cfg.S3OverloadInterval = v
					consumed["skill.3.overload_interval"] = true
				}
			case "wave_speed":
				if s.Slot == 3 {
					cfg.S3WaveSpeed = v
					consumed["skill.3.wave_speed"] = true
				}
			case "normal_half_width":
				if s.Slot == 3 {
					cfg.S3NormalHalfWidth = v
					consumed["skill.3.normal_half_width"] = true
				}
			case "overload_half_width":
				if s.Slot == 3 {
					cfg.S3OverloadHalfWidth = v
					consumed["skill.3.overload_half_width"] = true
				}
			case "projectile_range":
				if s.Slot == 3 {
					cfg.S3ProjectileRange = v
					consumed["skill.3.projectile_range"] = true
				}
			case "range_radius":
				if s.Slot == 3 {
					cfg.S3RangeRadius = v
					consumed["skill.3.range_radius"] = true
				}
			case "random_birth_delay":
				if s.Slot == 3 {
					cfg.S3RandomBirthDelay = v
					consumed["skill.3.random_birth_delay"] = true
				}
			case "wave_exit_distance":
				if s.Slot == 3 {
					cfg.S3WaveExitDistance = v
					consumed["skill.3.wave_exit_distance"] = true
				}
			case "same_wave_repeat_damage_scale":
				if s.Slot == 3 {
					cfg.S3SameWaveRepeatScale = v
					consumed["skill.3.same_wave_repeat_damage_scale"] = true
				}
			}
		}
	}

	for k := range consumed {
		cfg.ConsumedKeys = append(cfg.ConsumedKeys, k)
	}
	sort.Strings(cfg.ConsumedKeys)

	return cfg, nil
}
