// talentpanel.go：**天赋的面板倍率**——按黑板键把天赋折进面板。
//
// ## 为什么要有这个文件
//
// 2026-09-24 现算（`akdb`，2649 条天赋行）：**212 / 460 位** `char_` 干员的天赋带面板键
// （`atk`×383 ／ `def`×157 ／ `max_hp`×78 ／ …），而**两台引擎原来一个都不折**。
// 实测一例：玫兰莎 E1L55／信 100／潜 6 的 `atk` 在两侧都是 **828**（＝基底 738 ＋信赖 65
// ＋潜能 25），按天赋「攻击提升 +4%」应是 **861.1**。
//
// 博士 2026-09-24 定：**Go 要折进去**（「不用管 Python，只做 Go 侧」）。
// ⇒ 这会与冻结的 Python 大面积分道扬镳，必须具名登记（见 `docs/three-star-modelling.md`）。
//
// ## 为什么复用 `skilleffects`
//
// 天赋黑板与技能黑板**共用**那批键（`atk`／`def`／`max_hp`／`attack_speed`／`cost` …）
// ——这是量出来的（见 `docs/three-star-modelling.md` §5）。所以这里**复用**
// `ApplyBlackboard`，不是第二套代码。博士要的模块化：加一名干员不改判定逻辑。
//
// ## 只取哪几个键，为什么
//
// | 键 | 折不折 | 为什么 |
// | --- | --- | --- |
// | `atk` / `def` / `max_hp` | **折** | 本文件的任务；原来两侧都没折 |
// | `attack_speed` | **不折** | 已由 `attackSpeedBonus`（`operator_aspd.go`）那条具名 finder 管着，再折一遍＝同一个量两处各算一次 |
// | `cost` | **不折** | 它改的是**部署费用**（`deploycost.go`），不是面板 |
// | 其余 | **不折** | 不是面板量（`prob`／`atk_scale`／`duration` …） |
package main

import "encoding/json"

// talentPanelMods 把**这一练度下真正生效的**天赋逐条过一遍键表，只取面板三键。
//
// 多个天赋组同时给同一个键时**相乘叠加**（各自 ×(1+v)）——这与「先各自算再相乘」是
// 同一个结果，且顺序无关；加法叠加会在两个 +4% 上给出 +8% 而不是 +8.16%，
// 而游戏里的天赋是**各自一条乘式**。
func talentPanelMods(talents []json.RawMessage, elite, level, potential int) skillMods {
	out := skillMods{}
	for _, t := range resolveTalents(talents, elite, level, potential) {
		if len(t.Blackboard) == 0 {
			continue
		}
		m, _ := ApplyBlackboard(t.Blackboard)
		//: ⚠ `ApplyBlackboard` 会给 `AtkScale=1`／`Times=1` 这样的**缺省值**，
		//: 这里只取三个百分比键，别的**一律不看**——免得把技能的语义（倍率、连击）
		//: 误当成天赋的面板加成。
		out.ATKPct = mulPct(out.ATKPct, m.ATKPct)
		out.DEFPct = mulPct(out.DEFPct, m.DEFPct)
		out.MaxHPPct = mulPct(out.MaxHPPct, m.MaxHPPct)
	}
	return out
}

// mulPct 把两条「＋v 的比例」叠加成一条：`(1+a)(1+b) − 1`。
func mulPct(a, b float64) float64 {
	if a == 0 {
		return b
	}
	if b == 0 {
		return a
	}
	return (1+a)*(1+b) - 1
}
