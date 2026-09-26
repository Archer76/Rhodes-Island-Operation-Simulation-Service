package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"rios-sim/data"
)

// # 引擎客户端：起 `rios-sim.exe`，讲它那套 JSON 行协议
//
// 界面**不能同进程**用引擎：`rios-sim` 根目录 68 个 `.go` 全是 `package main`
// （迁移图 §10）⇒ 只能起子进程。协议形状照 `ak_tactic/simgo/client.py`：
// **一行一个 JSON 对象进、一行一个 JSON 对象出**，一次进程一次请求。
//
// ★ 与 `engclient.go` 分开写，因为两者的失败模式完全不同：那一头缺的是**解释器与
// qrcode**（玩家自己装的），这一头缺的是**我们自己的 exe**（随包发的）。排障话术
// 因此也不同 —— 把两条路混在一个文件里，迟早会出现"按 Python 的话术去修引擎"。

const (
	//: 引擎 exe 的路径：环境变量优先（判据与排障用），缺省按 exe 同目录/往上找。
	envEngine = "RIOS_SIM_BIN"
	//: 引擎 exe 的名字（发布形态里它与界面 exe 同目录）。
	engineExe = "rios-sim.exe"
)

type engineClient struct {
	path string
	//: 起子进程时用的工作目录。
	//:
	//: ⚠ **必须给对**：引擎的 gamedata 路径是**相对 cwd** 拼的
	//: （`data/gamedata/_level_index.json`，不走 `RIOS_DB`）⇒ cwd 错了它会报
	//: 「读关卡索引失败」。而界面自己拿得到数据目录（`data.DataDBDir()`），
	//: 所以由界面把 cwd 摆到数据目录的**上一层**。
	dir string
}

// newEngineClient 解析出「跑哪个 exe、在哪个目录跑」。
//
// 找不到 exe 时**具名失败**（连"找过哪些位置"一起给）：静默退化成"没有结果"是最
// 坏的一类错 —— 玩家分不清"这一关搜不出来"与"引擎根本没起来"。
func newEngineClient() (*engineClient, error) {
	path, tried, err := findEngineExe()
	if err != nil {
		return nil, err
	}
	if path == "" {
		return nil, fmt.Errorf("★ 找不到引擎 %s。找过这些位置：\n    %s\n"+
			"  它是随界面一起发的（发布形态里两个 exe 同目录）：\n"+
			"    用 %s=<引擎 exe 的绝对路径> 显式指定，或把它放到界面 exe 旁边",
			engineExe, strings.Join(tried, "\n    "), envEngine)
	}
	return &engineClient{path: path, dir: engineWorkDir()}, nil
}

// findEngineExe 依次找：`RIOS_SIM_BIN` → 界面 exe 同目录 → 往上三层 → cwd。
//
// ★ **显式指定了却不存在 ⇒ 具名失败，不再回退去找别的**。第一版是"指的那个不在就
// 接着找"，而自检里的负对照当场抓住它：把 `RIOS_SIM_BIN` 指到一个不存在的路径，
// 它居然**照样拿到了一个客户端**（在别处找到了另一个 `rios-sim.exe`）。在判据里
// 那是很坏的事 —— **你以为读的是 A 仪器，实际读的是 B**。环境变量是明确的指令，
// 指令落空就要说，不许静默改读别的。
func findEngineExe() (string, []string, error) {
	tried := []string{}
	hit := func(cand string) bool {
		tried = append(tried, cand)
		if st, err := os.Stat(cand); err == nil && !st.IsDir() {
			return true
		}
		return false
	}
	if v := strings.TrimSpace(os.Getenv(envEngine)); v != "" {
		if hit(v) {
			return v, tried, nil
		}
		return "", tried, fmt.Errorf("★ %s 指到一个不存在的路径：%s\n"+
			"  既然显式指定了，就**不再回退**去找别的 exe —— 否则读数可能来自另一个仪器。\n"+
			"  要么把它改对，要么清掉这个环境变量让界面自己找", envEngine, v)
	}
	roots := []string{}
	if exe, err := os.Executable(); err == nil {
		roots = append(roots, filepath.Dir(exe))
	}
	if wd, err := os.Getwd(); err == nil {
		roots = append(roots, wd)
	}
	for _, root := range roots {
		if hit(filepath.Join(root, engineExe)) {
			return filepath.Join(root, engineExe), tried, nil
		}
		//: 开发时常在 `out/` 里，往上三层基本能回到仓根
		dir := root
		for i := 0; i < 3; i++ {
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
			if hit(filepath.Join(dir, engineExe)) {
				return filepath.Join(dir, engineExe), tried, nil
			}
		}
	}
	return "", tried, nil
}

// engineWorkDir 是起引擎时该用的 cwd（引擎的 gamedata 路径相对它拼）。
//
// 逻辑：数据目录若是个**绝对路径**，就取它的上一层（那样 `data/gamedata/...`
// 正好落回原处）；否则保持当前目录 —— 相对路径说明调用方本来就在仓根跑。
func engineWorkDir() string {
	d := data.DataDBDir()
	if !filepath.IsAbs(d) {
		return ""
	}
	return filepath.Dir(d)
}

// engineDataRoot 给出该告诉引擎的 gamedata 绝对路径（相对情形返回空 = 不设）。
//
// 引擎那边读的是 `RIOS_DATA`，缺省是**相对 cwd** 的 `data/gamedata`。
func engineDataRoot() string {
	d := data.DataDBDir()
	if !filepath.IsAbs(d) {
		return ""
	}
	return filepath.Join(d, "gamedata")
}

// engineResp 是一次应答。字段与协议里那几个**顶层键**同名，取用哪个由调用方决定。
type engineResp struct {
	ID    int             `json:"id"`
	OK    bool            `json:"ok"`
	Error string          `json:"error"`
	Raw   json.RawMessage `json:"-"`
}

