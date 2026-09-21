package main

// effects.go：`_parse_effects` 的**计数账**（丙阶段四·第七批）。
//
// 对应 `ak_tactic/operator/skill.py:2110-2192` 的 `_parse_effects`。
//
// ## 本文件只做计数，不做效果对象的内容
//
// `_parse_effects` 把黑板分装进五个箱子（buffs / damage / control /
// variant_units / other）。本批**只复刻两个计数与 `other` 的键集**
// ——它们是 Python `SkillEffects` 直接暴露、且本批能逐条对上的量。
// `buffs` / `damage` / `variants` 的**内容**（含尾部那两趟
// `scales`/`ammos` 的收尾）**未接**，见 `skillmeta.go` 的字段注释。
//
// ## 口径逐条抄（出处行号）
//
//	① `$` 开头的键是 valueStr 标记，**不计数**（:2128-2129）；
//	② 每个键先 `total += 1`（:2130）；
//	③ `[kill].max_stack_cnt` 收成规范字段 `kill_max_stack`
//	   （:2135-2137），★ **但不 `classified += 1`**；
//	④ 起飞/降落演出参数（`_FLIGHT_KEYS`）在 `_classify` **之前**收走，
//	   `classified += 1`（:2141-2145）——它们本来就不属于任何一类，
//	   靠分类表永远进不来；
//	⑤ `_classify(bare)` 归不了 → 落 `other`，**不计数**（:2147-2149）；
//	⑥ 归得了 → `classified += 1`（:2151）；`ammo` 在 `durationType != "AMMO"`
//	   时 `classified -= 1` 并落 `other`（:2162-2167）。
//
// ## ★ ③ 那一行是本批的全部内容
//
// 上一轮我在 ③ 上多加了 1，全表对拍立刻报 11002/11012——唯一差的就是
// `skchr_amiya2_2`（阿米娅技2，正带 `[kill].max_stack_cnt`）：
// Go=6 / Python=5，而它的 `other` 键集两边相同。
// **「哪一支不计数」是这一族里唯一会静默偏 1 的地方。**

import "strings"

// EffectsAccount 返回 `(total, classified, other 键集)`。
func EffectsAccount(bb map[string]any, durationType string) (int, int, []string) {
	total, classified := 0, 0
	other := []string{}
	for key := range bb {
		if strings.HasPrefix(key, "$") {
			continue
		}
		total++
		variant, bare := "", key
		if v, rest, ok := SplitVariant(key); ok {
			variant, bare = v, rest
		}
		if variant == "kill" && bare == "max_stack_cnt" {
			//: ★ 这一支**不加 classified**（`skill.py:2135-2137` 是 `continue`）。
			continue
		}
		if _, ok := FLIGHT_KEYS[rsplitAt(bare)]; ok {
			classified++
			continue
		}
		kind, name, _, hit := Classify(bare)
		if !hit {
			other = append(other, key)
			continue
		}
		classified++
		if kind == "damage" && name == "ammo" && durationType != "AMMO" {
			classified--
			other = append(other, key)
		}
	}
	sortStringsAsc(other)
	return total, classified, other
}

func sortStringsAsc(a []string) {
	for i := 1; i < len(a); i++ {
		for j := i; j > 0 && a[j] < a[j-1]; j-- {
			a[j], a[j-1] = a[j-1], a[j]
		}
	}
}
