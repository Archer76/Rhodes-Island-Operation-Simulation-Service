package main

import (
	"fmt"
	"sort"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

// # [2] 选编队：问编队 ＋ 选人屏
//
// 对应 Python 的 `SquadAskScreen`（`ak_tactic/tui/app.py:1543`）与
// `SquadPickScreen`（`:1776`），以及它们的两个回调 `_squad_asked` / `_squad_picked`
// （`:2693` / `:2705`）。
//
// 分工照 Python：**选人屏只管画列表与勾人**，回车把「勾了哪些人」交还给调用方
// （`actBack` 带 res），由回调决定下一步。判定与拦截也在回调里，不放屏上 ——
// 屏是可被重建的，规则不是。★ 2026-09-26 起，那个「回调里的判定」收成了**解算入口
// 的守卫**（`enterSolve` ＋ `solveGate`，见下），因为两条路（手选／自动）都要经过它。
//
// ---------------------------------------------------------------------------
// # 政策：拦下「全员压到最低练度」的编队 —— 落点是**解算入口的守卫**
//
// 博士原话（2026-09-26）：
//
//	「如果玩家在选择干员的时候把所有槽位都选上了小于等于精一1级的干员，就提示
//	 『本模拟器不希望被用于暴力破解自限玩法』并退回干员选择界面。」
//
// 博士当天确认的三条口径（2026-09-26，**改口径先改这一段**）：
//
//  1. **闸门放在解算入口**：判定收成**一个**守卫 `solveGate`，手选与自动编队
//     **两条路都必须过它**，以后写解算屏时**绕不过去**。原实现把判定写在选人屏
//     的回调里，只有手选那条路经过 —— 那正是这条口径要修掉的东西。
//  2. **两条路都拦**（★ 口径变更，登记）：自动编队（「不用，让程序自己挑」）
//     **同样拦**。当天早上那版曾裁定「程序自己挑出来的放行」（理由是"那是程序挑的、
//     不是玩家在自限"，外加"整册低练度的新号否则走不下去"），博士随即**撤销**该豁免：
//     判据是**编队的练度**，不是「谁挑的」。⇒ 守卫里**没有豁免分支**，`solveSource`
//     只决定拦下之后退回哪一屏，**不决定拦不拦**。
//  3. **不要槽位条件**：判定就是「**选了人** 且 **全员 ≤ E1L1** ⇒ 拦」。原先那条
//     「取不到可部署人数 ⇒ 判定退化为非空即拦」的说法**作废** —— 那不是退化，
//     **这就是规则本身**。⇒ 守卫签名里**没有** `slotLimit`；屏上那行
//     「槽位 N 人／槽位：未知」照旧显示，但**不参与判定**（它是给玩家看的信息）。
//
// 判定范围（博士明确）：**精英0 1级 到 精英1 1级（含两端）**。
//
// 为什么要有这条：本模拟器是**帮玩家在真实名册里找出打得过的编队**用的。把编队
// 填成初始练度，是拿它去替玩家**暴力破解自限玩法**（「全员精零一级通关」那类挑战）
// ——那问的已经不是「我这一关该怎么打」，而是「帮我把自定的规则绕过去」。这句话
// 就是那条界线的落点：拦下、退回、让人看见界线在这儿；而不是悄悄算出一个能过的解。
//
// ⚠ 副作用（如实登记，不是实现缺陷）：口径 2 之后，「名册整册低练度的新号」在手选
// 与自动两条路上**都会被拦**。要留路得先由博士改口径（例如按「是否整册低练度」
// 另开一条分支），**不要在守卫之外偷偷放行**。
// ---------------------------------------------------------------------------

// squadMinLevelMsg 是拦下时那句话。**一字不改**：它是政策本身，不是提示文案。
const squadMinLevelMsg = "本模拟器不希望被用于暴力破解自限玩法"

// isMinLevel 是这条政策的**原子判定**：一名干员是否落在「精英0 1级 到 精英1 1级」。
//
// 照博士给的判定式原样写 `level <= 1`（而不是 `level == 1`）。等级 0 不出现在
// 真实名册里（森空岛的 level 最小是 1），所以两种写法在实际数据上等价；
// 但判据要跟**原式**一致，不在这里悄悄改语义。
func isMinLevel(op RosterOperator) bool {
	return (op.Elite == 0 && op.Level <= 1) || (op.Elite == 1 && op.Level <= 1)
}

// allMinLevel 是「每一个被选中的干员都在范围内」。
//
// 空列表返回 true —— 这是「全员」的**真空真**（一位也没有，就没有反例）。
// 「非空」这一条不在这里判，由守卫 `solveGate` 判：两件事分开写，
// 免得把「没勾人」和「勾了但不够低」混成一个函数的结果。
func allMinLevel(picked []RosterOperator) bool {
	for _, op := range picked {
		if !isMinLevel(op) {
			return false
		}
	}
	return true
}

// ---- 解算入口的守卫 ---------------------------------------------------------

// solveSource 是「这一份编队是谁定的」。它是守卫的第二个入参，**只影响拦下之后
// 退回哪一屏**；拦不拦只看编队本身（口径 2：没有豁免）。
type solveSource int

const (
	solveSourceManual solveSource = iota // 手选：玩家在选人屏自己勾出来的
	solveSourceAuto                      // 自动：「不用，让程序自己挑」—— 程序挑出来的
)

func (s solveSource) String() string {
	if s == solveSourceAuto {
		return "自动编队"
	}
	return "手选编队"
}

// solveGateBranch 是守卫**实际走的那条分支**。它同时是行使计数的下标 ——
// 判据靠它区分「走了这条分支」与「这条路根本没判」（后者的读数是全 0）。
type solveGateBranch int

const (
	//: 空编队 ⇒ 放行：一位也没选，不是「全员低练度」（真空真不算触发）。
	gateAllowEmptySquad solveGateBranch = iota
	//: 编队里有超过 E1L1 的人 ⇒ 放行：不在政策范围内。
	gateAllowNotMinLevel
	//: 手选、非空、全员低练度 ⇒ **拦**。
	gateBlockManual
	//: 自动、非空、全员低练度 ⇒ **拦**。★ 口径 2（2026-09-26）：早上那版这里是一条
	//: 「自动编队豁免」，博士当天下文撤销 —— 现在它与手选那条一样是拦下的分支，
	//: 只是拦下之后退回的屏不同。**不许**在这里加回豁免。
	gateBlockAuto

	//: 数组长度用，不是一条分支。
	solveGateBranchCount
)

// solveGateBranchNames 是四条分支的名字（判据与排障打印用）。
var solveGateBranchNames = [solveGateBranchCount]string{
	"放行·空编队", "放行·非全员低练度", "拦下·手选", "拦下·自动",
}

// solveGateHits 是四条分支的**行使计数**。判据读它证明每条分支都真的被走到过，
// 而且是**这一次调用**走的（自检取前后差，不是只看总数非零）。
var solveGateHits [solveGateBranchCount]int

// solveGateHitsSnapshot 取一次计数快照。
func solveGateHitsSnapshot() [solveGateBranchCount]int { return solveGateHits }

// solveVerdict 是守卫的结论。
type solveVerdict struct {
	Allow  bool            // true = 放行进解算
	Branch solveGateBranch // 走的是哪条分支（行使计数与判据都看它）
}

// solveGate 是这条政策的**唯一判定**：给定「已选编队」与「来源模式」，答放行还是拦。
//
// 纯函数：只看两个入参（`solveSource` 只用来选分支，不改变拦不拦）。三条同时
// 成立才拦 —— 注意**没有**槽位那一条（口径 3）：
//
//	选了人 ∧ 全员在 E0L1..E1L1 之内 ⇒ 拦（手选、自动**一样**拦，口径 2）
//
// ★ 唯一的 `allMinLevel` 调用点就在这里。这个事实由下面那条**防绕过判据**
// （`guardBypassFindings`）盯着：它扫源码，守卫之外再出现一处 `allMinLevel`
// 调用就判红。
func solveGate(picked []RosterOperator, src solveSource) solveVerdict {
	if len(picked) == 0 {
		return solveVerdict{Allow: true, Branch: gateAllowEmptySquad}
	}
	if !allMinLevel(picked) {
		return solveVerdict{Allow: true, Branch: gateAllowNotMinLevel}
	}
	if src == solveSourceAuto {
		return solveVerdict{Allow: false, Branch: gateBlockAuto}
	}
	return solveVerdict{Allow: false, Branch: gateBlockManual}
}

// guardBypassFindings 是那条「防后人绕过守卫」的判据核心：扫一份源码，报出
// **守卫函数体之外**还在自己判「全员低练度」的地方。
//
// 判据只有一条：`allMinLevel` 的**调用点**必须全部落在 `solveGate` 的函数体里
// —— 定义行 `func allMinLevel` 不算调用点，整行注释也不算（注释里提到函数名是
// 在解释政策，不是在判）。理由见口径 1：政策的判定只有一处，谁要在别处再判一遍，
// 就得调这个函数，而那一处会被这里照出来。
//
// 做成**吃源码文本的纯函数**，是为了让这条判据自己能判红：自检喂它一份故意在
// 守卫之外多写一处调用的合成源码，要求它报 ≥1 处；报 0 就是尺子恒空（等于没写）。
// 反过来，喂「调用只在守卫体内」的源码必须报 0 处 —— 两个方向都试过，它才是一条
// 会红也会绿的尺子。
//
// ⚠ 自检文件 `selftest.go` **不在扫描范围内**：它是造负对照的地方，本来就会直接
// 调 `allMinLevel` 来证明这函数不是恒真。它不是界面路径，也不压屏。
func guardBypassFindings(src string) []string {
	//: ★ 先归一化行尾再按行比对 —— 顶格收尾大括号认的是 `ln == "}"`，而工作树的
	//: 检出可能是 CRLF（`core.autocrlf`），那时每行尾巴都带 \r，收尾大括号永远认不到，
	//: **守卫体内那一处合法调用会被误报成「守卫之外」**。
	//: 这不是假想：本轮就实测到了 —— 负对照喂的合成源码是 LF（报得对），真源码是
	//: CRLF（报了一处假红）。两个方向的对照合起来才把这个尺子自身的毛病照出来。
	src = strings.ReplaceAll(src, "\r\n", "\n")
	lines := strings.Split(src, "\n")
	gateStart, gateEnd := -1, -1
	for i, ln := range lines {
		if strings.HasPrefix(ln, "func solveGate(") {
			gateStart = i
			continue
		}
		//: gofmt 之下，顶层函数的收尾就是一个**顶格**的 }。
		if gateStart >= 0 && ln == "}" {
			gateEnd = i
			break
		}
	}
	out := []string{}
	//: ★ 被找的那个记号在这里**拼出来**，不写成字面量 —— 否则本函数自己这一行就会
	//: 被自己扫成「守卫之外的一处调用」（判据把自己判红，是尺子的经典自伤）。
	token := "allMin" + "Level("
	def := "func allMin" + "Level("
	for i, ln := range lines {
		t := strings.TrimSpace(ln)
		if strings.HasPrefix(t, "//") || !strings.Contains(ln, token) {
			continue
		}
		if strings.Contains(ln, def) {
			continue //: 定义行，不是调用点
		}
		if gateStart >= 0 && i > gateStart && i < gateEnd {
			continue //: 守卫体内 —— 政策的判定就住在这儿
		}
		out = append(out, fmt.Sprintf("第 %d 行 %s", i+1, t))
	}
	return out
}

// blockNote 是拦下时留在屏上那句话。
//
// ★ 口径 3（2026-09-26）：它现在**陈述规则本身**。早先那句「本次没取到本关的可部署
// 人数，按「非空且全员在范围内」判定」随槽位条件一起作废 —— 槽位不再参与判定，
// 所以这里**没有**任何「退路／退化」要交代。
func blockNote(branch solveGateBranch) string {
	back := "已退回干员选择界面，请调整编队。"
	if branch == gateBlockAuto {
		back = "已退回「选编队」，请换一种选法。"
	}
	return "★ " + squadMinLevelMsg + " —— " + back +
		"\n（判定规则：编队非空、且每一位都在「精英0 1级 到 精英1 1级」之内 ⇒ 拦下；" +
		"自动编队同样拦。与槽位数无关。）"
}

// ---- 名册（桥取一次，缓存在共享态里）----------------------------------------

// ensureRoster 取一次名册并缓存。**取不到不抛错、也不返回空名册**：把原因
// 原样记进 `rosterErr`，由选人屏具名显示（照 `welcomeScreen` 那条口径：
// 任何一栏取不到，也要把原因写在那一栏里）。
//
// ★ 与 Python 的差异（登记）：Python 在 `RiosApp` 启动时就 `load_roster()`
// （`app.py:2460`），Go 这边**进 [2] 时才读一次**并缓存。差的是"什么时候付这份
// 代价"（Python 是开机就付），不是名册的内容。
func (c *appCtx) ensureRoster() *rosterData {
	if c.roster != nil || c.rosterErr != "" {
		return c.roster
	}
	r, err := fetchRoster()
	if err != nil {
		c.rosterErr = err.Error()
		return nil
	}
	c.roster = r
	return r
}

// slotLimit 是这一关的**可部署人数**（Python 的 `State.deploy_limit`）。
// 0 = 取不到 —— 引擎那侧的 `options.characterLimit` 还没接到界面来。
//
// ★ 口径 3（2026-09-26）：这个数现在**只用来显示**（选人屏那行「槽位 N 人／
// 槽位：未知」），**不参与那条拦截的判定** —— 守卫 `solveGate` 的签名里没有它。
func (c *appCtx) slotLimit() int { return c.deployLimit }

// ---- [2a] 问编队 -----------------------------------------------------------

type squadAskScreen struct{ cursor int }

func (*squadAskScreen) title() string { return "选编队" }
func (*squadAskScreen) help() string  { return listHelp }

func (s *squadAskScreen) view(c *appCtx) string {
	rows := []string{}
	if c.roster != nil {
		rows = append(rows, pad("不用，让程序自己挑", 24)+
			"直接从名册里找组合，这一轮你不指定人")
		rows = append(rows, pad("我自己选", 24)+
			fmt.Sprintf("进选人界面，从名册的 %d 人里勾", len(c.roster.Operators)))
	} else {
		//: 名册取不到也要把两条路**都**列出来，并在下面具名写清为什么
		//: ——「我自己选」进得去，只是里面没有可勾的人。
		rows = append(rows, pad("不用，让程序自己挑", 24)+
			"直接从名册里找组合，这一轮你不指定人")
		rows = append(rows, pad("我自己选", 24)+"进选人界面（现在没有名册）")
	}
	return renderList(c, "选编队　要不要手动加人", rows, s.cursor) + "\n" + c.rosterLine()
}

func (s *squadAskScreen) update(_ *appCtx, k tea.KeyMsg) (screen, action) {
	if n, ok := moveCursor(k, s.cursor, 2); ok {
		s.cursor = n
		return s, action{kind: actNone}
	}
	switch {
	case keyIs(k, "enter"):
		return s, action{kind: actBack, res: s.cursor == 1} // true = 我自己选
	case keyIs(k, "esc"), keyIs(k, "backspace"):
		return s, action{kind: actBack}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
	}
	return s, action{kind: actNone}
}

// ---- [2b] 选人屏 -----------------------------------------------------------

// squadPickScreen 是选人屏：槽位数 ＋ 可多选的干员列表（名册来自桥）＋ 进入下一步。
//
// ★ 与 Python 的差异（登记，都是**没做**而不是做错）：Python 那一屏还有
// **主职业行 / 子职业行**两排筛选（`PickerRow`）与**练度门槛下拉**三档
// （不限／≥精英二60／精英二90），这一版只做「槽位数 ＋ 列表 ＋ 多选 ＋ 前进」。
// 少了筛选，两百多人的名册得靠上下键翻——判据不依赖它们，先用着。
type squadPickScreen struct {
	cursor int
	rows   []RosterOperator
	picked map[string]bool //: 键是**干员名**（与 Python 的 `_picked: set[str]` 同口径）
}

func (*squadPickScreen) title() string { return "选人" }

func (*squadPickScreen) help() string {
	return "↑/↓ 移动 · 空格 勾选 · Enter 进入下一步 · M 切换模式 · Esc 返回 · Q 退出"
}

// newSquadPickScreen 造一张新的选人屏。`keep` 是「重建时要把哪些勾带过来」
// （拦下之后重进时用：勾选不丢，人才知道该动哪一个）。
func newSquadPickScreen(c *appCtx, keep []RosterOperator) *squadPickScreen {
	s := &squadPickScreen{picked: map[string]bool{}}
	if r := c.roster; r != nil {
		ops := append([]RosterOperator(nil), r.Operators...)
		//: 练度降序 —— 与 Python 的 `Roster.top()` 同向（那边还带 potential，
		//: 桥上没给这个字段，同级改按 char_id 定序，保证两次打开顺序一致）。
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
		s.rows = ops
	}
	//: 把上一轮已经定下的编队勾回来（Python 用 `state.squad` 做同一件事）。
	for _, op := range s.rows {
		for _, n := range c.squad {
			if op.Name == n {
				s.picked[op.Name] = true
			}
		}
	}
	for _, op := range keep {
		s.picked[op.Name] = true
	}
	return s
}

func (s *squadPickScreen) view(c *appCtx) string {
	head := make([]string, 0, 2)
	//: 槽位数**照旧写在屏上**（给玩家看的信息），但它**不参与判定**了 ——
	//: 口径 3（2026-09-26）：判定就是「选了人且全员 ≤E1L1」，与槽位数无关，
	//: 所以这里写「未知」也不会改变拦不拦。
	slot := styleCursor.Render(fmt.Sprintf("槽位 %d 人", c.slotLimit()))
	if c.slotLimit() <= 0 {
		slot = styleCursor.Render("槽位：未知（没取到本关的可部署人数）")
	}
	mode := "允许程序补充"
	if c.mode == "only" {
		mode = "只用我选的"
	}
	head = append(head, slot+"　模式："+mode+
		fmt.Sprintf("　已勾 %d 人", len(s.picked)))
	head = append(head, c.rosterLine())

	rows := make([]string, 0, len(s.rows))
	for _, op := range s.rows {
		box := "[ ]"
		if s.picked[op.Name] {
			box = "[x]"
		}
		rows = append(rows, box+" "+pad(op.Name, 14)+
			pad(fmt.Sprintf("E%d %d级", op.Elite, op.Level), 9)+
			professionCN(op.Profession))
	}
	return renderPickList(c, head, rows, s.cursor)
}

func (s *squadPickScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	if n, ok := moveCursor(k, s.cursor, len(s.rows)); ok {
		s.cursor = n
		return s, action{kind: actNone}
	}
	switch {
	case keyIs(k, " ") || k.Type == tea.KeySpace:
		if s.cursor < len(s.rows) {
			name := s.rows[s.cursor].Name
			if s.picked[name] {
				delete(s.picked, name)
			} else {
				s.picked[name] = true
			}
		}
	case keyIs(k, "enter"):
		if c.roster == nil {
			//: 没有名册就选不了人。**不许静默**：把原因原样留在屏上。
			c.note = "★ 名册没取到，选不了人（原因见屏上那一行）"
			return s, action{kind: actNone}
		}
		return s, action{kind: actBack, res: s.pickedOps()}
	case keyIs(k, "m"):
		if c.mode == "only" {
			c.mode = "auto"
		} else {
			c.mode = "only"
		}
	case keyIs(k, "esc"), keyIs(k, "backspace"):
		return s, action{kind: actBack}
	case keyIs(k, "q"):
		return s, action{kind: actQuit}
	}
	return s, action{kind: actNone}
}

// pickedNames 按名字排序返回勾中的人 —— 与 Python 的 `sorted(self._picked)` 同口径
// （Go 的字符串比较与 Python 的码点序在中日文上一致）。
func (s *squadPickScreen) pickedNames() []string {
	out := make([]string, 0, len(s.picked))
	for n := range s.picked {
		out = append(out, n)
	}
	sort.Strings(out)
	return out
}

// pickedOps 把勾中的名字还原成干员。同名多形态（阿米娅那样）取列表里第一个
// —— Python 那边以名字为键，也有同一个性质。
func (s *squadPickScreen) pickedOps() []RosterOperator {
	byName := map[string]RosterOperator{}
	for _, op := range s.rows {
		if _, dup := byName[op.Name]; !dup {
			byName[op.Name] = op
		}
	}
	out := make([]RosterOperator, 0, len(s.picked))
	for _, n := range s.pickedNames() {
		if op, ok := byName[n]; ok {
			out = append(out, op)
		}
	}
	return out
}

// renderPickList 是选人屏自己的列表渲染：比 `renderList` 多一段信息头，
// 并**把它占的行数从可见窗口里扣掉** —— 矮窗口下不能因为多了两行说明，
// 就让列表整个消失（本屏的口径与 Python 的 `_fit_extra` 一样：装饰让路，内容优先）。
func renderPickList(c *appCtx, head []string, rows []string, cursor int) string {
	var b strings.Builder
	for _, ln := range head {
		b.WriteString(cut(ln, c.w-1) + "\n")
	}
	body := bodyRows(c) - len(head)
	if body < 1 {
		body = 1
	}
	if len(rows) == 0 {
		b.WriteString(styleDim.Render("  （名册里没有可勾的干员）"))
		return b.String()
	}
	top := 0
	if cursor >= body {
		top = cursor - body + 1
	}
	for i := top; i < len(rows) && i < top+body; i++ {
		line := cut(rows[i], c.w-3)
		if i == cursor {
			b.WriteString(styleCursor.Render("> "+line) + "\n")
		} else {
			b.WriteString("  " + line + "\n")
		}
	}
	b.WriteString(styleDim.Render(fmt.Sprintf("共 %d 人", len(rows))))
	return b.String()
}

// rosterLine 是「名册从哪来、有几个、是不是完整名册」那一行。
//
// 取不到时**写原因**（只取第一行：错误全文有好几行，窗宽装不下；全文留在
// `rosterErr` 里，判据与排障读它）。这一行是那块"不许静默"的落点。
func (c *appCtx) rosterLine() string {
	if c.rosterErr != "" {
		first := strings.SplitN(c.rosterErr, "\n", 2)[0]
		return styleDim.Render("★ 名册：取不到 —— " + first)
	}
	if c.roster == nil {
		return styleDim.Render("名册：尚未读取")
	}
	flag := "完整（含专精与模组等级）"
	if !c.roster.Complete {
		flag = "**降级来源**（没有专精与模组等级）"
	}
	return styleDim.Render(fmt.Sprintf("名册：%d 人　来源 %s　%s",
		len(c.roster.Operators), c.roster.Source, flag))
}

// professionCN 把名册里的英文职业枚举翻成中文。
//
// 表照 `ak_tactic/tui/data.py:431` 的 `PROFESSION_CN` 抄（八个职业 ＋ 召唤物／装置）。
// 抄而不是查库：选人屏不该为了八个常量去开一次 `akdb.sqlite`（Python 那边
// 也是这么处理的）。
var professionCNTable = map[string]string{
	"PIONEER": "先锋", "WARRIOR": "近卫", "TANK": "重装", "SNIPER": "狙击",
	"CASTER": "术师", "MEDIC": "医疗", "SUPPORT": "辅助", "SPECIAL": "特种",
	"TOKEN": "召唤物", "TRAP": "装置",
}

func professionCN(code string) string {
	if cn, ok := professionCNTable[code]; ok {
		return cn
	}
	if code == "" {
		return "未知"
	}
	return code
}

// ---- 回调：压屏与解算入口（对应 RiosApp._squad_asked / _squad_picked）-------

// enterSolve 是**解算入口**，也是那条守卫的落点：**两条路（手选／自动）都必须
// 从这里进**（口径 1）。判定只住在 `solveGate` 里，屏上动作只住在这里。
//
// 为什么现在就立这个入口：解算屏还没有实体（`cmd/rios-tui/` 下没有 solve/result
// 文件），所以「绕不过去」现在只能靠**入口唯一**来保证 —— 谁要进解算，就得调这个
// 函数；谁要在别处自己判一遍，就会被 `guardBypassFindings` 扫出来。
//
// ★ 给未来的解算屏（登记，2026-09-26）：`SolveScreen` 落地时**必须**经由本函数进解算
// （把下面两处 `note` 换成压解算屏即可，守卫的位置不动），并且那时要**再加**一条断言
// 盯着「解算入口这条路径确实经过 solveGate」。现在已有的两条是：
// ① 本文件里那条源码扫描判据 `guardBypassFindings`（守卫之外不许有第二处判定）；
// ② 自检里按**分支计数前后差**断言两条路各自走了哪条分支（路被绕开 ⇒ 读数为 0）。
func (r *root) enterSolve(picked []RosterOperator, src solveSource) solveVerdict {
	c := r.ctx
	v := solveGate(picked, src)
	solveGateHits[v.Branch]++ //: 行使计数：每条分支都要有非零读数
	if !v.Allow {
		c.note = blockNote(v.Branch)
		switch src {
		case solveSourceAuto:
			//: 自动编队被拦（口径 2，没有豁免）：回到「选编队」那一屏 ——
			//: 程序挑的人玩家改不了，能改的是「走哪条路」。
			r.push(&squadAskScreen{}, onSquadAsked)
		default:
			//: 手选被拦：选人屏这一刻已经弹掉了，所以把它**重新压回来**
			//: （等价于「退回干员选择界面」），并把勾选带过去 —— 人才知道该改哪一个。
			r.push(newSquadPickScreen(c, picked), onSquadPicked)
		}
		return v
	}
	names := make([]string, 0, len(picked))
	for _, op := range picked {
		names = append(names, op.Name)
	}
	c.squad = names
	switch {
	case len(names) == 0 && src == solveSourceAuto:
		c.note = "已选「不用，让程序自己挑」—— 下一步（解算）尚未实现"
	case len(names) == 0:
		c.note = "未指定干员 —— 下一步（解算）尚未实现"
	default:
		c.note = fmt.Sprintf("已确定编队 %d 人：%s —— 下一步（解算）尚未实现",
			len(names), strings.Join(names, "、"))
	}
	return v
}

// onSquadAsked 是问编队屏的回调。Esc（res 不是 bool）已经弹回上一层，什么都不做。
//
// 「不用，让程序自己挑」这条路**也过守卫**（口径 2：没有豁免）：程序挑出来的编队
// 放在 `c.autoPicks` 里 —— 搜索层还没接进来，运行期它是空的（走「空编队放行」那条
// 分支）；自检里显式填一个全员低练度的自动编队，好把 `gateBlockAuto` 真的走到。
// **它不是「没判」**：判定与行使计数都发生在 `enterSolve` 里。
func onSquadAsked(r *root, res any) {
	manual, ok := res.(bool)
	if !ok {
		return
	}
	c := r.ctx
	if !manual {
		c.mode = "auto"
		r.enterSolve(c.autoPicks, solveSourceAuto)
		return
	}
	c.ensureRoster() //: 取不到也只记进 rosterErr，由选人屏具名显示
	r.push(newSquadPickScreen(c, nil), onSquadPicked)
}

// onSquadPicked 是选人屏的回调：**手选这条路的落点**。
//
// 拦下时不用「退一层」来实现 —— 选人屏这一刻已经弹掉了，正确的动作是**把选人屏
// 重新压回来**（Python 是 dismiss 之后由调用方 push 新屏；Go 这边自己持有屏实例，
// 等价于「回到选人界面」）。这件事现在住在 `enterSolve` 里（两条路共用）。
func onSquadPicked(r *root, res any) {
	picked, ok := res.([]RosterOperator)
	if !ok {
		return // Esc：已弹回上一层
	}
	r.enterSolve(picked, solveSourceManual)
}
