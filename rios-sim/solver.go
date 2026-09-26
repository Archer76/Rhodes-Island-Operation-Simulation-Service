package main

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"rios-sim/core"
)

// # Beam 搜索：`ak_tactic/search.py:192-425` 的 Go 侧对应物
//
// 第二层（第一层是 `candidates.go` 的几何剪枝）。状态 = 一个有序的部署列表
// （顺序即落地顺序，因此也决定费用曲线）；每层把候选接到状态末尾，跑模拟，
// 按 `rank` 排序，留前 `beam` 个。
//
// ## 为什么按「加一个人」而不是「同时选一套阵容」
//
// 同时选阵容是组合爆炸（460 选 4 ≈ 1.8 亿），而且大部分组合在费用上根本下不去。
// 逐个追加天然尊重费用曲线 —— **先下的便宜、后下的贵**，与实机打法同一个顺序。
//
// ## 六个要点（照抄权威，逐条都有理由）
//
//  1. **排序键是全序**：`rank = (stars, life, kills, -漏怪扣命, damage)`。中间状态大多
//     打不赢，只按星级排会让整层并列。用**扣掉的生命**而不是漏怪只数：`life_cost`
//     可以是 0（漏 4 只只扣 3 命），按只数排会把这两种情况混为一谈。
//  2. **排序稳定**：Python 的 `list.sort(reverse=True)` 稳定 ⇒ 同分保持插入序，
//     而紧跟着就是按序切 `uniq[:beam]` —— 平局顺序变了，留下的状态就换一批。
//  3. **去重按 (干员, 格) 的集合**：同一套人不同顺序算近似重复（费用曲线不同，但差别
//     小于噪声），留排名最高的那个。不去重的话 beam 会被「同一批人的各种排列」占满，
//     多样性归零。
//  4. **跨层保留最好的**：多加一个人未必更好 —— 费用曲线会被推后。只交最后一层会把
//     这种退步当成结果报出去。
//  5. **三星即停**（且 `depth >= min_ops`）。
//  6. **拒跑与打输不是一回事**：取不到规格／模拟报错 ⇒ 这一条状态**丢弃**
//     （Python 的 `except: return None`），但计数器要分开记，免得"没跑"被读成"打输"。

// 闸门那两个口径参数的**权威取值**（`ak_tactic/simgo/verifier.py:85`，含裁定出处：
// PM 裁定④ 2026-09-20 走乙）。搜索这条路与该声明同口径。
const (
	gateAllowDevices = true
	gateAllowSkills  = false
)

// SolveQuery 是 `solve` 命令的 spec。
type SolveQuery struct {
	Roster     string            `json:"roster"` //: 名册 JSON 路径（同 `candidates`）
	Difficulty string            `json:"difficulty"`
	Operators  []string          `json:"operators"`
	MaxOps     int               `json:"max_ops"`
	Beam       int               `json:"beam"`
	PerOp      int               `json:"per_op"`
	MinOps     int               `json:"min_ops"`
	Skills     map[string][2]int `json:"skills"`
	SpeedScale float64           `json:"speed_scale"`
	//: 闸门的两个口径参数。**nil ⇒ 照权威的常量**（`ak_tactic/simgo/verifier.py:85`：
	//: `GATE_ALLOW_DEVICES=True` / `GATE_ALLOW_SKILLS=False`）。
	//:
	//: ⚠ 用指针是为了**三态**："不送"与"显式送 false"必须分得开 —— 权威那边这两个
	//: 参数是**必填**的，Go 侧兜一个默认值会静默改掉近一半主线关的可跑性
	//: （`buildspec.go` 那里写着：196 关、45.3 个百分点，从可跑变拒跑）。
	AllowDevices *bool `json:"allow_devices,omitempty"`
	AllowSkills  *bool `json:"allow_skills,omitempty"`

	//: 助战干员的名字（界面 `cmd/rios-tui` 在 `solveParams.support` 里送过来）。
	//:
	//: ★ 口径（博士 2026-09-26）：**用助战 ⇒ 编队上限 13**（自己的 12 ＋ 助战 1，
	//: 助战占一格）；不用 ⇒ 12。**练度不填、只写名字** —— 官方协议里 `opers[]`
	//: 只有 `name` 必填，`requirements` 是"练度要求，自动编队时校验。可选，
	//: 默认为空"，MAA 也不识别助战干员的练度。
	//:
	//: ⚠ 它**不参与搜索**：搜索只在 `Operators` 给定的池子里挑组合，助战是"编队里
	//: 那一格"，不是候选。所以 `MaxOps` 不会因为它 +1（13 是**编队**上限，不是
	//: 搜索深度）。引擎这边的落点只有两处：原样回声进 `SolveOut.Support`，
	//: 以及留一份在 `SolveOut.Params["support"]` 里（排障时看得见这一轮带了谁）。
	Support string `json:"support,omitempty"`
}

