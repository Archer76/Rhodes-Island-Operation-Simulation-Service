package main

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// # 登录屏（[0b]，对应 Python 的 `LoginScreen`，`app.py:693`）
//
// 五键：`L` 扫码登录 · `S` 切换账号 · `U` 补全账号信息 · `O` 退出账号 · `Esc` 返回。
//
// ## 三件必须做对的事（照 Python 的注释）
//
//  1. **轮询在后台跑**：`login_by_qr` 默认 2 秒一次、最长 180 秒。Go 这边整条链在
//     **常驻桥进程**里（见 `bridgesession.go` 的文件头：一次一进程时那个后台线程
//     活不过 `login_start` 那一问），界面侧用 `tea.Cmd` + 定时消息驱动轮询，
//     界面线程一秒都不卡。
//  2. **回调里不许直接碰界面**：Python 那边 `on_qr`/`on_status` 在后台线程被调，只能
//     `post_message`；Go 这边每一次轮询就是一条消息，天然同构。
//  3. **二维码不落进本屏**：它单独一屏（`qr.go`）。本屏只负责把码弹出去、把状态行
//     更新到那张屏上（那张屏不在栈顶时，状态就写回本屏的提示区）。
//
// ## `Esc` 在这里是三态（博士 2026-09-17 / 09-18 的裁定）
//
//   - **已经登着账号** ⇒ 直接回主界面。原先还会问一句"确定不登录吗"——他刚扫码登进去、
//     按 Esc 想回主界面，那一问是荒唐的，问的是他已经做完的事；
//   - **手上还没有账号** ⇒ 问「本次不登录 / 以后都不问」。答"以后都不"写进配置
//     （`login_prompt=""`），此后启动不再自动进这个向导；答"本次"什么都不写；
//   - **问屏上再按 Esc** ⇒ 取消这一问（回本屏继续扫），**不是**答"不登录"。
//     （这一点由 `AskScreen` 的 Esc 语义天然给出：它带着 nil 弹回去，回调什么都不做。）
//
// ## 登录成功后**直接弹回主界面**
//
// 不再留在本屏等玩家按 Esc（同一条裁定）。回去时带一句话显示在账号行上：**登回当前这个
// 号 / 登回本机已有的另一个号 / 新号** 三种情形要分开说 —— 不说的话，前两种会让人以为
// 多了个账号（账号数其实没变）。

type loginScreen struct {
	busy    bool
	filling bool
	asking  bool

	ping    *pingData
	accts   *accountsData
	loadErr string

	//: 扫码那块与补全那块的提示（对应 Python 的 `#login-note`）
	note string
	//: 账号列表那块的提示/补全结果（对应 `#login-accounts` 的尾注）
	acctNote string

	knownBefore map[string]bool
	curBefore   string

	sess    *bridgeSession
	qr      *qrScreen
	polling bool
}

func newLoginScreen() *loginScreen {
	return &loginScreen{knownBefore: map[string]bool{},
		note: "按 L 申请二维码，然后用**森空岛 APP** 扫。"}
}

func (*loginScreen) title() string { return "登录" }
func (*loginScreen) help() string {
	return "L 扫码登录 · S 切换账号 · U 补全账号信息 · O 退出账号 · Esc 返回"
}

// ---------------------------------------------------------------- 异步消息

type loginInfoMsg struct {
	ping  *pingData
	accts *accountsData
	err   error
}

type loginStartMsg struct {
	sess *bridgeSession
	st   *loginStartData
	err  error
}

type loginPollMsg struct {
	pl  *loginPollData
	err error
}

// loginTickMsg 是「该再问一次进度了」（不是桥的应答，是本屏自己排的定时）。
type loginTickMsg struct{}

// loginActionMsg 是 S/U/O 三条动作的结果。
type loginActionMsg struct {
	what   string // switch / logout / fill
	err    error
	fill   *fillResult
	roster *rosterData
}

// ---------------------------------------------------------------- 命令（异步）

// loginInfoCmd 读一次「登录态 ＋ 本机账号」（都是本地文件，但要走桥 ⇒ 异步）。
func loginInfoCmd() tea.Cmd {
	return func() tea.Msg {
		p, perr := fetchPing()
		if perr != nil {
			return loginInfoMsg{err: perr}
		}
		a, aerr := fetchAccounts()
		if aerr != nil {
			return loginInfoMsg{ping: p, err: aerr}
		}
		return loginInfoMsg{ping: p, accts: a}
	}
}

