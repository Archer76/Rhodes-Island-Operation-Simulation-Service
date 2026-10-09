package main

import (
	"encoding/json"
	"fmt"
)

type wisdelRuntimeConfig struct {
	Slot int

	// Trait & Module
	AppendAtkScale   float64 // 0.5
	EnableThirdAttack bool    // module Lv1+ provides 1.0

	// Talent 1 (好礼)
	TalentMainAtkScale float64 // attack@main_atk_scale: 1.0 (E1) -> 1.15 (E2) -> 1.20 (Mod2) -> 1.25 (Mod3)
	TalentBombAtkScale float64 // attack@bomb_atk_scale: 1.2~1.85
	TalentBombProb     float64 // attack@prob: 0.15
	TalentBombStun     float64 // attack@stun: 0.5s / 1.0s
	TalentBombRadius   float64 // attack@range_radius: 1.1

	// Skill 1 (定点清算)
	S1AppendAtkScale float64 // append_atk_scale: 0.6 ~ 1.2
	S1StunDuration   float64 // stun_duration: 0.5 ~ 1.5

	// Skill 2 (饱和复仇)
	S2Atk            float64 // atk: 0.1 ~ 0.35
	S2BaseAttackTime float64 // base_attack_time: -0.5 ~ -0.7
	S2AtkScaleOl     float64 // attack@atk_scale_ol: 0.6 ~ 0.8

	// Skill 3 (爆裂黎明)
	S3Atk            float64 // atk: 0.95 ~ 1.8
	S3AtkScale3      float64 // attack@atk_scale_3: 1.6 ~ 2.2
	S3Prob           float64 // attack@prob: 1.0
	S3TriggerTime    int     // attack@trigger_time: 6 (ammo count)
	S3BaseAttackTime float64 // base_attack_time: 2.9
	S3MaxCnt         int     // max_cnt: 1 ~ 2 (wards summoned)
	S3SpParam        float64 // sp: 3.0

	// Token Skill (魂灵之影 sktok_wisdel_wward)
	WardSluggish float64 // sluggish: 1.0
	WardSpMin    float64 // sp_min: 0.0
	WardSpMax    float64 // sp_max: 3.0
}

func wisdelStrictBB(raw json.RawMessage) (map[string]float64, error) {
	if len(raw) == 0 {
		return map[string]float64{}, nil
	}
	var obj struct {
		Blackboard []struct {
			Key      string   `json:"key"`
			Value    *float64 `json:"value"`
			ValueStr *string  `json:"valueStr"`
		} `json:"blackboard"`
	}
	if err := json.Unmarshal(raw, &obj); err != nil {
		return nil, err
	}
	out := make(map[string]float64, len(obj.Blackboard))
	for _, r := range obj.Blackboard {
		if r.Key == "" {
			return nil, fmt.Errorf("invalid wisdel blackboard entry")
		}
		if _, exists := out[r.Key]; exists {
			return nil, fmt.Errorf("duplicate wisdel key %s", r.Key)
		}
		if r.Value != nil {
			out[r.Key] = *r.Value
		} else {
			out[r.Key] = 0
		}
	}
	return out, nil
}

