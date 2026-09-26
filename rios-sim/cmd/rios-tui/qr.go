package main

import (
	"errors"
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/x/ansi"
)

// # QrScreen：扫码用的**全屏居中**二维码（对应 Python 的 `QrScreen`，`app.py:588`）
//
// ## 为什么单独一屏
//
// Python 那边原先二维码是登录屏里的一块 `Static`，被上下几个块挤着，高度不够就被
// 裁掉一截 —— 博士实测「显示不完整扫不了」。二维码**缺一个角就彻底作废**，不能靠
// 「大概看得见」来交付。所以它独占一屏、居中、尺寸随内容自适应。
//
// ## 矩阵从哪来：Python 给矩阵，Go 负责画
//
// 编码（文本 → 模块矩阵）仍由 Python 的 `ak_tactic.qrterm.matrix` 走 `qrcode` 库做，
// 桥上把它当 `qr_matrix`（每行一串 `0`/`1`）发过来 —— 与 Python 用的**同一份编码器**，
// Go 侧不引第二个二维码实现（两份编码器迟早会漂，而二维码画错是「扫不出来」，最难查的
// 那类症状）。**画法**这一层是界面的事，所以留在 Go：静默区怎么挑、半格怎么拼、
// 颜色怎么给。
//
// ## 静默区按规范给足
//
// 二维码四周必须有**至少 4 格纯白静默区**，否则识别率骤降。终端里 2 格通常够用
// （终端本身有行距），但既然空间允许就给足 4 格；屏幕实在小的时候才逐级退让
// （见 `pickQRBorder`）—— **宁可小一点，也不能缺角**。
//
// ## 颜色显式给，不靠终端主题
//
// `qrterm.py` 的文件头记着理由：只画「暗格填块、亮格留空」的写法**只在深色终端上
// 扫得出来**，浅色终端上极性正好反了。所以这里逐格给前景/背景色（黑 16 / 白 231），
// 与终端主题无关。

// : 256 色板里的纯黑与纯白。
const (
	qrBlack = 16
	qrWhite = 231
)

// : 半格块。Python 用 U+2584（▄ 下半块）而不是 U+2580，理由是**U+2580 编码不进
// : cp936**（本机控制台是 GBK，打印它会当场 UnicodeEncodeError）。Go 侧写 UTF-8
// : 不受这条限制，但**字形必须一致** —— 同一个码在两边长得不一样是不能接受的。
const qrLowerHalf = "▄"

// qrMatrixFromRows 把桥给的 `['0101…', …]` 解析成布尔矩阵（true = 暗格）。
//
// 三条检查都是「早点红」而不是防御性编程：矩阵不是方的、或混进别的字符，画出来的
// 是一个**看着像二维码**的废图 —— 那种错最难发现（人只会觉得"扫不出来"）。
func qrMatrixFromRows(rows []string) ([][]bool, error) {
	if len(rows) == 0 {
		return nil, errors.New("二维码矩阵是空的（桥没给 qr_matrix）")
	}
	n := len(rows[0])
	if n == 0 {
		return nil, errors.New("二维码矩阵首行是空的")
	}
	out := make([][]bool, 0, len(rows))
	for i, r := range rows {
		if len(r) != n {
			return nil, fmt.Errorf("二维码矩阵第 %d 行 %d 格，首行 %d 格 —— 不是方的（一折就废）",
				i, len(r), n)
		}
		row := make([]bool, n)
		for x := 0; x < n; x++ {
			switch r[x] {
			case '1':
				row[x] = true
			case '0':
			default:
				return nil, fmt.Errorf("二维码矩阵第 %d 行第 %d 格是 %q，只认 0/1", i, x, r[x])
			}
		}
		out = append(out, row)
	}
	return out, nil
}

// withQuiet 在四周补静默区。
//
// Python 把 `border=b` 交给 `qrcode` 库（库在四周补亮格），效果与这里补 `false`
// 完全一样 ⇒ 两边矩阵逐格相同。
func withQuiet(m [][]bool, b int) [][]bool {
	if b <= 0 || len(m) == 0 {
		return m
	}
	n := len(m[0]) + 2*b
	blank := make([]bool, n)
	out := make([][]bool, 0, len(m)+2*b)
	for i := 0; i < b; i++ {
		out = append(out, append([]bool(nil), blank...))
	}
	for _, row := range m {
		line := make([]bool, n)
		copy(line[b:], row)
		out = append(out, line)
	}
	for i := 0; i < b; i++ {
		out = append(out, append([]bool(nil), blank...))
	}
	return out
}

