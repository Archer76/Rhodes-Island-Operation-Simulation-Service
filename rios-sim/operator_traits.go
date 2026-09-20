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

import "encoding/json"

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
// 名字那一条是给"按天赋名"的审计用的，键那一条才是真的识别。
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
