package main

import (
	"fmt"
	"os"
	"path/filepath"
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
			//: ★ 这两条断言在 [2] 接进来之后**改了内容**（不是放宽）：以前选定
			//:   关卡只留一句占位提示，现在会压到「问编队」屏 —— 那才是 Python
			//:   的走向（`_squad_asked`）。旧断言写的是占位实现的形状。
			check("选定关卡后压到「问编队」屏（[2] 的第一步）",
				screenName(r.top()) == "*main.squadAskScreen", screenName(r.top()))
			check("还没定编队（要先答「要不要手动加人」）", len(c.squad) == 0,
				fmt.Sprintf("%d 人", len(c.squad)))
		}
	}

	//: 这一轮下钻把屏栈压深了，而下面几段要在**准备屏**上按键：逐层 Esc 退回去
	//: （Esc 是本仓唯一的"退一层"，最底层不退）。上限 10 次是防呆——
	//: 万一将来某一层的回调会再压屏，这里也不至于转不出来。
	for i := 0; i < 10 && len(r.stack) > 1; i++ {
		press(r, "esc")
	}
	check("逐层 Esc 能退回准备屏", screenName(r.top()) == "main.welcomeScreen",
		screenName(r.top()))

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

	fmt.Println("== 八 · 路径补全（check_tui.py 那套判据搬过来）==")
	tmp, terr := os.MkdirTemp("", "rios-tui-complete")
	if terr != nil {
		check("建临时目录", false, terr.Error())
	} else {
		defer os.RemoveAll(tmp)
		sep := string(os.PathSeparator)
		for _, name := range []string{"alpha-1", "alpha-2", "beta"} {
			_ = os.Mkdir(filepath.Join(tmp, name), 0o755)
		}
		nt, cd := completeDir("", "/X/guides")
		check("空输入补成默认目录", nt == "/X/guides"+sep, nt)
		check("补出来带分隔符（好接着往下打）", strings.HasSuffix(nt, sep), nt)

		//: ★ 唯一匹配用**自造场景**，不依赖本机目录里恰好只有一个同前缀条目
		//:   —— 那正是 Python 那边两条判据恒红的根因（worklog 仓与产品仓同前缀）。
		_ = os.Mkdir(filepath.Join(tmp, "solo"), 0o755)
		nt, cd = completeDir(filepath.Join(tmp, "sol"), "")
		sst, serr := os.Stat(strings.TrimRight(nt, "/\\"))
		check("唯一匹配补到真目录", serr == nil && sst.IsDir(), nt)
		check("补的是目录就带分隔符", strings.HasSuffix(nt, sep), nt)
		check("唯一匹配时不返回候选（没什么可挑的）", len(cd) == 0,
			fmt.Sprintf("%d 个候选", len(cd)))

		nt, _ = completeDir(filepath.ToSlash(tmp)+"/sol", "")
		check("正斜杠输入补出来仍是正斜杠（不在一个路径里混两种）",
			!strings.Contains(nt, "\\"), nt)

		nt, cd = completeDir(filepath.Join(tmp, "al"), "")
		check("多个匹配时只补到公共前缀，并把候选交回",
			len(cd) == 2 && strings.HasSuffix(filepath.ToSlash(nt), "alpha-"),
			fmt.Sprintf("%d 个候选 → %s", len(cd), nt))
		check("补到前缀之后**不**擅自加分隔符（还没定是哪一个）",
			!strings.HasSuffix(nt, sep), nt)

		_, listed := completeDir(tmp+sep, "")
		check("以分隔符结尾时列出该目录下全部条目", len(listed) == 4,
			fmt.Sprintf("%d 条", len(listed)))

		_ = os.Mkdir(filepath.Join(tmp, "Alpha-3"), 0o755)
		nt, cd = completeDir(filepath.Join(tmp, "a"), "")
		check("大小写不同的兄弟目录也能补出公共前缀（不能被大小写噎住）",
			len(cd) == 3 && len(nt) > len(tmp)+1,
			fmt.Sprintf("%s / 候选 %d 个", nt, len(cd)))

		nt, cd = completeDir("/__rios_no_such_dir__/x", "")
		check("不存在的路径原样退回、不给候选",
			nt == "/__rios_no_such_dir__/x" && len(cd) == 0, nt)
	}

	fmt.Println("== 九 · 改目录屏（GuidesDir）==")
	gdTmp, gerr := os.MkdirTemp("", "rios-tui-guides")
	if gerr != nil {
		check("建临时目录", false, gerr.Error())
	} else {
		defer os.RemoveAll(gdTmp)
		cfgTmp := filepath.Join(gdTmp, "tui.json")
		os.Setenv("RIOS_TUI_CONFIG", cfgTmp)
		defer os.Unsetenv("RIOS_TUI_CONFIG")
		check("配置路径已指到临时文件（判据不碰玩家真正的配置）",
			configPath() == cfgTmp, configPath())

		c.guidesDir = filepath.Join(gdTmp, "Guides")
		press(r, "d")
		check("D 键压到改目录屏", screenName(r.top()) == "*main.guidesDirScreen",
			screenName(r.top()))
		gv := r.View()
		check("屏幕上写着怎么用（Tab 补全／留空不改）",
			strings.Contains(gv, "Tab 补全") && strings.Contains(gv, "不修改"),
			firstLineWith(gv, "Tab 补全"))
		check("输入框预填的是当前目录", strings.Contains(gv, c.guidesDir), c.guidesDir)

		//: 造两个同前缀目录 —— 补全的"多个匹配"分支才走得到。
		_ = os.MkdirAll(filepath.Join(gdTmp, "alpha-1"), 0o755)
		_ = os.MkdirAll(filepath.Join(gdTmp, "alpha-2"), 0o755)
		gs := r.top().(*guidesDirScreen)
		gs.in.SetValue(filepath.Join(gdTmp, "al"))
		press(r, "tab")
		check("Tab 把输入补到公共前缀",
			strings.HasSuffix(filepath.ToSlash(gs.in.Value()), "alpha-"), gs.in.Value())
		check("并把候选交回界面（不替用户猜）", len(gs.cands) == 2,
			fmt.Sprintf("%d 个候选", len(gs.cands)))
		check("候选也画在屏上", strings.Contains(r.View(), "候选："), firstLineWith(r.View(), "候选："))

		pick := filepath.Join(gdTmp, "alpha-1")
		gs.in.SetValue(pick)
		press(r, "enter")
		check("回车后回到准备屏", screenName(r.top()) == "main.welcomeScreen", screenName(r.top()))
		raw, rerr := os.ReadFile(cfgTmp)
		check("配置真的写下来了（值正确）",
			rerr == nil && strings.Contains(string(raw), "alpha-1"), fmt.Sprintf("err=%v", rerr))
		check("共享态跟着更新", c.guidesDir == pick, c.guidesDir)
		check("提示是具名的（说清改成了什么）", strings.Contains(c.note, "已改为"), c.note)

		press(r, "d")
		before, _ := os.ReadFile(cfgTmp)
		press(r, "esc")
		after, _ := os.ReadFile(cfgTmp)
		check("Esc 返回且**不修改**配置",
			string(before) == string(after) && strings.Contains(c.note, "未修改"), c.note)
	}

	fmt.Println("== 十 · 选人屏与「自限」拦截（政策＝纯函数）==")

	//: ★ 本段自己的负对照：开头那条全局负对照只证了 `check` 不是恒真的；
	//:   这里要证**本段用的判据**不是恒真的 —— 一条恒真的 `allMinLevel`
	//:   会让下面"拦下／放行"那几条断言全部退化成同义反复（满屏 ✓ 零信息量）。
	rulerOK := true
	if !check("负对照：混入一位 E2 干员时 allMinLevel 必须为假（尺子要判红）",
		!allMinLevel([]RosterOperator{{CharID: "x", Name: "甲", Elite: 2, Level: 1}}),
		fmt.Sprintf("allMinLevel=%v",
			allMinLevel([]RosterOperator{{CharID: "x", Name: "甲", Elite: 2, Level: 1}}))) {
		rulerOK = false
	}
	if !check("负对照：提示语检查用在别的话上必须为假（尺子要判红）",
		!strings.Contains("与那句话无关的一段文本", squadMinLevelMsg),
		"别的话里不含那句话") {
		rulerOK = false
	}
	if !rulerOK {
		fmt.Println("★ 本段负对照没红 ⇒ 第十段的读数作废")
		return 3
	}

	//: 纯函数的边界：判定范围是「精英0 1级 到 精英1 1级（含两端）」。
	bounds := []struct {
		label string
		op    RosterOperator
		want  bool
	}{
		{"E0L1 ✓", RosterOperator{Elite: 0, Level: 1}, true},
		{"E1L1 ✓", RosterOperator{Elite: 1, Level: 1}, true},
		{"E1L2 ✗", RosterOperator{Elite: 1, Level: 2}, false},
		{"E2L1 ✗", RosterOperator{Elite: 2, Level: 1}, false},
		{"E0L2 ✗", RosterOperator{Elite: 0, Level: 2}, false},
	}
	for _, b := range bounds {
		got := isMinLevel(b.op)
		check("纯函数边界 isMinLevel "+b.label, got == b.want, fmt.Sprintf("实得 %v", got))
	}

	//: 假名册：自检**不去起 Python 桥**（那是一次环境依赖，不是判据），
	//: 但字段与形状跟桥给的**一模一样**（`engclient.go` 的 RosterOperator）。
	fake := &rosterData{Source: "selftest", Complete: true, Count: 4,
		Operators: []RosterOperator{
			{CharID: "char_1", Name: "甲", Profession: "PIONEER", Elite: 0, Level: 1},
			{CharID: "char_2", Name: "乙", Profession: "WARRIOR", Elite: 1, Level: 1},
			{CharID: "char_3", Name: "丙", Profession: "MEDIC", Elite: 1, Level: 45},
			{CharID: "char_4", Name: "丁", Profession: "CASTER", Elite: 2, Level: 90},
		}}
	pickCtx := func(slot int) *appCtx {
		return &appCtx{w: 90, h: 26, roster: fake, deployLimit: slot, mode: "auto",
			stage: &data.StageRecord{Code: "1-7", Name: "测试关"}}
	}
	pickTop := func(r *root) *squadPickScreen {
		s, _ := r.top().(*squadPickScreen)
		return s
	}
	//: 勾人：把光标移到名字那一行、按一下空格 —— 与真终端里按的是同一个键。
	markNames := func(r *root, s *squadPickScreen, names ...string) {
		for _, want := range names {
			for i, op := range s.rows {
				if op.Name == want {
					s.cursor = i
					press(r, " ")
				}
			}
		}
	}

	//: 甲 E0L1、乙 E1L1 —— 两位都在范围内；槽位 2 ⇒ 满。
	cA := pickCtx(2)
	rA := newRoot(cA, welcomeScreen{})
	sA := newSquadPickScreen(cA, nil)
	rA.push(sA, onSquadPicked)
	check("选人屏把槽位数写在屏上", strings.Contains(rA.View(), "槽位 2 人"),
		firstLineWith(rA.View(), "槽位"))
	check("选人屏列出的是名册里的人（共 4 人）", strings.Contains(rA.View(), "共 4 人"),
		firstLineWith(rA.View(), "共 "))
	markNames(rA, sA, "甲", "乙")
	check("空格真的勾上了人（勾选是新屏自己持有的）", len(sA.picked) == 2,
		fmt.Sprintf("%d 人", len(sA.picked)))
	press(rA, "enter")
	check("拦下：仍停在选人屏（**没**进下一步）",
		screenName(rA.top()) == "*main.squadPickScreen", screenName(rA.top()))
	check("拦下：提示语里含那句话", strings.Contains(cA.note, squadMinLevelMsg), cA.note)
	check("拦下：那句话**画在屏上**", strings.Contains(rA.View(), squadMinLevelMsg),
		firstLineWith(rA.View(), squadMinLevelMsg))
	check("拦下：编队没有被定下来", cA.squad == nil, fmt.Sprintf("%v", cA.squad))
	check("拦下：勾选跟着回到新屏（人还看得见该改哪一个）",
		pickTop(rA) != nil && len(pickTop(rA).picked) == 2,
		fmt.Sprintf("%d 人", len(pickTop(rA).picked)))

	//: 混进一位超范围的（丙 E1 45级）⇒ **放行**。
	markNames(rA, pickTop(rA), "丙")
	press(rA, "enter")
	check("放行：混进一位超范围的干员就不拦（退回上一层）",
		screenName(rA.top()) == "main.welcomeScreen", screenName(rA.top()))
	check("放行：编队定下来了（3 人，按码点序）", len(cA.squad) == 3,
		fmt.Sprintf("%v", cA.squad))
	check("放行：提示里写明下一步还没实现", strings.Contains(cA.note, "尚未实现"), cA.note)

	//: 全员在范围内、但**槽位没满**（2/5）⇒ **不拦**。
	cC := pickCtx(5)
	rC := newRoot(cC, welcomeScreen{})
	sC := newSquadPickScreen(cC, nil)
	rC.push(sC, onSquadPicked)
	markNames(rC, sC, "甲", "乙")
	press(rC, "enter")
	check("槽位未满（2/5）不拦：退回了上一层",
		screenName(rC.top()) == "main.welcomeScreen", screenName(rC.top()))
	check("槽位未满不拦：编队定下来了", len(cC.squad) == 2, fmt.Sprintf("%v", cC.squad))

	//: **退化**：槽位数取不到（0）⇒ 非空且全员在范围内也算触发，且屏上写明退化。
	cD := pickCtx(0)
	rD := newRoot(cD, welcomeScreen{})
	sD := newSquadPickScreen(cD, nil)
	rD.push(sD, onSquadPicked)
	check("槽位取不到时屏上写「未知」（不写成 0 人）",
		strings.Contains(rD.View(), "槽位：未知"), firstLineWith(rD.View(), "槽位"))
	markNames(rD, sD, "甲")
	press(rD, "enter")
	check("退化：非空且全员在范围内 ⇒ 拦下",
		screenName(rD.top()) == "*main.squadPickScreen" &&
			strings.Contains(cD.note, squadMinLevelMsg), cD.note)
	check("退化：**退化本身**写在提示里（不是只有代码知道）",
		strings.Contains(cD.note, "没取到本关的可部署人数"), firstLineWith(cD.note, "没取到"))

	//: 屏流程：选定关卡压的是「问编队」屏；选「我自己选」才进选人屏。
	cE := pickCtx(0)
	rE := newRoot(cE, welcomeScreen{})
	onStagePicked(rE, &data.StageRecord{Code: "1-7", Name: "测试关"})
	check("选定关卡后压的是「问编队」屏（**不许静默跳过**）",
		screenName(rE.top()) == "*main.squadAskScreen", screenName(rE.top()))
	press(rE, "enter") // 光标 0 ＝「不用，让程序自己挑」
	check("选「让程序自己挑」→ 退回上一层并具名说明",
		screenName(rE.top()) == "main.welcomeScreen" && strings.Contains(cE.note, "尚未实现"),
		cE.note)
	onStagePicked(rE, &data.StageRecord{Code: "1-7", Name: "测试关"})
	if ask, ok := rE.top().(*squadAskScreen); ok {
		ask.cursor = 1 //「我自己选」
	}
	press(rE, "enter")
	check("选「我自己选」→ 进选人屏", screenName(rE.top()) == "*main.squadPickScreen",
		screenName(rE.top()))

	fmt.Println("== 十一 · 桥客户端：缺件必须具名（不许退化成空名册）==")
	oldPy := os.Getenv(envPython)
	os.Setenv(envPython, "__rios_no_such_python__")
	_, berr := fetchRoster()
	os.Setenv(envPython, oldPy)
	check("解释器找不到时**具名失败**（报出解释器名与桥脚本路径）",
		berr != nil && strings.Contains(berr.Error(), "__rios_no_such_python__") &&
			strings.Contains(berr.Error(), "rios_bridge.py"),
		fmt.Sprintf("err=%v", berr))

	//: ★ 桥**可达**时做一次真实往返。这一条是**环境相关**的：取不到名册时
	//:   只具名说明、**不判红** —— 判红会把"这台机器上没有名册／没装 Python"
	//:   记成"界面写错了"。答了但字段不对，才是真的红。
	if live, lerr := fetchRoster(); lerr == nil {
		fieldsOK := len(live.Operators) > 0
		for _, op := range live.Operators {
			if op.CharID == "" || op.Name == "" {
				fieldsOK = false
				break
			}
		}
		check("桥真实往返：名册取到了，且每条的 char_id／name 都在",
			live.Source != "" && fieldsOK,
			fmt.Sprintf("source=%s complete=%v 条数=%d", live.Source, live.Complete,
				len(live.Operators)))
		//: 拿**真名册**跑一次判定（上面那几条用的是 4 人的假名册）：这个号里落在
		//: 「E0L1..E1L1」的人有多少，全勾上会不会被拦（槽位数取不到 ⇒ 走退化分支）。
		inRange := make([]RosterOperator, 0, len(live.Operators))
		for _, op := range live.Operators {
			if isMinLevel(op) {
				inRange = append(inRange, op)
			}
		}
		if len(inRange) == 0 {
			fmt.Println("  （未核：这个号的名册里没有落在 E0L1..E1L1 的干员，判定无从跑起）")
		} else {
			blocked := pickTriggersBlock(inRange, 0)
			check("真名册判定：范围内的人全勾上 ⇒ 拦下（槽位取不到，走退化）", blocked,
				fmt.Sprintf("范围内 %d/%d 人，pickTriggersBlock=%v", len(inRange),
					len(live.Operators), blocked))
		}
		//: 字段对了不等于**画得出来**（中文名宽度、可见窗口、截断都在渲染这一层）。
		//: 所以拿真名册再渲染一次选人屏。
		liveCtx := &appCtx{w: 90, h: 26, roster: live, deployLimit: 4, mode: "auto"}
		liveScr := newSquadPickScreen(liveCtx, nil)
		liveView := liveScr.view(liveCtx)
		check("真名册渲染：条数与名册一致",
			strings.Contains(liveView, fmt.Sprintf("共 %d 人", len(live.Operators))),
			firstLineWith(liveView, "共 "))
		check("真名册渲染：第一行就是练度最高的那位（排序生效）",
			len(liveScr.rows) > 0 && strings.Contains(liveView, liveScr.rows[0].Name),
			fmt.Sprintf("E%d %d级 %s", liveScr.rows[0].Elite, liveScr.rows[0].Level,
				liveScr.rows[0].Name))
	} else {
		fmt.Printf("  （未核：桥这次取不到名册，不判红。具名原因：%s）\n",
			strings.SplitN(lerr.Error(), "\n", 2)[0])
	}

	fmt.Println()
	if bad > 0 {
		fmt.Printf("结论：**%d 条红** —— TUI 自检不通过\n", bad)
		return 1
	}
	fmt.Println("结论：**全绿** —— 取数／降级／屏栈／下钻／退回／空数据退路／路径补全／改目录／选人屏与自限拦截逐条过")
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
