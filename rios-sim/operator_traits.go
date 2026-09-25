package main

// operator_traits.go：**特性那一族**里可纯数据判定的几支（丙阶段三·第四批）。
//
// 本轮只接「普攻连击 + 结算后缩放」（`battle/traits.py:206-240`）。
//
// ## 判据为什么长这样
//
// **某一条隐藏天赋**（`name` 为 null）的黑板里**同时**有 `attack@atk_scale`
// 与 `attack@damage_scale`，且 `damage_scale` 落在 (0,1)。
//
// ⚠ `attack@damage_scale` 这个键名**同名反义**：撼地者「汹涌怒火」的
// `damage_scale` 是「溅射伤害 +24%」（大于 1）。所以**只按键名认会误中**，
// 必须同时要求 `attack@atk_scale` 在场、且 `damage_scale < 1`（这里是「降低至」）。
//
// ⚠ 也不按干员名或子职业认：焰狐龙梓兰的 `character_table.trait` 是**空的**，
// 这条机制住在隐藏天赋里，审计的两道筛子与第三道都照不到它——
// PRTS 的 `|特性备注=` 才是它的出处。
//
// ## 「没有这条」是 1，不是 0
//
// `verify.py:342-344` 的三行：`combo_hits=combo.hits if combo else 1`、
// `combo_hit_scale=… else 1.0`、`combo_damage_scale=… else 1.0`。
// 按 0 判会把每一位没有连击的干员都当成「0 击」。

import (
	"encoding/json"
	"math"
	"strings"
)

// comboAttackKeys 复刻 `COMBO_ATTACK_KEYS`（`traits.py:128`）。
var comboAttackKeys = []string{"attack@atk_scale", "attack@damage_scale"}

// comboHits 复刻 `COMBO_HITS`（`traits.py:142`）。
// 黑板里**没有**这个数，出处见该常量的文档（焰狐龙梓兰：3 击 × 100%）。
const comboHits = 3

// ComboAttack 是一次普攻的连击结构（`traits.py:298-308`）。
type ComboAttack struct {
	Hits        int     `json:"combo_hits"`
	HitScale    float64 `json:"combo_hit_scale"`
	DamageScale float64 `json:"combo_damage_scale"`
}

// defaultCombo 是「没有这条」的那一份（`verify.py:342-344`）。
func defaultCombo() ComboAttack {
	return ComboAttack{Hits: 1, HitScale: 1.0, DamageScale: 1.0}
}

// readComboAttack 复刻 `read_combo_attack`（`traits.py:206-240`）。
func readComboAttack(talents []json.RawMessage) ComboAttack {
	for _, tRaw := range talents {
		var group struct {
			Candidates []struct {
				Name       *string           `json:"name"`
				Blackboard []json.RawMessage `json:"blackboard"`
			} `json:"candidates"`
		}
		if err := json.Unmarshal(tRaw, &group); err != nil {
			continue
		}
		for _, cand := range group.Candidates {
			//: ★ 隐藏天赋：`name` 为 null（或空）。
			if cand.Name != nil && *cand.Name != "" {
				continue
			}
			bb := pairsToDict(cand.Blackboard)
			ok := true
			for _, k := range comboAttackKeys {
				if _, has := bb[k]; !has {
					ok = false
					break
				}
			}
			if !ok {
				continue
			}
			scale, has := bb["attack@damage_scale"]
			if !has || !(scale > 0.0 && scale < 1.0) {
				//: 「提升至」式的大于 1 是别的东西（溅射增伤那一族），不认。
				continue
			}
			hitScale, _ := bb["attack@atk_scale"]
			return ComboAttack{Hits: comboHits, HitScale: hitScale,
				DamageScale: scale}
		}
	}
	return defaultCombo()
}

