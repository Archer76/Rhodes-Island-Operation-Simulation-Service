package main

import (
	"fmt"
	"strings"

	"rios-sim/data"
)

// runSelftest 是 TUI 的**无终端判据**。
//
// # 为什么必须有它
//
// 本仓的规矩是「行使判据必须是运行期计数」——而界面最容易退化成
// 「看起来能用」。没有终端的机器上跑不了交互，所以判据必须自己把模型
// 推到每一层、把每一屏**真的渲染出来**、再对内容做断言。
//
// 退出码：0 全过 ／ 1 有红 ／ 3 尺子自检不过（负对照没红，整批读数作废）。
func runSelftest(stages []data.StageRecord, zones []data.ZoneRecord) int {
	var bad int
	check := func(name string, cond bool, got string) bool {
		if cond {
			fmt.Printf("  ✓ %s %s\n", pad(name, 46), got)
			return true
		}
		bad++
		fmt.Printf("  ✗ %s %s\n", pad(name, 46), got)
		return false
	}

	// ★ 负对照：先证明这把尺子**会**判红。不证这一条，后面满屏的 ✓ 是零信息量
	//   （本仓记过：「控制组没红就是没有判据」。）
	if check("负对照：故意造一个假命题（应当判红）", 1 == 2, "这一条是刻意造的红") {
		fmt.Println("★ 负对照没红 ⇒ check 恒真 ⇒ 整批读数作废")
		return 3
	}
	bad = 0

	fmt.Println("== 一 · 取数层 ==")
	m := newModel(stages, zones)
	check("章节 116 条（迁移图 §7.5 的金标）", len(m.chapters) == 116,
		fmt.Sprintf("实得 %d", len(m.chapters)))
	six := 0
	for _, s := range stages {
		if s.Difficulty == "SIX_STAR" {
			six++
		}
	}
	check("六星档已被取数口滤掉（SIX_STAR 行 0）", six == 0, fmt.Sprintf("实得 %d 行", six))
	empty := 0
	for _, c := range m.chapters {
		if c.Levels == 0 {
			empty++
		}
	}
	check("没有空章", empty == 0, fmt.Sprintf("空章 %d 个", empty))

	fmt.Println("== 二 · 第一屏（章节）渲染 ==")
	v := m.View()
	check("渲染里有标题", strings.Contains(v, "R.I.O.S."), "R.I.O.S.")
	check("渲染里有第一个章的名字", strings.Contains(v, m.chapters[0].Title), m.chapters[0].Title)
	check("渲染里有光标行", strings.Contains(v, "> "), "> ")
	check("条数 = 章节数", m.count() == len(m.chapters), fmt.Sprintf("%d 条", m.count()))

	// 下钻：挑一个**多部**章，把「章 → 部 →（环境）→ 关卡」整条走完。
	multi := -1
	for i, c := range m.chapters {
		if len(c.Parts) > 1 {
			multi = i
			break
		}
	}
	check("存在多部章（否则选部那一屏永远走不到）", multi >= 0,
		fmt.Sprintf("首个多部章下标 %d", multi))

	if multi >= 0 {
		m.cursor = multi
		m.enter()
		fmt.Printf("== 三 · 选部屏（章 %s，%d 部）==\n", m.chapter.Title, len(m.chapter.Parts))
		check("进入了选部屏", m.scr == scrPart, fmt.Sprintf("scr=%d", m.scr))
		check("部数 = 章里的 Parts 数", m.count() == len(m.chapter.Parts), fmt.Sprintf("%d 部", m.count()))
		pt := m.chapter.Parts[0].Title
		if pt == "" {
			pt = m.chapter.Parts[0].ZoneID
		}
		check("选部屏渲染里有第一部名字", strings.Contains(m.View(), pt), pt)

		m.cursor = 0
		m.enter()
		zone := m.chapter.Parts[0].ZoneID
		if m.scr == scrEnv {
			fmt.Printf("== 四 · 环境分层屏（%s，%d 档）==\n", zone, len(m.envs))
			rows := m.rows()
			check("环境屏第一项是「不限」", len(rows) > 0 && strings.Contains(rows[0], "不限"), rows[0])
			m.cursor = 0
			m.enter()
		}
		fmt.Println("== 五 · 关卡列表 ==")
		check("已到关卡列表", m.scr == scrStage, fmt.Sprintf("scr=%d", m.scr))
		check("这一部有关卡", len(m.shown) > 0, fmt.Sprintf("%d 关", len(m.shown)))
		wrong := 0
		for _, s := range m.shown {
			if s.ZoneID != zone {
				wrong++
			}
		}
		check("列出的每一关都属于所选 zone（精确匹配）", wrong == 0, fmt.Sprintf("越界 %d 关", wrong))
		v = m.View()
		if len(m.shown) > 0 {
			check("关卡屏渲染里有第一关的代号", strings.Contains(v, m.shown[0].Code), m.shown[0].Code)
			m.enter()
			check("Enter 后给出选定提示", strings.Contains(m.status, m.shown[0].Code), m.status)
		}
		steps := 0
		for m.scr != scrChapter && steps < 8 {
			m.back()
			steps++
		}
		check("Esc 能逐层退回最外层", m.scr == scrChapter, fmt.Sprintf("退了 %d 步", steps))
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

	fmt.Println()
	if bad > 0 {
		fmt.Printf("结论：**%d 条红** —— TUI 自检不通过\n", bad)
		return 1
	}
	fmt.Println("结论：**全绿** —— 选关三层的取数／下钻／渲染／回退逐条过")
	return 0
}
