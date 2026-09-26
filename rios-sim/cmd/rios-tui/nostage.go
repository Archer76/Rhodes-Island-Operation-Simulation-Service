package main

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

// noStageScreen 对应 Python 的 `NoStageScreen`：关卡表是空的。
//
// 原注释一句话说清了这一屏的判据：**给一句能照做的话，不是一句"没有数据"。**
// 所以正文里带着命令、代价与失败时的行为（"取不到时它会明确报…并保留上一版表"）。
type noStageScreen struct{}

func (noStageScreen) title() string { return "关卡数据" }

func (noStageScreen) help() string { return "Esc 返回 · Q 退出" }

func (noStageScreen) view(*appCtx) string {
	var b strings.Builder
	b.WriteString(styleTitle.Render("关卡名获取失败") + "\n\n")
	b.WriteString("本地库里的关卡表是空的，选不了关卡。\n\n")
	b.WriteString("取一次（要联网，约 7 MB / 十秒上下）：\n")
	b.WriteString("    python -m ak_tactic db stage-fetch\n\n")
	b.WriteString(styleDim.Render("取不到时它会明确报「关卡名获取失败」，并保留上一版表。"))
	return b.String()
}

func (noStageScreen) update(_ *appCtx, k tea.KeyMsg) (screen, action) {
	switch {
	case keyIs(k, "esc"), keyIs(k, "backspace"):
		//: 原注释：这一屏是「关卡表空」的提示，**不该把人逼到只剩退出**。
		return nil, action{kind: actBack}
	case keyIs(k, "q"):
		return nil, action{kind: actQuit}
	}
	return nil, action{kind: actNone}
}
