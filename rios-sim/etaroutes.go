package main

// etaroutes.go：**路线生产侧的最上一层**——`eta.route_plans`（丙阶段四·第二十九批）。
//
// 权威 `ak_tactic/eta.py:122`（`route_plans`）＋`:48`（`leading_wait`）。
//
// ## 它为什么是「最上一层」
//
// 路线生产侧一共三层，前两层已经落地：
//
//	`StageMap.ground_path`  → `st.Mp.GroundPath`（`stagepath.go`，2594 例逐格一致）
//	`Route.legs`            → `st.LegsOf`        （`stagelegs.go`，2157 段逐字段一致）
//	`eta.route_plans`       → 本文件
//
// 上两层是**格子级**的；这一层把它们组装成**按路线号索引的一张表**，
// 也就是 `simgo/spec.py::_route_tables`（`:858`）返回的那个形状：
//
//	{路线号: (折线点, 入场待命秒数, 分段腿)}
//
// `spawns` 与 `unsupported` 两个键真正消费的就是这一张表，不是下面那两层。
//
// ## 三条最容易写错的
//
//  1. **`has_move` 判的是 `MOVE` 或 `APPEAR_AT_POS`，不是「有没有 checkpoints」**
//     （`eta.py:131-133`）。`WAIT_FOR_SECONDS` 不是移动，只有等待的路线照样
//     要沿可行走地块绕行——把它当「有路点」，敌人就会直线穿墙。
//  2. **寻路只在 `mode == "WALK"` 且 `has_move` 为假时发生，且是精确相等**
//     （`eta.py:134`）：`getattr(r, "mode", "WALK") == "WALK"`。
//     关卡数据里 `motionMode` 缺省解出来是**空串**（`stage.py:837`），
//     不是 `"WALK"`——写成 `.upper() == "WALK"` 或补默认值都会让
//     `mode == ""` 的那些路线**多走一次寻路**，而它们的 `pts` 本来来自路点。
//  3. **返回的是 `list(r.path)` 的一个副本**：`r.path` 是 property，
//     包含 `MOVE` 与 `APPEAR_AT_POS` 两种「真坐标」路点，首尾都要（`stage.py:372-381`）。
//
// ## 两个**结构上不可达**的分支（不是「没测到」，是可达性为零）
//
// 权威那两行各有一个兜底，它们在现有数据上永远不会执行：
//
//   - `if not pts: pts = [r.start] + [c.position …] + [r.end]`（`eta.py:138`）：
//     `StageMap.ground_path`（`stage.py:187-221`）**三条出口全部返回非空**
//     （同格 `[start]`、端点不可走 `[start, end]`、不连通 `[start, end]`）
//     ⇒ 它永远不会返回空列表。
//   - `if not legs`（`spawns` 侧 `wait=0.0 if legs else w`）：`Route.legs` 的
//     `flush()` 每次都至少产出 2 个点 ⇒ `legs` 恒非空。
//
// 两条都**照抄**（照抄才叫同一个口径），并各配一条现算守卫：判据每跑一次就把
// 这两件事在**全量关卡**上重量一遍，一旦哪天真出现（实现或数据变了），当场判红。
// 见 `tools/check_stagepath_go.py` 的 `route_plans` 段与 `STRUCTURAL_ZERO`。

import (
	"encoding/json"
	"fmt"
	"os"
)

// RoutePlan 是一条路线的可执行形态（`eta.py:71` 的 `RoutePlan`）。
//
// ⚠ 只带**被消费的那三个字段**：`_route_tables`（`spec.py:858-866`）只取
// `points` / `wait` / `legs`。`RoutePlan.mode` 与 `has_legs` / `length` /
// `fixed_seconds` / `duration` / `timeline_hint` 是展示与查询用的，没有消费者
// ——搬过来只会多出三个没有读者的字段（本项目的「无人读」清单已经够长了）。
type RoutePlan struct {
	Index  int
	Points [][2]float64
	Wait   float64
	Legs   []RouteLeg
}

