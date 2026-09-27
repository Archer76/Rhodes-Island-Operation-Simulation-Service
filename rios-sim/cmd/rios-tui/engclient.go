package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// pythonEnv 是**所有** Python 子进程共用的环境拼装（一处拼装、四处调用）。
//
// 三项各自防一件事，都不是风格问题：
//
//   - `PYTHONIOENCODING`／`PYTHONUTF8`：中文 Windows 的缺省代码页是 GBK，桥上把协议行
//     按 UTF-8 写，只要有一个字符编不出来，回给我们的就是一个**空管道** —— 而空管道
//     与「桥死了」长得一模一样。
//   - `PYTHONDONTWRITEBYTECODE`：★ **这一项是从 `启动.cmd` 搬进来的**（2026-09-27，
//     迁移图 §12.9）。那个壳原先替我们设了它；入口换成 `rios-tui.exe` 之后**没有任何
//     一层设**，于是 Python 一 import 就往安装目录里的 `eng/ak_tactic/` 与
//     `eng/tools/` 写 `__pycache__` —— 可重建、不影响功能，但会把目录弄脏：卸载残留
//     与哈希清单都要跟着多解释一句。搬进这里之后，"双击 exe"这条路与当初那个壳等价。
//
// ★ 为什么抽成一个函数而不是各处 `append(os.Environ(), ...)` 抄三遍：抄三遍迟早会漂，
// 而漂的表现是「有的路子干净、有的路子脏」——正好是这一项要防的形状。
func pythonEnv() []string {
	return append(os.Environ(),
		"PYTHONIOENCODING=utf-8",
		"PYTHONUTF8=1",
		"PYTHONDONTWRITEBYTECODE=1",
	)
}

// # Go↔Python 的桥客户端（解释器与脚本都可指定，缺件必须**具名失败**）
//
// 为什么是子进程而不是同进程：R.I.O.S. 的方针是「UI 与模拟器转到 Go」（`docs/python-to-go-migration.md`），
// 但**登录与名册留在 Python 侧**（博士 2026-09-26 裁定）——森空岛那条链
// （申请 → 轮询 → 换 hgToken → 换 cred）在 `ak_tactic/skland.py` 里已经有一份实现，
// 在 Go 里再写一遍就是第二份，两份迟早会漂。所以 Go 侧起一个子进程，
// 走 `tools/rios_bridge.py` 那条**一行一个 JSON 对象**的协议。
//
// ★ 形状照 `ak_tactic/simgo/client.py`（那是 Python→Go 的引擎协议），**不发明第二套 IPC**：
// 请求 `{"id":N,"cmd":"..."}` 一行，应答一行 JSON。`id` 回填在应答里，用来对齐
// 「这一行答的是哪一问」——一次一进程时它看着多余，但协议是照着长连接写的，
// 少了它以后换成常驻进程就得改协议。
//
// ★ 两条**不许**：
//   · 解释器**不写死**：`RIOS_PYTHON` 指定，缺省才是 `python`（发布形态里玩家自己装
//     的 Python 未必在 PATH 上）。
//   · 找不到解释器／桥脚本时**具名失败**：说清缺什么、怎么补。**绝不**静默退化成
//     一个空名册 —— 空名册与「这个号一个干员都没有」在界面上长得一模一样。

const (
	//: 解释器：环境变量优先，缺省 `python`。
	envPython = "RIOS_PYTHON"
	//: 桥脚本：环境变量可**直接**指定（判据与排障用），缺省按 exe／cwd 往上找。
	envBridge = "RIOS_BRIDGE"
	//: 桥脚本在仓里的相对位置。
	bridgeRel = "tools/rios_bridge.py"
	//: 发布树里的位置（迁移图 §12.2：工程侧 Python 单放 `eng/`）。
	//: ★ 两种形态都要认，且**先认开发树那一种** —— 开发时两者可能同时存在，
	//: 而仓里那份才是权威（发布树是它的副本）。
	bridgeRelEng = "eng/tools/rios_bridge.py"
)

