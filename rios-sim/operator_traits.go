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
				Name      *string             `json:"name"`
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
	//: **全部天赋候选**的正文里含「弱点伤害」（不是只看生效的那几条）。
	WeaknessDamage bool `json:"weakness_damage"`
}

// textDerived 复刻 `verify.py:305-308` 与 `:329-331`。
//
// ⚠ `weakness_damage` 的判据文本 `tal_text` 是**所有候选**的描述拼接，
// 不是「这个练度下生效的那几条」——照解析后的天赋判会漏掉高档位才解锁的那条。
func textDerived(traitDesc string, talents []json.RawMessage) TextDerived {
	out := TextDerived{DamageType: "PHYSICAL"}
	if strings.Contains(traitDesc, "法术伤害") {
		out.DamageType = "MAGIC"
	}
	out.Heals = strings.Contains(traitDesc, "恢复友方单位生命")
	out.WeaknessDamage = strings.Contains(talentText(talents), "弱点伤害")
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
