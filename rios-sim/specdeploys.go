package main

import (
	"fmt"
	"math"
	"sort"
)

// specdeploys.go：规格里的 `deploys` 那一串（丙阶段四·第二十三批）。
//
// 权威是两处拼起来的：
//
//   - **排时刻**：`verify.py:393-480`（费用模型，与 MAA 自动作战同规则——
//     「钱够了就下」）；
//   - **成键**：`spec.py:1232-1241`（按 `time` 排序、写 `index` 与 `char_id`、
//     `cost`、`auto_skill`）。
//
// ## 费用模型逐行
//
//	rate   = stage.options.cost_increase_time      ← **原始值**
//	budget = stage.options.initial_cost + Σ squad_cost_bonus(全队天赋)
//	now    = 0
//	每条部署：
//	  time 是 None（按费用自动排）：
//	      need = max(0, cost − budget); at = now + need × rate
//	      budget = budget + need − cost
//	  给了显式时刻：
//	      at = time; 若 at > now 则 budget += (at − now) ÷ rate
//	      budget = max(0, budget − cost)
//	  now = at
//
// ⚠ **`rate` 是原始值，不是 `stage_env` 给规格的那个 `cost_time`**：后者被
// 「四星档费用回复翻倍」的 `cbuff_cost_recovery.scale` **除过**（见 `stageenv.go`）。
// 两个数在四星档下不同。拿错的那一个当 rate，每一条落地时刻都会偏，
// 而模拟照常给判决——**没有任何判据会响**，除了这一条。
//
// ⚠ `time` 为 None 时 `budget` 可以变成**负数**（`need` 只把差额补到够，
// 于是 `budget + need − cost` 恰为 0；但 `cost` 大于 `need` 的差额部分
// 会让它落回 0 以下的情形出现在初值极小的时候）。原版不夹这一支，
// 这里也不夹——**照抄**。

// SpecDeploy 是 `deploys` 里的一条。
type SpecDeploy struct {
	Time      float64 `json:"time"`
	Index     int     `json:"index"`
	CharID    string  `json:"char_id"`
	Cost      int     `json:"cost"`
	AutoSkill bool    `json:"auto_skill"`
}

// BuildDeploys 造 `deploys` 那一串。
func BuildDeploys(plan PlayPlan, roster RosterRead, stage *Stage) ([]SpecDeploy, error) {
	rate := stage.Options.CostIncreaseTime
	if rate == 0 {
		//: 原版在这一支会 `ZeroDivisionError`；Go 的浮点除零静默给 ±Inf，
		//: 所以这里**必须**自己拦——否则时刻会变成 Inf 而一路不报错。
		return nil, fmt.Errorf("关卡的 cost_increase_time 是 0，费用速率无法折算")
	}
	budget := stage.Options.InitialCost
	type row struct {
		at   float64
		spec SpecDeploy
	}
	rows := make([]row, 0, len(plan.Deploys))
	now := 0.0
	for _, d := range plan.Deploys {
		e, err := ResolveLoadout(d, roster)
		if err != nil {
			return nil, err
		}
		trust := 0.0
		if e.Trust != nil {
			trust = float64(*e.Trust)
		}
		module := ""
		if e.Module != nil {
			module = *e.Module
		}
		modLevel := 0
		if e.ModuleLevel != nil {
			modLevel = *e.ModuleLevel
		}
		cost, err := CostOf(OperatorCalcConfig{
			CharID: e.CharID, Elite: e.Elite, Level: e.Level, Trust: trust,
			Potential: e.Potential, Module: module, ModuleLevel: modLevel,
		})
		if err != nil {
			return nil, fmt.Errorf("%s（%s）的部署费用：%v", d.Operator, e.CharID, err)
		}
		bonus, err := TalentCostBonus(e.CharID, e.Elite, e.Level, e.Potential)
		if err != nil {
			return nil, err
		}
		budget += bonus

		var at float64
		if d.Time == nil {
			need := math.Max(0.0, float64(cost)-budget)
			at = now + need*rate
			budget = budget + need - float64(cost)
		} else {
			at = *d.Time
			if at > now {
				budget += (at - now) / rate
			}
			budget = math.Max(0.0, budget-float64(cost))
		}
		now = at
		rows = append(rows, row{at: at, spec: SpecDeploy{
			Time: at, CharID: e.CharID, Cost: cost, AutoSkill: d.AutoSkill,
		}})
	}
	//: 原版 `sorted(sch.deployments, key=lambda d: d.time)`——**稳定**排序，
	//: 同时刻的两条保持计划里的先后。
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].at < rows[j].at })
	out := make([]SpecDeploy, 0, len(rows))
	for i, r := range rows {
		r.spec.Index = i
		out = append(out, r.spec)
	}
	return out, nil
}

// BuildDeploysFor 从两条路径读入，造 `deploys`（命令用）。
func BuildDeploysFor(planPath, rosterPath string) ([]SpecDeploy, error) {
	plan, err := ReadPlan(planPath)
	if err != nil {
		return nil, err
	}
	var rs RosterRead
	if rosterPath != "" {
		if rs, err = ReadRoster(rosterPath); err != nil {
			return nil, err
		}
	}
	st, err := LoadStage(plan.Stage)
	if err != nil {
		return nil, err
	}
	return BuildDeploys(plan, rs, st)
}
