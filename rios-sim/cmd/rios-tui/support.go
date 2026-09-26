package main

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"rios-sim/data"
)

// # [2c] 助战：选人屏上的开关 ＋ 单独一屏挑一位（新文件，2026-09-26）
//
// ## 博士已确认的口径（2026-09-26，**改口径先改这一段**）
//
//  1. **上限**：用助战 ⇒ 编队上限 **13**（自己的 12 ＋ 助战 1）；不用 ⇒ **12**。
//     助战占一格。
//  2. **助战干员从 gamedata 的「全部干员」里挑**（不是从本机名册里挑 ——
//     助战是好友的、不属于本机名册）。
//  3. **助战的练度不填、只写名字**：官方协议里 `opers[]` 只有 `name` 是必填的，
//     `requirements` 是"练度要求，自动编队时校验。可选，默认为空"（发布版原文）；
//     MAA 也识别不了助战干员的练度。⇒ 界面这一屏**只要玩家选一个名字**，
//     **不要**练度输入框。
//  4. **拦截规则里助战计入**（`solveGate` 的 `allMinLevel` 判定）：所以带一位助战就
//     **不会**触发那条「全员 ≤ 精英1 1级」的拦截 —— 助战没有练度、永远不满足"≤E1L1"。
//
// ## ⚠ 具名登记的后果（口径 4 ＋ 口径 1 的**必然结果**，不是 bug）
//
// 「全员压到最低练度」那条自限拦截，**在带一位助战时必然放行**：助战那一位没有练度，
// 不参与 `allMinLevel`，于是编队不可能「全员 ≤E1L1」。落成一句话就是：
//
//	**这道闸拦不住「1 位助战 ＋ 11 位 E0L1」的编队。**
//
// 这是博士 2026-09-26 两条口径合起来的必然后果，按口径就这么实现，如实登记在此。
// 要改就得先改口径，**不要在守卫里偷偷补一条别的判定**（那会让「唯一判定」变成两处）。
//
// ## ★ 另一个坑（本轮实测到的，写在这里免得后人踩）
//
// 口径 4 说「助战没有练度 ⇒ 永远不满足 ≤E1L1」—— 那说的是**协议里没有练度要求**。
// 但 Go 侧的**零值** `RosterOperator{}`（Elite=0、Level=0）**反倒落在范围内**：
// `isMinLevel` 的判定式是 `Elite == 0 && Level <= 1`，而 `0 <= 1` 为真
// ⇒ 拿一个零值干员顶替助战，闸门**照样拦**，与口径 4 正好相反。
// 所以助战在守卫里必须是**独立信号**（第三入参），不能拼进 `picked`。
// 自检里有一条断言把这件事钉住（`isMinLevel(零值) == true`）。

// supportSlots 是助战**自己占的那一格**（口径 1：13 = 自己的 12 ＋ 助战 1）。
const supportSlots = 1

// squadLimitOf 给出开关处于 `on` 时的编队上限。
//
// ★ 12 这个数只有**一处来源**（`solve.go` 的 `squadCap`）—— 屏上不写死它，
// 读的是 `appCtx.squadLimit`（由 `setSupportUse` 维护，见下）。
func squadLimitOf(on bool) int {
	if on {
		return squadCap + supportSlots
	}
	return squadCap
}

// setSupportUse 拨助战的开关，并把**上限一起改掉**。
//
// 关 ⇒ 连名字一起清掉：「不用助战」还留着一位将要用的人，是最容易出错的中间态
// （屏上写着「不用」而下游把他带上）。⇒ 名字与开关分成两个字段只是为了屏上能显示
// 「用（某某）」，**下游只认 `supportForSolve`**。
func (c *appCtx) setSupportUse(on bool) {
	c.useSupport = on
	if !on {
		c.supportName = ""
	}
	c.squadLimit = squadLimitOf(on)
}

// supportForSolve 是「这一轮解算／导出**实际带上**的助战」。
//
// 开关是唯一的真源：关掉就返回空串，**不看名字还在不在**。
func (c *appCtx) supportForSolve() string {
	if !c.useSupport {
		return ""
	}
	return strings.TrimSpace(c.supportName)
}

// squadLimitShown 是屏上要显示的那个上限。
//
// 零值上下文（自检手搓的、或这条链之外新建的 `appCtx`）按「不用助战」算 ——
// 与 `newAppCtx` 的初值同源，**不是第二处口径**。
func (c *appCtx) squadLimitShown() int {
	if c.squadLimit > 0 {
		return c.squadLimit
	}
	return squadCap
}

// supportLine 是屏上那一行「助战：…」。
//
// ⚠ 三种形态的字面必须**分得开**：「助战：不用」里**不含**子串「助战：用」
// （中间隔着那个"不"字）⇒ 自检可以直接用子串断言，不必上正则。
func (c *appCtx) supportLine() string {
	if !c.useSupport {
		return "助战：不用"
	}
	if n := c.supportForSolve(); n != "" {
		return "助战：用（" + n + "）"
	}
	return "助战：用（还没挑人）"
}

// ---- 屏：从全部干员里挑一位 ------------------------------------------------

// supportPickScreen 是**单独压一屏**的助战选择：从**全部干员**里挑一个名字。
//
// 与选人屏的三处不同（都是口径决定的，不是漏做）：
//
//  1. 列的是**全部干员**（`data.AllOperators()`），**不是本机名册** —— 助战是好友的；
//  2. **不分练度、不显示练度、也不收练度**（口径 3）；
//  3. 只能选**一个**（助战占一格，口径 1）。
//
// ★ 未做（具名登记）：这一屏**没有筛选／搜索**。四百六十人靠上下键翻，找某一位很难
// —— 选人屏（名册）也有同样的毛病，而 Python 侧那一屏有职业行与练度门槛两排筛查。
// 口径没定之前**不自己发明筛选键**（多一个键就多一处得跟 Python 对齐的行为），
// 先如实登记在这里。
type supportPickScreen struct {
	cursor int
	rows   []data.OperatorRow
	//: 取不到「全部干员」时的**具名**原因（照 `welcomeScreen` 那条口径：
	//: 任何一栏取不到，也要把原因写在那一栏里，不许静默空着）。
	err string
}

