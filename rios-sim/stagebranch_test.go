package main

// stagebranch_test.go：**照数据来写** —— 支线出怪动作的 `interval`（2026-09-28）。
//
// ## 这一节钉的是什么
//
// 博士 2026-09-28 定：**Go 是从零写的独立实现，字段按关卡数据原样读**，
// 该是什么样就什么样；Python 参照那边怎么兜底（`stage.py::_parse_branches` 用的是
// `float(a.get("interval", 1.0) or 1.0)`，显式 0 会被 `or` 顶成 1.0）**不是 Go 的口径**。
//
// 实测那一处数据（`act26side_ex08` 的 `branches.cledub_summon[0]`）：
//
//	{"actionType": "SPAWN", "key": "enemy_3005_lpeopl_2", "count": 1,
//	 "preDelay": 0, "interval": 0, "routeIndex": 8}
//
// ⇒ Go 读出 **0**（原样），Python 读出 1.0（它的兜底）。`count=1` 时两边出怪行为相同
// （`interval` 只在 `count>1` 时参与 `第 i 只 = start + preDelay + i × interval`）。
//
// ## 守卫的形状
//
//  1. 有值原样抄（含显式 0、负数、小数）；
//  2. 缺键／显式 null ⇒ 缺省 1.0（数据没写值，引擎总要有个默认，这个默认是引擎的、不是抄谁的）；
//  3. **负对照**：显式 0 必须读成 0 —— 谁哪天又把它"兜"成 1.0（复刻 Python 那个 `or`），
//     这一条当场红；并且走 `parseBranches` 的真解析路径再验一次，避免只在方法上成立。

import (
	"encoding/json"
	"testing"
)

func f(v float64) *float64 { return &v }

func TestBranchIntervalReadsDataAsIs(t *testing.T) {
	cases := []struct {
		what string
		got  float64
		want float64
	}{
		{"缺键 ⇒ 缺省 1.0", waveAction{}.interval(), 1.0},
		{"显式 0 ⇒ 0（照数据，**不许**兜成 1.0）", waveAction{Interval: f(0)}.interval(), 0},
		{"非零原值", waveAction{Interval: f(3.5)}.interval(), 3.5},
		{"负数原值", waveAction{Interval: f(-2)}.interval(), -2},
		{"很大的值原值", waveAction{Interval: f(120)}.interval(), 120},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("%s：得 %v、期望 %v", c.what, c.got, c.want)
		}
	}
}

func TestParseBranchesInterval(t *testing.T) {
	raw := json.RawMessage(`{
	  "cledub_summon": {"phases": [{"actions": [
	    {"actionType": "SPAWN", "key": "enemy_3005_lpeopl_2", "count": 1, "interval": 0, "routeIndex": 8},
	    {"actionType": "SPAWN", "key": "enemy_3006_x", "count": 2, "interval": 2.5, "routeIndex": 3},
	    {"actionType": "SPAWN", "key": "enemy_3007_y", "count": 1, "routeIndex": 1},
	    {"actionType": "SPAWN", "key": "enemy_3008_z", "count": 1, "interval": null, "routeIndex": 2}
	  ]}]},
	  "no_spawn": {"phases": [{"actions": [{"actionType": "MOVE", "key": "enemy_3009_w"}]}]}
	}`)
	out, err := parseBranches(raw)
	if err != nil {
		t.Fatalf("parseBranches 报错：%v", err)
	}
	acts := out["cledub_summon"]
	if len(acts) != 4 {
		t.Fatalf("支线动作条数 = %d、期望 4", len(acts))
	}
	want := []float64{0, 2.5, 1.0, 1.0} //: 显式 0 保留；2.5 原值；缺键 1.0；显式 null 1.0
	for i, w := range want {
		if acts[i].Interval != w {
			t.Errorf("动作[%d].Interval = %v、期望 %v（照数据来写）", i, acts[i].Interval, w)
		}
	}
	if _, ok := out["no_spawn"]; ok {
		t.Errorf("整条支线都不是 SPAWN ⇒ 不该出现在结果里")
	}
	//: 负对照：解析器真的在读这份 raw（改一个数必须跟着变）
	raw2 := json.RawMessage(`{"b": {"phases": [{"actions": [
	    {"actionType": "SPAWN", "key": "k", "interval": 7, "routeIndex": 0}]}]}}`)
	out2, err := parseBranches(raw2)
	if err != nil {
		t.Fatalf("parseBranches(负对照) 报错：%v", err)
	}
	if out2["b"][0].Interval != 7 {
		t.Errorf("负对照失败：非零区间没被读进去（得 %v）", out2["b"][0].Interval)
	}
}