// RosterOperator 是名册里一名干员的**界面侧**字段（桥上只给这几个）。
//
// ⚠ 与 Python 的 `ak_tactic.tui.data.Operator` 还差一截：那边还有 `potential` /
// `trust` / `skills` / 模组 —— 要显示潜能／专精时得再给 `cmd_roster` 加字段。
//
// ★ 2026-09-27 补 `SubProfession`：选人屏的**子职业行**（参照 `app.py:1838` 的
// `PickerRow #sub-row`）要靠它 —— 那一行只列出**当前职业下真有的**子职业。
// ⚠ 两条名册来源的完整度不同（skland 带、OperBox 未必）⇒ 拿不到时是空串，
// 界面按参照的口径**整行隐藏**，不是显示一排空白项。
type RosterOperator struct {
	CharID        string `json:"char_id"`
	Name          string `json:"name"`
	Profession    string `json:"profession"`
	SubProfession string `json:"sub_profession"`
	Elite         int    `json:"elite"`
	Level         int    `json:"level"`
}

// rosterData 是一次 `roster` 命令的应答（非协议字段：`ok` / `error` 由 call 处理）。
type rosterData struct {
	Source    string           `json:"source"`   // skland / operbox
	Complete  bool             `json:"complete"` // 是否带专精与模组等级
	Note      string           `json:"note"`     // 降级时必须说明缺了什么
	Count     int              `json:"count"`
	Operators []RosterOperator `json:"operators"`
	//: 名册**文件**的路径。★ 解算屏要把它交给引擎：引擎读的是这份文件（那份名册
	//: 带 `potential`/`module`，而桥上只送 5 个字段），差这几个字段攻击力就会算错。
	Path string `json:"path"`
}

// bridgeResp 是协议应答。**一份结构当联合体用**：桥那边"一条命令一组字段"，
// 这里都接上，取用哪个由调用方决定（`encoding/json` 忽略没出现的键）。
// 应答里的 `trace` 等字段不接 —— 界面只显示 `error` 那一行。
type bridgeResp struct {
	ID        int              `json:"id"`
	OK        bool             `json:"ok"`
	Error     string           `json:"error"`
	Source    string           `json:"source"`
	Complete  bool             `json:"complete"`
	Note      string           `json:"note"`
	Count     int              `json:"count"`
	Operators []RosterOperator `json:"operators"`
	Path      string           `json:"path"`
	//: `ensure_level`：这一关的关卡 JSON 在不在、这次取回来多少字节。
	Level    string `json:"level"`
	DataPath string `json:"data_path"`
	Cached   bool   `json:"cached"`
	Bytes    int    `json:"bytes"`
	//: `check_updates`：上游数据与数据包各要不要更新。
	Checked    bool   `json:"checked"`
	DataUpdate bool   `json:"data_update"`
	DataLocal  string `json:"data_local"`
	DataRemote string `json:"data_remote"`
	PackLocal  string `json:"pack_local"`
	PackLatest string `json:"pack_latest"`
	PackUpdate bool   `json:"pack_update"`
	//: 扫码登录那两条（`login_start` / `login_poll`）。
	Phase    string   `json:"phase"`
	URL      string   `json:"url"`
	QRMatrix []string `json:"qr_matrix"`
	QRSize   int      `json:"qr_size"`
	QRNote   string   `json:"qr_note"`
	Text     string   `json:"text"`
	//: `ping`：当前账号与**凭据状态三态**（cred / hgtoken / none）—— 登录屏那句状态
	//: 就是照它说的（"已保存凭据…"／"已保存 hgToken（尚未铸成 cred）"／"本机还没有任何
	//: 森空岛凭据"）。不给这一栏，界面只能干说一句"已登录"。
	Proto     int    `json:"proto"`
	Python    string `json:"python"`
	UID       string `json:"uid"`
	CredState string `json:"cred_state"`
	//: `accounts`：当前账号、名册用的游戏 uid，以及逐条账号
	//: （界面显示的是**游戏用户名 ＋ 游戏 uid** —— 博士 2026-09-18 口径）。
	Current  string       `json:"current"`
	GameUID  string       `json:"game_uid"`
	Accounts []accountRow `json:"accounts"`
	//: `login_poll`：`status` 可空（还没扫过时是 null）⇒ 用指针接，别拿 0 顶替。
	Status *int `json:"status"`
	//: `fill_accounts`：补全各账号游戏用户名与 uid（联网那条）。
	//:
	//: ⚠ 那个总数在桥上叫 **`total`** 而不是 `accounts` —— `accounts` 这个键已经被上面
	//: 那条命令占成**数组**了，同一个键两种类型会让"一份结构当联合体用"当场编译不过
	//: （第一版就是这么撞上的，编译器直接指出来）。
	Total   int      `json:"total"`
	Todo    int      `json:"todo"`
	Filled  int      `json:"filled"`
	Skipped int      `json:"skipped"`
	Lines   []string `json:"lines"`
}