// LeadingWait 复刻 `eta.leading_wait`（`:48`）：**开头连续**的
// `WAIT_FOR_SECONDS` 之和。
//
// ⚠ 判据是**精确相等** `type == "WAIT_FOR_SECONDS"`，与 `Route.legs` 里的
// `startswith("WAIT")` **不是同一条规则**（`stage.py:288` vs `stagelegs.go`）。
// 两处都要照各自的原样：这里写成 `startswith` 会把中段的 `WAIT_CUSTOM`
// 也算进入场待命，而那里写成相等会漏掉一整类等待。
//
// 一旦出现非 `WAIT_FOR_SECONDS` 的检查点就**停**：后面的等待是「走到那儿再等」，
// 属于路径中段（SR-EX-8 有 60 秒的那种）。
func (st *Stage) LeadingWait(r Route) float64 {
	total := 0.0
	for _, c := range r.Checkpoints {
		if c.Type != "WAIT_FOR_SECONDS" {
			break
		}
		total += c.Wait //: 权威也是朴素 `+=`（只有内建 sum() 才走补偿求和）
	}
	return total
}

// RoutePath 复刻 `Route.path`（`stage.py:372`）：敌人实际站过的格子，含首尾。
//
// 只有 `MOVE` 与 `APPEAR_AT_POS` 是真坐标（`stage.go` 里 `Position != nil`
// 正是这两种），`WAIT*` / `DISAPPEAR` 的 position 是占位、**不能当坐标读**。
func (st *Stage) RoutePath(r Route) [][2]int {
	pts := make([][2]int, 0, len(r.Checkpoints)+2)
	pts = append(pts, r.Start)
	for _, c := range r.Checkpoints {
		if c.Position != nil {
			pts = append(pts, *c.Position)
		}
	}
	return append(pts, r.End)
}

// HasMove 判这条路线有没有**真坐标路点**（`eta.py:131-133` 的 `has_move`）。
func HasMove(r Route) bool {
	for _, c := range r.Checkpoints {
		if c.Type == "MOVE" || c.Type == "APPEAR_AT_POS" {
			return true
		}
	}
	return false
}

// RoutePlanStats 是**行使计数**：每条分支被走到几次。
//
// 0 的项由判据侧另行登记（结构不可达的用 STRUCTURAL_ZERO ＋ 现算守卫），
// 不在这里静默消失——「这条线没跑」与「这条线跑了 0 次」必须长得不一样。
type RoutePlanStats struct {
	Routes                 int `json:"routes"`
	HasMove                int `json:"has_move"`
	NoMove                 int `json:"no_move"`
	WalkMode               int `json:"walk_mode"`
	NonWalkMode            int `json:"non_walk_mode"`
	SearchUsed             int `json:"search_used"`
	SearchNotUsedNoMove    int `json:"search_not_used_no_move"`
	SearchEmpty            int `json:"search_empty"`
	SearchSinglePoint      int `json:"search_single_point"`
	SearchStraightFallback int `json:"search_straight_fallback"`
	PathFallback           int `json:"path_fallback"`
	LegsEmpty              int `json:"legs_empty"`
	WaitPositive           int `json:"wait_positive"`
}

// RoutePlans 复刻 `eta.route_plans`（`:122`）：按路线号索引的 `RoutePlan` 表。
//
// 第二返回值是**按 `st.Routes` 顺序**排好的一份（等于按路线号的顺序），
// 第三份是行使计数。三者同一次遍历产出——分两次算就会有两份口径。
func (st *Stage) RoutePlans() (map[int]RoutePlan, []RoutePlan, RoutePlanStats) {
	out := make(map[int]RoutePlan, len(st.Routes))
	ordered := make([]RoutePlan, 0, len(st.Routes))
	var stats RoutePlanStats

	for _, r := range st.Routes {
		stats.Routes++
		hasMove := HasMove(r)
		if hasMove {
			stats.HasMove++
		} else {
			stats.NoMove++
		}
		if r.Mode == "WALK" {
			stats.WalkMode++
		} else {
			stats.NonWalkMode++
		}

		pts := st.RoutePath(r)
		if !hasMove && r.Mode == "WALK" {
			stats.SearchUsed++
			walked := st.Map.GroundPath(r.Start, r.End, true)
			switch {
			case len(walked) == 0:
				stats.SearchEmpty++
			case len(walked) == 1:
				stats.SearchSinglePoint++
			case len(walked) == 2 && (walked[1][0]-walked[0][0] > 1 ||
				walked[0][0]-walked[1][0] > 1 || walked[1][1]-walked[0][1] > 1 ||
				walked[0][1]-walked[1][1] > 1):
				//: 退回直线的形状：相邻两点跨格（寻路结果永远只走单位步与斜步）。
				stats.SearchStraightFallback++
			}
			pts = walked
		} else if !hasMove {
			stats.SearchNotUsedNoMove++
		}

		if len(pts) == 0 {
			//: `eta.py:138` 的兜底。**结构上不可达**（见文件头），照抄并计数。
			stats.PathFallback++
			pts = make([][2]int, 0, len(r.Checkpoints)+2)
			pts = append(pts, r.Start)
			for _, c := range r.Checkpoints {
				if c.Position != nil {
					pts = append(pts, *c.Position)
				}
			}
			pts = append(pts, r.End)
		}

		points := make([][2]float64, 0, len(pts))
		for _, p := range pts {
			points = append(points, [2]float64{float64(p[0]), float64(p[1])})
		}
		legs := st.LegsOf(r)
		wait := st.LeadingWait(r)
		if len(legs) == 0 {
			stats.LegsEmpty++
		}
		if wait != 0 {
			stats.WaitPositive++
		}
		plan := RoutePlan{Index: r.Index, Points: points, Legs: legs,
			Wait: wait}
		out[r.Index] = plan
		ordered = append(ordered, plan)
	}
	return out, ordered, stats
}