// SolveStep 是一层的 beam 摘要（`SearchResult.steps` 的一项）。
type SolveStep struct {
	Depth  int      `json:"depth"`
	Tried  int      `json:"tried"`
	Kept   int      `json:"kept"`
	Stars  int      `json:"stars"`
	Line   string   `json:"line"`
	Who    []string `json:"who"`
	States int      `json:"states"`
}

// SolveStats 是**行使计数**。
type SolveStats struct {
	Depths      int `json:"depths"`
	StatesBuilt int `json:"states_built"`
	Evaluated   int `json:"evaluated"`    //: 真的跑完模拟的条数
	PlanInvalid int `json:"plan_invalid"` //: `Validate` 拦下的
	SpecFailed  int `json:"spec_failed"`  //: 造不出规格（含拒跑）
	SimFailed   int `json:"sim_failed"`   //: 模拟本身报错
	Stars3      int `json:"stars3"`
	DedupeHit   int `json:"dedupe_hit"`
	//: **首条失败的原因**。整层被丢光时，光看计数只知道"全丢了"，不知道**为什么**
	//: —— 那是本仓点名过的坏读数（"没跑"与"打输"长得一样）。它进 note。
	FirstError string `json:"first_error,omitempty"`
}

// SolveOut 是 `solve` 的应答。
type SolveOut struct {
	OK        bool            `json:"ok"`
	Plan      json.RawMessage `json:"plan,omitempty"`
	Verdict   json.RawMessage `json:"verdict,omitempty"`
	Stars     int             `json:"stars"`
	Steps     []SolveStep     `json:"steps"`
	Depth     int             `json:"depth"`
	Evaluated int             `json:"evaluated"`
	Note      string          `json:"note"`
	Covered   SolveStats      `json:"covered"`
	Params    map[string]any  `json:"params"`
	//: 助战干员的名字（`SolveQuery.Support` 的**原样回声**）。
	//:
	//: ⚠ `omitempty`：不带助战时整个键消失 ⇒ 那一轮的应答与加这个字段之前
	//: **逐字节相同**（下游对拍与缓存不受影响）。
	Support string `json:"support,omitempty"`
}

// rankKey 是 `Verdict.rank()` 的 Go 形态（全序键，越大越好）。
type rankKey struct {
	stars   int
	life    int
	kills   int
	negLost float64 //: 取负的「漏怪扣命」之和
	damage  float64
}

// better 是字典序比较：`a` 比 `b` 好吗。
func (a rankKey) better(b rankKey) bool {
	if a.stars != b.stars {
		return a.stars > b.stars
	}
	if a.life != b.life {
		return a.life > b.life
	}
	if a.kills != b.kills {
		return a.kills > b.kills
	}
	if a.negLost != b.negLost {
		return a.negLost > b.negLost
	}
	return a.damage > b.damage
}

// numOf 把 JSON 解出来的数值统一成 float64。
//
// ⚠ **不许用 `asF`**：它只认 `float64`，而 `leak_events` 里的扣命是 **int**
// （`[][3]any`）—— 用 `asF` 会把每一笔扣命都读成 0，于是 `-lost` 那一档排序
// 静默失效。这类"取成 0 但仍能跑"的假绿在 `candidates.go` 已经踩过一次。
func numOf(v any) (float64, bool) {
	switch n := v.(type) {
	case int:
		return float64(n), true
	case int64:
		return float64(n), true
	case float64:
		return n, true
	}
	return 0, false
}

// starsOf 复刻 `verify.py:38` 的 `stars_of`。
//
// 打赢且**一只没漏** → 三星；打赢但漏了怪 → **二星**（漏几只都一样 —— 只要目标
// 生命没扣完就是二星）；目标生命扣完 → 零星。**没有"一星"这一档**（旧实现写过
// 「漏 2 只及以上 1 星」，博士 2026-09-18 实机口述确认那是错的）。
//
// 突袭（`challenge`）那一档 +1 是四星，本项目不做六星档，故不参数化。
func starsOf(v *Verdict) int {
	if !v.Won {
		return 0
	}
	if v.Leaks > 0 {
		return 2
	}
	return 3
}

