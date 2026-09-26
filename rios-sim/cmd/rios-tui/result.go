package main

import (
	"encoding/json"
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"rios-sim/core"
	"rios-sim/data"
	"rios-sim/maa"
)

// # 结果屏（对应 Python 的 `ResultScreen`，`app.py:2291`）
//
// 把通过的编队、模组、技能摆出来，并提供**导出**（这一屏存在的理由）。
//
// ## 这一屏**不挂 Esc**（博士 2026-09-17 裁定）
//
// 原话：「结果屏只留退出程序和回主界面」。所以 Esc 不被补上 —— 它在这里能做的事
// 与别的出口重复，而这一屏不是向导屏、没有"上一步"可退。
//
// 出口三个 ＋ 一个动作：
//
//   - `Q` 退出程序；
//   - `H` 回 [0] 准备屏（整轮重来，连关卡也忘掉）；
//   - `R` **回选关页**：退到关卡列表为止，章/分部/环境的选择都还留着，**编队也留着**
//     （换一关通常还是同一队）；
//   - `E` 导出 —— 不是出口，是这一屏存在的理由。
//
// ## 导出这一条链与作业本身**同一份取数**
//
// 人名清单走 `maa.OperatorsLines`（与写进 `doc.details` 的是同一个函数），编辑要求
// 取自**名册文件**（那份带 `potential`/`module`），模组名走库里的 `module` 表 ——
// 三处都不另起一份实现，否则屏幕上的字与实际落盘的作业迟早会不一样。

type resultScreen struct {
	//: 导出回执 / 失败原因（**具名**，不许只显示"导出失败"）
	msg string
}

func newResultScreen() *resultScreen { return &resultScreen{} }

func (*resultScreen) title() string { return "结果" }
func (*resultScreen) help() string {
	return "E 导出 · R 重选关卡 · H 主界面 · Q 退出"
}

// verdictView 是引擎判决里结果屏要显示的几栏。
type verdictView struct {
	Won         bool    `json:"won"`
	Elapsed     float64 `json:"elapsed"`
	Kills       int     `json:"kills"`
	Leaks       int     `json:"leaks"`
	Life        int     `json:"life"`
	DamageDealt float64 `json:"damage_dealt"`
}

func starsOfVerdict(v verdictView) int {
	if !v.Won {
		return 0
	}
	if v.Leaks > 0 {
		return 2
	}
	return 3
}