// loginStartCmd 起一次扫码（**在常驻会话里**）。
func loginStartCmd() tea.Cmd {
	return func() tea.Msg {
		sess, err := newBridgeSession()
		if err != nil {
			return loginStartMsg{err: err}
		}
		st, err := sess.loginStart(40 * time.Second)
		if err != nil {
			sess.close()
			return loginStartMsg{err: err}
		}
		return loginStartMsg{sess: sess, st: st}
	}
}

// loginPollCmd 问一次进度。
func loginPollCmd(sess *bridgeSession) tea.Cmd {
	return func() tea.Msg {
		pl, err := sess.loginPoll(30 * time.Second)
		return loginPollMsg{pl: pl, err: err}
	}
}

// loginTickCmd 排下一次轮询。
//
// ★ 间隔 2 秒与 Python 的 `login_by_qr(interval=2.0)` 同值；而 Go 这边每一问都是一次
// **子进程往返**（桥是"一行进一行出"的），所以实际节拍约 2 秒 ＋ 一次进程启动。
// **登记为分歧**：Python 在同一进程里读一个计数器，节拍更准；这里多出来的那点延迟
// 只影响状态行的刷新快慢，不影响能不能扫上。
func loginTickCmd() tea.Cmd {
	return tea.Tick(2*time.Second, func(time.Time) tea.Msg { return loginTickMsg{} })
}

func loginActionCmd(what, uid string) tea.Cmd {
	return func() tea.Msg {
		var err error
		switch what {
		case "switch":
			err = activateAccount(uid)
		case "logout":
			err = logoutAccount()
		}
		if err != nil {
			return loginActionMsg{what: what, err: err}
		}
		//: 名册必须**重读**：`load_roster()` 认的是当前账号，不重读就还是上一个号的。
		rr, rerr := fetchRoster()
		return loginActionMsg{what: what, roster: rr, err: rerr}
	}
}

func loginFillCmd() tea.Cmd {
	return func() tea.Msg {
		res, err := fillAccounts()
		if err != nil {
			return loginActionMsg{what: "fill", err: err}
		}
		//: 补全可能刚把**游戏 uid** 定下来，而名册是按游戏 uid 存的文件 ⇒ 顺手重读一次
		rr, _ := fetchRoster()
		return loginActionMsg{what: "fill", fill: res, roster: rr}
	}
}

// ---------------------------------------------------------------- 渲染

// statusText 复刻 `_status()`：当前账号 ＋ 凭据三态 ＋ 名册来源。
func (s *loginScreen) statusText(c *appCtx) string {
	if s.loadErr != "" {
		return "★ 读登录态失败：" + reasonOf(s.loadErr)
	}
	uid := ""
	if s.ping != nil {
		uid = s.ping.UID
	}
	head := ""
	if uid != "" {
		head = "当前账号：" + s.who(uid) + "\n"
	}
	switch {
	case s.ping == nil:
		head = "（正在读登录态……）\n"
	case s.ping.CredState == "cred":
		head += "已保存凭据：有效期内可直接校验；过期会由 hgToken 静默重铸。\n"
	case s.ping.CredState == "hgtoken":
		head += "已保存 hgToken（**尚未铸成 cred**）。\n"
	default:
		head += "本机还没有任何森空岛凭据。\n"
	}
	if c.roster == nil {
		return head + "没有名册。跳过登录不影响流程，编队那一步手动输名字即可。"
	}
	return head + fmt.Sprintf("名册来源：%s，共 %d 名。\n"+
		"登录只决定名册要不要刷新，不决定流程能不能走完。",
		c.roster.Source, len(c.roster.Operators))
}

// who 复刻 `_who`：**游戏用户名 ＋ 游戏 uid**（登录账号 id 只作附注）。
//
// 还没问过森空岛时如实说"未知"并给出那一键（`U`）—— 空白会让人以为程序坏了。
func (s *loginScreen) who(uid string) string {
	if uid == "" {
		return "（没有登录账号）"
	}
	if s.accts != nil {
		for _, r := range s.accts.Rows {
			if r.UID == uid {
				nick := r.Nick
				if nick == "" {
					nick = "游戏用户名未知，按 U 问一次"
				}
				game := r.GameUID
				if game == "" {
					game = "未知，按 U 问一次"
				}
				return fmt.Sprintf("%s　游戏uid=%s　（登录账号 %s）", nick, game, uid)
			}
		}
	}
	return fmt.Sprintf("（登录账号 %s；游戏用户名与 uid 未知，按 U 问一次）", uid)
}