// rankOf 复刻 `Verdict.rank()`：`(stars, life, kills, -Σ扣命, damage)`。
func rankOf(v *Verdict) rankKey {
	lost := 0.0
	for _, e := range v.LeakEvents {
		if len(e) < 3 {
			continue
		}
		if n, ok := numOf(e[2]); ok {
			lost += n
		}
	}
	return rankKey{stars: starsOf(v), life: v.Life, kills: v.Kills,
		negLost: -lost, damage: v.DamageDealt}
}

// verdictLine 复刻 `Verdict.line()`（人读一行）。
//
// `maxLife` 取自关卡的 `options.max_life_point` —— Go 的判决里没有这一栏
// （权威的 `Verdict` 有），所以由调用方从关卡带进来。
func verdictLine(v *Verdict, maxLife int) string {
	star := ""
	for i := 0; i < 3; i++ {
		if i < starsOf(v) {
			star += "★"
		} else {
			star += "☆"
		}
	}
	state := "失败"
	if v.Won {
		state = "胜利"
	}
	return fmt.Sprintf("%s  %s  %.1fs  击杀 %d  漏怪 %d  生命 %d/%d",
		star, state, v.Elapsed, v.Kills, v.Leaks, v.Life, maxLife)
}

// planFromState 复刻 `Searcher._plan`：候选序列 → 打法。
//
// 给了 `roster` 就**把用到的练度一并写进去**（精英/等级/潜能/信赖/模组），
// 否则存下来的打法一离开名册就跑不了 —— 搜索结果应当自足。
func planFromState(stageID string, state []CandidateRow,
	roster *core.RosterRead) core.PlayPlan {
	byName := map[string]core.RosterEntry{}
	if roster != nil {
		for _, e := range roster.Entries {
			byName[e.Name] = e
		}
	}
	deploys := make([]core.DeployOrder, 0, len(state))
	for _, c := range state {
		d := core.DeployOrder{
			Operator: c.Operator, Position: c.Position,
			Direction: c.Direction, Skill: c.Skill, Mastery: c.Mastery,
		}
		if e, ok := byName[c.Operator]; ok {
			//: 只写**名册里真的有**的字段（`RosterEntry` 的零值不算「有」：
			//: 权威那边判的是 `e.get(k) is not None`）
			if e.Elite != 0 || e.Level != 0 {
				elite, level := e.Elite, e.Level
				d.Elite, d.Level = &elite, &level
			}
			if e.Potential != 0 {
				v := e.Potential
				d.Potential = &v
			}
			if e.Module != nil {
				d.Module = e.Module
			}
			if e.ModuleLevel != 0 {
				v := e.ModuleLevel
				d.ModuleLevel = &v
			}
		}
		deploys = append(deploys, d)
	}
	title := fmt.Sprintf("%d 人", len(state))
	return core.PlayPlan{Stage: stageID, Deploys: deploys, Title: title}
}

// evalState 把一个状态跑成判决（`Searcher._eval`）。
//
// 走的是 `sim` 的**查询形式**（`plan`/`roster` 由查询带进去，不写临时文件）—— 那条路
// 已被 27 套判据覆盖，解算器不另造一条。
//
// ⚠ **名册走"路径"形态（一串路径），不是内联对象**：`BuildSpecQuery` 两种形态都收，
// 但内联那份要长得像**权威的 `Roster`**（顶层 `opers`/`chars`，见 `core.rosterRows`），
// 而 `core.RosterRead` 序列化出来是 `{entries, names}` —— 喂进去会**读不到行**，
// 表现为"造规格失败、一条状态都不剩"（第一版就是这么错的，`spec_failed` 全中）。
// 路径形态顺带省掉每场求值重序列化 200 多条名册。
func evalState(level, path string, q SolveQuery, st *Stage, state []CandidateRow,
	roster *core.RosterRead) (*core.PlayPlan, *Verdict, string, error) {
	plan := planFromState(st.LevelID, state, roster)
	if err := plan.Validate(); err != nil {
		return nil, nil, "plan_invalid", err
	}
	var rosterField json.RawMessage
	if q.Roster != "" {
		rosterField = mustJSON(q.Roster)
	}
	//: 两个口径参数**显式送**（不能靠 `BuildSpecQuery` 的 `omitempty` —— 那会把
	//: `false` 变成"没送"，而权威的闸门拒收没送的查询）。nil ⇒ 照权威常量。
	allowDev, allowSkill := gateAllowDevices, gateAllowSkills
	if q.AllowDevices != nil {
		allowDev = *q.AllowDevices
	}
	if q.AllowSkills != nil {
		allowSkill = *q.AllowSkills
	}
	qj, err := json.Marshal(struct {
		Plan         json.RawMessage `json:"plan"`
		Roster       json.RawMessage `json:"roster,omitempty"`
		Difficulty   string          `json:"difficulty,omitempty"`
		AllowDevices bool            `json:"allow_devices"`
		AllowSkills  bool            `json:"allow_skills"`
	}{
		Plan:         mustJSON(plan),
		Roster:       rosterField,
		Difficulty:   q.Difficulty,
		AllowDevices: allowDev,
		AllowSkills:  allowSkill,
	})
	if err != nil {
		return nil, nil, "spec_failed", err
	}
	_, sm, err := ClassifySimSpec(qj)
	if err != nil {
		return nil, nil, "spec_failed", err
	}
	spec, _, unsup, err := BuildSimSpecFromQuery(level, path, qj, sm)
	if err != nil {
		return nil, nil, "spec_failed", err
	}
	if len(unsup) > 0 {
		//: 拒跑：这一条状态**丢弃**，但要与"打输"分开计数
		return nil, nil, "spec_failed", fmt.Errorf("闸门拒跑：%v", unsup)
	}
	v, err := runSim(spec)
	if err != nil {
		return nil, nil, "sim_failed", err
	}
	return &plan, v, "", nil
}

