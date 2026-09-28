package main

import (
	"sort"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/x/ansi"
)

// R.I.O.S. 控制台视觉系统。仅改变绘制，不改变屏栈、行数或命中坐标。
// 使用 256 色而非终端真彩：旧版 Windows 控制台与远程终端也能读清。
var (
	colorInk    = lipgloss.Color("252")
	colorMuted  = lipgloss.Color("245")
	colorCyan   = lipgloss.Color("80")
	colorGold   = lipgloss.Color("221")
	colorPanel  = lipgloss.Color("24")
	colorDanger = lipgloss.Color("210")

	styleTitle  = lipgloss.NewStyle().Foreground(colorCyan).Bold(true)
	styleCrumb  = lipgloss.NewStyle().Foreground(colorMuted)
	styleCursor = lipgloss.NewStyle().Foreground(lipgloss.Color("16")).Background(colorCyan).Bold(true)
	styleDim    = lipgloss.NewStyle().Foreground(colorMuted)
	styleBrand  = lipgloss.NewStyle().Foreground(colorGold).Bold(true)
	styleKey    = lipgloss.NewStyle().Foreground(colorCyan).Bold(true)
	styleRow    = lipgloss.NewStyle().Foreground(colorInk)
	styleAlert  = lipgloss.NewStyle().Foreground(colorDanger).Bold(true)
	stylePanel  = lipgloss.NewStyle().Foreground(colorInk).Background(colorPanel)
)

// # 排版工具：宽度一律走 x/ansi
//
// ★ 不自己数 rune：中文是全角，`len()` 与视觉宽度不是一回事。选 `x/ansi` 有
// 现成依据 —— 本仓 2026-09-26 做过探针：`x/ansi.StringWidth` 与旧界面用的
// Rich `cell_len` 在 147 条真实对象上**逐字符 0 分歧**。照它排版，新旧界面的
// 对齐才是同一套口径。

// reasonOf 从一段（可能是多行的）失败文本里取出**该给玩家看的那一行**。
//
// 取法：有 `★` 就取含 `★` 的第一行（本仓约定：`★` 标住的是结论那一句，后面几行是细节），
// 否则退到**第一行非空内容**；整段都是空的才给一句具名的占位。
//
// ★ 为什么不用 `firstLineWith`（那个在 `selftest.go` 里）：它找不到针时返回的是
// "（没找到含 X 的行）" —— 那是**给写判据的人看的诊断**，不是给玩家看的话。拿它去填
// 提示就会把真正的原因整句丢掉。实测过：扫码失败时界面上写的是
// "★ 登录失败：（没找到含 ★ 的行）"，而桥明明说了"二维码已过期"（`phase=failed` 时
// 那句文本本来就不带 ★）。这正是本仓口径里"原因不许丢"要拦的东西。
func reasonOf(s string) string {
	first := ""
	for _, ln := range strings.Split(s, "\n") {
		t := strings.TrimSpace(ln)
		if first == "" && t != "" {
			first = t
		}
		if strings.Contains(ln, "★") {
			return t
		}
	}
	if first == "" {
		return "（对方没有给出说明）"
	}
	return first
}

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

// # 搜索框（列表屏头顶那一个）
//
// Python 侧有两处：章节屏 `Input #kw`（`app.py:1222`）与关卡屏 `Input #kw`
// （`app.py:1430`），行为一致 —— **边打边筛**、匹配是「折半角 ＋ 忽略大小写的
// **字面量**子串」。`check_tui.py` 还钉了一条：输全角 `ＡＣＴ５４ＳＩＤＥ`
// 必须筛出 `act54side`（中文输入法全角模式是常态，不归一的话用户按了也白按）。
//
// ★ 抽成一份共用：两个屏各写一份筛选口径，迟早会漂（本仓的老毛病）。
//
// ★ **零值可用**：`filterBox{}` 第一次用时自己初始化 —— 于是
// `&chapterScreen{}`／`&stageScreen{}` 这些既有构造点一个都不用改，
// 判据里那些直接构造屏的地方也不会因为漏调构造函数而崩。
type filterBox struct {
	in    textinput.Model
	ready bool
}

func (f *filterBox) ensure() {
	if f.ready {
		return
	}
	in := textinput.New()
	in.Prompt = ""
	in.Placeholder = "输关键词筛（Esc 清空）"
	in.CharLimit = 64
	in.Focus()
	*f = filterBox{in: in, ready: true}
}

