// rios-sim：R.I.O.S. 的第二份战斗模拟器（Go）。
//
// ## 它为什么存在
//
// HS-EX-4 一次解算是 214 秒——几千场完整战斗在纯 Python 里跑。`ak_tactic/battle/sim.py`
// 已经做过就地展开的优化（1.09–1.18×），**再榨只有 20%，要的是一个量级**。
//
// ## 它与原版的关系（博士 2026-09-18 的裁定）
//
// 「保留原版项目结构不动，另写一份新的模拟器」。所以：
//
//   - `ak_tactic/battle/*` **一行不改**，它继续是三关基线与 793 项自检的权威实现；
//   - 这一份是**另起**的，自带构建、自成一体；
//   - **判决必须逐位对齐**才有资格接班——对拍台见 `docs/tui-plan.md` 第十二节。
//
// ## 它是怎么被调用的
//
// 标准输入输出上的 **JSON 行协议**（一次进程、批量作业），不是 Python 扩展模块：
// 免掉 FFI 构建链，也能直接复用 `ak_tactic/parallel.py` 那套多进程并行。
//
// 请求（stdin 一行一个 JSON）：
//
//	{"id":1,"cmd":"ping"}
//	{"id":2,"cmd":"sim","spec":{…}}     // spec 见 wire.go，全部由 Python 侧解析好送来
//
// 应答（stdout 一行一个 JSON，与请求同序）：
//
//	{"id":1,"ok":true,"pong":{"version":"…","units":0}}
//	{"id":2,"ok":true,"verdict":{…}}
//
// **Go 侧不做任何数据源访问**：不读数据库、不联网、不做练度折算。它只把一场战斗
// 跑完——输入是"已经完全算好的数字"，输出是判决与时间线。这条边界是故意的：练度
// 折算那套东西有一整条已经验证过的 Python 链，搬过来只会多一处会漂的实现。
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"runtime"
	"sort"
	"time"

	"rios-sim/mech"
)

// : 协议版本。Python 侧连上来先 `ping` 一次核对它——二进制与调用方版本不一致时，
// : 症状会是"判决微妙地对不上"，那是最难查的一类错，所以要在这里挡住。
const protocolVersion = 1

type request struct {
	ID   int             `json:"id"`
	Cmd  string          `json:"cmd"`
	Spec json.RawMessage `json:"spec,omitempty"`
}

type response struct {
	ID      int             `json:"id"`
	OK      bool            `json:"ok"`
	Pong    *pong           `json:"pong,omitempty"`
	Verdict json.RawMessage `json:"verdict,omitempty"`
	Error   string          `json:"error,omitempty"`
}

type pong struct {
	Version  int    `json:"version"`
	Go       string `json:"go"`
	OS       string `json:"os"`
	Arch     string `json:"arch"`
	Started  string `json:"started"`
	SpecDone bool   `json:"spec_done"` //: `sim` 是否已经实现（最小版本落地后为 true）
	//: 本二进制里**编译进来**的关卡特有机制名（`mech.Available()`）。
	//: Python 侧据此判断"这一关的机制能不能交给 Go 跑"，不各自维护名单。
	Mechanisms []string `json:"mechanisms"`
}

func main() {
	// 机制层的痕迹通道（见 `initMechTrace`）：`RIOS_TRACE=1` 时接上，
	// 否则 `mech.Trace` 保持 no-op。
	initMechTrace()
	// 无缓冲地一行一行应答：调用方是"发一批、收一批"的同步用法，
	// 攒着不写会让人以为进程挂住了。
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 0, 1<<20), 1<<26) // spec 可能很大（整张地图 + 波次）
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()

	started := time.Now().Format(time.RFC3339)
	enc := json.NewEncoder(out)

	for in.Scan() {
		line := in.Bytes()
		if len(line) == 0 {
			continue
		}
		var req request
		if err := json.Unmarshal(line, &req); err != nil {
			_ = enc.Encode(response{OK: false,
				Error: fmt.Sprintf("请求不是合法 JSON：%v", err)})
			_ = out.Flush()
			continue
		}
		resp := handle(&req, started)
		if err := enc.Encode(resp); err != nil {
			fmt.Fprintf(os.Stderr, "写应答失败：%v\n", err)
			os.Exit(2)
		}
		_ = out.Flush()
		if err := in.Err(); err != nil && err != io.EOF {
			fmt.Fprintf(os.Stderr, "读请求失败：%v\n", err)
			os.Exit(2)
		}
	}
}

func handle(req *request, started string) response {
	switch req.Cmd {
	case "ping":
		ids := mech.Available()
		sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
		names := make([]string, 0, len(ids))
		for _, id := range ids {
			names = append(names, string(id))
		}
		return response{ID: req.ID, OK: true, Pong: &pong{
			Version: protocolVersion, Go: runtime.Version(),
			OS: runtime.GOOS, Arch: runtime.GOARCH, Started: started,
			SpecDone: true, Mechanisms: names,
		}}
	case "sim":
		if len(req.Spec) == 0 {
			return response{ID: req.ID, OK: false,
				Error: "sim 少了 spec"}
		}
		var spec Spec
		if err := json.Unmarshal(req.Spec, &spec); err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("spec 解析失败：%v", err)}
		}
		verdict, err := runSim(&spec)
		if err != nil {
			// **宁可什么都不回，也不回一个残缺的判决**：对拍台把"这一局不支持"
			// 当成失败，把"缺了机制的结果"当成通过，后者才是真危险。
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(verdict)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("判决序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Verdict: raw}
	default:
		return response{ID: req.ID, OK: false,
			Error: fmt.Sprintf("不认识的命令：%q（支持 ping / sim）", req.Cmd)}
	}
}
