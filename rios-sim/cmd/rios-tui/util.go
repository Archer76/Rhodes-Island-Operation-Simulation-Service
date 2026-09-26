package main

import (
	"sort"
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

// sortByLevelDesc 把名册按**练度降序**排（精英、等级，同级按 char_id 定序）。
//
// 与 Python 的 `Roster.top()` 同向；那边还带 `potential` 参与比较，而桥给的名册没有
// 这个字段，所以同级改按 `char_id` 定序 —— 保证两次打开的顺序一致（**登记为分歧**）。
//
// ★ 只有这一份：选人屏的显示序与解算屏补人用的池子序是**同一个口径**，两处各写一遍
// 迟早会漂，而"补进来的人不一样"在下游只表现为"结果不一样"，极难查。
func sortByLevelDesc(ops []RosterOperator) {
	sort.SliceStable(ops, func(i, j int) bool {
		a, b := ops[i], ops[j]
		if a.Elite != b.Elite {
			return a.Elite > b.Elite
		}
		if a.Level != b.Level {
			return a.Level > b.Level
		}
		return a.CharID < b.CharID
	})
}

// pad 补齐到 w 列（按视觉宽度，见文件头）。
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

// keyIs 处理「小写绑定 ＋ 大写提示 ＋ 全角孪生」那一件事。
//
// Python 侧由 `both_cases()` 给每个单字符绑定补两个孪生，理由写在
// `WelcomeScreen.BINDINGS` 的注释里，两条都是实测踩出来的：
//
//   - **大小写**：`Binding("h", …, key_display="H")` 里 `key_display` **只管显示**
//     —— Footer 上印着 `H`，注册的键只有小写 `h`，而 Textual 的键匹配区分大小写
//     ⇒ 用户照着 Footer 按 Shift+H 没反应。所以显示印大写、两种都收。
//   - **全角**：中文输入法全角模式下 `l` 送过来是 `ｌ`、`1` 送来是 `１`
//     ⇒ 不补孪生，用户按了也白按，而他看不到「程序收不到」，只看到「这个键坏了」。
//
// Go 这边不去逐个补孪生，而是**比较前统一折半角 ＋ 忽略大小写** —— 覆盖面更大
// （任何全角变体都认），也不会因为漏写一个孪生而留下一个静默失效的键。
func keyIs(k tea.KeyMsg, want string) bool {
	s := narrowHalf(k.String())
	if s == want {
		return true
	}
	return len(want) == 1 && strings.EqualFold(s, want)
}

// narrowHalf 把中文输入法送来的全角字符折成半角。
//
// **自写窄表，不引 `golang.org/x/text`**（博士 2026-09-26 裁定三）：本项目只需要
// 这两条规则 —— U+FF01–U+FF5E 逐个减 0xFEE0（ASCII 可见字符的全角区），
// U+3000 转空格。为一个字符集映射拖进一整个依赖不划算。
func narrowHalf(s string) string {
	if s == "" {
		return s
	}
	out := make([]rune, 0, len(s))
	for _, r := range s {
		switch {
		case r >= 0xFF01 && r <= 0xFF5E:
			out = append(out, r-0xFEE0)
		case r == 0x3000:
			out = append(out, ' ')
		default:
			out = append(out, r)
		}
	}
	return string(out)
}

// centerBlock 把一段文本在 w×h 的窗口里居中（对应 Python 的 `align: center middle`）。
//
// 宽度按**视觉宽度**算（`x/ansi`，见文件头那条依据），不是按字节数 ——
// 二维码那几行里带 ANSI 序列，按 `len()` 居中会整体偏左。
func centerBlock(block string, w, h int) string {
	lines := strings.Split(block, "\n")
	bw := 0
	for _, ln := range lines {
		if x := ansi.StringWidth(ln); x > bw {
			bw = x
		}
	}
	left := (w - bw) / 2
	if left < 0 {
		left = 0
	}
	top := (h - len(lines)) / 2
	if top < 0 {
		top = 0
	}
	pad := strings.Repeat(" ", left)
	out := make([]string, 0, top+len(lines))
	for i := 0; i < top; i++ {
		out = append(out, "")
	}
	for _, ln := range lines {
		out = append(out, pad+ln)
	}
	return strings.Join(out, "\n")
}

// boxStyle 是模态屏那个圆角框（Python 的 `border: round` ＋ `padding: 1 2`）。
//
// ⚠ `Width(66)` ＋ 边框 2 列 = **总宽 68**，与 Python 的 `#ask-box { width: 68 }`
// 对齐：lipgloss 的 Width 是「边框之内」的宽度，而 Textual 的 width 含边框。
// 这个差 2 的坑有判据盯着（自检里断言整框宽 68）。
var boxStyle = lipgloss.NewStyle().
	Border(lipgloss.RoundedBorder()).
	Padding(1, 2).
	Width(66)
