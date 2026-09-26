package main

import (
	"fmt"
	"math"
	"sort"
)

// # 到达表：`ak_tactic/eta.py:176-405` 的 Go 侧对应物
//
// 这一层回答两个问题，搜索层全靠它：
//
//  1. **每只敌人什么时候占着哪一格**（`Visit`：进入时刻、离开时刻）；
//  2. **一片格子上累计待了多少敌人·秒**（`ArrivalIndex.Dwell`）——这是落位价值的
//     便宜上界：一个干员的攻击格集合里敌人待得越久，它越可能值得放，**不用跑模拟**。
//
// 上游三层已经各有 Go 实现，本文件只补最上面这一层：
// `Timeline()`（`spawns.go`，出怪时刻表）＋ `RoutePlans()`（`etaroutes.go`，路线计划）
// ＋ `EnemyLibrary.At`（`enemy.go`，敌人属性）⇒ `EnemyArrivals`。
//
// ## 三处口径不许随手改
//
//   - **取整走 `math.RoundToEven`**（`result = round(position)`）：Python 内建
//     `round` 是银行家舍入，Go 的 `math.Round` 在 `.5` 上给相反的结果。
//     `operator.go:11` 把这条写成了硬规矩，这里照办。
//   - **求和走 `sumLikePython`**（`stagelegs.go`）：CPython 3.12+ 的内建 `sum()`
//     对浮点是 Neumaier 补偿求和，朴素 `+=` 会在末位差出来。
//   - **排序一律 `sort.SliceStable`**：Python 的 `list.sort` 稳定，而 `sort.Slice`
//     不稳定 —— 同 `enter` 的两条 visit 换个顺序，下游按序切片的产物就变了。
//
// ## 起点那半格为什么要算
//
// `_walk_visits` 给**起点**也记一格（`eta.py:225-233`）：敌人在出生点要待过半格时间，
// 站在出生点旁边的干员是真的能打到它的。早先这里直接跳过，热度图上出生点恒为 0，
// 看着像「没人经过」——那是个会让人做出错误布阵的假读数。

// Visit 是某只敌人占据某一格的时段（`eta.py:176` 的 `Visit`）。
type Visit struct {
	Cell    [2]int  `json:"cell"`
	Enter   float64 `json:"enter"`
	Exit    float64 `json:"exit"`
	Name    string  `json:"name"`
	EnemyID string  `json:"enemy_id"`
	Route   int     `json:"route"`
}

// Dwell 是这次占据持续了多久（`eta.py:187` 的 `dwell`：**不小于 0**）。
func (v Visit) Dwell() float64 { return math.Max(0, v.Exit-v.Enter) }

// EnemyArrival 是一只敌人从入场到抵达终点（或离场）的全过程（`eta.py:192`）。
type EnemyArrival struct {
	EnemyID   string
	Name      string
	Level     int
	Route     int
	Spawn     float64
	Speed     float64
	Length    float64
	Visits    []Visit
	StartsAt  float64
	ArrivesAt float64 //: 可能是 `+Inf`（没人拦就永远到不了 —— 移速 0 或中途离场）
	Vanished  bool
}

// Travel 是整段行程耗时（`eta.py:211` 的 `travel`）。
func (a EnemyArrival) Travel() float64 { return a.ArrivesAt - a.Spawn }

// walkVisits 复刻 `_walk_visits`（`eta.py:216`）：沿折线走，产出每一格的占据时段。
//
// 返回 (visits, 结束时刻)。折线不足两点时**原样返回 t0**（不是 inf）—— 这是权威的
// 行为，别"顺手改得更合理"。
func walkVisits(pts [][2]float64, t0, speed float64, name, enemyID string,
	route int) ([]Visit, float64) {
	out := []Visit{}
	if len(pts) < 2 {
		return out, t0
	}
	cum := 0.0
	for i, p := range pts {
		if i == 0 {
			seg := math.Hypot(pts[1][0]-p[0], pts[1][1]-p[1])
			if seg == 0 {
				seg = 1.0 //: 权威的 `or 1.0`
			}
			half := 0.0
			if speed > 0 {
				half = 0.5 * seg / speed
			}
			cell := [2]int{int(math.RoundToEven(p[0])), int(math.RoundToEven(p[1]))}
			out = append(out, Visit{Cell: cell, Enter: t0, Exit: t0 + half,
				Name: name, EnemyID: enemyID, Route: route})
			continue
		}
		seg := math.Hypot(p[0]-pts[i-1][0], p[1]-pts[i-1][1])
		cum += seg
		if speed <= 0 {
			continue
		}
		tv := t0 + cum/speed
		half := 0.5 * seg / speed
		cell := [2]int{int(math.RoundToEven(p[0])), int(math.RoundToEven(p[1]))}
		out = append(out, Visit{Cell: cell, Enter: tv - half, Exit: tv + half,
			Name: name, EnemyID: enemyID, Route: route})
	}
	end := math.Inf(1)
	if speed > 0 {
		end = t0 + cum/speed
	}
	return out, end
}

