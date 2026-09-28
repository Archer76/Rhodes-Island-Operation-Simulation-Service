package main

// stagebranch_test.go：**支线出怪动作的 `interval` 口径**（2026-09-27）。
//
// 为什么单开一节：Python 参照里两条路**故意**用了不同的 `or` 兜底，
//
//	出怪（`gamedata/stage.py::_parse_spawns`）   ：interval=float(a.get("interval", 1.0) or 0.0)
//	支线（`gamedata/stage.py::_parse_branches`）：interval=float(a.get("interval", 1.0) or 1.0)
//
// 差别只在**显式 0**：出怪保留 0，支线被 `or` 顶成 1.0。Go 原来两条路都抄原值，
// 于是 `act26side_ex08` 的 `branches.cledub_summon[0]` 与 `act49side_10` 的
// `branches.left_hand_room_branch[5]`（关卡文件里明写着 `"interval": 0`）
// 各红一处 —— 连带 `act26side_ex08#f#` 这个同内容别名，共三处。
//
// 这一节盯三件事：
//  1. 支线：缺键 ⇒ 1.0、显式 0 ⇒ 1.0、非零 ⇒ 原值；
//  2. **负对照**：出怪那条路**必须仍然保留显式 0** —— 谁要是"顺手统一"成同一个口径，
//     这一条当场红（两条路的口径分叉是**照证据**抄的，不是笔误）；
//  3. `parseBranches` 走真解析路径也要成立（不只是在方法上成立）。

import (
	"encoding/json"
	"testing"
)

func f(v float64) *float64 { return &v }

func TestBranchIntervalDefault(t *testing.T) {
	cases := []struct {
		what string
		got  float64
		want float64
	}{
		{"支线·缺键", waveAction{}.branchInterval(), 1.0},
		{"支线·显式 0（照 Python 的 `or 1.0`）", waveAction{Interval: f(0)}.branchInterval(), 1.0},
		{"支线·非零原值", waveAction{Interval: f(3.5)}.branchInterval(), 3.5},
		{"支线·负值原值", waveAction{Interval: f(-2)}.branchInterval(), -2},
		//: ★ 负对照：出怪那一支**不许**跟着变
		{"出怪·缺键", waveAction{}.interval(), 1.0},
		{"出怪·显式 0（`or 0.0` ⇒ 保留 0）", waveAction{Interval: f(0)}.interval(), 0},
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
	    {"actionType": "SPAWN", "key": "enemy_3007_y", "count": 1, "routeIndex": 1}
	  ]}]},
	  "no_spawn": {"phases": [{"actions": [{"actionType": "MOVE", "key": "enemy_3008_z"}]}]}
	}`)
	out, err := parseBranches(raw)
	if err != nil {
		t.Fatalf("parseBranches 报错：%v", err)
	}
	acts := out["cledub_summon"]
	if len(acts) != 3 {
		t.Fatalf("支线动作条数 = %d、期望 3（非 SPAWN 的应被跳过，但那是另一支线）", len(acts))
	}
	want := []float64{1.0, 2.5, 1.0} //: 显式 0 → 1.0；2.5 原值；缺键 → 1.0
	for i, w := range want {
		if acts[i].Interval != w {
			t.Errorf("动作[%d].Interval = %v、期望 %v", i, acts[i].Interval, w)
		}
	}
	if _, ok := out["no_spawn"]; ok {
		t.Errorf("整条支线都不是 SPAWN ⇒ 不该出现在结果里（Python 只在 acts 非空时收）")
	}
	//: 负对照：解析器真的在读这份 raw（改一个数必须跟着变）
	raw2 := json.RawMessage(`{"b": {"phases": [{"actions": [
	    {"actionType": "SPAWN", "key": "k", "interval": 7, "routeIndex": 0}]}]}}`)
	out2, err := parseBranches(raw2)
	if err != nil {
		t.Fatalf("parseBranches(负对照) 报错：%v", err)
	}
	if out2["b"][0].Interval != 7 {
		t.Errorf("负对照失败：非零区间没被读进去（得 %v）—— 说明上面那几条读数可能根本没走到解析",
			out2["b"][0].Interval)
	}
}
