// skilleffects.go：**键驱动的效果模型**——技能与天赋**共用一张键表**。
//
// ## 为什么是「键」而不是「干员名 / 技能名」
//
// 2026-09-24 现算（`akdb`，见 `docs/three-star-modelling.md` §5）：
//
//	技能黑板：全库 964 个不同键，三星 17 位只用 **10** 个；
//	天赋黑板：全库 568 个不同键（2649 条天赋行），三星 17 位只用 **10** 个；
//	两边**共用** atk／def／max_hp／attack_speed／cost／atk_scale／prob／duration。
//
// ⇒ 按名字硬编码（`if op.Name == "玫兰莎"`）每加一名干员就要改一次判定逻辑，
// 而按**键**驱动则「加一名新干员只要它的键在表里」。这就是博士要的模块化。
//
// ## 两条硬纪律
//
//  1. **认不出来的键必须报出来**：`ApplyBlackboard` 返回**未识别键清单**，调用方要把它
//     落进覆盖账（`OperatorsCoveredKeys` 那一族）。静默忽略＝把「没建」伪装成「没有这条机制」，
//     本仓在好几处栽过这个形状。
//  2. **不按名字特判**。真要按名字认（例如「同一机制换了键名实现」那种历史包袱），
//     也写在**注记**里而不是判定里，并让它出现在覆盖账上。
//
// ## 口径（每条键做的是**哪一件事**）
//
// 键值一律来自技能/天赋的 `blackboard`（`skillmeta.go` 已按「每个有 key 的项都落一个数值键、
// 另有 `$key` 落 valueStr」的口径解析好）。百分比键（`atk`／`def`／`max_hp`）在数据里是**小数**
// （`0.5` = +50%），不是 50。
package main

import (
	"math"
	"sort"
)

// skillMods 是一份黑板算出来的**修正集合**。零值＝「这条键没出现」。
type skillMods struct {
	//: 百分比族：`atk`／`def`／`max_hp` —— 数据里是小数（0.5 = +50%）。
	ATKPct   float64
	DEFPct   float64
	MaxHPPct float64

	//: 攻速（`attack_speed`，加**平坦值**）与基础攻击间隔（`base_attack_time`，秒）。
	AttackSpeed    float64
	BaseAttackTime float64

	//: 开启那一刻回的费用（`cost`）。
	CostGain float64

	//: 自疗（`heal_scale`，按**生命上限的比例**）。
	HealScale float64

	//: 单次攻击倍率（`atk_scale`）与连击次数（`times`）。
	AtkScale float64
	Times    int

	//: 射程前移（`ability_range_forward_extend`，格）与溅射半径缩放（`attack@range_scale`）。
	RangeForwardExtend float64
	SplashRangeScale   float64

	//: 触发族：`prob`（触发概率）与它触发时把攻击力改成几倍。
	//: ⚠ 同一个 `atk_scale` 在两个上下文里意思不同——技能里是「这一击的倍率」（恒常），
	//: 天赋里（与 `prob` 同现）是「触发后那一击的倍率」（概率）。所以这里分开存，
	//: 由 `applyMods` 决定怎么用，**不在解析阶段合并**。
	Prob      float64
	ProcScale float64

	//: 技力（`sp`，例如天赋「快速技能使用：部署后立即获得 15 点技力」）与持续时间（`duration`，秒）。
	SP       float64
	Duration float64
}

// skillKeyTable 是**首发表**：已经实现的那 15 个键，以及每个键「做的是哪一件事」。
//
// 这张表有两个用途，缺一不可：
//   - 解析时按它取数（`ApplyBlackboard`）；
//   - **覆盖账**：报告「这一份黑板里几个键被认了、哪几个没被认」。
//
// ⚠ 表外的键**不是错误**——全库 964 个技能键只实现了 15 个。它们是**待办**，
// 所以要**具名**出现在未识别清单里，而不是被忘掉。
var skillKeyTable = map[string]string{
	"atk":                          "攻击力 ×(1+v)",
	"def":                          "防御力 ×(1+v)",
	"max_hp":                       "生命上限 ×(1+v)",
	"attack_speed":                 "攻速 +v（平坦值）",
	"base_attack_time":             "基础攻击间隔改为 v 秒",
	"cost":                         "开启/部署时费用 +v",
	"heal_scale":                   "自疗：生命上限 ×v",
	"atk_scale":                    "单次攻击倍率 ×v（有 prob 时是触发后的倍率）",
	"times":                        "连击次数 = v",
	"ability_range_forward_extend": "射程前移 v 格",
	"attack@range_scale":           "溅射半径 ×v",
	"prob":                         "触发概率 v（与 atk_scale／attack@prob 同现）",
	"attack@prob":                  "同上，攻击触发那一支",
	"sp":                           "技力 +v",
	"duration":                     "持续时间 v 秒",
}

// SkillKeyTable 给外部（覆盖账报告）用的一份只读清单。
func SkillKeyTable() map[string]string {
	out := make(map[string]string, len(skillKeyTable))
	for k, v := range skillKeyTable {
		out[k] = v
	}
	return out
}

// ⚠ 数值键的取法**复用既有的 `bbFloat`**（`enemy_derive.go:314`，底下是 `toFloat`：
// 数字直接收、字符串尽力解析、其余算取不到）。本模块**不另写一份**——本仓记过
// 「同一个公式两处各写一份，一改就对不上」。所以这里没有第二个 `bbFloat`。
//
// ⚠ `$key` 前缀那条（valueStr）不走它：那是「召唤什么／给哪个装置」的字符串载荷，
// 属于另一层，本模块不管。

