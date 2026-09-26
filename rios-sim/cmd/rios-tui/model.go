package main

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/x/ansi"

	"rios-sim/data"
)

// 选关的三个层次（迁移图 §7.5）：章/活动 → 部(zone) → 环境分层 → 关卡列表。
//
// 「部」只在多部章里出现；「环境分层」只在 `ZoneEnvsShown` 为真时出现
// （6 个 zone 有 ≥2 档）。所以从章到关卡要走的层数是**按数据定的**，
// 不是写死的四步 —— 这一点与原 Python 界面一致。
type screen int

const (
	scrChapter screen = iota
	scrPart
	scrEnv
	scrStage
)

var (
	styleTitle  = lipgloss.NewStyle().Bold(true)
	styleCrumb  = lipgloss.NewStyle().Foreground(lipgloss.Color("245"))
	styleCursor = lipgloss.NewStyle().Bold(true).Reverse(true)
	styleDim    = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
)

type model struct {
	stages   []data.StageRecord
	zones    []data.ZoneRecord
	chapters []data.Chapter

	scr    screen
	cursor int
	w, h   int
	status string

	chapter *data.Chapter
	part    *data.ChapterPart
	env     string
	envs    []data.ZoneEnv
	shown   []data.StageRecord
}

func newModel(stages []data.StageRecord, zones []data.ZoneRecord) *model {
	return &model{
		stages: stages,
		zones:  zones,
		//: 三层都在同一份「一次读全表」的数据上做聚合，见 datastage.go 的注释。
		chapters: data.ListChapters(stages, zones),
		scr:      scrChapter,
		w:        90,
		h:        26,
	}
}

func (m *model) Init() tea.Cmd { return nil }

// ---- 宽度：一律走 x/ansi -------------------------------------------------
//
// ★ 不自己数 rune：中文是全角，`len()` 与视觉宽度不是一回事。选 `x/ansi`
// 有现成依据 —— 本仓 2026-09-26 做过探针：`x/ansi.StringWidth` 与旧界面用的
// Rich `cell_len` 在 147 条真实对象上**逐字符 0 分歧**。照它排版，新旧界面
// 的对齐才是同一套口径。

func pad(s string, w int) string {
	if d := w - ansi.StringWidth(s); d > 0 {
		return s + strings.Repeat(" ", d)
	}
	return s
}

func cut(s string, w int) string {
	if ansi.StringWidth(s) <= w {
		return s
	}
	return ansi.Truncate(s, w, "…")
}

// ---- 逐层的行 -------------------------------------------------------------

func (m *model) rows() []string {
	switch m.scr {
	case scrChapter:
		out := make([]string, 0, len(m.chapters))
		for _, c := range m.chapters {
			sub := c.Subtitle
			if sub == "" {
				sub = "—"
			}
			out = append(out, pad(c.Key, 12)+pad(c.Title, 24)+pad(sub, 18)+
				fmt.Sprintf("关数 %3d", c.Levels))
		}
		return out
	case scrPart:
		if m.chapter == nil {
			return nil
		}
		out := make([]string, 0, len(m.chapter.Parts))
		for _, p := range m.chapter.Parts {
			t := p.Title
			if t == "" {
				t = p.ZoneID
			}
			out = append(out, pad(t, 36)+fmt.Sprintf("关数 %3d", p.Levels)+"  "+p.ZoneID)
		}
		return out
	case scrEnv:
		if len(m.envs) <= 1 {
			return nil
		}
		out := []string{"不限（这一部的全部环境）"}
		for _, e := range m.envs {
			out = append(out, pad(e.Env, 10)+pad(e.Label, 14)+fmt.Sprintf("关数 %3d", e.Levels))
		}
		return out
	case scrStage:
		out := make([]string, 0, len(m.shown))
		for _, s := range m.shown {
			out = append(out, pad(s.Code, 12)+pad(s.Name, 22)+pad(s.Difficulty, 10)+
				pad(s.DiffGroup, 8)+s.LevelID)
		}
		return out
	}
	return nil
}

func (m *model) count() int { return len(m.rows()) }

// ---- 下钻与回退 -----------------------------------------------------------