// PowerAttack 是天赋「强击瓶专家」（焰狐龙梓兰 天赋1）翻出来的两数
// （`talents.py:293-306`、`find_power_attack` :347-355）。
//
// 正文：「部署后首次开启技能时，接下来 50 次攻击的攻击力提升至 115%」。
// prts.wiki 该页 `|备注=` 把它钉成**按轮数**而不是按箭矢：
// 一次出手的所有箭矢都吃加成、**整轮只扣一层**（技2 一次含三轮齐射＋
// 一次落地点射 ⇒ 一次扣四层）。
type PowerAttack struct {
	//: 一共多少轮。**「没有这条」是 0。**
	Count int `json:"power_attack_count"`
	//: 攻击力倍率。**「没有这条」是 1.0，不是 0**（`talents.py:354` 的 `or 1.0`）。
	Scale float64 `json:"power_attack_scale"`
}

// powerAttackTalentNames 复刻 `POWER_ATTACK_TALENTS`（`talents.py:332`）。
var powerAttackTalentNames = map[string]bool{"强击瓶专家": true}

// defaultPowerAttack 是「没有这条」的那一份（`verify.py:346-347`）。
func defaultPowerAttack() PowerAttack {
	return PowerAttack{Count: 0, Scale: 1.0}
}

// readPowerAttack 复刻 `is_power_attack_talent` + `find_power_attack`。
//
// ★ 判据是**键的组合**（`power_attack_count` + `power_attack_scale`），
// **不是名字**——名字只留给审计的第三道筛子看。两条都要留：
// 名字那一条是给「按天赋名」的审计用的，键那一条才是真的识别。
func readPowerAttack(talents []json.RawMessage, elite, level, potential int) PowerAttack {
	for _, t := range resolveTalents(talents, elite, level, potential) {
		if !powerAttackTalentNames[t.Name] {
			if _, a := t.Blackboard["power_attack_count"]; !a {
				continue
			}
			if _, b := t.Blackboard["power_attack_scale"]; !b {
				continue
			}
		}
		out := defaultPowerAttack()
		if v, ok := toFloat(t.Blackboard["power_attack_count"]); ok {
			out.Count = int(v)
		}
		if v, ok := toFloat(t.Blackboard["power_attack_scale"]); ok {
			out.Scale = v
		}
		return out
	}
	return defaultPowerAttack()
}

// ---- 特性：生命流失 与 特性溅射（几何那一半）----

// ---- 特性「可以进行远程攻击，但攻击力降低至 v」（领主那一族）----

// rangedAttackTrait / rangedLowerPhrase 是这条特性的**两段判据**。
//
// ★ 为什么必须两段（现算的影响面，`akdb` 全表）：特性黑板里带 `atk_scale` 的有
// **39 条**，而其中 `0.8` 那一族（银灰／棘刺／仇白／丰川祥子／月见夜…）才是
// 「远程降攻」；另有 `1.5`／`1.2` 的一族（假日威龙陈／缪尔赛思／伺夜／帕拉斯／莱伊）
// 是**别的东西**。只按键名认会把那 20 多条一起误中。
//
// 与 `readHPDrain` 同一个姿势：**正文 ＋ 黑板值**两段缺一不可。
const (
	rangedAttackTrait = "远程攻击"
	rangedLowerPhrase = "攻击力降低至"
)

// readTraitRangedScale 读「远程攻击时攻击力降低至 v」的 v。
//
// ★ 这个 v 用的是**哪一格**为判据、不是几何：博士 2026-09-25 裁定——
// 「只要被攻击的敌人在攻击范围内**并且未被月见夜阻挡**，这个时候对这名敌人的攻击
// 就是远程攻击；如果是被阻挡的敌人那么无论是前后左右都算近战攻击」。
// ⇒ 判据是「**目标有没有被她挡住**」（`sim.go` 里读 `target.blockedBy != op`），
// 与格子几何无关。落点写在 `sim.go::operatorsAttack`。
//
// 没有这条就返回 1.0——调用侧不用判空（这个量「没有」就是 1.0，它是乘数）。
func readTraitRangedScale(description string, traitRaw json.RawMessage) float64 {
	if !strings.Contains(stripTraitTags(description), rangedAttackTrait) ||
		!strings.Contains(stripTraitTags(description), rangedLowerPhrase) {
		return 1.0
	}
	for _, cand := range traitCandidates(traitRaw) {
		bb := pairsToDict(cand)
		if v, ok := bb["atk_scale"]; ok && v > 0.0 && v < 1.0 {
			return v
		}
	}
	return 1.0
}