// pickQRBorder 复刻 Python 的 `QrScreen._pick_border`：在「放得下」的前提下取最大的
// 静默区，优先级 4 → 0。
//
// `matrix(border=b)` 的边长是 `模块数 + 2b`，画成 `▄` 后占 `ceil(边长/2)` 行、`边长` 列。
// 中心区只放二维码，所以要给出去的只有：框的上下边框 2 行、贴底状态行 2 行、
// 左右各留 2 列余量 —— 这就是 `-4` 的来路。**这四个数是从 Python 那份实现搬来的，
// 不随手改**；改了两边就不对等了。
func pickQRBorder(base, w, h int) int {
	availRows := h - 4
	if availRows < 1 {
		availRows = 1
	}
	availCols := w - 4
	if availCols < 1 {
		availCols = 1
	}
	for _, b := range []int{4, 3, 2, 1, 0} {
		side := base + 2*b
		if side <= availCols && (side+1)/2 <= availRows {
			return b
		}
	}
	return 0
}

// renderQR 复刻 Python 的 `_render_ansi`：两行压成一行半格。
//
// `▄` 画的是**下半格** ⇒ 前景取下格的颜色、背景取上格的颜色。行数为奇数时最后一行
// 的下半格当作亮格（Python：`[False] * len(top)`）。
func renderQR(m [][]bool) []string {
	out := make([]string, 0, (len(m)+1)/2)
	for y := 0; y < len(m); y += 2 {
		top := m[y]
		var b strings.Builder
		for x := range top {
			low := false
			if y+1 < len(m) {
				low = m[y+1][x]
			}
			fg, bg := qrWhite, qrWhite
			if low {
				fg = qrBlack
			}
			if top[x] {
				bg = qrBlack
			}
			fmt.Fprintf(&b, "\x1b[38;5;%d;48;5;%dm%s", fg, bg, qrLowerHalf)
		}
		b.WriteString("\x1b[0m")
		out = append(out, b.String())
	}
	return out
}

// centerEachLine 把每一行居中（Python 的 `text-align: center`）。
func centerEachLine(s string, w int) string {
	lines := strings.Split(s, "\n")
	for i, ln := range lines {
		if x := ansi.StringWidth(ln); x < w {
			lines[i] = strings.Repeat(" ", (w-x)/2) + ln
		}
	}
	return strings.Join(lines, "\n")
}

type qrScreen struct {
	matrix [][]bool
	base   int
	note   string
}

func newQrScreen(m [][]bool, note string) *qrScreen {
	if note == "" {
		note = "等待扫码……"
	}
	return &qrScreen{matrix: m, base: len(m), note: note}
}

func (*qrScreen) title() string { return "扫码登录" }
func (*qrScreen) isModal() bool { return true }
func (*qrScreen) help() string  { return "Esc 返回" }

// setNote 换掉贴底那行提示（登录屏轮询到「已扫码」时要改它）。
//
// Python 那边是 `set_note()` ＋ `query_one("#qr-note")`；Go 里屏是**我们自己持有的
// 实例**（见 `stack.go` 的登记），所以登录屏拿着这个指针直接改就行，不必重建一屏。
func (s *qrScreen) setNote(text string) { s.note = text }

func (s *qrScreen) view(c *appCtx) string {
	b := pickQRBorder(s.base, c.w, c.h)
	lines := renderQR(withQuiet(s.matrix, b))
	box := lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).Padding(0, 1).
		Render(strings.Join(lines, "\n"))
	note := s.note
	if b < 4 {
		//: 静默区被压过就说出来：与其让人对着扫不出的码发愣，不如直接告诉他
		//: 「把窗口拉大点就能扫」（Python 的同一句话）。
		note += fmt.Sprintf("\n终端偏小，静默区已压到 %d 格——扫不出来的话把窗口拉大一点再按 L。", b)
	}
	//: 图占中间、提示贴底（照 Python 的 `#qr-note { dock: bottom }`）
	body := centerBlock(box, c.w, c.h-2)
	return body + "\n" + centerEachLine(note, c.w)
}

func (s *qrScreen) update(_ *appCtx, k tea.KeyMsg) (screen, action) {
	if keyIs(k, "esc") {
		return s, action{kind: actBack}
	}
	return s, action{kind: actNone}
}
