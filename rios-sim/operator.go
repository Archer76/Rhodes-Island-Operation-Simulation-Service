package main

// operator.go：**Go 侧自己折算干员面板**（丙阶段三）。
//
// 对应 Python `ak_tactic/operator/stats.py`（`OperatorCalculator.stats`，`:537-613`）
// 与它依赖的四个纯函数：`interpolate_keyframes`(:219)、`_apply_rounding`(:206)、
// `_potential_bonus`(:273)、`module_levels`(:499)。
//
// ## 三条最容易写错的
//
//  1. ★ **取整要用银行家舍入**（`math.RoundToEven`），不是 `math.Round`。
//     两语言在 .5 上的判决相反（8.5 → Python 8 / Go 的 Round 是 9），
//     本项目为此专门记过一条（记忆 `7fb765b5`）。
//  2. **只对 `INT_ATTRS` 里的属性取整**；`magicResistance` / `moveSpeed` /
//     `attackSpeed` / `baseAttackTime` 是浮点，取整会把 0.7 的移速压成 0。
//  3. **信赖的 `trust` 参数已经是「显示值 ÷ 2」的内部标度**（0–100），
//     直接当 `favorKeyFrames` 的 level 用，**不要再除一次**。
//
// ## 本轮的边界
//
// 模组那一支（`module_levels`，读 `battle_equip_table.json`）**这一轮没接**——
// 那份表不在本机缓存里（`excel/` 下只有 character_table / skill_table /
// range_table / char_patch_table 四份）。它是对拍工具里的具名缺口，不静默略过。

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// intAttrs 是面板上按整数显示的属性（`stats.py:125-129`）。
var intAttrs = map[string]bool{
	"maxHp": true, "atk": true, "def": true, "cost": true, "blockCnt": true,
	"respawnTime": true, "maxDeployCount": true, "maxDeckStackCnt": true,
	"tauntLevel": true, "massLevel": true, "baseForceLevel": true,
}

// potentialAttrMap 是潜能 `attributeModifiers.attributeType` → 属性名
// （`stats.py:171-182`，全大写那套）。
var potentialAttrMap = map[string]string{
	"MAX_HP": "maxHp", "ATK": "atk", "DEF": "def",
	"MAGIC_RESISTANCE": "magicResistance", "COST": "cost",
	"ATTACK_SPEED": "attackSpeed", "RESPAWN_TIME": "respawnTime",
	"BLOCK_CNT": "blockCnt", "MOVE_SPEED": "moveSpeed",
	"MAX_DEPLOY_COUNT": "maxDeployCount",
}

// moduleKeyMap 是模组 `attributeBlackboard` 的 key（下划线风格）→ 属性名
// （`stats.py:158-168`）。本轮未接模组那一支，但这张表先留着——
// 它是契约的一部分，不是推测。
var moduleKeyMap = map[string]string{
	"max_hp": "maxHp", "atk": "atk", "def": "def",
	"magic_resistance": "magicResistance", "attack_speed": "attackSpeed",
	"cost": "cost", "respawn_time": "respawnTime",
	"block_cnt": "blockCnt", "move_speed": "moveSpeed",
}

// OperatorCalcConfig 是一次折算的入参。
type OperatorCalcConfig struct {
	CharID      string  `json:"char_id"`
	Elite       int     `json:"elite"`
	Level       int     `json:"level"`
	Trust       float64 `json:"trust"`
	Potential   int     `json:"potential"`
	Module      string  `json:"module"`
	ModuleLevel int     `json:"module_level"`
}

