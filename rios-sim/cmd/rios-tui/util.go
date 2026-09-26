package main

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/x/ansi"
)

// 样式：集中一处，免得各屏各写一套颜色。
var (
	styleTitle  = lipgloss.NewStyle().Bold(true)
	styleCrumb  = lipgloss.NewStyle().Foreground(lipgloss.Color("245"))
	styleCursor = lipgloss.NewStyle().Bold(true).Reverse(true)
	styleDim    = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
)

// # 排版工具：宽度一律走 x/ansi
//
// ★ 不自己数 rune：中文是全角，`len()` 与视觉宽度不是一回事。选 `x/ansi` 有
// 现成依据 —— 本仓 2026-09-26 做过探针：`x/ansi.StringWidth` 与旧界面用的
// Rich `cell_len` 在 147 条真实对象上**逐字符 0 分歧**。照它排版，新旧界面的
// 对齐才是同一套口径。

func pad(s string, w int) string {
	if d := w - ansi.StringWidth(s); d > 0 {
		return s + strings.Repeat(" ", d)
	}
	return s
}

func cut(s string, w int) string {
	if w <= 0 || ansi.StringWidth(s) <= w {
		return s
	}
	return ansi.Truncate(s, w, "…")
}

// joinArrow 是面包屑的连接符。Python 那侧是步骤条（`theme.step_bar`），
// 我们先用最小形态；等搬到「步骤条」那一屏再对齐它的字形。
func joinArrow(parts []string) string { return strings.Join(parts, " › ") }

// keyIs 处理「小写绑定 ＋ 大写提示」那件事。
//
// Python 侧由 `both_cases()` 给每个单字母绑定补一个大写孪生，理由写在
// `WelcomeScreen.BINDINGS` 的注释里：**只写小写键、只印大写提示**，就会做出
// 「Footer 上写着 D、按 Shift+D 却没反应」的坑 —— 博士实测踩到过。
// 所以这里按钮提示印大写，而两种都收。
func keyIs(k tea.KeyMsg, want string) bool {
	s := k.String()
	if s == want {
		return true
	}
	return len(want) == 1 && strings.EqualFold(s, want)
}