// key 把一次按键交给输入框（只有它认得的那几种才吃：可打印字符、退格、左右）。
func (f *filterBox) key(k tea.KeyMsg) tea.Cmd {
	f.ensure()
	var cmd tea.Cmd
	f.in, cmd = f.in.Update(k)
	return cmd
}

func (f *filterBox) text() string {
	f.ensure()
	return f.in.Value()
}

func (f *filterBox) clear() {
	f.ensure()
	f.in.SetValue("")
	f.in.CursorEnd()
}

// match 是**唯一的筛选口径**：关键词与候选都折半角、忽略大小写，做字面量子串匹配。
//
// 空关键词一律命中（等于不筛）—— 与 Python 的 `Input` 初值行为一致。
// 多个候选字段之间是**或**（章节屏给 key／title／subtitle，关卡屏给
// code／name／level_id／zone_id，与 `StageFilter.Keyword` 的四列同口径）。
func (f *filterBox) match(fields ...string) bool {
	f.ensure()
	kw := strings.ToUpper(narrowHalf(strings.TrimSpace(f.in.Value())))
	if kw == "" {
		return true
	}
	for _, s := range fields {
		if strings.Contains(strings.ToUpper(narrowHalf(s)), kw) {
			return true
		}
	}
	return false
}

func (f *filterBox) view(c *appCtx) string {
	f.ensure()
	f.in.Width = max(20, c.w-4)
	return styleKey.Render("> ") + f.in.View()
}

// # 可点的一排标签（命中表）
//
// 对应参照实现的 `PickerRow`（`ak_tactic/tui/app.py:1599-1763`）的四件：
// `_layout`（怎么排）／`_boxes`（每项占哪几格）／`_hit`（点在哪一项上）／
// `on_click`（点中之后干什么）。
//
// 为什么非要有它：那一排分类标签在旧界面里是**鼠标操作的入口**
// （`tools/check_tui.py:1932` 的原文写着「**鼠标**：点分类行上的某一项
// （**博士是拿鼠标挑的**）」）。bubbletea 不白送命中测试 —— 每项落在哪几列，
// 只有画的时候知道 ⇒ **画的时候把格子记下来**，点击时按内容坐标查表。
//
// ★ 布局与画图**共用同一个循环**：参照实现踩过一次真 bug —— `_layout` 按 gap
// 推进坐标、`render()` 却没把那几格空格写进 Text，于是 `_boxes` 越往右偏得越多
// （第 k 项偏 k*gap 列），**点左边几项就点错人**（`check_tui.py:1822-1838` 记着）。
// 这里把"拼这一行"与"记这一格"写在一起，物理上不给它们分叉的机会。
type hitBox struct {
	line, x, w, idx int //: 行、起始列、宽（都是**这一屏 body 内**的内容坐标）
}

type hitRow struct{ boxes []hitBox }

// hit 把 body 内的（行, 列）换算成命中的项下标；没命中返回 -1。
func (h hitRow) hit(line, x int) int {
	for _, b := range h.boxes {
		if b.line == line && x >= b.x && x < b.x+b.w {
			return b.idx
		}
	}
	return -1
}

// renderHitRow 画出「一排标签」并**同时**记下每项的格子。
//
// `topLine` 是这一排**在 body 里的起始行**（调用方给，省得它自己加偏移时算错）。
// `width` 是可用宽度，超出就折到下一行 —— 折行后第二行上的项**照样点得到**
// （格子带着自己的行号，那正是 `_hit` 认行号的理由）。
// 每项两侧各留一格空格，并把这一格也算进它的命中框（点在名字旁边的空格上也算）：
// 「缝」是这类控件最容易出问题的地方 —— 点上去没反应的列会让人觉得"点不动"。
func renderHitRow(items []string, cursor, width, topLine int) (string, hitRow) {
	row := hitRow{boxes: make([]hitBox, 0, len(items))}
	if width < 8 {
		width = 8
	}
	var b strings.Builder
	line, col := topLine, 0
	for i, it := range items {
		cell := " " + it + " "
		w := ansi.StringWidth(cell)
		if col > 0 && col+w > width {
			b.WriteString("\n")
			line++
			col = 0
		}
		if i == cursor {
			b.WriteString(styleCursor.Render(cell))
		} else {
			b.WriteString(stylePanel.Render(cell))
		}
		row.boxes = append(row.boxes, hitBox{line: line, x: col, w: w, idx: i})
		col += w
	}
	return b.String(), row
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
	BorderForeground(colorCyan).
	Foreground(colorInk).
	Padding(1, 2).
	Width(66)