func (m *model) enter() {
	switch m.scr {
	case scrChapter:
		if m.cursor >= len(m.chapters) {
			return
		}
		c := &m.chapters[m.cursor]
		m.chapter, m.part, m.envs, m.env = c, nil, nil, ""
		if len(c.Parts) > 1 { // 多部：先选部
			m.scr, m.cursor = scrPart, 0
			return
		}
		if len(c.Parts) == 1 {
			m.part = &c.Parts[0]
		}
		m.enterPart()
	case scrPart:
		if m.chapter == nil || m.cursor >= len(m.chapter.Parts) {
			return
		}
		m.part = &m.chapter.Parts[m.cursor]
		m.enterPart()
	case scrEnv:
		m.env = ""
		if m.cursor > 0 && m.cursor-1 < len(m.envs) {
			m.env = m.envs[m.cursor-1].Env
		}
		m.enterStage()
	case scrStage:
		if m.cursor < len(m.shown) {
			s := m.shown[m.cursor]
			m.status = fmt.Sprintf("已选 %s %s —— 编队／解算这一步尚未实现（TUI 第一刀只做到选关）",
				s.Code, s.Name)
		}
	}
}

func (m *model) enterPart() {
	zone := ""
	if m.part != nil {
		zone = m.part.ZoneID
	}
	m.envs = data.ZoneEnvs(zone, m.stages)
	m.env = ""
	if data.ZoneEnvsShown(m.envs) {
		m.scr, m.cursor = scrEnv, 0
		return
	}
	m.enterStage()
}

func (m *model) enterStage() {
	f := data.StageFilter{Env: m.env}
	if m.part != nil {
		f.ZoneID = m.part.ZoneID //: 精确匹配，不是子串（datastage.go 的口径）
	}
	m.shown = data.ListStages(m.stages, f)
	m.scr, m.cursor = scrStage, 0
}

func (m *model) back() {
	switch m.scr {
	case scrChapter:
		m.status = "已经在最外层（按 q 退出）"
	case scrPart:
		m.reset()
	case scrEnv:
		if m.chapter != nil && len(m.chapter.Parts) > 1 {
			m.scr, m.cursor = scrPart, 0
			return
		}
		m.reset()
	case scrStage:
		if data.ZoneEnvsShown(m.envs) {
			m.scr, m.cursor = scrEnv, 0
			return
		}
		if m.chapter != nil && len(m.chapter.Parts) > 1 {
			m.scr, m.cursor = scrPart, 0
			return
		}
		m.reset()
	}
}

func (m *model) reset() {
	m.scr, m.cursor = scrChapter, 0
	m.chapter, m.part, m.env, m.envs, m.shown = nil, nil, "", nil, nil
}

// ---- 更新与渲染 -----------------------------------------------------------

func (m *model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.w, m.h = msg.Width, msg.Height
	case tea.KeyMsg:
		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "up", "k":
			if m.cursor > 0 {
				m.cursor--
			}
		case "down", "j":
			if m.cursor < m.count()-1 {
				m.cursor++
			}
		case "enter":
			m.enter()
		case "esc", "backspace":
			m.back()
		}
	}
	return m, nil
}

func (m *model) crumb() string {
	parts := []string{"章节"}
	if m.chapter != nil {
		parts = append(parts, m.chapter.Title)
	}
	if m.part != nil {
		t := m.part.Title
		if t == "" {
			t = m.part.ZoneID
		}
		parts = append(parts, t)
	}
	if m.scr == scrStage {
		e := m.env
		if e == "" {
			e = "全部环境"
		}
		parts = append(parts, e)
	}
	return strings.Join(parts, " › ")
}

func (m *model) help() string {
	base := "↑/↓ 或 j/k 移动 · Enter 进入 · Esc 返回"
	if m.scr == scrStage {
		return base + " · q 退出（这一层 Enter = 选定）"
	}
	return base + " · q 退出"
}

func (m *model) bodyRows() int {
	n := m.h - 6
	if n < 1 {
		n = 1
	}
	return n
}

func (m *model) View() string {
	var b strings.Builder
	b.WriteString(styleTitle.Render("R.I.O.S. 作战演算") + "  " + styleCrumb.Render(m.crumb()) + "\n")
	b.WriteString(styleDim.Render(m.help()) + "\n\n")

	lines := m.rows()
	if len(lines) == 0 {
		b.WriteString(styleDim.Render("  （这一层没有条目）") + "\n")
	} else {
		top := 0
		if m.cursor >= m.bodyRows() {
			top = m.cursor - m.bodyRows() + 1
		}
		for i := top; i < len(lines) && i < top+m.bodyRows(); i++ {
			line := cut(lines[i], m.w-3)
			if i == m.cursor {
				b.WriteString(styleCursor.Render("> "+line) + "\n")
			} else {
				b.WriteString("  " + line + "\n")
			}
		}
	}
	b.WriteString("\n" + styleDim.Render(fmt.Sprintf("共 %d 条", len(lines))) + "\n")
	if m.status != "" {
		b.WriteString(m.status + "\n")
	}
	return b.String()
}