// ---- 特性「击杀敌人后获得 N 点部署费用」（先锋·冲锋手那一族）----

// traitKillCostKey 是这条特性在黑板上的键。
//
// ★ 影响面（现算，`akdb` 全表）：特性黑板里带 `cost` 的有 **13 条**，分两族——
//
//	{"cost": 1.0}                  → **击杀得费**（翎羽／红豆／苇草／风笛／格拉尼／野鬃／历阵锐枪芬）
//	{"cost": -3.0, "interval": 3.0} → **行商**那一族（琳琅诗怀雅／老鲤／裁度／乌有／孑）：每 interval 秒扣 3 费
//
// ⇒ 判据取 **`cost > 0`**，行商那一族自然落在外面（它是负数）。
// 行商那一支**未实现**，登记在文档里。
const traitKillCostKey = "cost"

// readTraitKillCost 读「击杀敌人后获得 N 点部署费用」的 N（整数）。
//
// 没有这条就返回 0——调用侧不用判空。
func readTraitKillCost(traitRaw json.RawMessage) int {
	for _, cand := range traitCandidates(traitRaw) {
		bb := pairsToDict(cand)
		if v, ok := bb[traitKillCostKey]; ok && v > 0.0 {
			return int(math.Round(v))
		}
	}
	return 0
}

// traitSlowKey 是特性黑板里「攻击附带停顿多少秒」那个键。
//
// ⚠ 它**不在** `skillKeyTable` 里，也不该在：那张表的意思是「已经实现的键」，
// 而技能侧的 `sluggish`（凯尔希·保护性拒止 `sluggish 5.0`、换形态的 `stand_sluggish`）
// **还没实现**。表外 ⇒ 它会出现在覆盖账上，这正是本仓要的形态。
//
// ⚠ 与 `attack@sluggish` 是**两个键**（怒潮凛冬的高台溅射那 0.5 秒），本仓记过
// 「同名不同义」的坑，所以这里分开读、不合并。
const traitSlowKey = "sluggish"

// readTraitSlow 复刻「特性：攻击造成停顿」那一支（梓兰 凝滞师）。
//
// 判据只有一条：**特性黑板里有 `sluggish` 且为正**。不按子职业名、不按干员名——
// 与 `readTraitSplash` / `readHPDrain` 同一个姿势。
//
// ★ 值是**秒数**，不是减速比例（减速比例是全局常数 `sluggishSlowPct`＝80%，
// 博士 2026-09-25 裁定）。出处：`formula.py:585` 的 note
// 「文案未给时长，数值在黑板 sluggish」；与 `attack@sluggish` 同一条口径。
//
// 没有这条就返回 0.0——调用侧不用判空（这个量「没有」就是 0）。
func readTraitSlow(traitRaw json.RawMessage) float64 {
	for _, cand := range traitCandidates(traitRaw) {
		bb := pairsToDict(cand)
		if secs, ok := bb[traitSlowKey]; ok && secs > 0.0 {
			return secs
		}
	}
	return 0.0
}

// hpDrainTrait 复刻 `HP_DRAIN_TRAIT`（`traits.py:108`）。
const hpDrainTrait = "自身生命会不断流失"

// hpDrainKey 复刻 `HP_DRAIN_KEY`（`traits.py:110`）。
const hpDrainKey = "hp_ratio"

// splashRadiusKey / splashScaleKey 复刻 `traits.py:113/116`。
const (
	splashRadiusKey = "attack@ability_range_radius"
	splashScaleKey  = "attack@atk_scale_2"
)

// readHPDrain 复刻 `read_hp_drain`（`traits.py:181-203`）。
//
// 判据**两段，缺一不可**：① 特性正文含「自身生命会不断流失」；
// ② 特性黑板里有 `hp_ratio` 且为正。只读黑板会把别的带 `hp_ratio` 的特性误中。
//
// 没有这条就返回 0.0——调用侧不用判空（这个量「没有」就是 0）。
func readHPDrain(description string, traitRaw json.RawMessage) float64 {
	if !strings.Contains(description, hpDrainTrait) {
		return 0.0
	}
	for _, cand := range traitCandidates(traitRaw) {
		bb := pairsToDict(cand)
		if rate, ok := bb[hpDrainKey]; ok && rate > 0.0 {
			return rate
		}
	}
	return 0.0
}