// mustJSON 把值序列化成 RawMessage（失败给 nil —— 调用方的 JSON 里就是"没送"）。
func mustJSON(v any) json.RawMessage {
	blob, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	return blob
}

// dedupeKey 是「同一套人」的键：`(干员, 格)` 的集合 —— **与顺序无关**。
//
// 先排序再拼，等价于 Python 的 `frozenset`（Go 的 map 迭代序随机，不能直接拼）。
func dedupeKey(state []CandidateRow) string {
	parts := make([]string, 0, len(state))
	for _, c := range state {
		parts = append(parts, fmt.Sprintf("%s@%d,%d", c.Operator,
			c.Position[0], c.Position[1]))
	}
	sort.Strings(parts)
	out := ""
	for _, p := range parts {
		out += p + "|"
	}
	return out
}

// Solve 是 beam 搜索主入口（`Searcher.search`）。
//
// ⚠ **串行**：Python 那边一层要投几百个状态给进程池（每个 worker 各起一个引擎
// 进程）。Go 这边 `runSim` 是**同进程**调用，进程启动与 IPC 往返那两笔开销直接
// 消失 —— 这是把搜索搬进引擎的真正收益。要不要再上 goroutine 等有性能读数再定
// （先保证与串行语义一致：同序、失败丢弃）。
func Solve(level, path string, q SolveQuery) (SolveOut, error) {
	out := SolveOut{Steps: []SolveStep{},
		Params: map[string]any{"level": level, "path": path,
			"operators": len(q.Operators), "max_ops": q.MaxOps,
			"beam": q.Beam, "per_op": q.PerOp, "min_ops": q.MinOps}}
	//: 助战**如实回声**（它不是搜索参数，所以不进上面那串搜索旋钮里；单独放一栏，
	//: 空的时候连键都不出现 —— 不带助战的应答与加这个字段之前逐字节相同）。
	if strings.TrimSpace(q.Support) != "" {
		out.Support = strings.TrimSpace(q.Support)
		out.Params["support"] = out.Support
	}
	var st *Stage
	var err error
	if path != "" {
		st, err = loadStageFromFile(path, q.Difficulty)
	} else {
		if level == "" {
			return out, fmt.Errorf("solve 少了 level（关卡号或 levelId）或 path（合成关卡 JSON）")
		}
		st, err = LoadStage(level)
	}
	if err != nil {
		return out, err
	}
	var roster *core.RosterRead
	if q.Roster != "" {
		rr, rerr := core.ReadRoster(q.Roster)
		if rerr != nil {
			return out, fmt.Errorf("读名册 %s 失败：%w", q.Roster, rerr)
		}
		roster = &rr
	}
	//: 第一层照旧走几何剪枝（同一份实现，不另写）
	cands, err := CandidatesFor(level, path, q.Difficulty, CandidatesQuery{
		Roster: q.Roster, Operators: q.Operators, PerOp: q.PerOp,
		Skills: q.Skills, SpeedScale: q.SpeedScale})
	if err != nil {
		return out, err
	}
	if len(cands.Rows) == 0 {
		//: ★ **空名单与"剪枝剪没了"是两回事**，别把原因指错方向
		if len(q.Operators) == 0 {
			out.Note = "候选名单是空的：搜索只在给定的名单里挑人，空名单搜不出任何东西。"
		} else {
			out.Note = "几何剪枝后一个候选都不剩 —— 所有干员的攻击范围都罩不到" +
				"敌人的行进路线。先核对落位坐标口径（MAA，原点左上）。"
		}
		return out, nil
	}
	maxOps, beam, minOps := q.MaxOps, q.Beam, q.MinOps
	if maxOps <= 0 {
		maxOps = 4
	}
	if beam <= 0 {
		beam = 5
	}
	if minOps <= 0 {
		minOps = 1
	}
	maxLife := st.Options.MaxLifePoint

	type scored struct {
		key   rankKey
		state []CandidateRow
		plan  *core.PlayPlan
		v     *Verdict
	}
	var stats SolveStats
	var beamStates []scored
	var overall *scored
	for depth := 1; depth <= maxOps; depth++ {
		stats.Depths++
		seeds := [][]CandidateRow{nil}
		if len(beamStates) > 0 {
			seeds = make([][]CandidateRow, 0, len(beamStates))
			for _, s := range beamStates {
				seeds = append(seeds, s.state)
			}
		}
		tried := 0
		states := [][]CandidateRow{}
		for _, seed := range seeds {
			usedOp := map[string]bool{}
			usedPos := map[[2]int]bool{}
			for _, c := range seed {
				usedOp[c.Operator] = true
				usedPos[c.Position] = true
			}
			for _, cand := range cands.Rows {
				if usedOp[cand.Operator] || usedPos[cand.Position] {
					continue
				}
				tried++
				next := make([]CandidateRow, 0, len(seed)+1)
				next = append(next, seed...)
				states = append(states, append(next, cand))
			}
		}
		stats.StatesBuilt += len(states)
		pool := make([]scored, 0, len(states))
		for _, s := range states {
			plan, v, why, err := evalState(level, path, q, st, s, roster)
			if err != nil {
				switch why {
				case "plan_invalid":
					stats.PlanInvalid++
				case "spec_failed":
					stats.SpecFailed++
				default:
					stats.SimFailed++
				}
				if stats.FirstError == "" {
					stats.FirstError = why + "：" + err.Error()
				}
				continue
			}
			stats.Evaluated++
			if starsOf(v) == 3 {
				stats.Stars3++
			}
			pool = append(pool, scored{key: rankOf(v), state: s, plan: plan, v: v})
		}
		if len(pool) == 0 {
			out.Note = fmt.Sprintf("第 %d 人时已经没有可加的位置了（%d 个状态全部丢弃："+
				"造规格 %d、模拟 %d、校验 %d）。首个原因：%s",
				depth, len(states), stats.SpecFailed, stats.SimFailed,
				stats.PlanInvalid, stats.FirstError)
			break
		}
		//: 按 rank 稳定降序（Python 的 `sort(reverse=True)` 稳定 ⇒ 同分保持插入序）
		sort.SliceStable(pool, func(i, j int) bool { return pool[i].key.better(pool[j].key) })
		seen := map[string]bool{}
		uniq := make([]scored, 0, len(pool))
		for _, it := range pool {
			k := dedupeKey(it.state)
			if seen[k] {
				stats.DedupeHit++
				continue
			}
			seen[k] = true
			uniq = append(uniq, it)
		}
		if len(uniq) > beam {
			uniq = uniq[:beam]
		}
		beamStates = uniq
		best := uniq[0]
		if overall == nil || best.key.better(overall.key) {
			b := best
			overall = &b
		}
		who := make([]string, 0, len(best.state))
		for _, c := range best.state {
			who = append(who, fmt.Sprintf("%s@%v%s技能%d dwell=%.1f",
				c.Operator, c.Position, string([]rune(c.Direction)[0]), c.Skill, c.Dwell))
		}
		step := SolveStep{Depth: depth, Tried: tried, Kept: len(uniq),
			Stars: starsOf(best.v), Line: verdictLine(best.v, maxLife),
			Who: who, States: len(states)}
		out.Steps = append(out.Steps, step)
		out.Depth = depth
		if starsOf(best.v) == 3 && depth >= minOps {
			out.OK = true
			out.Plan = mustJSON(best.plan)
			out.Verdict = mustJSON(best.v)
			out.Stars = 3
			out.Evaluated = stats.Evaluated
			out.Covered = stats
			return out, nil
		}
	}
	out.Evaluated = stats.Evaluated
	out.Covered = stats
	if overall != nil {
		out.Plan = mustJSON(overall.plan)
		out.Verdict = mustJSON(overall.v)
		out.Stars = starsOf(overall.v)
		if out.Note == "" {
			out.Note = fmt.Sprintf("在 %d 人以内没找到三星；最好的是 %d 人方案 —— %s",
				maxOps, len(overall.state), verdictLine(overall.v, maxLife))
		}
	}
	return out, nil
}
