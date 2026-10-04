package main

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"rios-sim/progress"

	tea "github.com/charmbracelet/bubbletea"
)

// # 解算屏（对应 Python 的 `SolveScreen`，`app.py:2053`）
//
// 元素：关卡与人数上限、真实计数、进度条、日志（**只留最后 14 行** —— 这一屏的意义
// 是"看得见它在动"，不是"留下完整档案"；要看全，结果屏才是那条路）。
//
// ## 自动加深（博士 2026-09-18 定的）
//
// 先按 4 人找（大多数关卡这样就够）；**没找到三星**才加深，步长 2，天花板是这一关的
// **可部署人数**；取不到就按编队上限 12 封顶**并在日志里说明**（悄悄按 12 搜会让人
// 以为这一关真能上 12 个）。每深一层都要把搜索整个重跑一遍，代价是真的 ⇒ 每一轮都
// 往日志里写一行，让人看得见"它在加深，不是卡住了"。
//
// ## 运行时隔离与实时状态
//
// TUI 与引擎是独立进程。引擎在 stderr 输出真实搜索快照，stdout 只给最终响应。
// 每个解算屏持有可取消任务；结果、快照与心跳带屏幕任务身份及轮次。
// 输入在本轮固定。计数按后端完成尝试刷新，耗时/转轮独立刷新，不依赖最终响应。

const (
	//: 候选池上限。**这是候选池，不是出战人数**（博士 2026-09-18 追问过）：它只决定
	//: "从多少人里挑组合"，与出来的编队有几个人无关，所以界面上不写这个数。
	autoPool = 24
	//: 解算深度的起点：先按 4 人找。
	depthStart = 4
	//: 自动加深的步长（每深一层都要重跑一遍搜索，所以取 2 而不是 1）。
	depthStep = 2
	//: 一支编队最多 12 人（游戏内的编队槽位）。它与**关卡可部署人数**是两回事：
	//: 场上放不下的人可以撤下来换别人上，所以真正的闸门是可部署人数，12 只是封顶。
	squadCap = 12
	//: 一轮解算最多等多久。搜索是分钟级的，给足余量；超时会**具名**报出来。
	solveTimeout = 30 * time.Minute
)

// depthLadder 复刻 `app.py:144` 的 `depth_ladder`：从 4 人起，按 2 加深，到可部署人数。
//
// 末端一定落在 `cap` 上（`4、6、8` 而不是 `4、6、7` 里漏掉 8），免得"上限 8 人"那一档
// 永远试不到。
func depthLadder(deployLimit int) []int {
	cap := deployLimit
	if cap <= 0 {
		cap = squadCap
	}
	if cap > squadCap {
		cap = squadCap
	}
	if cap <= depthStart {
		return []int{cap}
	}
	out := []int{}
	for d := depthStart; d <= cap; d += depthStep {
		out = append(out, d)
	}
	if out[len(out)-1] != cap {
		out = append(out, cap)
	}
	return out
}

// firstN 取前 n 个（日志/提示里只列几个，免得一行爆掉）。
func firstN(xs []string, n int) []string {
	if len(xs) <= n {
		return xs
	}
	return xs[:n]
}

