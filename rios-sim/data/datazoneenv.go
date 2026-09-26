package data

// datazoneenv.go：TUI 选关的**第二层**——一个 zone 里**实际存在**的环境分层。
//
// 参照实现：`ak_tactic/tui/data.py:596-627`（`zone_envs`）。逐条口径见
// `out/zz_tui_data_spec.md` §5。
//
// ## 两条必须照抄的口径
//
//  1. **条数含四星限定版**（不过滤任何后缀）。理由写在参照实现里：
//     不含的话菜单报 24、下一层列表却给 41 行，**看着像筛错了**。
//  2. **全是 `NONE` 的章节这一层不该出现** —— 本函数此时返回**空表**；
//     而界面上还有第二道闸：显示条件是 **`len(envs) > 1`**（`tui/app.py:2592`），
//     **不是 `> 0`**（只有一个分层的章节也不显示这一层菜单）。
//
// ## 与 Python 的一处已知差（同 datachapter2.go 那条登记）
//
// 参照实现的计数**含 `#s`**，而本实现因博士 2026-09-26 裁定排除六星档。
// ⚠ 但**这批金标恰好不受影响**：有环境分层的那 6 个 zone 全在第 9～14 章，
// 而 45 个 `#s` 全在第 15～17 章 ⇒ 两边应当**逐格相同**（已用金标验，见测试）。

import (
	"sort"
	"strings"
)

// ZoneEnv 是一个环境分层。
type ZoneEnv struct {
	Env    string //: EASY / NORMAL / TOUGH / ALL
	Label  string //: 剧情体验 / 标准实战 / 磨难险地 / 通用
	Levels int    //: 该 (zone, diff_group) 的关卡行数
}

// ZoneEnvs 复刻 `zone_envs`：按 `envOrder` 排，空／`NONE` 的直接不计。
//
// 未知的 `diff_group` 值**不静默丢**：附在末尾（按名排序）并在测试里断言「本机库里不存在」。
func ZoneEnvs(zoneID string, stages []StageRecord) []ZoneEnv {
	counts := map[string]int{}
	for _, r := range stages {
		if r.ZoneID != zoneID {
			continue
		}
		g := strings.ToUpper(strings.TrimSpace(r.DiffGroup))
		if g == "" || g == "NONE" {
			continue
		}
		counts[g]++
	}
	out := []ZoneEnv{}
	known := map[string]bool{}
	for _, e := range envOrder {
		known[e] = true
		if n, ok := counts[e]; ok {
			out = append(out, ZoneEnv{Env: e, Label: envLabels[e], Levels: n})
		}
	}
	//: 表外的（若有）：排在已知的后面，名字原样带着 —— 让它在读数里**看得见**。
	extra := []string{}
	for g := range counts {
		if !known[g] {
			extra = append(extra, g)
		}
	}
	sort.Strings(extra)
	for _, g := range extra {
		out = append(out, ZoneEnv{Env: g, Label: envLabels[g], Levels: counts[g]})
	}
	return out
}

// ZoneEnvsShown 是**界面层那道闸**：显示这一层菜单的条件是 `len(envs) > 1`
// （`ak_tactic/tui/app.py:2592`）—— 注意**不是 `> 0`**：只有一个分层的章节不显示。
func ZoneEnvsShown(envs []ZoneEnv) bool { return len(envs) > 1 }