// accountRow 是 `accounts` 命令里的一行账号。
//
// ★ 界面上要显示的是**游戏用户名与游戏 uid**：登录账号 id 只是凭据文件名上的东西、
// 认不出人。`Line` 是 Python 侧 `describe_account` 排好的那一行（已剥掉富文本标记）
// —— 用它就与旧界面逐字同形。
type accountRow struct {
	UID     string `json:"uid"`
	GameUID string `json:"game_uid"`
	Nick    string `json:"nick"`
	Known   bool   `json:"known"`
	Current bool   `json:"current"`
	Line    string `json:"line"`
}

type bridgeClient struct {
	python string // 解释器（可执行名或绝对路径）
	script string // 桥脚本的绝对路径
}

// newBridgeClient 解析出「用哪个解释器、跑哪个脚本」。
//
// 两件缺一不可，缺哪个都要**具名**报出来（连"找过哪些路径"一起给）。
func newBridgeClient() (*bridgeClient, error) {
	py := strings.TrimSpace(os.Getenv(envPython))
	if py == "" {
		py = "python"
	}
	script, tried := findBridgeScript()
	if script == "" {
		return nil, fmt.Errorf("★ 找不到桥脚本 %s。找过这些位置：\n    %s\n"+
			"  它是仓里的一部分（与界面同一次提交），找不到说明**构建产物与仓分家了**：\n"+
			"    用 %s=<桥脚本的绝对路径> 显式指定，或把 exe 放回仓里再跑",
			bridgeRel, strings.Join(tried, "\n    "), envBridge)
	}
	return &bridgeClient{python: py, script: script}, nil
}