// solvePool 复刻 `SolveScreen._pool`（`app.py:2214`）：这一轮解算的**人选池**。
//
// 勾的人 ＋（auto 时）名册里按练度补的人，补到 `autoPool` 为止。
//
// ★ 这一步非有不可：`candidates_for` 是**按名单遍历**的，空名单一个候选都不产生，
// 搜索会当场返回"几何剪枝后一个候选都不剩" —— 而那句话把原因指向坐标口径，完全
// 指错方向。界面上那句「程序还可以再挑人补位」也只有在 mode=auto 时才是真的。
//
// ⚠ 一处与 Python 的细微差别（登记）：Python 是拿**计划名册**（文件）判"名册里有没有
// 这一位"，Go 这边手上只有桥给的那份（同样来自名册，但字段少）。两者不一致时，
// 引擎会在 `covered.entry_missing` 里**具名**报出来，不会静默少人。
func solvePool(c *appCtx) ([]string, string) {
	inRoster := map[string]bool{}
	if c.roster != nil {
		for _, op := range c.roster.Operators {
			inRoster[op.Name] = true
		}
	}
	kept := []string{}
	missing := []string{}
	for _, n := range c.squad {
		if inRoster[n] {
			kept = append(kept, n)
		} else {
			missing = append(missing, n)
		}
	}
	if c.mode == "only" {
		note := fmt.Sprintf("只用勾的 %d 人", len(kept))
		if len(missing) > 0 {
			note += "（名册里没有：" + strings.Join(firstN(missing, 3), "、") + "）"
		}
		if len(kept) == 0 {
			note = "「只用我选的」但一个人都没勾——池子是空的，搜不出东西。" +
				"回去勾人，或按 M 换成「允许程序补充」。"
		}
		return kept, note
	}
	extra := []string{}
	want := autoPool - len(kept)
	if want < 0 {
		want = 0
	}
	if c.roster != nil && want > 0 {
		seen := map[string]bool{}
		for _, n := range kept {
			seen[n] = true
		}
		ops := append([]RosterOperator(nil), c.roster.Operators...)
		sortByLevelDesc(ops)
		for _, op := range ops {
			if len(extra) >= want {
				break
			}
			if !seen[op.Name] && inRoster[op.Name] {
				seen[op.Name] = true
				extra = append(extra, op.Name)
			}
		}
	}
	if len(kept) == 0 && len(extra) == 0 {
		return nil, "名册是空的，池子里一个人都没有。"
	}
	note := fmt.Sprintf("勾的 %d 人 + 名册按练度补 %d 人（共 %d 人）",
		len(kept), len(extra), len(kept)+len(extra))
	if len(missing) > 0 {
		note += "　名册里没有：" + strings.Join(firstN(missing, 3), "、")
	}
	return append(kept, extra...), note
}

// ---------------------------------------------------------------- 引擎那一侧

// solveStepView 是引擎 `solve` 段里的一层摘要。
type solveStepView struct {
	Depth  int      `json:"depth"`
	Tried  int      `json:"tried"`
	Kept   int      `json:"kept"`
	Stars  int      `json:"stars"`
	Line   string   `json:"line"`
	Who    []string `json:"who"`
	States int      `json:"states"`
}

// solveOutView 是引擎 `solve` 段里我们关心的那几栏（其余忽略）。
type solveOutView struct {
	OK        bool            `json:"ok"`
	Plan      json.RawMessage `json:"plan"`
	Verdict   json.RawMessage `json:"verdict"`
	Stars     int             `json:"stars"`
	Steps     []solveStepView `json:"steps"`
	Depth     int             `json:"depth"`
	Evaluated int             `json:"evaluated"`
	Note      string          `json:"note"`
	//: 引擎**回声**的助战名（它从 spec 的 `support` 收下、原样放进 `SolveOut.Support`）。
	//: 这一栏是"界面确实把助战送到了引擎那一步"的**唯一凭据** —— 自检里有一条真往返
	//: 断言读的就是它（屏上自己记着名字不算数：那只证明界面知道）。
	Support string `json:"support"`
}

// solveRoundMsg 是「一轮引擎调用回来了」。
type solveRoundMsg struct {
	taskID uint64
	round  int
	depth  int
	out    solveOutView
	err    error
}

// solveTickMsg 是**心跳**：每秒一跳，与引擎轮次无关。
//
// ★ 2026-09-28 博士实测报的：「解算屏似乎完全没有开始解算」「读秒更新不是按秒跳的」。
// 根因是这一屏原先**只在轮次回来时**才有消息可处理，而一轮是分钟级（实测：同一关，
// 小参数 2.3s、生产参数 113s）⇒ 屏上秒数冻住、日志停在 0.0s、进度条钉在 5%，
// 看着与"卡死"一模一样 —— 其实引擎正在烧 CPU。
// 修法：屏自己带一个**独立计数**的秒表（`elapsed`），每秒一跳、每跳重画一次。
type solveTickMsg struct{ taskID uint64 }