// OperatorStats 是一次折算的结果。
//
// 四份来源分开留着（与 `OperatorStats` 同构），对拍时逐份比——
// 只比 `total` 会让「base 错、抵消后 total 对」这种情形溜过去。
type OperatorStats struct {
	CharID string `json:"char_id"`
	//: 干员名（`stats.py:306` 的 `self.name = char.get("name") or char_id`）——
	//: 规格的 `name` 就是它（`_operator_spec` 的 `op.name or op.char_id`）。
	//: 与 `char_id` 同源、同一条 fallback，所以住在这里而不是调用方现查一次表。
	Name           string         `json:"name"`
	Elite          int            `json:"elite"`
	Level          int            `json:"level"`
	Trust          float64        `json:"trust"`
	Potential      int            `json:"potential"`
	Module         string         `json:"module"`
	ModuleLevel    int            `json:"module_level"`
	Base           map[string]any `json:"base"`
	TrustBonus     map[string]any `json:"trust_bonus"`
	PotentialBonus map[string]any `json:"potential_bonus"`
	ModuleBonus    map[string]any `json:"module_bonus"`
	Total          map[string]any `json:"total"`
	//: **天赋折进面板的那三个比例**（见 `talentpanel.go`）。没有天赋给面板加成时是 nil。
	//:
	//: 为什么要单独留一栏而不是让调用方去比 `total` 与 `base`：`total` 里同时还叠着
	//: 信赖／潜能／模组，**从 `total` 反推不出「天赋改了多少」**——而那正是本仓反复
	//: 要的那个「哪一件事真的发生了」。
	TalentPanelMods map[string]float64 `json:"talent_panel_mods,omitempty"`
	//: 攻速加成（天赋常驻 ＋ 模组特性改写，见 `operator_aspd.go`）。
	//: 匿名嵌入把 `aspd_flat` / `aspd_when_free` / `aspd_high_ground` 平铺出来——
	//: 与 `verify.py:326` 那三行同名，对拍要同形。
	AttackSpeedBonus
	//: 普攻连击（`operator_traits.go`）。**「没有这条」是 1 / 1.0，不是 0**。
	ComboAttack
	//: 天赋「强击瓶专家」（`operator_traits.go`）。**`scale` 的「没有这条」是 1.0**。
	PowerAttack
	//: 特性：生命流失速率 与 特性溅射的几何那一半（`operator_traits.go`）。
	//: 与 `verify.py:333/334/340` 的字段名同形；「没有这条」一律是 0。
	SplashRadius float64 `json:"splash_radius"`
	SplashScale  float64 `json:"splash_scale"`
	//: 天赋「汹涌怒火」叠上去的三项（`traits.py:251-270`）。**「没有这条」分别是
	//: 1.0 / 0.0 / 0.0**——`damage_scale` 的「没有」是 1.0 不是 0（它是乘数）。
	SplashDamageScale      float64 `json:"splash_damage_scale"`
	HighlandSplashScale    float64 `json:"highland_splash_scale"`
	HighlandSplashSluggish float64 `json:"highland_splash_sluggish"`
	HPDrainPerSec          float64 `json:"hp_drain_per_sec"`
	//: 特性「攻击附带停顿」的**秒数**（梓兰 凝滞师，特性黑板 `sluggish`）。
	//: ⚠ 减速比例不在这里——那是**全局常数** `sluggishSlowPct`＝80%（博士 2026-09-25 裁定）。
	TraitSlowSec float64 `json:"trait_slow_sec"`
	//: 特性「可以进行远程攻击，但攻击力降低至 v」的 **v**（领主那一族，月见夜）。
	//: ⚠ 判据是**目标有没有被她挡住**（博士 2026-09-25 裁定），不是格子几何。
	//: **「没有这条」是 1.0**（它是乘数，给 0 会让这位干员打不出伤害）。
	RangedAtkScale float64 `json:"ranged_atk_scale"`
	//: 特性「击杀敌人后获得 N 点部署费用」（先锋·冲锋手那一族，翎羽）。
	//: **「没有这条」是 0。**
	KillCostOnKill int `json:"kill_cost_on_kill"`
	//: 同一条特性的**后半句**「撤退时返还初始部署费用」（同族的 7 位都带）。
	//: 消费者是 `sim.go` 的撤退动作：撤退时按**实际付出的**部署费用退费。
	RetreatRefund bool `json:"retreat_refund"`
	//: 三个纯文本判据（`operator_traits.go`）。
	TextDerived
	//: 身份两字段：势力与主职业代号。**消费者是两个不同的东西**——
	//: 「医者丰碑」按势力（罗德岛）翻倍，而按职业发的全场光环看的是
	//: 主职业代号（`TANK`）。与 `team_id`（小队）也不是一回事，别混。
	NationID   string `json:"nation_id"`
	Profession string `json:"profession"`
	//: 天赋「翔虫机动」（`operator_traits.go`）。**没有这条时全取零值**。
	Glider
	//: 天赋的**非面板**效果（`talenteffects.go`）：部署给技力／概率强化攻击／
	//: 附加治疗／治疗授闪避。**只有 `ProcFactor` 的「没有这条」是 1.0，其余是 0。**
	TalentEffects talentEffects `json:"talent_effects"`
	//: 这一位的天赋黑板里、**键表之外**的键（已排序去重）。空 ≠ 这里没问题，
	//: 只表示「这一位的键都在已支持的键表里」；表外的族由覆盖账另行计数。
	TalentUnknownKeys []string `json:"talent_unknown_keys,omitempty"`
}