// RoutePlanRow 是应答里的一行：`{路线号: (折线点, 待命, 分段腿)}` 的 JSON 投影。
//
// ⚠ **不用 `omitempty`**（四个键一律写）：`wait` 是 0 与「没有这个键」是两回事，
// 而 0 秒待命在 55 关里有 1271 条——省掉它们会让回读方把绝大多数读成「没送」。
type RoutePlanRow struct {
	Index  int          `json:"index"`
	Points [][2]float64 `json:"points"`
	Wait   float64      `json:"wait"`
	Legs   []RouteLeg   `json:"legs"`
}

// RoutePlansQuery 是 `routeplans` 命令的 spec 体。
//
// 只有难度一项：`route_plans` 不吃别的参数（它连计划都不吃——路线是关卡数据）。
// 难度会落到合成关卡那一支（`ParseStage` 的 difficulty），并按 `Params` 回显。
type RoutePlansQuery struct {
	Difficulty string `json:"difficulty,omitempty"`
}

// RoutePlansOut 是 `routeplans` 的应答。
type RoutePlansOut struct {
	Routes []RoutePlanRow `json:"routes"`
	//: 行使计数（见 `RoutePlanStats`）。判据拿它核对「Go 真走到了哪几条分支」，
	//: 而不是只看值相等——值相等而分支没走到的绿是零信息量的绿。
	Covered RoutePlanStats `json:"covered"`
	//: 口径与对象身份原样回显（哪一关、按哪个路径问的），判据据此核对。
	Params map[string]any `json:"params"`
}

// RoutePlansOf 取一关的路线计划表。
//
// 关卡走 `level`（关卡号／levelId）或 `path`（合成关卡 JSON 文件），
// 与 `stageenv` / `unsupported` 同一口径。
func RoutePlansOf(level, path, difficulty string) (RoutePlansOut, error) {
	out := RoutePlansOut{
		Routes: []RoutePlanRow{},
		Params: map[string]any{"level": level, "path": path,
			"difficulty": difficulty},
	}
	var st *Stage
	var err error
	if path != "" {
		st, err = loadStageFromFile(path, difficulty)
	} else {
		if level == "" {
			return out, fmt.Errorf("routeplans 少了 level（关卡号或 levelId）或 path（合成关卡 JSON）")
		}
		st, err = LoadStage(level)
	}
	if err != nil {
		return out, err
	}
	_, ordered, stats := st.RoutePlans()
	out.Covered = stats
	for _, p := range ordered {
		legs := p.Legs
		if legs == nil {
			legs = []RouteLeg{}
		}
		out.Routes = append(out.Routes, RoutePlanRow{
			Index: p.Index, Points: p.Points, Wait: p.Wait, Legs: legs,
		})
	}
	return out, nil
}

// loadStageFromFile 读一份**合成关卡**并解析（`unsupported` 的 `path` 用的是同一套）。
//
// 与 `LoadStage` 的差别只有取数入口：那里走 `_level_index.json`，这里直接读文件。
// 两者最后都落到 `ParseStage`，所以解析口径只有一份。
func loadStageFromFile(path, difficulty string) (*Stage, error) {
	blob, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("合成关卡读不出来（%s）：%w", path, err)
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(blob, &raw); err != nil {
		return nil, fmt.Errorf("合成关卡不是合法 JSON（%s）：%w", path, err)
	}
	return ParseStage(raw, "", "", difficulty)
}