func solveTickCmd(taskID uint64) tea.Cmd {
	return tea.Tick(time.Second, func(time.Time) tea.Msg { return solveTickMsg{taskID: taskID} })
}

// solveParams 是这一屏跑一轮需要的全部输入（起屏时定下来，之后不变）。
type solveParams struct {
	levelID    string
	rosterPath string
	difficulty string
	pool       []string
	perOp      int
	beam       int
	//: 助战干员的名字（口径 1／3：用助战 ⇒ 编队上限 13）。它随请求进引擎的
	//: `solve` spec（`support` 键），**不进 `pool`** —— 搜索只在自己的干员里挑组合。
	support string
}

// runSolveRoundCmd 起**一轮**解算。
//
// 异步（`tea.Cmd`）：一轮是分钟级的，界面线程绝不能被它卡住 —— 卡住了连"中止"都按不动。
func runSolveRoundCmd(p solveParams, depth int) tea.Cmd {
	return func() tea.Msg {
		ec, err := newEngineClient()
		if err != nil {
			return solveRoundMsg{depth: depth, err: err}
		}
		raw, err := ec.callSolve(p, depth, solveTimeout)
		if err != nil {
			return solveRoundMsg{depth: depth, err: err}
		}
		var out solveOutView
		if err := json.Unmarshal(raw, &out); err != nil {
			return solveRoundMsg{depth: depth,
				err: fmt.Errorf("★ 引擎的 solve 段解不开：%v", err)}
		}
		return solveRoundMsg{depth: depth, out: out}
	}
}

// ---------------------------------------------------------------- 屏

type solveScreen struct {
	p        solveParams
	ladder   []int
	idx      int // 正在跑阶梯的第几项（0 起）
	lines    []string
	evals    int
	t0       time.Time
	running  bool
	done     bool
	err      string
	best     solveOutView // 跨轮保留最好的（"加人未必更好"）
	haveBest bool
	//: ★ 心跳的**独立计数**（博士 2026-09-28 要的）：每秒 +1，由 `solveTickMsg` 驱动。
	//: 显示用它，**不用** `time.Since(t0)` —— 后者只在重画时取一次，屏不重画就冻住。
	elapsed int
	//: spinner 的帧号（同一跳里 +1）：让"它在动"这件事一眼可见。
	spin           int
	taskID         uint64
	task           *solveTask
	retired        []*solveTask
	live           progress.Snapshot
	completedEvals int
}

func (s *solveScreen) startRound() tea.Cmd {
	if s.task != nil {
		s.retired = append(s.retired, s.task)
	}
	s.live = progress.Snapshot{Phase: "preparing", MaxDepth: s.currentDepth()}
	s.task = startSolveTask(s.taskID, s.idx, s.p, s.currentDepth())
	return s.task.next()
}

func (s *solveScreen) close() {
	s.running = false
	if s.task != nil {
		s.task.cancel()
	}
	for _, t := range s.retired {
		t.cancel()
	}
}

func (s *solveScreen) waitClosed() {
	s.close()
	if s.task != nil {
		<-s.task.exited
	}
	for _, t := range s.retired {
		<-t.exited
	}
}

// spinnerFrames 是解算中那个转轮（ASCII，任何终端都画得出）。
var spinnerFrames = []string{"|", "/", "-", "\\"}

