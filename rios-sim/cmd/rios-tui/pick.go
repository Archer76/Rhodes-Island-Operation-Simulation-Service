package main

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"rios-sim/data"
)

// # 选关四屏
//
// 对应 Python 的 ChapterPickScreen / PartPickScreen / EnvPickScreen /
// StagePickScreen（`app.py:1210/1297/1344/1397`）。
//
// 四屏各自只做一件事：把一列东西画出来、让光标选、回车把**选中的那一个**交还
// 给上一步（`actBack` 带 res）。**下一屏由回调压**（照 `push_step(make, callback)`），
// 不在这四屏里自己 push —— 这样 Esc 退回时每一层只关心自己那一步。
//
// 「部」只在多部章里出现；「环境分层」只在 `ZoneEnvsShown` 为真时出现
// （数据里是 6 个 zone 有 ≥2 档）。所以从章到关卡的层数是**按数据定的**。

func bodyRows(c *appCtx) int {
	n := c.h - 6
	if n < 1 {
		n = 1
	}
	return n
}

// moveCursor 是四屏共用的上下移动（含边界夹取）。
func moveCursor(k tea.KeyMsg, cur, n int) (int, bool) {
	switch {
	case keyIs(k, "up"):
		if cur > 0 {
			return cur - 1, true
		}
		return cur, true
	case keyIs(k, "down"):
		if cur < n-1 {
			return cur + 1, true
		}
		return cur, true
	}
	return cur, false
}

// renderList 是四屏共用的列表渲染：标题 ＋ 可滚动窗口 ＋ 条数。
func renderList(c *appCtx, heading string, rows []string, cursor int) string {
	var b strings.Builder
	b.WriteString(styleTitle.Render(heading) + "\n")
	if len(rows) == 0 {
		b.WriteString(styleDim.Render("  （这一层没有条目）"))
		return b.String()
	}
	body := bodyRows(c)
	top := 0
	if cursor >= body {
		top = cursor - body + 1
	}
	for i := top; i < len(rows) && i < top+body; i++ {
		line := cut(rows[i], c.w-3)
		if i == cursor {
			b.WriteString(styleCursor.Render("> "+line) + "\n")
		} else {
			b.WriteString("  " + line + "\n")
		}
	}
	b.WriteString(styleDim.Render(fmt.Sprintf("共 %d 条", len(rows))))
	return b.String()
}

const listHelp = "↑/↓ 移动 · Enter 进入 · Esc 返回 · Q 退出"

// ---- [3] 选章 -------------------------------------------------------------

type chapterScreen struct {
	cursor int
	box    filterBox //: 零值可用，见 `filterBox` 的说明
}

// shown 是**当前筛选下可见的那些章**（返回的是 `c.chapters` 的下标）。
//
// ★ 光标是**可见列表**里的位置，不是 `c.chapters` 里的位置 —— 筛选一变，
// 同一个光标指的可能是另一章。所有取值都走这里，屏上就不会出现「看到的行
// 与选中的行不是同一条」那种最容易被当成"随机"的错。
func (s *chapterScreen) shown(c *appCtx) []int {
	s.box.ensure()
	out := make([]int, 0, len(c.chapters))
	for i, ch := range c.chapters {
		if s.box.match(ch.Key, ch.Title, ch.Subtitle) {
			out = append(out, i)
		}
	}
	return out
}

// backToChapters 退回「选章节」那一屏（能保留当前章的光标位）。
//
// ★ 为什么是「**把选章屏压回来**」而不是「弹一层」：本仓的导航模型是「屏交结果时
// **弹掉自己**、由回调压下一屏」（`stack.go:11-23` 登记过这次简化）⇒ 走进关卡屏时
// **选章节屏根本不在栈里**（实测：栈是 `[welcomeScreen, stageScreen]`），
// `actBack` 一弹就到准备屏。要退到选章节，只能把选章屏压回来。
//
// ★ 调用点必须在「**弹掉自己之后**的回调」里（`done` 收到 nil 的那一支）。
// 在屏自己的 `update` 里直接 `actPush` 会把这一屏留在栈里 —— 再按一次 esc 又弹
// 回来，来回打转。两处调用点：`onStagePicked`（关卡屏 esc）与 `onSolveClosed`
// （解算屏 q／esc 中止）。
func backToChapters(r *root) {
	scr := &chapterScreen{}
	if c := r.ctx; c.chapter != nil {
		for i := range c.chapters {
			if c.chapters[i].Key == c.chapter.Key {
				scr.cursor = i
				break
			}
		}
	}
	r.push(scr, onChapterPicked)
}

