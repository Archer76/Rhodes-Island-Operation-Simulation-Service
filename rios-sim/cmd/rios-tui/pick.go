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

type chapterScreen struct{ cursor int }

func (*chapterScreen) title() string { return "选章节" }
func (*chapterScreen) help() string  { return listHelp }

func (s *chapterScreen) view(c *appCtx) string {
	rows := make([]string, 0, len(c.chapters))
	for _, ch := range c.chapters {
		sub := ch.Subtitle
		if sub == "" {
			sub = "—"
		}
		rows = append(rows, pad(ch.Key, 12)+pad(ch.Title, 24)+pad(sub, 18)+
			fmt.Sprintf("关数 %3d", ch.Levels))
	}
	return renderList(c, "选择章节／活动", rows, s.cursor)
}

func (s *chapterScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	if n, ok := moveCursor(k, s.cursor, len(c.chapters)); ok {
		s.cursor = n
		return s, action{kind: actNone}
	}
	switch {
	case keyIs(k, "enter"):
		if s.cursor < len(c.chapters) {
			return s, action{kind: actBack, res: &c.chapters[s.cursor]}
		}
	case keyIs(k, "esc"), keyIs(k, "backspace"):
		return s, action{kind: actBack}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
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
	//: 第 0 行固定是「不限」——它对应 Python 里的 `env=None`。
	rows := []string{"不限（这一部的全部环境）"}
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
			return s, action{kind: actBack} // res=nil 就是「不限」
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

type stageScreen struct {
	heading string
	rows    []data.StageRecord
	cursor  int
}

func (*stageScreen) title() string { return "选关卡" }
func (*stageScreen) help() string {
	return "↑/↓ 移动 · Enter 选定 · Esc 返回 · Q 退出"
}

func (s *stageScreen) view(c *appCtx) string {
	rows := make([]string, 0, len(s.rows))
	for _, st := range s.rows {
		rows = append(rows, pad(st.Code, 12)+pad(st.Name, 22)+pad(st.Difficulty, 10)+
			pad(st.DiffGroup, 8)+st.LevelID)
	}
	return renderList(c, s.heading, rows, s.cursor)
}

func (s *stageScreen) update(_ *appCtx, k tea.KeyMsg) (screen, action) {
	if n, ok := moveCursor(k, s.cursor, len(s.rows)); ok {
		s.cursor = n
		return s, action{kind: actNone}
	}
	switch {
	case keyIs(k, "enter"):
		if s.cursor < len(s.rows) {
			return s, action{kind: actBack, res: &s.rows[s.cursor]}
		}
	case keyIs(k, "esc"), keyIs(k, "backspace"):
		return s, action{kind: actBack}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
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
		r.ctx.env = "" // 不限
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
		return
	}
	c := r.ctx
	c.stage = st
	//: ★ 这一关的**可部署人数**目前取不到（引擎侧的 `options.characterLimit`
	//: 还没接到界面来），显式写 0 —— **不是**"这一关能上 0 个人"。
	//: 那条拦截规则遇到 0 会退化，见 `squad.go` 文件头的登记。
	c.deployLimit = 0
	c.squad = nil
	c.ensureRoster() //: 进 [2] 时读一次名册并缓存（取不到也只记原因，不拦路）
	r.push(&squadAskScreen{}, onSquadAsked)
}