func newSolveScreen(p solveParams, ladder []int) *solveScreen {
	p.pool = append([]string(nil), p.pool...)
	s := &solveScreen{p: p, ladder: append([]int(nil), ladder...), t0: time.Now(), running: true,
		taskID: solveTaskSequence.Add(1)}
	//: 第一轮的"已发出"也要写进日志：否则从"开始解算……"到第一轮回来（分钟级）
	//: 中间一个字都没有 —— 那正是博士看到的"像没开始"。
	s.logRoundStart()
	return s
}

// logRoundStart 记一行"本轮已发给引擎"（带这一轮的参数）。
func (s *solveScreen) logRoundStart() {
	s.log(fmt.Sprintf("第 %d/%d 轮：最多 %d 人、beam %d、per-op %d　已发给引擎，等它回来",
		s.idx+1, len(s.ladder), s.currentDepth(), s.p.beam, s.p.perOp))
}

func (*solveScreen) title() string { return "解算" }
func (*solveScreen) help() string {
	return "Q 中止（退回上一步）· 跑完自动进结果屏"
}

// log 往日志里追加一行（只留最后 14 行，照 Python）。
func (s *solveScreen) log(msg string) {
	s.lines = append(s.lines, fmt.Sprintf("%6.1fs  %s",
		time.Since(s.t0).Seconds(), msg))
	if len(s.lines) > 14 {
		s.lines = s.lines[len(s.lines)-14:]
	}
}

// currentDepth 是这一轮的人数上限。
func (s *solveScreen) currentDepth() int {
	if s.idx < len(s.ladder) {
		return s.ladder[s.idx]
	}
	if len(s.ladder) > 0 {
		return s.ladder[len(s.ladder)-1]
	}
	return depthStart
}

// headText 复刻 `_head_text`：正常版四行，**极矮窗口压成两行**（一行都不丢，
// 丢的只是换行 —— 博士 2026-09-18：「保证终端窗口小的时候也要让玩家看到所有内容」）。
func (s *solveScreen) headText(c *appCtx) string {
	code, levelID := "（未选关）", ""
	if c.stage != nil {
		code, levelID = c.stage.Code, c.stage.LevelID
	}
	elapsed := float64(s.elapsed)
	depth := s.currentDepth()
	capNote := ""
	if c.deployLimit > 0 {
		capNote = fmt.Sprintf("　本关最多可部署 %d 人", c.deployLimit)
	}
	if c.h > 0 && c.h < tinyHeight {
		return fmt.Sprintf("%s　本轮最多 %d 人%s\n已评估 %d 个候选　已用 %.0f 秒",
			code, depth, capNote, s.evals, elapsed)
	}
	out := fmt.Sprintf("关卡：%s（%s）\n本轮最多 %d 人%s\n", code, levelID, depth, capNote)
	//: 编队那一行是**上下文**，不是这一屏的主角（上一屏刚选过）⇒ 矮窗口下先收它。
	//: 同一条「数据 > 说明」的优先级。
	if c.h == 0 || c.h >= compactHeight {
		squad := "（不指定，全名册）"
		if len(c.squad) > 0 {
			squad = strings.Join(c.squad, "、")
		}
		//: 助战是**编队里的一格**（口径 1：占了第 13 格）⇒ 写在编队那一行里，
		//: 与"程序可以补充人"那句并列。它**不在搜索的候选池**里（搜索只挑自己的）。
		if c.supportForSolve() != "" {
			squad += "　＋助战 " + c.supportForSolve()
		}
		mode := "允许补充"
		if c.mode == "only" {
			mode = "只用我选的"
		}
		out += fmt.Sprintf("编队：%s　模式：%s\n", squad, mode)
	}
	return out + fmt.Sprintf("已评估 %d 个候选　已用 %.0f 秒", s.evals, elapsed)
}

// progress 是当前层完成尝试占真实状态总数的比例，不是整场搜索完成率。
// 分母未知时显示等待；早停可能在未遍历整层时完成。
func (s *solveScreen) progress() float64 {
	if s.done {
		return 100
	}
	if len(s.ladder) == 0 {
		return 0
	}
	if s.live.Total <= 0 {
		return 0
	}
	return 100 * float64(s.live.Completed) / float64(s.live.Total)
}