// accountsText 复刻 `_refresh_accounts` 那一块：逐行账号 ＋ 尾注。
func (s *loginScreen) accountsText() string {
	if s.accts == nil || len(s.accts.Rows) == 0 {
		return "本机还没有登录过的账号。"
	}
	lines := make([]string, 0, len(s.accts.Rows)+2)
	for _, r := range s.accts.Rows {
		lines = append(lines, r.Line)
	}
	//: 这两句从主界面搬到这里（Python 的注释：它本来就只在讲"退出"这件事，
	//: 而退出这个动作也在这块屏上；主界面留着要多占一行）。
	hint := "按 O 退出账号——凭据文件保留，之后可切回，不必重扫。"
	hint += "\n按 S 切换账号（同样不必重扫）。"
	needFill := false
	for _, r := range s.accts.Rows {
		if !r.Known {
			needFill = true
		}
	}
	if needFill {
		hint += "　按 U 补全游戏用户名与游戏 uid（联网，按一次问一次）。"
	}
	if s.acctNote != "" {
		hint = s.acctNote + "\n" + hint
	}
	lines = append(lines, hint)
	return strings.Join(lines, "\n")
}

func (s *loginScreen) view(c *appCtx) string {
	var b strings.Builder
	b.WriteString(styleTitle.Render("登录态") + "\n" + s.statusText(c) + "\n\n")
	b.WriteString(styleTitle.Render("本机登录过的账号") + "\n" + s.accountsText() + "\n\n")
	b.WriteString(styleTitle.Render("扫码登录") + "\n" + s.note)
	return b.String()
}

// ---------------------------------------------------------------- 交互

func (s *loginScreen) uid() string {
	if s.ping == nil {
		return ""
	}
	return s.ping.UID
}

func (s *loginScreen) update(c *appCtx, k tea.KeyMsg) (screen, action) {
	switch {
	case keyIs(k, "l"):
		if s.busy {
			return s, action{kind: actNone}
		}
		s.busy = true
		s.polling = true
		//: 快照**扫码之前**的账号状态：登录写盘之后那个号已经在列表里了，
		//: 不快照就分不清"登的是新号"还是"登回了老号"。
		s.knownBefore = map[string]bool{}
		if s.accts != nil {
			for _, r := range s.accts.Rows {
				s.knownBefore[r.UID] = true
			}
		}
		s.curBefore = s.uid()
		s.note = "正在申请二维码……"
		return s, action{kind: actNone, cmd: loginStartCmd()}
	case keyIs(k, "s"):
		if s.accts == nil || len(s.accts.Rows) == 0 {
			s.note = "本机没有登录过的账号。按 L 扫码登录。"
			return s, action{kind: actNone}
		}
		rows := make([]askRow, 0, len(s.accts.Rows))
		for _, r := range s.accts.Rows {
			rows = append(rows, askRow{value: r.UID, label: r.Line})
		}
		return s, action{kind: actPush,
			push: newAskScreen("切换账号",
				"凭据与名册都在这台机器上，切换不需要重新扫码。", rows),
			done: onAccountPicked}
	case keyIs(k, "u"):
		if s.busy || s.filling {
			return s, action{kind: actNone}
		}
		s.filling = true
		s.note = "正在问森空岛补全账号信息……"
		return s, action{kind: actNone, cmd: loginFillCmd()}
	case keyIs(k, "o"):
		if s.uid() == "" {
			return s, action{kind: actPush,
				push: newAskScreen("没有可退出的账号",
					"当前本来就没有登录的账号。\n按 L 扫码登录；登过的号按 L 再按 S 可以切回。",
					[]askRow{{value: "ok", label: "知道了"}}),
				done: nil}
		}
		others := 0
		if s.accts != nil {
			others = len(s.accts.Rows) - 1
		}
		body := "退出后当前账号的名册不再显示，会降级成 MAA OperBox（没有专精与模组等级）。\n" +
			"**凭据与名册文件一个都不删。**"
		if others > 0 {
			body += fmt.Sprintf("\n本机另存着 %d 个登过的账号，之后按 S 可以切回。", others)
		} else {
			body += "\n之后按 L 重新扫码即可登回。"
		}
		return s, action{kind: actPush,
			push: newAskScreen("退出账号", body,
				[]askRow{{value: "yes", label: "确认退出"}}),
			done: onLogoutConfirmed}
	case keyIs(k, "esc"):
		//: ★ 三态的第一条：**已经登着账号 ⇒ 直接回主界面**，不再问那一句
		if s.uid() != "" {
			s.stopLogin()
			return s, action{kind: actBack}
		}
		//: 手上还没有账号 ⇒ 问「本次不登录 / 以后都不问」
		return s, action{kind: actPush,
			push: newAskScreen("不登录？",
				"不登录也能继续：编队那一步手动输名字。",
				[]askRow{{value: "once", label: "本次不登录"},
					{value: "never", label: "以后都不问"}}),
			done: onLoginSkipAnswered}
	}
	return s, action{kind: actNone}
}

