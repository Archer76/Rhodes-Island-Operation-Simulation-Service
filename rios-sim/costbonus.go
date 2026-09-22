package main

import "strings"

// costbonus.go：初始部署费用天赋（丙阶段四·第二十批）。
//
// 权威是 `battle/talents.py:714-728` 的 `squad_cost_bonus`：
//
//	只看**单键 `cost`** 的天赋——把黑板里 `$` 开头的键滤掉之后，
//	剩下的签好等于 `["cost"]` 才算，数额取该键的值；否则不算。
//
// 「键多了就不认」是**有意的保守**：`cost` 与别的键同时出现时更可能是
// 「费用降低 / 费用上限」之类，那属于没建模的范畴——宁可返回 0 也不猜。
//
// ★ 为什么它排在 `deploys` 前面：排程的起始费用是
// `initial_cost + Σ squad_cost_bonus(全队天赋)`（`verify.py:403-405`）。
// 少了它，带这类天赋的队伍**每一次落地时刻都会偏**，而模拟照常给判决。
// 它是 `deploys` 与 `skill_uses` 两个键共同的前置。

// SquadCostBonus 复刻 `squad_cost_bonus`。
//
// `boards` 是每名干员的天赋黑板（键 → 数值）。`$` 开头的键是**写法标记**
// 而非条目，滤掉后再判签。
func SquadCostBonus(boards []map[string]float64) float64 {
	total := 0.0
	for _, bb := range boards {
		sig := []string{}
		for k := range bb {
			if !strings.HasPrefix(k, "$") {
				sig = append(sig, k)
			}
		}
		if len(sig) == 1 && sig[0] == "cost" {
			total += bb["cost"]
		}
	}
	return total
}
