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
// 跑完——输入是「已经完全算好的数字」，输出是判决与时间线。这条边界是故意的：练度
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
// : 症状会是「判决微妙地对不上」，那是最难查的一类错，所以要在这里挡住。
const protocolVersion = 1

type request struct {
	ID   int             `json:"id"`
	Cmd  string          `json:"cmd"`
	Spec json.RawMessage `json:"spec,omitempty"`
	//: `load` 用：关卡查询串。既收 levelId（`main_00-01`）也收关卡号（`0-1`），
	//: 换算走 `_level_index.json`，与 `stage.py:966-980` 同口径。
	Level string `json:"level,omitempty"`
	//: `roster` 用：名册文件路径（见 `roster.go`）。
	Path string `json:"path,omitempty"`
}

type response struct {
	ID      int             `json:"id"`
	OK      bool            `json:"ok"`
	Pong    *pong           `json:"pong,omitempty"`
	Verdict json.RawMessage `json:"verdict,omitempty"`
	//: `load` 的应答：Go 自己解析出来的关卡（见 `stage.go`）。
	Stage json.RawMessage `json:"stage,omitempty"`
	//: `enemies` 的应答：一关引用的敌人各自那一档（见 `enemy.go`）。
	Enemies json.RawMessage `json:"enemies,omitempty"`
	//: `opstats` 的应答：干员面板折算结果（见 `operator.go`）。
	OpStats json.RawMessage `json:"opstats,omitempty"`
	//: `range` 的应答：攻击范围（相对格 ＋ 绝对格，见 `range.go`）。
	Ranges json.RawMessage `json:"ranges,omitempty"`
	//: `skill` 的应答：技能状态机参数（见 `skill.go`）。
	Skills json.RawMessage `json:"skills,omitempty"`
	//: `classify` 的应答：黑板键的归类（见 `classify.go`）。
	Classes json.RawMessage `json:"classes,omitempty"`
	//: `maxhp` 的应答：生命上限加成那一行（见 `profile.go`）。
	MaxHP json.RawMessage `json:"maxhp,omitempty"`
	//: `interval` 的应答：开技能的攻击间隔那一行（见 `profile.go`）。
	Interval json.RawMessage `json:"interval,omitempty"`
	//: `panel` 的应答：同一帧的五处读数（见 `panelfold.go`）。
	Panel json.RawMessage `json:"panel,omitempty"`
	//: `roster` 的应答：练度名册（见 `roster.go`）。
	Roster json.RawMessage `json:"roster,omitempty"`
	//: `plan` 的应答：打法（见 `plan.go`）。
	Plan json.RawMessage `json:"plan,omitempty"`
	//: `loadout` 的应答：名册与计划合起来之后的练度（见 `loadout.go`）。
	Loadout json.RawMessage `json:"loadout,omitempty"`
	//: `stageenv` 的应答：构建规格要用的关卡静态 8 项（见 `stageenv.go`）。
	StageEnv json.RawMessage `json:"stage_env,omitempty"`
	//: `cells` 的应答：规格里的两张格表（见 `cells.go`）。
	Cells json.RawMessage `json:"cells,omitempty"`
	//: `specgo` 的应答：Go 现在能造出的那部分规格（见 `specgo.go`）。
	SpecGo json.RawMessage `json:"spec_go,omitempty"`
	Error string          `json:"error,omitempty"`
}

type pong struct {
	Version  int    `json:"version"`
	Go       string `json:"go"`
	OS       string `json:"os"`
	Arch     string `json:"arch"`
	Started  string `json:"started"`
	SpecDone bool   `json:"spec_done"` //: `sim` 是否已经实现（最小版本落地后为 true）
	//: 本二进制里**编译进来**的关卡特有机制名（`mech.Available()`）。
	//: Python 侧据此判断「这一关的机制能不能交给 Go 跑」，不各自维护名单。
	Mechanisms []string `json:"mechanisms"`
}

