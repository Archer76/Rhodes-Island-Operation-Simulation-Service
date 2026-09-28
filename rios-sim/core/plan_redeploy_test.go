package core

// plan_redeploy_test.go：计划层对**同一干员二次部署**的处置（博士 2026-09-29 定的规则）。
//
// 规则：「不允许一个干员**同时在场上**出现两次，但如果被击倒／撤退回到待部署区、
// 且再部署冷却结束，则可以再次部署。」
//
// 这条规则**是运行期的**，计划层判不了（要知道「死没死」、「离场多久了」）⇒ 计划层
// **不再拦**，真值交给模拟器（`sim.go` 两道具名拒收，端到端判据见
// `rios-sim/redeploy_test.go`）。本文件钉住的是**改动边界**：
//
//	· 二次部署 ⇒ **放**（带不带撤退都放：阵亡那条路计划层同样看不见）；
//	· 同格重叠 ⇒ **仍拒**（两个模拟器都不校验占格，放行会静默重叠）；
//	· 撤退／开技能给了没部署过的人 ⇒ **仍拒**（这两条计划层判得了）。
//
// ⚠ 这是与原版（`ak_tactic/plan.py:270-274`）的一处**刻意分歧**，不是漏改：
// 那一条由 `tools/check_plan_go.py` 的「同一人部署两次」按 `go-accept-only` 登记。

import (
	"encoding/json"
	"strings"
	"testing"
)

func deployAt(op string, pos [2]int) DeployOrder {
	return DeployOrder{Operator: op, Position: pos, Direction: "Right", Skill: 0}
}

// TestValidateAllowsRedeploy 二次部署**放行**——两条都是正例，连「没撤退」那条也放。
//
// 为什么「没撤退」也算正例：计划层看不见阵亡，**拦它就是替模拟器判死**
// （骗伤位「落地→被击倒→冷却过后再落」是一条正常打法）。
func TestValidateAllowsRedeploy(t *testing.T) {
	base := PlayPlan{Stage: "main_01-07", Deploys: []DeployOrder{
		deployAt("砾", [2]int{2, 3}),
		deployAt("砾", [2]int{4, 3}), //: 换一格再上
	}}
	//: ① 带撤退：撤了再上（冷却够不够是模拟器的事）
	withRetreat := base
	withRetreat.Retreats = []RetreatOrder{{Operator: "砾", Time: 30}}
	if err := withRetreat.Validate(); err != nil {
		t.Errorf("撤退后再部署被计划层拦下了：%v", err)
	}
	//: ② 不带撤退：阵亡那条路（计划层看不见，不许拦）
	if err := base.Validate(); err != nil {
		t.Errorf("二次部署（未排撤退）被计划层拦下了：%v", err)
	}
	//: ③ 三次部署也放（次数不设限——每次都在场上/冷却上判）
	three := PlayPlan{Stage: "main_01-07", Deploys: []DeployOrder{
		deployAt("砾", [2]int{2, 3}),
		deployAt("砾", [2]int{4, 3}),
		deployAt("砾", [2]int{5, 3}),
	}}
	if err := three.Validate(); err != nil {
		t.Errorf("三次部署被计划层拦下了：%v", err)
	}
}

// TestValidateRefusesSameTile 同格重叠**仍拒**——正反两侧都要看：
//
//	· 两个**不同**干员挤同一格 ⇒ 拒（这一条是原版就有的）；
//	· 同一干员**撤了再上同一格** ⇒ **也拒**（副作用，具名登记：要放开得先在模拟器
//	  里加一条具名占格拒收，现在两侧都不校验占格）。
func TestValidateRefusesSameTile(t *testing.T) {
	diff := PlayPlan{Stage: "main_01-07", Deploys: []DeployOrder{
		deployAt("甲", [2]int{1, 1}),
		deployAt("乙", [2]int{1, 1}),
	}}
	err := diff.Validate()
	if err == nil || !strings.Contains(err.Error(), "两个干员挤在同一格") {
		t.Errorf("两个干员同格：err = %v，应当拒「两个干员挤在同一格」", err)
	}
	same := PlayPlan{Stage: "main_01-07", Deploys: []DeployOrder{
		deployAt("砾", [2]int{1, 1}),
		deployAt("砾", [2]int{1, 1}),
	}}
	same.Retreats = []RetreatOrder{{Operator: "砾", Time: 30}}
	err = same.Validate()
	if err == nil || !strings.Contains(err.Error(), "两个干员挤在同一格") {
		t.Errorf("同一人同格再上：err = %v，应当仍拒（占格无人校验）", err)
	}
}

// TestValidateStillRefusesUnknownOperator 负对照：两条**判得了**的仍然拒——
// 放开的只是「重复」，不是整套校验。
func TestValidateStillRefusesUnknownOperator(t *testing.T) {
	p := PlayPlan{Stage: "main_01-07", Deploys: []DeployOrder{deployAt("甲", [2]int{1, 1})}}
	p.Retreats = []RetreatOrder{{Operator: "丙", Time: 1}}
	if err := p.Validate(); err == nil || !strings.Contains(err.Error(), "撤退了没部署过的干员") {
		t.Errorf("撤退没部署过的人：err = %v，应当拒", err)
	}
	q := PlayPlan{Stage: "main_01-07", Deploys: []DeployOrder{deployAt("甲", [2]int{1, 1})}}
	q.Skills = []SkillOrder{{Operator: "丙", Time: 1, Slot: 1}}
	if err := q.Validate(); err == nil || !strings.Contains(err.Error(), "给没部署的干员开技能") {
		t.Errorf("给没部署的人开技能：err = %v，应当拒", err)
	}
}

// TestParsePlanAcceptsRedeployJSON 端到端的**入口**判据：原文里的二次部署不许在
// `ParsePlan` 这一层就被打回（`BuildSpecQuery`／`sim` 的查询形式都走它）。
func TestParsePlanAcceptsRedeployJSON(t *testing.T) {
	var obj map[string]json.RawMessage
	if err := json.Unmarshal([]byte(`{
		"stage": "main_01-07",
		"deploys": [
			{"operator": "砾", "position": [2,3], "direction": "Right"},
			{"operator": "砾", "position": [4,3], "direction": "Right", "time": 120}
		],
		"retreats": [{"operator": "砾", "time": 40}]
	}`), &obj); err != nil {
		t.Fatalf("夹具 JSON 坏了：%v", err)
	}
	p, err := ParsePlan(obj)
	if err != nil {
		t.Fatalf("ParsePlan 把二次部署的计划打回了：%v", err)
	}
	if len(p.Deploys) != 2 || len(p.Retreats) != 1 {
		t.Errorf("解析结果 = %d 条部署 / %d 条撤退，应当是 2 / 1",
			len(p.Deploys), len(p.Retreats))
	}
	if p.Deploys[1].Time == nil || *p.Deploys[1].Time != 120 {
		t.Errorf("第二条部署的 time 没读进来：%v", p.Deploys[1].Time)
	}
}
