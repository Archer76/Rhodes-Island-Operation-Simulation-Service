package main

import (
	tea "github.com/charmbracelet/bubbletea"

	"rios-sim/data"
)

// # 屏栈：与 Python 侧 `RiosApp.push_step/step_back` 同构
//
// Python 那边的来路写得很清楚（`app.py:2515-2551`）：向导里按 Esc 要退回上一层，
// 所以每推一屏都要把「怎么把它重建出来」记进一条**路径**；退回时丢掉尾巴、
// 把新的尾巴重新推出来。
//
// Go 这边不需要「重建」这一步 —— Textual 的 Screen 被 dismiss 之后不能复用，
// 而 bubbletea 里我们自己持有实例，**弹栈即回到上一屏**。所以这里存的是
// **屏实例 ＋ 它关闭时要回调的那个函数**，比 Python 少一次重建。
//
// ★ 登记一处行为差异：Python 退回上一层拿到的是**一张新屏**（光标回到顶上），
// 我们是**原来那一张**（光标位置保留）。哪个对要等判据说话；先记在这里，
// 不让它变成「以为两边一样」。

// screen 是一屏。`update` 返回「下一屏」与「这一屏想干什么」。
type screen interface {
	title() string
	help() string
	view(c *appCtx) string
	update(c *appCtx, k tea.KeyMsg) (screen, action)
}

// modal 是「不算一步」的屏 —— 对应 Python 的 `ModalScreen`（AskScreen / QrScreen）。
//
// 两条要照做，否则就是可见的行为差：
//   - **不进面包屑**：Python 的步骤条只记向导的路径，模态屏盖在上面但不占一格。
//   - **独占整屏**：Textual 的 ModalScreen 会连顶栏一起盖住，底下的屏不参与绘制。
//     我们这边若照常画顶栏，观感就变成「一屏挤在另一屏的下半截」。
type modal interface{ isModal() bool }

func isModalScreen(s screen) bool {
	m, ok := s.(modal)
	return ok && m.isModal()
}

type actKind int

const (
	actNone actKind = iota
	actBack         // 退回上一层（Esc）
	actPush         // 压一屏（带回调）
	actQuit
)

type action struct {
	kind actKind
	res  any              // actBack 带回给上一屏的结果
	push screen           // actPush 的目标屏
	done func(*root, any) // actPush 的关屏回调
}

// appCtx 是整个向导共享的一份状态。照 Python 的 `State`，只留现在已经用得到的那些；
// 名册、计划、解算结果等后面按需加，不预先摆一堆没人读的字段。
type appCtx struct {
	stages   []data.StageRecord
	zones    []data.ZoneRecord
	chapters []data.Chapter

	w, h int // 当前窗口尺寸（矮窗口降级要用）

	dataDir   string // 实际在用的数据目录（RIOS_DB 解析出来的那个）
	guidesDir string // Guides 导出目录；空 = 还没设置
	note      string // 上一屏带回的一句话，显示一帧

	//: 这一轮选到哪了。指针指向 stages/chapters 里的元素，不复制。
	chapter *data.Chapter
	part    *data.ChapterPart
	envs    []data.ZoneEnv
	env     string
	stage   *data.StageRecord

	//: [2] 选编队那一段。名册来自 Python 桥（`engclient.go`，只取一次）；
	//: 取不到时 `rosterErr` 里是**原因全文**，选人屏只画它的第一行。
	roster    *rosterData
	rosterErr string

	//: 这一关的**可部署人数**（Python 的 `State.deploy_limit`，来自 gamedata 的
	//: `options.characterLimit`）。**0 = 取不到**。★ 口径 3（2026-09-26）：它现在
	//: **只用来显示**（选人屏那行「槽位 N 人／槽位：未知」），**不参与**那条拦截的
	//: 判定 —— 守卫 `solveGate` 的签名里没有它。见 `squad.go` 文件头。
	deployLimit int

	//: 「不用，让程序自己挑」这条路**程序挑出来的编队**。守卫的自动分支判的就是它
	//: （口径 2：自动编队同样拦）。搜索层还没接进来 ⇒ 运行期它是空的（nil），
	//: 于是自动路走「空编队放行」那条分支；自检显式填一个全员低练度的来行使
	//: `gateBlockAuto`。填它的地方将来是搜索层／解算屏，**不是**第二处判定。
	autoPicks []RosterOperator

	//: 已确定的编队（干员名）与模式（`auto` 允许程序补充 / `only` 只用我选的）。
	//: 照 Python 的 `State.squad` 与 `State.mode`。
	squad []string
	mode  string
}