func (*supportPickScreen) title() string { return "选助战" }

func (*supportPickScreen) help() string {
	return "↑/↓ 移动 · Enter 选定这位助战 · Esc 取消（不用助战）· Q 退出"
}

// newSupportPickScreen 造一张助战屏。
//
// 取不到全量表也**照常造屏**：原因写进 `err` 并由屏上具名显示，回车选不了人
// —— 与选人屏「没有名册」那条口径一样（屏照压，但不假装能选）。
func newSupportPickScreen() *supportPickScreen {
	s := &supportPickScreen{}
	rows, err := data.AllOperators()
	if err != nil {
		s.err = err.Error()
		return s
	}
	s.rows = rows
	return s
}

func (s *supportPickScreen) view(c *appCtx) string {
	head := []string{
		c.supportLine() + fmt.Sprintf("　编队上限 %d 人（自己的 %d ＋ 助战 %d）",
			c.squadLimitShown(), squadCap, supportSlots),
		//: 口径 3 那句话要**写在屏上**：玩家看得见"不用填练度"，才不会去找输入框。
		"★ 助战的练度不用填（MAA 不识别助战干员的练度）—— 这一屏只选一个名字。",
	}
	if s.err != "" {
		head = append(head, styleDim.Render("★ 全部干员取不到："+firstLineWith(s.err, "★")))
	} else {
		head = append(head, styleDim.Render(fmt.Sprintf(
			"候选：全部干员 %d 名（gamedata 全量表，与自己的名册无关）", len(s.rows))))
	}
	if len(s.rows) == 0 {
		//: ⚠ 不走 `renderPickList`：它那句"名册里没有可勾的干员"在这一屏是**错的**
		//: （这里压根不是名册）。空的原因由上面那行具名给出。
		var b strings.Builder
		for _, ln := range head {
			b.WriteString(cut(ln, c.w-1) + "\n")
		}
		b.WriteString(styleDim.Render("  （没有可挑的候选）"))
		return b.String()
	}
	rows := make([]string, 0, len(s.rows))
	for _, op := range s.rows {
		rows = append(rows, pad(op.Name, 16)+professionCN(op.Profession))
	}
	return renderPickList(c, head, rows, s.cursor)
}

func (s *supportPickScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	if n, ok := moveCursor(k, s.cursor, len(s.rows)); ok {
		s.cursor = n
		return s, action{kind: actNone}
	}
	switch {
	case keyIs(k, "enter"):
		if s.err != "" || len(s.rows) == 0 {
			//: 没有候选就选不了人。**不许静默**：把原因留在屏上（它已经在头的第三行）。
			c.note = "★ 全部干员取不到，挑不了助战（原因见屏上那一行）"
			return s, action{kind: actNone}
		}
		return s, action{kind: actBack, res: s.rows[s.cursor].Name}
	case keyIs(k, "esc"), keyIs(k, "backspace"):
		//: 取消 = **不用助战**，退回选人屏。交回 nil —— 与「选了个空名字」分得开
		//: （照询问屏那条口径：取消与空值是两回事）。
		return s, action{kind: actBack}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
	}
	return s, action{kind: actNone}
}

// ---- 回调与开关的落点 ------------------------------------------------------

// onSupportPicked 是助战屏的关屏回调。两条路都要把状态**收干净**：
//
//   - 回车选了名字 ⇒ 开关开、上限 13、名字记进 `appCtx`；
//   - Esc 取消（`res` 不是字符串）⇒ **不用助战**：名字清掉、上限回 12、退回选人屏。
//
// 取消**不是**"关掉这一屏什么都不做"：口径里 Esc 就是"不用助战"，状态必须跟着回退，
// 否则会留下一个"名字还在、但没人用它"的中间态（下一轮进选人屏时屏上会写着"用"）。
func onSupportPicked(r *root, res any) {
	c := r.ctx
	name, ok := res.(string)
	if !ok || strings.TrimSpace(name) == "" {
		c.setSupportUse(false)
		c.note = fmt.Sprintf("已取消：这一轮不用助战（编队上限回到 %d）", c.squadLimitShown())
		return
	}
	c.supportName = strings.TrimSpace(name)
	c.setSupportUse(true)
	c.note = "助战：" + c.supportName + fmt.Sprintf(
		"　练度不用填（MAA 不识别助战干员的练度）；编队上限 %d", c.squadLimitShown())
}

// toggleSupport 是选人屏上那个键（`T`）的落点：拨开关，并把「用」这一支**立刻**
// 接去挑人。
//
// ★ 「开着但没挑人」**不是**一个可停留的状态：口径 1 说助战占一格 ⇒ 开关一开就得
// 有人占那一格。所以开的时候**直接压助战屏**；在那一屏 Esc 取消即回到「不用」
// （`onSupportPicked` 收的尾）。关的时候把名字一起清掉（见 `setSupportUse`）。
func toggleSupport(c *appCtx) action {
	if c.useSupport {
		c.setSupportUse(false)
		c.note = fmt.Sprintf("助战：不用（编队上限回到 %d）", c.squadLimitShown())
		return action{kind: actNone}
	}
	c.setSupportUse(true)
	return action{kind: actPush, push: newSupportPickScreen(), done: onSupportPicked}
}
