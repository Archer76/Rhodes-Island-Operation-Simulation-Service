package main

import (
	"encoding/json"
	"fmt"
)

type lingRuntimeConfig struct {
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

	// 第一天赋「挑灯问梦」
	InventoryMax int // 初始持有召唤物数 (精0:3, 精1:4, 精2:5, +模组特性:3 = 8)
	FieldMax     int // 场上最大部署数 (基础3, 模组2/3级为4)

	// 第二天赋「随付笺咏醉屠苏」
	Talent2SP       float64 // 击倒/吸收/回收时获得 SP (精1: 2/3, 精2: 3/4)
	Talent2AtkRatio float64 // 每次攻击力加成比例 (精1: 0.02, 精2: 0.03)
	Talent2MaxStack int     // 最大层数 (5)

	// 技能 1「重进酒」
	S1AtkBuff   float64 // +atk
	S1ASPD      float64 // +attack_speed
	S1Duration  float64 // 25.0
	S1SupplyCnt int     // 1 (开启时获得)

	// 技能 2「笑鸣瑟」
	S2AtkScale       float64 // atk_scale
	S2Duration       float64 // 束缚时间 ling_s2_unmovable.duration
	S2MaxCharges     int     // 可充能次数 value
	S2RecycleHPRatio float64 // hp_ratio (0.5，低于此比例回收)
	S2SupplyCnt      int     // 1

	// 技能 3「宁作吾」
	S3AtkBuff      float64 // +atk
	S3DefBuff      float64 // +def
	S3PulseScale   float64 // atk_scale (0.2)
	S3PulseInterval float64 // interval (0.5)
	S3Duration     float64 // 20.0 ~ 30.0
	S3SupplyCnt    int     // 1 (结束时获得)

	// 弦惊合体倍率 (来自 sktok_ling_soul3 的 2.* 键)
	FusionHpMult       float64 // 2.max_hp (1.0 -> 基础属性 + 100% = 2.0x)
	FusionAtkMult      float64 // 2.atk (0.8 -> +80% = 1.8x)
	FusionDefMult      float64 // 2.def (0.8 -> +80% = 1.8x)
	FusionMagicResMult float64 // 2.magic_resistance (1.0 -> +100% = 2.0x)
	FusionAtkTimeMult  float64 // 2.base_attack_time (0.8 -> +80% = 1.8x)
	FusionBlockBonus   int     // 2.block_cnt (+2 -> 阻挡数从 2 变 4)
	FusionDeploySlots  int     // 占 2 个部署位
}

func lingStrictBB(raw json.RawMessage) (map[string]float64, error) {
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
			return nil, fmt.Errorf("invalid ling blackboard entry")
		}
		if _, ok := out[r.Key]; ok {
			return nil, fmt.Errorf("duplicate ling key %s", r.Key)
		}
		out[r.Key] = *r.Value
	}
	return out, nil
}

