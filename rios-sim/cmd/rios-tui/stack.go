package main

import (
	"encoding/json"

	tea "github.com/charmbracelet/bubbletea"

	"rios-sim/data"
	"rios-sim/mechanisms"
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
	actNone  actKind = iota
	actBack          // 退回上一层（Esc）
	actPush          // 压一屏（带回调）
	actPopTo         // 连弹到**第一个满足条件的屏**（含它自己）—— 结果屏的 R／H 两个出口
	actQuit
)

type action struct {
	kind actKind
	res  any              // actBack 带回给上一屏的结果
	push screen           // actPush 的目标屏
	done func(*root, any) // actPush 的关屏回调
	//: 顺手要跑的一条命令（异步活儿：解算那一轮引擎调用）。屏自己拿不到 `tea.Cmd`
	//: 的出口 —— `update` 的返回值只有"下一屏"与"想干什么"。
	cmd tea.Cmd
	//: actPopTo 的判别式（照 Python 的 `goto_home` / `goto_stage_list`：退到哪一层）
	match func(screen) bool
}

// msgScreen 是「会收到异步消息」的屏：根模型把非按键消息交给栈里第一个实现它的屏。
//
// 为什么需要这个接口：一轮解算／一次扫码要跑几十秒到几分钟，界面线程绝不能被它卡住
// （卡住了连「中止」都按不动）⇒ 那活儿必须走 `tea.Cmd` 异步跑，回来是一条 `tea.Msg`。
// 而 `screen` 接口只有 `update(…, tea.KeyMsg)`，收不到它。
//
// 为什么给 `*root`：处理一条异步消息时，屏有时要**连动屏栈**（登录成功那一刻：先收掉
// 二维码那张码屏、再把自己弹回主界面并把一句话交给回调 —— 照 Python 的 `_done`）。
// 只给 `*appCtx` 的话屏改不动栈，只能把这件事拆成几次往返，而中间态是可见的。
//
// ★ 这条路径**只返回 action，不许就地换屏**（对比 `update` 的 `next`）。理由是自检抓到的
// 一次真崩溃：分派器原先照按键那条路的样子回写 `r.stack[i].scr = next`，而 `onMsg`
// 自己就可能弹栈（登录成功正是如此）—— 栈一短，那句回写就越界 panic，症状是
// **扫上了那一刻界面直接崩**。屏要换自己，就走压/弹栈（可见的栈操作），不要在消息里偷偷换。
type msgScreen interface {
	onMsg(r *root, msg tea.Msg) action
}

// mouseScreen 是「认鼠标」的屏。
//
// ★ 为什么单列一个接口、而不是改 `screen`：`screen` 的 `update` 是**编译期**只收
// `tea.KeyMsg` 的（14 个屏都实现了它）。把 `MouseMsg` 塞进同一个方法要动所有屏，
// 而绝大多数屏**不需要**认鼠标（纯文本屏点了也没意义）⇒ 用可选的窄接口：
// 认的屏实现它，不认的一个字节都不用改，而"这个屏认不认鼠标"在类型上一眼可见。
//
// ★ 也**不是** `msgScreen`：那个收的是**异步消息**（一轮解算回来、扫码结果），
// 语义与"用户在屏上点了一下"是两回事，混在一起两条链会互相干扰。
//
// ★ 坐标：`m.Y` 已被 `root.Update` 换算成**这一屏 body 内**的行号（终端坐标减掉
// 顶栏那几行）—— 屏自己不必知道顶栏在不在、占几行，那件事只有 `root` 知道。
type mouseScreen interface {
	onMouse(c *appCtx, m tea.MouseMsg) (screen, action)
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

	//: ---- 助战（口径 2026-09-26，见 `support.go` 文件头）----
	//:
	//: `useSupport` 是选人屏上那个开关，`supportName` 是挑中的那一位。
	//: 两者分开是为了屏上能显示「用（某某）」；**下游只认 `supportForSolve()`**
	//: （开关关掉 ⇒ 空串，名字留着也不算数）。
	useSupport  bool
	supportName string
	//: 这一轮的**编队上限**：不用助战 12、用助战 13（自己的 12 ＋ 助战 1，助战占一格）。
	//: 由 `setSupportUse` 维护 —— 屏上**不许写死**这个数（口径 1）。
	squadLimit int

	//: 解算结果（结果屏读它）。`plan`／`verdict` 是引擎给的原样 JSON，不在这里
	//: 重新解释 —— 那是 `solver.go` 与 `maa` 包的事。
	solveStatus       string
	solvePlaceholders []mechanisms.Gap // 完整列表；complete 时是被排除候选，不是最终计划缺口。
	solvePlan         json.RawMessage
	solveVerdict      json.RawMessage
	solveStars        int
	solveNote         string
	solveSteps        []solveStepView
	solveEvaluated    int
	solveSeconds      float64
	//: 最近一次导出的作业路径（结果屏把它显示出来 —— 玩家要靠它找到文件）。
	exportPath string
	//: 登录屏带回的一句话（显示在 `[0]` 屏的**账号行**上，照 Python 的 `_login_done`）。
	//: 它会说明"登的是新号还是登回了老号"——账号条数没变时，不说会让人以为多了个号。
	accountNote string
}

