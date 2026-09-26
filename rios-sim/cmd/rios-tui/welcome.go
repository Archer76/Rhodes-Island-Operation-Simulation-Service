package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"rios-sim/data"
)

// 照 `ak_tactic/tui/theme.py:10-11` 抄（不是重写）。
const (
	appTitle    = "R.I.O.S. 罗德岛作战演算服务"
	appSubtitle = "Rhodes Island Operation Simulation Service"
)

// welcomeShortHeight 照 Python 的 `WelcomeScreen.SHORT_HEIGHT = 11`。
//
// ★ 这个数是**量出来的**，不是估的：原注释记着博士报过「主界面只看得见四行标题」，
// 用 `_proto/home_fold.py` 实测 80x20 时名册那句落在 y=20、窗口只有 0–19。
// 修掉根因（`height: auto`）之后这一屏 11 行就装得下，阈值才降到"只剩标题可收"。
const welcomeShortHeight = 11

// welcomeScreen 是 [0] 准备：数据目录在哪、名册从哪来、当前登录的是哪个号。
//
// 这一屏是别人第一次跑起来看到的东西 —— 所以 Python 原注释那条口径要照办：
// **任何一栏取不到，也要把原因写在那一栏里，绝不留空白**。空白分不清
// 「没登录」「没有名册」还是「代码在这台机器上挂了」。
type welcomeScreen struct{}

func (welcomeScreen) title() string { return "准备" }

func (welcomeScreen) help() string {
	return "Enter 开始 · D 改目录 · L 登录 · Q 退出"
}

func (welcomeScreen) view(c *appCtx) string {
	var b strings.Builder
	//: 矮窗口下**先收标题块**：优先级是明写的 —— 数据 > 标题。
	//: 服务名顶栏也印着，而数据目录与登录状态才是他每次来这一屏要看的东西。
	if c.h == 0 || c.h >= welcomeShortHeight {
		b.WriteString(styleTitle.Render(appTitle) + "\n")
		b.WriteString(styleCrumb.Render(appSubtitle) + "\n\n")
	}
	b.WriteString(styleTitle.Render("数据目录") + "\n" + c.dirLine() + "\n\n")
	b.WriteString(styleTitle.Render("登录账号") + "\n" + c.accountLine() + "\n" + c.dataLine())
	return b.String()
}

func (welcomeScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	switch {
	case keyIs(k, "enter"):
		//: 对应 Python 的 `action_go → app.goto_stage_pick()`。
		//: ⚠ 回调必须是 `onChapterPicked`（选章屏关屏时把选中的章交回来），
		//: 不是 `onStagePicked` —— 挂错的症状是「回车进选章之后再回车毫无反应」，
		//: 而这条正是 `-selftest` 第五段抓出来的。
		return nil, action{kind: actPush, push: c.stagePickScreen(), done: onChapterPicked}
	case keyIs(k, "d"):
		c.note = "改目录（GuidesDir 屏）尚未实现：它要子进程列目录 ＋ PathInput 的 tab 补全，" +
			"而 check_tui.py 里那套补全判据也要一起搬 —— 排在下一刀"
		return nil, action{kind: actNone}
	case keyIs(k, "l"):
		c.note = "登录屏尚未实现：它走 Python 子进程（§11.4 的三条约束已定），尚未接线"
		return nil, action{kind: actNone}
	case keyIs(k, "q"):
		return nil, action{kind: actQuit}
	}
	return nil, action{kind: actNone}
}

// dirLine 对应 Python 的 `_dir_line`：**当前正在用的 Guides 目录**，两行。
//
// ⚠ 现在还没接线：那个目录存在 TUI 的配置里，读配置与写配置都走 Python 那侧。
// 所以这里**具名说出"还没接"**，而不是印一个看起来像真值的默认路径 ——
// 后者会让人以为自己的设置没生效。
func (c *appCtx) dirLine() string {
	if c.guidesDir == "" {
		return styleDim.Render("（尚未接入：Guides 目录存在配置里，读写配置走 Python 子进程那条路）")
	}
	out := c.guidesDir + "\n" + styleDim.Render("MAA 作业输出到 "+
		filepath.Join(c.guidesDir, "<关卡名>"))
	if st, err := os.Stat(c.guidesDir); err != nil || !st.IsDir() {
		out += styleDim.Render("　（这个目录还不存在，导出时自动建）")
	}
	return out
}

// accountLine 对应 `_account_line`。登录态同样走 Python 子进程，尚未接线 ⇒ 具名说清。
func (c *appCtx) accountLine() string {
	return styleDim.Render("（登录尚未接入：按 L 的登录屏还没做）")
}

// dataLine 对应 `_data_line` 里**干员库那一半**。
//
// 这一半现在就能真取到 —— 而且它顺带就是启动器自检的第一项（§12.3：
// 缺件要具名报错，不许静默跑出一个空列表）。取不到时给出的处置是**具名**的：
// 说清是缺库、还是库在而读不出来，并给出重建命令。
func (c *appCtx) dataLine() string {
	n, err := data.OperatorCount()
	if err == nil {
		return fmt.Sprintf("干员库：已获取（%s %d 名）",
			filepath.Base(data.DBPath("akdb")), n)
	}
	return fmt.Sprintf("干员库：未获取（%v）　先跑 python -m ak_tactic db build", err)
}