func (s *resultScreen) view(c *appCtx) string {
	var b strings.Builder
	code, levelID := "（无）", ""
	if c.stage != nil {
		code, levelID = c.stage.Code, c.stage.LevelID
	}
	b.WriteString(styleTitle.Render(code) + "　" + styleDim.Render(levelID) + "\n\n")

	var v verdictView
	haveVerdict := false
	if len(c.solveVerdict) > 0 && json.Unmarshal(c.solveVerdict, &v) == nil {
		haveVerdict = true
	}
	switch {
	case c.solveNote != "" && !haveVerdict:
		b.WriteString("解算失败：" + c.solveNote + "\n")
	case !haveVerdict:
		b.WriteString("没有结果。\n")
	case starsOfVerdict(v) < 3:
		b.WriteString("这次没找到三星方案。\n")
	}
	if haveVerdict {
		st := starsOfVerdict(v)
		b.WriteString(fmt.Sprintf("  评价　　　%s%s（%s）\n",
			strings.Repeat("★", st), strings.Repeat("☆", 3-st),
			map[bool]string{true: "胜利", false: "失败"}[v.Won]))
		b.WriteString(fmt.Sprintf("  时长　　　%.1fs\n", v.Elapsed))
		b.WriteString(fmt.Sprintf("  击杀　　　%d\n", v.Kills))
		b.WriteString(fmt.Sprintf("  漏怪　　　%d\n", v.Leaks))
		//: ⚠ 权威的 `Verdict` 有 `max_life`，Go 的判决里没有，而界面手上的
		//: `data.StageRecord` 也没有这一列 ⇒ **分母显示不出来**（**登记为分歧**）。
		//: 要补得给 StageRecord 加列、或让引擎把 max_life 带回来（那会改判决的键集，
		//: 而 sim 那几套判据是逐字段比的，得一并核过）。
		b.WriteString(fmt.Sprintf("  剩余生命　%d\n", v.Life))
		b.WriteString(fmt.Sprintf("  总伤害　　%.0f\n", v.DamageDealt))
	}

	plan, ops, perr := loadSolved(c)
	b.WriteString("\n")
	switch {
	case perr != nil:
		b.WriteString("★ 解算结果取不出来：" + perr.Error() + "\n")
	case plan == nil:
		b.WriteString("没有可导出的编队。\n")
	default:
		b.WriteString(fmt.Sprintf("%s（%d 人，按部署顺序）\n",
			styleTitle.Render("用到的干员"), len(plan.Deploys)))
		for _, ln := range maa.OperatorsLines(ops) {
			b.WriteString("  " + ln + "\n")
		}
		b.WriteString("\n" + styleDim.Render(
			"编制要求取自名册（真实专精 / 模组 / 信赖）。") + "\n")
	}
	depth := 0
	if n := len(c.solveSteps); n > 0 {
		depth = c.solveSteps[n-1].Depth
	}
	b.WriteString("\n" + styleDim.Render(fmt.Sprintf(
		"已评估 %d 个方案，最深 %d 人。", c.solveEvaluated, depth)) + "\n")
	if c.solveNote != "" {
		//: ★ `note` 必须摆出来：搜索"没有三星方案"有四种完全不同的来路（几何剪枝后
		//: 没候选／没位置可加／全是失败／到了人头上限），只说一句"没找到"的话四种
		//: 长得一模一样 —— 而一句话的差别决定了要不要去查模拟器。
		b.WriteString("\n" + c.solveNote + "\n")
	}
	b.WriteString("\n" + styleDim.Render("E 导出作业到 "+c.guidesDir+"/<关卡名>/"))
	if s.msg != "" {
		b.WriteString("\n\n" + s.msg)
	}
	return b.String()
}

// loadSolved 把解算结果还原成 (打法, 干员表)。
//
// 名册走**文件**（`c.roster.Path`）：那份带 `potential`/`module`，而桥只送 5 个字段
// —— 差这几个字段模组名与攻击力就都不对。缺库/缺文件都要**具名**。
func loadSolved(c *appCtx) (*core.PlayPlan, []maa.UsedOperator, error) {
	if len(c.solvePlan) == 0 {
		return nil, nil, nil
	}
	var plan core.PlayPlan
	if err := json.Unmarshal(c.solvePlan, &plan); err != nil {
		return nil, nil, fmt.Errorf("解算结果不是一份打法：%v", err)
	}
	roster, err := exportRoster(c)
	if err != nil {
		return nil, nil, err
	}
	tbl := moduleTableBestEffort()
	ops, err := maa.UsedOperators(plan, roster, tbl)
	if err != nil {
		return nil, nil, err
	}
	return &plan, ops, nil
}

// exportRoster 读导出要用的名册（文件形态）。
func exportRoster(c *appCtx) (*core.RosterRead, error) {
	if c.roster == nil || c.roster.Path == "" {
		return nil, fmt.Errorf("名册没有可用路径，导出的编制要求取不到")
	}
	rr, err := core.ReadRoster(c.roster.Path)
	if err != nil {
		return nil, fmt.Errorf("读名册 %s 失败：%w", c.roster.Path, err)
	}
	return &rr, nil
}

// moduleTableBestEffort 尽力取模组表。
//
// ★ **尽力而为是刻意的**：没有人带模组时导出**不需要**这张表，而缺库要由
// `maa.ToMaa` 在"确实需要"的时候**具名**报出来 —— 在这里先报错会把一条本来能成功的
// 路（没有库、也没人带模组）判死。取不到就返回 nil，让下游按它的口径处置。
func moduleTableBestEffort() map[string]maa.ModuleInfo {
	db, err := data.OpenReadOnly("akdb")
	if err != nil {
		return nil
	}
	defer db.Close()
	tbl, err := maa.ModuleTable(db)
	if err != nil {
		return nil
	}
	return tbl
}