type frame struct {
	scr  screen
	done func(*root, any)
}

type root struct {
	ctx   *appCtx
	stack []frame
	quit  bool
	//: 回**调里**（`pop` 的 done 里）压屏时要求的命令先存这儿 —— 下一次 `Update`
	//: 的出口把它交出去。bubbletea 的 `Init` 只在程序启动时调一次，动态压的屏拿不到它。
	pending      tea.Cmd
	closedSolves []*solveTask
}

func (r *root) closeScreen(s screen) {
	if solve, ok := s.(*solveScreen); ok {
		solve.close()
		// Retain only unfinished process handles, not old screens and their logs.
		pending := r.closedSolves[:0]
		for _, task := range r.closedSolves {
			select {
			case <-task.exited:
			default:
				pending = append(pending, task)
			}
		}
		r.closedSolves = pending
		tasks := append([]*solveTask(nil), solve.retired...)
		if solve.task != nil {
			tasks = append(tasks, solve.task)
		}
		for _, task := range tasks {
			select {
			case <-task.exited:
			default:
				r.closedSolves = append(r.closedSolves, task)
			}
		}
	}
}

func (r *root) cancelTasks() {
	for _, f := range r.stack {
		if s, ok := f.scr.(*solveScreen); ok {
			s.close()
		}
	}
	for _, task := range r.closedSolves {
		task.cancel()
	}
}

func (r *root) shutdown() {
	r.cancelTasks()
	for _, f := range r.stack {
		if s, ok := f.scr.(*solveScreen); ok {
			s.waitClosed()
		}
	}
	for _, task := range r.closedSolves {
		<-task.exited
	}
	r.closedSolves = nil
}

func newRoot(c *appCtx, first screen) *root {
	r := &root{ctx: c}
	r.stack = []frame{{scr: first}}
	return r
}

func (r *root) top() screen { return r.stack[len(r.stack)-1].scr }

// bodyTop 是「当前这一屏的 body 从终端第几行开始」。
//
// 必须与 `View()` 的拼装**逐字对应**，否则鼠标点击会整体错行：
//
//	View = [顶栏 + "\n"] + "\n" + body + "\n" + foot + "\n"
//
// 顶栏在矮窗口下会被收掉（`tinyHeight`），所以这里要照着同一条判据算。
// ★ 这是"布局与命中必须共用同一份坐标"那条纪律的落点：`View` 一改，这里跟着改；
// 判据里有一条真点一次、断言筛出来的集合变了 —— 错行会当场红。
func (r *root) bodyTop() int {
	if r.ctx.h == 0 || r.ctx.h >= tinyHeight {
		return 2 //: 顶栏 1 行 ＋ 它后面那个空行
	}
	return 1 //: 没有顶栏，body 前面只有一个空行
}

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
	r.closeScreen(f.scr)
	r.stack = r.stack[:len(r.stack)-1]
	if f.done != nil {
		f.done(r, res) // 回调里可以再 push（照 Python 的 back_to_step）
	}
}

func (r *root) Init() tea.Cmd { return nil }