func decodeWisdelRuntimeConfig(s *WisdelSourceSpec) (wisdelRuntimeConfig, error) {
	if s == nil {
		return wisdelRuntimeConfig{}, fmt.Errorf("invalid wisdel source spec")
	}
	cfg := wisdelRuntimeConfig{
		Slot:               s.Slot,
		AppendAtkScale:     0.5,
		TalentBombProb:     0.15,
		TalentMainAtkScale: 1.0,
		TalentBombRadius:   1.1,
	}

	// 1. Skill blackboard
	bb, err := wisdelStrictBB(s.OperatorSkill.Raw)
	if err != nil {
		return cfg, err
	}
	switch s.Slot {
	case 1:
		val, ok := bb["append_atk_scale"]
		if !ok {
			return cfg, fmt.Errorf("missing append_atk_scale in wisdel s1")
		}
		cfg.S1AppendAtkScale = val
		val, ok = bb["stun_duration"]
		if !ok {
			return cfg, fmt.Errorf("missing stun_duration in wisdel s1")
		}
		cfg.S1StunDuration = val

	case 2:
		val, ok := bb["atk"]
		if !ok {
			return cfg, fmt.Errorf("missing atk in wisdel s2")
		}
		cfg.S2Atk = val
		val, ok = bb["base_attack_time"]
		if !ok {
			return cfg, fmt.Errorf("missing base_attack_time in wisdel s2")
		}
		cfg.S2BaseAttackTime = val
		val, ok = bb["attack@atk_scale_ol"]
		if !ok {
			return cfg, fmt.Errorf("missing attack@atk_scale_ol in wisdel s2")
		}
		cfg.S2AtkScaleOl = val

	case 3:
		val, ok := bb["atk"]
		if !ok {
			return cfg, fmt.Errorf("missing atk in wisdel s3")
		}
		cfg.S3Atk = val
		val, ok = bb["attack@atk_scale_3"]
		if !ok {
			return cfg, fmt.Errorf("missing attack@atk_scale_3 in wisdel s3")
		}
		cfg.S3AtkScale3 = val
		val, ok = bb["attack@prob"]
		if !ok {
			return cfg, fmt.Errorf("missing attack@prob in wisdel s3")
		}
		cfg.S3Prob = val
		val, ok = bb["attack@trigger_time"]
		if !ok {
			return cfg, fmt.Errorf("missing attack@trigger_time in wisdel s3")
		}
		cfg.S3TriggerTime = int(val)
		val, ok = bb["base_attack_time"]
		if !ok {
			return cfg, fmt.Errorf("missing base_attack_time in wisdel s3")
		}
		cfg.S3BaseAttackTime = val
		val, ok = bb["max_cnt"]
		if !ok {
			return cfg, fmt.Errorf("missing max_cnt in wisdel s3")
		}
		cfg.S3MaxCnt = int(val)
		if spVal, ok := bb["sp"]; ok {
			cfg.S3SpParam = spVal
		}
	}

	// 2. Talent 1 blackboard (from base talent)
	for _, t := range s.Talents {
		if t.Group == 0 {
			tbb, err := wisdelStrictBB(t.Raw)
			if err != nil {
				return cfg, err
			}
			if v, ok := tbb["attack@main_atk_scale"]; ok {
				cfg.TalentMainAtkScale = v
			}
			if v, ok := tbb["attack@bomb_atk_scale"]; ok {
				cfg.TalentBombAtkScale = v
			}
			if v, ok := tbb["attack@prob"]; ok {
				cfg.TalentBombProb = v
			}
			if v, ok := tbb["attack@stun"]; ok {
				cfg.TalentBombStun = v
			}
			if v, ok := tbb["attack@range_radius"]; ok {
				cfg.TalentBombRadius = v
			}
		}
	}

	// 3. Module candidate overrides (trait + talent 1 upgrades)
	for _, rawCand := range s.ModuleCandidates {
		mbb, err := wisdelStrictBB(rawCand)
		if err != nil {
			return cfg, err
		}
		if v, ok := mbb["attack@enable_third_attack"]; ok && v > 0 {
			cfg.EnableThirdAttack = true
		}
		if v, ok := mbb["attack@append_atk_scale"]; ok {
			cfg.AppendAtkScale = v
		}
		if v, ok := mbb["attack@main_atk_scale"]; ok {
			cfg.TalentMainAtkScale = v
		}
		if v, ok := mbb["attack@bomb_atk_scale"]; ok {
			cfg.TalentBombAtkScale = v
		}
		if v, ok := mbb["attack@stun"]; ok {
			cfg.TalentBombStun = v
		}
		if v, ok := mbb["attack@range_radius"]; ok {
			cfg.TalentBombRadius = v
		}
	}

	// 4. Token Skill (魂灵之影)
	if s.TokenSkill != nil && len(s.TokenSkill.Raw) > 0 {
		tokbb, err := wisdelStrictBB(s.TokenSkill.Raw)
		if err == nil {
			if v, ok := tokbb["sluggish"]; ok {
				cfg.WardSluggish = v
			}
			if v, ok := tokbb["sp_min"]; ok {
				cfg.WardSpMin = v
			}
			if v, ok := tokbb["sp_max"]; ok {
				cfg.WardSpMax = v
			}
		}
	}

	return cfg, nil
}
