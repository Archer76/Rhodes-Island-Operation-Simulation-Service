package main

import (
	"os"
	"path/filepath"
	"testing"
)

// # 可部署格（`spots.go`）的 Go 侧判据
//
// 三条要点，每条都对着一次真实事故或一处易错口径：
//
//   - **`ALL` 必须两种都算**：只认 MELEE / RANGED 时，`act31side_ex05` 与
//     `act31side_sub-1-2` 整图零可部署格，症状是「无论选什么都是 0 条结果」；
//   - **行主序**（y 在外、x 在内）：与 Python 的
//     `for y in range(height) for x in range(width)` 逐字对齐，顺序变了
//     `per_op` 截断的产物就换一批；
//   - **第五种取值不许静默消失**：认不得的 `buildable` 要落进 `unknown` 计数。

// TestDeployableHandComputed 手算：四种 buildable 各一格。
func TestDeployableHandComputed(t *testing.T) {
	m := StageMap{Width: 4, Height: 1, Tiles: [][]Tile{{
		{Key: "tile_floor", Buildable: "NONE"},
		{Key: "tile_floor", Buildable: "MELEE"},
		{Key: "tile_high", Buildable: "RANGED"},
		{Key: "tile_high", Buildable: "ALL"},
	}}}
	//: MELEE 与 ALL ⇒ 地面；(1,0) 与 (3,0)
	if got := m.MeleeSpots(); !sameCells(got, [][2]int{{1, 0}, {3, 0}}) {
		t.Errorf("地面格 = %v，手算 [[1 0] [3 0]]", got)
	}
	//: RANGED 与 ALL ⇒ 高台；(2,0) 与 (3,0)
	if got := m.RangedSpots(); !sameCells(got, [][2]int{{2, 0}, {3, 0}}) {
		t.Errorf("高台格 = %v，手算 [[2 0] [3 0]]", got)
	}
	c := CountBuildable(m)
	if c.None != 1 || c.Melee != 1 || c.Ranged != 1 || c.All != 1 || c.Unknown != 0 {
		t.Errorf("四种取值计数 = %+v，手算各 1、unknown 0", c)
	}
}

// TestSpotsAreRowMajor 钉住**行主序**。
//
// 造两格让它与「列主序」分得开：(1,0) 与 (0,1)。行主序给 [(1,0) (0,1)]，
// 列主序（x 在外）会给 [(0,1) (1,0)]。
func TestSpotsAreRowMajor(t *testing.T) {
	m := StageMap{Width: 2, Height: 2, Tiles: [][]Tile{
		{{Buildable: "NONE"}, {Buildable: "MELEE"}},
		{{Buildable: "MELEE"}, {Buildable: "NONE"}},
	}}
	if got := m.MeleeSpots(); !sameCells(got, [][2]int{{1, 0}, {0, 1}}) {
		t.Fatalf("行主序应为 [(1,0) (0,1)]，实得 %v（若是 [(0,1) (1,0)] 就是列主序，判据会漂）", got)
	}
	//: 负对照：`SortedSpots` 是**另一套顺序**（x 优先），两者不许混为一谈
	if got := SortedSpots(m.MeleeSpots()); !sameCells(got, [][2]int{{0, 1}, {1, 0}}) {
		t.Errorf("字典序应为 [(0,1) (1,0)]，实得 %v", got)
	}
}

// TestAllOnlyMapIsNotEmpty 是那次事故的**回归判据**。
//
// 一张只有 `ALL` 的地图，必须给出满格的可部署格 —— 只认 MELEE/RANGED 的实现
// 会在这里给空表，而那正是「无论选什么都是 0 条结果」的病根。
func TestAllOnlyMapIsNotEmpty(t *testing.T) {
	m := StageMap{Width: 3, Height: 2, Tiles: [][]Tile{
		{{Buildable: "ALL"}, {Buildable: "ALL"}, {Buildable: "ALL"}},
		{{Buildable: "ALL"}, {Buildable: "ALL"}, {Buildable: "ALL"}},
	}}
	melee, ranged := m.MeleeSpots(), m.RangedSpots()
	if len(melee) != 6 || len(ranged) != 6 {
		t.Fatalf("全 ALL 的地图两种可部署格都该是 6 格，实得 地面 %d / 高台 %d",
			len(melee), len(ranged))
	}
	//: 负对照：全 NONE 的地图必须是**空表**（不是 nil，也不是"有一格"）
	none := StageMap{Width: 2, Height: 1, Tiles: [][]Tile{{
		{Buildable: "NONE"}, {Buildable: "NONE"}}}}
	if got := none.MeleeSpots(); len(got) != 0 || got == nil {
		t.Errorf("全 NONE 的地图要给空表（非 nil），实得 %v", got)
	}
	//: 负对照：第五种取值必须落进 unknown，不许静默消失
	weird := StageMap{Width: 1, Height: 1, Tiles: [][]Tile{{{Buildable: "SOMETHING_NEW"}}}}
	if c := CountBuildable(weird); c.Unknown != 1 {
		t.Errorf("认不得的取值应落进 unknown，实得 %+v", c)
	}
}

// TestSpotsOnRealStage 真关卡上查恒等式：地面格数 = MELEE 数 + ALL 数（反过来也一样）。
func TestSpotsOnRealStage(t *testing.T) {
	chdirRepoRootForData(t)
	st, err := LoadStage("main_01-07")
	if err != nil {
		if missingData(err) {
			t.Skipf("缺关卡数据（环境问题，不是红）：%v", err)
		}
		t.Fatalf("取关卡失败：%v", err)
	}
	c := CountBuildable(st.Map)
	melee := st.Map.MeleeSpots()
	ranged := st.Map.RangedSpots()
	if len(melee) == 0 || len(ranged) == 0 {
		t.Fatalf("这一关两种可部署格都不该是空的：地面 %d / 高台 %d", len(melee), len(ranged))
	}
	if len(melee) != c.Melee+c.All {
		t.Errorf("地面格 %d ≠ MELEE %d ＋ ALL %d", len(melee), c.Melee, c.All)
	}
	if len(ranged) != c.Ranged+c.All {
		t.Errorf("高台格 %d ≠ RANGED %d ＋ ALL %d", len(ranged), c.Ranged, c.All)
	}
	//: 行使计数不许为零（否则上面那些恒等式是零信息量的绿）
	if c.Melee+c.Ranged+c.All == 0 {
		t.Fatalf("一格可部署的都没有：%+v", c)
	}
	t.Logf("关 main_01-07：地面 %d 格 / 高台 %d 格（NONE %d / MELEE %d / RANGED %d / ALL %d）",
		len(melee), len(ranged), c.None, c.Melee, c.Ranged, c.All)
}

// chdirRepoRootForData 把 cwd 切到仓根（引擎的 gamedata 路径是相对 cwd 拼的）。
//
// ⚠ 不切的话，依赖关卡数据的根包测试会在 `go test`（cwd = 包目录）下被**静默 skip**
// —— 那是零行使的假绿。缺数据时保持原样，让调用方按 skip 处理。
func chdirRepoRootForData(t *testing.T) {
	t.Helper()
	if _, err := os.Stat(filepath.Join("data", "gamedata", "_level_index.json")); err == nil {
		return
	}
	wd, err := os.Getwd()
	if err != nil {
		return
	}
	root := filepath.Dir(wd)
	if _, err := os.Stat(filepath.Join(root, "data", "gamedata", "_level_index.json")); err != nil {
		return
	}
	if err := os.Chdir(root); err != nil {
		return
	}
	t.Cleanup(func() { _ = os.Chdir(wd) })
}

func sameCells(a, b [][2]int) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
