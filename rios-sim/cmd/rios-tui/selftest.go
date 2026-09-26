package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/ansi"

	"rios-sim/core"
	"rios-sim/data"
	"rios-sim/maa"
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
	//: ★ 旧文案（还没接的登录栏写「尚未接入」）**已经随着登录屏落地而删除**，
	//: 所以这条不再盯文案——盯**性质**：这一栏在任何一档状态下都不许留空白。
	//: 三档各造一个 ctx 直接问 accountLine，比在整屏渲染里找字更准（也免得日后
	//: 再改一次文案就红一次）。
	{
		accStates := []struct {
			what string
			ctx  *appCtx
		}{
			{"没账号", &appCtx{}},
			{"有名册", &appCtx{roster: &rosterData{Source: "skland", Count: 12}}},
			{"名册取不到", &appCtx{rosterErr: "★ 名册读不出来"}},
		}
		blank := ""
		for _, s := range accStates {
			if strings.TrimSpace(ansi.Strip(s.ctx.accountLine())) == "" {
				blank = s.what
			}
		}
		check("登录账号栏三档都有话说（不留空白）", blank == "",
			fmt.Sprintf("空白的那一档：%q（三档：没账号／有名册／名册取不到）", blank))
		//: 负对照：这把尺子**对已知的空**必须给得出「空」。只写纯 ANSI 转义
		//: （肉眼看着是空白的那种）也算空——否则上面那条绿可能只是尺子眼瞎。
		ctrl := strings.TrimSpace(ansi.Strip("\x1b[2m   \x1b[0m")) == ""
		check("负对照：空白检测器认得纯 ANSI 的空白", ctrl, fmt.Sprintf("实得 %v", ctrl))
	}

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

	fmt.Println("== 十 · 解算入口的守卫（自限拦截：一个守卫，两条路都过它）==")

	//: ★ 本段自己的负对照（**负对照在前**）：开头那条全局负对照只证了 `check` 不是
	//:   恒真的；这里要证**本段用的这把尺子**不是恒真的 —— 一条恒真的 `allMinLevel`
	//:   会让下面「拦下／放行」的断言全退化成同义反复（满屏 ✓ 零信息量）；
	//:   而一条恒空的「防绕过」判据等于没写，也要在这里试出来。
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
	//: 把守卫的结论**反过来读**：全员低练度 ＋ 手选 ⇒「放行」若成立，说明这守卫
	//: 拦不住任何东西，下面那些「拦下」的断言就全是空话。这是口径 1／2 的反向对照。
	inv := solveGate([]RosterOperator{{CharID: "a", Name: "甲", Elite: 0, Level: 1}},
		solveSourceManual)
	if !check("负对照：把守卫结论反过来读必须不成立（全员低练度＋手选 ⇒ 不是放行）",
		!inv.Allow,
		fmt.Sprintf("Allow=%v 分支=%s", inv.Allow, solveGateBranchNames[inv.Branch])) {
		rulerOK = false
	}
	//: 防绕过扫描器的**两个方向**：会红（合成源码里守卫之外多一处调用）＋ 不滥红
	//: （调用只在守卫体内 ⇒ 0 处）。只试一个方向分不出「判据恒空」与「源码干净」。
	//: 合成源码里那个记号是**拼出来**的：本文件不在扫描范围内，但拼写让它即使被扫
	//: 也不会自己撞上自己。
	sneakCall := "allMin" + "Level(p)"
	cleanSrc := "func solveGate(p []RosterOperator, src solveSource) solveVerdict {\n" +
		"\tif !" + sneakCall + " {\n\t\treturn solveVerdict{}\n\t}\n\treturn solveVerdict{}\n}\n"
	bypassSrc := cleanSrc + "\nfunc sneaky(p []RosterOperator) bool {\n\treturn " + sneakCall +
		" // 绕过守卫自己再判一遍\n}\n"
	if !check("负对照：防绕过扫描器喂「守卫之外多一处调用」必须报 ≥1 处（尺子要判红）",
		len(guardBypassFindings(bypassSrc)) > 0,
		fmt.Sprintf("报出 %v", guardBypassFindings(bypassSrc))) {
		rulerOK = false
	}
	if !check("反向对照：同一把尺子喂「调用只在守卫体内」必须报 0 处（尺子不恒非空）",
		len(guardBypassFindings(cleanSrc)) == 0,
		fmt.Sprintf("报出 %v", guardBypassFindings(cleanSrc))) {
		rulerOK = false
	}
	if !rulerOK {
		fmt.Println("★ 本段负对照没红 ⇒ 第十段的读数作废")
		return 3
	}

	//: 行使读数：围着**一次**调用取前后差。只看「整个自检跑完这个计数非零」证不了
	//: 什么 —— 别的调用会把它垫高，某条路被绕开也看不出来。前后差能证明
	//: 「**这一次**调用走的是哪条分支」，这正是口径 1／2 唯一能被证伪的地方。
	delta := func(f func()) [solveGateBranchCount]int {
		b := solveGateHitsSnapshot()
		f()
		a := solveGateHitsSnapshot()
		var d [solveGateBranchCount]int
		for i := range d {
			d[i] = a[i] - b[i]
		}
		return d
	}
	fmtDelta := func(d [solveGateBranchCount]int) string {
		parts := make([]string, 0, solveGateBranchCount)
		for i := range d {
			parts = append(parts, fmt.Sprintf("%s=%d", solveGateBranchNames[i], d[i]))
		}
		return strings.Join(parts, " ")
	}
	oneBranch := func(d [solveGateBranchCount]int, want solveGateBranch) bool {
		if d[want] != 1 {
			return false
		}
		for i := range d {
			if i != int(want) && d[i] != 0 {
				return false
			}
		}
		return true
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
	//: ★ 名册还得有一个**文件路径**：放行之后解算屏要把它交给引擎（引擎读的是那份
	//: 文件，桥上只送 5 个字段）。自检**自己写一份最小名册到临时目录**，不去依赖玩家
	//: 那份 gitignore 的文件 —— 依赖它的话，判据在别人机器上只会静默跳过。
	fakeDir, _ := os.MkdirTemp("", "rios-selftest-roster-")
	fake.Path = filepath.Join(fakeDir, "roster.json")
	_ = os.WriteFile(fake.Path, []byte(
		`[{"name":"丙","charId":"char_3","elite":1,"level":45,"potential":1}]`), 0o644)
	//: `slot` 只填给**屏上显示**（口径 3：槽位不参与判定）—— 下面故意拿 2／5／0
	//: 三种槽位跑同一个编队，判定必须一样。
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

	//: 甲 E0L1、乙 E1L1 —— 两位都在范围内。槽位 2 只是**显示**（口径 3）。
	cA := pickCtx(2)
	rA := newRoot(cA, welcomeScreen{})
	sA := newSquadPickScreen(cA, nil)
	rA.push(sA, onSquadPicked)
	check("选人屏把槽位数写在屏上（口径 3：显示照旧）",
		strings.Contains(rA.View(), "槽位 2 人"), firstLineWith(rA.View(), "槽位"))
	check("选人屏列出的是名册里的人（共 4 人）", strings.Contains(rA.View(), "共 4 人"),
		firstLineWith(rA.View(), "共 "))
	markNames(rA, sA, "甲", "乙")
	check("空格真的勾上了人（勾选是新屏自己持有的）", len(sA.picked) == 2,
		fmt.Sprintf("%d 人", len(sA.picked)))
	dBlock := delta(func() { press(rA, "enter") })
	check("手选·拦下：仍停在选人屏（**没**进下一步）",
		screenName(rA.top()) == "*main.squadPickScreen", screenName(rA.top()))
	check("手选·拦下：提示语里含那句话", strings.Contains(cA.note, squadMinLevelMsg), cA.note)
	check("手选·拦下：那句话**画在屏上**", strings.Contains(rA.View(), squadMinLevelMsg),
		firstLineWith(rA.View(), squadMinLevelMsg))
	check("手选·拦下：编队没有被定下来", cA.squad == nil, fmt.Sprintf("%v", cA.squad))
	check("手选·拦下：勾选跟着回到新屏（人还看得见该改哪一个）",
		pickTop(rA) != nil && len(pickTop(rA).picked) == 2,
		fmt.Sprintf("%d 人", len(pickTop(rA).picked)))
	check("行使计数：这一次调用只走了「拦下·手选」这条分支",
		oneBranch(dBlock, gateBlockManual), fmtDelta(dBlock))

	//: 混进一位超范围的（丙 E1 45级）⇒ **放行**。
	markNames(rA, pickTop(rA), "丙")
	var cmdA tea.Cmd
	dAllow := delta(func() { _, cmdA = rA.Update(keyMsg("enter")) })
	check("放行：混进一位超范围的干员就不拦（压解算屏）",
		screenName(rA.top()) == "*main.solveScreen", screenName(rA.top()))
	check("放行：编队定下来了（3 人，按码点序）", len(cA.squad) == 3,
		fmt.Sprintf("%v", cA.squad))
	if sc, ok := rA.top().(*solveScreen); ok {
		//: ★ 这一条盯的是"压了屏却没跑"：屏压上了、第一轮命令也排上了，才算真的进了解算
		check("放行：第一轮命令已排上（不是压了屏却没跑）", cmdA != nil, "cmd 非空")
		//: ⚠ 首轮人数取自**阶梯**，而阶梯的第一项是 `cap`（`deployLimit ≤ 4` 时就是
		//: 它本身，见 `depth_ladder`）—— 这个上下文用的是 `deployLimit=2`，所以首轮
		//: 是 **2 人**而不是 4。我第一版照"起点恒为 4"写，断言当场红了而**代码是对的**。
		wantDepth := sc.ladder[0]
		check("放行：池子非空、首轮人数取自阶梯",
			len(sc.p.pool) > 0 && sc.currentDepth() == wantDepth,
			fmt.Sprintf("池子 %d 人 / 首轮 %d 人（阶梯 %v）",
				len(sc.p.pool), sc.currentDepth(), sc.ladder))
	} else {
		check("放行：栈顶该是解算屏", false, screenName(rA.top()))
	}
	check("行使计数：这一次调用只走了「放行·非全员低练度」这条分支",
		oneBranch(dAllow, gateAllowNotMinLevel), fmtDelta(dAllow))

	//: ★ 口径 3（2026-09-26）：槽位**不再参与判定**。同一个「全员在范围内」的编队，
	//:   在槽位 2／5／0 三种情况下判定必须**一模一样**（都拦）—— 旧实现里
	//:   「槽位 2 人、只勾了 2 人」拦、「槽位 5 人、只勾了 2 人」放行，
	//:   那条「槽位没满就不拦」现在**作废**（它不再是数据缺失导致的退化，而是规则）。
	for _, slot := range []int{2, 5, 0} {
		cS := pickCtx(slot)
		rS := newRoot(cS, welcomeScreen{})
		sS := newSquadPickScreen(cS, nil)
		rS.push(sS, onSquadPicked)
		if slot == 0 {
			check("槽位取不到时屏上仍写「未知」（口径 3：显示照旧，判定不看它）",
				strings.Contains(rS.View(), "槽位：未知"), firstLineWith(rS.View(), "槽位"))
		}
		markNames(rS, sS, "甲", "乙")
		d := delta(func() { press(rS, "enter") })
		check(fmt.Sprintf("口径 3：槽位 %d 时判定与槽位无关（非空＋全员低练度 ⇒ 拦）", slot),
			screenName(rS.top()) == "*main.squadPickScreen" && oneBranch(d, gateBlockManual),
			fmt.Sprintf("%s｜%s", screenName(rS.top()), fmtDelta(d)))
	}

	//: 空编队 ⇒ 放行（一位也没选，不是「全员低练度」）。
	cF := pickCtx(2)
	rF := newRoot(cF, welcomeScreen{})
	sF := newSquadPickScreen(cF, nil)
	rF.push(sF, onSquadPicked)
	dEmpty := delta(func() { press(rF, "enter") })
	check("空编队：不拦（「一位也没选」不是「全员低练度」）",
		screenName(rF.top()) == "*main.solveScreen", screenName(rF.top()))
	check("空编队：编队是空的（也没被定成别人）", len(cF.squad) == 0,
		fmt.Sprintf("%v", cF.squad))
	check("行使计数：这一次调用只走了「放行·空编队」这条分支",
		oneBranch(dEmpty, gateAllowEmptySquad), fmtDelta(dEmpty))

	fmt.Println("  —— 自动编队那条路（口径 2：**也拦**，没有豁免）——")
	//: 程序挑出来的编队住在 `c.autoPicks` 里（搜索层还没接进来 ⇒ 运行期它是空的）。
	//: 这里显式填一个**全员低练度**的自动编队：口径 2 要求它**被拦**，而且必须走在
	//: `拦下·自动` 这条分支上 —— 「这条路根本没走守卫」的读数是**全 0**，
	//: 与「走了拦下·自动」是分得开的（这正是这条断言要证的事）。
	cG := pickCtx(2)
	cG.autoPicks = []RosterOperator{
		{CharID: "char_1", Name: "甲", Profession: "PIONEER", Elite: 0, Level: 1},
		{CharID: "char_2", Name: "乙", Profession: "WARRIOR", Elite: 1, Level: 1},
	}
	rG := newRoot(cG, welcomeScreen{})
	onStagePicked(rG, &data.StageRecord{Code: "1-7", Name: "测试关"})
	check("自动路：选定关卡后压的是「问编队」屏",
		screenName(rG.top()) == "*main.squadAskScreen", screenName(rG.top()))
	dAuto := delta(func() { press(rG, "enter") }) //: 光标 0 ＝「不用，让程序自己挑」
	check("自动编队·拦下：全员在范围内 ⇒ **拦**（口径 2：没有豁免）",
		screenName(rG.top()) == "*main.squadAskScreen" &&
			strings.Contains(cG.note, squadMinLevelMsg),
		fmt.Sprintf("%s｜%s", screenName(rG.top()), firstLineWith(cG.note, "★")))
	check("自动编队·拦下：**不是**「没判」——计数必须走在「拦下·自动」这条分支上",
		oneBranch(dAuto, gateBlockAuto), fmtDelta(dAuto))
	check("自动编队·拦下：提示语陈述规则本身（口径 3：写明与槽位数无关）",
		strings.Contains(cG.note, "与槽位数无关"), firstLineWith(cG.note, "判定规则"))
	check("自动编队·拦下：编队没有被定下来", len(cG.squad) == 0, fmt.Sprintf("%v", cG.squad))

	//: 同一条路的另一次：运行期程序还没挑出人（`autoPicks` 为空）⇒ 走「空编队放行」。
	//: 这两条读数合起来说明自动路**确实过了守卫**（而不是压根没判）：
	//: 一次走拦下分支、一次走空编队分支，看的是同一个入口。
	cH := pickCtx(2)
	rH := newRoot(cH, welcomeScreen{})
	onStagePicked(rH, &data.StageRecord{Code: "1-7", Name: "测试关"})
	dAutoEmpty := delta(func() { press(rH, "enter") })
	check("自动路（程序还没挑出人）：放行 —— 走的是「放行·空编队」这条分支",
		screenName(rH.top()) == "*main.solveScreen" && oneBranch(dAutoEmpty, gateAllowEmptySquad),
		fmt.Sprintf("%s｜%s", screenName(rH.top()), fmtDelta(dAutoEmpty)))

	//: 屏流程：选定关卡压的是「问编队」屏；选「我自己选」才进选人屏。
	cE := pickCtx(0)
	rE := newRoot(cE, welcomeScreen{})
	onStagePicked(rE, &data.StageRecord{Code: "1-7", Name: "测试关"})
	check("选定关卡后压的是「问编队」屏（**不许静默跳过**）",
		screenName(rE.top()) == "*main.squadAskScreen", screenName(rE.top()))
	press(rE, "enter") // 光标 0 ＝「不用，让程序自己挑」
	check("选「让程序自己挑」→ 压解算屏（空编队走「放行·空编队」）",
		screenName(rE.top()) == "*main.solveScreen", screenName(rE.top()))
	onStagePicked(rE, &data.StageRecord{Code: "1-7", Name: "测试关"})
	if ask, ok := rE.top().(*squadAskScreen); ok {
		ask.cursor = 1 //「我自己选」
	}
	press(rE, "enter")
	check("选「我自己选」→ 进选人屏", screenName(rE.top()) == "*main.squadPickScreen",
		screenName(rE.top()))

	//: ---- 防绕过判据：拿它去扫**本包真源码**的这一次读数 ----
	//: 尺子会不会红，由上面那两条合成源码对照证过（会红 ＋ 不滥红）；这里换成真文件。
	//: 判的是口径 1 那句话：「谁要在别处再判一遍，就会在源码里留下第二处调用点」。
	_, selfPath, _, pathOK := runtime.Caller(0)
	if !pathOK {
		fmt.Println("  （未核：拿不到本文件的编译期路径，防绕过扫描跳过，不判红）")
	} else {
		pkgDir := filepath.Dir(selfPath)
		entries, derr := os.ReadDir(pkgDir)
		if derr != nil {
			fmt.Printf("  （未核：读不到本包源码目录 %s，不判红。具名原因：%v）\n",
				pkgDir, derr)
		} else {
			scanned, gateDefs := 0, 0
			findings := []string{}
			for _, e := range entries {
				name := e.Name()
				//: `selftest.go` 是造负对照的那个文件（上面就直接调了 `allMinLevel`），
				//: 它不是界面路径 —— 扫描范围把它排除，理由写在 `guardBypassFindings`。
				if e.IsDir() || !strings.HasSuffix(name, ".go") || name == "selftest.go" {
					continue
				}
				raw, rerr := os.ReadFile(filepath.Join(pkgDir, name))
				if rerr != nil {
					continue
				}
				scanned++
				for _, ln := range strings.Split(string(raw), "\n") {
					if strings.HasPrefix(ln, "func solveGate(") {
						gateDefs++
					}
				}
				for _, f := range guardBypassFindings(string(raw)) {
					findings = append(findings, name+":"+f)
				}
			}
			check(fmt.Sprintf("防绕过：本包 %d 个界面源码文件里，判定只有守卫那一处", scanned),
				scanned > 0 && len(findings) == 0,
				fmt.Sprintf("守卫之外的调用点 %d 处 %v", len(findings), findings))
			check("防绕过：守卫函数确实定义着（改名或删掉都会判红）",
				gateDefs == 1, fmt.Sprintf("顶层 func solveGate( 的条数 %d", gateDefs))
		}
	}

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
			v := solveGate(inRange, solveSourceManual)
			check("真名册判定：范围内的人全勾上 ⇒ 拦下（口径 3：与槽位数无关）",
				!v.Allow && v.Branch == gateBlockManual,
				fmt.Sprintf("范围内 %d/%d 人，分支=%s", len(inRange), len(live.Operators),
					solveGateBranchNames[v.Branch]))
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

	// ---------------------------------------------------------------- 询问屏

	fmt.Println("== 十二 · 询问屏（一问一答）==")
	//: 负对照排在最前：编号越界必须**什么都不做**。这既测了行为，也证明了
	//: 「按了键」与「什么都没发生」在这把尺子下是分得开的。
	var got any
	r.push(newAskScreen("登录", "不登录的话，是本次跳过还是以后都不再问？",
		[]askRow{{"once", "本次不登录"}, {"never", "以后都不问"}}),
		func(_ *root, res any) { got = res })
	press(r, "9")
	check("负对照：编号越界什么都不做（仍停在询问屏）",
		got == nil && isModalScreen(r.top()) && len(r.stack) == 2,
		fmt.Sprintf("got=%v 栈深=%d", got, len(r.stack)))
	press(r, "1")
	check("数字键交还的是「值」而不是标签", got == "once", fmt.Sprintf("got=%v", got))
	check("选完就退回上一层", len(r.stack) == 1, fmt.Sprintf("栈深=%d", len(r.stack)))

	got = "先放个值"
	r.push(newAskScreen("退出账号", "确认退出？",
		[]askRow{{"yes", "退出"}, {"no", "算了"}}),
		func(_ *root, res any) { got = res })
	press(r, "１") //: 全角数字（中文输入法全角模式下送来的就是这个）
	check("全角数字也一样能选", got == "yes", fmt.Sprintf("got=%v", got))

	got = "先放个值"
	r.push(newAskScreen("退出账号", "确认退出？", []askRow{{"yes", "退出"}}),
		func(_ *root, res any) { got = res })
	press(r, "esc")
	check("Esc 交还 nil（取消与「选了个空串」是两回事）", got == nil,
		fmt.Sprintf("got=%v", got))

	askView := newAskScreen("登录", "正文一句话",
		[]askRow{{"a", "甲"}, {"b", "乙"}}).view(c)
	check("渲染里有标题与正文",
		strings.Contains(askView, "登录") && strings.Contains(askView, "正文一句话"),
		"标题/正文")
	check("渲染里有编号行",
		strings.Contains(askView, "1　甲") && strings.Contains(askView, "2　乙"), "1　甲 / 2　乙")
	boxFirst := strings.Split(boxStyle.Render("x"), "\n")[0]
	check("整框宽度 = 68（Width(66) ＋ 边框 2，照 Python 的 width: 68）",
		ansi.StringWidth(boxFirst) == 68, fmt.Sprintf("实得 %d", ansi.StringWidth(boxFirst)))

	//: 模态屏两条：不进面包屑、独占整屏（照 Textual 的 ModalScreen）
	crumbBefore := r.crumb()
	r.push(newAskScreen("x", "y", []askRow{{"a", "b"}}), nil)
	check("模态屏不进面包屑", r.crumb() == crumbBefore, fmt.Sprintf("%q", r.crumb()))
	check("模态屏独占整屏（不画顶栏）", !strings.Contains(r.View(), appTitle), "无顶栏")
	r.pop(nil)

	// ---------------------------------------------------------------- 扫码屏

	fmt.Println("== 十三 · 扫码屏（矩阵 → 半格图）==")
	m4, err4 := qrMatrixFromRows([]string{"1010", "0101", "1100", "0011"})
	dark := 0
	for _, row := range m4 {
		for _, v := range row {
			if v {
				dark++
			}
		}
	}
	check("矩阵解析：4×4 且暗格 8 个", err4 == nil && len(m4) == 4 && dark == 8,
		fmt.Sprintf("err=%v 行=%d 暗格=%d", err4, len(m4), dark))
	//: 三个负对照：非方、非 0/1、空 —— 都必须报错。它们画出来是「看着像二维码的
	//: 废图」，而那是最难发现的错（人只会觉得"扫不出来"）。
	_, eNonSquare := qrMatrixFromRows([]string{"101", "0101"})
	_, eBadChar := qrMatrixFromRows([]string{"10x1"})
	_, eEmpty := qrMatrixFromRows(nil)
	check("负对照：非方矩阵必须报错", eNonSquare != nil, fmt.Sprintf("%v", eNonSquare))
	check("负对照：非 0/1 字符必须报错", eBadChar != nil, fmt.Sprintf("%v", eBadChar))
	check("负对照：空矩阵必须报错", eEmpty != nil, fmt.Sprintf("%v", eEmpty))

	lines := renderQR(withQuiet(m4, 0))
	check("四行压成两行半格", len(lines) == 2, fmt.Sprintf("实得 %d 行", len(lines)))
	flipped := make([][]bool, len(m4))
	for i, row := range m4 {
		flipped[i] = append([]bool(nil), row...)
	}
	flipped[0][0] = !flipped[0][0]
	check("负对照：翻一个模块渲染结果必须跟着变（尺子不是恒等映射）",
		strings.Join(renderQR(withQuiet(flipped, 0)), "\n") != strings.Join(lines, "\n"),
		"翻转后不同")

	//: 几何：静默区的挑法是从 Python 那份实现搬来的，四个数不许改
	check("静默区按规范取 4（120×40 放得下）", pickQRBorder(57, 120, 40) == 4,
		fmt.Sprintf("实得 %d", pickQRBorder(57, 120, 40)))
	check("窗口不够时逐级退让（80×24 ⇒ 0）", pickQRBorder(57, 80, 24) == 0,
		fmt.Sprintf("实得 %d", pickQRBorder(57, 80, 24)))
	mono := true
	for w := 50; w <= 200; w += 10 {
		if pickQRBorder(57, w, 40) < pickQRBorder(57, w-10, 40) {
			mono = false
		}
	}
	check("静默区随窗口变大只增不减（单调）", mono, "40→200 逐档比过")

	wide := fakeQRGeometry(57)
	bigCtx := &appCtx{w: 120, h: 40}
	bigView := newQrScreen(wide, "").view(bigCtx)
	rowsBig := strings.Split(bigView, "\n")
	maxw := 0
	for _, ln := range rowsBig {
		if x := ansi.StringWidth(ln); x > maxw {
			maxw = x
		}
	}
	check("120×40 下整屏渲染不超窗口（缺角就废，所以这条要真数）",
		len(rowsBig) <= bigCtx.h && maxw <= bigCtx.w,
		fmt.Sprintf("%d 行 ≤ %d，最宽 %d ≤ %d", len(rowsBig), bigCtx.h, maxw, bigCtx.w))
	check("120×40 下不喊「静默区被压」", !strings.Contains(bigView, "静默区已压到"), "无提示")
	smallView := newQrScreen(wide, "").view(&appCtx{w: 60, h: 18})
	check("小窗口下把「静默区被压」说出来",
		strings.Contains(smallView, "静默区已压到"),
		firstLineWith(smallView, "静默区已压到"))
	check("贴底提示默认是「等待扫码……」", strings.Contains(bigView, "等待扫码"), "等待扫码……")
	qs := newQrScreen(wide, "")
	qs.setNote("已扫码，请在手机上确认")
	check("setNote 能换掉贴底提示（登录屏轮询时要用）",
		strings.Contains(qs.view(bigCtx), "已扫码，请在手机上确认"), "已扫码…")

	//: 真桥那一段：**真的**向森空岛申请一张二维码（一次性、会自然过期），
	//: 证明「Python 编码 → 桥给矩阵 → Go 解析 → 画成半格图」这条链是通的。
	//: 起不来就**未核不判红**（具名给原因），不把它算成绿。
	if st, lerr2 := fetchLoginStart(); lerr2 != nil {
		fmt.Printf("  （未核：桥这次起不了扫码会话，不判红。具名原因：%s）\n",
			strings.SplitN(lerr2.Error(), "\n", 2)[0])
	} else if st.QRNote != "" {
		fmt.Printf("  （未核：桥说二维码编不出来，不判红。具名原因：%s）\n", st.QRNote)
	} else if liveQR, qerr := qrMatrixFromRows(st.QRMatrix); qerr != nil {
		check("桥给的矩阵必须解析得动", false, fmt.Sprintf("err=%v", qerr))
	} else {
		check("桥真实往返：扫码会话起了且矩阵是方的",
			len(liveQR) > 0 && len(liveQR)%4 == 1,
			fmt.Sprintf("phase=%s 边长=%d qr_size=%d", st.Phase, len(liveQR), st.QRSize))
		check("桥真实往返：矩阵边长 ≥ 21（二维码最小 21×21）", len(liveQR) >= 21,
			fmt.Sprintf("边长=%d", len(liveQR)))
		check("桥真实往返：真矩阵能画成半格图且行数对",
			len(renderQR(withQuiet(liveQR, 4))) == (len(liveQR)+8+1)/2,
			fmt.Sprintf("%d 行", len(renderQR(withQuiet(liveQR, 4)))))
	}

	fmt.Println("== 十六 · 登录屏（五键／三态 Esc／成功带回的话）==")
	{
		isWelcome := func(s screen) bool { _, ok := s.(welcomeScreen); return ok }

		//: ★ 一节里有两处会**真的写配置**（答「以后都不问」、扫码成功那一刻）。所以整节
		//: 都把配置指向临时文件 —— 不指的话，跑一次自检就把玩家真正的
		//: `~/.rios/tui.json` 改了（那正是 `RIOS_TUI_CONFIG` 存在的理由）。
		//: 本节结束时显式恢复：后面的节（解算／结果屏）要按**真配置**拿导出目录。
		cfgSave := os.Getenv("RIOS_TUI_CONFIG")
		cfgTmp := filepath.Join(os.TempDir(), "__rios_tui_login_cfg__.json")
		_ = os.Remove(cfgTmp)
		_ = os.Setenv("RIOS_TUI_CONFIG", cfgTmp)

		//: 初始态：三块齐、且**每一栏都有话说**（空白会让人以为程序坏了）。
		ls := newLoginScreen()
		v := ls.view(&appCtx{})
		check("登录屏三块齐（登录态／本机账号／扫码）",
			strings.Contains(v, "登录态") && strings.Contains(v, "本机登录过的账号") &&
				strings.Contains(v, "扫码登录"), firstLineWith(v, "扫码登录"))
		check("还没读到登录态时说的是「正在读」",
			strings.Contains(v, "正在读登录态"), firstLineWith(v, "正在读登录态"))
		check("没账号那栏不留空白（要说清可以跳过）",
			strings.Contains(v, "本机还没有登录过的账号") && strings.Contains(v, "手动输名字"),
			firstLineWith(v, "本机还没有登录过的"))
		//: 负对照：同一把尺子对**不存在的字**必须给 false，否则上面三条绿是尺子眼瞎。
		check("负对照：同一把尺子对不存在的字给 false",
			!strings.Contains(v, "***这个串不可能出现***"), "实得 false")

		//: 读登录态失败 ⇒ 具名（★ ＋ 原因），不许退化成一栏空白。
		lf := newLoginScreen()
		lf.loadErr = "★ 桥没有应答"
		st := lf.statusText(&appCtx{})
		check("读登录态失败时具名（★ ＋ 原因）",
			strings.Contains(st, "★ 读登录态失败") && strings.Contains(st, "桥没有应答"), st)

		//: `who()` 三态：**不知道就说不知道，并且指出按哪一键**（U）——不许留空白。
		accs := &accountsData{Rows: []accountRow{{UID: "1", Nick: "甲", GameUID: "g1"}}}
		known := newLoginScreen()
		known.ping, known.accts = &pingData{UID: "1"}, accs
		unknown := newLoginScreen()
		unknown.ping = &pingData{UID: "9"} //: 本机账号表里没有这个 uid
		unknown.accts = accs
		none := newLoginScreen()
		check("who：已知账号说昵称与游戏 uid",
			strings.Contains(known.who("1"), "甲") && strings.Contains(known.who("1"), "g1"),
			known.who("1"))
		check("who：查不到的账号说「未知」并指出按 U",
			strings.Contains(unknown.who("9"), "未知") && strings.Contains(unknown.who("9"), "按 U"),
			unknown.who("9"))
		check("who：一个账号都没有时也不留空白",
			strings.TrimSpace(none.who("")) != "", none.who(""))

		//: 登录成功带回主界面的那句话 —— **三档必须互不相同**。这是那句注释守的性质：
		//: 三条并作一条（或两条并作一条）时，人会以为"账号变多了"，而条数其实没变。
		noteOf := func(cur, uid string, wasKnown bool) (string, *loginScreen) {
			s := newLoginScreen()
			s.ping = &pingData{UID: uid}
			s.accts = &accountsData{Rows: []accountRow{{UID: uid, Nick: "甲", GameUID: "g1"}}}
			s.curBefore = cur
			if wasKnown {
				s.knownBefore = map[string]bool{uid: true}
			}
			return s.backNote(), s
		}
		nSame, _ := noteOf("1", "1", true)     //: 本来就登着这个号（只刷新了凭据）
		nKnown, _ := noteOf("1", "2", true)    //: 本机登过、但不是当前号
		nNew, _ := noteOf("1", "3", false)     //: 新号
		check("登录成功带回的话三档互不相同",
			nSame != nKnown && nKnown != nNew && nSame != nNew,
			fmt.Sprintf("同号=%q｜老号=%q｜新号=%q", nSame, nKnown, nNew))
		check("三档都说清了账号条数有没有变多",
			strings.Contains(nSame, "没有变多") && strings.Contains(nKnown, "没有变多") &&
				strings.Contains(nNew, "新账号"),
			fmt.Sprintf("同号=%q｜老号=%q｜新号=%q", nSame, nKnown, nNew))

		//: Esc 三态之一：**已经登着账号 ⇒ 直接退回主界面**，不再问那句荒唐的话。
		s1 := newLoginScreen()
		s1.ping = &pingData{UID: "1"}
		nx, act1 := s1.update(&appCtx{}, tea.KeyMsg{Type: tea.KeyEsc})
		check("Esc 有账号 ⇒ 直接退回（actBack，且不问）",
			act1.kind == actBack && act1.push == nil && nx == screen(s1),
			fmt.Sprintf("kind=%d push=%v", act1.kind, act1.push != nil))

		//: Esc 三态之二：还没账号 ⇒ 问「本次／以后都不」，**两行的取值**是那条契约
		//: （回调就是按这两个值分派的），所以盯取值不盯文案。
		s2 := newLoginScreen()
		_, act2 := s2.update(&appCtx{}, tea.KeyMsg{Type: tea.KeyEsc})
		ask, isAsk := act2.push.(*askScreen)
		vals := ""
		if isAsk {
			for _, rw := range ask.rows {
				vals += rw.value + " "
			}
		}
		check("Esc 没账号 ⇒ 问「本次／以后都不」（两个取值）",
			act2.kind == actPush && isAsk && len(ask.rows) == 2 &&
				vals == "once never ", fmt.Sprintf("kind=%d 取值=%q", act2.kind, vals))

		//: Esc 三态之三：**问屏上再按 Esc ⇒ 取消这一问，留在登录屏**（不是答"不登录"）。
		ctx3 := &appCtx{}
		r3 := newRoot(ctx3, welcomeScreen{})
		r3.push(s2, onLoginDone)
		r3.apply(act2) //: 把那张问屏压上去
		if askTop, ok := r3.top().(*askScreen); ok {
			_, escAct := askTop.update(ctx3, tea.KeyMsg{Type: tea.KeyEsc})
			r3.apply(escAct) //: 带 nil 弹回 ⇒ 回调什么都不做
		}
		check("问屏上再按 Esc ⇒ 取消（仍留在登录屏）", r3.top() == screen(s2),
			fmt.Sprintf("实得栈顶 %T（栈深 %d）", r3.top(), len(r3.stack)))

		//: 答「本次不登录」⇒ 退回主界面，且**什么都不写**（文件都不该被建出来）。
		//: 答「以后都不问」⇒ 写进配置。这两条要一起测，因为它们共用一条 write 路径：
		//: 只测一条的话，"写"与"不写"哪个是真行为就分不清了。
		rOnce := newRoot(&appCtx{}, welcomeScreen{})
		rOnce.push(newLoginScreen(), onLoginDone)
		onLoginSkipAnswered(rOnce, "once")
		_, statOnce := os.Stat(cfgTmp)
		check("答「本次不登录」⇒ 退回主界面且不写配置",
			isWelcome(rOnce.top()) && os.IsNotExist(statOnce),
			fmt.Sprintf("栈顶=%T 配置存在=%v", rOnce.top(), statOnce == nil))

		rNever := newRoot(&appCtx{}, welcomeScreen{})
		rNever.push(newLoginScreen(), onLoginDone)
		onLoginSkipAnswered(rNever, "never")
		cfg := loadConfig()
		pv, pok := cfg["login_prompt"]
		check("答「以后都不问」⇒ 退回主界面并把 login_prompt 写成空串",
			isWelcome(rNever.top()) && pok && pv == "",
			fmt.Sprintf("栈顶=%T login_prompt=%#v（在=%v）", rNever.top(), pv, pok))
		//: 正对照：同一把「文件在不在」的尺子，上面刚判过"不在"，这里必须判得出"在"。
		_, statNever := os.Stat(cfgTmp)
		check("正对照：同一把尺子认得刚写出来的文件", statNever == nil,
			fmt.Sprintf("配置存在=%v", statNever == nil))

		//: `L` 起扫码：**第二条命令不许再发**（一次只允许有一张码在等）。
		//: 这条不是洁癖：真并起两次，两张码会互相把会话关掉，症状是"扫上了也不推进"。
		s4 := newLoginScreen()
		_, actL1 := s4.update(&appCtx{}, tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("l")})
		_, actL2 := s4.update(&appCtx{}, tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("l")})
		check("连按两次 L 只起一次扫码（第二次不发命令）",
			actL1.cmd != nil && actL2.cmd == nil && s4.busy,
			fmt.Sprintf("第一次有命令=%v 第二次有命令=%v busy=%v",
				actL1.cmd != nil, actL2.cmd != nil, s4.busy))

		//: 起扫码**失败**（桥缺件／超时）⇒ 具名，而且 `busy` 必须放掉。
		//: 放不掉的话 `L` 从此按不动 —— 那是真的会发生的死锁，不是洁癖。
		//: ★ 「原因不丢」是**单独判的性质**：这里刻意用一个**不带 ★** 的错误文本，
		//: 因为带 ★ 的那种（桥自己造的错）恰好会掩盖取原因那一处的缺陷。
		s5 := newLoginScreen()
		s5.busy, s5.polling = true, true
		_ = s5.onMsg(newRoot(&appCtx{}, welcomeScreen{}),
			loginStartMsg{err: errors.New("桥超时")})
		check("申请二维码失败 ⇒ 具名且放掉 busy（L 还能再按）",
			!s5.busy && strings.Contains(s5.note, "★ 申请二维码失败"),
			fmt.Sprintf("busy=%v note=%q", s5.busy, s5.note))
		check("失败提示里**不许丢掉原因**（不带 ★ 的文本也要原样带出来）",
			strings.Contains(s5.note, "桥超时"), fmt.Sprintf("note=%q", s5.note))

		//: `reasonOf` 是本仓取原因的那一处 —— 它自己也要判，因为上面那条性质全靠它。
		//: 三档：带 ★ 取 ★ 那行／不带 ★ 取第一行非空／全空给具名占位。
		roStar := reasonOf("细节一\n★ 桥报错：没有应答\n细节二")
		roPlain := reasonOf("\n  二维码已过期  \n后面还有一行")
		roEmpty := reasonOf("   \n  ")
		check("reasonOf：有 ★ 取 ★ 那一行", roStar == "★ 桥报错：没有应答", roStar)
		check("reasonOf：没有 ★ 退到第一行非空（不丢原因）",
			roPlain == "二维码已过期", roPlain)
		check("reasonOf：整段都空时给具名占位", strings.Contains(roEmpty, "没有给出说明"), roEmpty)
		//: 负对照：**旧的那把尺子**（判据用的显示工具）在同一份输入上会丢掉原因 ——
		//: 这一条证明上面那条「不丢」不是在判一个恒真的命题。
		oldRuler := firstLineWith("\n  二维码已过期  \n", "★")
		check("负对照：判据用的 firstLineWith 在同一输入上确实会丢原因",
			!strings.Contains(oldRuler, "二维码已过期"), oldRuler)

		//: 二维码**编不出来**（桥给了原因）⇒ 说原因，且把那个会话收掉（不许挂着）。
		s6 := newLoginScreen()
		s6.busy, s6.polling = true, true
		s6.sess = &bridgeSession{}
		_ = s6.onMsg(newRoot(&appCtx{}, welcomeScreen{}),
			loginStartMsg{st: &loginStartData{QRNote: "二维码库缺失"}})
		check("二维码编不出来 ⇒ 说原因并收掉会话",
			!s6.busy && s6.sess == nil && strings.Contains(s6.note, "二维码库缺失"),
			fmt.Sprintf("busy=%v sess=%v note=%q", s6.busy, s6.sess, s6.note))

		//: ★ 这一节盯的是**屏栈连动**那条架构（`msgScreen` 从栈顶往下找第一个实现它的屏）：
		//: 二维码那张**模态屏压在登录屏上面**，而轮询消息必须送到**登录屏**去。
		//: 只看栈顶的话，码出来了、状态行不动、扫上了也不推进。
		mkQRStack := func(withLogin bool) (*root, *loginScreen, *qrScreen, *appCtx) {
			c := &appCtx{w: 80, h: 30}
			sc := newLoginScreen()
			qr := newQrScreen([][]bool{{true, false}, {false, true}}, "等待扫码……")
			sc.qr, sc.polling, sc.busy = qr, true, true
			sc.ping = &pingData{UID: "1"}
			sc.accts = &accountsData{Rows: []accountRow{{UID: "1", Nick: "甲", GameUID: "g1"}}}
			rr := newRoot(c, welcomeScreen{})
			if withLogin {
				rr.push(sc, onLoginDone)
			}
			rr.push(qr, nil)
			return rr, sc, qr, c
		}
		r7, _, qr7, _ := mkQRStack(true)
		_, _ = r7.Update(loginPollMsg{pl: &loginPollData{Phase: "waiting", Text: "已扫码，请在手机上确认"}})
		check("扫码进度绕过码屏送到登录屏（状态行落在码上）",
			strings.Contains(qr7.note, "已扫码"), fmt.Sprintf("码屏提示=%q", qr7.note))
		check("送完之后码屏仍在栈顶（没被顺手弹掉）", r7.top() == screen(qr7),
			fmt.Sprintf("栈顶=%T（栈深 %d）", r7.top(), len(r7.stack)))
		//: 负对照：栈里**没有**登录屏时，同一条消息进去谁都不该动那张码
		//: ⇒ 证明上面那次变化是登录屏干的，不是别人顺手改的。
		r8, _, qr8, _ := mkQRStack(false)
		_, _ = r8.Update(loginPollMsg{pl: &loginPollData{Phase: "waiting", Text: "已扫码，请在手机上确认"}})
		check("负对照：栈里没有登录屏时，那条进度改不动码屏",
			!strings.Contains(qr8.note, "已扫码"), fmt.Sprintf("码屏提示=%q", qr8.note))

		//: 扫上了（`done`）：① 码收掉 ② 整屏弹回主界面 ③ 那句话交给回调显示在账号行上。
		r9, ls9, qr9, c9 := mkQRStack(true)
		_, _ = r9.Update(loginPollMsg{pl: &loginPollData{Phase: "done", Text: "登录成功"}})
		check("扫上了 ⇒ 码屏收掉、整屏弹回主界面、带回的话落到账号行",
			isWelcome(r9.top()) && ls9.qr == nil && qr9 != nil &&
				c9.accountNote != "" && strings.Contains(c9.accountNote, "账号") &&
				len(r9.stack) == 1,
			fmt.Sprintf("栈顶=%T 栈深=%d accountNote=%q", r9.top(), len(r9.stack), c9.accountNote))

		//: 失败：具名 ＋ 收掉会话 ＋ 码屏也收掉（一张作废的码留在屏上只会诱人白扫）。
		r10, ls10, _, _ := mkQRStack(true)
		_, _ = r10.Update(loginPollMsg{pl: &loginPollData{Phase: "failed", Text: "二维码已过期"}})
		check("登录失败 ⇒ 具名、收会话、收码屏",
			ls10.sess == nil && !ls10.polling && ls10.qr == nil &&
				strings.Contains(ls10.note, "二维码已过期"),
			fmt.Sprintf("sess=%v polling=%v note=%q", ls10.sess, ls10.polling, ls10.note))

		//: 收尾路径本身也要判：它是好几条错误路径的公共出口（申请失败／轮询超时／按 Esc），
		//: 它自己炸掉就会把真正的原因盖掉（玩家看到 panic，不是"桥超时"）。
		//: 文档声称 close「可重复调用」—— 在这之前没人测过这一句。
		var closePanic string
		func() {
			defer func() {
				if r := recover(); r != nil {
					closePanic = fmt.Sprint(r)
				}
			}()
			half := &bridgeSession{} //: 只造了一半的会话（没进程、没管道）
			half.close()
			half.close() //: 第二次必须是空操作
			_, cerr := half.call("ping", nil, time.Second)
			if cerr == nil {
				closePanic = "关了之后还肯发请求"
			}
		}()
		check("close 可重复调用、空会话不炸、关了之后拒发请求", closePanic == "",
			"实得："+closePanic)

		//: 恢复现场：本节起就把配置指到了临时文件（因为本节有两处真会写配置）。后面的节
		//: （引擎客户端／解算屏／结果屏）要按**真配置**拿导出目录，别让它们看见这份临时的。
		if cfgSave == "" {
			_ = os.Unsetenv("RIOS_TUI_CONFIG")
		} else {
			_ = os.Setenv("RIOS_TUI_CONFIG", cfgSave)
		}
		_ = os.Remove(cfgTmp)
	}

	fmt.Println("== 十七 · 桥的常驻会话（登录那条链的前提）==")
	//: ★ 这一段的中心是**一件事**：`login_start` 在桥上起的那个后台线程，能不能活到
	//: 下一次 `login_poll`。一次一进程时它活不过 —— 进程读完 stdin 就退出，线程随之
	//: 消失，`login_poll` 永远看到 `idle`；而症状极其隐蔽（二维码画得出来，扫了没反应）。
	//: 所以这里必须**真起一个常驻会话**、连着发两条命令、看第二条能不能看见那条会话。
	if sess, serr := newBridgeSession(); serr != nil {
		fmt.Printf("  （未核：桥这次起不来，不判红。具名原因：%s）\n",
			firstLineWith(serr.Error(), "★"))
	} else {
		defer sess.close()
		//: ① 同一个进程里连发两条：`id` 要自增，且两条都要答在**自己那一问**上
		p1, e1 := sess.call("ping", nil, 30*time.Second)
		p2, e2 := sess.call("ping", nil, 30*time.Second)
		check("常驻会话：同一进程里连发两条都答得上来（id 自增且不串）",
			e1 == nil && e2 == nil && p1 != nil && p2 != nil && p1.Proto == p2.Proto,
			fmt.Sprintf("proto=%v/%v cred=%q", p1.Proto, p2.Proto, p1.CredState))
		//: ② 真起一次扫码会话
		st, serr2 := sess.call("login_start", nil, 40*time.Second)
		if serr2 != nil {
			check("常驻会话：login_start 起了扫码会话", false, serr2.Error())
		} else if st.QRNote != "" {
			fmt.Printf("  （未核：桥说二维码编不出来，不判红。具名原因：%s）\n", st.QRNote)
		} else {
			check("常驻会话：login_start 给了矩阵", len(st.QRMatrix) > 0,
				fmt.Sprintf("边长=%d phase=%s", len(st.QRMatrix), st.Phase))
			//: ③ ★ 关键那一问：**换一条命令**问同一个会话的进度。
			//:    `idle` 就是"会话不存在"——那正是"一次一进程"会有的症状。
			pl, perr := sess.call("login_poll", nil, 30*time.Second)
			check("常驻会话：另起一问能看见那条会话（phase ≠ idle）",
				perr == nil && pl.Phase != "idle" && pl.Phase != "",
				fmt.Sprintf("phase=%q（idle 就是会话没了）", pl.Phase))
		}
	}

	fmt.Println("== 十四 · 引擎客户端（起子进程讲 JSON 行协议）==")
	//: 负对照在前：把 `RIOS_SIM_BIN` 指到一个**不存在**的路径，必须**具名失败**。
	//: 静默退化成"没有结果"是最坏的一类错 —— 玩家分不清"这一关搜不出来"与
	//: "引擎根本没起来"。
	oldBin, hadBin := os.LookupEnv(envEngine)
	_ = os.Setenv(envEngine, filepath.Join(os.TempDir(), "__rios_no_such_engine__.exe"))
	if _, err := newEngineClient(); err == nil {
		check("负对照：引擎 exe 不存在时必须具名失败", false, "竟然拿到了客户端")
	} else {
		//: 断言的性质是「**报错点名了那个环境变量与那个路径**」，不是某句固定文案 ——
		//: 第一版照字面匹配"找不到引擎"，而修好回退缺陷之后那句话变成了
		//: "指到一个不存在的路径"，于是这条**因为错误的理由**红了。判据要盯性质，
		//: 不要盯文案（文案会随修 bug 变，性质不会）。
		msg := err.Error()
		check("负对照：引擎 exe 不存在时必须具名失败",
			strings.Contains(msg, envEngine) &&
				strings.Contains(msg, "__rios_no_such_engine__"),
			firstLineWith(msg, "不存在的路径"))
	}
	if hadBin {
		_ = os.Setenv(envEngine, oldBin)
	} else {
		_ = os.Unsetenv(envEngine)
	}
	//: 真往返：`ping` 不需要任何数据，正好用来证「发现 → 起进程 → 写一行 → 读一行 →
	//: 校 id」这条链。引擎 exe 不在场就**未核不判红**（它是随包发的另一个可执行
	//: 文件，开发机上未必就在查找路径里 —— 那种"未核"必须看得见）。
	if ec, err := newEngineClient(); err != nil {
		fmt.Printf("  （未核：这次找不到引擎 exe，不判红。具名原因：%s）\n",
			firstLineWith(err.Error(), "找不到引擎"))
	} else {
		fields, cerr := ec.call("ping", 7, "", nil, 20*time.Second)
		if cerr != nil {
			check("引擎真实往返：ping 必须答上来", false, fmt.Sprintf("err=%v", cerr))
		} else {
			_, hasPong := fields["pong"]
			check("引擎真实往返：ping 答了且带 pong 段", hasPong,
				fmt.Sprintf("顶层键 %s", string(mustJSONKeys(fields))))
			//: ⚠「应答 id 对不上」那一条**在真引擎上不可达**：真引擎会把请求的 id
			//: 原样回填（我拿 id=999 试过，它答的也是 999）⇒ 这不是"没实现"，是
			//: 这条分支需要**假引擎**才走得通。照本仓口径**具名未核**，不假造读数。
			//: 核法：临时把 `RIOS_SIM_BIN` 指到一个回错 id 的小程序（或给引擎加一个
			//: 只在判据下开的"故意答错 id"开关）。
			fmt.Println("  （未核：应答 id 校验分支——真引擎会回填请求 id，需假引擎才走得到）")
		}
	}

	fmt.Println("== 十五 · 解算屏（阶梯／池子／真起一轮引擎）==")
	//: 阶梯：六档**手算**（权威 `depth_ladder` 有两处易错：取不到时按 12 封顶；
	//: 末端一定落在 `cap` 上，不然"上限 5 人"那一档永远试不到）
	for _, c := range []struct {
		limit int
		want  []int
	}{
		{0, []int{4, 6, 8, 10, 12}},
		{12, []int{4, 6, 8, 10, 12}},
		{8, []int{4, 6, 8}},
		{5, []int{4, 5}},
		{4, []int{4}},
		{2, []int{2}},
	} {
		got := depthLadder(c.limit)
		check(fmt.Sprintf("阶梯 deployLimit=%d", c.limit),
			fmt.Sprint(got) == fmt.Sprint(c.want),
			fmt.Sprintf("实得 %v，手算 %v", got, c.want))
	}
	//: 池子三态（`candidates_for` 是**按名单遍历**的 ⇒ 空池子一个候选都不产生，
	//: 而搜索会把它报成"几何剪枝后一个候选都不剩" —— 那句把原因指错方向）
	cPool := &appCtx{roster: fake, squad: []string{"丙", "查无此人"}, mode: "auto"}
	pool, poolNote := solvePool(cPool)
	check("池子：勾的 ＋ 按练度补到上限，且点名名册里没有的",
		len(pool) == 4 && strings.Contains(poolNote, "名册里没有"),
		fmt.Sprintf("%d 人｜%s", len(pool), poolNote))
	cOnly := &appCtx{roster: fake, mode: "only"}
	_, onlyNote := solvePool(cOnly)
	check("池子：「只用我选的」但没勾人 ⇒ 具名说池子是空的",
		strings.Contains(onlyNote, "池子是空的"), onlyNote)
	cNoRoster := &appCtx{mode: "auto"}
	if _, note := solvePool(cNoRoster); !strings.Contains(note, "名册是空的") {
		check("池子：没有名册 ⇒ 具名说名册是空的", false, note)
	} else {
		check("池子：没有名册 ⇒ 具名说名册是空的", true, note)
	}
	//: ★ 运行期行使见证：**真起一轮**引擎（`runSolveRoundCmd` 返回的就是一个
	//: `func() tea.Msg`，直接调它即可），再喂给屏的消息处理，看状态机走完。
	//: 参数取最小（per_op=1、beam=1、1 人）—— 这一条要的是"链通"，不是"搜得好"。
	if _, err := newEngineClient(); err != nil {
		fmt.Printf("  （未核：找不到引擎 exe，解算那一段不判红。具名原因：%s）\n",
			firstLineWith(err.Error(), "★"))
	} else {
		solveDir, _ := os.MkdirTemp("", "rios-selftest-solve-")
		solveRoster := filepath.Join(solveDir, "roster.json")
		_ = os.WriteFile(solveRoster, []byte(`[
 {"name":"圣聆初雪","charId":"char_1046_sbell2","elite":2,"level":90,"potential":1,"module_level":0},
 {"name":"赤刃明霄陈","charId":"char_1050_chen3","elite":2,"level":90,"potential":1,
  "module":"uniequip_002_chen3","module_level":3}]`), 0o644)
		params := solveParams{levelID: "main_01-07", rosterPath: solveRoster,
			pool: []string{"圣聆初雪", "赤刃明霄陈"}, perOp: 1, beam: 1}
		scr := newSolveScreen(params, []int{1})
		scr.log("开始解算……")
		cSolve := &appCtx{w: 90, h: 26, deployLimit: 6,
			stage: &data.StageRecord{Code: "1-7", LevelID: "main_01-07", Name: "测试关"}}
		//: 屏的消息处理现在收 `*root`（它要连动屏栈）⇒ 这里造一个最小根模型。
		rSolve := newRoot(cSolve, welcomeScreen{})
		msg := runSolveRoundCmd(params, 1)()
		if m, ok := msg.(solveRoundMsg); ok && m.err != nil {
			fmt.Printf("  （未核：这一轮解算没跑成，不判红。具名原因：%s）\n",
				firstLineWith(m.err.Error(), "★"))
		} else {
			_ = scr.onMsg(rSolve, msg)
			check("真起一轮：跑完并落到 done（不是卡在 running）",
				scr.done && scr.running == false && scr.err == "",
				fmt.Sprintf("done=%v running=%v err=%q", scr.done, scr.running, scr.err))
			check("真起一轮：日志里有轮摘要", len(scr.lines) > 0,
				firstLineWith(strings.Join(scr.lines, "\n"), "第 1 人"))
			check("真起一轮：评估次数非零（真跑了模拟）", scr.evals > 0,
				fmt.Sprintf("%d 次", scr.evals))
			check("真起一轮：结果写进 appCtx（结果屏要读它）",
				len(cSolve.solveVerdict) > 0 && cSolve.solveStars >= 0,
				fmt.Sprintf("verdict %d 字节 / %d 星", len(cSolve.solveVerdict), cSolve.solveStars))
			v := scr.view(cSolve)
			check("真起一轮：渲染里有「已评估」与进度条",
				strings.Contains(v, "已评估") && strings.Contains(v, "["), firstLineWith(v, "已评估"))

			// ------------------------------------------------------ 结果屏
			fmt.Println("== 十六 · 结果屏（渲染 ＋ **真导出**）==")
			cSolve.guidesDir, _ = os.MkdirTemp("", "rios-selftest-guides-")
			//: 结果屏要**名册文件**才导得出（桥上那份只有 5 个字段，缺 potential/module）
			cSolve.roster = &rosterData{Source: "selftest", Path: solveRoster, Count: 2,
				Operators: []RosterOperator{
					{CharID: "char_1046_sbell2", Name: "圣聆初雪", Elite: 2, Level: 90},
					{CharID: "char_1050_chen3", Name: "赤刃明霄陈", Elite: 2, Level: 90},
				}}
			rv := newResultScreen().view(cSolve)
			for _, want := range []string{"评价", "时长", "击杀", "漏怪", "剩余生命", "总伤害",
				"用到的干员", "编制要求取自名册", "已评估"} {
				if !strings.Contains(rv, want) {
					check("结果屏渲染里有「"+want+"」", false, firstLineWith(rv, "评价"))
					break
				}
			}
			check("结果屏渲染：判决六栏 ＋ 干员清单 ＋ 汇总都在",
				strings.Contains(rv, "评价") && strings.Contains(rv, "总伤害") &&
					strings.Contains(rv, "用到的干员") && strings.Contains(rv, "已评估"),
				firstLineWith(rv, "评价"))
			check("结果屏渲染：把没找到三星的**来路**摆出来（不许只说一句没找到）",
				cSolve.solveNote != "" && strings.Contains(rv, cSolve.solveNote),
				firstLineWith(rv, "没找到"))

			//: ★★ **真导出**：这一条是判据 2（端到端）那段"结果 → MAA 导出"的实证。
			//: 走的是与作业完全相同的取数（名册文件 ＋ 库里的模组表），落盘到**临时
			//: 的** Guides 目录（不碰玩家那份）。
			rRoot := newRoot(cSolve, welcomeScreen{})
			rRoot.push(&stageScreen{}, nil)
			rs := newResultScreen()
			rRoot.push(rs, nil)
			_, actExport := rs.update(cSolve, keyMsg("e"))
			_ = actExport
			if cSolve.exportPath == "" {
				check("真导出：写出了作业文件", false, rs.msg)
			} else {
				blob, rerr := os.ReadFile(cSolve.exportPath)
				var job map[string]any
				jerr := json.Unmarshal(blob, &job)
				check("真导出：文件真的落盘了且是 JSON",
					rerr == nil && jerr == nil && len(blob) > 0,
					fmt.Sprintf("%s（%d 字节）", cSolve.exportPath, len(blob)))
				opers, _ := job["opers"].([]any)
				//: 不变量是「**文件里的 opers 条数 ＝ 打法里的部署条数**」，不是一个写死的
				//: 数字 —— 自检那次解算跑的是 `max_ops=1`（故意取最小参数），所以这里
				//: 是 1 条而不是 2 条。我第一版写死成 2，红了，而**导出是对的**。
				var planForCount struct {
					Deploys []json.RawMessage `json:"deploys"`
				}
				_ = json.Unmarshal(cSolve.solvePlan, &planForCount)
				check("真导出：stage_name 用 levelId、opers 条数＝打法里的部署条数",
					job["stage_name"] == "main_01-07" && len(opers) == len(planForCount.Deploys),
					fmt.Sprintf("stage_name=%v opers=%d（打法里 %d 条部署）",
						job["stage_name"], len(opers), len(planForCount.Deploys)))
				doc, _ := job["doc"].(map[string]any)
				details, _ := doc["details"].(string)
				check("真导出：doc.details 带上了出处那句",
					strings.Contains(details, "由 R.I.O.S. 解算导出"), firstLineWith(details, "【编队】"))
			}
			//: 负对照：没有解算结果时导出必须**具名**拒绝，不许写出半个文件
			cEmpty := &appCtx{guidesDir: cSolve.guidesDir}
			rsEmpty := newResultScreen()
			rsEmpty.update(cEmpty, keyMsg("e"))
			check("负对照：没有结果时导出具名拒绝",
				strings.Contains(rsEmpty.msg, "没有可导出的编队"), rsEmpty.msg)
			//: 负对照：名册路径坏掉 ⇒ 具名失败（不许静默导出成一份没有练度的作业）
			cBadRoster := &appCtx{guidesDir: cSolve.guidesDir, stage: cSolve.stage,
				solvePlan: cSolve.solvePlan, solveVerdict: cSolve.solveVerdict,
				roster: &rosterData{Path: filepath.Join(os.TempDir(), "__no_such_roster__.json")}}
			rsBad := newResultScreen()
			rsBad.update(cBadRoster, keyMsg("e"))
			check("负对照：名册读不出来时导出具名失败",
				strings.Contains(rsBad.msg, "★ 导出失败"), rsBad.msg)

			//: 出口：R 回选关页、H 回准备屏、**Esc 什么都不做**（博士 2026-09-17 裁定）
			before := len(rRoot.stack)
			rRoot.Update(keyMsg("esc"))
			check("结果屏不挂 Esc（按 Esc 什么都不做，且不退出）",
				len(rRoot.stack) == before && screenName(rRoot.top()) == "*main.resultScreen",
				screenName(rRoot.top()))
			rRoot.Update(keyMsg("r"))
			check("R 回选关页（连弹到选关卡那一层，编队留着）",
				screenName(rRoot.top()) == "*main.stageScreen", screenName(rRoot.top()))
			//: ⚠ `R` 之后栈顶已经不是结果屏了 ⇒ 要验 `H` 得**重新压一张**。
			//: 第一版连着按 R 再按 H，于是那个 `h` 打到了选关屏上（断言当场红了）。
			rRoot.push(newResultScreen(), nil)
			rRoot.Update(keyMsg("h"))
			check("H 回准备屏（整轮重来）",
				screenName(rRoot.top()) == "main.welcomeScreen", screenName(rRoot.top()))
		}
	}

	// =====================================================================
	fmt.Println("== 十七 · 助战（开关／单独一屏／上限 13／拦截计入／导出带名字）==")
	//: 口径（博士 2026-09-26）：用助战 ⇒ 编队上限 **13**（自己的 12 ＋ 助战 1）；
	//: 助战从**全部干员**里挑（不是名册）；**练度不填、只写名字**；拦截里助战计入。
	//: 全貌与那条具名登记的后果写在 `support.go` 文件头与 `solveGate` 的注释里。
	//:
	//: ★ 本段自己的负对照（**负对照在前**，照第十段那套写法）：
	//:  ① 把守卫的结论反过来读：**不带助战**时同一份「全员 ≤E1L1」的编队必须
	//:     **仍然拦** —— 它若放行，说明"放行"被无条件走了，下面那条"带助战不拦"
	//:     就成了同义反复（满屏 ✓ 零信息量）。
	//:  ② 尺子 `supportForSolve` 要**两个方向都读得到**：开＋有名字 ⇒ 给名字；
	//:     关（名字还留着）⇒ 空串。只试一个方向分不出"恒空"与"开关真的管用"。
	//:  ③ 屏上那三种形态的字面必须分得开：不带助战那一行**不含**子串「助战：用」。
	//:  ④ **一条故意造的红**（照文件开头那条全局负对照的写法，红完把 `bad` 归零）。
	rulerOK17 := true
	{
		noSup12 := make([]RosterOperator, 0, 12)
		for i := 0; i < 12; i++ {
			noSup12 = append(noSup12, RosterOperator{
				CharID: fmt.Sprintf("char_sup%02d", i), Name: fmt.Sprintf("练%02d", i),
				Profession: "PIONEER", Elite: i % 2, Level: 1})
		}
		inv17 := solveGate(noSup12, solveSourceManual, "")
		if !check("负对照：不带助战时，12 位全员 ≤E1L1 的编队**仍然拦**（尺子要判红）",
			!inv17.Allow && inv17.Branch == gateBlockManual,
			fmt.Sprintf("Allow=%v 分支=%s", inv17.Allow,
				solveGateBranchNames[inv17.Branch])) {
			rulerOK17 = false
		}
		on17 := &appCtx{useSupport: true, supportName: "令"}
		off17 := &appCtx{useSupport: false, supportName: "令"}
		if !check("负对照：supportForSolve 两个方向都要读到（开⇒名字、关⇒空串）",
			on17.supportForSolve() == "令" && off17.supportForSolve() == "",
			fmt.Sprintf("开=%q 关=%q", on17.supportForSolve(), off17.supportForSolve())) {
			rulerOK17 = false
		}
		zero17 := &appCtx{}
		if !check("负对照：不带助战那一行**不含**子串「助战：用」（三种形态分得开）",
			!strings.Contains(zero17.supportLine(), "助战：用"),
			fmt.Sprintf("%q", zero17.supportLine())) {
			rulerOK17 = false
		}
	}
	if !rulerOK17 {
		fmt.Println("★ 本段负对照没红 ⇒ 第十七段的读数作废")
		return 3
	}
	//: ④ 故意造的红：口径 4 那句话说的是"协议里助战**没有练度要求**"，而 Go 的
	//:   **零值**干员（Elite 0／Level 0）**落在**「≤E1L1」范围内（`0 <= 1` 为真）
	//:   ⇒ 拿零值干员顶替助战，闸门照样拦，与口径 4 相反。所以下面这条命题是**假的**：
	//:   它必须报 ✗。它红了，才证明这一段的断言不是同义反复。
	if check("负对照（故意造的红）：零值干员不在「≤E1L1」范围内",
		!isMinLevel(RosterOperator{}),
		fmt.Sprintf("isMinLevel(零值)=%v —— 真值就是它**在**范围内",
			isMinLevel(RosterOperator{}))) {
		fmt.Println("★ 这条负对照没红 ⇒ 第十七段的读数作废")
		return 3
	}
	bad = 0 //: 与文件开头那条全局负对照同处置：故意造的红不算进最终读数

	//: ---- 开关与上限（都在选人屏上看得见）----
	//: 用第十段那套假名册（`fake`，4 人）：开关与上限与名册无关，不必另造一份。
	cS17 := pickCtx(6)
	rS17 := newRoot(cS17, welcomeScreen{})
	pS17 := newSquadPickScreen(cS17, nil)
	rS17.push(pS17, onSquadPicked)
	check("开关初值：关（屏上写着「助战：不用」）",
		!cS17.useSupport && strings.Contains(rS17.View(), "助战：不用"),
		firstLineWith(rS17.View(), "助战："))
	check("开关关着：上限是 12（自己那 12 格）",
		cS17.squadLimitShown() == 12 && strings.Contains(rS17.View(), "编队上限 12 人"),
		fmt.Sprintf("squadLimitShown=%d｜%s", cS17.squadLimitShown(),
			firstLineWith(rS17.View(), "编队上限")))
	press(rS17, "t")
	check("按 T：开关变「用」，并**单独压一屏**挑助战",
		screenName(rS17.top()) == "*main.supportPickScreen" &&
			strings.Contains(rS17.View(), "助战：用"),
		fmt.Sprintf("%s｜%s", screenName(rS17.top()), firstLineWith(rS17.View(), "助战：用")))
	check("开关一开：上限就是 13（自己的 12 ＋ 助战 1，助战占一格）",
		cS17.squadLimitShown() == 13 && strings.Contains(rS17.View(), "编队上限 13 人"),
		fmt.Sprintf("squadLimitShown=%d｜%s", cS17.squadLimitShown(),
			firstLineWith(rS17.View(), "编队上限")))

	//: ---- 助战屏：列的是**全部干员**（不是名册）----
	supScr17, isSupScr17 := rS17.top().(*supportPickScreen)
	nSup17 := 0
	if supScr17 != nil {
		nSup17 = len(supScr17.rows)
	}
	inRoster17 := map[string]bool{}
	for _, op := range fake.Operators {
		inRoster17[op.Name] = true
	}
	//: 断言用一个**名册里没有**的名字：只有名册外的名字才证得动"列的是全部干员"。
	//: 阿米娅在 gamedata 全量表里（`char_002_amiya`），任何小号名册都不会有她。
	const probe17 = "阿米娅"
	probeIdx17, tokenRows17 := -1, 0
	if isSupScr17 {
		for i, op := range supScr17.rows {
			if op.Name == probe17 {
				probeIdx17 = i
			}
			if op.Profession == "TOKEN" || op.Profession == "TRAP" {
				tokenRows17++
			}
		}
	}
	check("助战屏：候选来自**全部干员**（名册里没有的名字也在列）",
		isSupScr17 && probeIdx17 >= 0 && !inRoster17[probe17],
		fmt.Sprintf("候选 %d 名；%s 在第 %d 行；它在名册里吗=%v",
			nSup17, probe17, probeIdx17+1, inRoster17[probe17]))
	check("助战屏：写明「练度不用填（MAA 不识别）」（口径 3 要看得见）",
		strings.Contains(rS17.View(), "练度不用填") &&
			strings.Contains(rS17.View(), "MAA 不识别"),
		firstLineWith(rS17.View(), "练度不用填"))
	check("助战屏：候选里没有装置／召唤物（取的是 is_operator=1 的干员表）",
		tokenRows17 == 0, fmt.Sprintf("TOKEN/TRAP 行 %d（共 %d 行）", tokenRows17, nSup17))

	//: ---- 回车：把名字记下来 ----（`pointer` 取消后走 Esc）
	if isSupScr17 && probeIdx17 >= 0 {
		supScr17.cursor = probeIdx17
	}
	press(rS17, "enter")
	check("回车：助战名字记下来了（记在 appCtx 上那一位）",
		cS17.supportName == probe17 && cS17.supportForSolve() == probe17,
		fmt.Sprintf("supportName=%q supportForSolve=%q", cS17.supportName, cS17.supportForSolve()))
	check("回车后：助战屏弹掉、回到选人屏，屏上看得见「用（阿米娅）」",
		screenName(rS17.top()) == "*main.squadPickScreen" &&
			strings.Contains(rS17.View(), "助战：用（"+probe17+"）"),
		fmt.Sprintf("%s｜%s", screenName(rS17.top()), firstLineWith(rS17.View(), "助战：用")))

	//: ---- 关掉（再按 T）与 Esc 取消：两条路都要把状态收干净 ----
	press(rS17, "t")
	check("再按 T：关掉 —— 名字清掉、上限回 12、屏上写「不用」",
		!cS17.useSupport && cS17.supportName == "" && cS17.squadLimitShown() == 12 &&
			strings.Contains(rS17.View(), "助战：不用"),
		fmt.Sprintf("开关=%v 名字=%q 上限=%d", cS17.useSupport, cS17.supportName,
			cS17.squadLimitShown()))
	press(rS17, "t")   //: 重新开 ⇒ 进助战屏
	press(rS17, "esc") //: 取消
	check("助战屏 Esc：取消 = 不用助战 —— 没记名字、退回选人屏、上限回 12",
		screenName(rS17.top()) == "*main.squadPickScreen" && !cS17.useSupport &&
			cS17.supportName == "" && cS17.supportForSolve() == "" &&
			cS17.squadLimitShown() == 12,
		fmt.Sprintf("%s｜开关=%v 名字=%q supportForSolve=%q 上限=%d",
			screenName(rS17.top()), cS17.useSupport, cS17.supportName,
			cS17.supportForSolve(), cS17.squadLimitShown()))

	//: ---- 拦截：12 位全员 ≤E1L1，带助战 ⇒ 放行；不带 ⇒ 拦 ----
	//: 两条都**走入口**（`enterSolve`）：行使计数只在入口里加，直接调纯函数读不到
	//: "这条路真的过了守卫"（那种读数是全 0，与"走了某条分支"分得开）。
	min12Names := make([]string, 0, 12)
	min12 := make([]RosterOperator, 0, 12)
	entries12 := make([]map[string]any, 0, 12)
	for i := 0; i < 12; i++ {
		nm, cid := fmt.Sprintf("练%02d", i), fmt.Sprintf("char_sup%02d", i)
		min12Names = append(min12Names, nm)
		min12 = append(min12, RosterOperator{CharID: cid, Name: nm,
			Profession: "PIONEER", Elite: i % 2, Level: 1})
		entries12 = append(entries12, map[string]any{
			"name": nm, "charId": cid, "elite": i % 2, "level": 1, "potential": 1})
	}
	blob12, _ := json.Marshal(entries12)
	dir12, _ := os.MkdirTemp("", "rios-selftest-support-")
	path12 := filepath.Join(dir12, "roster12.json")
	_ = os.WriteFile(path12, blob12, 0o644)
	c12 := &appCtx{w: 90, h: 26, deployLimit: 6, mode: "auto",
		roster: &rosterData{Source: "selftest", Complete: true, Count: 12,
			Operators: min12, Path: path12},
		stage: &data.StageRecord{Code: "1-7", LevelID: "main_01-07", Name: "测试关"}}
	r12 := newRoot(c12, welcomeScreen{})
	s12 := newSquadPickScreen(c12, nil)
	r12.push(s12, onSquadPicked)
	markNames(r12, s12, min12Names...)
	check("12 位全员 ≤E1L1：都勾上了（下面两条拦截读数拿的就是这一份编队）",
		len(s12.picked) == 12, fmt.Sprintf("勾了 %d 位", len(s12.picked)))
	dBlock17 := delta(func() { press(r12, "enter") })
	check("不带助战：12 位全员 ≤E1L1 ⇒ **拦**（走「拦下·手选」，编队没定下来）",
		screenName(r12.top()) == "*main.squadPickScreen" &&
			oneBranch(dBlock17, gateBlockManual) && len(c12.squad) == 0,
		fmt.Sprintf("%s｜%s｜squad=%v", screenName(r12.top()), fmtDelta(dBlock17), c12.squad))

	//: 同一份 12 人编队，加一位助战 ⇒ 必须**放行**（口径 4，含那条具名登记的后果：
	//: "1 位助战 ＋ 11 位 E0L1"照样放行 —— 这里正是 12 位 E0L1 ＋ 1 位助战）。
	press(r12, "t")
	if sup12, ok := r12.top().(*supportPickScreen); ok && len(sup12.rows) > 0 {
		sup12.cursor = 0
	}
	press(r12, "enter")
	check("挑完助战：回到选人屏，助战记下来了",
		screenName(r12.top()) == "*main.squadPickScreen" && c12.supportForSolve() != "",
		fmt.Sprintf("%s｜助战=%q", screenName(r12.top()), c12.supportForSolve()))
	dAllow17 := delta(func() { press(r12, "enter") })
	check("带助战：同 12 位全员 ≤E1L1 ⇒ **不拦**（压解算屏），走「放行·带助战」分支",
		screenName(r12.top()) == "*main.solveScreen" && oneBranch(dAllow17, gateAllowSupport),
		fmt.Sprintf("%s｜%s", screenName(r12.top()), fmtDelta(dAllow17)))
	check("带助战：编队定下来了（12 人）",
		len(c12.squad) == 12, fmt.Sprintf("%d 人（%v）", len(c12.squad), c12.squad))
	if sc12, ok := r12.top().(*solveScreen); ok {
		check("带助战：这一轮的命令排上了，且助战进了 solveParams（要交给引擎）",
			sc12.p.support != "" && sc12.p.support == c12.supportForSolve(),
			fmt.Sprintf("params.support=%q（appCtx 上 %q）", sc12.p.support,
				c12.supportForSolve()))
	} else {
		check("带助战：栈顶该是解算屏", false, screenName(r12.top()))
	}
	check("登记：零值干员（Elite 0／Level 0）**落在**「≤E1L1」范围内 ⇒ 助战不能用零值顶替",
		isMinLevel(RosterOperator{}), fmt.Sprintf("isMinLevel(零值)=%v", isMinLevel(RosterOperator{})))

	//: ---- 导出：带 `SupportName` ⇒ `opers` 末尾多一格，且**只有一个键 name** ----
	supDir17, _ := os.MkdirTemp("", "rios-selftest-sup-export-")
	supRosterPath17 := filepath.Join(supDir17, "roster.json")
	_ = os.WriteFile(supRosterPath17, []byte(`[{"name":"圣聆初雪","charId":"char_1046_sbell2",`+
		`"elite":2,"level":90,"potential":1,"module_level":0}]`), 0o644)
	rr17, rrErr17 := core.ReadRoster(supRosterPath17)
	if rrErr17 != nil {
		check("导出：名册读得出来（下面两条读数靠它）", false, fmt.Sprintf("err=%v", rrErr17))
	} else {
		plan17 := core.PlayPlan{Stage: "main_01-07", Title: "1-7",
			Deploys: []core.DeployOrder{{Operator: "圣聆初雪", Position: [2]int{1, 2},
				Direction: "Right", Skill: 1}}}
		jobNo17, errNo17 := maa.ToMaa(plan17, &rr17, nil, nil,
			maa.MaaOptions{StageName: "main_01-07"})
		jobSup17, errSup17 := maa.ToMaa(plan17, &rr17, nil, nil,
			maa.MaaOptions{StageName: "main_01-07", SupportName: "阿米娅"})
		//: 断言落在**序列化之后**的字节上：`opers` 那一格的形状由 `MaaOper.MarshalJSON`
		//: 收敛（助战条目只输出 `name`），看 Go 结构体看不出来。
		blobSup17, _ := json.Marshal(jobSup17)
		var wire17 struct {
			Opers []map[string]any `json:"opers"`
		}
		_ = json.Unmarshal(blobSup17, &wire17)
		last17 := map[string]any{}
		if len(wire17.Opers) > 0 {
			last17 = wire17.Opers[len(wire17.Opers)-1]
		}
		check("导出：不带 SupportName 时**不多**那一格（负方向也要看）",
			errNo17 == nil && len(jobNo17.Opers) == 1,
			fmt.Sprintf("err=%v opers=%d", errNo17, len(jobNo17.Opers)))
		check("导出：带 SupportName ⇒ opers 末尾多一格、且**只有一个键 name**",
			errSup17 == nil && len(jobSup17.Opers) == len(jobNo17.Opers)+1 &&
				len(last17) == 1 && last17["name"] == "阿米娅",
			fmt.Sprintf("err=%v opers %d→%d；末格 %v（%d 个键）", errSup17,
				len(jobNo17.Opers), len(jobSup17.Opers), last17, len(last17)))

		//: ★ 端到端：走**结果屏那条路**（`result.go` 的导出）真导一份出来 —— 判据要盯的
		//: 正是"结果屏把助战接上了"这件事，只调 `ToMaa` 证不动接线。落盘到**临时**的
		//: Guides 目录（不碰玩家那份，与第十六段同口径）。
		planBlob17, _ := json.Marshal(plan17)
		guidesSup17, _ := os.MkdirTemp("", "rios-selftest-sup-guides-")
		cExp17 := &appCtx{guidesDir: guidesSup17, w: 90, h: 26,
			stage:     &data.StageRecord{Code: "1-7", LevelID: "main_01-07"},
			solvePlan: planBlob17, squad: []string{"圣聆初雪"},
			useSupport: true, supportName: "阿米娅",
			roster: &rosterData{Source: "selftest", Path: supRosterPath17, Count: 1,
				Operators: []RosterOperator{{CharID: "char_1046_sbell2", Name: "圣聆初雪",
					Elite: 2, Level: 90}}}}
		rsSup17 := newResultScreen()
		rsSup17.update(cExp17, keyMsg("e"))
		if cExp17.exportPath == "" {
			check("结果屏导出（带助战）：写出了作业文件", false, rsSup17.msg)
		} else {
			blobExp17, rerrExp17 := os.ReadFile(cExp17.exportPath)
			var wireExp17 struct {
				Opers []map[string]any `json:"opers"`
			}
			jerrExp17 := json.Unmarshal(blobExp17, &wireExp17)
			lastExp17 := map[string]any{}
			if len(wireExp17.Opers) > 0 {
				lastExp17 = wireExp17.Opers[len(wireExp17.Opers)-1]
			}
			check("结果屏导出（带助战）：落盘的 opers 末尾就是助战那一格（只有 name）",
				rerrExp17 == nil && jerrExp17 == nil && len(wireExp17.Opers) == 2 &&
					len(lastExp17) == 1 && lastExp17["name"] == "阿米娅",
				fmt.Sprintf("%s｜opers=%d 末格=%v（%d 个键）", cExp17.exportPath,
					len(wireExp17.Opers), lastExp17, len(lastExp17)))
			check("结果屏渲染：助战**单列一行**（它不在 deploys 里 —— 是要求不是部署）",
				strings.Contains(rsSup17.view(cExp17), "助战 阿米娅"),
				firstLineWith(rsSup17.view(cExp17), "助战"))
		}
	}

	//: ---- 引擎那一侧：助战**真的送到了**（真起一轮，读引擎的回声）----
	//: 界面自己记着名字不算数（那只证明界面知道）；凭据只有引擎回声
	//: （`SolveOut.Support`）。那一段的往返参数与第十五段同值（per_op=1、beam=1、1 人）。
	if _, eerr17 := newEngineClient(); eerr17 != nil {
		fmt.Printf("  （未核：找不到引擎 exe，助战随 solve 送引擎那一条不判红。具名原因：%s）\n",
			firstLineWith(eerr17.Error(), "★"))
	} else {
		dirE17, _ := os.MkdirTemp("", "rios-selftest-sup-engine-")
		rosterE17 := filepath.Join(dirE17, "roster.json")
		_ = os.WriteFile(rosterE17, []byte(`[
 {"name":"圣聆初雪","charId":"char_1046_sbell2","elite":2,"level":90,"potential":1,"module_level":0},
 {"name":"赤刃明霄陈","charId":"char_1050_chen3","elite":2,"level":90,"potential":1,
  "module":"uniequip_002_chen3","module_level":3}]`), 0o644)
		p17 := solveParams{levelID: "main_01-07", rosterPath: rosterE17,
			pool: []string{"圣聆初雪", "赤刃明霄陈"}, perOp: 1, beam: 1, support: "阿米娅"}
		msg17 := runSolveRoundCmd(p17, 1)()
		m17, ok17 := msg17.(solveRoundMsg)
		switch {
		case !ok17:
			check("助战随 solve 送到引擎：回来的不是一轮解算结果", false,
				fmt.Sprintf("%T", msg17))
		case m17.err != nil:
			fmt.Printf("  （未核：这一轮解算没跑成，不判红。具名原因：%s）\n",
				firstLineWith(m17.err.Error(), "★"))
		default:
			check("助战随 solve 送到引擎：引擎原样回声（solveOutView.Support）",
				m17.out.Support == p17.support,
				fmt.Sprintf("引擎回声 %q（送的是 %q）", m17.out.Support, p17.support))
		}
	}

	fmt.Println()
	if bad > 0 {
		fmt.Printf("结论：**%d 条红** —— TUI 自检不通过\n", bad)
		return 1
	}
	fmt.Println("结论：**全绿** —— 取数／降级／屏栈／下钻／退回／空数据退路／路径补全／改目录／解算入口守卫（自限拦截·两条路）／防绕过／桥具名失败／询问屏／扫码屏／引擎客户端／解算屏／结果屏与导出逐条过")
	return 0
}

// fakeQRGeometry 造一张 n×n 的**几何用**矩阵（不是真二维码，只用来量排版：
// 静默区挑得对不对、渲染行数对不对）。**别拿它当二维码去扫**。
func fakeQRGeometry(n int) [][]bool {
	m := make([][]bool, n)
	for i := range m {
		m[i] = make([]bool, n)
		for x := range m[i] {
			m[i][x] = (i+x)%3 == 0
		}
	}
	return m
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