// findBridgeScript 依次找：`RIOS_BRIDGE` → exe 所在目录往上 5 层 → cwd 往上 5 层；
// 每一层先看 `tools/rios_bridge.py`（开发树），再看 `eng/tools/rios_bridge.py`（发布树）。
//
// 为什么要往上找而不是写死一个相对路径：发布形态是「双击 exe」，cwd 未必是 exe
// 所在目录；而开发时 exe 又常常建在 `out/` 里（比仓根低一层）。逐层往上找
// 两头都照顾得到，找到的**第一个**就是它。
//
// ★ 发布树多一个 `eng/`：迁移图 §12.2 把工程侧 Python 单放一个目录（登录／名册／
// 建库都走它）。不多认这一层的话，双击启动会报「找不到桥脚本」，而它明明就躺在
// `eng/tools/` 里 —— 那种「缺件报错本身是错的」最难查。
func findBridgeScript() (string, []string) {
	tried := []string{}
	hit := func(cand string) bool {
		tried = append(tried, cand)
		if st, err := os.Stat(cand); err == nil && !st.IsDir() {
			return true
		}
		return false
	}
	if v := strings.TrimSpace(os.Getenv(envBridge)); v != "" {
		if hit(v) {
			return v, tried
		}
	}
	roots := []string{}
	if exe, err := os.Executable(); err == nil {
		roots = append(roots, filepath.Dir(exe))
	}
	if wd, err := os.Getwd(); err == nil {
		roots = append(roots, wd)
	}
	for _, root := range roots {
		//: ★ 发布形态**到此为止**：桥脚本要么在 `eng/tools/`，要么在 `tools/`
		//: （同级），再往上走会走出安装目录、借到旁边另一棵树的副本 ——
		//: 实测过一次（打包自查的负对照），理由见 `isReleaseTree`。
		if isReleaseTree(root) {
			for _, rel := range []string{bridgeRel, bridgeRelEng} {
				cand := filepath.Join(root, filepath.FromSlash(rel))
				if hit(cand) {
					return cand, tried
				}
			}
			continue
		}
		dir := root
		for i := 0; i < 5; i++ {
			for _, rel := range []string{bridgeRel, bridgeRelEng} {
				cand := filepath.Join(dir, filepath.FromSlash(rel))
				if hit(cand) {
					return cand, tried
				}
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break // 到盘根了
			}
			dir = parent
		}
	}
	return "", tried
}

// call 起一次子进程、发一行请求、读一行应答。
//
// `extra` 是请求里除 `id`/`cmd` 之外的字段（`activate` 要带 `uid`，其余命令用不上）。
// 一次一进程：名册这条本来就只要一次取数（几百毫秒），常驻进程要管生命周期、
// 僵尸与并发，这一屏还用不上。协议（`id` ＋ 一行 JSON）照常，换成常驻时调用方不用动。
func (b *bridgeClient) call(cmd string, id int, extra map[string]any,
	timeout time.Duration) (*bridgeResp, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	c := exec.CommandContext(ctx, b.python, b.script)
	//: 子进程的环境**一处拼装**（`pythonEnv`）：编码两项的由来见那里，第三项
	//: `PYTHONDONTWRITEBYTECODE` 是从 `启动.cmd` 搬进来的（§12.9）。
	c.Env = pythonEnv()

	stdin, err := c.StdinPipe()
	if err != nil {
		return nil, fmt.Errorf("★ 桥的 stdin 拿不到：%v", err)
	}
	var out, errBuf bytes.Buffer
	c.Stdout, c.Stderr = &out, &errBuf

	if err := c.Start(); err != nil {
		return nil, startError(b, err)
	}
	payload := map[string]any{"id": id, "cmd": cmd}
	for k, v := range extra {
		payload[k] = v
	}
	req, err := json.Marshal(payload)
	if err != nil {
		_ = c.Process.Kill()
		_ = c.Wait()
		return nil, fmt.Errorf("★ 请求序列化失败：%v", err)
	}
	if _, err := stdin.Write(append(req, '\n')); err != nil {
		_ = c.Process.Kill()
		_ = c.Wait()
		return nil, fmt.Errorf("★ 给桥写请求失败：%v", err)
	}
	_ = stdin.Close()
	_ = c.Wait() //: 退出码不当判据：协议行在，就以应答为准（见下面的逐条检查）

	line := firstJSONLine(out.String())
	if line == "" {
		if ctx.Err() != nil {
			return nil, fmt.Errorf("★ 桥在 %s 内没给应答（已超时）。解释器 %s，脚本 %s",
				timeout, b.python, b.script)
		}
		return nil, fmt.Errorf("★ 桥没有给出应答行。解释器 %s，脚本 %s\n    stderr：%s",
			b.python, b.script, tailLines(errBuf.String(), 6))
	}
	var resp bridgeResp
	if err := json.Unmarshal([]byte(line), &resp); err != nil {
		return nil, fmt.Errorf("★ 桥的应答不是一行 JSON：%v\n    原文：%s", err, cut(line, 200))
	}
	//: `id` 现在只是"答的是哪一问"的凭据（一次一进程时不会串），但它得**真的被用**，
	//: 否则协议里那个字段就是摆设 —— 将来换成常驻进程时才发现没人校过它。
	if resp.ID != id {
		return nil, fmt.Errorf("★ 应答的 id 对不上：请求 %d，应答 %d（协议串了）", id, resp.ID)
	}
	if !resp.OK {
		return nil, fmt.Errorf("★ 桥报错：%s", resp.Error)
	}
	return &resp, nil
}