func (*chapterScreen) title() string { return "选章节" }
func (*chapterScreen) help() string {
	return "输关键词筛 · ↑/↓ 移动 · Enter 选定 · Esc 清空／返回 · Q 退出"
}

func (s *chapterScreen) view(c *appCtx) string {
	idx := s.shown(c)
	rows := make([]string, 0, len(idx))
	for _, i := range idx {
		ch := c.chapters[i]
		sub := ch.Subtitle
		if sub == "" {
			sub = "—"
		}
		rows = append(rows, pad(ch.Key, 12)+pad(ch.Title, 24)+pad(sub, 18)+
			fmt.Sprintf("关数 %3d", ch.Levels))
	}
	return s.box.view(c) + "\n" + renderList(c, "选择章节／活动", rows, s.cursor)
}

func (s *chapterScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	idx := s.shown(c)
	//: 筛选一变，可见条数就变 ⇒ 光标要先夹回范围内，否则「第 40 行」在一份
	//: 只剩 2 行的列表上会让取值越界（本仓判据里 `cursor < len(rows)` 那种
	//: 守卫只防越界，不防"指到了别的章"）。
	if s.cursor >= len(idx) {
		s.cursor = max(0, len(idx)-1)
	}
	if n, ok := moveCursor(k, s.cursor, len(idx)); ok {
		s.cursor = n
		return s, action{kind: actNone}
	}
	switch {
	case keyIs(k, "enter"):
		if s.cursor >= 0 && s.cursor < len(idx) {
			return s, action{kind: actBack, res: &c.chapters[idx[s.cursor]]}
		}
	case keyIs(k, "esc"):
		//: Esc 分两级：**有关键词先清空**（这是「我刚打错了」最常见的意图），
		//: 没关键词才返回上一层。Python 侧 `Input` 的 Esc 也是先清自己。
		if s.box.text() != "" {
			s.box.clear()
			s.cursor = 0
			return s, action{kind: actNone}
		}
		return s, action{kind: actBack}
	case keyIs(k, "backspace"):
		if s.box.text() != "" {
			return s, action{kind: actNone, cmd: s.box.key(k)}
		}
		return s, action{kind: actBack}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
	default:
		//: 其余按键交给输入框（可打印字符、左右移动、删除…）。它不认的键
		//: 什么也不做 —— 于是"打字"与"翻列表"两件事不会互相抢键。
		return s, action{kind: actNone, cmd: s.box.key(k)}
	}
	return s, action{kind: actNone}
}

// ---- 选部（只在多部章里出现）------------------------------------------------

type partScreen struct{ cursor int }

func (*partScreen) title() string { return "选分部" }
func (*partScreen) help() string  { return listHelp }

func (s *partScreen) view(c *appCtx) string {
	if c.chapter == nil {
		return renderList(c, "选择分部", nil, 0)
	}
	rows := make([]string, 0, len(c.chapter.Parts))
	for _, p := range c.chapter.Parts {
		t := p.Title
		if t == "" {
			t = p.ZoneID
		}
		rows = append(rows, pad(t, 36)+fmt.Sprintf("关数 %3d", p.Levels)+"  "+p.ZoneID)
	}
	return renderList(c, "选择分部（"+c.chapter.Title+"）", rows, s.cursor)
}

func (s *partScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	if c.chapter == nil {
		return s, action{kind: actBack}
	}
	if n, ok := moveCursor(k, s.cursor, len(c.chapter.Parts)); ok {
		s.cursor = n
		return s, action{kind: actNone}
	}
	switch {
	case keyIs(k, "enter"):
		if s.cursor < len(c.chapter.Parts) {
			return s, action{kind: actBack, res: &c.chapter.Parts[s.cursor]}
		}
	case keyIs(k, "esc"), keyIs(k, "backspace"):
		return s, action{kind: actBack}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
	}
	return s, action{kind: actNone}
}

// ---- 环境分层 -------------------------------------------------------------

type envScreen struct{ cursor int }

func (*envScreen) title() string { return "选环境" }
func (*envScreen) help() string  { return listHelp }

