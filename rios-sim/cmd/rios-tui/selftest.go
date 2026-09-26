package main

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"rios-sim/data"
)

// runSelftest 是 TUI 的**无终端判据**。
//
// # 为什么必须有它
//
// 本仓的规矩是「行使判据必须是运行期计数」——而界面最容易退化成
// 「看起来能用」。没有终端的机器上跑不了交互，所以判据必须自己把屏栈推下去、
// 把每一屏**真的渲染出来**、再对内容做断言。
//
// 退出码：0 全过 ／ 1 有红 ／ 3 尺子自检不过（负对照没红，整批读数作废）。
func runSelftest(stages []data.StageRecord, zones []data.ZoneRecord) int {
	var bad int
	check := func(name string, cond bool, got string) bool {
		if cond {
			fmt.Printf("  ✓ %s %s\n", pad(name, 48), got)
			return true
		}
		bad++
		fmt.Printf("  ✗ %s %s\n", pad(name, 48), got)
		return false
	}

	// ★ 负对照：先证明这把尺子**会**判红。不证这一条，后面满屏的 ✓ 是零信息量
	//   （本仓记过：「控制组没红就是没有判据」。）
	if check("负对照：故意造一个假命题（应当判红）", 1 == 2, "这一条是刻意造的红") {
		fmt.Println("★ 负对照没红 ⇒ check 恒真 ⇒ 整批读数作废")
		return 3
	}
	bad = 0

	c := &appCtx{
		stages:   stages,
		zones:    zones,
		chapters: data.ListChapters(stages, zones),
		w:        90,
		h:        26,
		dataDir:  data.DataDBDir(),
	}
	r := newRoot(c, welcomeScreen{})
	r.Update(tea.WindowSizeMsg{Width: 90, Height: 26})

	fmt.Println("== 一 · 取数层 ==")
	check("章节 116 条（迁移图 §7.5 的金标）", len(c.chapters) == 116,
		fmt.Sprintf("实得 %d", len(c.chapters)))
	six := 0
	for _, s := range stages {
		if s.Difficulty == "SIX_STAR" {
			six++
		}
	}
	check("六星档已被取数口滤掉（SIX_STAR 行 0）", six == 0, fmt.Sprintf("实得 %d 行", six))
	n, err := data.OperatorCount()
	check("干员库数得出来（首页那一栏靠它）", err == nil && n > 1000,
		fmt.Sprintf("n=%d err=%v", n, err))

	fmt.Println("== 二 · [0] 准备屏 渲染 ==")
	v := r.View()
	check("渲染里有服务名", strings.Contains(v, appTitle), appTitle)
	check("渲染里有「数据目录」栏", strings.Contains(v, "数据目录"), "数据目录")
	check("渲染里有「登录账号」栏", strings.Contains(v, "登录账号"), "登录账号")
	check("干员库那栏是真读数", strings.Contains(v, "干员库：已获取"),
		firstLineWith(v, "干员库"))
	check("还没接的登录栏是**具名**的（不留空白）",
		strings.Contains(v, "尚未接入"), firstLineWith(v, "登录尚未接入"))

	fmt.Println("== 三 · 矮窗口降级（优先级：数据 > 标题）==")
	r.Update(tea.WindowSizeMsg{Width: 80, Height: 12})
	v12 := r.View()
	check("12 行：标题块还在", strings.Contains(v12, appTitle), "有服务名")
	r.Update(tea.WindowSizeMsg{Width: 80, Height: 10})
	v10 := r.View()
	check("10 行：标题块收起来了", !strings.Contains(v10, appTitle), "无服务名")
	check("10 行：数据目录**仍然看得见**", strings.Contains(v10, "数据目录"), "数据目录")
	check("10 行：登录账号**仍然看得见**", strings.Contains(v10, "登录账号"), "登录账号")
	r.Update(tea.WindowSizeMsg{Width: 90, Height: 26})

	fmt.Println("== 四 · 屏栈：Enter 进选章、Esc 退回 ==")
	press(r, "enter")
	check("压到选章屏", screenName(r.top()) == "*main.chapterScreen", screenName(r.top()))
	check("面包屑含两层", strings.Contains(r.crumb(), "准备") &&
		strings.Contains(r.crumb(), "选章节"), r.crumb())
	check("选章屏渲染出第一章", strings.Contains(r.View(), c.chapters[0].Title),
		c.chapters[0].Title)
	press(r, "esc")
	check("Esc 退回准备屏", screenName(r.top()) == "main.welcomeScreen", screenName(r.top()))
	check("退出后栈深回到 1", len(r.stack) == 1, fmt.Sprintf("%d", len(r.stack)))

	fmt.Println("== 五 · 整条下钻：章 → 部 →（环境）→ 关卡 ==")
	press(r, "enter")
	multi := -1
	for i := range c.chapters {
		if len(c.chapters[i].Parts) > 1 {
			multi = i
			break
		}
	}
	check("存在多部章（否则选部那一屏永远走不到）", multi >= 0,
		fmt.Sprintf("首个多部章下标 %d", multi))
	if multi >= 0 {
		r.top().(*chapterScreen).cursor = multi
		press(r, "enter")
		check("压到选部屏", screenName(r.top()) == "*main.partScreen", screenName(r.top()))
		check("部数 = 章里的 Parts 数",
			strings.Contains(r.View(), fmt.Sprintf("共 %d 条", len(c.chapters[multi].Parts))),
			fmt.Sprintf("%d 部", len(c.chapters[multi].Parts)))
		press(r, "enter")
		if screenName(r.top()) == "*main.envScreen" {
			check("多档环境的部会先过环境屏", true, "envScreen")
			check("环境屏首项是不限", strings.Contains(r.View(), "不限"), "不限")
			r.top().(*envScreen).cursor = 0
			press(r, "enter")
		}
		check("到关卡屏", screenName(r.top()) == "*main.stageScreen", screenName(r.top()))
		if screenName(r.top()) != "*main.stageScreen" {
			//: 断言不成立时**不要硬转**（那会把判据变成 panic，读数全丢）。
			fmt.Println("  （不在关卡屏，本段后续断言跳过）")
		} else {
			ss := r.top().(*stageScreen)
			check("这一部有关卡", len(ss.rows) > 0, fmt.Sprintf("%d 关", len(ss.rows)))
			zone := c.chapters[multi].Parts[0].ZoneID
			wrong := 0
			for _, st := range ss.rows {
				if st.ZoneID != zone {
					wrong++
				}
			}
			check("列出的每一关都属于所选 zone（精确匹配）", wrong == 0,
				fmt.Sprintf("越界 %d 关", wrong))
			check("关卡屏渲染里有第一关的代号", strings.Contains(r.View(), ss.rows[0].Code),
				ss.rows[0].Code)
			press(r, "enter")
			check("选定后回到准备屏", screenName(r.top()) == "main.welcomeScreen",
				screenName(r.top()))
			check("并留下具名提示（走到哪一步）",
				strings.Contains(c.note, "尚未实现") && strings.Contains(c.note, "已选"), c.note)
		}
	}

	fmt.Println("== 六 · 环境筛选（取数口径）==")
	hit := ""
	for _, z := range zones {
		if data.ZoneEnvsShown(data.ZoneEnvs(z.ZoneID, stages)) {
			hit = z.ZoneID
			break
		}
	}
	check("存在 ≥2 档环境的 zone", hit != "", hit)
	if hit != "" {
		envs := data.ZoneEnvs(hit, stages)
		e := envs[0].Env
		got := data.ListStages(stages, data.StageFilter{ZoneID: hit, Env: e})
		mism := 0
		for _, s := range got {
			if !strings.EqualFold(s.DiffGroup, e) {
				mism++
			}
		}
		check("按环境筛出的行 diff_group 都等于该环境", len(got) > 0 && mism == 0,
			fmt.Sprintf("%s：%d 关，失配 %d", e, len(got), mism))
	}

	fmt.Println("== 七 · 无关卡那一屏（空数据下的退路）==")
	empty := &appCtx{w: 90, h: 26}
	check("无章节无关卡时给的是 NoStage 屏",
		screenName(empty.stagePickScreen()) == "main.noStageScreen",
		screenName(empty.stagePickScreen()))
	ns := noStageScreen{}.view(empty)
	check("NoStage 屏给的是**能照做的话**（含命令）",
		strings.Contains(ns, "db stage-fetch"), "含 db stage-fetch")

	fmt.Println()
	if bad > 0 {
		fmt.Printf("结论：**%d 条红** —— TUI 自检不通过\n", bad)
		return 1
	}
	fmt.Println("结论：**全绿** —— 取数／降级／屏栈／下钻／退回／空数据退路逐条过")
	return 0
}

// press 把一次按键送进根模型（等价于在真终端里按一下）。
func press(r *root, s string) { r.Update(keyMsg(s)) }

func keyMsg(s string) tea.KeyMsg {
	switch s {
	case "enter":
		return tea.KeyMsg{Type: tea.KeyEnter}
	case "esc":
		return tea.KeyMsg{Type: tea.KeyEsc}
	case "up":
		return tea.KeyMsg{Type: tea.KeyUp}
	case "down":
		return tea.KeyMsg{Type: tea.KeyDown}
	case "backspace":
		return tea.KeyMsg{Type: tea.KeyBackspace}
	}
	return tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune(s)}
}

func screenName(s screen) string { return fmt.Sprintf("%T", s) }

func firstLineWith(s, needle string) string {
	for _, ln := range strings.Split(s, "\n") {
		if strings.Contains(ln, needle) {
			return ln
		}
	}
	return "（没找到含 " + needle + " 的行）"
}