// startError 把「起不来」讲成能照做的话。**这是最要紧的一条**：解释器找不到时
// 静默返回空名册，玩家看到的是"名册空"，而不是"你的 Python 没找到"。
func startError(b *bridgeClient, err error) error {
	if errors.Is(err, exec.ErrNotFound) || errors.Is(err, os.ErrNotExist) {
		//: ★ 提示里**不写任何本机路径**（原来的写法把开发机上那个解释器的绝对路径
		//: 印了出来，既是本机信息、对玩家也毫无用处）。给形状，不给机器。
		return fmt.Errorf("★ 找不到 Python 解释器 %q（桥脚本在 %s）。\n"+
			"    指定一个再用：PowerShell 里 $env:%s='<你的 python.exe 绝对路径>'\n"+
			"    （名册与登录那条链必须走 Python；只输名字就得它在 PATH 上）",
			b.python, b.script, envPython)
	}
	return fmt.Errorf("★ 起 Python 桥失败：%v（解释器 %q，脚本 %s）", err, b.python, b.script)
}

// firstJSONLine 取第一个非空行。桥的 stdout 只该有协议行（它自己把 stdout 换成了
// devnull），所以这里不做"找出 JSON 那一行"的猜测 —— 空就是没答上来。
func firstJSONLine(s string) string {
	for _, ln := range strings.Split(s, "\n") {
		if strings.TrimSpace(ln) != "" {
			return strings.TrimSpace(ln)
		}
	}
	return ""
}

func tailLines(s string, n int) string {
	ls := strings.Split(strings.TrimRight(s, "\r\n"), "\n")
	if len(ls) > n {
		ls = ls[len(ls)-n:]
	}
	if len(ls) == 1 && ls[0] == "" {
		return "（空）"
	}
	return strings.Join(ls, " / ")
}

// updateInfo 是 `check_updates` 的应答：上游数据与我们数据包各要不要更新。
type updateInfo struct {
	Checked    bool   `json:"checked"`
	Note       string `json:"note"`
	DataUpdate bool   `json:"data_update"`
	DataLocal  string `json:"data_local"`
	DataRemote string `json:"data_remote"`
	PackLocal  string `json:"pack_local"`
	PackLatest string `json:"pack_latest"`
	PackUpdate bool   `json:"pack_update"`
}

// checkUpdates 问一次桥：上游数据与数据包有没有新版。
func checkUpdates() (*updateInfo, error) {
	b, err := newBridgeClient()
	if err != nil {
		return nil, err
	}
	resp, err := b.call("check_updates", 1, nil, 60*time.Second)
	if err != nil {
		return nil, err
	}
	return &updateInfo{
		Checked:    resp.Checked,
		Note:       resp.Note,
		DataUpdate: resp.DataUpdate,
		DataLocal:  resp.DataLocal,
		DataRemote: resp.DataRemote,
		PackLocal:  resp.PackLocal,
		PackLatest: resp.PackLatest,
		PackUpdate: resp.PackUpdate,
	}, nil
}