func (s *envScreen) view(c *appCtx) string {
	//: 第 0 行是「全部关卡」——它对应 Python 里的 `env=None`（不按环境筛）。
	//:
	//: ★ **这一行是 Go 比参照多出来的**：参照的 `EnvPickScreen`
	//: （`ak_tactic/tui/app.py:1363-1391`）只列真环境，想跳过这一层只能 Esc 退回
	//: 上一层。博士 2026-09-27 裁定：**留着**，名字叫「全部关卡」（原先是
	//: 「不限（这一部的全部环境）」）。⇒ 这是一处**具名登记的分道扬镳**，
	//: 登记在 `docs/python-to-go-migration.md`。
	//:
	//: 语义与 Esc 同一个落点（都把这一部的全部关卡列出来）——所以这一屏的两个
	//: 口子说的是同一件事，不是两种行为。
	rows := []string{"全部关卡"}
	for _, e := range c.envs {
		rows = append(rows, pad(e.Env, 10)+pad(e.Label, 14)+
			fmt.Sprintf("关数 %3d", e.Levels))
	}
	return renderList(c, "选择环境分层（"+c.heading()+")", rows, s.cursor)
}

func (s *envScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	if n, ok := moveCursor(k, s.cursor, len(c.envs)+1); ok {
		s.cursor = n
		return s, action{kind: actNone}
	}
	switch {
	case keyIs(k, "enter"):
		if s.cursor == 0 {
			return s, action{kind: actBack} // res=nil 就是「全部关卡」
		}
		if s.cursor-1 < len(c.envs) {
			return s, action{kind: actBack, res: &c.envs[s.cursor-1]}
		}
	case keyIs(k, "esc"), keyIs(k, "backspace"):
		return s, action{kind: actBack}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
	}
	return s, action{kind: actNone}
}

// ---- [4] 选关卡 -----------------------------------------------------------

// stageDiffOption 是难度下拉的一档（对应 Python `Select #diff` 的 options）。
type stageDiffOption struct {
	label string //: 显示名 —— **带关数**，照 Python 的「普通（三星）（19 关）」
	value string //: 传给 `data.StageFilter.Difficulty` 的值；空 = 全部
}

type stageScreen struct {
	heading string
	//: **基数**：`pushStage` 已经按 zone／env 筛过的那一批。关键词与难度都在它
	//: 之上再筛 —— 顺序与 Python 一致（`#diff` 与 `#kw` 都是屏上的二次筛选）。
	rows   []data.StageRecord
	cursor int
	box    filterBox //: 零值可用，见 `filterBox`
	diff   string    //: 当前难度档的**值**（""=全部），不是标签
	//: 下拉的展开态（照 Python 的 `Select`：不是循环键，是"开菜单→选→确认"）
	picking bool
	pickAt  int
}

func (*stageScreen) title() string { return "选关卡" }
func (*stageScreen) help() string {
	return "输关键词筛 · D 难度（全部／普通／突袭）· ↑/↓ 移动 · Enter 选定 · Esc 清空／返回 · Q 退出"
}

// diffOptions 是难度下拉的三档 —— 与 Python `Select #diff`（`app.py:1425-1429`）
// 逐项对齐，**标签带关数**（那是它在参照实现里就有的一栏，不是我们加的）。
//
// ★ 关数的口径：对**基数**数（已按 zone／env 筛过、还没按关键词／难度筛）——
// 与 Python 一致：它那两个数是「这一部里普通档几关、突袭档几关」。
// ★ 六星（险地作战）**不单列一档**：参照实现那个下拉也只有三档，`#s` 行只在
// 「全部」里出现。这一条如实登记 —— 要单列是一行代码的事，但那会与参照不同。
// ★ 第一档的显示名参照实现给的是**空串**（`Select` 的 NULL 档，靠占位符
// 「难度」显示"没选"）。这里显式写成「全部（N 关）」：空标签在终端里是一行
// 看不出所以然的空白，而这一档就是"不按难度筛"。
func (s *stageScreen) diffOptions() []stageDiffOption {
	nNormal, nFour := 0, 0
	for _, st := range s.rows {
		switch st.Difficulty {
		case "NORMAL":
			nNormal++
		case "FOUR_STAR":
			nFour++
		}
	}
	return []stageDiffOption{
		{label: fmt.Sprintf("全部（%d 关）", len(s.rows)), value: ""},
		{label: fmt.Sprintf("普通（三星）（%d 关）", nNormal), value: "NORMAL"},
		{label: fmt.Sprintf("突袭（四星）（%d 关）", nFour), value: "FOUR_STAR"},
	}
}

func (s *stageScreen) diffIndex() int {
	for i, o := range s.diffOptions() {
		if o.value == s.diff {
			return i
		}
	}
	return 0
}