// export 把结果编队写成 MAA 认得的作业（`ResultScreen.action_export`）。
func (s *resultScreen) export(c *appCtx) action {
	plan, ops, err := loadSolved(c)
	if err != nil {
		s.msg = "★ 导出失败：" + err.Error()
		return action{kind: actNone}
	}
	if plan == nil {
		s.msg = "没有可导出的编队。"
		return action{kind: actNone}
	}
	if c.stage == nil {
		s.msg = "★ 导出失败：没有选中的关卡"
		return action{kind: actNone}
	}
	//: 说明那一行：把模拟预测写进作业，**不满三星要显式提醒**（放进 MAA 之前先自己确认）
	note := ""
	var v verdictView
	if len(c.solveVerdict) > 0 && json.Unmarshal(c.solveVerdict, &v) == nil {
		note = fmt.Sprintf("模拟预测：%s，%.1fs，击杀 %d，漏怪 %d，剩余生命 %d，总伤害 %.0f。\n",
			map[bool]string{true: "胜利", false: "失败"}[v.Won], v.Elapsed, v.Kills,
			v.Leaks, v.Life, v.DamageDealt)
		if starsOfVerdict(v) < 3 {
			note += "**注意：这份方案不是三星**（有漏怪或掉命），放进 MAA 之前请先自行确认。\n"
		}
	}
	squad := "自动编队"
	if len(c.squad) > 0 {
		squad = strings.Join(c.squad, " ")
	}
	db, derr := data.OpenReadOnly("akdb")
	var tbl map[string]maa.ModuleInfo
	if derr == nil {
		defer db.Close()
		if t, terr := maa.ModuleTable(db); terr == nil {
			tbl = t
		}
	}
	job, err := maa.ToMaa(*plan, mustExportRoster(c), tbl, db, maa.MaaOptions{
		StageName:  c.stage.LevelID,
		Difficulty: c.stage.Difficulty,
		Title:      c.stage.Code + " " + squad,
		Details:    note + "由 R.I.O.S. 解算导出；编制要求取自名册，含真实专精与模组。",
	})
	if err != nil {
		s.msg = "★ 导出失败：" + err.Error()
		return action{kind: actNone}
	}
	path, err := maa.WriteJob(job, c.guidesDir, c.stage.Code)
	if err != nil {
		s.msg = "★ 写出作业失败：" + err.Error()
		return action{kind: actNone}
	}
	c.exportPath = path
	s.msg = fmt.Sprintf("已导出 %s\n  用了 %d 名干员：%s", path, len(plan.Deploys),
		maa.OperatorsBrief(ops))
	return action{kind: actNone}
}

// mustExportRoster 给 `ToMaa` 用的名册（已经在上一步校过，这里再读一次）。
//
// 读不出来返回 nil：`ToMaa` 对 nil 名册的处置是"练度取不到写 0"（裁定二），
// 而不是崩 —— 但那条路在上面 `loadSolved` 已经用**具名失败**挡住了。
func mustExportRoster(c *appCtx) *core.RosterRead {
	r, err := exportRoster(c)
	if err != nil {
		return nil
	}
	return r
}

func (s *resultScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	switch {
	case keyIs(k, "e"):
		return s, s.export(c)
	case keyIs(k, "r"):
		//: 回**选关页**（`stageScreen`）：章／分部／环境的选择都留着，编队也留着
		return s, action{kind: actPopTo, match: func(scr screen) bool {
			_, ok := scr.(*stageScreen)
			return ok
		}}
	case keyIs(k, "h"):
		//: 回 [0] 准备屏（整轮重来，连关卡也忘掉）
		return s, action{kind: actPopTo, match: func(scr screen) bool {
			_, ok := scr.(welcomeScreen)
			return ok
		}}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
	}
	//: ★ **这里故意不处理 Esc**（见文件头：博士 2026-09-17 裁定）。
	return s, action{kind: actNone}
}