func main() {
	// 机制层的痕迹通道（见 `initMechTrace`）：`RIOS_TRACE=1` 时接上，
	// 否则 `mech.Trace` 保持 no-op。
	initMechTrace()
	// 无缓冲地一行一行应答：调用方是「发一批、收一批」的同步用法，
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
			// **宁可什么都不回，也不回一个残缺的判决**：对拍台把「这一局不支持」
			// 当成失败，把「缺了机制的结果」当成通过，后者才是真危险。
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(verdict)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("判决序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Verdict: raw}
	case "load":
		// 丙阶段一：**Go 自己读关卡数据**，不经 Python 的规格。
		// 这是把取数链搬进 Go 的第一块，见 `stage.go` 的文件头。
		if req.Level == "" {
			return response{ID: req.ID, OK: false,
				Error: "load 少了 level（给 levelId，如 main_00-01，或关卡号，如 0-1）"}
		}
		st, err := LoadStage(req.Level)
		if err != nil {
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(st)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("关卡序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Stage: raw}
	case "enemies":
		// 丙阶段二：**Go 自己读敌人库**，逐档合并后取这一关引用的那几档。
		if req.Level == "" {
			return response{ID: req.ID, OK: false,
				Error: "enemies 少了 level（给关卡，如 main_00-01）"}
		}
		lid, refs, err := EnemiesForStage(req.Level)
		if err != nil {
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(map[string]any{"level_id": lid, "refs": refs})
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("敌人序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Enemies: raw}
	case "opstats":
		// 丙阶段三：**Go 自己折算干员面板**。`spec` 收一个配置或一批配置。
		if len(req.Spec) == 0 {
			return response{ID: req.ID, OK: false,
				Error: "opstats 少了 spec（一个配置或一批配置的数组）"}
		}
		var list []OperatorCalcConfig
		if err := json.Unmarshal(req.Spec, &list); err != nil {
			var one OperatorCalcConfig
			if err2 := json.Unmarshal(req.Spec, &one); err2 != nil {
				return response{ID: req.ID, OK: false,
					Error: fmt.Sprintf("spec 既不是配置数组也不是单个配置：%v", err2)}
			}
			list = []OperatorCalcConfig{one}
		}
		results := make([]*OperatorStats, 0, len(list))
		for _, c := range list {
			st, err := OperatorStatsFor(c, "round")
			if err != nil {
				return response{ID: req.ID, OK: false, Error: err.Error()}
			}
			results = append(results, st)
		}
		raw, err := json.Marshal(results)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("面板序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, OpStats: raw}
	case "range":
		// 丙阶段三·第十一批：**Go 自己读范围表**并做旋转/平移。
		if len(req.Spec) == 0 {
			return response{ID: req.ID, OK: false,
				Error: "range 少了 spec（一批 {code,direction,x,y}）"}
		}
		var qs []RangeQuery
		if err := json.Unmarshal(req.Spec, &qs); err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("spec 不是范围查询数组：%v", err)}
		}
		res, err := RangeFor(qs)
		if err != nil {
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(res)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("范围序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Ranges: raw}
	case "skill":
		// 丙阶段四：**Go 自己读技能元数据**（状态机那一半）。
		if len(req.Spec) == 0 {
			return response{ID: req.ID, OK: false,
				Error: "skill 少了 spec（一批 {skill_id,level}）"}
		}
		var qs []struct {
			SkillID string `json:"skill_id"`
			Level   int    `json:"level"`
		}
		if err := json.Unmarshal(req.Spec, &qs); err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("spec 不是技能查询数组：%v", err)}
		}
		out := make([]*SkillMeta, 0, len(qs))
		for _, q := range qs {
			m, err := SkillMetaFor(q.SkillID, q.Level)
			if err != nil {
				return response{ID: req.ID, OK: false, Error: err.Error()}
			}
			out = append(out, m)
		}
		raw, err := json.Marshal(out)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("技能序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Skills: raw}
	case "maxhp":
		// 丙阶段四·第九批：生命上限加成那一行（纯函数，见 `profile.go`）。
		if len(req.Spec) == 0 {
			return response{ID: req.ID, OK: false,
				Error: "maxhp 少了 spec（一批 {base,cur,pct}）"}
		}
		var qs []struct {
			Base float64 `json:"base"`
			Cur  float64 `json:"cur"`
			Pct  float64 `json:"pct"`
		}
		if err := json.Unmarshal(req.Spec, &qs); err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("spec 不是参数数组：%v", err)}
		}
		vals := make([]float64, 0, len(qs))
		for _, q := range qs {
			vals = append(vals, MaxHPAfterBonus(q.Base, q.Cur, q.Pct))
		}
		raw, err := json.Marshal(vals)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, MaxHP: raw}
	case "interval":
		// 丙阶段四·第十批：开技能的攻击间隔那一行（纯函数，见 `profile.go`）。
		if len(req.Spec) == 0 {
			return response{ID: req.ID, OK: false,
				Error: "interval 少了 spec（一批 {baseIv,baseSpd,ivBuff,spdBuff}）"}
		}
		var qs []struct {
			BaseIv  float64 `json:"base_iv"`
			BaseSpd float64 `json:"base_spd"`
			IvBuff  float64 `json:"iv_buff"`
			SpdBuff float64 `json:"spd_buff"`
		}
		if err := json.Unmarshal(req.Spec, &qs); err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("spec 不是参数数组：%v", err)}
		}
		vals := make([]float64, 0, len(qs))
		for _, q := range qs {
			vals = append(vals,
				AttackInterval(q.BaseIv, q.BaseSpd, q.IvBuff, q.SpdBuff))
		}
		raw, err := json.Marshal(vals)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Interval: raw}
	case "panel":
		// 丙阶段四·第十一批：同一帧的五处读数（纯函数，见 `panelfold.go`）。
		if len(req.Spec) == 0 {
			return response{ID: req.ID, OK: false,
				Error: "panel 少了 spec（一批 PanelState）"}
		}
		var qs []PanelState
		if err := json.Unmarshal(req.Spec, &qs); err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("spec 不是状态数组：%v", err)}
		}
		out := make([]PanelReadings, 0, len(qs))
		for _, q := range qs {
			out = append(out, FoldPanel(q))
		}
		raw, err := json.Marshal(out)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Panel: raw}
	case "roster":
		// 丙阶段四·第十二批：Go 直读练度名册（见 `roster.go`）。
		if req.Path == "" {
			return response{ID: req.ID, OK: false,
				Error: "roster 少了 path（名册文件路径）"}
		}
		rr, err := ReadRoster(req.Path)
		if err != nil {
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(rr)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Roster: raw}
	case "plan":
		// 丙阶段四·第十三批：Go 直读打法（见 `plan.go`）。
		if req.Path == "" {
			return response{ID: req.ID, OK: false,
				Error: "plan 少了 path（打法文件路径）"}
		}
		pp, err := ReadPlan(req.Path)
		if err != nil {
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(pp)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Plan: raw}
	case "loadout":
		// 丙阶段四·第十四批：名册与计划合起来的练度解析（见 `loadout.go`）。
		if len(req.Spec) == 0 {
			return response{ID: req.ID, OK: false,
				Error: "loadout 少了 spec（{plan, roster}）"}
		}
		var q struct {
			Plan   string `json:"plan"`
			Roster string `json:"roster"`
		}
		if err := json.Unmarshal(req.Spec, &q); err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("spec 不是 {plan, roster}：%v", err)}
		}
		if q.Plan == "" {
			return response{ID: req.ID, OK: false, Error: "loadout 少了 plan 路径"}
		}
		pp, err := ReadPlan(q.Plan)
		if err != nil {
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		var rs RosterRead
		if q.Roster != "" {
			if rs, err = ReadRoster(q.Roster); err != nil {
				return response{ID: req.ID, OK: false, Error: err.Error()}
			}
		}
		out := make([]LoadoutEntry, 0, len(pp.Deploys))
		for _, d := range pp.Deploys {
			e, err := ResolveLoadout(d, rs)
			if err != nil {
				return response{ID: req.ID, OK: false, Error: err.Error()}
			}
			out = append(out, e)
		}
		raw, err := json.Marshal(out)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Loadout: raw}
	case "stageenv":
		// 丙阶段四·第十六批：构建规格要用的关卡静态 8 项（见 `stageenv.go`）。
		// 这是「Go 自己构造规格」的第一块——`build_spec` 19 个顶层键里
		// 不依赖 sim／干员／机制的那 8 个。
		if req.Level == "" && req.Path == "" {
			return response{ID: req.ID, OK: false,
				Error: "stageenv 少了 level（给 levelId 或关卡号）或 path（关卡 JSON）"}
		}
		difficulty := "NORMAL"
		if len(req.Spec) > 0 {
			var q struct {
				Difficulty string `json:"difficulty"`
			}
			if err := json.Unmarshal(req.Spec, &q); err != nil {
				return response{ID: req.ID, OK: false,
					Error: fmt.Sprintf("spec 不是 {difficulty}：%v", err)}
			}
			if q.Difficulty != "" {
				difficulty = q.Difficulty
			}
		}
		envOut, err := LoadStageEnv(req.Level, difficulty)
		if req.Path != "" {
			//: 合成关卡（判据用）走这条路：它不在关卡索引里。
			envOut, err = LoadStageEnvFile(req.Path, difficulty)
		}
		if err != nil {
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(envOut)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, StageEnv: raw}
	case "cells":
		// 丙阶段四·第十七批：规格里的两张格表——防守点格与高台格（见 `cells.go`）。
		if req.Level == "" {
			return response{ID: req.ID, OK: false,
				Error: "cells 少了 level（给 levelId 或关卡号）"}
		}
		ct, err := CellsOf(req.Level)
		if err != nil {
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(ct)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Cells: raw}
	case "specgo":
		// 丙阶段四·第十八批：Go 自己造规格的骨架（见 `specgo.go`）。
		if req.Level == "" {
			return response{ID: req.ID, OK: false,
				Error: "specgo 少了 level（给 levelId 或关卡号）"}
		}
		var sq struct {
			Difficulty string  `json:"difficulty"`
			MaxTime    float64 `json:"max_time"`
		}
		if len(req.Spec) > 0 {
			if err := json.Unmarshal(req.Spec, &sq); err != nil {
				return response{ID: req.ID, OK: false,
					Error: fmt.Sprintf("spec 不是 {difficulty,max_time}：%v", err)}
			}
		}
		sp, err := BuildSpecPart(req.Level, sq.Difficulty, sq.MaxTime)
		if err != nil {
			return response{ID: req.ID, OK: false, Error: err.Error()}
		}
		raw, err := json.Marshal(sp)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, SpecGo: raw}
	case "classify":
		// 丙阶段四·第五批：黑板键的归类（**只查表 ＋ 拆变体**，
		// `_classify` 的降级序列本轮未接，见 `classify.go` 文件头）。
		if len(req.Spec) == 0 {
			return response{ID: req.ID, OK: false,
				Error: "classify 少了 spec（一批键名）"}
		}
		var keys []string
		if err := json.Unmarshal(req.Spec, &keys); err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("spec 不是键名数组：%v", err)}
		}
		outs := make([]KeyClass, 0, len(keys))
		for _, k := range keys {
			outs = append(outs, ClassifyKey(k))
		}
		raw, err := json.Marshal(outs)
		if err != nil {
			return response{ID: req.ID, OK: false,
				Error: fmt.Sprintf("归类序列化失败：%v", err)}
		}
		return response{ID: req.ID, OK: true, Classes: raw}
	default:
		return response{ID: req.ID, OK: false,
			Error: fmt.Sprintf(
				"不认识的命令：%q（支持 ping / sim / load / enemies / opstats / range / skill / classify）",
				req.Cmd)}
	}
}
