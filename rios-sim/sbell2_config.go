package main

import (
	"encoding/json"
	"fmt"
)

// Sbell2RuntimeConfig 将圣聆初雪的所有机制黑板键映射为强类型配置。
type Sbell2RuntimeConfig struct {
	// 子职业特性
	TraitDef              float64 `json:"trait_def"`               // def: 2.0 (未开启技能时 DEF +200%)
	TraitMagicResistance  float64 `json:"trait_magic_resistance"`  // magic_resistance: 20.0 (未开启技能时 RES +20)

	// Y 模组特性强化
	TraitDamageScale      float64 `json:"trait_damage_scale"`      // 0.03 (每多1个敌人提升 3% 伤害)
	TraitMaxValidStackCnt int     `json:"trait_max_valid_stack_cnt"` // 5 (最多叠加 5 层)

	// 第一天赋【无垠的雪景】
	T1Interval         float64 `json:"t1_interval"`           // 产生积雪间隔 (10.0 / 7.5 / 5.5 / 5.0)
	T1MaxCastCnt       int     `json:"t1_max_cast_cnt"`       // 最大层数 (5)
	T1MoveSpeed        float64 `json:"t1_move_speed"`         // 减速 (-0.10 / -0.12)
	T1TalentMagicScale float64 `json:"t1_talent_magic_scale"` // 踏入法术伤害倍率 (0.2 ~ 1.05)
	T1FirstSnow        bool    `json:"t1_first_snow"`         // 部署瞬间产生积雪 (first_snow: 1.0)

	// 第二天赋【圣山的祝福】
	T2Unlocked  bool    `json:"t2_unlocked"`   // 是否解锁第二天赋 (E2)
	T2HpRatio   float64 `json:"t2_hp_ratio"`   // 满血复活比例 (1.0)
	T2Cold      float64 `json:"t2_cold"`       // 受击反击寒冷秒数 (1.5 / 2.0)
	T2Freeze    float64 `json:"t2_freeze"`     // 自身冻结秒数 (4.0)
	T2C2eFreeze float64 `json:"t2_c2e_freeze"` // 范围敌方冻结秒数 (8.0)

	// 技能槽与通用属性
	Slot         int     `json:"slot"`
	SkillLevel   int     `json:"skill_level"`
	SPType       string  `json:"sp_type"`
	SPCost       int     `json:"sp_cost"`
	InitSP       int     `json:"init_sp"`
	MaxCharge    int     `json:"max_charge"`
	Duration     float64 `json:"duration"`
	SkillRangeID string  `json:"skill_range_id"`

	// 技能一【铃音吹雪】
	S1AtkScale float64 `json:"s1_atk_scale"` // 伤害倍率 (4.8 ~ 5.2)
	S1Cold     float64 `json:"s1_cold"`      // 施加寒冷 (3.5)
	S1Force    float64 `json:"s1_force"`     // 推动力度 (1.0)
	S1TrigCnt  int     `json:"s1_trig_cnt"`  // 积雪向前扩散格数 (5)

	// 技能二【霜涛覆岭】
	S2AtkScaleS2        float64 `json:"s2_atk_scale_s2"`         // 攻击伤害倍率 (3.5 ~ 3.8)
	S2TalentCold        float64 `json:"s2_talent_cold"`          // 离雪寒冷 (5.0)
	S2TalentS2MagicScale float64 `json:"s2_talent_s2_magic_scale"` // 积雪上每秒受到法伤倍率 (0.2)
	S2MaxCastTileCount  int     `json:"s2_max_cast_tile_count"`  // 积雪扩散上限 (20)
	S2TokenKeyFreeze    bool    `json:"s2_token_key_freeze"`     // 满 5 层冻结 (talent@token_key)

	// 技能三【群山俯首】
	S3Atk                     float64 `json:"s3_atk"`                       // 攻击力加成 (0.7 ~ 1.0)
	S3AttackSpeed             float64 `json:"s3_attack_speed"`             // 攻速加成 (30.0)
	S3MagicResistPenetrateFixed float64 `json:"s3_magic_resist_penetrate_fixed"` // 法抗穿透 (10.0)
	S3AttractTime             float64 `json:"s3_attract_time"`             // 诱导吸引持续时间 (10.0)
	S3AtkScaleS3              float64 `json:"s3_atk_scale_s3"`              // 攻击伤害倍率 (2.1 ~ 2.6)
	S3Interval                float64 `json:"s3_interval"`                  // 积雪生成加速间隔 (1.5)

	// 键审计
	ConsumedKeys []string `json:"consumed_keys"`
	UnusedKeys   []string `json:"unused_keys"`
}

