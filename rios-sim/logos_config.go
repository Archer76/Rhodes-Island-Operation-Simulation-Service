package main

import (
	"encoding/json"
	"fmt"
)

// LogosRuntimeConfig 把逻各斯的全部黑板键解析为强类型字段。
// 遵循零硬编码原则，全部数值来自 gamedata 原文。
type LogosRuntimeConfig struct {
	// ---- 天赋一「语汇演化」（E1 解锁） ----
	//
	// 博士 2026-10-25 裁定 V-2 之后，这一族按下述口径消费：
	//   - `prob`：**精确抽样**的伯努利判定（每击一次，seed 来自规格）；
	//   - `atk_scale`：命中时那一笔额外法术伤害的倍率；
	//   - `sluggish`：命中时给目标的**停顿秒数**（减速比例是全局常数 80%）；
	//   - `emit_count`（模组Y）：一次命中挑几个**不同**目标；
	//   - `element_atk_scale`（模组X）：需要「目标处于凋亡损伤爆发期间」，
	//     条件判不出来 ⇒ 具名缺口（概率那一半不受影响）。
	Talent1Enabled      bool    `json:"talent1_enabled"`
	Talent1Prob         float64 `json:"talent1_prob"`
	Talent1AtkScale     float64 `json:"talent1_atk_scale"`
	Talent1Sluggish     float64 `json:"talent1_sluggish"`
	Talent1ElementScale float64 `json:"talent1_element_atk_scale"` // 模组X提供
	Talent1EmitCount    int     `json:"talent1_emit_count"`        // 模组Y提供，默认为 1

	// ---- 天赋二「剜魂具辞」（E2 解锁） ----
	Talent2Enabled       bool    `json:"talent2_enabled"`
	Talent2Duration      float64 `json:"talent2_duration"`
	Talent2MagicResDelta float64 `json:"talent2_magic_resistance"` // 削弱法抗，如 -10
	Talent2AtkAddition   float64 `json:"talent2_atk_addition"`     // 受到的法伤提高加成，如 150/165

	// ---- 模组特性覆写 ----
	ModTraitEPDamageRatio float64 `json:"mod_trait_ep_damage_ratio"` // 模组X: 附带 8% 凋亡损伤
	ModTraitSP            int     `json:"mod_trait_sp"`              // 模组Y: 命中精英/领袖回 1 点技力

	// ---- 技能公共字段 ----
	Slot            int      `json:"slot"`
	SkillLevel      int      `json:"skill_level"`
	SPType          string   `json:"sp_type"`
	SPCost          int      `json:"sp_cost"`
	InitSP          int      `json:"init_sp"`
	Duration        float64  `json:"duration"`
	SkillRangeID    string   `json:"skill_range_id"`
	SkillRangeCells [][2]int `json:"skill_range_cells,omitempty"`

	// ---- 技能一「殁亡」 ----
	S1AtkRatio     float64 `json:"s1_atk_ratio"`      // atk: 攻击力增加比例 (如 1.0)
	S1KillAtkScale float64 `json:"s1_kill_atk_scale"` // attack@kill_atk_scale: 斩杀阈值乘数 (如 1.5)
	S1KillDamage   float64 `json:"s1_kill_damage"`    // attack@kill_damage: 9999999

	// ---- 技能二「提喻」 ----
	S2MagicRes       float64 `json:"s2_magic_resistance"`       // magic_resistance: +70
	S2Cooldown       float64 `json:"s2_attack_cooldown"`        // attack@cooldown: 0.5s 一次
	S2AtkScaleBase   float64 `json:"s2_attack_atk_scale_base"`  // attack@atk_scale_base: 0.75
	S2AtkScaleDelta  float64 `json:"s2_attack_atk_scale_delta"` // attack@atk_scale_delta: 0.15
	S2MoveSpeedDelta float64 `json:"s2_attack_move_speed"`      // attack@move_speed: -0.06
	S2MaxStackCnt    int     `json:"s2_attack_max_stack_cnt"`   // attack@max_stack_cnt: 10

	// ---- 技能三「延异视阈」 ----
	S3AtkRatio            float64 `json:"s3_atk_ratio"`             // atk: +3.0
	S3MaxTarget           int     `json:"s3_attack_max_target"`     // attack@max_target: 4
	S3ProjectileMoveScale float64 `json:"s3_projectile_move_scale"` // projectile_move_scale: 0.05

	// ---- 审计 ----
	ConsumedKeys []string `json:"consumed_keys"`
	UnusedKeys   []string `json:"unused_keys"`
	Unresolved   []string `json:"unresolved"`
}

func (c *LogosRuntimeConfig) consume(nums map[string]float64, strs map[string]string, keys ...string) map[string]bool {
	used := map[string]bool{}
	for _, k := range keys {
		if _, ok := nums[k]; ok {
			used[k] = true
			c.ConsumedKeys = append(c.ConsumedKeys, k)
		}
		if _, ok := strs[k]; ok {
			used[k] = true
			c.ConsumedKeys = append(c.ConsumedKeys, k)
		}
	}
	return used
}

