package main

import (
	"encoding/json"
	"fmt"
)

// shuS2SpecialIntervalBonus 是技能二「嘉禾盈仓」备注里写的**增量**。
//
// PRTS 黍页（revision 442689）技能二备注原文：「『特殊间隔』指攻击间隔1.3+1.3」。
// 前一个 1.3 是技能黑板 `base_attack_time`（技能期间的攻击间隔，已进
// `profile.Interval`）；这里只写**增量** 1.3，所以实际间隔是
// 「当前攻击间隔 + 1.3」，不是把 2.6 直接写成常量。
const shuS2SpecialIntervalBonus = 1.3

// ShuRuntimeConfig 把黍的全部黑板键解析成强类型字段。
//
// 数值**全部来自 raw 原文**：天赋读 `spec.Talents` 的候选 raw、模组读
// `ModuleCandidates` 与 `TraitOverride`、技能读 `OperatorSkill.Raw`。
// 这里不放任何一个写死的数——`buildShuSourceSpec` 与配置层是同一份证据链，
// 换精英/潜能/模组等级只改输入，不改代码。
type ShuRuntimeConfig struct {
	// ---- 天赋一「百谷长青」 ----
	// 治疗干员时对其与周围四格播种：每秒恢复 SowRecoveryPerSec 生命、
	// 获得 SowProtect 比例的庇护（伤害减免）。
	SowRecoveryPerSec float64 `json:"sow_recovery_per_sec"`
	SowProtect        float64 `json:"sow_protect"`
	// BornSow 是模组三级的「部署时立即给所处地块播种该效果」。
	BornSow bool `json:"born_sow"`

	// ---- 天赋二「天有四时」（E2 解锁） ----
	SeasonEnabled           bool    `json:"season_enabled"`
	SeasonProfessionCount   int     `json:"season_profession_count"`
	SeasonMaxHPRatio        float64 `json:"season_max_hp_ratio"`
	SeasonSameProfessionCnt int     `json:"season_same_profession_count"`
	SeasonAspd              float64 `json:"season_aspd"`
	SeasonSuiDeployCount    int     `json:"season_sui_deploy_count"`
	SeasonAtkRatio          float64 `json:"season_atk_ratio"`
	SeasonSPInterval        float64 `json:"season_sp_interval"`
	SeasonSPAmount          float64 `json:"season_sp_amount"`
	// SeasonBonusAtkRatio 是 Y 模组 talentIndex=-1 的额外攻击力（+3%/+5%），
	// 触发条件是「三条件达成两种及以上」。
	SeasonBonusAtkRatio float64 `json:"season_bonus_atk_ratio"`

	// ---- 模组对职业特性的覆写 ----
	// 「治疗生命值低于 LowHealRatio 的友方单位时治疗量提升 LowHealScale」。
	LowHealRatio float64 `json:"low_heal_ratio"`
	LowHealScale float64 `json:"low_heal_scale"`
	// TraitDamageResistance 是 Y 模组特性覆写的「受到的伤害减少 N%」。
	// 数据没写减伤对象（自身/全体），只存字段、暂不参与结算。
	TraitDamageResistance float64 `json:"trait_damage_resistance"`

	// ---- 当前技能（按 Slot 解码） ----
	Slot         int     `json:"slot"`
	SkillLevel   int     `json:"skill_level"`
	SPType       string  `json:"sp_type"`
	SPCost       int     `json:"sp_cost"`
	InitSP       int     `json:"init_sp"`
	MaxCharge    int     `json:"max_charge"`
	Duration     float64 `json:"duration"`
	SkillRangeID string  `json:"skill_range_id"`
	// SkillRangeCells 是技能范围的**相对格**（来自 range_table 的 grids，
	// 坐标为 `[col,row]`，与项目「朝右」口径一致）。技能一「化被草木」的
	// 治疗范围与技能二/三的治疗范围都靠它，不在这里手写格子。
	SkillRangeCells [][2]int `json:"skill_range_cells,omitempty"`

	// 一技能「化被草木」：下一次攻击为周围血量不足一半的一名友方恢复
	// 攻击力 × S1HealScale 的生命，可充能 S1Charges 次。
	S1HealScale float64 `json:"s1_heal_scale"`
	S1Charges   int     `json:"s1_charges"`

	// 二技能「嘉禾盈仓」：停止攻击，专注治疗范围内至多 S2MaxTarget 名友方，
	// 攻击力 +(S2AtkRatio)，阻挡 +S2BlockBonus，第一天赋效果 ×S2TalentScale，
	// 治疗间隔 S2HealInterval。
	S2AtkRatio     float64 `json:"s2_atk_ratio"`
	S2BlockBonus   int     `json:"s2_block_bonus"`
	S2MaxTarget    int     `json:"s2_max_target"`
	S2HealInterval float64 `json:"s2_heal_interval"`
	S2TalentScale  float64 `json:"s2_talent_scale"`

	// 三技能「离离枯荣」：治疗范围扩大，攻击同时治疗友方，攻击力 +(S3AtkRatio)；
	// 有地面敌人处于播种地块时技能范围内友方攻击力 +(S3EnemyAtk)、攻速 +(S3EnemyAspd)；
	// 敌人经过播种地块获得效果，远离该地块超过 S3MaxDistance 格时被传送回该地块。
	S3AtkRatio    float64 `json:"s3_atk_ratio"`
	S3EnemyAtk    float64 `json:"s3_enemy_atk"`
	S3EnemyAspd   float64 `json:"s3_enemy_aspd"`
	S3MaxDistance float64 `json:"s3_max_distance"`

	// ---- 审计 ----
	// ConsumedKeys 是被本层显式消费的黑板键（供测试逐键断言）。
	ConsumedKeys []string `json:"consumed_keys"`
	// UnusedKeys 是黑板上出现过、却没有任何运行期消费者的键。它们会被
	// `shuRemainingGaps` 具名登记成机制缺口——不静默忽略。
	UnusedKeys []string `json:"unused_keys"`
	// Unresolved 记录证据不足以定死的语义（例如传送触发频率）。
	Unresolved []string `json:"unresolved"`
}