// readTraitSplash 复刻 `read_trait_splash`（`traits.py:163-178`）的**几何那一半**。
//
// 判据只有一条：**特性黑板上同时有 `attack@ability_range_radius` 与
// `attack@atk_scale_2`**。不是按子职业名、也不是按干员名——特性是**数据**，
// 子职业名是**文案**，后者会随版本改名而前者不会。
//
// ⚠ 本轮**只接几何**（半径/倍率）；`apply_splash_talent` 叠上去的那三项
// （`damage_scale` / `highland_splash_scale` / `highland_splash_sluggish`）
// **未接**——那要按天赋键 `("damage_scale","attack@splash_atk_scale")` 再判一次。
func readTraitSplash(traitRaw json.RawMessage) (float64, float64, bool) {
	for _, cand := range traitCandidates(traitRaw) {
		bb := pairsToDict(cand)
		radius, okR := bb[splashRadiusKey]
		scale, okS := bb[splashScaleKey]
		if okR && okS {
			return radius, scale, true
		}
	}
	return 0.0, 0.0, false
}

// splashTalentNames 复刻 `SPLASH_TALENTS`（`traits.py:124`）。
var splashTalentNames = map[string]bool{"汹涌怒火": true}

// splashTalentKeys 复刻 `SPLASH_TALENT_KEYS`（`traits.py:120`）。
var splashTalentKeys = []string{"damage_scale", "attack@splash_atk_scale"}

// Splash 是一条特性溅射的**已解释**参数（`TraitSplash`，`traits.py:279-295`）。
//
// ⚠ `damage_scale` 只乘在**溅射**上，不乘主目标。
type Splash struct {
	Radius           float64
	Scale            float64
	DamageScale      float64
	HighlandScale    float64
	HighlandSluggish float64
	OK               bool
}

// readSplash 复刻 `read_trait_splash` + `apply_splash_talent`
// （`traits.py:163-178` 与 `251-270`）。
//
// 两段：
//  1. **几何**只认特性黑板上的键组合（不是子职业名）；
//  2. 天赋「汹涌怒火」再叠三项——**只认第一条命中的**，没有就原样返回，
//     此时 `damage_scale` 保持 1.0、两个 highland 保持 0.0（`TraitSplash` 的默认值）。
func readSplash(traitRaw json.RawMessage, talents []json.RawMessage,
	elite, level, potential int) Splash {
	out := Splash{DamageScale: 1.0}
	for _, cand := range traitCandidates(traitRaw) {
		bb := pairsToDict(cand)
		radius, okR := bb[splashRadiusKey]
		scale, okS := bb[splashScaleKey]
		if okR && okS {
			out.Radius, out.Scale, out.OK = radius, scale, true
			break
		}
	}
	if !out.OK {
		return out
	}
	for _, t := range resolveTalents(talents, elite, level, potential) {
		if !isSplashTalent(t) {
			continue
		}
		out.DamageScale = 1.0
		if v, ok := toFloat(t.Blackboard["damage_scale"]); ok {
			out.DamageScale = v
		}
		if v, ok := toFloat(t.Blackboard["attack@splash_atk_scale"]); ok {
			out.HighlandScale = v
		}
		if v, ok := toFloat(t.Blackboard["attack@sluggish"]); ok {
			out.HighlandSluggish = v
		}
		return out
	}
	return out
}

// isSplashTalent 复刻 `is_splash_talent`（`traits.py:243-248`）。
func isSplashTalent(t resolvedTalent) bool {
	if splashTalentNames[t.Name] {
		return true
	}
	for _, k := range splashTalentKeys {
		if _, ok := t.Blackboard[k]; !ok {
			return false
		}
	}
	return true
}

// ---- 天赋「翔虫机动」----

// gliderTalentNames / gliderTalentKeys 复刻 `talents.py:256/258`。
var gliderTalentNames = map[string]bool{"翔虫机动": true}
var gliderTalentKeys = []string{"ignore_build_type_target", "not_add_respawn_cost_cnt"}