func decodeSbell2RuntimeConfig(s *Sbell2SourceSpec) (*Sbell2RuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("sbell2 config: source spec is nil")
	}

	cfg := &Sbell2RuntimeConfig{
		Slot:                 s.Slot,
		SkillLevel:           s.SkillLevel,
		TraitDef:             2.0,  // 基础特性 def +200%
		TraitMagicResistance: 20.0, // 基础特性 res +20
		T1MaxCastCnt:         5,
		T1Interval:           10.0,
		T1MoveSpeed:          -0.10,
		T1TalentMagicScale:   0.20,
		ConsumedKeys:         make([]string, 0),
		UnusedKeys:           make([]string, 0),
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
					case "interval":
						cfg.T1Interval = v
						consumed["talent.0.interval"] = true
					case "max_cast_cnt":
						cfg.T1MaxCastCnt = int(v)
						consumed["talent.0.max_cast_cnt"] = true
					case "move_speed":
						cfg.T1MoveSpeed = v
						consumed["talent.0.move_speed"] = true
					case "talent_magic_scale":
						cfg.T1TalentMagicScale = v
						consumed["talent.0.talent_magic_scale"] = true
					case "first_snow":
						cfg.T1FirstSnow = (v > 0)
						consumed["talent.0.first_snow"] = true
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
					case "hp_ratio":
						cfg.T2HpRatio = v
						consumed["talent.1.hp_ratio"] = true
					case "cold":
						cfg.T2Cold = v
						consumed["talent.1.cold"] = true
					case "freeze":
						cfg.T2Freeze = v
						consumed["talent.1.freeze"] = true
					case "c2e_freeze":
						cfg.T2C2eFreeze = v
						consumed["talent.1.c2e_freeze"] = true
					}
				}
			}
		}
	}

	// 2. 模组覆盖与强化
	if s.Module != nil {
		for _, candRaw := range s.ModuleCandidates {
			var cand struct {
				TalentIndex int             `json:"talentIndex"`
				Blackboard  json.RawMessage `json:"blackboard"`
			}
			if err := json.Unmarshal(candRaw, &cand); err == nil {
				nums, _, _ := parseRawBlackboard(cand.Blackboard)
				if cand.TalentIndex == 0 {
					// 升级第一天赋
					for k, v := range nums {
						switch k {
						case "interval":
							cfg.T1Interval = v
							consumed["module.t0.interval"] = true
						case "max_cast_cnt":
							cfg.T1MaxCastCnt = int(v)
							consumed["module.t0.max_cast_cnt"] = true
						case "move_speed":
							cfg.T1MoveSpeed = v
							consumed["module.t0.move_speed"] = true
						case "talent_magic_scale":
							cfg.T1TalentMagicScale = v
							consumed["module.t0.talent_magic_scale"] = true
						case "first_snow":
							cfg.T1FirstSnow = (v > 0)
							consumed["module.t0.first_snow"] = true
						}
					}
				} else if cand.TalentIndex == -1 {
					// 模组特性附加 (Y 模组范围增伤)
					for k, v := range nums {
						switch k {
						case "damage_scale":
							cfg.TraitDamageScale = v
							consumed["module.trait.damage_scale"] = true
						case "max_valid_stack_cnt":
							cfg.TraitMaxValidStackCnt = int(v)
							consumed["module.trait.max_valid_stack_cnt"] = true
						}
					}
				}
			}
		}
	}

	// 3. 技能解析
	var skRaw struct {
		SkillType  string          `json:"skillType"`
		SPData     struct {
			SPType    string `json:"spType"`
			LevelUpCost int  `json:"levelUpCost"`
			MaxChargeTime int `json:"maxChargeTime"`
			SPCost    int    `json:"spCost"`
			InitSP    int    `json:"initSp"`
			Increment float64 `json:"increment"`
		} `json:"spData"`
		Duration   float64         `json:"duration"`
		RangeID    string          `json:"rangeId"`
		Blackboard json.RawMessage `json:"blackboard"`
	}
	if err := json.Unmarshal(s.OperatorSkill.Raw, &skRaw); err != nil {
		return nil, fmt.Errorf("sbell2 config: failed to unmarshal skill raw: %w", err)
	}

	cfg.SPType = skRaw.SPData.SPType
	cfg.SPCost = skRaw.SPData.SPCost
	cfg.InitSP = skRaw.SPData.InitSP
	cfg.MaxCharge = skRaw.SPData.MaxChargeTime
	cfg.Duration = skRaw.Duration
	cfg.SkillRangeID = skRaw.RangeID

	nums, _, _ := parseRawBlackboard(skRaw.Blackboard)
	for k, v := range nums {
		switch k {
		// S1 键
		case "atk_scale":
			cfg.S1AtkScale = v
			consumed["skill.atk_scale"] = true
		case "cold":
			cfg.S1Cold = v
			consumed["skill.cold"] = true
		case "force":
			cfg.S1Force = v
			consumed["skill.force"] = true
		case "trig_cnt":
			cfg.S1TrigCnt = int(v)
			consumed["skill.trig_cnt"] = true

		// S2 键
		case "attack@atk_scale_s2":
			cfg.S2AtkScaleS2 = v
			consumed["skill.attack@atk_scale_s2"] = true
		case "talent@cold":
			cfg.S2TalentCold = v
			consumed["skill.talent@cold"] = true
		case "talent@s2_magic_scale":
			cfg.S2TalentS2MagicScale = v
			consumed["skill.talent@s2_magic_scale"] = true
		case "talent@max_cast_tile_count":
			cfg.S2MaxCastTileCount = int(v)
			consumed["skill.talent@max_cast_tile_count"] = true
		case "talent@token_key":
			cfg.S2TokenKeyFreeze = true
			consumed["skill.talent@token_key"] = true

		// S3 键
		case "atk":
			cfg.S3Atk = v
			consumed["skill.atk"] = true
		case "attack_speed":
			cfg.S3AttackSpeed = v
			consumed["skill.attack_speed"] = true
		case "magic_resist_penetrate_fixed":
			cfg.S3MagicResistPenetrateFixed = v
			consumed["skill.magic_resist_penetrate_fixed"] = true
		case "attract_time":
			cfg.S3AttractTime = v
			consumed["skill.attract_time"] = true
		case "attack@atk_scale_s3":
			cfg.S3AtkScaleS3 = v
			consumed["skill.attack@atk_scale_s3"] = true
		case "interval":
			cfg.S3Interval = v
			consumed["skill.interval"] = true
		default:
			cfg.UnusedKeys = append(cfg.UnusedKeys, k)
		}
	}

	for k := range consumed {
		cfg.ConsumedKeys = append(cfg.ConsumedKeys, k)
	}

	return cfg, nil
}