func (c *LogosRuntimeConfig) auditBlackboard(nums map[string]float64, strs map[string]string, used map[string]bool) {
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

// decodeLogosRuntimeConfig 从 LogosSourceSpec 的 gamedata 原文中解析出强类型运行期配置
func decodeLogosRuntimeConfig(s *LogosSourceSpec) (*LogosRuntimeConfig, error) {
	if s == nil {
		return nil, fmt.Errorf("logos config: source is nil")
	}
	cfg := &LogosRuntimeConfig{
		Slot:             s.Slot,
		SkillLevel:       s.SkillLevel,
		Talent1EmitCount: 1, // 默认 1，模组可升级至 2
	}

	// 1. 解析天赋
	for _, t := range s.Talents {
		var cand struct {
			Name       string          `json:"name"`
			Blackboard json.RawMessage `json:"blackboard"`
		}
		if err := json.Unmarshal(t.Raw, &cand); err != nil {
			return nil, fmt.Errorf("logos config: unmarshal talent candidate: %w", err)
		}
		nums, strs, err := parseRawBlackboard(cand.Blackboard)
		if err != nil {
			return nil, fmt.Errorf("logos config: parse talent blackboard: %w", err)
		}
		switch t.Group {
		case 0: // 天赋一：语汇演化
			cfg.Talent1Enabled = true
			used := cfg.consume(nums, strs, "prob", "atk_scale", "sluggish")
			cfg.Talent1Prob = nums["prob"]
			cfg.Talent1AtkScale = nums["atk_scale"]
			cfg.Talent1Sluggish = nums["sluggish"]
			cfg.auditBlackboard(nums, strs, used)
		case 1: // 天赋二：剜魂具辞
			cfg.Talent2Enabled = true
			used := cfg.consume(nums, strs, "duration", "magic_resistance", "atk_addition")
			cfg.Talent2Duration = nums["duration"]
			cfg.Talent2MagicResDelta = nums["magic_resistance"]
			cfg.Talent2AtkAddition = nums["atk_addition"]
			cfg.auditBlackboard(nums, strs, used)
		}
	}

	// 2. 解析模组改写（若存在）
	for _, mc := range s.ModuleCandidates {
		var cand struct {
			Blackboard json.RawMessage `json:"blackboard"`
		}
		if err := json.Unmarshal(mc, &cand); err != nil {
			continue
		}
		nums, strs, err := parseRawBlackboard(cand.Blackboard)
		if err != nil {
			continue
		}
		// 模组对天赋一的改写
		if _, ok := nums["prob"]; ok {
			used := cfg.consume(nums, strs, "prob", "atk_scale", "sluggish", "element_atk_scale", "emit_count")
			cfg.Talent1Prob = nums["prob"]
			cfg.Talent1AtkScale = nums["atk_scale"]
			cfg.Talent1Sluggish = nums["sluggish"]
			if v, ok := nums["element_atk_scale"]; ok {
				cfg.Talent1ElementScale = v
			}
			if v, ok := nums["emit_count"]; ok {
				cfg.Talent1EmitCount = int(v)
			}
			cfg.auditBlackboard(nums, strs, used)
		}
		// 模组隐藏天赋：凋亡损伤比例 ep_damage_ratio
		if v, ok := nums["ep_damage_ratio"]; ok {
			used := cfg.consume(nums, strs, "ep_damage_ratio")
			cfg.ModTraitEPDamageRatio = v
			cfg.auditBlackboard(nums, strs, used)
		}
	}

	// 模组特性覆写
	if len(s.TraitOverride) > 0 {
		var to struct {
			Blackboard json.RawMessage `json:"blackboard"`
		}
		if err := json.Unmarshal(s.TraitOverride, &to); err == nil {
			nums, strs, err := parseRawBlackboard(to.Blackboard)
			if err == nil {
				if v, ok := nums["sp"]; ok {
					used := cfg.consume(nums, strs, "sp")
					cfg.ModTraitSP = int(v)
					cfg.auditBlackboard(nums, strs, used)
				}
			}
		}
	}

	// 3. 解析技能
	var sk struct {
		RangeID    string          `json:"rangeId"`
		Duration   *float64        `json:"duration"`
		Blackboard json.RawMessage `json:"blackboard"`
		SPData     struct {
			SPType string `json:"spType"`
			SPCost int    `json:"spCost"`
			InitSP int    `json:"initSp"`
		} `json:"spData"`
	}
	if err := json.Unmarshal(s.OperatorSkill.Raw, &sk); err != nil {
		return nil, fmt.Errorf("logos config: unmarshal skill: %w", err)
	}

	cfg.SPType = sk.SPData.SPType
	cfg.SPCost = sk.SPData.SPCost
	cfg.InitSP = sk.SPData.InitSP
	if sk.Duration != nil {
		cfg.Duration = *sk.Duration
	}
	cfg.SkillRangeID = sk.RangeID
	if cfg.SkillRangeID != "" {
		ranges, err := logosRawRecords("range_table", cfg.SkillRangeID)
		if err != nil {
			return nil, fmt.Errorf("logos config: range %s: %w", cfg.SkillRangeID, err)
		}
		var r struct {
			Grids []struct {
				Row int `json:"row"`
				Col int `json:"col"`
			} `json:"grids"`
		}
		if err := json.Unmarshal(ranges[cfg.SkillRangeID], &r); err != nil {
			return nil, fmt.Errorf("logos config: range %s: %w", cfg.SkillRangeID, err)
		}
		for _, g := range r.Grids {
			cfg.SkillRangeCells = append(cfg.SkillRangeCells, [2]int{g.Col, g.Row})
		}
	}

	nums, strs, err := parseRawBlackboard(sk.Blackboard)
	if err != nil {
		return nil, fmt.Errorf("logos config: parse skill blackboard: %w", err)
	}

	switch s.Slot {
	case 1:
		used := cfg.consume(nums, strs, "atk", "attack@kill_atk_scale", "attack@kill_damage")
		cfg.S1AtkRatio = nums["atk"]
		cfg.S1KillAtkScale = nums["attack@kill_atk_scale"]
		cfg.S1KillDamage = nums["attack@kill_damage"]
		cfg.auditBlackboard(nums, strs, used)
	case 2:
		used := cfg.consume(nums, strs, "magic_resistance", "attack@cooldown", "attack@atk_scale_base", "attack@atk_scale_delta", "attack@move_speed", "attack@max_stack_cnt")
		cfg.S2MagicRes = nums["magic_resistance"]
		cfg.S2Cooldown = nums["attack@cooldown"]
		cfg.S2AtkScaleBase = nums["attack@atk_scale_base"]
		cfg.S2AtkScaleDelta = nums["attack@atk_scale_delta"]
		cfg.S2MoveSpeedDelta = nums["attack@move_speed"]
		cfg.S2MaxStackCnt = int(nums["attack@max_stack_cnt"])
		cfg.auditBlackboard(nums, strs, used)
	case 3:
		used := cfg.consume(nums, strs, "atk", "attack@max_target", "projectile_move_scale")
		cfg.S3AtkRatio = nums["atk"]
		cfg.S3MaxTarget = int(nums["attack@max_target"])
		cfg.S3ProjectileMoveScale = nums["projectile_move_scale"]
		cfg.auditBlackboard(nums, strs, used)
	default:
		return nil, fmt.Errorf("logos config: unsupported slot %d", s.Slot)
	}

	// 语义待证项：这些**不是**"机制没建"，是"建了但口径只有行为证据能定死"。
	// 它们落进机制文档的裁定栏，**不进 Gap 列表**——报成 Gap 会让整场拒跑，
	// 把"已建模但口径待核"错变成"不能模拟"。
	cfg.Unresolved = append(cfg.Unresolved,
		"天赋二「剜魂具辞」的时点：本次这一击的伤害先结算、减益作用于之后的伤害；"+
			"数据里没有第二个键能判「同一击是否享受到自己的减益」")
	cfg.Unresolved = append(cfg.Unresolved,
		"第一天赋「语汇演化」的抽样口径：每**普通出手**抽一次签（`prob`），命中后先在范围内定下 "+
			"`emit_count` 个互不重复的目标再逐个结算；技能二「提喻」的锁定伤害不是普攻，不抽这一支")
	cfg.Unresolved = append(cfg.Unresolved,
		"第一天赋「语汇演化」的「随机目标」是否排除本击的主目标：数据里没有第二个键可判；"+
			"当前候选池**包含**主目标（与「攻击范围内一个随机目标」的字面读法一致）")
	if s.Slot == 1 {
		cfg.Unresolved = append(cfg.Unresolved,
			"技能一「殁亡」的「另一个随机目标」：数据里没有种子也没有权重，本实现取敌人列表次序的第一个合格目标；"+
				"换成别的确定性次序会改判决")
		cfg.Unresolved = append(cfg.Unresolved,
			"技能一「殁亡」的转移伤害口径：与倒下单位生命值相等的数值先当作**法术伤害原值**，再走标准法术结算（法抗会削它）")
	}
	if s.Slot == 2 {
		cfg.Unresolved = append(cfg.Unresolved,
			"技能二「提喻」的层数时序：每 `attack@cooldown` 一拍先加一层再结算，因此第 10 拍（5.0 秒）达到倍率 "+
				"`base+delta×10` = 3 倍、移速 40%；「先结算后加层」会把满层推后一拍")
	}
	return cfg, nil
}