// shown 是当前筛选下真正列出的关卡。
//
// ★ 筛选**走数据层的 `data.ListStages`**（`StageFilter.Keyword` / `Difficulty`），
// 不在这里自己写一遍匹配 —— 「同一件事只许一份实现」。关键词在这里只做
// **折半角**：参照实现也是 UI 层先 NFKC 归一、再由 `list_stages` 做字面量匹配。
func (s *stageScreen) shown() []data.StageRecord {
	s.box.ensure()
	return data.ListStages(s.rows, data.StageFilter{
		Keyword:    narrowHalf(strings.TrimSpace(s.box.text())),
		Difficulty: s.diff,
	})
}

func (s *stageScreen) view(c *appCtx) string {
	rows := s.shown()
	lines := make([]string, 0, len(rows))
	for _, st := range rows {
		lines = append(lines, pad(st.Code, 12)+pad(st.Name, 22)+
			pad(st.Difficulty, 10)+pad(st.DiffGroup, 8)+st.LevelID)
	}
	opts := s.diffOptions()
	head := styleDim.Render("难度：") + opts[s.diffIndex()].label
	if s.picking {
		//: 展开态：三档列出来、当前项高亮（照 Python 的 `SelectOverlay`）。
		var b strings.Builder
		b.WriteString("难度：\n")
		for i, o := range opts {
			line := "  " + o.label
			if i == s.pickAt {
				line = styleCursor.Render("> " + o.label)
			}
			b.WriteString(line + "\n")
		}
		head = strings.TrimRight(b.String(), "\n")
	}
	return s.box.view(c) + "\n" + head + "\n" +
		renderList(c, s.heading, lines, s.cursor)
}

func (s *stageScreen) update(_ *appCtx, k tea.KeyMsg) (screen, action) {
	opts := s.diffOptions()
	if s.picking {
		//: 下拉展开时**独占方向键与回车** —— 这正是参照实现记过的那条坑：
		//: 回车在下拉上是「确认这一档」，**不是**「开始解算」/「选定这一关」。
		switch {
		case keyIs(k, "up"):
			s.pickAt = max(0, s.pickAt-1)
		case keyIs(k, "down"):
			s.pickAt = min(len(opts)-1, s.pickAt+1)
		case keyIs(k, "enter"):
			s.diff = opts[s.pickAt].value
			s.picking = false
			s.cursor = 0
		case keyIs(k, "esc"):
			s.picking = false
		}
		return s, action{kind: actNone}
	}
	rows := s.shown()
	//: 筛选一变可见条数就变 ⇒ 光标先夹回范围内（否则会"指到别的关"）。
	if s.cursor >= len(rows) {
		s.cursor = max(0, len(rows)-1)
	}
	if n, ok := moveCursor(k, s.cursor, len(rows)); ok {
		s.cursor = n
		return s, action{kind: actNone}
	}
	switch {
	case keyIs(k, "d"):
		s.picking = true
		s.pickAt = s.diffIndex()
		return s, action{kind: actNone}
	case keyIs(k, "enter"):
		if s.cursor >= 0 && s.cursor < len(rows) {
			return s, action{kind: actBack, res: &rows[s.cursor]}
		}
	case keyIs(k, "esc"):
		if s.box.text() != "" {
			s.box.clear()
			s.cursor = 0
			return s, action{kind: actNone}
		}
		return s, action{kind: actBack}
	case keyIs(k, "backspace"):
		if s.box.text() != "" {
			return s, action{kind: actNone, cmd: s.box.key(k)}
		}
		return s, action{kind: actBack}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
	default:
		return s, action{kind: actNone, cmd: s.box.key(k)}
	}
	return s, action{kind: actNone}
}

// ---- 向导流：压屏与回调（对应 RiosApp 的同名方法）----------------------------

// stagePickScreen 对应 Python 的 `RiosApp.goto_stage_pick`。
func (c *appCtx) stagePickScreen() screen {
	if len(c.chapters) > 0 {
		return &chapterScreen{}
	}
	if len(c.stages) > 0 {
		//: 有 stage 但归不出章（旧库没跑过带 zone 的 `db stage-fetch`）：
		//: 退回平铺列表，总比甩一句「没有数据」强。
		return &stageScreen{heading: "全部关卡（没有章节数据）", rows: c.stages}
	}
	return noStageScreen{}
}