// Glider 是天赋「翔虫机动」翻出来的七个量（`talents.py:210-252`）。
//
// **一个天赋，两个平面**：落位放宽（能不能放近战位）＋ 限时攻击力加成。
// 没有这条时全部取「零值」——`verify.py:348-354` 的 `if glider else …`。
type Glider struct {
	AtkBonus     float64 `json:"mobility_atk_bonus"`
	AtkDuration  float64 `json:"mobility_atk_duration"`
	Projectile   string  `json:"mobility_leftover"`
	DeployRange  string  `json:"mobility_deploy_range"`
	IgnoreBuild  bool    `json:"mobility_melee_deploy"`
	IgnoreDir    float64 `json:"mobility_ignore_dir"`
	NoRespawnAdd bool    `json:"no_respawn_cost_add"`
}

// readGlider 复刻 `is_glider_mobility` + `find_glider_mobility`（`talents.py:261-289`）。
//
// ★ **两个范围/弹道代号住在 `$键`（`valueStr`）里**，裸键的 `value` 恒为 0：
// `{"key": "ignore_build_type_target_range", "value": 0, "valueStr": "x-1"}`。
// 判据是 `$键 或 裸键`——只看裸键会拿到一个恒为 0 的数并静默丢掉 `x-1`。
func readGlider(talents []json.RawMessage, elite, level, potential int) Glider {
	for _, t := range resolveTalents(talents, elite, level, potential) {
		if !isGliderTalent(t) {
			continue
		}
		var g Glider
		if v, ok := toFloat(t.Blackboard["atk"]); ok {
			g.AtkBonus = v
		}
		if v, ok := toFloat(t.Blackboard["atk_duration"]); ok {
			g.AtkDuration = v
		}
		g.Projectile = strOr(t.Blackboard["$projectile"], t.Blackboard["projectile"])
		g.DeployRange = strOr(t.Blackboard["$ignore_build_type_target_range"],
			t.Blackboard["ignore_build_type_target_range"])
		if v, ok := toFloat(t.Blackboard["ignore_build_type_target"]); ok {
			g.IgnoreBuild = v != 0
		}
		if v, ok := toFloat(t.Blackboard["ignore_build_type_target_dir"]); ok {
			g.IgnoreDir = v
		}
		if v, ok := toFloat(t.Blackboard["not_add_respawn_cost_cnt"]); ok {
			g.NoRespawnAdd = v != 0
		}
		return g
	}
	return Glider{}
}

// isGliderTalent 复刻 `is_glider_mobility`：名字或**键的组合**命中即可。
func isGliderTalent(t resolvedTalent) bool {
	if gliderTalentNames[t.Name] {
		return true
	}
	for _, k := range gliderTalentKeys {
		if _, ok := t.Blackboard[k]; !ok {
			return false
		}
	}
	return true
}

// strOr 复刻 `str(a or b or "")`：前者为空则取后者。
func strOr(a, b any) string {
	if s, ok := a.(string); ok && s != "" {
		return s
	}
	if s, ok := b.(string); ok && s != "" {
		return s
	}
	return ""
}

// ---- 三个纯文本判据（`verify.py:329-331`）----
//
// 它们各自只有一个判据词，**必须与 Python 逐字一致**——差一个字就会静默变成
// 另一种攻击类型 / 不治疗 / 丢了弱点伤害。

