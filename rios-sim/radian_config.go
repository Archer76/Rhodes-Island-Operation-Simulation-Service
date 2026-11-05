package main

import (
	"encoding/json"
	"fmt"
)

type radianRuntimeConfig struct {
	Slot       int
	SkillLevel int
	TokenKey   string

	// 基础召唤物属性与限制
	TokenMaxHp        float64
	TokenAtk          float64
	TokenDef          float64
	TokenMagicResist  float64
	TokenCost         float64
	TokenBlockCnt     int
	TokenBaseAtkTime  float64
	TokenMaxDeployCnt int

	// 第一天赋【卡带里的灵感】
	InventoryMax int // 初始持有召唤物数 (精0:3, 精1:4, 精2:5)
	FieldMax     int // 场上最大部署数 (3)

	// 第二天赋【加油~】
	Talent2HpRatio  float64 // 全队与召唤物生命提升比例 (0.12, 潜5: 0.15)
	Talent2DefRatio float64 // 全队与召唤物防御提升比例 (0.12, 潜5: 0.15)
	Talent2AtkRatio float64 // 全队与召唤物攻击提升比例 (0.12, 潜5: 0.15)

	// 技能一【律动线】
	S1DefBuff      float64 // +def (0.3 ~ 0.8)
	S1BarrierRatio float64 // hp_ratio (0.2 ~ 1.0)
	S1Duration     float64 // 25.0
	S1SupplyCnt    int     // 1

	// 技能二【环形鳄地】
	S2AtkBuff     float64 // +atk (0.2 ~ 0.8)
	S2BaseAtkTime float64 // base_attack_time
	S2Duration    float64 // 25.0
	S2SupplyCnt   int     // 1

	// 技能三【手牵手】
	S3AtkBuff               float64 // +atk (0.5 ~ 1.5)
	S3DamageScale           float64 // damage_scale (1.1 ~ 1.35)
	S3SluggishDuration      float64 // sluggish (2.0s)
	S3MagicFragileDuration  float64 // weak[magic][limit] (2.0s)
	S3Duration              float64 // 30.0
	S3SupplyCnt             int     // 1
}

func radianStrictBB(raw json.RawMessage) (map[string]float64, error) {
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
			return nil, fmt.Errorf("invalid radian blackboard entry")
		}
		if _, ok := out[r.Key]; ok {
			return nil, fmt.Errorf("duplicate radian key %s", r.Key)
		}
		out[r.Key] = *r.Value
	}
	return out, nil
}