// Length 是整条路线的**行走**总格数，不含待命与离场（`eta.py:85` 的 `length`）。
//
// 加在 `RoutePlan` 上而不是加字段：`routeplans` 的应答形状已经被判据钉住了
// （`check_stagepath_go.py` 逐字段比），多一个字段就是在改那份契约。
func (p RoutePlan) Length() float64 {
	if len(p.Legs) > 0 {
		xs := make([]float64, 0, len(p.Legs))
		for _, l := range p.Legs {
			xs = append(xs, l.Length)
		}
		return sumLikePython(xs)
	}
	xs := make([]float64, 0, len(p.Points))
	for i := 1; i < len(p.Points); i++ {
		xs = append(xs, math.Hypot(p.Points[i][0]-p.Points[i-1][0],
			p.Points[i][1]-p.Points[i-1][1]))
	}
	return sumLikePython(xs)
}

// HasLegs 是 `eta.py:82` 的 `has_legs`。
func (p RoutePlan) HasLegs() bool { return len(p.Legs) > 0 }

// ArrivalStats 是**行使计数**：这张表是哪几条分支产出的。
//
// 与 `RoutePlanStats` 同一用意：0 的项要能被看见（「这条线没跑」与「这条线跑了 0 次」
// 必须长得不一样），判据侧据此决定是登记还是查错。
type ArrivalStats struct {
	Timeline    int `json:"timeline"`
	PlanMissing int `json:"plan_missing"`
	HasLegs     int `json:"has_legs"`
	Straight    int `json:"straight"`
	WalkLegs    int `json:"walk_legs"`
	VanishLegs  int `json:"vanish_legs"`
	WaitLegs    int `json:"wait_legs"`
	SpeedZero   int `json:"speed_zero"`
	Visits      int `json:"visits"`
	ArrivesInf  int `json:"arrives_inf"`
	Vanished    int `json:"vanished"`
}