// TextDerived 是三项由文本推出的字段。
type TextDerived struct {
	//: `"MAGIC" if "法术伤害" in trait else "PHYSICAL"`（特性正文）。
	DamageType string `json:"damage_type_text"`
	//: 特性正文含「恢复友方单位生命」= 这个人的平A 是治疗。
	Heals bool `json:"heals"`
	//: 特性正文含「技能可以治疗友方单位」= 这个人**技能开启期间**的平A 是治疗
	//: （守护者那一族：斑点 `char_284_spot`）。
	//:
	//: ★ 为什么要与 `Heals` **分开两个字段**：它们是**互补**的两条，不是同一条的强弱：
	//:   · `Heals`（医疗）平A 恒为治疗，技能写明攻击倍率时**改成伤害**（凯尔希·思衡托）；
	//:   · `HealsOnSkill`（守护者）平A 恒为伤害，技能开启期间**改成治疗**
	//:     （斑点「次级治疗模式」，黑板只有 `atk` 与 `base_attack_time`——
	//:     那个 `atk` 抬的是**治疗量**，不是伤害）。
	//: 压成一个字段会让这两族的判据互相打架：压成 `Heals=true` 就再没有
	//: 「技能期间才治」这条信息，斑点会在没开技能时也去治人。
	HealsOnSkill bool `json:"heals_on_skill"`
	//: **全部天赋候选**的正文里含「弱点伤害」（不是只看生效的那几条）。
	WeaknessDamage bool `json:"weakness_damage"`
	//: 特性正文含「优先攻击空中单位」⇒ 选目标时**飞行单位优先**（狙击·速射手那一族）。
	//:
	//: ⚠ 「优先」不是「只能」：范围里只有地面单位时她照打。把它实现成过滤器
	//: （只打飞行）会让速射手在**没有空中单位**的关卡里一次都不出手——
	//: 那是把「优先」读成了「只能」，症状是整关零输出。
	AirPriority bool `json:"air_priority"`
	//: 特性正文含「同时攻击阻挡的所有敌人」⇒ 一次出手打**她自己挡住的全部**敌人
	//: （泡普卡）。**不是**「打范围内所有人」——范围里路过而没被挡住的敌人不算。
	AttacksAllBlocked bool `json:"attacks_all_blocked"`
	//: **天赋**正文含「优先攻击防御力最高的敌人」（史都华德 铠甲突破）⇒ 选目标时
	//: 防御力高的优先。
	//:
	//: ⚠ 与上面三条不同：这一条的出处是**天赋**正文，不是特性正文——史都华德的黑板
	//: 里只有 `{"atk": 0.03}`（面板那一半），**选目标这件事一个字都没写进黑板**。
	//: 所以它走 `talentText`（与 `weakness_damage` 同一个取数口）。
	PreferHighestDef bool `json:"prefer_highest_def"`
	//: **天赋**正文含「优先攻击使用远程武器的敌人」（安德切尔 短板突破）⇒ 选目标时
	//: `ApplyWay == "RANGED"` 的敌人优先。
	//:
	//: ⚠ 安德切尔**同时**带特性「优先攻击空中单位」与这一条天赋。两条同时命中时
	//: 谁先谁后**没有取证**（全库只有他一位这样的干员），所以本实现把它排在
	//: 空中之后（见 `sim.go::pickTargets` 的排序链与那里的注释），并**具名登记**
	//: 这条次序未经取证——它不像「哪一条该生效」那样可以直接量。
	PreferRanged bool `json:"prefer_ranged"`
}

// airPriorityTrait / allBlockedTrait 是特性那两条的判据词。
//
// ★ 为什么不按键：这两条**黑板是空的**（实测：克洛丝／安德切尔／泡普卡的
// `operator_trait.blackboard` 都是 `{}`），机制只写在正文里。
// 「黑板里没有」不等于「没有这条机制」——本仓写明的盲区之一。
const (
	airPriorityTrait = "优先攻击空中单位"
	allBlockedTrait  = "同时攻击阻挡的所有敌人"
)

// preferHighestDefTalent / preferRangedTalent 是那两条**天赋**正文的判据词。
// 与上面两条同族，但出处不同（天赋正文，不是特性正文）。
const (
	preferHighestDefTalent = "优先攻击防御力最高的敌人"
	preferRangedTalent     = "优先攻击使用远程武器的敌人"
)

// stripTraitTags 把特性正文里的**排版标签**剥掉再判词。
//
// ★ 为什么必须剥（2026-09-25 实测）：泡普卡的 `trait_text` 原文是
//
//	同时攻击阻挡的<@ba.kw>所有敌人</>
//
// 标签**插在词中间**——整串短语一个字都不差地去扫是**扫不到**的。
// 本仓为这件事单独留过注释（`skillmeta.go:94-98`：`skill.py:134` 那两行，
// 「伤害类型变为<@ba.vup>真实</>」原样扫「真实伤害」扫不到）。
// ⚠ 这一次是**特性**侧第一次真被它咬到，代价是那条特性整条静默不生效。
//
// ⚠ 剥标签只会让命中**变多**（严格放宽），不会把原来命中的变成不命中；
// 但「变多」本身是一次行为变更，所以它必须出现在判据里（`check_operator_go.py`
// 的行使计数会跟着动）——这正是本次跑判据的原因。
func stripTraitTags(s string) string { return tagRE.ReplaceAllString(s, "") }