func (r *root) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmd tea.Cmd
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		r.ctx.w, r.ctx.h = msg.Width, msg.Height
		return r, nil
	case rosterMsg:
		//: ★ 2026-09-28：名册重取的应答由**根模型**接（名册是 `appCtx` 级状态，不属于
		//: 任何一屏；扫码登录成功后登录屏已弹掉，交给屏会没人接）。成功落进 ctx，
		//: 失败记进 `rosterErr`（选人屏会具名画出来）。
		if msg.err != nil {
			r.ctx.rosterErr = msg.err.Error()
		} else if msg.roster != nil {
			r.ctx.roster = msg.roster
			r.ctx.rosterErr = ""
		}
		return r, nil
	case tea.KeyMsg:
		//: ctrl+c 在任何屏都退，且不走屏自己的键表（与 Python 的 App 级绑定一致）。
		if msg.String() == "ctrl+c" {
			r.cancelTasks()
			return r, tea.Quit
		}
		//: ⚠ 这个快照必须在 `update` **之前**取：屏可以在自己那一步里设一条新提示
		//: （`guidesDirScreen` 保存成功、`noteBackScreen` 就是那个形状）；取晚了就会把
		//: "新提示"当成"旧提示"一起清掉 —— 第一版正是这么错的，被那条负对照当场抓住。
		noteBefore := r.ctx.note
		next, act := r.top().update(r.ctx, msg)
		if next != nil {
			if next != r.top() {
				r.closeScreen(r.top())
			}
			//: 屏可以就地换掉自己（例如「没有关卡」这种终态）。
			r.stack[len(r.stack)-1].scr = next
		}
		if act.kind == actQuit {
			r.cancelTasks()
			return r, tea.Quit
		}
		cmd = r.apply(act)
		//: ★ 2026-09-28 博士：「选关之后那个提示，只要进入了任意另一个屏幕就可以消失，
		//: 不要一直显示」。判据取**这一步有没有产生新提示**：屏自己（或压/弹屏的回调）
		//: 要给新提示，会在上面那两处设 ⇒ 它天然被保住（例：拦下时那句就在回调里设）。
		//: 只有"换屏了、却没人说话"时才把旧提示清掉 —— 那正是要消失的那种。
		if (act.kind == actBack || act.kind == actPush || act.kind == actPopTo) &&
			r.ctx.note == noteBefore {
			r.ctx.note = ""
		}
	case tea.MouseMsg: //: 鼠标交给**实现 `mouseScreen` 的栈顶屏**（不实现就什么也不做 —— 静默丢弃
		//: 是刻意的：纯文本屏点了本来就没有含义）。
		//: 坐标换算在一处：终端行号 − 本屏 body 的起始行 = 屏内行号。
		m := msg
		m.Y -= r.bodyTop()
		if ms, ok := r.top().(mouseScreen); ok {
			next, act := ms.onMouse(r.ctx, m)
			if next != nil {
				r.stack[len(r.stack)-1].scr = next
			}
			if act.kind == actQuit {
				r.cancelTasks()
				return r, tea.Quit
			}
			noteBefore := r.ctx.note
			cmd = r.apply(act)
			//: 与键盘那条同一口径：换屏而没人说话 ⇒ 旧提示不留（见 KeyMsg 分支的注释）。
			if (act.kind == actBack || act.kind == actPush || act.kind == actPopTo) &&
				r.ctx.note == noteBefore {
				r.ctx.note = ""
			}
		}
		return r, cmd
	default:
		//: 异步消息交给**栈里第一个**实现 `msgScreen` 的屏（从栈顶往下找）。
		//:
		//: ★ 为什么不只看栈顶：模态屏（二维码那张）就压在登录屏上面，而登录那条链的
		//: 消息必须送到**登录屏**去 —— 只看栈顶的话，轮询结果会被一张不处理消息的
		//: 码屏挡掉（症状：码出来了、状态行不动、扫上了也不推进）。
		//:
		//: ⚠ 这里**不回写** `r.stack[i].scr`：`onMsg` 允许弹/压栈（登录成功要先收码屏
		//: 再弹自己），回写就会在栈已经变短之后越界 —— 见 `msgScreen` 的说明。
		for i := len(r.stack) - 1; i >= 0; i-- {
			ms, ok := r.stack[i].scr.(msgScreen)
			if !ok {
				continue
			}
			act := ms.onMsg(r, msg)
			if act.kind == actQuit {
				r.cancelTasks()
				return r, tea.Quit
			}
			cmd = r.apply(act)
			break
		}
	}
	if cmd == nil {
		cmd = r.pending
	}
	r.pending = nil
	return r, cmd
}

// apply 执行一次动作，并把它的命令交出去。
func (r *root) apply(act action) tea.Cmd {
	switch act.kind {
	case actBack:
		r.pop(act.res)
	case actPush:
		r.push(act.push, act.done)
	case actPopTo:
		r.popTo(act.match)
	}
	return act.cmd
}

// popTo 连弹到**第一个满足条件的屏**（含它自己），并且**不回调**被弹掉的屏。
//
// 照 Python 的两个出口（`goto_home` / `goto_stage_list`）：
//   - `H` 回准备屏 ⇒ 整轮清空、连"在哪一章"都忘掉；
//   - `R` 回选关页 ⇒ 章／分部／环境的选择都留着，编队也留着（换一关通常还是同一队）。
//
// 不回调是**刻意的**：这两个出口是"退到某一层"，不是"逐级返回"，逐级回调会把中间
// 那几屏的 `done`（例如再压一屏）当成副作用带出来。
func (r *root) popTo(match func(screen) bool) {
	if match == nil {
		return
	}
	for i := len(r.stack) - 1; i >= 0; i-- {
		if match(r.stack[i].scr) {
			for _, f := range r.stack[i+1:] {
				r.closeScreen(f.scr)
			}
			r.stack = r.stack[:i+1]
			return
		}
	}
	//: 找不到目标层就不动（例如结果屏是从别处压上来的）—— 不许把栈弹空
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
		// 顶栏仍只占一行：鼠标 bodyTop 与矮窗口口径均保持不变。
		brand := styleBrand.Render("R.I.O.S.") + styleDim.Render(" │ ") +
			styleTitle.Render("作战演算")
		head = brand + styleDim.Render("  /  ") + styleCrumb.Render(r.crumb()) + "\n"
	}
	body := top.view(r.ctx)
	foot := styleDim.Render("操作  ") + styleKey.Render(r.help())
	if r.ctx.note != "" {
		foot += "\n" + styleAlert.Render(r.ctx.note)
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