// EnemyArrivals 复刻 `enemy_arrivals`（`eta.py:247`）：按 `stage.timeline()` 把每只
// 敌人的到达时刻全算出来。
//
// `speedScale` 是给「敌速未知量扫描」用的：整关敌人一起加速/减速，缺省 1.0 就是关卡
// 数据本身的值。`plans` 为 nil 时现算（与权威的 `plans or route_plans(stage)` 同）。
//
// `enemyAt` 是取敌人属性的出口：默认走 `EnemyLibrary.At`（与 `check_eta.py` 里那条
// `lib.get` 同口径）。**刻意不在这里塞本地覆盖（`StatsForSpawn`）** —— 那是另一个
// 出口，等接入搜索层时按那边的口径核过再决定，先与本层参照实现对齐。
func EnemyArrivals(st *Stage, lib *EnemyLibrary, speedScale float64,
	plans map[int]RoutePlan) ([]EnemyArrival, ArrivalStats, error) {
	var stats ArrivalStats
	if speedScale == 0 {
		speedScale = 1.0
	}
	if plans == nil {
		plans, _, _ = st.RoutePlans()
	}
	//: ★ 权威写的是 `float(getattr(options, "move_multiplier", 1.0) or 1.0)` —— 注意那个
	//: `or`：**0 会被兜成 1.0**。照抄这一条，别"顺手"把 0 当合法移速乘数：那会让整关
	//: 敌人一动不动，而到达表照样算得出来（最难查的那一类错）。
	mul := st.Options.MoveMultiplier
	if mul == 0 {
		mul = 1.0
	}
	out := []EnemyArrival{}
	for _, item := range st.Timeline() {
		stats.Timeline++
		spawnT := item.Time
		enemyID := item.Spawn.EnemyID
		level := item.Spawn.Level
		routeIndex := item.Spawn.RouteIndex
		plan, ok := plans[routeIndex]
		if !ok {
			stats.PlanMissing++
			continue
		}
		es, err := lib.At(enemyID, level)
		if err != nil {
			return nil, stats, fmt.Errorf("取敌人 %s（第 %d 档）失败：%w", enemyID, level, err)
		}
		name := es.Name
		if name == "" {
			name = enemyID
		}
		ms := 1.0
		if es.MoveSpeed != nil {
			ms = *es.MoveSpeed
		}
		speed := math.Max(0, ms) * mul * speedScale
		if speed <= 0 {
			stats.SpeedZero++
		}

		visits := []Visit{}
		t := spawnT
		vanished := false
		var arrives float64
		if plan.HasLegs() {
			stats.HasLegs++
			for _, leg := range plan.Legs {
				switch leg.Kind {
				case "walk":
					stats.WalkLegs++
					pts := make([][2]float64, 0, len(leg.Points))
					for _, p := range leg.Points {
						pts = append(pts, [2]float64{float64(p[0]), float64(p[1])})
					}
					vs, nt := walkVisits(pts, t, speed, name, enemyID, routeIndex)
					visits = append(visits, vs...)
					t = nt
				case "vanish":
					stats.VanishLegs++
					vanished = true
					t += leg.Seconds
				default:
					stats.WaitLegs++
					if len(visits) > 0 {
						last := visits[len(visits)-1]
						visits[len(visits)-1] = Visit{Cell: last.Cell, Enter: last.Enter,
							Exit: last.Exit + leg.Seconds, Name: name,
							EnemyID: enemyID, Route: routeIndex}
					}
					t += leg.Seconds
				}
			}
			arrives = t
		} else {
			stats.Straight++
			starts := t + plan.Wait
			vs, arr := walkVisits(plan.Points, starts, speed, name, enemyID, routeIndex)
			if plan.Wait != 0 && len(vs) > 0 {
				first := vs[0]
				vs[0] = Visit{Cell: first.Cell, Enter: t, Exit: first.Exit,
					Name: name, EnemyID: enemyID, Route: routeIndex}
			}
			visits = append(visits, vs...)
			arrives = arr
		}
		stats.Visits += len(visits)
		if vanished {
			stats.Vanished++
		}
		final := arrives
		if speed <= 0 {
			final = math.Inf(1)
			stats.ArrivesInf++
		}
		out = append(out, EnemyArrival{
			EnemyID: enemyID, Name: name, Level: level, Route: routeIndex,
			Spawn: spawnT, Speed: speed, Length: plan.Length(),
			Visits: visits, StartsAt: spawnT + plan.Wait,
			ArrivesAt: final, Vanished: vanished,
		})
	}
	return out, stats, nil
}

// ---------------------------------------------------------------- 查询索引

// ArrivalIndex 按格反查「什么时候有敌人经过」，以及「在给定格集合里待了多少敌人·秒」
// （`eta.py:327` 的 `ArrivalIndex`）。
type ArrivalIndex struct {
	Arrivals []EnemyArrival
	byCell   map[[2]int][]Visit
}

// NewArrivalIndex 建索引。同一格的多条 visit **按 `enter` 稳定排序** —— 与权威的
// `vs.sort(key=lambda v: v.enter)` 同口径（Python 的排序稳定，Go 这里也必须稳定：
// 下游 `visits()` 按序拼接，平局顺序变了，切片结果就变了）。
func NewArrivalIndex(arrivals []EnemyArrival) *ArrivalIndex {
	idx := &ArrivalIndex{Arrivals: arrivals, byCell: map[[2]int][]Visit{}}
	for _, a := range arrivals {
		for _, v := range a.Visits {
			idx.byCell[v.Cell] = append(idx.byCell[v.Cell], v)
		}
	}
	for _, vs := range idx.byCell {
		sort.SliceStable(vs, func(i, j int) bool { return vs[i].Enter < vs[j].Enter })
	}
	return idx
}

// Cells 是有敌人经过的格，按 (x, y) 排序（`eta.py:345`）。
func (idx *ArrivalIndex) Cells() [][2]int {
	out := make([][2]int, 0, len(idx.byCell))
	for c := range idx.byCell {
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i][0] != out[j][0] {
			return out[i][0] < out[j][0]
		}
		return out[i][1] < out[j][1]
	})
	return out
}

// At 是某一格上的全部 visit（`eta.py:348`）。
func (idx *ArrivalIndex) At(cell [2]int) []Visit {
	return append([]Visit(nil), idx.byCell[cell]...)
}

