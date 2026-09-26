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
// 屏是可被重建的，规则不是。
//
// ---------------------------------------------------------------------------
// # 政策：拦下「全员压到最低练度」的编队
//
// 博士原话（2026-09-26）：
//
//	「如果玩家在选择干员的时候把所有槽位都选上了小于等于精一1级的干员，就提示
//	 『本模拟器不希望被用于暴力破解自限玩法』并退回干员选择界面。」
//
// 判定范围（博士随后明确）：**精英0 1级 到 精英1 1级（含两端）**。读作
// 「每一位被选中的干员都满足 `(elite==0 && level<=1) || (elite==1 && level<=1)`，
// **并且**所有槽位都选上了」。「所有槽位」＝这一关的**可部署人数**
// （Python 侧叫 `State.deploy_limit`，来自 gamedata 的 `options.characterLimit`）。
//
// 为什么要有这条：本模拟器是**帮玩家在真实名册里找出打得过的编队**用的。
// 把每一个槽位都填成初始练度的干员，是拿它去替玩家**暴力破解自限玩法**
// （「全员精零一级通关」那类挑战）——那问的已经不是「我这一关该怎么打」，
// 而是「帮我把自定的规则绕过去」。这句话就是那条界线的落点：拦下、退回、
// 让人看见界线在这儿；而不是悄悄算出一个能过的解。
//
// ★ 退化（如实登记，不假装知道槽位数）：取不到可部署人数时（Go 侧现在的实际
// 情况 —— 引擎那侧的 `options.characterLimit` 还没接到界面来，`deployLimit`
// 恒为 0；Python 侧同一个数是 0 时含义相同），判定**退化为**
// 「非空且全员在范围内也算触发」。屏上会把这次退化写出来（不是只有代码知道）。
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
// 「非空」这一条不在这里判，由 pickTriggersBlock 判：两件事分开写，
// 免得把"没勾人"和"勾了但不够低"混成一个函数的结果。
func allMinLevel(picked []RosterOperator) bool {
	for _, op := range picked {
		if !isMinLevel(op) {
			return false
		}
	}
	return true
}

// pickTriggersBlock 是那条政策的**纯函数判据**（界面只是它的一个调用方）。
//
// 三条同时成立才拦：
//  1. 勾了人（空编队不是「所有槽位都选上了」）；
//  2. 勾的每一位都在「E0L1..E1L1」之内；
//  3. 槽位满了 —— `slotLimit` 是这一关的可部署人数；`slotLimit <= 0` 表示
//     **取不到**，此时第 3 条退化为不判（见文件头的退化说明）。
func pickTriggersBlock(picked []RosterOperator, slotLimit int) bool {
	if len(picked) == 0 {
		return false
	}
	if !allMinLevel(picked) {
		return false
	}
	if slotLimit > 0 && len(picked) < slotLimit {
		return false // 槽位没满
	}
	return true
}

// blockNote 是拦下时留在屏上那句话。槽位取不到时**顺带把退化写出来**。
func blockNote(slotLimit int) string {
	msg := "★ " + squadMinLevelMsg + " —— 已退回干员选择界面，请调整编队。"
	if slotLimit <= 0 {
		msg += "\n（本次没取到本关的可部署人数，按「非空且全员在范围内」判定。）"
	}
	return msg
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
	//: 槽位数**必须写在屏上**：那条拦截规则判的就是"所有槽位都选上了没有"，
	//: 玩家看不到槽位数就没法理解为什么被拦。
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

// ---- 回调：压屏与拦截（对应 RiosApp._squad_asked / _squad_picked）----------

// onSquadAsked 是问编队屏的回调。Esc（res 不是 bool）已经弹回上一层，什么都不做。
func onSquadAsked(r *root, res any) {
	manual, ok := res.(bool)
	if !ok {
		return
	}
	c := r.ctx
	if !manual {
		c.squad = nil
		c.mode = "auto"
		c.note = "已选「不用，让程序自己挑」—— 下一步（解算）尚未实现"
		return
	}
	c.ensureRoster() //: 取不到也只记进 rosterErr，由选人屏具名显示
	r.push(newSquadPickScreen(c, nil), onSquadPicked)
}

// onSquadPicked 是选人屏的回调：**这条政策的落点**。
//
// 被拦下时不用"退一层"来实现 —— 选人屏这一刻已经弹掉了，所以正确的动作是
// **把选人屏重新压回来**（Python 是 dismiss 之后由调用方 push 新屏；Go 这边
// 自己持有屏实例，等价于"回到选人界面"），并把勾选带过去，顺带把话说在屏上。
func onSquadPicked(r *root, res any) {
	picked, ok := res.([]RosterOperator)
	if !ok {
		return // Esc：已弹回上一层
	}
	c := r.ctx
	if pickTriggersBlock(picked, c.slotLimit()) {
		c.note = blockNote(c.slotLimit())
		r.push(newSquadPickScreen(c, picked), onSquadPicked)
		return
	}
	names := make([]string, 0, len(picked))
	for _, op := range picked {
		names = append(names, op.Name)
	}
	c.squad = names
	if len(names) == 0 {
		c.note = "未指定干员 —— 下一步（解算）尚未实现"
		return
	}
	c.note = fmt.Sprintf("已确定编队 %d 人：%s —— 下一步（解算）尚未实现",
		len(names), strings.Join(names, "、"))
}