func solvePhaseLabel(phase string) string {
	switch phase {
	case "preparing", "":
		return "准备中"
	case "candidates":
		return "候选已生成"
	case "evaluating":
		return "评估中"
	case "filtering":
		return "筛选中"
	case "completed":
		return "本轮完成"
	case "failed":
		return "失败"
	default:
		return phase
	}
}

func (s *solveScreen) view(c *appCtx) string {
	var b strings.Builder
	head := "解算中"
	if s.running {
		//: 转轮 ＋ 轮次：一眼看出"它在动"、且在第几轮（心跳那件事的可见面）
		head = fmt.Sprintf("解算中 %s　第 %d/%d 轮",
			spinnerFrames[s.spin%len(spinnerFrames)], s.idx+1, len(s.ladder))
	}
	b.WriteString(styleTitle.Render(head) + "\n")
	b.WriteString(s.headText(c) + "\n\n")
	b.WriteString(fmt.Sprintf("状态：%s　搜索深度 %d/%d　beam %d　per-op %d\n",
		solvePhaseLabel(s.live.Phase), s.live.Depth, s.currentDepth(), s.p.beam, s.p.perOp))
	b.WriteString(fmt.Sprintf("几何候选 %d　当前层完成 %d/%d　保留 %d　最佳 %d 星\n",
		s.live.Candidates, s.live.Completed, s.live.Total, s.live.Kept, s.live.BestStars))
	if s.live.BestLine != "" {
		b.WriteString("当前最佳：" + s.live.BestLine + "\n")
	}
	if s.live.Total > 0 {
		b.WriteString("当前层尝试进度：" + progressBar(s.progress(), c.w) + "\n")
	} else {
		b.WriteString("当前层尝试进度：等待后端提供分母\n")
	}
	if s.err != "" {
		b.WriteString(styleTitle.Render("失败：") + s.err + "\n")
	}
	b.WriteString(strings.Join(s.lines, "\n"))
	return b.String()
}

// progressBar 画一条不含 ANSI 的进度条（宽度按窗口，最窄 10 列）。
//
// 与 Python 的 `ProgressBar` 只对齐"看得见进度"这件事，**不追求逐字符同形** ——
// 那是另一套控件的地盘，这里没有可对拍的参照物（**登记为分歧**）。
func progressBar(pct float64, width int) string {
	w := width - 12
	if w < 10 {
		w = 10
	}
	if w > 60 {
		w = 60
	}
	if pct < 0 {
		pct = 0
	}
	if pct > 100 {
		pct = 100
	}
	filled := int(float64(w) * pct / 100.0)
	return fmt.Sprintf("[%s%s] %3.0f%%", strings.Repeat("█", filled),
		strings.Repeat("·", w-filled), pct)
}

func (s *solveScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	switch {
	case keyIs(k, "q"), keyIs(k, "esc"):
		//: 中止 ⇒ **退回上一步**（不是退出程序）。Python 那边原先写成 `app.exit()`，
		//: Footer 上写着「中止」按下去却把整个程序关掉 —— 博士 2026-09-17 裁定改掉。
		s.close()
		s.log("已中止（取消引擎并退回上一步）")
		return s, action{kind: actBack}
	}
	return s, action{kind: actNone}
}

