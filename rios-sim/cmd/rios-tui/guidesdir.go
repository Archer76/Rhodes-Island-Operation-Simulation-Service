package main

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
)

// guidesDirScreen 对应 Python 的 `GuidesDirScreen`（`app.py:503-534`）：
// 「可跳过的『重设默认目录』。Esc 不改就回去。」
//
// 输入框用 `bubbles/textinput` —— 它对应 Python 那边的 textual `Input`
// （Python 特意派生了 `PathInput` 只为把 Tab 挂上，因为 `Input` 自己不占 Tab；
// 注释还记着那条坑：**不设 priority 的话 Tab 会先被屏幕的焦点切换抢走，按下毫无反应**。
// bubbletea 这边没有"焦点链"这回事，Tab 天然归屏自己处理，所以那条坑不存在）。
type guidesDirScreen struct {
	in    textinput.Model
	cands []string
}

func newGuidesDirScreen(c *appCtx) *guidesDirScreen {
	in := textinput.New()
	in.Prompt = ""
	in.SetValue(c.guidesDir)
	in.CursorEnd()
	in.Focus()
	in.CharLimit = 1024
	return &guidesDirScreen{in: in}
}

func (*guidesDirScreen) title() string { return "改目录" }

func (*guidesDirScreen) help() string {
	return "Tab 补全 · Enter 确定 · Esc 返回（不修改）"
}

func (s *guidesDirScreen) view(c *appCtx) string {
	var b strings.Builder
	b.WriteString(styleTitle.Render("数据目录") + "\n")
	b.WriteString(styleDim.Render("MAA 作业的输出根目录。默认在**本工具根目录**下的 Guides/。") + "\n")
	b.WriteString(styleDim.Render("按 Tab 补全路径；留空或按 Esc 则不修改。") + "\n\n")
	s.in.Width = max(20, c.w-4)
	b.WriteString("> " + s.in.View() + "\n\n")
	if len(s.cands) > 0 {
		n := min(12, len(s.cands))
		more := ""
		if len(s.cands) > 12 {
			more = fmt.Sprintf("　…（共 %d 项）", len(s.cands))
		}
		b.WriteString(styleDim.Render("候选："+strings.Join(s.cands[:n], "　")+more) + "\n")
	}
	return b.String()
}

func (s *guidesDirScreen) update(_ *appCtx, k tea.KeyMsg) (screen, action) {
	switch k.String() {
	case "esc":
		return s, action{kind: actBack} // 带回 nil ⇒ 「不修改」
	case "tab":
		//: 照 Python 的 `PathInput.action_complete`：先补全，再把候选交回界面。
		//: 补全之后光标必须移到行尾 —— 否则接着打会插到路径中间。
		nt, cands := completeDir(s.in.Value(), "")
		if nt != s.in.Value() {
			s.in.SetValue(nt)
			s.in.CursorEnd()
		}
		s.cands = cands
		return s, action{kind: actNone}
	case "enter":
		raw := strings.TrimSpace(s.in.Value())
		if raw == "" {
			return s, action{kind: actBack} // 「留空……则不修改」
		}
		return s, action{kind: actBack, res: expandUser(raw)}
	}
	var cmd tea.Cmd
	s.in, cmd = s.in.Update(k)
	_ = cmd
	return s, action{kind: actNone}
}

// onGuidesDirChosen 是改目录屏的回调：写配置，并刷新上一屏那一栏。
func onGuidesDirChosen(r *root, res any) {
	p, _ := res.(string)
	if p == "" {
		r.ctx.note = "数据目录未修改"
		return
	}
	if err := saveConfig("guides_dir", p); err != nil {
		//: ★ 具名失败。Python 那边这里是把 `OSError` **吞掉**的（写不进去一声不响），
		//: 于是界面照旧显示"已改"，下次启动又变回旧值 —— 静默退化比失败更坏。
		r.ctx.note = "★ 保存失败：" + err.Error()
		return
	}
	r.ctx.guidesDir = p
	r.ctx.note = "数据目录已改为 " + p
}