type frame struct {
	scr  screen
	done func(*root, any)
}

type root struct {
	ctx   *appCtx
	stack []frame
	quit  bool
}

func newRoot(c *appCtx, first screen) *root {
	r := &root{ctx: c}
	r.stack = []frame{{scr: first}}
	return r
}

func (r *root) top() screen { return r.stack[len(r.stack)-1].scr }

func (r *root) push(s screen, done func(*root, any)) {
	r.stack = append(r.stack, frame{scr: s, done: done})
}

// pop 弹掉顶上那一屏，并把结果交给它的回调。
//
// ★ 最底层不退：栈里只剩一屏时 pop 是空操作 —— 否则一按 Esc 就退出程序，
// 而本仓的口径是「最外层按 Esc 什么都不做，退出是 q」。
func (r *root) pop(res any) {
	if len(r.stack) <= 1 {
		r.ctx.note = "已经在最外层（按 q 退出）"
		return
	}
	f := r.stack[len(r.stack)-1]
	r.stack = r.stack[:len(r.stack)-1]
	if f.done != nil {
		f.done(r, res) // 回调里可以再 push（照 Python 的 back_to_step）
	}
}

func (r *root) Init() tea.Cmd { return nil }

func (r *root) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		r.ctx.w, r.ctx.h = msg.Width, msg.Height
		return r, nil
	case tea.KeyMsg:
		//: ctrl+c 在任何屏都退，且不走屏自己的键表（与 Python 的 App 级绑定一致）。
		if msg.String() == "ctrl+c" {
			return r, tea.Quit
		}
		next, act := r.top().update(r.ctx, msg)
		if next != nil {
			//: 屏可以就地换掉自己（例如「没有关卡」这种终态）。
			r.stack[len(r.stack)-1].scr = next
		}
		switch act.kind {
		case actQuit:
			return r, tea.Quit
		case actBack:
			r.pop(act.res)
		case actPush:
			r.push(act.push, act.done)
		}
	}
	return r, nil
}

func (r *root) View() string {
	if len(r.stack) == 0 {
		return ""
	}
	top := r.top()
	if isModalScreen(top) {
		//: 模态屏**独占整屏**：不画顶栏与面包屑（对应 Textual 的 ModalScreen
		//: 把底下的屏连顶栏一起盖住）。它自己的 help 印在最底下。
		return top.view(r.ctx) + "\n" + styleDim.Render(top.help()) + "\n"
	}
	head := ""
	if r.ctx.h == 0 || r.ctx.h >= tinyHeight {
		head = styleTitle.Render("R.I.O.S. 作战演算") + "  " +
			styleCrumb.Render(r.crumb()) + "\n"
	}
	body := top.view(r.ctx)
	foot := styleDim.Render(r.help())
	if r.ctx.note != "" {
		foot += "\n" + r.ctx.note
	}
	return head + "\n" + body + "\n" + foot + "\n"
}

// crumb 是面包屑：把栈里各屏的标题串起来（对应 Python 的步骤条 `theme.step_bar`）。
//
// 模态屏**不进面包屑** —— 它不算向导里的一步（见 `modal`）。
func (r *root) crumb() string {
	out := make([]string, 0, len(r.stack))
	for _, f := range r.stack {
		if isModalScreen(f.scr) {
			continue
		}
		out = append(out, f.scr.title())
	}
	return joinArrow(out)
}

func (r *root) help() string { return r.top().help() }

// 矮窗口的两道阈值照 Python 的屏基类来（`app.py:219-223`）：它们是**量出来的**，
// 不是估的 —— 原注释写明 `_proto/small_window_audit.py` 逐屏逐档核对过
// 「不滚动就要看得见」，`tools/check_tui.py` 的 `check_small_window()` 把同一套
// 判据钉进自检。所以这三个数不许随手改。
const (
	compactHeight = 22 // 以下：收掉块的边框与内边距（内容优先）
	tinyHeight    = 16 // 以下：连顶栏也收掉（顶栏印的是服务名与时钟，是装饰）
)
