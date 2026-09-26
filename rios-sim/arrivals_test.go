package main

import (
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// # 到达表（`arrivals.go`）的 Go 侧判据
//
// 分两层，缺一层就会有一条看不见的假绿：
//
//   - **手算的折线用例**：期望值是拿笔算出来的（不是从实现里抄的），它钉住的是
//     `_walk_visits` 那条算法本身 —— 起点算半格、每格 `[tv-half, tv+half]`、
//     末时刻 `t0 + cum/speed`；
//   - **真关卡上的不变量**：量很大（41 条出怪、533 条 visit），逐条对期望不现实，
//     所以对**能从两个独立来源算出来的量**下断言（计数、可加性、排序、跨度），
//     并且每个「零」都配一个正对照。
//
// ⚠ 与 Python 的**逐字段对拍**不在这里 —— 那是 `tools/check_stagepath_go.py`
// （期望值通道）那一套的活。本文件证明的是「实现自洽」，不是「与权威一致」。

func approx(a, b float64) bool {
	if math.IsInf(a, 1) && math.IsInf(b, 1) {
		return true
	}
	return math.Abs(a-b) <= 1e-9*math.Max(1, math.Max(math.Abs(a), math.Abs(b)))
}

// TestWalkVisitsHandComputed 是手算用例：三点折线，速度 1 格/秒。
//
//	pts = (0,0) → (3,0) → (3,4)，t0 = 0
//	第 0 格：seg=hypot(3,0)=3 ⇒ half=1.5 ⇒ (0,0) 占 [0, 1.5]
//	第 1 格：cum=3, tv=3   ⇒ half=1.5 ⇒ (3,0) 占 [1.5, 4.5]
//	第 2 格：cum=7, tv=7   ⇒ half=2.0 ⇒ (3,4) 占 [5.0, 9.0]
//	末时刻：t0 + cum/speed = 7.0
func TestWalkVisitsHandComputed(t *testing.T) {
	pts := [][2]float64{{0, 0}, {3, 0}, {3, 4}}
	vs, end := walkVisits(pts, 0, 1, "甲", "enemy_x", 2)
	want := []Visit{
		{Cell: [2]int{0, 0}, Enter: 0, Exit: 1.5},
		{Cell: [2]int{3, 0}, Enter: 1.5, Exit: 4.5},
		{Cell: [2]int{3, 4}, Enter: 5.0, Exit: 9.0},
	}
	if len(vs) != len(want) {
		t.Fatalf("visit 条数 = %d，手算 %d", len(vs), len(want))
	}
	for i := range want {
		if vs[i].Cell != want[i].Cell || !approx(vs[i].Enter, want[i].Enter) ||
			!approx(vs[i].Exit, want[i].Exit) {
			t.Errorf("第 %d 条 = %+v，手算 %+v", i, vs[i], want[i])
		}
		if vs[i].Name != "甲" || vs[i].EnemyID != "enemy_x" || vs[i].Route != 2 {
			t.Errorf("第 %d 条的标注没带上：%+v", i, vs[i])
		}
	}
	if !approx(end, 7.0) {
		t.Errorf("末时刻 = %v，手算 7", end)
	}
	//: 负对照 1：折线不足两点 ⇒ 原样返回 t0（**不是** inf，别顺手改合理）
	vsShort, endShort := walkVisits([][2]float64{{1, 1}}, 5, 1, "甲", "e", 0)
	if len(vsShort) != 0 || !approx(endShort, 5) {
		t.Errorf("单点折线应返回 (空, 5)，实得 (%d 条, %v)", len(vsShort), endShort)
	}
	//: 负对照 2：移速 0 ⇒ 只有起点那半格且时长为 0，末时刻是 +Inf
	vsZero, endZero := walkVisits(pts, 0, 0, "甲", "e", 0)
	if len(vsZero) != 1 || vsZero[0].Dwell() != 0 || !math.IsInf(endZero, 1) {
		t.Errorf("移速 0 应给 (1 条零长 visit, +Inf)，实得 (%d 条, %v)", len(vsZero), endZero)
	}
}

// TestRoutePlanLength 走两条分支（权威的 `length` 也是这两支）。
func TestRoutePlanLength(t *testing.T) {
	legs := RoutePlan{Legs: []RouteLeg{{Kind: "walk", Length: 3.5},
		{Kind: "walk", Length: 2.5}}}
	if got := legs.Length(); !approx(got, 6.0) {
		t.Errorf("有分段时 length = %v，要 6（各段之和）", got)
	}
	straight := RoutePlan{Points: [][2]float64{{0, 0}, {3, 4}}}
	if got := straight.Length(); !approx(got, 5.0) {
		t.Errorf("无分段时 length = %v，要 5（折线长度 3-4-5）", got)
	}
	if !legs.HasLegs() || straight.HasLegs() {
		t.Errorf("HasLegs 判反了：legs=%v straight=%v", legs.HasLegs(), straight.HasLegs())
	}
}

// TestArrivalIndexEmptyIsNotZeroTraffic 是**空表**那一侧：负对照要先能红。
//
// 空表上「没有敌人经过」与「敌人经过了但时长为 0」必须分得开 —— 前者 `First` 给
// false，后者给一个 0 时刻的真值。
func TestArrivalIndexEmptyIsNotZeroTraffic(t *testing.T) {
	idx := NewArrivalIndex(nil)
	if lo, hi := idx.Span(); lo != 0 || hi != 0 {
		t.Errorf("空表跨度应为 (0,0)，实得 (%v,%v)", lo, hi)
	}
	if _, ok := idx.First([2]int{1, 1}); ok {
		t.Errorf("空表上 First 必须给 false")
	}
	if d := idx.Dwell([][2]int{{1, 1}}, math.Inf(-1), math.Inf(1)); d != 0 {
		t.Errorf("空表上 Dwell 应为 0，实得 %v", d)
	}
	if n := idx.Count([][2]int{{1, 1}}, math.Inf(-1), math.Inf(1)); n != 0 {
		t.Errorf("空表上 Count 应为 0，实得 %d", n)
	}
	if len(idx.Cells()) != 0 || len(idx.Busiest(3)) != 0 {
		t.Errorf("空表上不该有格")
	}
	//: 正对照：同一条 visit 放进索引之后，上面四个量必须**都动**
	idx2 := NewArrivalIndex([]EnemyArrival{{Name: "甲", Visits: []Visit{
		{Cell: [2]int{1, 1}, Enter: 2, Exit: 5, Name: "甲"}}}})
	if _, ok := idx2.First([2]int{1, 1}); !ok {
		t.Errorf("正对照失败：有 visit 却 First 给 false")
	}
	if d := idx2.Dwell([][2]int{{1, 1}}, math.Inf(-1), math.Inf(1)); !approx(d, 3) {
		t.Errorf("正对照失败：Dwell = %v，要 3", d)
	}
	if n := idx2.Count([][2]int{{1, 1}}, math.Inf(-1), math.Inf(1)); n != 1 {
		t.Errorf("正对照失败：Count = %d，要 1", n)
	}
}

// TestArrivalsOnRealStage 在真关卡上查不变量。缺数据就跳过（缺件不是红）。
func TestArrivalsOnRealStage(t *testing.T) {
	//: ⚠ 引擎的 gamedata 路径是**相对 cwd** 拼的（`data/gamedata/_level_index.json`，
	//: 不走 `RIOS_DB`），而 `go test` 的 cwd 是**包目录** ⇒ 不处置的话这一条会被
	//: 静默 skip，而 skip 出来的绿等于没测。所以这里显式切到仓根，测完切回来。
	if _, err := os.Stat(filepath.Join("data", "gamedata", "_level_index.json")); err != nil {
		if wd, werr := os.Getwd(); werr == nil {
			root := filepath.Dir(wd)
			if _, e := os.Stat(filepath.Join(root, "data", "gamedata",
				"_level_index.json")); e == nil {
				if cerr := os.Chdir(root); cerr == nil {
					defer func() { _ = os.Chdir(wd) }()
				}
			}
		}
	}
	st, err := LoadStage("main_01-07")
	if err != nil {
		if missingData(err) {
			t.Skipf("缺关卡数据（环境问题，不是红）：%v", err)
		}
		t.Fatalf("取关卡失败：%v", err)
	}
	lib, err := LoadEnemyLibrary()
	if err != nil {
		if missingData(err) {
			t.Skipf("缺敌人库（环境问题，不是红）：%v", err)
		}
		t.Fatalf("取敌人库失败：%v", err)
	}
	arrivals, stats, err := EnemyArrivals(st, lib, 1.0, nil)
	if err != nil {
		t.Fatalf("算到达表失败：%v", err)
	}
	//: ★ 行使计数必须非零 —— 否则下面这些「不变量全过」是零信息量的绿
	if stats.Timeline == 0 || stats.Visits == 0 {
		t.Fatalf("行使计数为零（timeline=%d visits=%d）：这份数据没走到算法里",
			stats.Timeline, stats.Visits)
	}
	if len(arrivals) != stats.Timeline-stats.PlanMissing {
		t.Fatalf("到达条数 %d ≠ timeline %d − plan_missing %d",
			len(arrivals), stats.Timeline, stats.PlanMissing)
	}
	//: 每条 visit 的时长不许为负（`dwell` 的 max(0,…) 是给浮点噪声用的，不是给反序用的）
	total := 0
	for _, a := range arrivals {
		for _, v := range a.Visits {
			total++
			if v.Exit < v.Enter {
				t.Errorf("%s 在 %v 的离开时刻早于进入时刻：%v < %v",
					a.EnemyID, v.Cell, v.Exit, v.Enter)
			}
		}
	}
	if total != stats.Visits {
		t.Errorf("独立数出的 visit %d ≠ 计数器 %d", total, stats.Visits)
	}

	idx := NewArrivalIndex(arrivals)
	cells := idx.Cells()
	if len(cells) == 0 {
		t.Fatalf("有 visit 却一个格都没有")
	}
	//: 可加性：整片格子的 dwell 必须等于逐格之和（两条独立路径）
	all := idx.Dwell(cells, math.Inf(-1), math.Inf(1))
	sum := 0.0
	for _, c := range cells {
		sum += idx.CellDwell(c)
	}
	if !approx(all, sum) {
		t.Errorf("dwell 不可加：整片 %v ≠ 逐格之和 %v", all, sum)
	}
	//: count 与 visits 长度同源但算法不同，两边必须一致
	if n := idx.Count(cells, math.Inf(-1), math.Inf(1)); n != len(idx.Visits(cells)) {
		t.Errorf("count %d ≠ visits 条数 %d", n, len(idx.Visits(cells)))
	}
	//: 同一格内的 visit 必须按 enter 升序（`sort.SliceStable` 那条）
	for _, c := range cells {
		vs := idx.At(c)
		for i := 1; i < len(vs); i++ {
			if vs[i].Enter < vs[i-1].Enter {
				t.Errorf("格 %v 的 visit 没按 enter 排序：%v > %v", c, vs[i-1].Enter, vs[i].Enter)
			}
		}
	}
	//: 跨度与独立重算的一致
	lo, hi := idx.Span()
	minSpawn, maxArr := math.Inf(1), math.Inf(-1)
	for _, a := range arrivals {
		minSpawn = math.Min(minSpawn, a.Spawn)
		if !math.IsInf(a.ArrivesAt, 1) {
			maxArr = math.Max(maxArr, a.ArrivesAt)
		}
	}
	if !approx(lo, minSpawn) || (maxArr > math.Inf(-1) && !approx(hi, maxArr)) {
		t.Errorf("跨度 (%v,%v) ≠ 独立重算 (%v,%v)", lo, hi, minSpawn, maxArr)
	}
	//: ★ 零要有正对照：一个肯定没人经过的格 vs 最忙的那一格
	far := [2]int{999, 999}
	if _, ok := idx.First(far); ok {
		t.Errorf("格 %v 不该有人经过", far)
	}
	if d := idx.Dwell([][2]int{far}, math.Inf(-1), math.Inf(1)); d != 0 {
		t.Errorf("没人经过的格 dwell 应为 0，实得 %v", d)
	}
	if bx := idx.Busiest(1); len(bx) != 1 || bx[0].Dwell <= 0 {
		t.Errorf("正对照失败：最忙的格居然没有时长：%+v", bx)
	} else {
		t.Logf("关 %s：到达 %d 条 / visit %d 条 / 最忙的格 %v（%.3f 敌人·秒）",
			"main_01-07", len(arrivals), stats.Visits, bx[0].Cell, bx[0].Dwell)
	}
}

// TestArrivalsErrorsAreNamed 取数失败要**具名**，不许静默给一张空表。
func TestArrivalsErrorsAreNamed(t *testing.T) {
	if _, err := ArrivalsOf("", "", "", 0, nil); err == nil {
		t.Errorf("既没有 level 也没有 path 时必须报错")
	} else if !strings.Contains(err.Error(), "arrivals 少了 level") {
		t.Errorf("报错要说清缺什么，实得：%v", err)
	}
	if _, err := ArrivalsOf("__no_such_level__", "", "", 0, nil); err == nil {
		t.Errorf("关卡号不存在时必须报错")
	}
}

// missingData 判「这条错误是缺数据造成的」。
//
// ⚠ 只用它决定 **skip**，绝不用它把红说成绿：真出错（解析坏了、字段改名了）的
// 错误文本不含这些串，会走到 `t.Fatalf` 那一支。
func missingData(err error) bool {
	s := err.Error()
	for _, m := range []string{"cannot find the path", "cannot find the file",
		"no such file or directory", "系统找不到"} {
		if strings.Contains(s, m) {
			return true
		}
	}
	return false
}