// onMsg 处理异步回来的那一轮结果。
//
// 收 `*root` 而不是 `*appCtx`：跑完要把结果屏**压上去**，而"压屏"是屏栈的事
// （见 `msgScreen` 的说明）。
func (s *solveScreen) onMsg(r *root, msg tea.Msg) action {
	c := r.ctx
	//: ★ 心跳：每秒一跳。**独立计数**（不看 `time.Since`），跑着就再排下一跳；
	//: 结束了就停（不再排），免得空转重画。
	if tick, ok := msg.(solveTickMsg); ok {
		if !s.running || tick.taskID != s.taskID {
			return action{kind: actNone}
		}
		s.elapsed++
		s.spin++
		return action{kind: actNone, cmd: solveTickCmd(s.taskID)}
	}
	if m, ok := msg.(solveProgressMsg); ok {
		if !s.running || m.taskID != s.taskID || m.round != s.idx {
			return action{kind: actNone}
		}
		previous := s.live
		s.live = m.snapshot
		s.evals = s.completedEvals + m.snapshot.Evaluated
		if m.snapshot.Message != "" && (previous.Message != m.snapshot.Message || previous.Phase != m.snapshot.Phase || previous.Depth != m.snapshot.Depth) {
			s.log(m.snapshot.Message)
		}
		if s.task != nil {
			return action{kind: actNone, cmd: s.task.next()}
		}
		return action{kind: actNone}
	}
	m, ok := msg.(solveRoundMsg)
	if !ok || !s.running || m.taskID != s.taskID || m.round != s.idx {
		return action{kind: actNone}
	}
	if m.err != nil {
		s.err = m.err.Error()
		s.running = false
		s.done = true
		s.log("失败：" + reasonOf(m.err.Error()))
		return action{kind: actNone}
	}
	s.completedEvals += m.out.Evaluated
	s.evals = s.completedEvals
	for _, st := range m.out.Steps {
		s.log(fmt.Sprintf("第 %d 人：生成 %d 个状态、留 %d，最佳 %s",
			st.Depth, st.States, st.Kept, st.Line))
	}
	if !s.haveBest || m.out.Stars > s.best.Stars {
		s.best, s.haveBest = m.out, true
	}
	if m.out.OK {
		s.done = true
		s.running = false
		s.log("找到三星方案。")
		return s.finish(c, m.out)
	}
	//: 没找到三星 ⇒ 加深再试一轮（每深一层都要重跑一遍，日志里已经写了）
	if s.idx+1 < len(s.ladder) {
		s.log(fmt.Sprintf("%d 人以内没找到三星，加深到 %d 人再试一轮",
			m.depth, s.ladder[s.idx+1]))
		s.idx++
		s.logRoundStart()
		return action{kind: actNone, cmd: s.startRound()}
	}
	s.done = true
	s.running = false
	note := m.out.Note
	if note == "" {
		note = fmt.Sprintf("加深到 %d 人（本关可部署上限）仍没找到三星，把最接近的那个方案交给你",
			m.depth)
	}
	s.log(note)
	return s.finish(c, m.out)
}

// finish 把结果写进 `appCtx`（结果屏读它）。
//
// 跨轮保留最好的：**加一个人未必更好** —— 费用曲线会被推后（Python 那边的注释点名了
// SR-EX-8 上"加机械师反而失败"）。所以只在最后一轮没找到三星时，交**所有轮里最好的**
// 那个，并且把 note 一起带上（至少让人看见差在哪）。
//
// ⚠ 结果屏还没落地 ⇒ 这里**不静默什么都不做**（那会变成"看起来跑完了"），而是在日志
// 里明说一句。结果屏写出来之后，这一处改成 push 它（一行的事）。
func (s *solveScreen) finish(c *appCtx, out solveOutView) action {
	use := out
	if s.haveBest && !out.OK {
		use = s.best
	}
	c.solvePlan = use.Plan
	c.solveVerdict = use.Verdict
	c.solveStars = use.Stars
	c.solveNote = use.Note
	c.solveSteps = use.Steps
	c.solveEvaluated = s.evals
	c.solveSeconds = time.Since(s.t0).Seconds()
	if c.solveNote == "" && use.Stars < 3 {
		c.solveNote = "没找到三星方案（可加大 --beam / --per-op）"
	}
	//: 压结果屏（Python 那边是 `push_screen(ResultScreen())`）
	return action{kind: actPush, push: newResultScreen()}
}
