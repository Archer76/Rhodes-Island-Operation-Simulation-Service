package main

import (
	"fmt"
	"strconv"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

// # AskScreen：通用的一问一答（对应 Python 的 `AskScreen`，`app.py:535`）
//
// **只问，不做事** —— 按下的那一行把「值」原样回给调用方，按 Esc 回 nil。
//
// 为什么做成通用的：本项目有两处要问（「不登录？本次还是以后都不」、「确认退出账号？」），
// 它们除了文字完全同构。各写一个屏，迟早会把「Esc 是什么意思」写飘一处 ——
// 而「取消」的语义漂了，是要出事的那种漂。
//
// ## 选项画在正文里，不画在 Footer
//
// 选项**本身就是问题的一部分**（「1　本次不登录」读起来是一句话），不是附加的动作
// 提示；所以 Footer 只留 `Esc 返回`，编号列在正文里。两处都印一遍，就是博士指出过的
// 「底部两行一样的东西」。
//
// ## 全角数字也认
//
// `1`–`9` 的比较走 `keyIs`，它比较前统一折半角 —— 中文输入法全角模式下送来的是
// `１`，不折就选不动（Python 侧靠 `both_cases()` 补全角孪生，两边到此行为一致）。

type askRow struct{ value, label string }

type askScreen struct {
	heading string
	body    string
	rows    []askRow
}

func newAskScreen(heading, body string, rows []askRow) *askScreen {
	return &askScreen{heading: heading, body: body, rows: rows}
}

func (*askScreen) title() string { return "询问" }
func (*askScreen) isModal() bool { return true }
func (*askScreen) help() string  { return "1–9 选择 · Esc 返回" }

func (s *askScreen) view(c *appCtx) string {
	inner := []string{styleTitle.Render(s.heading)}
	if s.body != "" {
		inner = append(inner, "", styleDim.Render(s.body))
	}
	inner = append(inner, "")
	for i, r := range s.rows {
		inner = append(inner,
			fmt.Sprintf("  %s　%s", styleTitle.Render(strconv.Itoa(i+1)), r.label))
	}
	return centerBlock(boxStyle.Render(strings.Join(inner, "\n")), c.w, c.h)
}

func (s *askScreen) update(_ *appCtx, k tea.KeyMsg) (screen, action) {
	if keyIs(k, "esc") {
		return s, action{kind: actBack} //: res 留 nil ⇒ 取消（与「选了一个空串」区分开）
	}
	//: 编号越界或没有这一行 ⇒ **什么都不做**（照 Python 的 `action_pick`）
	for i := range s.rows {
		if keyIs(k, strconv.Itoa(i+1)) {
			return s, action{kind: actBack, res: s.rows[i].value}
		}
	}
	return s, action{kind: actNone}
}