func decodeLingRuntimeConfig(s *LingSourceSpec) (lingRuntimeConfig, error) {
	if s == nil || s.Slot < 1 || s.Slot > 3 {
		return lingRuntimeConfig{}, fmt.Errorf("invalid ling source spec")
	}
	cfg := lingRuntimeConfig{
		Slot:              s.Slot,
		SkillLevel:        s.SkillLevel,
		TokenKey:          s.TokenKey,
		FusionDeploySlots: 2,
	}

	// 1. 读取召唤物基础属性 (来自 Evidence 中对应 token 的 Phase 数据)
	tokenRaw, ok := s.Evidence[s.TokenKey]
	if !ok {
		return cfg, fmt.Errorf("missing token evidence %s", s.TokenKey)
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
		return cfg, err
	}
	if s.Elite >= len(tokenChar.Phases) || len(tokenChar.Phases[s.Elite].AttributesKeyFrames) == 0 {
		return cfg, fmt.Errorf("missing token phase for E%d", s.Elite)
	}
	// 召唤物等级通常跟随干员等级（取最后一帧/对应帧；满级对齐 Phase 最后一帧或按等级比例）
	// 这里取对应 Phase 的关键帧属性
	frames := tokenChar.Phases[s.Elite].AttributesKeyFrames
	targetFrame := frames[len(frames)-1].Data
	for _, f := range frames {
		if f.Level <= s.Level {
			targetFrame = f.Data
		}
	}
	cfg.TokenMaxHp = targetFrame.MaxHp
	cfg.TokenAtk = targetFrame.Atk
	cfg.TokenDef = targetFrame.Def
	cfg.TokenMagicResist = targetFrame.MagicResistance
	cfg.TokenCost = targetFrame.Cost
	cfg.TokenBlockCnt = targetFrame.BlockCnt
	cfg.TokenBaseAtkTime = targetFrame.BaseAttackTime
	cfg.TokenMaxDeployCnt = targetFrame.MaxDeployCount

	// 2. 解析干员技能黑板
	bb, err := lingStrictBB(s.OperatorSkill.Raw)
	if err != nil {
		return cfg, err
	}
	var operSkillMeta struct {
		Duration float64 `json:"duration"`
	}
	_ = json.Unmarshal(s.OperatorSkill.Raw, &operSkillMeta)

	switch s.Slot {
	case 1:
		cfg.S1AtkBuff = bb["atk"]
		cfg.S1ASPD = bb["attack_speed"]
		cfg.S1Duration = operSkillMeta.Duration
		cfg.S1SupplyCnt = int(bb["cnt"])
	case 2:
		cfg.S2AtkScale = bb["atk_scale"]
		cfg.S2Duration = bb["ling_s2_unmovable.duration"]
		cfg.S2MaxCharges = int(bb["value"])
		cfg.S2RecycleHPRatio = bb["hp_ratio"]
		cfg.S2SupplyCnt = int(bb["cnt"])
	case 3:
		cfg.S3AtkBuff = bb["atk"]
		cfg.S3DefBuff = bb["def"]
		cfg.S3PulseScale = bb["atk_scale"]
		cfg.S3PulseInterval = bb["interval"]
		cfg.S3Duration = operSkillMeta.Duration
		cfg.S3SupplyCnt = int(bb["cnt"])

		// 解析召唤物技能合体黑板 (sktok_ling_soul3)
		tokBB, err := lingStrictBB(s.TokenSkill.Raw)
		if err != nil {
			return cfg, err
		}
		cfg.FusionHpMult = 1.0 + tokBB["2.max_hp"]
		cfg.FusionAtkMult = 1.0 + tokBB["2.atk"]
		cfg.FusionDefMult = 1.0 + tokBB["2.def"]
		cfg.FusionMagicResMult = 1.0 + tokBB["2.magic_resistance"]
		cfg.FusionAtkTimeMult = 1.0 + tokBB["2.base_attack_time"]
		cfg.FusionBlockBonus = int(tokBB["2.block_cnt"])
	}

	// 3. 解析第一天赋与第二天赋
	cfg.FieldMax = 3 // 默认同场最大部署数 3
	for _, t := range s.Talents {
		tbb, err := lingStrictBB(t.Raw)
		if err != nil {
			return cfg, err
		}
		if t.Group == 0 {
			// 第一天赋「挑灯问梦」
			cfg.InventoryMax = int(tbb["cnt"])
		} else if t.Group == 1 {
			// 第二天赋「随付笺咏醉屠苏」
			cfg.Talent2SP = tbb["sp"]
			cfg.Talent2AtkRatio = tbb["atk"]
			cfg.Talent2MaxStack = int(tbb["max_stack_cnt"])
		}
	}

	// 4. 解析模组加成（持有上限+3、部署上限+1、费用减免、属性加成）
	if s.Module != nil {
		var modPhase struct {
			EquipLevel              int `json:"equipLevel"`
			TokenAttributeBlackboard map[string][]struct {
				Key   string  `json:"key"`
				Value float64 `json:"value"`
			} `json:"tokenAttributeBlackboard"`
			Parts []struct {
				Target string `json:"target"`
				AddOrOverrideTalentDataBundle struct {
					Candidates []struct {
						Blackboard []struct {
							Key   string  `json:"key"`
							Value float64 `json:"value"`
						} `json:"blackboard"`
					} `json:"candidates"`
				} `json:"addOrOverrideTalentDataBundle"`
				OverrideTraitDataBundle struct {
					Candidates []struct {
						Blackboard []struct {
							Key   string  `json:"key"`
							Value float64 `json:"value"`
						} `json:"blackboard"`
					} `json:"candidates"`
				} `json:"overrideTraitDataBundle"`
			} `json:"parts"`
		}
		if err := json.Unmarshal(s.Module.Raw, &modPhase); err == nil {
			// 特性加成 (TRAIT): 持有上限 +cnt
			for _, part := range modPhase.Parts {
				if part.Target == "TRAIT" {
					for _, cand := range part.OverrideTraitDataBundle.Candidates {
						for _, r := range cand.Blackboard {
							if r.Key == "cnt" {
								cfg.InventoryMax += int(r.Value)
							}
						}
					}
				}
				// 模组对天赋的提升：Lv2/Lv3 时最多同时部署 4 个
				if part.Target == "TALENT_DATA_ONLY" {
					if modPhase.EquipLevel >= 2 {
						cfg.FieldMax = 4
					}
				}
			}

			// tokenAttributeBlackboard (费用减少与生命攻击白值)
			if tokenMods, ok := modPhase.TokenAttributeBlackboard[s.TokenKey]; ok {
				for _, r := range tokenMods {
					switch r.Key {
					case "cost":
						cfg.TokenCost += r.Value // e.g. -3 or -5
					case "max_hp":
						cfg.TokenMaxHp += r.Value
					case "atk":
						cfg.TokenAtk += r.Value
					}
				}
			}
		}
	}

	return cfg, nil
}