// ---------------------------------------------------------------- 数据源

var charTableCache map[string]json.RawMessage

// OperatorSkillIDs 返回一名干员的**技能槽列表**（按 `character_table.json` 里
// `skills` 数组的书写顺序；槽号 1 起算，即 `skills[0]` 是技能 1）。
//
// 它服务的是一条判定口径（博士 2026-09-24）：计划 json 里的 `deploys[*].skill: 0`
// **不等于「不用技能」**——除了一二星干员是真的没有技能之外，0 都会选到
// **玩家的默认技能**；测试期间把 `skill: 0` 认定为 `skill: 1`。
//
// 为什么从 `character_table` 取：那是**唯一**一份带顺序的技能槽表
// （`akdb` 的 `operator_skill` 也有，但那是另一条取数线，两处各取一份迟早分叉）。
func OperatorSkillIDs(charID string) ([]string, error) {
	tbl, err := loadCharTable()
	if err != nil {
		return nil, err
	}
	raw, ok := tbl[charID]
	if !ok || string(raw) == "null" {
		return nil, fmt.Errorf("character_table 里没有 %q", charID)
	}
	var char struct {
		Skills []struct {
			SkillID string `json:"skillId"`
		} `json:"skills"`
	}
	if err := json.Unmarshal(raw, &char); err != nil {
		return nil, fmt.Errorf("%s 的技能槽解析失败：%w", charID, err)
	}
	out := make([]string, 0, len(char.Skills))
	for _, s := range char.Skills {
		if s.SkillID != "" {
			out = append(out, s.SkillID)
		}
	}
	return out, nil
}