type rawBBItem struct {
	Key      string   `json:"key"`
	Value    *float64 `json:"value"`
	ValueStr *string  `json:"valueStr"`
}

func parseRawBlackboard(raw json.RawMessage) (map[string]float64, map[string]string, error) {
	var items []rawBBItem
	if err := json.Unmarshal(raw, &items); err != nil {
		return nil, nil, err
	}
	nums := make(map[string]float64, len(items))
	strs := make(map[string]string, len(items))
	for _, it := range items {
		if it.Value != nil {
			nums[it.Key] = *it.Value
		}
		if it.ValueStr != nil {
			strs[it.Key] = *it.ValueStr
		}
	}
	return nums, strs, nil
}

func rawBlackboardOf(raw json.RawMessage) (map[string]float64, map[string]string, error) {
	var v struct {
		Blackboard json.RawMessage `json:"blackboard"`
	}
	if err := json.Unmarshal(raw, &v); err != nil {
		return nil, nil, err
	}
	if len(v.Blackboard) == 0 {
		return map[string]float64{}, map[string]string{}, nil
	}
	return parseRawBlackboard(v.Blackboard)
}

func talentNameOf(raw json.RawMessage) (string, error) {
	var v struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(raw, &v); err != nil {
		return "", err
	}
	return v.Name, nil
}

// consume 记录一个被消费的键名（只在它真的出现在黑板上时登记）。
func (c *ShuRuntimeConfig) consume(nums map[string]float64, strs map[string]string, keys ...string) map[string]bool {
	used := map[string]bool{}
	for _, k := range keys {
		_, hasNum := nums[k]
		_, hasStr := strs[k]
		if !hasNum && !hasStr {
			continue
		}
		used[k] = true
		c.ConsumedKeys = append(c.ConsumedKeys, k)
	}
	return used
}