// healsOnSkillTrait 是「技能可以治疗友方单位」这条特性的判据词。
// 与 `Heals` 一样是**整串短语**匹配——差一个字就会静默变成「从不开技能治疗」，
// 而那个症状（斑点一整场打不出一次治疗）看起来像「治疗没接」。
const healsOnSkillTrait = "技能可以治疗友方单位"

// textDerived 复刻 `verify.py:305-308` 与 `:329-331`。
//
// ⚠ `weakness_damage` 的判据文本 `tal_text` 是**所有候选**的描述拼接，
// 不是「这个练度下生效的那几条」——照解析后的天赋判会漏掉高档位才解锁的那条。
func textDerived(traitDesc string, talents []json.RawMessage) TextDerived {
	out := TextDerived{DamageType: "PHYSICAL"}
	//: ★ 四条判词都扫**剥过标签**的正文，不是原文——`stripTraitTags` 的注释里
	//: 记了实测（泡普卡那条标签插在词中间）。这一处是**共用**的：
	//: 只给新加的判词剥、把老的两条留在原文上，等于把同一个 bug 留一半。
	plain := stripTraitTags(traitDesc)
	if strings.Contains(plain, "法术伤害") {
		out.DamageType = "MAGIC"
	}
	out.Heals = strings.Contains(plain, "恢复友方单位生命")
	out.HealsOnSkill = strings.Contains(plain, healsOnSkillTrait)
	out.AirPriority = strings.Contains(plain, airPriorityTrait)
	out.AttacksAllBlocked = strings.Contains(plain, allBlockedTrait)
	//: 这两条走**天赋**正文（`talents`），不是特性正文——史都华德／安德切尔的
	//: 黑板里一个字都没写它们。取数口与 `weakness_damage` 同一个（`talentText`）。
	tal := talentText(talents)
	out.PreferHighestDef = strings.Contains(tal, preferHighestDefTalent)
	out.PreferRanged = strings.Contains(tal, preferRangedTalent)
	out.WeaknessDamage = strings.Contains(tal, "弱点伤害")
	return out
}

// talentText 复刻 `verify.py:305-308`：所有候选的描述拼成一串。
func talentText(talents []json.RawMessage) string {
	var b strings.Builder
	for _, tRaw := range talents {
		var group struct {
			Candidates []struct {
				Description string `json:"description"`
			} `json:"candidates"`
		}
		if err := json.Unmarshal(tRaw, &group); err != nil {
			continue
		}
		for _, cand := range group.Candidates {
			b.WriteString(cand.Description)
			b.WriteString(" ")
		}
	}
	return b.String()
}

// traitCandidates 取出 `trait.candidates[].blackboard`。
func traitCandidates(traitRaw json.RawMessage) [][]json.RawMessage {
	if len(traitRaw) == 0 {
		return nil
	}
	var t struct {
		Candidates []struct {
			Blackboard []json.RawMessage `json:"blackboard"`
		} `json:"candidates"`
	}
	if err := json.Unmarshal(traitRaw, &t); err != nil {
		return nil
	}
	out := make([][]json.RawMessage, 0, len(t.Candidates))
	for _, c := range t.Candidates {
		out = append(out, c.Blackboard)
	}
	return out
}

// pairsToDict 复刻 `_pairs_to_dict`（`traits.py:145`）：
// `[{key, value}]` → `{key: 数值}`。取不到数的键**不进表**——
// 进了会让 `all(k in bb)` 那条判据把字符串键当成命中。
func pairsToDict(raws []json.RawMessage) map[string]float64 {
	out := map[string]float64{}
	for _, r := range raws {
		var b struct {
			Key   string   `json:"key"`
			Value *float64 `json:"value"`
		}
		if err := json.Unmarshal(r, &b); err != nil || b.Key == "" {
			continue
		}
		if b.Value != nil {
			out[b.Key] = *b.Value
		}
	}
	return out
}
