// talenteffects.go：**天赋的非面板效果**——与 `talentpanel.go` 同一族，仍然按黑板键驱动。
//
// ## 为什么单开一个文件，而不是塞进 `talentpanel.go`
//
// `talentpanel.go` 只管**折进面板**的那三个键（`atk`／`def`／`max_hp`）——它的产物是
// 「面板上的一个数」。这里管的是**发生在场上、某一时刻才兑现**的效果：
// 部署那一刻给技力、出手那一刻判概率、治疗那一刻授闪避。两者的产物形态不同，
// 却共用同一张键表（`skillKeyTable`，见 `skilleffects.go`）与同一个解析器
// （`ApplyBlackboard`），所以是**同一个模块的第二个出口**，不是第二套代码。
//
// ## 判据一律是**键的组合**，不是天赋名、不是干员名
//
// 博士 2026-09-24 的模块化口径：加一名新干员（不管几星）不许改判定逻辑。
// 三星这一族给了**三条互不歧义的键组合**（都是现算出来的原文，见
// `docs/three-star-modelling.md` §十）：
//
//	┌───────────────────────────────┬──────────────────────────────────────────┐
//	│ 键的组合                       │ 效果                                      │
//	├───────────────────────────────┼──────────────────────────────────────────┤
//	│ `sp`                           │ 部署后立即获得 v 点技力（炎熔 快速技能使用）│
//	│ `prob` ＋ `atk_scale`（无 `duration`）│ 概率强化当次攻击（克洛丝／月见夜 要害瞄准·初级）│
//	│ `attack@prob`（无 `atk_scale`）│ 附加治疗一名的概率（安赛尔 附加治疗）      │
//	│ `prob` ＋ `duration`           │ 治疗友方后授出持续 v 秒的闪避（斑点 烟雾加装）│
//	└───────────────────────────────┴──────────────────────────────────────────┘
//
// ⚠ **`prob` 与 `attack@prob` 是两个键、两种意思**——实测就是如此：
// 安赛尔的黑板是 `attack@prob: 0.07`（**不加** `duration`），斑点是
// `prob: 0.1` ＋ `duration: 3.0`（且**没有** `attack@prob`）。`ApplyBlackboard`
// 把两者都归进同一个 `m.Prob`（技能侧需要这样），所以这里**必须回看原始键名**
// 才分得开——「键名被合并成同义词」正是本仓记过的假信号来源。
//
// ## 两条纪律
//
//  1. **概率走期望值，不掷骰子**：与既有的闪避同一条口径
//     （`resolveDamage` 把 `dodge` 当期望值削掉 —— `sim.go:3237`）。
//     掷骰子会让同一条时间线两次跑出两个数，而本仓的判决比对靠的就是可重复。
//  2. **认不出来的键必须具名报出来**：`ApplyBlackboard` 的未识别清单原样上抛，
//     由调用方落进覆盖账。表外的键不是错误，是**待办**。
package main

import (
	"encoding/json"
	"math"
	"sort"
)

// talentEffects 是天赋里**非面板**的那几项效果。
//
// 零值＝「这名干员没有这一条」。唯一例外是 `ProcFactor`：它的「没有这条」是
// **1.0**（期望倍率），所以构造函数里显式给 1.0 —— 给 0 会让这个人打不出伤害。
type talentEffects struct {
	//: `sp`：部署后立即获得的技力。
	DeploySP float64
	//: 概率强化当次攻击的**期望倍率**：多位天赋各给一条时相乘
	//: `Π(1 + p_i·(s_i − 1))`。「没有这条」是 1.0。
	ProcFactor float64
	//: `attack@prob`：额外治疗一名的概率（多位各给时按 `1 − Π(1 − p_i)` 并）。
	ExtraHealProb float64
	//: `prob` ＋ `duration`：治疗友方后授出的**闪避比例**。
	DodgeOnHeal float64
	//: 上面那条闪避的持续秒数。
	DodgeSeconds float64
}

// defaultTalentEffects 是「一条都没有」的那一份。
func defaultTalentEffects() talentEffects {
	return talentEffects{ProcFactor: 1.0}
}

// talentEffectsFrom 把**这一练度下真正生效的**天赋逐条过一遍键表。
//
// 返回的第二项是**未识别键**（已排序去重）——表外的新键要在这里具名出现，
// 不许静默丢掉：这个仓在「静默忽略」上栽过不止一次。
func talentEffectsFrom(talents []json.RawMessage, elite, level, potential int) (talentEffects, []string) {
	out := defaultTalentEffects()
	var unknown []string
	seen := map[string]bool{}

	for _, t := range resolveTalents(talents, elite, level, potential) {
		if len(t.Blackboard) == 0 {
			continue
		}
		m, unk := ApplyBlackboard(t.Blackboard)
		for _, k := range unk {
			if !seen[k] {
				seen[k] = true
				unknown = append(unknown, k)
			}
		}
		_, hasProb := t.Blackboard["prob"]
		_, hasAtkProb := t.Blackboard["attack@prob"]
		_, hasDuration := t.Blackboard["duration"]
		_, hasScale := t.Blackboard["atk_scale"]

		out.DeploySP += m.SP

		switch {
		case hasProb && hasDuration:
			//: 治疗给闪避（斑点）。同一条机制只认**第一次命中的**那一份——
			//: 与 `readSplash` 里「只认第一条命中的」同一个写法。
			if out.DodgeOnHeal == 0 {
				out.DodgeOnHeal = m.Prob
				out.DodgeSeconds = m.Duration
			}
		case hasAtkProb && !hasScale:
			//: 附加治疗（安赛尔）。**第一条直接赋值**，第二条起才走并集公式
			//: `1 − (1−a)(1−b)`——写成 `1 − Π(1−p)` 从空积起算的话，
			//: 单条的 `1 − (1 − 0.07)` 在浮点下是 `0.07000000000000006`：
			//: 值本身无害，但它会让判据里「两边相等」这种最朴素的写法失效。
			p := clamp01(m.Prob)
			if out.ExtraHealProb == 0 {
				out.ExtraHealProb = p
			} else {
				out.ExtraHealProb = 1 - (1-out.ExtraHealProb)*(1-p)
			}
		case hasProb && hasScale:
			//: 概率强化当次攻击（克洛丝／月见夜）：期望倍率。
			out.ProcFactor *= 1 + clamp01(m.Prob)*(m.ProcScale-1)
		}
	}
	sort.Strings(unknown)
	return out, unknown
}

// talentEffectsUsed 报告「这份效果集合里哪几项真的非零」——给痕迹与覆盖账用。
// 它回答的是「这条机制的哪一半真的动了」，比「键存在」强。
func talentEffectsUsed(e talentEffects) []string {
	out := []string{}
	add := func(cond bool, name string) {
		if cond {
			out = append(out, name)
		}
	}
	add(e.DeploySP != 0, "sp")
	add(e.ProcFactor != 1.0, "proc")
	add(e.ExtraHealProb != 0, "extra_heal")
	add(e.DodgeOnHeal != 0, "dodge_on_heal")
	add(e.DodgeSeconds != 0, "dodge_seconds")
	return out
}

// clamp01 把一个概率夹进 [0,1]。黑板里的数不保证是概率——同名字段在不同
// 天赋里存过别的量（本仓记过 `attack@sluggish` 存的是秒数）。夹一次是**守卫**：
// 夹到了说明数据与假设不符，但至少不会造出一个大于 1 的倍率或负概率。
func clamp01(p float64) float64 {
	if math.IsNaN(p) {
		return 0
	}
	return math.Min(1.0, math.Max(0.0, p))
}