// stopLogin 收掉扫码会话（关进程；超时那条路也靠它把挂着的读放掉）。
func (s *loginScreen) stopLogin() {
	s.polling = false
	s.busy = false
	if s.sess != nil {
		s.sess.close()
		s.sess = nil
	}
}

// backNote 复刻 `_back_note`：登录成功后带回主界面、显示在账号行上的那句话。
//
// **登到已有账号上要明说**：本机原先就登过这个号时，这次扫码只是刷新了凭据、账号条数
// 没变 —— 不提醒的话，人会以为多了一个号。
func (s *loginScreen) backNote() string {
	uid := s.uid()
	who, game := "游戏用户名未知（按 U 问一次）", "未知（按 U 问一次）"
	if s.accts != nil {
		for _, r := range s.accts.Rows {
			if r.UID == uid {
				if r.Nick != "" {
					who = r.Nick
				}
				if r.GameUID != "" {
					game = r.GameUID
				}
			}
		}
	}
	msg := fmt.Sprintf("已登录：%s　游戏uid=%s", who, game)
	switch {
	case uid != "" && uid == s.curBefore:
		msg += "；这个号**本来就登录着**，这次只刷新了凭据（账号没有变多）。"
	case uid != "" && s.knownBefore[uid]:
		msg += "；这个号**本机已经登录过**——凭据更新了，账号没有变多，按 S 可以切回其他号。"
	default:
		msg += "；这是**新账号**，已加进本机账号列表（按 L 进登录屏后按 S 可切回旧号）。"
	}
	return msg
}