func (c *ShuRuntimeConfig) auditBlackboard(nums map[string]float64, strs map[string]string, used map[string]bool) {
	for k := range nums {
		if !used[k] {
			c.UnusedKeys = append(c.UnusedKeys, k)
		}
	}
	for k := range strs {
		if !used[k] {
			c.UnusedKeys = append(c.UnusedKeys, k)
		}
	}
}

func decodeShuRuntimeConfig(s *ShuSourceSpec) (*ShuRuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("shu config: nil spec")
	}
	cfg := &ShuRuntimeConfig{Slot: s.Slot, SkillLevel: s.SkillLevel}

	// ---- 1. 天赋：按名字取原文，再按键解析 ----
	talentBy := map[string]json.RawMessage{}
	for _, t := range s.Talents {
		name, err := talentNameOf(t.Raw)
		if err != nil {
			return nil, fmt.Errorf("shu config: talent raw: %w", err)
		}
		talentBy[name] = t.Raw
	}
	if raw, ok := talentBy["百谷长青"]; ok {
		nums, strs, err := rawBlackboardOf(raw)
		if err != nil {
			return nil, fmt.Errorf("shu config: 百谷长青: %w", err)
		}
		used := cfg.consume(nums, strs, "hp_recovery_per_sec", "damage_resistance")
		cfg.SowRecoveryPerSec = nums["hp_recovery_per_sec"]
		cfg.SowProtect = nums["damage_resistance"]
		cfg.auditBlackboard(nums, strs, used)
	} else if s.Elite >= 1 {
		// 精英 0 没有天赋（百谷长青的解锁阶段是 PHASE_1）；精英 1 起缺失
		// 就是数据缺口，不能当成"没这条天赋"。
		return nil, fmt.Errorf("shu config: 百谷长青 missing at E%dP%d", s.Elite, s.Potential)
	}
	if raw, ok := talentBy["天有四时"]; ok {
		nums, strs, err := rawBlackboardOf(raw)
		if err != nil {
			return nil, fmt.Errorf("shu config: 天有四时: %w", err)
		}
		used := cfg.consume(nums, strs, "max_hp", "attack_speed", "atk", "interval", "sp")
		cfg.SeasonEnabled = true
		cfg.SeasonProfessionCount = 3
		cfg.SeasonMaxHPRatio = nums["max_hp"]
		cfg.SeasonSameProfessionCnt = 3
		cfg.SeasonAspd = nums["attack_speed"]
		cfg.SeasonSuiDeployCount = 4
		cfg.SeasonAtkRatio = nums["atk"]
		cfg.SeasonSPInterval = nums["interval"]
		cfg.SeasonSPAmount = nums["sp"]
		cfg.auditBlackboard(nums, strs, used)
	}

	// ---- 2. 模组：天赋改写（覆盖天赋一）与特性覆写 ----
	for _, mc := range s.ModuleCandidates {
		nums, strs, err := rawBlackboardOf(mc)
		if err != nil {
			return nil, fmt.Errorf("shu config: module talent: %w", err)
		}
		used := cfg.consume(nums, strs, "hp_recovery_per_sec", "damage_resistance", "born_range_id")
		if v, ok := nums["hp_recovery_per_sec"]; ok {
			cfg.SowRecoveryPerSec = v
		}
		if v, ok := nums["damage_resistance"]; ok {
			cfg.SowProtect = v
		}
		if _, ok := strs["born_range_id"]; ok {
			// 模组的 `born_range_id=0-1` = 部署时给**所处地块**（自身格）播种。
			cfg.BornSow = true
		}
		cfg.auditBlackboard(nums, strs, used)
	}
	// Y 模组：第二天赋「天有四时」的改写（talentIndex=1）。
	//
	// 候选来自 `parts[].addOrOverrideTalentDataBundle.candidates[talentIndex=1]`，
	// 覆盖同一组键（max_hp/attack_speed/atk/interval/sp）。它与 X 模组的天赋一
	// 改写是**两个不同的天赋组**，所以不能写进同一条覆盖链。
	for _, mc := range s.ModuleSeasonCandidates {
		nums, strs, err := rawBlackboardOf(mc)
		if err != nil {
			return nil, fmt.Errorf("shu config: module season talent: %w", err)
		}
		used := cfg.consume(nums, strs, "max_hp", "attack_speed", "atk", "interval", "sp")
		cfg.SeasonEnabled = true
		cfg.SeasonProfessionCount = 3
		cfg.SeasonSameProfessionCnt = 3
		cfg.SeasonSuiDeployCount = 4
		if v, ok := nums["max_hp"]; ok {
			cfg.SeasonMaxHPRatio = v
		}
		if v, ok := nums["attack_speed"]; ok {
			cfg.SeasonAspd = v
		}
		if v, ok := nums["atk"]; ok {
			cfg.SeasonAtkRatio = v
		}
		if v, ok := nums["interval"]; ok {
			cfg.SeasonSPInterval = v
		}
		if v, ok := nums["sp"]; ok {
			cfg.SeasonSPAmount = v
		}
		cfg.auditBlackboard(nums, strs, used)
	}

	// Y 模组：talentIndex=-1 的隐藏候选（黑板只有 atk）。
	//
	// 数值与天赋描述「上述三个条件达成两种或以上时，则额外使所有干员
	// 攻击力+3%/+5%」一一对应；但"三种条件达成两种"这个**触发条件**
	// 只写在 upgradeDescription 里、不在黑板键上，判定点（何时判、是否
	// 与三条件同帧）数据未明写——按条件性加成消费，语义登记待裁定。
	if len(s.ModuleConditionalAtk) > 0 {
		nums, strs, err := rawBlackboardOf(s.ModuleConditionalAtk)
		if err != nil {
			return nil, fmt.Errorf("shu config: module conditional atk: %w", err)
		}
		used := cfg.consume(nums, strs, "atk")
		cfg.SeasonBonusAtkRatio = nums["atk"]
		cfg.auditBlackboard(nums, strs, used)
		cfg.Unresolved = append(cfg.Unresolved,
			"Y 模组 talentIndex=-1 候选：黑板只有 atk，数值与「三条件达成两种及以上额外攻击力 +3%/+5%」一一对应；触发条件只写在 upgradeDescription，判定点（何时判）数据未明写，按与三条件同帧重算")
	}

	if len(s.TraitOverride) > 0 {
		nums, strs, err := rawBlackboardOf(s.TraitOverride)
		if err != nil {
			return nil, fmt.Errorf("shu config: module trait: %w", err)
		}
		used := cfg.consume(nums, strs, "heal_scale", "hp_ratio", "damage_resistance")
		cfg.LowHealScale = nums["heal_scale"]
		cfg.LowHealRatio = nums["hp_ratio"]
		if v, ok := nums["damage_resistance"]; ok {
			// Y 模组的特性覆写：「受到的伤害减少 15%」。减伤的对象（自身 /
			// 全体）数据里没写主语，只存字段、暂不消费（待裁定）。
			cfg.TraitDamageResistance = v
			cfg.Unresolved = append(cfg.Unresolved,
				"Y 模组特性覆写「受到的伤害减少 15%」未写减伤对象（自身/全体），只存字段、暂不参与结算")
		}
		cfg.auditBlackboard(nums, strs, used)
	}

	// ---- 3. 技能 ----
	if len(s.OperatorSkill.Raw) == 0 {
		return nil, fmt.Errorf("shu config: empty operator skill raw")
	}
	var sk struct {
		SPData struct {
			SPType        string `json:"spType"`
			SPCost        int    `json:"spCost"`
			InitSP        int    `json:"initSp"`
			MaxChargeTime int    `json:"maxChargeTime"`
		} `json:"spData"`
		Duration   *float64        `json:"duration"`
		RangeID    string          `json:"rangeId"`
		Blackboard json.RawMessage `json:"blackboard"`
	}
	if err := json.Unmarshal(s.OperatorSkill.Raw, &sk); err != nil {
		return nil, fmt.Errorf("shu config: failed unmarshal skill raw: %w", err)
	}
	cfg.SPType = sk.SPData.SPType
	cfg.SPCost = sk.SPData.SPCost
	cfg.InitSP = sk.SPData.InitSP
	cfg.MaxCharge = sk.SPData.MaxChargeTime
	if cfg.MaxCharge < 1 {
		cfg.MaxCharge = 1
	}
	if sk.Duration != nil {
		cfg.Duration = *sk.Duration
	}
	cfg.SkillRangeID = sk.RangeID
	if cfg.SkillRangeID != "" {
		ranges, err := shuRawRecords("range_table", cfg.SkillRangeID)
		if err != nil {
			return nil, fmt.Errorf("shu config: range %s: %w", cfg.SkillRangeID, err)
		}
		var r struct {
			Grids []struct {
				Row int `json:"row"`
				Col int `json:"col"`
			} `json:"grids"`
		}
		if err := json.Unmarshal(ranges[cfg.SkillRangeID], &r); err != nil {
			return nil, fmt.Errorf("shu config: range %s: %w", cfg.SkillRangeID, err)
		}
		for _, g := range r.Grids {
			cfg.SkillRangeCells = append(cfg.SkillRangeCells, [2]int{g.Col, g.Row})
		}
	}

	nums, strs, err := parseRawBlackboard(sk.Blackboard)
	if err != nil {
		return nil, fmt.Errorf("shu config: failed parse skill blackboard: %w", err)
	}
	switch s.Slot {
	case 1:
		used := cfg.consume(nums, strs, "heal_scale", "ct")
		cfg.S1HealScale = nums["heal_scale"]
		cfg.S1Charges = int(nums["ct"])
		if cfg.S1Charges < 1 {
			cfg.S1Charges = cfg.MaxCharge
		}
		cfg.auditBlackboard(nums, strs, used)
	case 2:
		used := cfg.consume(nums, strs, "atk", "extra_extend_scale", "block_cnt", "attack@max_target", "base_attack_time")
		cfg.S2AtkRatio = nums["atk"]
		cfg.S2TalentScale = nums["extra_extend_scale"]
		cfg.S2BlockBonus = int(nums["block_cnt"])
		cfg.S2MaxTarget = int(nums["attack@max_target"])
		if cfg.S2MaxTarget == 0 {
			return nil, fmt.Errorf("shu config: 嘉禾盈仓 attack@max_target missing")
		}
		cfg.S2HealInterval = nums["base_attack_time"]
		if cfg.S2HealInterval == 0 {
			return nil, fmt.Errorf("shu config: 嘉禾盈仓 base_attack_time missing")
		}
		cfg.auditBlackboard(nums, strs, used)
	case 3:
		used := cfg.consume(nums, strs, "atk", "e_atk", "e_attack_speed", "max_distance", "e_max_stack_cnt")
		cfg.S3AtkRatio = nums["atk"]
		cfg.S3EnemyAtk = nums["e_atk"]
		cfg.S3EnemyAspd = nums["e_attack_speed"]
		cfg.S3MaxDistance = nums["max_distance"]
		if cfg.S3MaxDistance <= 0 {
			return nil, fmt.Errorf("shu config: 离离枯荣 max_distance missing")
		}
		// e_max_stack_cnt = 效果层数上限（1）：同一名敌人只保留一个锚点，
		// 不叠加。运行期用它作"每敌至多一个锚点"的上限。
		cfg.auditBlackboard(nums, strs, used)
	default:
		return nil, fmt.Errorf("shu config: unsupported slot %d", s.Slot)
	}

	// 传送的触发频率（传送后是否重新建锚、能否再次触发）在 gamedata 里
	// 没有第二个键可判，PRTS 正文也只写"被传送回该地块"。这里按"传送后
	// 锚点消耗、可重新获得"建模，并把该语义登记为待证。
	if s.Slot == 3 {
		cfg.Unresolved = append(cfg.Unresolved,
			"传送触发频率：传送后是否重新建立锚点、能否再次触发，只有行为证据可判；当前按「传送后锚点消耗、再次经过可重新获得」建模")
	}

	return cfg, nil
}