// loadCharTable 读 `character_table.json`（14 MB），只读一次并缓存。
//
// 复刻 `stats.py:400-423` 的**两步**：
//
//  1. **只留 `char_` 前缀**——`trap_*` / `token_*` 是装置与召唤物，不是干员。
//     不筛会把它们当干员算，症状是「名册之外的 id 也能算出面板」。
//  2. **并入升变形态**：阿米娅的近卫/医疗（`char_1001_amiya2` / `char_1037_amiya3`）
//     **不在 `character_table` 里**，而在 `char_patch_table.json` 的 `patchChars`，
//     结构与干员本体完全相同。森空岛名册引用的正是这些 charId——
//     不并进来则直接报「没有这个干员」，而**这一族一直在名册里**。
//     合并用 `setdefault` 语义（已存在的不被覆盖）。
//
// ★ 补丁表**取不到不该让整个计算器哑火**（Python 的注释原话：「少两个形态而已」），
// 所以它读失败只是不合并，不作为错误返回。
func loadCharTable() (map[string]json.RawMessage, error) {
	if charTableCache != nil {
		return charTableCache, nil
	}
	base := filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel")
	blob, err := os.ReadFile(filepath.Join(base, "character_table.json"))
	if err != nil {
		return nil, fmt.Errorf("读 character_table 失败（%s）：%w", base, err)
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(blob, &raw); err != nil {
		return nil, fmt.Errorf("character_table 不是合法 JSON（%s）：%w", base, err)
	}
	tbl := make(map[string]json.RawMessage, len(raw))
	for k, v := range raw {
		if strings.HasPrefix(k, "char_") {
			tbl[k] = v
		}
	}
	if len(tbl) == 0 {
		return nil, fmt.Errorf("character_table 里一个 char_ 条目都没有（%s）", base)
	}
	if pblob, perr := os.ReadFile(filepath.Join(base, "char_patch_table.json")); perr == nil {
		var patch struct {
			PatchChars map[string]json.RawMessage `json:"patchChars"`
		}
		if json.Unmarshal(pblob, &patch) == nil {
			added := 0
			for cid, c := range patch.PatchChars {
				if _, exists := tbl[cid]; !exists {
					tbl[cid] = c
					added++
				}
			}
			_ = added
		}
	}
	charTableCache = tbl
	return tbl, nil
}

// ---------------------------------------------------------------- 纯函数

// applyRounding 复刻 `_apply_rounding`（`stats.py:206-216`）。
//
// ★ `round` 这一支是**银行家舍入**——Python 内建 `round` 就是它。
// 用 Go 的 `math.Round` 会在 .5 上分出相反的结果。
func applyRounding(v float64, attr, rounding string) any {
	if !intAttrs[attr] || rounding == "none" {
		return v
	}
	switch rounding {
	case "floor":
		return int(math.Floor(v))
	case "round":
		return int(math.RoundToEven(v))
	case "ceil":
		return int(math.Ceil(v))
	}
	return v
}

// frame 是一个关键帧。
type frame struct {
	Level float64
	Data  map[string]any
}

// interpolateKeyframes 复刻 `interpolate_keyframes`（`stats.py:219-270`）。
//
// **不假定只有两帧**——真实数据里存在 3、4、6 甚至 11 帧的阶段。
// 等级落在两帧之间按比例插值；超出范围夹到最近一帧；布尔取左侧那帧。
func interpolateKeyframes(frames []frame, level float64, rounding string) map[string]any {
	fr := make([]frame, 0, len(frames))
	for _, f := range frames {
		if len(f.Data) > 0 {
			fr = append(fr, f)
		}
	}
	sort.SliceStable(fr, func(i, j int) bool { return fr[i].Level < fr[j].Level })
	if len(fr) == 0 {
		return map[string]any{}
	}
	if len(fr) == 1 {
		out := map[string]any{}
		for k, v := range fr[0].Data {
			out[k] = v
		}
		return out
	}
	var lo, hi frame
	switch {
	case level <= fr[0].Level:
		lo, hi = fr[0], fr[0]
	case level >= fr[len(fr)-1].Level:
		lo, hi = fr[len(fr)-1], fr[len(fr)-1]
	default:
		lo, hi = fr[0], fr[len(fr)-1]
		for i := 0; i+1 < len(fr); i++ {
			if fr[i].Level <= level && level <= fr[i+1].Level {
				lo, hi = fr[i], fr[i+1]
				break
			}
		}
	}
	span := hi.Level - lo.Level
	t := 0.0
	if span != 0 {
		t = (level - lo.Level) / span
	}
	keys := map[string]bool{}
	for k := range lo.Data {
		keys[k] = true
	}
	for k := range hi.Data {
		keys[k] = true
	}
	out := map[string]any{}
	for k := range keys {
		va, oka := lo.Data[k]
		vb, okb := hi.Data[k]
		if !oka || va == nil {
			out[k] = vb
			continue
		}
		if !okb || vb == nil {
			out[k] = va
			continue
		}
		if isBool(va) || isBool(vb) {
			if t < 0.5 {
				out[k] = va
			} else {
				out[k] = vb
			}
			continue
		}
		fa, oka2 := toFloat(va)
		fb, okb2 := toFloat(vb)
		if oka2 && okb2 {
			out[k] = applyRounding(fa+(fb-fa)*t, k, rounding)
		} else {
			out[k] = va
		}
	}
	return out
}

func isBool(v any) bool {
	_, ok := v.(bool)
	return ok
}

// potentialBonus 复刻 `_potential_bonus`（`stats.py:273-296`）。
//
// 游戏里的潜能是 1–6，而 `potentialRanks` 只有 5 项——**对应潜能 2–6**，
// 潜能 1 是干员到手时的状态、没有任何加成。所以取前 `potential - 1` 项。
func potentialBonus(ranks []json.RawMessage, potential int) map[string]any {
	out := map[string]any{}
	if potential <= 1 {
		return out
	}
	n := potential - 1
	if n > len(ranks) {
		n = len(ranks)
	}
	for _, rRaw := range ranks[:n] {
		var rank struct {
			Type string `json:"type"`
			Buff struct {
				Attributes struct {
					AttributeModifiers []struct {
						AttributeType string   `json:"attributeType"`
						Value         *float64 `json:"value"`
						FormulaItem   string   `json:"formulaItem"`
					} `json:"attributeModifiers"`
				} `json:"attributes"`
			} `json:"buff"`
		}
		if err := json.Unmarshal(rRaw, &rank); err != nil {
			continue
		}
		if rank.Type != "BUFF" {
			continue
		}
		for _, m := range rank.Buff.Attributes.AttributeModifiers {
			attr, ok := potentialAttrMap[m.AttributeType]
			if !ok {
				continue
			}
			val := 0.0
			if m.Value != nil {
				val = *m.Value
			}
			if m.FormulaItem == "MULTIPLIER" {
				//: 乘算潜能（少数干员有），键名前加 `x` 打标记，最后单独处理。
				out["x"+attr] = val
			} else {
				cur, _ := toFloat(out[attr])
				out[attr] = cur + val
			}
		}
	}
	return out
}

// ---------------------------------------------------------------- 主入口

// OperatorStatsFor 折算一名干员在某一档配置下的面板。
func OperatorStatsFor(cfg OperatorCalcConfig, rounding string) (*OperatorStats, error) {
	if rounding == "" {
		rounding = "round"
	}
	tbl, err := loadCharTable()
	if err != nil {
		return nil, err
	}
	raw, ok := tbl[cfg.CharID]
	if !ok || string(raw) == "null" {
		return nil, fmt.Errorf("character_table 里没有 %q", cfg.CharID)
	}
	var char struct {
		Name        string            `json:"name"`
		Phases      []json.RawMessage `json:"phases"`
		Favor       []json.RawMessage `json:"favorKeyFrames"`
		Potentials  []json.RawMessage `json:"potentialRanks"`
		Talents     []json.RawMessage `json:"talents"`
		Trait       json.RawMessage   `json:"trait"`
		Description string            `json:"description"`
		NationID    string            `json:"nationId"`
		Profession  string            `json:"profession"`
	}
	if err := json.Unmarshal(raw, &char); err != nil {
		return nil, fmt.Errorf("%s 的表项解析失败：%w", cfg.CharID, err)
	}
	if cfg.Elite < 0 || cfg.Elite >= len(char.Phases) {
		return nil, fmt.Errorf("%s 只有 %d 个精英阶段，没有精英 %d",
			char.Name, len(char.Phases), cfg.Elite)
	}
	var ph struct {
		MaxLevel  int               `json:"maxLevel"`
		KeyFrames []json.RawMessage `json:"attributesKeyFrames"`
	}
	if err := json.Unmarshal(char.Phases[cfg.Elite], &ph); err != nil {
		return nil, err
	}
	if cfg.Level < 1 || cfg.Level > ph.MaxLevel {
		return nil, fmt.Errorf("精英 %d 的等级必须在 1–%d，收到 %d",
			cfg.Elite, ph.MaxLevel, cfg.Level)
	}

	st := &OperatorStats{
		CharID: cfg.CharID, Elite: cfg.Elite, Level: cfg.Level,
		Trust: cfg.Trust, Potential: cfg.Potential,
		Module: cfg.Module, ModuleLevel: cfg.ModuleLevel,
		TrustBonus: map[string]any{}, PotentialBonus: map[string]any{},
		ModuleBonus: map[string]any{},
	}
	//: `stats.py:306` 的 `char.get("name") or char_id`——空名回落到 id（不是空串）。
	st.Name = char.Name
	if st.Name == "" {
		st.Name = cfg.CharID
	}
	st.Base = interpolateKeyframes(parseFrames(ph.KeyFrames),
		float64(cfg.Level), rounding)
	//: 信赖：`favorKeyFrames` 的 level 是 0–50，对应显示信赖 0%–100%，
	//: 即 `level = 显示 / 2`。`trust` 本身已是「显示 ÷ 2」，**直接当 level 用**。
	for k, v := range interpolateKeyframes(parseFrames(char.Favor), cfg.Trust, rounding) {
		if f, ok := toFloat(v); ok && f != 0 {
			st.TrustBonus[k] = v
		}
	}
	st.PotentialBonus = potentialBonus(char.Potentials, cfg.Potential)
	if cfg.Module != "" && cfg.ModuleLevel != 0 {
		levels, err := moduleLevels(cfg.Module)
		if err != nil {
			return nil, err
		}
		bb, ok := levels[cfg.ModuleLevel]
		if !ok {
			return nil, fmt.Errorf("模组 %s 只有这几个等级 %v，收到 %d",
				cfg.Module, sortedLevels(levels), cfg.ModuleLevel)
		}
		st.ModuleBonus = bb
	}

	total := map[string]any{}
	for k, v := range st.Base {
		if isBool(v) {
			total[k] = v
			continue
		}
		f, ok := toFloat(v)
		if !ok {
			total[k] = v
			continue
		}
		acc := f
		for _, src := range []map[string]any{st.TrustBonus, st.PotentialBonus, st.ModuleBonus} {
			if b, ok := toFloat(src[k]); ok {
				acc += b
			}
		}
		//: 乘算潜能
		if mul, ok := toFloat(st.PotentialBonus["x"+k]); ok && mul != 0 {
			acc *= mul
		}
		total[k] = applyRounding(acc, k, rounding)
	}
	//: ---- ★ 天赋的**面板倍率**（博士 2026-09-24 新口径：Go 要折进去）----
	//:
	//: 为什么现在才做：`akdb` 现算，**212 / 460 位**干员的天赋带这类面板键
	//: （`atk`×383 ／ `def`×157 ／ `max_hp`×78 …），而**两台引擎原来都一个都不折**
	//: ——`OperatorCalculator` 的 `total` 只由「基底 ＋ 信赖 ＋ 潜能 ＋ 模组」四项相加，
	//: 实测：玫兰莎 E1L55／信100／潜6 的 `atk` 两边都是 828，而乘上天赋（＋4%）应是 861.1。
	//:
	//: ⚠ **只折 `atk`／`def`／`max_hp` 三个键**，理由逐条：
	//:   · `attack_speed` **已经**由 `attackSpeedBonus`（`operator_aspd.go`）那条具名 finder
	//:     管着，再折一遍＝同一个量两处各算一次（本仓记过：一改就对不上）；
	//:   · `cost`（轻量化那一族）改的是**部署费用**，那是另一条路（`deploycost.go`），
	//:     不是面板；
	//:   · 其余键（`prob`／`atk_scale`／`duration` …）不是面板量。
	//:
	//: ★ 这是**有意与冻结的 Python 分道扬镳**：Python 侧不折，因此所有「与 Python 逐字段
	//: 一致」的面板类判据会看见差值。**must 具名登记**，别处不许当它没发生。
	talentMods := talentPanelMods(char.Talents, cfg.Elite, cfg.Level, cfg.Potential)
	if talentMods.ATKPct != 0 || talentMods.DEFPct != 0 || talentMods.MaxHPPct != 0 {
		for key, pct := range map[string]float64{
			"atk": talentMods.ATKPct, "def": talentMods.DEFPct, "maxHp": talentMods.MaxHPPct,
		} {
			if pct == 0 {
				continue
			}
			if cur, ok := toFloat(total[key]); ok {
				total[key] = applyRounding(cur*(1+pct), key, rounding)
			}
		}
		st.TalentPanelMods = map[string]float64{
			"atk": talentMods.ATKPct, "def": talentMods.DEFPct, "max_hp": talentMods.MaxHPPct,
		}
	}
	st.Total = total
	//: 攻速加成：天赋（常驻/高台条件）＋ 模组特性改写（未阻挡条件）。
	parts, err := moduleParts(cfg.Module, cfg.ModuleLevel)
	if err != nil {
		return nil, err
	}
	st.AttackSpeedBonus = attackSpeedBonus(char.Talents, cfg.Elite, cfg.Level,
		cfg.Potential, parts)
	//: 普攻连击：读隐藏天赋的键组合（不是按干员名）。
	st.ComboAttack = readComboAttack(char.Talents)
	//: 「强击瓶专家」：按**键的组合**认（名字那条只给审计用）。
	st.PowerAttack = readPowerAttack(char.Talents, cfg.Elite, cfg.Level, cfg.Potential)
	//: 特性那两支：溅射（几何 ＋ 天赋「汹涌怒火」叠的三项）、生命流失速率。
	//: **「没有这条」：半径/倍率/滑坡是 0，damage_scale 是 1.0。**
	sp := readSplash(char.Trait, char.Talents, cfg.Elite, cfg.Level, cfg.Potential)
	if sp.OK {
		st.SplashRadius, st.SplashScale = sp.Radius, sp.Scale
		st.SplashDamageScale = sp.DamageScale
		st.HighlandSplashScale = sp.HighlandScale
		st.HighlandSplashSluggish = sp.HighlandSluggish
	} else {
		st.SplashDamageScale = 1.0
	}
	st.HPDrainPerSec = readHPDrain(char.Description, char.Trait)
	//: 特性「攻击附带停顿」（梓兰）——**秒数**走这里，减速比例是全局常数。
	st.TraitSlowSec = readTraitSlow(char.Trait)
	//: 特性「可以进行远程攻击，但攻击力降低至 v」（月见夜 领主）——**两段判据**
	//: （正文含「远程攻击」＋「攻击力降低至」，且黑板 `atk_scale` 落在 (0,1)）。
	//: 只按键名认会误中 39 条里那 20 多条 `1.5`／`1.2` 的别的机制。
	st.RangedAtkScale = readTraitRangedScale(char.Description, char.Trait)
	//: 特性「击杀敌人后获得 N 点部署费用」（翎羽 冲锋手）——取 `cost > 0`，
	//: 行商那一族（`cost: -3` + `interval: 3`）自然落在外面。
	st.KillCostOnKill = readTraitKillCost(char.Trait)
	//: 同一条特性的后半句「撤退时返还初始部署费用」（翎羽那一族 7 位都带）。
	st.RetreatRefund = strings.Contains(stripTraitTags(char.Description), retreatRefundTrait)
	//: 三个纯文本判据（攻击类型 / 平A 是否治疗 / 弱点伤害）。
	st.TextDerived = textDerived(char.Description, char.Talents)
	//: 身份两字段：直接取自 character_table，不做任何推断。
	st.NationID = char.NationID
	st.Profession = char.Profession
	//: 「翔虫机动」：一个天赋两个平面（落位放宽 ＋ 限时攻击力加成）。
	st.Glider = readGlider(char.Talents, cfg.Elite, cfg.Level, cfg.Potential)
	//: 天赋的**非面板**效果（`talenteffects.go`）：走**同一张键表**与同一个解析器
	//: （`ApplyBlackboard`），所以「加一名新干员不必改判定逻辑」这条在这里也成立。
	//: ⚠ 未识别键**原样上抛**，由调用方落进覆盖账——静默丢掉＝把「没建」伪装成「没有」。
	te, teUnknown := talentEffectsFrom(char.Talents, cfg.Elite, cfg.Level, cfg.Potential)
	st.TalentEffects = te
	st.TalentUnknownKeys = teUnknown
	return st, nil
}

// ---------------------------------------------------------------- 模组

var battleEquipCache map[string]json.RawMessage

// moduleLevels 复刻 `module_levels`（`stats.py:499-517`）。
//
// ★ 返回的是该等级的**总加成**，不是相对上一级的增量。
// ★ `attributeBlackboard` 的 key 是**下划线风格**（`max_hp` / `magic_resistance`），
// 与 character_table 的属性名不同名，要走 `moduleKeyMap` 转一次。
func moduleLevels(moduleID string) (map[int]map[string]any, error) {
	if battleEquipCache == nil {
		p := filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel",
			"battle_equip_table.json")
		blob, err := os.ReadFile(p)
		if err != nil {
			return nil, fmt.Errorf("读 battle_equip_table 失败（%s）：%w", p, err)
		}
		var tbl map[string]json.RawMessage
		if err := json.Unmarshal(blob, &tbl); err != nil {
			return nil, fmt.Errorf("battle_equip_table 不是合法 JSON（%s）：%w", p, err)
		}
		battleEquipCache = tbl
	}
	raw, ok := battleEquipCache[moduleID]
	if !ok {
		//: 与 `stats.py:505-507` 同口径：**基础证章不带属性加成**，没有这一条。
		return nil, fmt.Errorf("模组 %s 没有战斗数值（基础证章不带属性加成）", moduleID)
	}
	var entry struct {
		Phases []struct {
			EquipLevel *int `json:"equipLevel"`
			Board      []struct {
				Key   string   `json:"key"`
				Value *float64 `json:"value"`
			} `json:"attributeBlackboard"`
		} `json:"phases"`
	}
	if err := json.Unmarshal(raw, &entry); err != nil {
		return nil, fmt.Errorf("模组 %s 解析失败：%w", moduleID, err)
	}
	out := map[int]map[string]any{}
	for _, ph := range entry.Phases {
		lv := 0
		if ph.EquipLevel != nil {
			lv = *ph.EquipLevel
		}
		bb := map[string]any{}
		for _, b := range ph.Board {
			attr, ok := moduleKeyMap[b.Key]
			if !ok {
				continue
			}
			v := 0.0
			if b.Value != nil {
				v = *b.Value
			}
			bb[attr] = v
		}
		out[lv] = bb
	}
	return out, nil
}

func sortedLevels(m map[int]map[string]any) []int {
	out := make([]int, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Ints(out)
	return out
}

func parseFrames(raws []json.RawMessage) []frame {
	out := make([]frame, 0, len(raws))
	for _, r := range raws {
		var f struct {
			Level *float64       `json:"level"`
			Data  map[string]any `json:"data"`
		}
		if err := json.Unmarshal(r, &f); err != nil {
			continue
		}
		lv := 0.0
		if f.Level != nil {
			lv = *f.Level
		}
		out = append(out, frame{Level: lv, Data: f.Data})
	}
	return out
}