// call 起一次引擎、发一行请求、读一行应答，返回整份应答对象。
//
// ⚠ **`level` 是请求的顶层字段，不是 spec 里的**：引擎的 `solve`／`candidates`／
// `spots` 都读 `req.Level`（`main.go` 的 case 里写着）。第一版把它塞进 spec，引擎当场
// 报"少了 level（关卡号或 levelId）或 path" —— 是那句**具名失败**点出来的，不是猜的。
//
// 一次一进程：解算那一屏一次只发一条 `solve`（它内部要跑几十上百场模拟，进程启动的
// 开销相对可以忽略）。协议（`id` ＋ 一行 JSON）照常，换成常驻时调用方不用动。
func (e *engineClient) call(cmd string, id int, level string, spec any,
	timeout time.Duration) (map[string]json.RawMessage, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	req := map[string]any{"id": id, "cmd": cmd}
	if level != "" {
		req["level"] = level
	}
	if spec != nil {
		req["spec"] = spec
	}
	line, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("★ 请求序列化失败：%v", err)
	}

	c := exec.CommandContext(ctx, e.path)
	if e.dir != "" {
		c.Dir = e.dir
	}
	//: 再把 gamedata 目录**显式钉住**（`RIOS_DATA`）。实测过四种组合（见
	//: `tools/check_stage_go.py` 文件头）：`cwd=C:\` ＋ `RIOS_DATA` 绝对路径照样能跑通，
	//: 而只摆 cwd 也能 —— 双保险比只靠一个稳，发布形态里尤其（双击启动时 cwd 未必对）。
	if d := engineDataRoot(); d != "" {
		c.Env = append(os.Environ(), "RIOS_DATA="+d)
	}
	var out, errBuf bytes.Buffer
	c.Stdout, c.Stderr = &out, &errBuf
	stdin, err := c.StdinPipe()
	if err != nil {
		return nil, fmt.Errorf("★ 引擎的 stdin 拿不到：%v", err)
	}
	if err := c.Start(); err != nil {
		return nil, fmt.Errorf("★ 起引擎失败：%v（exe %s，cwd %s）", err, e.path, e.dir)
	}
	if _, err := stdin.Write(append(line, '\n')); err != nil {
		_ = c.Process.Kill()
		_ = c.Wait()
		return nil, fmt.Errorf("★ 给引擎写请求失败：%v", err)
	}
	_ = stdin.Close()
	_ = c.Wait() //: 退出码不当判据：协议行在，就以应答为准

	text := firstJSONLine(out.String())
	if text == "" {
		if ctx.Err() != nil {
			return nil, fmt.Errorf("★ 引擎在 %s 内没给应答（已超时）。exe %s，cwd %s\n"+
				"    解算本来就慢（每层要跑几十场模拟），超时说明这一轮的参数偏大",
				timeout, e.path, e.dir)
		}
		return nil, fmt.Errorf("★ 引擎没有给出应答行。exe %s，cwd %s\n    stderr：%s",
			e.path, e.dir, tailLines(errBuf.String(), 6))
	}
	var head struct {
		ID    int    `json:"id"`
		OK    bool   `json:"ok"`
		Error string `json:"error"`
	}
	if err := json.Unmarshal([]byte(text), &head); err != nil {
		return nil, fmt.Errorf("★ 引擎的应答不是一行 JSON：%v\n    原文：%s", err, cut(text, 200))
	}
	//: `id` 得**真的被校**，否则协议里那个字段就是摆设（与桥那边同一条理由）
	if head.ID != id {
		return nil, fmt.Errorf("★ 应答的 id 对不上：请求 %d，应答 %d（协议串了）", id, head.ID)
	}
	if !head.OK {
		return nil, fmt.Errorf("★ 引擎报错：%s", head.Error)
	}
	var full map[string]json.RawMessage
	if err := json.Unmarshal([]byte(text), &full); err != nil {
		return nil, fmt.Errorf("★ 引擎应答解不开：%v", err)
	}
	return full, nil
}

// callSolve 发一条 `solve`，拿回它的 `solve` 段。
//
// `level` 走顶层字段（见 `call` 的说明），spec 里是 `solver.go` 的 `SolveQuery` 形状。
func (e *engineClient) callSolve(p solveParams, depth int,
	timeout time.Duration) (json.RawMessage, error) {
	spec := map[string]any{
		"roster": p.rosterPath, "operators": p.pool,
		"max_ops": depth, "min_ops": 1, "beam": p.beam, "per_op": p.perOp,
		"difficulty": p.difficulty,
	}
	//: ★ 助战走 spec 的 `support` 键（引擎侧是 `solver.go` 的 `SolveQuery.Support`，
	//: 见口径 1／3）。**空的时候整个键不发** —— 于是"不带助战"那一轮的请求与加这个
	//: 字段之前**逐字节相同**（读数可复核，也不给老引擎多送一个它不认识的键）。
	if p.support != "" {
		spec["support"] = p.support
	}
	fields, err := e.call("solve", 1, p.levelID, spec, timeout)
	if err != nil {
		return nil, err
	}
	raw, ok := fields["solve"]
	if !ok || len(raw) == 0 {
		return nil, fmt.Errorf("★ 引擎的应答里没有 solve 段（协议变了？）：%s",
			cut(string(mustJSONKeys(fields)), 200))
	}
	return raw, nil
}

// mustJSONKeys 只给错误消息用：把应答的顶层键列出来，不 dump 整份（可能很大）。
func mustJSONKeys(m map[string]json.RawMessage) []byte {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	blob, _ := json.Marshal(keys)
	return blob
}