// updateActions 是**纯函数**：一次检查结果 ⇒ 该做哪几件事（顺序即执行顺序）。
//
// ★ 抽成纯函数的理由与别处一样：判据要能喂两格直接验，不必真联网。
// 顺序：先更新游戏数据（它才决定关卡表与干员库），再更新数据包
// （包里的敌人库是独立的一份，先后都不影响正确性，但先数据后包更符合直觉）。
func updateActions(u *updateInfo) []string {
	if u == nil || !u.Checked {
		return nil //: 没查成 ⇒ 什么都不做（取不到 ≠ 有新版）
	}
	out := []string{}
	if u.DataUpdate {
		out = append(out, "rebuild")
	}
	if u.PackUpdate {
		out = append(out, "pack")
	}
	return out
}

// ensureLevelFile 让桥**确保某一关的关卡 JSON 在本地**（不在就取一个）。
//
// ★ 随用随取（博士 2026-09-27 裁）：首次运行不再一次下 1765 个文件（实测 98 MB、
// 5～25 分钟），改到玩家真正**选定这一关**时再取一个（约 60 KB）。
// 界面在问引擎 `load` 之前调它 —— 引擎只读盘、不下载，文件不在它只会报
// 「读关卡文件失败」，那不是玩家能照做的说法。
//
// 返回 `(这次是否真的取了, 字节数, err)`：本来就在盘上时不发请求、零网络开销。
func ensureLevelFile(level string) (bool, int, error) {
	b, err := newBridgeClient()
	if err != nil {
		return false, 0, err
	}
	//: 给足超时：这是**一次网络往返**（60 KB），慢窗口下可能要几秒
	resp, err := b.call("ensure_level", 1, map[string]any{"level": level},
		120*time.Second)
	if err != nil {
		return false, 0, err
	}
	return !resp.Cached, resp.Bytes, nil
}

// fetchRoster 取一次名册。失败时返回的错误**带着原因**，由调用方原样显示。
func fetchRoster() (*rosterData, error) {
	b, err := newBridgeClient()
	if err != nil {
		return nil, err
	}
	resp, err := b.call("roster", 1, nil, 60*time.Second)
	if err != nil {
		return nil, err
	}
	return &rosterData{
		Source:    resp.Source,
		Complete:  resp.Complete,
		Note:      resp.Note,
		Count:     resp.Count,
		Operators: resp.Operators,
		Path:      resp.Path,
	}, nil
}

// ---------------------------------------------------------------- 登录那几条

// pingData 是 `ping` 的应答（握手 ＋ 凭据状态）。
type pingData struct {
	Proto     int    `json:"proto"`
	Python    string `json:"python"`
	UID       string `json:"uid"`
	CredState string `json:"cred_state"` // cred / hgtoken / none
}

// fetchPing 握手一次：拿当前账号与**凭据状态三态**。
//
// 登录屏那块"登录态"就是照它说的（Python 的 `_status()` 读 `skland.load_cred()`）：
// 不给这一栏，界面只能干说一句"已登录"，而"有 hgToken 但还没铸成 cred"是**另一种**
// 状态、处置也不同。
func fetchPing() (*pingData, error) {
	b, err := newBridgeClient()
	if err != nil {
		return nil, err
	}
	resp, err := b.call("ping", 1, nil, 20*time.Second)
	if err != nil {
		return nil, err
	}
	return &pingData{Proto: resp.Proto, Python: resp.Python, UID: resp.UID,
		CredState: resp.CredState}, nil
}

// accountsData 是本机登过的账号那一块。
type accountsData struct {
	Current string       `json:"current"`
	GameUID string       `json:"game_uid"`
	Rows    []accountRow `json:"accounts"`
}

// fetchAccounts 读本机登过的账号。**离线**（读的都是本地文件）—— 退出账号不删文件，
// 所以这里通常不止一行，"切回不必重扫"的根据就是它。
func fetchAccounts() (*accountsData, error) {
	b, err := newBridgeClient()
	if err != nil {
		return nil, err
	}
	resp, err := b.call("accounts", 1, nil, 30*time.Second)
	if err != nil {
		return nil, err
	}
	return &accountsData{Current: resp.Current, GameUID: resp.GameUID,
		Rows: resp.Accounts}, nil
}

