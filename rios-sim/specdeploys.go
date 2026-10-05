package main

import (
	"fmt"
)

// specdeploys.go：规格里的 `deploys` 那一串。
// H3: 未写 time 的部署保留运行期费用等待意图，不能在构造期预测
// 技能/撤退/击杀带来的费用。显式 time 保留一次性截止请求。
// 初费天赋按唯一上阵干员汇总一次，环境参数与模拟共用 StageEnv。

// SpecDeploy 是 `deploys` 里的一条。
type SpecDeploy struct {
	Time        float64 `json:"time"`
	Index       int     `json:"index"`
	CharID      string  `json:"char_id"`
	Cost        int     `json:"cost"`
	AutoSkill   bool    `json:"auto_skill"`
	WaitForCost bool    `json:"wait_for_cost,omitempty"`
	PlanOrder   bool    `json:"plan_order,omitempty"`
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

// DeployRow resolves one deployment's loadout, cost, request intent and plan identity.
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
	// Explicit deadline, or earliest eligibility (zero) for an automatic request.
	At        float64
	AutoSkill bool
	//: 计划里的**技能槽号**（`DeployOrder.Skill`，0–3）。
	//:
	//: ★ 口径（博士 2026-09-24）：**`0` 不等于「不用技能」**——除了一二星干员是真的
	//: 没有技能之外，0 都会选到**玩家的默认技能**；测试期间把 `0` 认定为 `1`。
	//: 绑定发生在 `buildOperatorOut`（走 `OperatorSkillIDs` 把槽号映射成技能 id）。
	Skill       int
	WaitForCost bool
}

// BuildDeployRows resolves loadouts in plan order without predicting dynamic DP.
// At is an explicit deadline, or zero eligibility time when WaitForCost is true.
func BuildDeployRows(plan PlayPlan, roster RosterRead,
	stage *Stage) ([]DeployRow, error) {
	return buildDeployRowsWithInputs(plan, roster, stage, nil)
}
func buildDeployRowsWithInputs(plan PlayPlan, roster RosterRead, stage *Stage, inputs *buildInputs) ([]DeployRow, error) {
	rows := make([]DeployRow, 0, len(plan.Deploys))
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
		stats, err := inputs.operatorStats(OperatorCalcConfig{
			CharID: e.CharID, Elite: e.Elite, Level: e.Level, Trust: trust,
			Potential: e.Potential, Module: module, ModuleLevel: modLevel,
		})
		if err != nil {
			return nil, fmt.Errorf("%s（%s）的部署费用：%v", d.Operator, e.CharID, err)
		}
		cost, err := costFromStats(stats)
		if err != nil {
			return nil, fmt.Errorf("%s（%s）的部署费用：%v", d.Operator, e.CharID, err)
		}
		// No predicted affordability time: the simulator owns the live balance.
		at := 0.0
		if d.Time != nil {
			at = *d.Time
		}
		rows = append(rows, DeployRow{
			PlanIdx: i, Operator: d.Operator, Position: d.Position,
			Direction: d.Direction, Entry: e, Cost: cost, At: at,
			AutoSkill: d.AutoSkill, Skill: d.Skill, WaitForCost: d.Time == nil,
		})
	}
	// Preserve plan identity/order. Explicit deadlines are independent at runtime.
	return rows, nil
}

// squadInitialCostBonus counts each deployed character once, before any action.
func squadInitialCostBonus(rows []DeployRow) (float64, error) {
	seen := map[string]DeployRow{}
	total := 0.0
	for _, r := range rows {
		e := r.Entry
		if previous, ok := seen[e.CharID]; ok {
			p := previous.Entry
			if p.Elite != e.Elite || p.Level != e.Level || p.Potential != e.Potential {
				return 0, fmt.Errorf("%s 重复部署的初费天赋练度冲突：计划第%d条 E%d/L%d/P%d，第%d条 E%d/L%d/P%d", e.CharID, previous.PlanIdx+1, p.Elite, p.Level, p.Potential, r.PlanIdx+1, e.Elite, e.Level, e.Potential)
			}
			continue
		}
		seen[e.CharID] = r
		bonus, err := TalentCostBonus(e.CharID, e.Elite, e.Level, e.Potential)
		if err != nil {
			return 0, err
		}
		total += bonus
	}
	return total, nil
}

// BuildDeploys 造 `deploys` 那一串。
func BuildDeploys(plan PlayPlan, roster RosterRead, stage *Stage) ([]SpecDeploy, error) {
	rows, err := BuildDeployRows(plan, roster, stage)
	if err != nil {
		return nil, err
	}
	return deploysFromRows(rows), nil
}

func deploysFromRows(rows []DeployRow) []SpecDeploy {
	out := make([]SpecDeploy, 0, len(rows))
	for i, r := range rows {
		out = append(out, SpecDeploy{
			Time: r.At, Index: i, CharID: r.Entry.CharID, Cost: r.Cost,
			AutoSkill: r.AutoSkill, WaitForCost: r.WaitForCost, PlanOrder: true,
		})
	}
	return out
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