func (s *loginScreen) onMsg(r *root, msg tea.Msg) action {
	c := r.ctx
	switch m := msg.(type) {
	case loginInfoMsg:
		s.ping, s.accts = m.ping, m.accts
		if m.err != nil {
			s.loadErr = m.err.Error()
		} else {
			s.loadErr = ""
		}
		return action{kind: actNone}

	case loginStartMsg:
		if m.err != nil {
			s.busy = false
			s.note = "★ 申请二维码失败：" + reasonOf(m.err.Error())
			return action{kind: actNone}
		}
		s.sess = m.sess
		if m.st.QRNote != "" {
			//: 编不出来就把**原因**说出来（别给一张空图），会话也收掉
			s.note = "★ 二维码编不出来：" + m.st.QRNote
			s.stopLogin()
			return action{kind: actNone}
		}
		m4, err := qrMatrixFromRows(m.st.QRMatrix)
		if err != nil {
			s.note = "★ 二维码矩阵有问题：" + err.Error()
			s.stopLogin()
			return action{kind: actNone}
		}
		s.qr = newQrScreen(m4, "等待扫码……")
		s.note = "二维码已弹出（全屏居中）。有效期约 2 分钟；Esc 关掉它，按 L 可重新申请。"
		//: 弹码 ＋ 立刻排第一次轮询
		return action{kind: actPush, push: s.qr, cmd: loginPollCmd(s.sess)}

	case loginTickMsg:
		if !s.polling || s.sess == nil {
			return action{kind: actNone}
		}
		return action{kind: actNone, cmd: loginPollCmd(s.sess)}

	case loginPollMsg:
		if m.err != nil {
			s.note = "★ 取扫码进度失败：" + reasonOf(m.err.Error())
			s.stopLogin()
			return action{kind: actNone}
		}
		//: 状态行落在**二维码那张屏**上（它不在栈顶时写回本屏 —— 与 Python 的
		//: `_qr_screen` 判断同口径）
		text := m.pl.Text
		if text == "" {
			text = "等待扫码……"
		}
		if s.qr != nil && r.top() == screen(s.qr) {
			s.qr.setNote(text + "　（Esc 关掉这张码）")
		} else {
			s.note = text
		}
		switch m.pl.Phase {
		case "done":
			//: ① 二维码收掉（一张作废的码留在屏上只会诱人白扫）② 整屏弹回主界面，
			//: 并把那句话交给回调（照 Python 的 `_done`：先 pop 码屏再 dismiss 自己）
			s.stopLogin()
			if s.qr != nil && r.top() == screen(s.qr) {
				r.pop(nil)
			}
			note := s.backNote()
			//: 登录成功 ⇒ 那条「以后都不登录」不该再拦着他（Python 的同一行）
			_ = saveConfig("login_prompt", "")
			r.pop(note)
			s.qr = nil
			return action{kind: actNone, cmd: loginInfoCmd()}
		case "failed":
			s.note = "★ 登录失败：" + reasonOf(m.pl.Text)
			s.stopLogin()
			if s.qr != nil && r.top() == screen(s.qr) {
				r.pop(nil)
				s.qr = nil
			}
			return action{kind: actNone}
		}
		return action{kind: actNone, cmd: loginTickCmd()}

	case loginActionMsg:
		s.filling = false
		if m.err != nil {
			s.note = "★ " + m.what + " 失败：" + reasonOf(m.err.Error())
			return action{kind: actNone}
		}
		if m.roster != nil {
			c.roster = m.roster
			c.rosterErr = ""
		}
		switch m.what {
		case "fill":
			s.filling = false
			if m.fill != nil && len(m.fill.Lines) > 0 {
				s.note = strings.Join(m.fill.Lines, "\n") +
					"\n已记在本地账号表里，下次不必再问。"
			} else {
				s.note = "没有需要补的账号（每个号的游戏用户名与游戏 uid 都已记下）。"
			}
		case "switch":
			s.acctNote = "已切换账号，名册已按这个账号重读。"
			s.note = "已切换。"
		case "logout":
			s.acctNote = "已退出账号（凭据与名册文件都还在，按 S 可切回）。"
			s.note = "已退出账号。"
		}
		return action{kind: actNone, cmd: loginInfoCmd()}
	}
	return action{kind: actNone}
}

// ---------------------------------------------------------------- 回调（包级，照本仓的屏风格）

// onAccountPicked 是「切换账号」那张问屏的回调。
func onAccountPicked(r *root, res any) {
	uid, _ := res.(string)
	if uid == "" {
		return // Esc ⇒ 取消
	}
	sc, ok := r.top().(*loginScreen)
	if !ok {
		return
	}
	sc.note = "正在切换账号……"
	r.pending = loginActionCmd("switch", uid)
}

// onLogoutConfirmed 是「退出账号」那张问屏的回调。
func onLogoutConfirmed(r *root, res any) {
	v, _ := res.(string)
	if v != "yes" {
		return
	}
	sc, ok := r.top().(*loginScreen)
	if !ok {
		return
	}
	sc.note = "正在退出账号……"
	r.pending = loginActionCmd("logout", "")
}

// onLoginSkipAnswered 是「本次不登录 / 以后都不问」那张问屏的回调。
//
// 答"以后都不"要写进配置（此后启动不再自动进这个向导）；答"本次"什么都不写；
// 按 Esc 取消这一问时 `res` 是 nil ⇒ **什么都不做，留在登录屏**。
func onLoginSkipAnswered(r *root, res any) {
	v, _ := res.(string)
	switch v {
	case "never":
		_ = saveConfig("login_prompt", "")
		fallthrough
	case "once":
		if sc, ok := r.top().(*loginScreen); ok {
			sc.stopLogin()
		}
		r.pop(nil) //: 退回主界面
	}
}

// onLoginDone 是登录屏的回调（`_login_done`）：它带回一句话时，那句话显示在
// **账号行**上（登录可能刚落下一份新凭据，那一行原先是按旧状态画的），并刷新那块。
func onLoginDone(r *root, res any) {
	if s, ok := res.(string); ok && strings.TrimSpace(s) != "" {
		r.ctx.accountNote = s
	}
	r.pending = loginInfoCmd()
}
