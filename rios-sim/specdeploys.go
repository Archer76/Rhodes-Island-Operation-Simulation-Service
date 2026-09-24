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

// SpecSkillUse 是 `skill_uses` 里的一条。
//
// 权威 `spec.py:1249-1251` 的 `[{"time": float(u.time), "cell": [x, y]}]`，
// 而 `u` 来自 `sched.skill_uses`——它在 `verify.py:497-501` 被逐条追加：
//
//	for s in plan.skills:                      ← **计划里的顺序**，不排序
//	    _at, pos, _d, _e = deployed[s.operator]  ← 该干员**落地时**的格子
//	    sched.use_skill(pos, s.time)
//
// ⚠ 顺序是**计划给的**，不是按时刻排的：判据若按时刻重排就会与生产规格分叉，
// 而两边都「看着合理」。
type SpecSkillUse struct {
	Time float64 `json:"time"`
	Cell [2]int  `json:"cell"`
}

// BuildSkillUses 造 `skill_uses`（计划顺序）。
func BuildSkillUses(plan PlayPlan) []SpecSkillUse {
	pos := map[string][2]int{}
	for _, d := range plan.Deploys {
		pos[d.Operator] = d.Position
	}
	out := make([]SpecSkillUse, 0, len(plan.Skills))
	for _, s := range plan.Skills {
		p, ok := pos[s.Operator]
		if !ok {
			//: `Plan.validate` 已经拦过「给没部署的干员开技能」，走到这里
			//: 说明校验被绕过了——不静默给 (0,0)，那会变成「在原点开技能」。
			continue
		}
		out = append(out, SpecSkillUse{Time: s.Time, Cell: p})
	}
	return out
}

// DeployRow 是一条**解算完的部署**：练度 ＋ 费用 ＋ 落地时刻 ＋ 计划里的下标。
//
// 为什么单独抽出来（第二十四批 `operators` 要用）：`build_spec` 里 `deploys` 与
// `operators` 是**同一个循环**里的两次 append ——
//
//	for d in sorted(sch.deployments, key=lambda d: d.time):
//	    operators.append(_operator_spec(inp, d))     # 顺序 = 这一串
//	    deploys.append({...})
//
// 所以两个键的**次序口径只能有一份**。各写一遍的症状是「两个键各自看着都合理、
// 但第 7 位起错开一格」——而配错人的面板在判决上只表现为「某个干员数字不对」。
type DeployRow struct {
	//: `plan.Deploys` 里的下标（**排序前**的先后，配对用）。
	PlanIdx   int
	Operator  string
	Position  [2]int
	Direction string
	Entry     LoadoutEntry
	Cost      int
	//: 落地时刻（费用模型算出来的）。排序键。
	At        float64
	AutoSkill bool
	//: 计划里的**技能槽号**（`DeployOrder.Skill`，0–3）。
	//:
	//: ★ 口径（博士 2026-09-24）：**`0` 不等于「不用技能」**——除了一二星干员是真的
	//: 没有技能之外，0 都会选到**玩家的默认技能**；测试期间把 `0` 认定为 `1`。
	//: 绑定发生在 `buildOperatorOut`（走 `OperatorSkillIDs` 把槽号映射成技能 id）。
	Skill int
}

// BuildDeployRows 复刻 `verify.py:393-480` 的费用模型，返回**按落地时刻稳定排序**
// 的行。顺序与 `sorted(sch.deployments, key=lambda d: d.time)` 逐个相同。
func BuildDeployRows(plan PlayPlan, roster RosterRead,
	stage *Stage) ([]DeployRow, error) {
	rate := stage.Options.CostIncreaseTime
	if rate == 0 {
		//: 原版在这一支会 `ZeroDivisionError`；Go 的浮点除零静默给 ±Inf，
		//: 所以这里**必须**自己拦——否则时刻会变成 Inf 而一路不报错。
		return nil, fmt.Errorf("关卡的 cost_increase_time 是 0，费用速率无法折算")
	}
	budget := stage.Options.InitialCost
	rows := make([]DeployRow, 0, len(plan.Deploys))
	now := 0.0
	for i, d := range plan.Deploys {
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
		rows = append(rows, DeployRow{
			PlanIdx: i, Operator: d.Operator, Position: d.Position,
			Direction: d.Direction, Entry: e, Cost: cost, At: at,
			AutoSkill: d.AutoSkill, Skill: d.Skill,
		})
	}
	//: 原版 `sorted(sch.deployments, key=lambda d: d.time)`——**稳定**排序，
	//: 同时刻的两条保持计划里的先后。
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].At < rows[j].At })
	return rows, nil
}

// BuildDeploys 造 `deploys` 那一串。
func BuildDeploys(plan PlayPlan, roster RosterRead, stage *Stage) ([]SpecDeploy, error) {
	rows, err := BuildDeployRows(plan, roster, stage)
	if err != nil {
		return nil, err
	}
	out := make([]SpecDeploy, 0, len(rows))
	for i, r := range rows {
		out = append(out, SpecDeploy{
			Time: r.At, Index: i, CharID: r.Entry.CharID, Cost: r.Cost,
			AutoSkill: r.AutoSkill,
		})
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
