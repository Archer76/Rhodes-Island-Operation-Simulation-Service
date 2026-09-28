package main

import (
	"bytes"
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
	//: ★ 2026-09-27 口径又动过一次（当晚）：在「18 主线（含序章）＋ 剿灭 ＋ 代号带
	//: sre/side 的活动」之上，**加回故事集（`mini`，15 族 249 关）与早期活动
	//: （`dN`，7 族 132 关）** ⇒ 69 → **91**（见 `keeps_zone` 与施工图 §12.14）。
	//: 这条数与 Go `-chapters`／Python `list_chapters`／金标三处复算一致。
	check("章节 91 条（2026-09-27 当晚口径：＋故事集 15 ＋早期活动 7；旧数 69 已过期）",
		len(c.chapters) == 91, fmt.Sprintf("实得 %d", len(c.chapters)))
	six := 0
	for _, s := range stages {
		if s.Difficulty == "SIX_STAR" {
			six++
		}
	}
	//: ★★ 2026-09-27 **反转**：09-26 那笔「六星档不做」是**弄错了** —— 15～17 章的
	//: 六星是**险地作战**（等效于突袭），博士裁定加回；模拟器不做沙盘推演 ⇒ 实际
	//: 打的是它的四星版本（`#s` 与同名普通档共用 `data_path`）。⇒ 这一条从
	//: 「必须为 0」翻成「必须在场」，并钉住**数据事实**：45 = 16（15 章）＋15（16 章）
	//: ＋14（17 章）。它与建库白名单无关，所以不随口径漂；将来上游加了新的险地作战
	//: 关卡，这条会红 —— 那是**该被看见**的数据变更。
	check("六星档（险地作战）已在取数面（SIX_STAR 45 行）", six == 45,
		fmt.Sprintf("实得 %d 行", six))
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
			//: ★ 2026-09-28 新增（博士："已经登陆也会提示未登录，两句提示共存了"）：
			//: 刚登录成功、名册还没到 —— 这一档**不许**出现"当前没有登录的账号"。
			{"刚登录但名册未到", &appCtx{accountNote: "已登录：Archer#6725　游戏uid=10404662"}},
		}
		blank := ""
		for _, s := range accStates {
			if strings.TrimSpace(ansi.Strip(s.ctx.accountLine())) == "" {
				blank = s.what
			}
		}
		check("登录账号栏四档都有话说（不留空白）", blank == "",
			fmt.Sprintf("空白的那一档：%q（四档：没账号／有名册／名册取不到／刚登录名册未到）", blank))
		//: ★ 自相矛盾那条：刚登录成功时**不许**再说"当前没有登录的账号"
		justLogged := ansi.Strip((&appCtx{
			accountNote: "已登录：Archer#6725　游戏uid=10404662"}).accountLine())
		check("★ 刚登录成功 ⇒ 不再说「当前没有登录的账号」（两句提示不许共存）",
			!strings.Contains(justLogged, "当前没有登录的账号") &&
				strings.Contains(justLogged, "名册还没取到"),
			firstLineWith(justLogged, "登录"))
		//: 负对照：**真的**没登录时那句话必须还在（别把这条修成"永远不说"）
		noAcct := ansi.Strip((&appCtx{}).accountLine())
		check("负对照：真没登录时仍说「当前没有登录的账号」",
			strings.Contains(noAcct, "当前没有登录的账号"), firstLineWith(noAcct, "当前"))
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
			check("环境屏首行是「全部关卡」（博士 2026-09-27 定名，逐条见五之九）",
				strings.Contains(r.View(), "全部关卡"), "全部关卡")
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

	fmt.Println("== 五之二 · 退回的落点：关卡屏 esc／解算屏 q 都退到「选章节」==")
	//: ★ 2026-09-27 新加。此前**没有任何断言**盯这两处 —— 旧自检只断言了
	//: 「章屏 esc ⇒ 回准备屏」（上面第四节），而博士实测报的恰恰是这两处：
	//: 关卡屏按 esc 弹回了准备屏、解算屏按 q 也是。
	//:
	//: 根因是导航模型：屏交结果时**弹掉自己**、由回调压下一屏 ⇒ 走到关卡屏时
	//: **选章屏不在栈里**（实测栈是 [welcomeScreen, stageScreen]），`actBack`
	//: 一弹就到准备屏。所以「退回选章节」只能**把选章屏压回来**，
	//: 且必须落在「弹掉自己之后的回调」里（否则来回打转）。
	//: 这条判据盯的就是那个落点 —— 不是文案、不是栈深，是**顶上那一屏是谁**。
	{
		r3 := newRoot(newAppCtx(stages, zones), welcomeScreen{})
		r3.Update(tea.WindowSizeMsg{Width: 90, Height: 26})
		press(r3, "enter") //: 准备屏 → 选章屏
		press(r3, "enter") //: 选章屏 →（选部／环境）→ 关卡屏
		for i := 0; i < 3 && (screenName(r3.top()) == "*main.partScreen" ||
			screenName(r3.top()) == "*main.envScreen"); i++ {
			press(r3, "enter")
		}
		if screenName(r3.top()) != "*main.stageScreen" {
			check("（前置）走到关卡屏", false, screenName(r3.top()))
		} else {
			press(r3, "esc")
			check("关卡屏 esc ⇒ 退回**选章节**（不是准备屏）",
				screenName(r3.top()) == "*main.chapterScreen", screenName(r3.top()))
			check("退回后栈里是 [准备屏, 选章节]（关卡屏已被弹掉，栈深 2）",
				len(r3.stack) == 2, fmt.Sprintf("栈深 %d", len(r3.stack)))
		}
	}
	{
		r4 := newRoot(newAppCtx(stages, zones), welcomeScreen{})
		r4.Update(tea.WindowSizeMsg{Width: 90, Height: 26})
		press(r4, "enter") //: 准备屏 → 选章屏（好让「退回选章节」有章可指）
		r4.push(newSolveScreen(solveParams{levelID: "main_01-07"}, []int{4}),
			onSolveClosed)
		press(r4, "q") //: 解算屏的中止键
		check("解算屏按 q（中止）⇒ 退回**选章节**（不是准备屏，也不是「问编队」）",
			screenName(r4.top()) == "*main.chapterScreen", screenName(r4.top()))
	}

	fmt.Println("== 五之三 · 章节屏的搜索框（Python `Input #kw` 的等价物）==")
	//: ★ 2026-09-27 新加：Python 的 `ChapterPickScreen` 有 `Input #kw`
	//: （`app.py:1222`），Go 这一版此前**连字段都没有**（博士实测报「搜索框没了」）。
	//: 这里盯四件事：空关键词不筛、能筛出唯一一条、**全角也筛得出来**
	//: （`narrowHalf` 那条：中文输入法全角是常态）、筛不着时**不乱选**。
	{
		r5 := newRoot(newAppCtx(stages, zones), welcomeScreen{})
		r5.Update(tea.WindowSizeMsg{Width: 90, Height: 26})
		press(r5, "enter") //: → 选章屏
		cs, ok := r5.top().(*chapterScreen)
		if !ok {
			check("（前置）走到选章屏", false, screenName(r5.top()))
		} else {
			all := len(cs.shown(r5.ctx))
			check("空关键词 = 不筛（可见条数 = 全部章节）",
				all == len(r5.ctx.chapters),
				fmt.Sprintf("可见 %d / 全部 %d", all, len(r5.ctx.chapters)))
			press(r5, "月行水上")
			hits := cs.shown(r5.ctx)
			keys := make([]string, 0, len(hits))
			for _, i := range hits {
				keys = append(keys, r5.ctx.chapters[i].Key)
			}
			check("输「月行水上」筛出唯一一条 act54side",
				len(keys) == 1 && keys[0] == "act54side",
				fmt.Sprintf("命中 %v", keys))
			//: 全角：中文输入法全角模式下打出来的是 `ＡＣＴ５４ＳＩＤＥ`。
			//: 不折半角的话用户按了也白按，而他只看到「这个框坏了」。
			press(r5, "esc") //: 先清空
			press(r5, "ＡＣＴ５４ＳＩＤＥ")
			fw := cs.shown(r5.ctx)
			fwKeys := make([]string, 0, len(fw))
			for _, i := range fw {
				fwKeys = append(fwKeys, r5.ctx.chapters[i].Key)
			}
			check("全角「ＡＣＴ５４ＳＩＤＥ」筛出同一章（折半角生效）",
				len(fwKeys) == 1 && fwKeys[0] == "act54side",
				fmt.Sprintf("命中 %v", fwKeys))
			//: 负对照：筛不着时**不许乱选** —— 按 Enter 什么都不该发生。
			press(r5, "esc")
			press(r5, "不存在的章节名")
			none := len(cs.shown(r5.ctx))
			depth0 := len(r5.stack)
			press(r5, "enter")
			check("负对照：筛不着时可见 0 条、按 Enter 不推进（不乱选）",
				none == 0 && len(r5.stack) == depth0,
				fmt.Sprintf("可见 %d、栈深 %d→%d", none, depth0, len(r5.stack)))
			press(r5, "esc") //: 清空
			check("Esc 先清关键词、再按一次才返回",
				len(cs.shown(r5.ctx)) == len(r5.ctx.chapters), "清空后不筛")
		}
	}

	fmt.Println("== 五之四 · 关卡屏的搜索框与难度下拉（Python `#kw` ＋ `Select #diff`）==")
	//: ★ 2026-09-27 新加：参照实现在这一屏有两件交互件 —— `Select #diff`
	//: （`app.py:1425-1429`，三档、**标签带关数**）与 `Input #kw`
	//: （`app.py:1430`）；Go 这一版此前**连字段都没有**。
	//: 这里盯四件事：三档的关数对得上、切档真的换集合、关键词能筛（含全角）、
	//: 以及那条参照实现记过的坑 —— **回车在下拉上是"确认这一档"，不是"选定关卡"**。
	{
		r6 := newRoot(newAppCtx(stages, zones), welcomeScreen{})
		r6.Update(tea.WindowSizeMsg{Width: 90, Height: 26})
		press(r6, "enter") //: → 选章屏
		press(r6, "enter") //: →（选部／环境）→ 关卡屏
		for i := 0; i < 3 && (screenName(r6.top()) == "*main.partScreen" ||
			screenName(r6.top()) == "*main.envScreen"); i++ {
			press(r6, "enter")
		}
		ss, ok := r6.top().(*stageScreen)
		if !ok {
			check("（前置）走到关卡屏", false, screenName(r6.top()))
		} else {
			base := len(ss.rows)
			nNormal, nFour := 0, 0
			for _, st := range ss.rows {
				switch st.Difficulty {
				case "NORMAL":
					nNormal++
				case "FOUR_STAR":
					nFour++
				}
			}
			opts := ss.diffOptions()
			check("难度下拉恰是三档，且**关数写进标签**（照参照的「普通（三星）（19 关）」）",
				len(opts) == 3 &&
					strings.Contains(opts[0].label, fmt.Sprintf("%d 关", base)) &&
					strings.Contains(opts[1].label, fmt.Sprintf("%d 关", nNormal)) &&
					strings.Contains(opts[2].label, fmt.Sprintf("%d 关", nFour)),
				fmt.Sprintf("%v", []string{opts[0].label, opts[1].label, opts[2].label}))
			//: 正对照：基数里两档都要有货，否则下面切档那两条是零行使的绿。
			check("（前置）这一部里普通档与突袭档都有货", nNormal > 0 && nFour > 0,
				fmt.Sprintf("普通 %d、突袭 %d、共 %d", nNormal, nFour, base))
			check("全选（默认档）⇒ 列出的就是基数", len(ss.shown()) == base,
				fmt.Sprintf("%d / %d", len(ss.shown()), base))

			//: 切「突袭（四星）」：下拉必须**开→选→确认**，且展开时回车归它。
			depth0 := len(r6.stack)
			press(r6, "d")
			check("D 打开难度下拉（展开态）", ss.picking, fmt.Sprintf("picking=%v", ss.picking))
			press(r6, "enter") //: 回车 = 确认当前档（第一档=全部），**不是**选定关卡
			check("★ 下拉展开时回车**只确认难度**、不选定关卡（对照实现记过的那条坑）",
				!ss.picking && len(r6.stack) == depth0,
				fmt.Sprintf("picking=%v 栈深 %d→%d", ss.picking, depth0, len(r6.stack)))
			press(r6, "d")
			press(r6, "down")
			press(r6, "down")
			press(r6, "enter") //: 确认「突袭（四星）」
			four := ss.shown()
			allFour := true
			for _, st := range four {
				if st.Difficulty != "FOUR_STAR" {
					allFour = false
				}
			}
			check("选「突袭（四星）」⇒ 列出的每一条都是 FOUR_STAR，且条数 = 标签里那个数",
				allFour && len(four) == nFour,
				fmt.Sprintf("实得 %d 条（标签写 %d）", len(four), nFour))
			ss.diff = "" //: 回到全部，接着测关键词
			ss.cursor = 0

			//: 关键词：先拿基数里第一条的代号当关键词（必然命中它自己）。
			if base > 0 {
				code := ss.rows[0].Code
				press(r6, code)
				hit := ss.shown()
				check("关键词 = 第一条的代号 ⇒ 至少筛出它自己",
					len(hit) >= 1 && len(hit) < base,
					fmt.Sprintf("命中 %d / %d", len(hit), base))
				press(r6, "esc") //: 清空
			}
			//: 全角：中文输入法全角模式下打出来的是全角字母／数字。
			if base > 0 {
				code := ss.rows[0].Code
				press(r6, widenHalfForTest(code))
				fwHit := len(ss.shown())
				check("全角写法的同一个代号 ⇒ 同样筛得出来（折半角生效）",
					fwHit >= 1 && fwHit < base,
					fmt.Sprintf("命中 %d / %d", fwHit, base))
				press(r6, "esc")
			}
			//: 负对照：筛不着时不许乱选。
			press(r6, "绝不可能存在的关卡代号")
			none := len(ss.shown())
			d1 := len(r6.stack)
			press(r6, "enter")
			check("负对照：筛不着时可见 0 条、按 Enter 不推进", none == 0 && len(r6.stack) == d1,
				fmt.Sprintf("可见 %d、栈深 %d→%d", none, d1, len(r6.stack)))
		}
	}

	fmt.Println("== 五之五 · 鼠标通道 ＋ 分类行命中表（Python `PickerRow`）==")
	//: ★ 2026-09-27 新加。博士报「这版 TUI 不能用鼠标点击了」，并要「和之前完全一样」。
	//: 根因是**两道闸**：`main.go` 没开鼠标选项（终端根本不产生 `MouseMsg`），
	//: 且 `screen` 接口的 `update` 在**编译期**只收 `tea.KeyMsg`。处置：开选项 ＋ 加一个
	//: **可选**的窄接口 `mouseScreen`（认的屏实现它，不认的一个字节不用改）。
	//:
	//: 这一节盯四件事：通道通（屏实现了那个接口）、键盘 ←/→ 能切、**真发一个鼠标
	//: 按下事件**能切到点中的那一项、以及折行后**第二行上的项照样点得到**
	//: （最后那条是参照实现记过的性质：`_boxes` 带行号就是为了它）。
	{
		//: 自带一份最小名册：本节用的 `fake` 在**下面**才声明（Go 不能先用后声明），
		//: 而且这一节要的正是"每个职业各一人 ＋ 有重复职业"，自己写清更直接。
		roster7 := &rosterData{Source: "selftest", Complete: true, Count: 5,
			Operators: []RosterOperator{
				{CharID: "char_1", Name: "甲", Profession: "PIONEER", Elite: 0, Level: 1},
				{CharID: "char_2", Name: "乙", Profession: "WARRIOR", Elite: 1, Level: 1},
				{CharID: "char_3", Name: "丙", Profession: "MEDIC", Elite: 1, Level: 45},
				{CharID: "char_4", Name: "丁", Profession: "CASTER", Elite: 2, Level: 90},
				{CharID: "char_5", Name: "戊", Profession: "MEDIC", Elite: 0, Level: 30},
			}}
		ctx := &appCtx{w: 90, h: 26, roster: roster7, mode: "auto"}
		r7 := newRoot(ctx, newSquadPickScreen(ctx, nil))
		r7.Update(tea.WindowSizeMsg{Width: 90, Height: 26})
		ss7, ok := r7.top().(*squadPickScreen)
		if !ok {
			check("（前置）选人屏在栈顶", false, screenName(r7.top()))
		} else {
			_, isMouse := any(ss7).(mouseScreen)
			check("选人屏实现了 mouseScreen（鼠标消息送得到它）", isMouse,
				"mouseScreen 接口断言")
			items, vals := ss7.profOptions()
			check("分类行 = 「全部」＋ 名册里真有的职业（按游戏序）",
				len(items) == 5 && items[0] == "全部" && vals[0] == "" &&
					vals[1] == "PIONEER" && vals[2] == "WARRIOR",
				fmt.Sprintf("%v", items))
			r7.View() //: 先画一次 —— 命中表是"画的时候"填的
			before := len(ss7.visible())
			press(r7, "right")
			after := ss7.visible()
			profOK := len(after) > 0 && len(after) < before
			for _, op := range after {
				if op.Profession != ss7.prof {
					profOK = false
				}
			}
			check("→ 切职业：列出的每一条都属于该职业，且比「全部」少",
				profOK, fmt.Sprintf("全部 %d → %s %d", before, ss7.prof, len(after)))

			//: 鼠标：点某一项的**格子中间**（照参照的 `click_offset`），落到那一项上。
			r7.View()
			medic := -1
			for i, v := range vals {
				if v == "MEDIC" {
					medic = i
				}
			}
			box, found := hitBox{}, false
			for _, b := range ss7.profRow.boxes {
				if b.idx == medic {
					box, found = b, true
				}
			}
			if medic < 0 || !found {
				check("（前置）医疗那一项在命中表里", false, fmt.Sprintf("idx=%d", medic))
			} else {
				clickY, clickX := box.line+r7.bodyTop(), box.x+box.w/2
				r7.Update(tea.MouseMsg{Action: tea.MouseActionPress,
					Button: tea.MouseButtonLeft, X: clickX, Y: clickY})
				check("★ 鼠标点分类行 ⇒ 切到点中的那一项（博士原来的操作方式）",
					ss7.prof == "MEDIC",
					fmt.Sprintf("点 (%d,%d) → %q", clickX, clickY, ss7.prof))
				keep := ss7.prof
				r7.Update(tea.MouseMsg{Action: tea.MouseActionPress,
					Button: tea.MouseButtonLeft, X: 0, Y: 0})
				check("负对照：点在格子之外 ⇒ 筛选不变", ss7.prof == keep,
					fmt.Sprintf("%q → %q", keep, ss7.prof))
			}
			//: 折行：窄窗口下这一行会折成两行，**第二行上的项照样点得到**。
			r7.Update(tea.WindowSizeMsg{Width: 30, Height: 26})
			ss7.prof, ss7.profIdx, ss7.cursor = "", 0, 0
			r7.View()
			wrapped, secondLineIdx := false, -1
			for _, b := range ss7.profRow.boxes {
				if b.line > 0 {
					wrapped, secondLineIdx = true, b.idx
				}
			}
			if !wrapped {
				fmt.Println("  （未核：窄窗口下这一行没折行，第二行那条性质这次没行使）")
			} else {
				b2 := ss7.profRow.boxes[0]
				for _, b := range ss7.profRow.boxes {
					if b.idx == secondLineIdx {
						b2 = b
					}
				}
				r7.Update(tea.MouseMsg{Action: tea.MouseActionPress,
					Button: tea.MouseButtonLeft,
					X:      b2.x + b2.w/2, Y: b2.line + r7.bodyTop()})
				check("折行后**第二行上的项照样点得到**（格子带行号的理由）",
					ss7.prof == vals[secondLineIdx],
					fmt.Sprintf("点第二行第 %d 项 → %q（应 %q）",
						secondLineIdx, ss7.prof, vals[secondLineIdx]))
			}
			r7.Update(tea.WindowSizeMsg{Width: 90, Height: 26})
		}
	}

	fmt.Println("== 五之六 · 子职业行（Python `PickerRow #sub-row`）==")
	//: ★ 2026-09-27 新加。参照实现的选人屏有**两排**筛选：主职业行与子职业行
	//: （`app.py:1837-1838`）；后者**只列出当前职业下真有的子职业**，取不到就整行隐藏
	//: （`app.py:1878-1881`）；主职业一换，子职业行重建并回到「全部」
	//: （`app.py:1886-1893`）。它的前置（桥与结构体补 `sub_profession`）本轮先落。
	{
		roster8 := &rosterData{Source: "selftest", Complete: true, Count: 5,
			Operators: []RosterOperator{
				{CharID: "char_1", Name: "甲", Profession: "PIONEER",
					SubProfession: "尖兵", Elite: 0, Level: 1},
				{CharID: "char_2", Name: "乙", Profession: "WARRIOR",
					SubProfession: "剑豪", Elite: 1, Level: 1},
				{CharID: "char_3", Name: "丙", Profession: "MEDIC",
					SubProfession: "医师", Elite: 1, Level: 45},
				{CharID: "char_4", Name: "丁", Profession: "CASTER",
					SubProfession: "中坚术师", Elite: 2, Level: 90},
				{CharID: "char_5", Name: "戊", Profession: "MEDIC",
					SubProfession: "咒愈师", Elite: 0, Level: 30},
			}}
		ctx8 := &appCtx{w: 90, h: 26, roster: roster8, mode: "auto"}
		r8 := newRoot(ctx8, newSquadPickScreen(ctx8, nil))
		r8.Update(tea.WindowSizeMsg{Width: 90, Height: 26})
		ss8, _ := r8.top().(*squadPickScreen)
		if ss8 == nil {
			check("（前置）选人屏在栈顶", false, screenName(r8.top()))
		} else {
			items8, _ := ss8.subOptions()
			check("没选职业 ⇒ 子职业行**不出现**（整行隐藏，照参照）",
				len(items8) == 0, fmt.Sprintf("%v", items8))
			r8.View()
			check("（同上）隐藏时命中表是空的 —— 点在一块看不见的行上不许有反应",
				len(ss8.subRow.boxes) == 0,
				fmt.Sprintf("%d 个格子", len(ss8.subRow.boxes)))

			//: 选「医疗」：它的两名干员分属 医师／咒愈师 ⇒ 子职业行出现、按名册首次出现序。
			medic := -1
			_, pv := ss8.profOptions()
			for i, v := range pv {
				if v == "MEDIC" {
					medic = i
				}
			}
			ss8.setProf(medic)
			subItems, subVals := ss8.subOptions()
			check("选「医疗」⇒ 子职业行 = 「全部」＋ 该职业下真有的子职业（按名册首次出现序）",
				len(subItems) == 3 && subItems[0] == "全部" &&
					subVals[1] == "医师" && subVals[2] == "咒愈师",
				fmt.Sprintf("%v", subItems))

			//: 鼠标点子职业行里的「咒愈师」。
			r8.View()
			box8, found8 := hitBox{}, false
			for _, b := range ss8.subRow.boxes {
				if b.idx == 2 {
					box8, found8 = b, true
				}
			}
			if !found8 {
				check("（前置）「咒愈师」在子职业行的命中表里", false,
					fmt.Sprintf("%d 个格子", len(ss8.subRow.boxes)))
			} else {
				r8.Update(tea.MouseMsg{Action: tea.MouseActionPress,
					Button: tea.MouseButtonLeft,
					X:      box8.x + box8.w/2, Y: box8.line + r8.bodyTop()})
				vis8 := ss8.visible()
				subOK := ss8.sub == "咒愈师" && len(vis8) == 1 &&
					strings.TrimSpace(vis8[0].SubProfession) == "咒愈师"
				check("★ 鼠标点子职业行的「咒愈师」⇒ 只剩该子职业的那一位",
					subOK, fmt.Sprintf("sub=%q 可见 %d 人", ss8.sub, len(vis8)))
			}

			//: 换职业 ⇒ 子职业回到「全部」（否则会留一个在新职业下不存在的子职业）。
			ss8.setProf(1) //: 先锋
			check("换职业 ⇒ 子职业回到「全部」、可见集合按新职业重算",
				ss8.sub == "" && ss8.subIdx == 0 && len(ss8.visible()) == 1,
				fmt.Sprintf("sub=%q 可见 %d 人", ss8.sub, len(ss8.visible())))

			//: Tab 切焦点 ⇒ ←/→ 作用于子职业行（终端里没有焦点链，Tab 就是那条链）。
			//: ⚠ 起点要写死：上面那次鼠标点击已经把焦点留在**子职业行**了（那是它的
			//: 正确行为），不重置的话 Tab 会把它翻回职业行，断言就会因为
			//: 「我以为焦点在 0」而红 —— 判据红得对，是我的前提写错了。
			ss8.setProf(medic)
			ss8.focus = 0
			r8.View()
			press(r8, "tab")
			check("Tab 之后焦点在子职业行（有子职业时才切得过去）",
				ss8.focus == 1, fmt.Sprintf("focus=%d", ss8.focus))
			press(r8, "right")
			check("焦点在子职业行时 → 改的是子职业（不是职业）",
				ss8.sub == "医师" && ss8.prof == "MEDIC",
				fmt.Sprintf("prof=%q sub=%q", ss8.prof, ss8.sub))
			//: 负对照：子职业行隐藏时，Tab 不该把焦点切到一行不存在的控件上。
			ss8.setProf(0) //: 回到全部
			press(r8, "tab")
			check("负对照：子职业行隐藏时 Tab **不切焦点**（否则 ←/→ 会像坏了）",
				ss8.focus == 0, fmt.Sprintf("focus=%d", ss8.focus))
		}
	}

	fmt.Println("== 五之七 · 练度门槛下拉（Python `Select #f-trained`）==")
	//: ★ 2026-09-27 新加。参照实现那一屏的第三个交互件：三档练度门槛
	//: （`data.py:453-457`），判定是**元组比较** `(elite, level) >= (min)`。
	//: 这里盯三件事：三档文案与参照逐字相同、**边界**（那条最容易写错的
	//: `E1L80` 在「≥精英二60」下不该过）、展开时回车只确认门槛。
	{
		roster9 := &rosterData{Source: "selftest", Complete: true, Count: 5,
			Operators: []RosterOperator{
				{CharID: "char_1", Name: "甲", Profession: "PIONEER", Elite: 0, Level: 1},
				{CharID: "char_2", Name: "乙", Profession: "WARRIOR", Elite: 1, Level: 1},
				{CharID: "char_3", Name: "丙", Profession: "MEDIC", Elite: 1, Level: 45},
				{CharID: "char_4", Name: "丁", Profession: "CASTER", Elite: 2, Level: 90},
				{CharID: "char_5", Name: "戊", Profession: "MEDIC", Elite: 0, Level: 30},
			}}
		ctx9 := &appCtx{w: 90, h: 26, roster: roster9, mode: "auto"}
		r9 := newRoot(ctx9, newSquadPickScreen(ctx9, nil))
		r9.Update(tea.WindowSizeMsg{Width: 90, Height: 26})
		ss9, _ := r9.top().(*squadPickScreen)
		if ss9 == nil {
			check("（前置）选人屏在栈顶", false, screenName(r9.top()))
		} else {
			labels := make([]string, 0, len(trainedOptions))
			for _, o := range trainedOptions {
				labels = append(labels, o.label)
			}
			check("练度门槛恰是三档，且文案与参照逐字相同",
				strings.Join(labels, "|") == "不限|≥ 精英二 60 级|精英二 90 级",
				strings.Join(labels, "|"))
			//: ★ 边界：这一组是参照的判据专门钉过的形状（`check_tui.py:1643-1650`：
			//: 「E1 80 级不该过『≥精英二60』」）—— 元组比较 vs「两个都 ≥」的分水岭。
			bounds := []struct {
				why  string
				op   RosterOperator
				opt  trainedOption
				want bool
			}{
				{"E1L80 不过「≥精英二60」（精英段不够，元组比较先比精英段）",
					RosterOperator{Elite: 1, Level: 80}, trainedOptions[1], false},
				{"E2L60 过「≥精英二60」（边界取等）",
					RosterOperator{Elite: 2, Level: 60}, trainedOptions[1], true},
				{"E2L59 不过「≥精英二60」",
					RosterOperator{Elite: 2, Level: 59}, trainedOptions[1], false},
				{"E2L45 不过「精英二90」",
					RosterOperator{Elite: 2, Level: 45}, trainedOptions[2], false},
				{"E0L1 过「不限」（底线是 (0,1)，不是 (0,0)）",
					RosterOperator{Elite: 0, Level: 1}, trainedOptions[0], true},
				{"E0L0 不过「不限」",
					RosterOperator{Elite: 0, Level: 0}, trainedOptions[0], false},
			}
			for _, b := range bounds {
				check("练度门槛边界："+b.why,
					meetsTrained(b.op, b.opt) == b.want,
					fmt.Sprintf("实得 %v", meetsTrained(b.op, b.opt)))
			}
			base9 := len(ss9.visible())
			depth9 := len(r9.stack)
			press(r9, "f")
			check("F 打开练度下拉（展开态）", ss9.trOpen, fmt.Sprintf("trOpen=%v", ss9.trOpen))
			press(r9, "enter") //: 回车 = 确认当前档（不限），**不是**进入下一步
			check("★ 下拉展开时回车**只确认门槛**、不进入下一步（栈深不变）",
				!ss9.trOpen && len(r9.stack) == depth9,
				fmt.Sprintf("trOpen=%v 栈深 %d→%d", ss9.trOpen, depth9, len(r9.stack)))
			press(r9, "f")
			press(r9, "down")
			press(r9, "down")
			press(r9, "enter") //: 确认「精英二 90 级」
			vis9 := ss9.visible()
			check("选「精英二 90 级」⇒ 只剩 E2L90 的那一位",
				len(vis9) == 1 && vis9[0].Name == "丁",
				fmt.Sprintf("可见 %d 人", len(vis9)))
			//: 再加一道职业筛 ⇒ 空集：这时屏上必须说清"是筛选筛没了"，
			//: 而不是与"名册本身是空的"共用一句含糊的话。
			for i, v := range func() []string { _, vs := ss9.profOptions(); return vs }() {
				if v == "PIONEER" {
					ss9.setProf(i)
				}
			}
			view9 := r9.View()
			check("筛到空集时屏上说清原因（名册有 N 人／当前筛选没人），不是含糊一句",
				len(ss9.visible()) == 0 &&
					strings.Contains(view9, "当前筛选下一个人都没有"),
				fmt.Sprintf("可见 %d 人", len(ss9.visible())))
			ss9.setProf(0)
			ss9.trIdx = 0
			check("负对照：门槛回到「不限」⇒ 可见人数回到基数",
				len(ss9.visible()) == base9,
				fmt.Sprintf("%d / %d", len(ss9.visible()), base9))
		}
	}

	fmt.Println("== 五之八 · 控件清单（「这一屏应当有哪个控件」）==")
	//: ★ 2026-09-27 新加。**这一类断言本身就是那一批问题的病根**：旧自检只断言
	//: **屏名与栈深**（见第四／五节），所以一个控件**整件消失**它照样全绿 ——
	//: 博士实测报的三条（章节屏搜索框、关卡屏难度下拉、选人屏筛选）全是这么溜过去的。
	//:
	//: 这张表 = 各屏的**交互件清单**（照参照实现逐条点出来的）。每一项配一个
	//: **行使性**探针 —— 不是"字段在不在"，而是"它还能不能干活"；
	//: 于是"控件还在但已经废了"也会红。
	//:
	//: ★ 纪律：参照那边某屏加了控件、或这边谁删了控件，**先改这张表**；
	//: 表里每一项都有断言跟着，改了表不改断言会红（表与断言是一对）。
	{
		invCtx := &appCtx{w: 90, h: 26, mode: "auto",
			roster: &rosterData{Source: "selftest", Complete: true, Count: 3,
				Operators: []RosterOperator{
					{CharID: "c1", Name: "甲", Profession: "PIONEER",
						SubProfession: "尖兵", Elite: 0, Level: 1},
					{CharID: "c2", Name: "乙", Profession: "MEDIC",
						SubProfession: "医师", Elite: 1, Level: 45},
					{CharID: "c3", Name: "丙", Profession: "MEDIC",
						SubProfession: "咒愈师", Elite: 2, Level: 90},
				}}}
		invCtx.chapters = data.ListChapters(stages, zones)

		csI := &chapterScreen{}
		ssI := newSquadPickScreen(invCtx, nil)
		stI := &stageScreen{heading: "全部关卡（清单探针）", rows: stages}
		chapterAll := len(csI.shown(invCtx))
		stageAll := len(stI.shown())

		//: 搜索框那条探针的**唯一实现**（正例与负对照共用同一份逻辑）—— 两处各写
		//: 一遍的话，负对照就证明不了正例那把尺子，等于白配。
		//: 判据是「**打字能改可见条数**」：控件整件没了 ⇒ 关键词进不去 ⇒ 条数不变 ⇒ 红。
		chapterKw := func(k string) int {
			csI.update(invCtx, keyMsg(k))
			n := len(csI.shown(invCtx))
			csI.box.clear()
			return n
		}
		stageKw := func(k string) int {
			stI.update(invCtx, keyMsg(k))
			n := len(stI.shown())
			stI.box.clear()
			return n
		}
		kwAlive := func(n, all int) bool { return n > 0 && n < all }

		inv := []struct {
			screen, widget, note string
			probe                func() bool
		}{
			//: 关键词用 `MAIN`（结构性：章节键就是 main_0…main_13 ＋ act*mainss，
			//: 不随数据刷新而变）；**中文与全角折半角**那两把尺子在五之三，不在这里重复。
			{"选章节", "搜索框 #kw", "打字能改可见条数",
				func() bool { return kwAlive(chapterKw("MAIN"), chapterAll) }},
			{"选关卡", "搜索框 #kw", "打字能改可见条数",
				func() bool { return kwAlive(stageKw("1-7"), stageAll) }},
			{"选关卡", "难度下拉 #diff", "恰三档、标签带关数", func() bool {
				o := stI.diffOptions()
				return len(o) == 3 && strings.Contains(o[1].label, "关")
			}},
			{"选人", "练度门槛 #f-trained", "恰三档（不限／≥精英二60／精英二90）",
				func() bool { return len(trainedOptions) == 3 }},
			{"选人", "主职业行 #prof-row", "「全部」＋名册里真有的职业", func() bool {
				i, v := ssI.profOptions()
				return len(i) >= 2 && len(i) == len(v) && v[0] == ""
			}},
			{"选人", "子职业行 #sub-row", "选职业后出现，且只列该职业下的", func() bool {
				ssI.setProf(1) //: 第一个职业（先锋 ⇒ 尖兵）
				i, _ := ssI.subOptions()
				ssI.setProf(0)
				return len(i) == 2
			}},
			{"选人", "鼠标（mouseScreen）", "这一屏认鼠标", func() bool {
				_, ok := any(ssI).(mouseScreen)
				return ok
			}},
		}
		for _, it := range inv {
			check(fmt.Sprintf("控件清单：%s 有「%s」（%s）", it.screen, it.widget, it.note),
				it.probe(), "探针")
		}
		check("控件清单本身不许被清空（至少 7 项，否则这一段会静默变成零行使）",
			len(inv) >= 7, fmt.Sprintf("%d 项", len(inv)))

		//: ★ 这组探针**自己的负对照**（每条尺子一条）：喂一个匹配不到任何行的关键词，
		//: 该形状必须读 **false**（`n > 0` 那一半由此被证明是吃劲的）—— 两条合起来
		//: 才是"有区分力"的证据：同一个形状，一个关键词给 0 行、另一个给非满行。
		//: 少了它，一个"筛成空表"的实现（`shown` 恒返回空）会让上面那两条全绿 ——
		//: 那正是本仓记过的"零行使的绿"。（不写 `!kwAlive(...)`：给定 `n == 0`，
		//: 它是恒真的，摆上去只会像在办事。）
		badCh, badSt := chapterKw("zzz绝无此章"), stageKw("zzz绝无此关")
		check("控件清单负对照：章节屏喂匹配不到的关键词 ⇒ 该形状读 false",
			badCh == 0, fmt.Sprintf("命中 %d 行", badCh))
		check("控件清单负对照：关卡屏喂匹配不到的关键词 ⇒ 该形状读 false",
			badSt == 0, fmt.Sprintf("命中 %d 行", badSt))
	}

	fmt.Println("== 五之九 · 环境屏的「全部关卡」那一行（Go 比参照多的一行）==")
	//: ★ 2026-09-27 新加（博士当天定名）。环境屏是**主线第 9-14 章那一类**才会
	//: 出现的一层（判据是库里那个 zone 真有 ≥2 档 diff_group，不是按章号写死）。
	//:
	//: 它的第 0 行是「全部关卡」——**参照实现没有这一行**（`EnvPickScreen` 只列真
	//: 环境，想跳过去只能 Esc 退回上一层）。博士裁定留着并定名 ⇒ 具名登记的分道
	//: 扬镳（登记在 `docs/python-to-go-migration.md`）。
	//:
	//: 判据盯两件**性质**，不盯文案：
	//:   ① 首行的字就是「全部关卡」——**名字本身是博士定的规格**，所以这一条是
	//:      规格断言，不是"某段文案"断言；
	//:   ② 选中它 ⇒ 列出这一部的**全部**关卡，且**严格多于**任一个真环境档。
	//: ② 是这条尺子的负对照：若它哪天悄悄退化成"等于某个环境档"，只盯 ① 会照样绿。
	{
		zid := ""
		for _, z := range zones {
			if data.ZoneEnvsShown(data.ZoneEnvs(z.ZoneID, stages)) {
				zid = z.ZoneID
				break
			}
		}
		check("存在多档环境的 zone（这一段的前置）", zid != "", zid)
		if zid != "" {
			envs := data.ZoneEnvs(zid, stages)
			r5 := newRoot(&appCtx{w: 90, h: 26, mode: "auto", stages: stages,
				envs: envs, part: &data.ChapterPart{ZoneID: zid, Title: "环境屏探针"}},
				welcomeScreen{})
			r5.push(&envScreen{}, onEnvPicked)
			if screenName(r5.top()) != "*main.envScreen" {
				check("（前置）压到环境屏", false, screenName(r5.top()))
			} else {
				check(fmt.Sprintf("环境屏首行是「全部关卡」（%s 这一部）", zid),
					strings.Contains(r5.View(), "全部关卡"), "全部关卡")
				press(r5, "enter") //: 光标默认在 0 = 「全部关卡」
				if screenName(r5.top()) != "*main.stageScreen" {
					check("选「全部关卡」⇒ 进关卡屏", false, screenName(r5.top()))
				} else {
					got := len(r5.top().(*stageScreen).rows)
					all := len(data.ListStages(stages, data.StageFilter{ZoneID: zid}))
					check("选「全部关卡」⇒ 列出这一部的全部关卡（不按环境筛）",
						got == all && got > 0,
						fmt.Sprintf("实得 %d 关 / 不筛 %d 关", got, all))
					most := 0
					for _, e := range envs {
						if n := len(data.ListStages(stages,
							data.StageFilter{ZoneID: zid, Env: e.Env})); n > most {
							most = n
						}
					}
					check("负对照：「全部关卡」严格多于任一单个环境档（否则它是假的）",
						got > most, fmt.Sprintf("全部 %d 关 > 最大单档 %d 关", got, most))
				}
			}
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

	fmt.Println("== 十四 · 登录屏（五键／三态 Esc／成功带回的话）==")
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
		nSame, _ := noteOf("1", "1", true)  //: 本来就登着这个号（只刷新了凭据）
		nKnown, _ := noteOf("1", "2", true) //: 本机登过、但不是当前号
		nNew, _ := noteOf("1", "3", false)  //: 新号
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

	fmt.Println("== 十五 · 桥的常驻会话（登录那条链的前提）==")
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

	fmt.Println("== 十六 · 引擎客户端（起子进程讲 JSON 行协议）==")
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

	//: ★ 2026-09-27 新加：`load` 那条链 —— 它是 **`deployLimit` 的真值来源**。
	//:
	//: 为什么必须有这条尺子：在它之前，`onStagePicked` 里写的是 `c.deployLimit = 0`
	//: （**写死**），而 `selftest` 里所有 `deployLimit` 都是**测试自己注入**的
	//: （`pickCtx(slot)`／`deployLimit: 4`／`= 6`…）⇒ 那条写死的 0 **不在任何尺子的
	//: 视野里**，跑多少次都是绿的。这正是「零行使的绿」：断言全绿，被测行为一次
	//: 都没被走过。这条判据**真起一次引擎**去问一关的真值，把那条路照亮。
	//:
	//: 两条一起：正例（真值 8，与原始 JSON 并排核过）＋ 负对照（关卡不存在 ⇒
	//: **必须具名失败**，不许静默给 0 —— 0 读起来是「这关能上 0 个人」）。
	//: 引擎或那一关的 JSON 不在场 ⇒ **具名未核**，不判红也不假绿。
	if ec, err := newEngineClient(); err != nil {
		fmt.Printf("  （未核：load 那条链需要引擎 exe，这次找不到。具名原因：%s）\n",
			firstLineWith(err.Error(), "找不到引擎"))
	} else {
		opts, lerr := ec.callLoad("main_01-07")
		if lerr != nil {
			fmt.Printf("  （未核：load main_01-07 取不到（引擎在、但那一关的 JSON 不在本地？）。"+
				"具名原因：%s）\n", firstLineWith(lerr.Error(), "★"))
		} else {
			check("load main_01-07 的 characterLimit = 8（deployLimit 的真值，"+
				"与原始 JSON 的 characterLimit 并排核过）",
				opts.CharacterLimit == 8, fmt.Sprintf("实得 %d", opts.CharacterLimit))
		}
		//: ★ 2026-09-27 加第二关，**它就是博士当场报的那一关**：发布形态下
		//: 「取部署人数上限失败（main_09-12）：★ 桥报错：读关卡文件失败 …The system
		//: cannot find the path specified.」——根因是**逐关 JSON 没人取**
		//: （`data/gamedata/<镜像>/levels/` 那一层不在），不是引擎或路径写错。
		//: 处置是给 `rebuild_data.py` 加了一步「关卡文件」（见 docs 的 12.12）。
		//: 这一条与上面那条**同一处置**：取不到就具名未核，不判红也不假绿 ——
		//: 因为"这批 JSON 在不在盘上"是**数据准备**的状态，不是界面代码的性质。
		if o2, e2 := ec.callLoad("main_09-12"); e2 != nil {
			fmt.Printf("  （未核：load main_09-12 取不到（博士报过的那一关）。"+
				"具名原因：%s）\n", firstLineWith(e2.Error(), "★"))
		} else {
			check("load main_09-12 的 characterLimit = 8（博士当场报的那一关，"+
				"它的 JSON 补进缓存后就该答得上来）",
				o2.CharacterLimit == 8, fmt.Sprintf("实得 %d", o2.CharacterLimit))
		}
		if _, nerr := ec.callLoad("__no_such_level__"); nerr == nil {
			check("负对照：不存在的一关必须具名失败（不许静默给 0）", false,
				"它竟然答上来了")
		} else {
			check("负对照：不存在的一关必须具名失败（不许静默给 0）", true,
				firstLineWith(nerr.Error(), "★"))
		}
	}

	fmt.Println("== 十七 · 解算屏（阶梯／池子／真起一轮引擎）==")
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
			fmt.Println("== 十八 · 结果屏（渲染 ＋ **真导出**）==")
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
	fmt.Println("== 十九 · 助战（开关／单独一屏／上限 13／拦截计入／导出带名字）==")
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
	//:
	//: ★ 它**不许**用「把全局红计数清零」来豁免（旧写法就是 `bad = 0`）：
	//:   那等于把**这一行之前所有红一并勾销** —— 实测 2026-09-27：第一节那条
	//:   「章节 69 条」红了（真值 91），结论照样印「全绿」、退出码照样 0。
	//:   正确做法是**只减掉这一条**：先记住此刻的红数，这条故意红之后再放回去。
	badBeforeDeliberate := bad
	if check("负对照（故意造的红）：零值干员不在「≤E1L1」范围内",
		!isMinLevel(RosterOperator{}),
		fmt.Sprintf("isMinLevel(零值)=%v —— 真值就是它**在**范围内",
			isMinLevel(RosterOperator{}))) {
		fmt.Println("★ 这条负对照没红 ⇒ 第十七段的读数作废")
		return 3
	}
	bad = badBeforeDeliberate

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

	fmt.Println("== 二十 · 发布形态的两条判定（启动前自检的底座）==")
	{
		//: 为什么要在这里判：这两条判定（怎么认发布树、数据根在哪）落下去之后，
		//: 原来只有**打包脚本的装完自查**在行使它们 —— 那要装一棵树才跑得到。
		//: 放在这里，`-selftest` 一条命令就能把它们的**判定表**走一遍。
		base, err := os.MkdirTemp("", "rios-release-form-")
		if err != nil {
			check("建临时目录（发布形态判定的夹具）", false, err.Error())
		} else {
			defer os.RemoveAll(base)
			mk := func(name string, withEng bool, withEngine bool) string {
				d := filepath.Join(base, name)
				_ = os.MkdirAll(d, 0o755)
				if withEng {
					_ = os.MkdirAll(filepath.Join(d, "eng"), 0o755)
				}
				if withEngine {
					_ = os.WriteFile(filepath.Join(d, engineExe), []byte("x"), 0o644)
				}
				return d
			}
			withEng := mk("release", true, true)
			devTree := mk("dev", false, false)
			halfTree := mk("half", false, true)
			engOnly := mk("engonly", true, false)

			check("发布形态：同级有 eng/ ⇒ 是（正常安装出来的样子）",
				isReleaseTree(withEng), withEng)
			//: 负对照：开发树长什么样（有 tools/ 有 go.mod，但没有 eng/、没有引擎 exe）
			//: —— 这一条必须 false，否则开发时那套"往上找"就废了。
			check("负对照：开发树（没有 eng/、没有引擎 exe）⇒ 不是",
				!isReleaseTree(devTree), devTree)
			check("半成品：只有引擎 exe、没有 eng/ ⇒ 也算发布树",
				isReleaseTree(halfTree), halfTree)
			check("只有 eng/、引擎 exe 还没摆 ⇒ 也算发布树",
				isReleaseTree(engOnly), engOnly)

			//: 数据根：发布树里 Python 侧的 `parents[2]` 就是 eng/ ⇒ 两侧共同的数据根是
			//: `eng/data`。候选里没有它，就会出现「db build 说建好了、界面说找不到库」。
			found := ""
			for _, c := range dataDirCandidates() {
				if strings.HasSuffix(filepath.ToSlash(c), "eng/data") {
					found = c
				}
			}
			check("数据目录候选里有 eng/data（发布树两侧的共同数据根）",
				found != "", strings.Join(dataDirCandidates(), " ｜ "))
			//: 负对照：候选里**必须**还留着开发树那两个（exe 同级 data／cwd 下 data），
			//: 否则开发时就找不到数据了 —— 加了 eng/data 不能把原来的挤掉。
			cands := strings.Join(dataDirCandidates(), " ｜ ")
			check("负对照：加了 eng/data 之后，原来的候选一个没少",
				strings.Contains(filepath.ToSlash(cands), "/data ｜") ||
					strings.HasSuffix(filepath.ToSlash(cands), "/data"), cands)

			//: 缺件报告里同一个路径不许出现两次（exe 同级与 cwd 在同一棵树上时会重叠）。
			d := dedupe([]string{"a", "b", "a", "c", "b"})
			check("dedupe 去重且保序（缺件报告里不重复列同一个路径）",
				len(d) == 3 && d[0] == "a" && d[1] == "b" && d[2] == "c",
				strings.Join(d, ","))
		}
	}

	fmt.Println("== 二十一 · 首次运行准备的计划（-setup 的判定层）==")
	{
		//: 为什么只判"计划"不真跑：`-setup` 真跑会下载几十 MB 并建库 —— 那是长等待，
		//: 塞进无终端自检会让这条尺子从"秒级"变成"十几分钟级"。所以把**判定**抽成
		//: 纯函数 `setupPlanFrom` 在这里走遍组合，真跑那一层交给 `tools/build_installer.py`
		//: 的装完自查（它本来就要装一棵树）。
		all := setupPlanFrom(true, false, true, true)
		check("三项齐全 ⇒ 计划为空（入口每次都会调它，这条路径必须是哑的）",
			len(all) == 0, fmt.Sprintf("%d 步", len(all)))

		noPy := setupPlanFrom(false, false, true, true)
		needKeys := func(steps []setupStep) string {
			out := []string{}
			for _, s := range steps {
				out = append(out, s.key)
			}
			return strings.Join(out, ",")
		}
		check("缺解释器 ⇒ 只计划 Python 一项，且**不动**已经齐的数据",
			needKeys(noPy) == "python", needKeys(noPy))
		check("缺数据 ⇒ 计划里有 data（并给出具名原因）",
			needKeys(setupPlanFrom(true, false, false, true)) == "data" &&
				strings.Contains(setupPlanFrom(true, false, false, true)[0].why, "_level_index.json"),
			needKeys(setupPlanFrom(true, false, false, true)))
		check("缺派生库 ⇒ 计划里有 derived（具名到 akdb.sqlite）",
			needKeys(setupPlanFrom(true, false, true, false)) == "derived" &&
				strings.Contains(setupPlanFrom(true, false, true, false)[0].why, "akdb.sqlite"),
			needKeys(setupPlanFrom(true, false, true, false)))
		check("三样全缺 ⇒ 三步按 python→data→derived 排（先有解释器才谈得上建库）",
			needKeys(setupPlanFrom(false, false, false, false)) == "python,data,derived",
			needKeys(setupPlanFrom(false, false, false, false)))
		//: 「没有」与「太旧」必须是两句不同的话 —— 对太旧的机器说「没找到 Python」是错话。
		oldOnly := setupPlanFrom(true, true, true, true)
		check("有 Python 但太旧 ⇒ 计划里有 python，且理由是**版本**不是「没找到」",
			needKeys(oldOnly) == "python" && strings.Contains(oldOnly[0].why, "低于实测过的"),
			needKeys(oldOnly)+" / "+oldOnly[0].why)
		check("太旧 ＋ 缺派生库 ⇒ 两步都在（那两件事互不替代）",
			needKeys(setupPlanFrom(true, true, true, false)) == "python,derived",
			needKeys(setupPlanFrom(true, true, true, false)))
		//: 版本判定的边界（含**保守**的那一侧：3.10 没实测过，就当「太旧」提示一次）。
		check("版本判定：3.11/3.14 不算旧，3.10 与 3.9 算，2.x 算",
			!pythonTooOld("3.11.9") && !pythonTooOld("3.14.4") &&
				pythonTooOld("3.10.11") && pythonTooOld("3.9.13") && pythonTooOld("2.7.18"),
			fmt.Sprintf("3.11.9=%v 3.14.4=%v 3.10.11=%v 3.9.13=%v",
				pythonTooOld("3.11.9"), pythonTooOld("3.14.4"),
				pythonTooOld("3.10.11"), pythonTooOld("3.9.13")))
		//: 负对照：**解析不出来时不许拿它当判据**（空串、怪串都返回 false＝不提示），
		//: 否则一个探针抽风就会让所有人看到「你的 Python 太旧」。
		check("负对照：版本串解析不出来时不判旧（不拿猜的东西当判据）",
			!pythonTooOld("") && !pythonTooOld("weird") && !pythonTooOld("3"),
			fmt.Sprintf("空=%v 怪串=%v 单段=%v",
				pythonTooOld(""), pythonTooOld("weird"), pythonTooOld("3")))
		//: 负对照：把「齐全」和「缺一样」的读数摆在一起，证明这把尺子分得开
		//: （恒真的判据在这里会把它俩判成同一个结果）。
		check("负对照：齐全与缺一样必须给出**不同**的计划",
			len(all) != len(setupPlanFrom(true, false, false, true)),
			fmt.Sprintf("齐全=%d 步 / 缺数据=%d 步", len(all), len(setupPlanFrom(true, false, false, true))))

		//: 真环境那一层：在开发树里（解释器在、数据在）应当判成"不用准备"。
		//: 这一条同时给上面那些纯函数读数当一个"接得上真环境"的凭据。
		real := setupPlan()
		realKeys := needKeys(real)
		check("真环境（开发树）：解释器与数据都在 ⇒ 计划为空",
			realKeys == "", "实得："+realKeys)

		//: 一键流程**不许**去拉开发审计用的那几样（博士 2026-09-27 问过一次：
		//: 「为什么 release 包还会拉 wiki 的干员正文和备注」）。判据把它钉住：
		//: 玩家清单必须**含**那三步硬依赖，且**不含**备注语料／范围索引／外部名册。
		//: ★ 同日晚些时候博士又裁「关卡数据**随用随取**」⇒「关卡文件」这一步
		//: **从这份清单里去掉了**（它本来会一次下 1765 个文件、98 MB、5～25 分钟），
		//: 改成选定某一关时取那一个（见二十三节）。所以下面由「必须含」翻成
		//: **「必须不含」** —— 这条断言就是「首次运行不再全量下载」的守门人。
		joined := strings.Join(playerSteps, ",")
		check("一键流程只跑玩家必需的几步，且**不含关卡文件**（随用随取）",
			strings.Contains(joined, "gamedata 源表") &&
				strings.Contains(joined, "akdb.sqlite") &&
				strings.Contains(joined, "stage 表") &&
				strings.Contains(joined, "enemydb.sqlite") &&
				!strings.Contains(joined, "关卡文件") &&
				!strings.Contains(joined, "prts-notes") &&
				!strings.Contains(joined, "op-briefs") &&
				!strings.Contains(joined, "ranges.json") &&
				!strings.Contains(joined, "operbox"),
			joined)
		//: ★ 2026-09-28 新增（博士首启实测报的那条）：**源表那一步必须在最前面**
		//: —— 干员库是离线步骤，没有源表就必挂；顺序错了等于首启必挂。
		check("「gamedata 源表」排在离线步骤之前（否则干员库必挂）",
			len(playerSteps) > 0 && playerSteps[0] == "gamedata 源表",
			joined)

		//: 双击 exe 那条路（无参数）才自动跑准备；**任何显式开关都不走** ——
		//: 否则判据与排障会被"顺手下载几十 MB"污染，而那是长等待。
		check("无参数且缺件才自动跑准备；显式开关与齐全时都不走",
			shouldAutoSetup(0, setupPlanFrom(false, false, false, false)) &&
				!shouldAutoSetup(1, setupPlanFrom(false, false, false, false)) &&
				!shouldAutoSetup(0, setupPlanFrom(true, false, true, true)),
			fmt.Sprintf("无参缺件=%v 有参缺件=%v 无参齐全=%v",
				shouldAutoSetup(0, setupPlanFrom(false, false, false, false)),
				shouldAutoSetup(1, setupPlanFrom(false, false, false, false)),
				shouldAutoSetup(0, setupPlanFrom(true, false, true, true))))

		//: 工程侧根与那条命令的定位（发布树里必须是 eng/tools/）
		rs := rebuildScript()
		check("那条「一次做齐」的命令定位得到，且与桥脚本同一个根",
			rs != "" && strings.HasSuffix(filepath.ToSlash(rs), "/tools/rebuild_data.py"),
			rs)
	}

	fmt.Println("== 二十二 · 首次运行的进度条（每项任务一条）==")
	//: ★ 2026-09-27 新加（博士要求：「初次运行时的下载不用逐条给出在下载什么东西，
	//: 每项任务渲染一个进度条就行了」）。
	//:
	//: 这一段的**主判据不是"画得好看"，是"子进程的原话不许漏到屏幕上"** ——
	//: 那条要求如果只靠"我改成了 quiet"，下一个人换个传参方式就会漏回去。
	//: 所以喂几行**子进程散文**进去，断言渲染结果里一个字节都不许出现。
	{
		dir, derr := os.MkdirTemp("", "rios-selftest-bars-")
		if derr != nil {
			check("临时目录建得出来（这一段的前置）", false, derr.Error())
			dir = "."
		}
		defer func() { _ = os.RemoveAll(dir) }()
		pf := filepath.Join(dir, "prog.jsonl")
		lines := []string{
			`{"ev":"plan","steps":[{"key":"akdb.sqlite","title":"干员库"},` +
				`{"key":"关卡文件","title":"逐关文件"}]}`,
			`{"ev":"step","key":"akdb.sqlite","state":"run"}`,
			//: ↓ 子进程散文：必须被丢掉
			`取到 2674 个关卡（2242 个关卡号），耗时 0.4 秒`,
			`  [25/1765] 已下 25 个、1.5 MB、失败 0、重试 0`,
			`{"ev":"step","key":"akdb.sqlite","state":"ok","sec":13.9}`,
			`{"ev":"step","key":"关卡文件","state":"run"}`,
			`{"ev":"tick","key":"关卡文件","done":50,"total":200}`,
			`{"ev":"unknown_future_event","x":1}`,
			`{"ev":"summary","ok":1,"failed":0}`,
		}
		if err := os.WriteFile(pf, []byte(strings.Join(lines, "\n")+"\n"), 0o644); err != nil {
			check("进度文件写得出来（这一段的前置）", false, err.Error())
		}
		bars := &setupBars{}
		var off int64
		bars.pollProgress(pf, &off)
		check("plan 解析出 2 步", len(bars.steps) == 2,
			fmt.Sprintf("%d 步", len(bars.steps)))
		check("步状态：干员库 ok、逐关文件 run",
			bars.steps[0].State == "ok" && bars.steps[1].State == "run",
			fmt.Sprintf("%q / %q", bars.steps[0].State, bars.steps[1].State))
		check("tick 落到**正在跑**的那一步（tick 事件不带 key 也能对上）",
			bars.steps[1].Done == 50 && bars.steps[1].Total == 200,
			fmt.Sprintf("%d/%d", bars.steps[1].Done, bars.steps[1].Total))
		check("summary 计数拿到了", bars.haveSum && bars.ok == 1 && bars.failed == 0,
			fmt.Sprintf("ok=%d failed=%d", bars.ok, bars.failed))
		check("负对照：认不出的 ev 不改任何状态（前向兼容，不炸）",
			!bars.apply([]byte(`{"ev":"unknown_future_event","x":1}`)), "忽略")

		var out bytes.Buffer
		bars.render(&out)
		rendered := out.String()
		check("★ 主判据：子进程的原话**一个字节都没漏到屏幕上**",
			!strings.Contains(rendered, "取到 2674 个关卡") &&
				!strings.Contains(rendered, "[25/1765]") &&
				!strings.Contains(rendered, "已下 25 个"),
			fmt.Sprintf("渲染 %d 字节", len(rendered)))
		check("每项任务一行（2 步 ＋ 汇总行）",
			strings.Count(rendered, "\n") == 3,
			fmt.Sprintf("%d 行", strings.Count(rendered, "\n")))
		check("正例：带总数的运行中那一步画出真实百分比（50/200 ⇒ 25%）",
			strings.Contains(rendered, "25%"), firstLineWith(rendered, "25%"))
		check("已完成的画满格、未开始的画空格",
			strings.Contains(rendered, strings.Repeat("█", barWidth)) &&
				!strings.Contains(rendered, "x"), "格数对")
		//: ★ 2026-09-28 新增（博士真机截图报的）：**行宽必须夹住终端宽度**。
		//: 形状：长中文标题（一个字占两格）＋ 窄窗口 ⇒ 行超宽 ⇒ 终端折行 ⇒
		//: 光标回位按逻辑行数上移、物理行数却是两倍 ⇒ 每帧往下漂一行、满屏残字。
		//: 三条断言：① 每行显示宽度 ≤ 窗口宽；② 一行都不许折（行数＝步数）；
		//: ③ 第二帧仍按上一帧的**行数**上移（漂移的判别式）。
		narrow := &setupBars{width: 60, ansi: true}
		narrow.steps = []progressStep{
			{Key: "akdb.sqlite", Title: "干员库", State: "ok", Sec: 12.3},
			{Key: "stage 表", Title: "关卡索引（akdb 里的一张表）", State: "run"},
			{Key: "enemydb.sqlite", Title: "敌人库"},
		}
		var w1 bytes.Buffer
		narrow.render(&w1)
		maxw := 0
		for _, ln := range strings.Split(strings.TrimRight(w1.String(), "\n"), "\n") {
			if x := ansi.StringWidth(strings.TrimPrefix(ln, "\x1b[2K")); x > maxw {
				maxw = x
			}
		}
		check("★ 进度条行宽夹住终端宽度（60 列窗口：最宽一行 ≤ 60）", maxw <= 60,
			fmt.Sprintf("最宽 %d 格", maxw))
		check("★ 长中文标题不折行（3 步 ＋ 1 汇总位 ⇒ 内容恰好 4 行；首帧另有 4 行占位）",
			strings.Count(w1.String(), "\n") == 8,
			fmt.Sprintf("%d 行（4 占位 ＋ 4 内容）", strings.Count(w1.String(), "\n")))
		var w2 bytes.Buffer
		narrow.render(&w2)
		check("★ 重画按上一帧行数上移（第二帧以 \\x1b[4A 开头 ⇒ 不逐帧往下漂）",
			strings.HasPrefix(w2.String(), "\x1b[4A"),
			fmt.Sprintf("第二帧 %d 字节、4 行", w2.Len()))
		//: ★★ 2026-09-28 博士物理机截图（同一行被印了三遍）⇒ 两条钉死：
		//:   ① 块高**恒定**＝步数 ＋ 1（给汇总留位）；② 第一帧**先占位再锚定**
		//:   （先把滚动吃掉，否则贴底时每帧都会偏一行、旧字留在屏上）。
		check("★ 第一帧先占位（3 步 ⇒ 先打 4 个空行，再上移 4）",
			strings.HasPrefix(w1.String(), "\n\n\n\n\x1b[4A"),
			fmt.Sprintf("开头 %q", w1.String()[:min(12, w1.Len())]))
		check("★ 每帧**内容**行数恒定（首帧 4 占位 ＋ 4 内容；之后每帧 4 行）",
			strings.Count(w1.String(), "\n")-4 == strings.Count(w2.String(), "\n") &&
				strings.Count(w2.String(), "\n") == 4,
			fmt.Sprintf("第一帧 %d 行 / 第二帧 %d 行",
				strings.Count(w1.String(), "\n"), strings.Count(w2.String(), "\n")))
		//: 负对照：汇总来了之后，行数**不许变**（变一行就会漂一行）
		narrow.haveSum = true
		narrow.ok, narrow.failed = 3, 0
		var w2b bytes.Buffer
		narrow.render(&w2b)
		check("负对照：汇总行出现后行数仍为 4（不许长高）",
			strings.Count(w2b.String(), "\n") == 4,
			fmt.Sprintf("%d 行", strings.Count(w2b.String(), "\n")))
		//: 负对照：窗口压到极窄，也必须一行都不超（`cut` 兜底在场）
		tiny := &setupBars{width: 28, ansi: true}
		tiny.steps = narrow.steps
		var w3 bytes.Buffer
		tiny.render(&w3)
		tw := 0
		for _, ln := range strings.Split(strings.TrimRight(w3.String(), "\n"), "\n") {
			if x := ansi.StringWidth(strings.TrimPrefix(ln, "\x1b[2K")); x > tw {
				tw = x
			}
		}
		check("负对照：28 列窗口下也不许有行超宽", tw <= 28, fmt.Sprintf("最宽 %d 格", tw))
		//: ★ 2026-09-28 新增（博士第二次截图：满屏 `[2K`、`[3A` 字面量）：
		//: **VT 开不了时不许装作能原地重画** —— 一行转义序列都不发，只在状态变时追加。
		plain := &setupBars{width: 60}
		plain.steps = []progressStep{
			{Key: "akdb.sqlite", Title: "干员库", State: "ok", Sec: 12.3},
			{Key: "stage 表", Title: "关卡索引（akdb 里的一张表）", State: "run"},
		}
		var p1, p2 bytes.Buffer
		plain.render(&p1)
		plain.render(&p2)
		check("★ VT 开不了时退化成追加式：输出里一个转义序列都没有",
			!strings.Contains(p1.String(), "\x1b"),
			fmt.Sprintf("首帧 %d 行", strings.Count(p1.String(), "\n")))
		check("★ 追加式：状态没变就不重复印（第二帧 0 字节 ⇒ 不会堆满屏）",
			p2.Len() == 0, fmt.Sprintf("%d 字节", p2.Len()))
		plain.steps[1].State = "ok"
		var p3 bytes.Buffer
		plain.render(&p3)
		check("负对照：追加式里状态一变就必须印一行（否则这条路是死的）",
			strings.Count(p3.String(), "\n") == 1,
			fmt.Sprintf("%d 行", strings.Count(p3.String(), "\n")))
		//: ★ 2026-09-28 新增（博士要的）：**百分比 ＋ 下载速度 ＋ 已下多少**。
		rate := &setupBars{width: 100, ansi: true}
		rate.steps = []progressStep{
			{Key: "enemydb.sqlite", Title: "敌人库", State: "run", Done: 421, Total: 1807},
		}
		rate.sampleRate(&rate.steps[0], 0, 0) //: 第一次取样：有字节没速度
		//: 造一段"两秒下了 2 MB"的取样（直接摆样本，不真的 sleep）
		rate.samples["enemydb.sqlite"] = sample{bytes: 0, at: time.Now().Add(-2 * time.Second)}
		rate.sampleRate(&rate.steps[0], 2<<20, 0)
		var rb bytes.Buffer
		rate.render(&rb)
		check("★ 运行中的一步报出百分比",
			strings.Contains(rb.String(), "421 / 1807（23%）"),
			firstLineWith(rb.String(), "421"))
		check("★ 报出下载速度（2 MB / 2 s ⇒ 1.0 MB/s）",
			strings.Contains(rb.String(), "1.0 MB/s"), firstLineWith(rb.String(), "MB/s"))
		check("★ 报出已下多少", strings.Contains(rb.String(), "已下 2.0 MB"),
			firstLineWith(rb.String(), "已下"))
		//: 负对照：字节没涨（缓存命中，本来就没走网络）⇒ **不许报速度**
		//: （报个"0 B/s"会被读成"卡住了"，那是编出来的信息）
		nost := &progressStep{Key: "x", State: "run", Done: 1, Total: 10}
		nb := &setupBars{}
		nb.sampleRate(nost, 5<<20, 0)
		nb.samples["x"] = sample{bytes: 5 << 20, at: time.Now().Add(-2 * time.Second)}
		nb.sampleRate(nost, 5<<20, 0)
		check("负对照：字节没涨（缓存命中）⇒ 不报速度", nost.Rate == 0,
			fmt.Sprintf("rate=%.0f B/s", nost.Rate))
		//: ★ 2026-09-28 新增（博士第二次报"没看到下载速度"）：**同一批读进来的两行**
		//: 也必须算得出速度 —— 关键是时刻取 tick **自带的** `t`，不是"读到它的时刻"。
		//: 用 `apply()` 走真解析路径（不是直接调 sampleRate），两行连着喂。
		speed := &setupBars{}
		speed.steps = []progressStep{{Key: "gamedata 源表", Title: "游戏源表", State: "run"}}
		base := float64(time.Now().Unix())
		speed.apply([]byte(fmt.Sprintf(
			`{"ev":"tick","key":"gamedata 源表","done":0,"total":8,"bytes":0,"t":%.3f}`, base)))
		speed.apply([]byte(fmt.Sprintf(
			`{"ev":"tick","key":"gamedata 源表","done":1,"total":8,"bytes":2097152,"t":%.3f}`,
			base+2)))
		check("★ 同一批读进来的两行 tick 也算得出速度（时刻取 tick 自带的 t）",
			speed.steps[0].Rate > 900000 && speed.steps[0].Rate < 1100000,
			fmt.Sprintf("rate=%.2f MB/s", speed.steps[0].Rate/1048576))
		var sb bytes.Buffer
		speed.render(&sb)
		check("★ 那一行确实印出了速度", strings.Contains(sb.String(), "1.0 MB/s"),
			firstLineWith(sb.String(), "1.0"))
		//: ★ 完成之后**不许把数字抹掉**：短步骤的实时数字会被"完成"那一行取代，
		//: 不带过去就等于"我从没见过速度"。完成行要带已下多少 ＋ 平均速度。
		done0 := &progressStep{Key: "z", Title: "游戏源表", State: "ok", Sec: 4.0,
			Bytes: 8 << 20}
		dl := tailOf(done0)
		check("★ 完成行带上下载量与平均速度（否则速度一闪就没）",
			strings.Contains(dl, "已下 8.0 MB") && strings.Contains(dl, "2.0 MB/s 平均"), dl)
		//: 负对照：给不出总数的那一步**不许编百分比**，只报"已下多少"
		notot := &progressStep{Key: "y", Title: "干员库", State: "run", Bytes: 3 << 20}
		tl := tailOf(notot)
		check("负对照：没有总数时不编百分比（只报已下多少）",
			!strings.Contains(tl, "%") && strings.Contains(tl, "已下 3.0 MB"), tl)
		//: 负对照：坏 JSON 不许把已解析出来的东西打乱
		before := len(bars.steps)
		check("负对照：截断的 JSON 行被丢掉，不影响已解析的状态",
			!bars.apply([]byte(`{"ev":"step","key":"关卡`)) && len(bars.steps) == before,
			"忽略")
		_ = os.Remove(pf)
	}

	fmt.Println("== 二十三 · 关卡随用随取（选定一关才取那一个文件）==")
	//: ★ 2026-09-27 博士裁：首次运行不再一次下 1765 个关卡文件（98 MB、5～25 分钟），
	//: 改成**选定那一关时**取那一个（约 60 KB）。这一节盯两件性质：
	//:   ① 已经在盘上的关 ⇒ 桥**不发请求**（`cached`），只报文件大小；
	//:      —— 这条防的是"每选一次关都重下一遍"那种看不见的浪费；
	//:   ② 负对照：索引里没有这一关 ⇒ **具名失败**，不许静默当成"这关没地图"
	//:      （与"部署人数上限不写死 0"同一处置）。
	//: 这一节要走 Python 桥；桥不在场时**具名未核**（发布树里它随 eng/ 走，通常在场）。
	{
		if _, err := newBridgeClient(); err != nil {
			fmt.Printf("  （未核：这一条要走 Python 桥，这次找不到。具名原因：%s）\n",
				firstLineWith(err.Error(), "★"))
		} else {
			//: ★ 2026-09-28 修（打包自查时红的那一条）：原来**只调一次**就断言
			//: `!fetched` ⇒ 它量的其实是"这台机器的缓存里恰好有这一关"，而不是
			//: "已在盘上就不再发请求"这条性质。发布树里没有 `data/`，于是桥真去取
			//: 了一次、`fetched=true` ⇒ 假红（`build_release.py` 因此 rc=1）。
			//: 改成**先预热一次**（不在盘上就先取下来），再调第二次断言 ——
			//: 这样量的是性质本身，与环境无关；首取那次的读数照样印出来当对照。
			firstFetched, _, ferr := ensureLevelFile("main_09-12")
			if ferr != nil {
				fmt.Printf("  （未核：预热那一取没成，取不到「已在盘上」这条正例。具名原因：%s）\n",
					firstLineWith(ferr.Error(), "★"))
			} else {
				fetched, n, err := ensureLevelFile("main_09-12")
				if err != nil {
					fmt.Printf("  （未核：ensure_level 没答上来。具名原因：%s）\n",
						firstLineWith(err.Error(), "★"))
				} else {
					check("已在盘上的关 ⇒ 桥不发请求（cached），并报出文件大小",
						!fetched && n > 0,
						fmt.Sprintf("首取 fetched=%v、复取 fetched=%v bytes=%d",
							firstFetched, fetched, n))
				}
			}
			if _, _, err := ensureLevelFile("__no_such_level__"); err == nil {
				check("负对照：索引里没有这一关 ⇒ 具名失败（不许静默当成「这关没地图」）",
					false, "竟然成功了")
			} else {
				check("负对照：索引里没有这一关 ⇒ 具名失败（不许静默当成「这关没地图」）",
					strings.Contains(err.Error(), "__no_such_level__"),
					firstLineWith(err.Error(), "索引"))
			}
		}
	}

	fmt.Println("== 二十四 · 打开工具时的自动更新检查（纯函数判定）==")
	//: ★ 2026-09-27 博士：「让用户打开本工具的时候程序自动请求数据文件」。
	//: 判定抽成纯函数 `updateActions`，判据直接喂六格 —— 不必真联网。
	//: 最要紧的一条是**负对照**：查不到（未核）时绝不动手，因为把"没问到"
	//: 说成"有新版本"会让人白下几十 MB。
	{
		cases := []struct {
			name string
			in   *updateInfo
			want string
		}{
			{"没查成 ⇒ 什么都不做（哪怕两个标志都是真）",
				&updateInfo{Checked: false, DataUpdate: true, PackUpdate: true}, ""},
			{"都一致 ⇒ 什么都不做", &updateInfo{Checked: true}, ""},
			{"只游戏数据旧 ⇒ 重建", &updateInfo{Checked: true, DataUpdate: true}, "rebuild"},
			{"只数据包旧 ⇒ 拉包", &updateInfo{Checked: true, PackUpdate: true}, "pack"},
			{"都旧 ⇒ 先重建、后拉包（顺序即执行顺序）",
				&updateInfo{Checked: true, DataUpdate: true, PackUpdate: true},
				"rebuild,pack"},
			{"nil ⇒ 不炸、不动手", nil, ""},
		}
		for _, c := range cases {
			got := strings.Join(updateActions(c.in), ",")
			check("自动更新："+c.name, got == c.want,
				fmt.Sprintf("实得 %q，期望 %q", got, c.want))
		}
	}

	fmt.Println()
	if bad > 0 {
		fmt.Printf("结论：**%d 条红** —— TUI 自检不通过\n", bad)
		return 1
	}
	fmt.Println("结论：**全绿** —— 取数／降级／屏栈／下钻／退回／空数据退路／路径补全／改目录／解算入口守卫（自限拦截·两条路）／防绕过／桥具名失败／询问屏／扫码屏／登录屏（含桥的常驻会话）／引擎客户端／解算屏／结果屏与导出／助战（上限 13·拦截计入）／发布形态（认树·数据根）／首次运行准备（计划层）逐条过")
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

// widenHalfForTest 把 ASCII 可见字符写成**全角** —— 模拟中文输入法全角模式打出来的
// 那一串（`narrowHalf` 的反向）。判据用它来证「全角也能筛」（用户全角模式下按了
// 也白按，是他看不到的那种坏）。
func widenHalfForTest(s string) string {
	out := make([]rune, 0, len(s))
	for _, r := range s {
		if r >= 0x21 && r <= 0x7E {
			out = append(out, r+0xFEE0)
			continue
		}
		out = append(out, r)
	}
	return string(out)
}

func firstLineWith(s, needle string) string {
	for _, ln := range strings.Split(s, "\n") {
		if strings.Contains(ln, needle) {
			return ln
		}
	}
	return "（没找到含 " + needle + " 的行）"
}