// heading 是当前这一层的名字，给环境屏与关卡屏当标题用。
func (c *appCtx) heading() string {
	if c.part != nil {
		if c.part.Title != "" {
			return c.part.Title
		}
		return c.part.ZoneID
	}
	if c.chapter != nil {
		return c.chapter.Title
	}
	return "全部"
}

// 注：这四个回调是**包级函数**而不是 root 的方法 —— 屏的 `update` 只拿得到
// 共享态、拿不到 root，而回调要能 `push`。做成包级函数，屏就能直接引用它们。

// onChapterPicked 是选章屏的回调。
func onChapterPicked(r *root, res any) {
	ch, _ := res.(*data.Chapter)
	if ch == nil {
		return // Esc：已经弹回上一屏，什么都不做
	}
	c := r.ctx
	c.chapter, c.part, c.env, c.stage = ch, nil, "", nil
	if len(ch.Parts) > 1 {
		r.push(&partScreen{}, onPartPicked)
		return
	}
	if len(ch.Parts) == 1 {
		c.part = &ch.Parts[0]
	}
	r.enterPart()
}

func onPartPicked(r *root, res any) {
	p, _ := res.(*data.ChapterPart)
	if p == nil {
		return
	}
	r.ctx.part = p
	r.enterPart()
}

// enterPart 决定「部之后是环境屏还是直接进关卡列表」——按数据定，不写死步数。
func (r *root) enterPart() {
	c := r.ctx
	zone := ""
	if c.part != nil {
		zone = c.part.ZoneID
	}
	c.envs = data.ZoneEnvs(zone, c.stages)
	c.env = ""
	if data.ZoneEnvsShown(c.envs) {
		r.push(&envScreen{}, onEnvPicked)
		return
	}
	r.pushStage()
}

func onEnvPicked(r *root, res any) {
	if e, ok := res.(*data.ZoneEnv); ok && e != nil {
		r.ctx.env = e.Env
	} else {
		r.ctx.env = "" // 全部关卡（不按环境筛）
	}
	r.pushStage()
}

func (r *root) pushStage() {
	c := r.ctx
	f := data.StageFilter{Env: c.env}
	zone := ""
	if c.part != nil {
		zone = c.part.ZoneID
		f.ZoneID = zone //: 精确匹配，不是子串（datastage.go 的口径）
	}
	head := "选择关卡"
	if c.part != nil {
		head = "选择关卡（" + c.heading() + "）"
	}
	if c.env != "" {
		head += " · " + c.env
	}
	r.push(&stageScreen{heading: head, rows: data.ListStages(c.stages, f)}, onStagePicked)
}

// onStagePicked 是选关屏的回调：选定关卡 → 进 [2] 问编队（`squadAskScreen`，
// 对应 Python 的 `RiosApp.goto_stage_pick` 之后那一步
// —— `_squad_asked`／`_squad_picked` 见 `squad.go`）。
func onStagePicked(r *root, res any) {
	st, _ := res.(*data.StageRecord)
	if st == nil {
		//: Esc（`res` 是 nil）⇒ 退回**选章节**，不是准备屏（博士 2026-09-27 要的落点）。
		//: 落点为什么在这里而不是关卡屏自己的 `update` 里 —— 见 `backToChapters`。
		backToChapters(r)
		return
	}
	c := r.ctx
	c.stage = st
	//: ★ 可部署人数**问引擎**（2026-09-27 接上）。派生库的 `stage` 表没有这一列
	//: （实测 9 列），只有引擎那份解析器读得到 `options.characterLimit`
	//: —— 见 `engpipe.go` 的 `callLoad`。
	//: ⚠ 取不到时**具名记一句**（`c.note`，屏上看得见），**不静默写 0**：
	//: 「0」读起来是「这一关能上 0 个人」，与「没取到」必须长得不一样。
	//: 同步调用与 `ensureRoster()` 同一处置（都是读一份数据，不是分钟级的活）。
	c.deployLimit = 0
	switch ec, err := newEngineClient(); {
	case err != nil:
		c.note = "取部署人数上限失败：" + err.Error()
	default:
		if opts, err := ec.callLoad(st.LevelID); err != nil {
			c.note = "取部署人数上限失败（" + st.LevelID + "）：" + err.Error()
		} else {
			c.deployLimit = opts.CharacterLimit
		}
	}
	c.squad = nil
	c.ensureRoster() //: 进 [2] 时读一次名册并缓存（取不到也只记原因，不拦路）
	r.push(&squadAskScreen{}, onSquadAsked)
}