// First 是某一格上**最早**的进入时刻；没有经过则返回 false（`eta.py:351` 的 `None`）。
func (idx *ArrivalIndex) First(cell [2]int) (float64, bool) {
	vs := idx.byCell[cell]
	if len(vs) == 0 {
		return 0, false
	}
	best := vs[0].Enter
	for _, v := range vs[1:] {
		if v.Enter < best {
			best = v.Enter
		}
	}
	return best, true
}

// Visits 是一片格子上的全部 visit，按 enter 排序（`eta.py:357`）。
func (idx *ArrivalIndex) Visits(cells [][2]int) []Visit {
	out := []Visit{}
	for _, c := range cells {
		out = append(out, idx.byCell[c]...)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Enter < out[j].Enter })
	return out
}

// Names 是每只敌人**几次**会进入这片格子（同一只分两次经过算两次，`eta.py:364`）。
func (idx *ArrivalIndex) Names(cells [][2]int) map[string]int {
	out := map[string]int{}
	for _, v := range idx.Visits(cells) {
		out[v.Name]++
	}
	return out
}

// Dwell 是这片格子上累计的**敌人·秒**（可加时间窗，`eta.py:371`）。
//
// 这就是「这个落位能接到多少活」的便宜度量。它只是上界——干员打不打得动、
// 会不会被反杀，模拟器才知道——但用来**剪枝**足够：dwell 为零的落位连试都不必试。
func (idx *ArrivalIndex) Dwell(cells [][2]int, t0, t1 float64) float64 {
	total := 0.0
	for _, v := range idx.Visits(cells) {
		lo, hi := math.Max(v.Enter, t0), math.Min(v.Exit, t1)
		if hi > lo {
			total += hi - lo
		}
	}
	return total
}

// Count 是有几次「进入」落在这个时间窗里（`eta.py:386`）。
func (idx *ArrivalIndex) Count(cells [][2]int, t0, t1 float64) int {
	n := 0
	for _, v := range idx.Visits(cells) {
		if t0 <= v.Enter && v.Enter <= t1 {
			n++
		}
	}
	return n
}

// CellDwell 是某一格自己的累计占据时长（`busiest` 用的那个量）。
func (idx *ArrivalIndex) CellDwell(cell [2]int) float64 {
	total := 0.0
	for _, v := range idx.byCell[cell] {
		total += v.Dwell()
	}
	return total
}

// BusiestRow 是「最忙的格子」一行（`eta.py:392` 的 `busiest` 的产物）。
type BusiestRow struct {
	Cell  [2]int  `json:"cell"`
	Dwell float64 `json:"dwell"`
}

// Busiest 按累计占据时长排出最忙的格子 —— 摆位的第一手直觉。
//
// ⚠ 平局按格子坐标定序，而 Python 那边是稳定排序作用在 `dict` 的**插入序**上
// （先插入的在前）。**登记为分歧**：只影响并列项的展示顺序，不影响任何数值；
// 但判据比这一项时要么按 (格, 时长) 化成集合比，要么把平局剔除。
func (idx *ArrivalIndex) Busiest(top int) []BusiestRow {
	rows := make([]BusiestRow, 0, len(idx.byCell))
	for c := range idx.byCell {
		rows = append(rows, BusiestRow{Cell: c, Dwell: idx.CellDwell(c)})
	}
	sort.SliceStable(rows, func(i, j int) bool {
		if rows[i].Dwell != rows[j].Dwell {
			return rows[i].Dwell > rows[j].Dwell
		}
		if rows[i].Cell[0] != rows[j].Cell[0] {
			return rows[i].Cell[0] < rows[j].Cell[0]
		}
		return rows[i].Cell[1] < rows[j].Cell[1]
	})
	if top > 0 && len(rows) > top {
		rows = rows[:top]
	}
	return rows
}

// Span 是整张表的时间跨度 `(最早入场, 最晚抵达)`（`eta.py:399`）。
//
// 「最晚抵达」只统计**有限**的抵达时刻：移速 0 与中途离场的那几只的 `arrives_at`
// 是 `+Inf`，落进 max 里会把整个跨度变成 Inf。全表都是 Inf 时权威给 0。
func (idx *ArrivalIndex) Span() (float64, float64) {
	if len(idx.Arrivals) == 0 {
		return 0, 0
	}
	lo := math.Inf(1)
	hi := math.Inf(-1)
	anyFinite := false
	for _, a := range idx.Arrivals {
		lo = math.Min(lo, a.Spawn)
		if !math.IsInf(a.ArrivesAt, 1) {
			hi = math.Max(hi, a.ArrivesAt)
			anyFinite = true
		}
	}
	if !anyFinite {
		return lo, 0
	}
	return lo, hi
}