func decodeRadianRuntimeConfig(s *RadianSourceSpec) (radianRuntimeConfig, error) {
	if s == nil || s.Slot < 1 || s.Slot > 3 {
		return radianRuntimeConfig{}, fmt.Errorf("invalid radian source spec")
	}
	cfg := radianRuntimeConfig{
		Slot:       s.Slot,
		SkillLevel: s.SkillLevel,
		TokenKey:   s.TokenKey,
		FieldMax:   3,
	}

	// 1. 读取召唤物基础属性 (来自 Evidence 中对应 token 的 Phase 数据)
	tokenRaw, ok := s.Evidence[s.TokenKey]
	if !ok {
		return radianRuntimeConfig{}, fmt.Errorf("missing token evidence for %s", s.TokenKey)
	}
	var tokenChar struct {
		Phases []struct {
			AttributesKeyFrames []struct {
				Level int `json:"level"`
				Data  struct {
					MaxHp           float64 `json:"maxHp"`
					Atk             float64 `json:"atk"`
					Def             float64 `json:"def"`
					MagicResistance float64 `json:"magicResistance"`
					Cost            float64 `json:"cost"`
					BlockCnt        int     `json:"blockCnt"`
					BaseAttackTime  float64 `json:"baseAttackTime"`
					MaxDeployCount  int     `json:"maxDeployCount"`
				} `json:"data"`
			} `json:"attributesKeyFrames"`
		} `json:"phases"`
	}
	if err := json.Unmarshal(tokenRaw, &tokenChar); err != nil {
		return radianRuntimeConfig{}, err
	}
	phaseIdx := s.Elite
	if phaseIdx >= len(tokenChar.Phases) {
		phaseIdx = len(tokenChar.Phases) - 1
	}
	p := tokenChar.Phases[phaseIdx]
	if len(p.AttributesKeyFrames) == 0 {
		return radianRuntimeConfig{}, fmt.Errorf("token %s has no keyframes", s.TokenKey)
	}
	// 取当前 Phase 最大等级帧作为标准召唤物属性
	targetFrame := p.AttributesKeyFrames[len(p.AttributesKeyFrames)-1].Data
	cfg.TokenMaxHp = targetFrame.MaxHp
	cfg.TokenAtk = targetFrame.Atk
	cfg.TokenDef = targetFrame.Def
	cfg.TokenMagicResist = targetFrame.MagicResistance
	cfg.TokenCost = targetFrame.Cost
	cfg.TokenBlockCnt = targetFrame.BlockCnt
	cfg.TokenBaseAtkTime = targetFrame.BaseAttackTime
	cfg.TokenMaxDeployCnt = targetFrame.MaxDeployCount
	if cfg.TokenMaxDeployCnt == 0 {
		cfg.TokenMaxDeployCnt = 3
	}

	// 2. 第一天赋【卡带里的灵感】库存
	cfg.InventoryMax = 3
	switch s.Elite {
	case 1:
		cfg.InventoryMax = 4
	case 2:
		cfg.InventoryMax = 5
	}
	for _, t := range s.Talents {
		if t.Group == 0 {
			bb, err := radianStrictBB(t.Raw)
			if err == nil {
				if v, ok := bb["cnt"]; ok {
					cfg.InventoryMax = int(v)
				}
			}
		}
	}

	// 3. 第二天赋【加油~】
	if s.Elite >= 2 {
		cfg.Talent2HpRatio = 0.12
		cfg.Talent2DefRatio = 0.12
		cfg.Talent2AtkRatio = 0.12
		if s.Potential >= 5 {
			cfg.Talent2HpRatio = 0.15
			cfg.Talent2DefRatio = 0.15
			cfg.Talent2AtkRatio = 0.15
		}
		for _, t := range s.Talents {
			if t.Group == 1 {
				bb, err := radianStrictBB(t.Raw)
				if err == nil {
					if v, ok := bb["max_hp"]; ok {
						cfg.Talent2HpRatio = v
					}
					if v, ok := bb["def"]; ok {
						cfg.Talent2DefRatio = v
					}
					if v, ok := bb["atk"]; ok {
						cfg.Talent2AtkRatio = v
					}
				}
			}
		}
	}

	// 4. 解析技能黑板
	skillBB, err := radianStrictBB(s.OperatorSkill.Raw)
	if err != nil {
		return radianRuntimeConfig{}, fmt.Errorf("decode operator skill blackboard: %w", err)
	}

	switch s.Slot {
	case 1:
		cfg.S1Duration = 25.0
		cfg.S1SupplyCnt = 1
		if v, ok := skillBB["def"]; ok {
			cfg.S1DefBuff = v
		}
		if v, ok := skillBB["hp_ratio"]; ok {
			cfg.S1BarrierRatio = v
		}
		if v, ok := skillBB["cnt"]; ok {
			cfg.S1SupplyCnt = int(v)
		}

	case 2:
		cfg.S2Duration = 25.0
		cfg.S2SupplyCnt = 1
		if v, ok := skillBB["atk"]; ok {
			cfg.S2AtkBuff = v
		}
		if v, ok := skillBB["base_attack_time"]; ok {
			cfg.S2BaseAtkTime = v
		}
		if v, ok := skillBB["cnt"]; ok {
			cfg.S2SupplyCnt = int(v)
		}

	case 3:
		cfg.S3Duration = 30.0
		cfg.S3SupplyCnt = 1
		if v, ok := skillBB["atk"]; ok {
			cfg.S3AtkBuff = v
		}
		if v, ok := skillBB["damage_scale"]; ok {
			cfg.S3DamageScale = v
		}
		if v, ok := skillBB["sluggish"]; ok {
			cfg.S3SluggishDuration = v
		}
		if v, ok := skillBB["weak[magic][limit]"]; ok {
			cfg.S3MagicFragileDuration = v
		}
		if v, ok := skillBB["cnt"]; ok {
			cfg.S3SupplyCnt = int(v)
		}
	}

	return cfg, nil
}