// loginPollData 是一次轮询的结果（**不含二维码**：只在 `login_start` 给一次）。
type loginPollData struct {
	Phase  string `json:"phase"` // idle → waiting → done / failed
	Status *int   `json:"status"`
	Text   string `json:"text"`
	URL    string `json:"url"`
}

// pollLogin 问一次扫码进度。
func pollLogin() (*loginPollData, error) {
	b, err := newBridgeClient()
	if err != nil {
		return nil, err
	}
	resp, err := b.call("login_poll", 1, nil, 30*time.Second)
	if err != nil {
		return nil, err
	}
	return &loginPollData{Phase: resp.Phase, Status: resp.Status,
		Text: resp.Text, URL: resp.URL}, nil
}

// activateAccount 切到某个已登账号。**不联网、不重扫** —— 凭据与名册都在本地。
func activateAccount(uid string) error {
	b, err := newBridgeClient()
	if err != nil {
		return err
	}
	_, err = b.call("activate", 1, map[string]any{"uid": uid}, 30*time.Second)
	return err
}

// logoutAccount 退出账号（**一个文件都不删** —— 只把"当前账号"这个指向清空）。
func logoutAccount() error {
	b, err := newBridgeClient()
	if err != nil {
		return err
	}
	_, err = b.call("logout", 1, nil, 30*time.Second)
	return err
}

// fillResult 是 `fill_accounts` 的应答。
type fillResult struct {
	Total   int      `json:"total"`
	Todo    int      `json:"todo"`
	Filled  int      `json:"filled"`
	Skipped int      `json:"skipped"`
	Lines   []string `json:"lines"`
}

// fillAccounts 补全各账号的游戏用户名与游戏 uid（**联网**，按一次问一次）。
//
// 联网动作不在挂载时悄悄打一次（博士 2026-09-17 裁定）：它只在玩家按 `U` 时跑。
// 超时给得宽（每个账号一问，逐个串行）。
func fillAccounts() (*fillResult, error) {
	b, err := newBridgeClient()
	if err != nil {
		return nil, err
	}
	resp, err := b.call("fill_accounts", 1, nil, 180*time.Second)
	if err != nil {
		return nil, err
	}
	return &fillResult{Total: resp.Total, Todo: resp.Todo,
		Filled: resp.Filled, Skipped: resp.Skipped, Lines: resp.Lines}, nil
}

// loginStartData 是一次 `login_start` 的应答。
//
// **二维码只在这一条里给一次**（`login_poll` 不重发）：桥给的是**矩阵**
// （每行一串 `0`/`1`），画法在 `qr.go` 里 —— 见那边的文件头。
type loginStartData struct {
	Phase    string   `json:"phase"`
	URL      string   `json:"url"`
	QRMatrix []string `json:"qr_matrix"`
	QRSize   int      `json:"qr_size"`
	QRNote   string   `json:"qr_note"` // 非空 = 二维码编不出来，里面是原因
	Text     string   `json:"text"`
}

// fetchLoginStart 起一次扫码登录，拿到二维码矩阵。
//
// 桥内部会先等二维码出来（最多 10 秒）再应答 —— 那 10 秒里 Python 正拿着一张
// **新的**二维码向森空岛申请，是网络在花时间，不是桥慢，所以这里给 30 秒余量：
// 超时了就具名报出来，不静默退成一张空图。
func fetchLoginStart() (*loginStartData, error) {
	b, err := newBridgeClient()
	if err != nil {
		return nil, err
	}
	resp, err := b.call("login_start", 1, nil, 30*time.Second)
	if err != nil {
		return nil, err
	}
	return &loginStartData{
		Phase:    resp.Phase,
		URL:      resp.URL,
		QRMatrix: resp.QRMatrix,
		QRSize:   resp.QRSize,
		QRNote:   resp.QRNote,
		Text:     resp.Text,
	}, nil
}