// ---------------------------------------------------------------- 命令面

// ArrivalsQuery 是 `arrivals` 命令的 spec。
type ArrivalsQuery struct {
	Difficulty string   `json:"difficulty"`
	SpeedScale float64  `json:"speed_scale"`
	Cells      [][2]int `json:"cells"` //: 给了就顺带算这片格子的 dwell／count／names
}

// ArrivalRow 是**上线形态**的 EnemyArrival：`arrives_at` 是 `*float64`，
// `null` 表示 `+Inf`。JSON 编不出 Inf，硬编会当场报错或写出 `Inf` 这种非法字面量；
// 用 null 表示并**在判据里把 Python 的 inf 映射成 None** 是唯一干净的做法。
type ArrivalRow struct {
	EnemyID   string   `json:"enemy_id"`
	Name      string   `json:"name"`
	Level     int      `json:"level"`
	Route     int      `json:"route"`
	Spawn     float64  `json:"spawn"`
	Speed     float64  `json:"speed"`
	Length    float64  `json:"length"`
	StartsAt  float64  `json:"starts_at"`
	ArrivesAt *float64 `json:"arrives_at"`
	Vanished  bool     `json:"vanished"`
	Visits    []Visit  `json:"visits"`
}

// CellsOut 是指定格集合上的一次查询（给了 cells 才有）。
type CellsOut struct {
	Cells [][2]int       `json:"cells"`
	Dwell float64        `json:"dwell"`
	Count int            `json:"count"`
	Names map[string]int `json:"names"`
}

// ArrivalsOut 是 `arrivals` 的应答。
//
// 逐条敌人放在 `rows` 而不是 `arrivals`：外层那个 `arrivals` 是这一整份应答
// （`response.arrivals`），内层再叫一次就成了 `arrivals.arrivals` —— 判据与判据
// 的读者都会被它绊一下。
type ArrivalsOut struct {
	Rows    []ArrivalRow   `json:"rows"`
	Span    [2]float64     `json:"span"`
	Busiest []BusiestRow   `json:"busiest"`
	Cells   *CellsOut      `json:"cells,omitempty"`
	Covered ArrivalStats   `json:"covered"`
	Params  map[string]any `json:"params"`
}

// ArrivalsOf 是命令入口：与 `routeplans`／`spawns` 同口径（关卡走 level 或合成关卡的 path）。
func ArrivalsOf(level, path, difficulty string, speedScale float64,
	cells [][2]int) (ArrivalsOut, error) {
	out := ArrivalsOut{Rows: []ArrivalRow{}, Busiest: []BusiestRow{},
		Params: map[string]any{"level": level, "path": path,
			"difficulty": difficulty, "speed_scale": speedScale}}
	var st *Stage
	var err error
	if path != "" {
		st, err = loadStageFromFile(path, difficulty)
	} else {
		if level == "" {
			return out, fmt.Errorf("arrivals 少了 level（关卡号或 levelId）或 path（合成关卡 JSON）")
		}
		st, err = LoadStage(level)
	}
	if err != nil {
		return out, err
	}
	lib, err := LoadEnemyLibrary()
	if err != nil {
		return out, err
	}
	arrivals, stats, err := EnemyArrivals(st, lib, speedScale, nil)
	if err != nil {
		return out, err
	}
	out.Covered = stats
	for _, a := range arrivals {
		row := ArrivalRow{
			EnemyID: a.EnemyID, Name: a.Name, Level: a.Level, Route: a.Route,
			Spawn: a.Spawn, Speed: a.Speed, Length: a.Length,
			StartsAt: a.StartsAt, Vanished: a.Vanished,
			Visits: a.Visits,
		}
		if !math.IsInf(a.ArrivesAt, 1) {
			v := a.ArrivesAt
			row.ArrivesAt = &v
		}
		out.Rows = append(out.Rows, row)
	}
	idx := NewArrivalIndex(arrivals)
	lo, hi := idx.Span()
	out.Span = [2]float64{lo, hi}
	out.Busiest = idx.Busiest(12)
	if cells != nil {
		out.Cells = &CellsOut{
			Cells: cells,
			Dwell: idx.Dwell(cells, math.Inf(-1), math.Inf(1)),
			Count: idx.Count(cells, math.Inf(-1), math.Inf(1)),
			Names: idx.Names(cells),
		}
	}
	return out, nil
}