// ApplyBlackboard 把一份黑板解析成修正集合，并**具名**返回没认出来的键（已排序去重）。
//
// ⚠ 未识别清单里**不含**以 `$` 开头的键：那是 valueStr 的落点（字符串载荷），
// 由别的层负责，不是「漏掉的数值键」。
func ApplyBlackboard(bb map[string]any) (skillMods, []string) {
	m := skillMods{AtkScale: 1.0, Times: 1}
	var unknown []string
	seen := map[string]bool{}
	for k := range bb {
		if len(k) > 0 && k[0] == '$' {
			continue
		}
		if _, ok := skillKeyTable[k]; !ok {
			if !seen[k] {
				seen[k] = true
				unknown = append(unknown, k)
			}
		}
	}
	if _, ok := bb["atk"]; ok {
		m.ATKPct = bbFloat(bb, "atk")
	}
	if _, ok := bb["def"]; ok {
		m.DEFPct = bbFloat(bb, "def")
	}
	if _, ok := bb["max_hp"]; ok {
		m.MaxHPPct = bbFloat(bb, "max_hp")
	}
	if _, ok := bb["attack_speed"]; ok {
		m.AttackSpeed = bbFloat(bb, "attack_speed")
	}
	if _, ok := bb["base_attack_time"]; ok {
		m.BaseAttackTime = bbFloat(bb, "base_attack_time")
	}
	if _, ok := bb["cost"]; ok {
		m.CostGain = bbFloat(bb, "cost")
	}
	if _, ok := bb["heal_scale"]; ok {
		m.HealScale = bbFloat(bb, "heal_scale")
	}
	//: ⚠ `atk_scale` 与 `times` 要**先问在不在**再取：它们的「缺省」不是 0
	//: （分别是 1.0 与 1）——直接赋值会把「没有这条键」写成「倍率 0／连击 0 次」，
	//: 那正好是「打不死人」与「不出手」两种最坏的症状。
	if _, ok := bb["atk_scale"]; ok {
		m.AtkScale = bbFloat(bb, "atk_scale")
	}
	if _, ok := bb["times"]; ok {
		m.Times = int(math.Round(bbFloat(bb, "times")))
	}
	if _, ok := bb["ability_range_forward_extend"]; ok {
		m.RangeForwardExtend = bbFloat(bb, "ability_range_forward_extend")
	}
	if _, ok := bb["attack@range_scale"]; ok {
		m.SplashRangeScale = bbFloat(bb, "attack@range_scale")
	}
	if _, ok := bb["prob"]; ok {
		m.Prob = bbFloat(bb, "prob")
	}
	if _, ok := bb["attack@prob"]; ok {
		m.Prob = bbFloat(bb, "attack@prob")
	}
	if m.Prob > 0 {
		//: 触发族：`prob` 与 `atk_scale` 同现时，后者是「触发后那一击的倍率」。
		m.ProcScale = m.AtkScale
	}
	if _, ok := bb["sp"]; ok {
		m.SP = bbFloat(bb, "sp")
	}
	if _, ok := bb["duration"]; ok {
		m.Duration = bbFloat(bb, "duration")
	}
	sort.Strings(unknown)
	return m, unknown
}

// applyMods 把一份修正集合盖到一组基准数值上。
//
// ⚠ 这里**只做算术**，不判断「这是技能还是天赋」——调用方按自己的口径决定用哪几个分量。
// 例如天赋的「攻击提升 +4%」与技能的「攻击力强化 +50%」都只是 `ATKPct`，
// 差别在**谁把它乘进去**（天赋进常驻面板、技能进 active 快照），那是调用方的口径。
func applyMods(baseATK, baseDEF, baseMaxHP, baseASPD, baseInterval float64,
	m skillMods) (atk, def, maxHP, aspd, interval float64) {
	atk = baseATK * (1 + m.ATKPct)
	def = baseDEF * (1 + m.DEFPct)
	maxHP = baseMaxHP * (1 + m.MaxHPPct)
	aspd = baseASPD + m.AttackSpeed
	if m.BaseAttackTime > 0 {
		interval = m.BaseAttackTime * 100.0 / math.Max(opsAspdMin, aspd)
	} else {
		interval = baseInterval
		if m.AttackSpeed != 0 {
			interval = baseInterval * baseASPD / math.Max(opsAspdMin, aspd)
		}
	}
	return
}

// modsUsed 报告「这份修正集合里哪几个分量是非零的」——给痕迹与覆盖账用。
// 它回答的是「这条机制的哪一半真的动了」，比「键存在」强。
func modsUsed(m skillMods) []string {
	out := []string{}
	add := func(cond bool, name string) {
		if cond {
			out = append(out, name)
		}
	}
	add(m.ATKPct != 0, "atk")
	add(m.DEFPct != 0, "def")
	add(m.MaxHPPct != 0, "max_hp")
	add(m.AttackSpeed != 0, "attack_speed")
	add(m.BaseAttackTime != 0, "base_attack_time")
	add(m.CostGain != 0, "cost")
	add(m.HealScale != 0, "heal_scale")
	add(m.AtkScale != 1.0, "atk_scale")
	add(m.Times > 1, "times")
	add(m.RangeForwardExtend != 0, "ability_range_forward_extend")
	add(m.SplashRangeScale != 0, "attack@range_scale")
	add(m.Prob != 0, "prob")
	add(m.SP != 0, "sp")
	add(m.Duration != 0, "duration")
	return out
}
