package main

import (
	"fmt"
	"sort"
)

// # 可部署格：`ak_tactic/gamedata/stage.py:84-150` 的 Go 侧对应物
//
// 这一层是搜索的**第一道筛子**：候选落位只可能出现在可部署格上，而一个 33×11 的
// 关卡里地面格 363 个，可部署的往往只有几十个。没有它，`candidates_for` 就在整张
// 地图上试朝向。
//
// ## `ALL` 是真实取值，不是笔误
//
// 关卡 `mapData.tiles[].buildableType` 一共**四个**取值，全量扫过 `data/gamedata`
// 的 34 个怀黍离关卡文件：NONE 1779 / MELEE 788 / RANGED 359 / **ALL 75**。
// `ALL` = 地面与高台都能放。Python 那边原先只认 MELEE / RANGED，于是 `ALL` 落进
// 「两种都不能」：`act31side_ex05`（33 格）与 `act31side_sub-1-2`（42 格）**整图一个
// 可部署格都没有**，几何剪枝自然一个候选都不剩 —— 症状是「无论选什么都是 0 条结果」。
// Go 这边一次就把四个取值认全，并把 `all` 计入行使计数（它是最容易被漏的那一类）。

// DeployableMelee 是「能站地面干员」（`stage.py:84`：`MELEE` 或 `ALL`）。
func (t Tile) DeployableMelee() bool {
	return t.Buildable == "MELEE" || t.Buildable == "ALL"
}

// DeployableRanged 是「能站高台干员」（`stage.py:89`：`RANGED` 或 `ALL`）。
func (t Tile) DeployableRanged() bool {
	return t.Buildable == "RANGED" || t.Buildable == "ALL"
}

// MeleeSpots 复刻 `stage.py:141`：可放地面干员的格子。
//
// ⚠ **行主序**（y 在外、x 在内）—— 与 Python 的
// `for y in range(height) for x in range(width)` 逐字对齐。顺序不是小事：
// 候选枚举按这个顺序推进，`per_op` 截断与平局取谁都跟着它走。
func (m StageMap) MeleeSpots() [][2]int { return m.spots(Tile.DeployableMelee) }

// RangedSpots 复刻 `stage.py:147`：可放高台干员的格子（同样是行主序）。
func (m StageMap) RangedSpots() [][2]int { return m.spots(Tile.DeployableRanged) }

func (m StageMap) spots(want func(Tile) bool) [][2]int {
	out := [][2]int{}
	for y := 0; y < m.Height; y++ {
		if y >= len(m.Tiles) {
			break
		}
		for x := 0; x < m.Width; x++ {
			if x >= len(m.Tiles[y]) {
				break
			}
			if want(m.Tiles[y][x]) {
				out = append(out, [2]int{x, y})
			}
		}
	}
	return out
}

// SpotsCounts 是**行使计数**：四种 `buildable` 各多少格。
//
// 单独把 `all` 列出来，是因为**它就是那次事故的那一类**（见文件头）：
// 一个「可部署格 0」的关卡，如果只看 melee／ranged 两个数，会看不出
// 是「地图真的没地方站」还是「有一类取值没被认」。
type SpotsCounts struct {
	None        int `json:"none"`
	Melee       int `json:"melee"`
	Ranged      int `json:"ranged"`
	All         int `json:"all"`
	Unknown     int `json:"unknown"` //: 出现第五种取值 —— 那说明上游数据变了，要查
	MeleeSpots  int `json:"melee_spots"`
	RangedSpots int `json:"ranged_spots"`
}

// SpotsOut 是 `spots` 命令的应答。
type SpotsOut struct {
	Melee   [][2]int       `json:"melee"`
	Ranged  [][2]int       `json:"ranged"`
	Covered SpotsCounts    `json:"covered"`
	Params  map[string]any `json:"params"`
}

// SpotsQuery 是 `spots` 命令的 spec。
type SpotsQuery struct {
	Difficulty string `json:"difficulty"`
}

// SpotsOf 是命令入口：与 `routeplans`／`spawns`／`arrivals` 同口径
// （关卡走 level 或合成关卡的 path）。
func SpotsOf(level, path, difficulty string) (SpotsOut, error) {
	out := SpotsOut{Melee: [][2]int{}, Ranged: [][2]int{},
		Params: map[string]any{"level": level, "path": path,
			"difficulty": difficulty}}
	var st *Stage
	var err error
	if path != "" {
		st, err = loadStageFromFile(path, difficulty)
	} else {
		if level == "" {
			return out, fmt.Errorf("spots 少了 level（关卡号或 levelId）或 path（合成关卡 JSON）")
		}
		st, err = LoadStage(level)
	}
	if err != nil {
		return out, err
	}
	out.Melee = st.Map.MeleeSpots()
	out.Ranged = st.Map.RangedSpots()
	out.Covered = CountBuildable(st.Map)
	out.Covered.MeleeSpots = len(out.Melee)
	out.Covered.RangedSpots = len(out.Ranged)
	return out, nil
}

// CountBuildable 数四种 `buildable` 取值各多少格。
func CountBuildable(m StageMap) SpotsCounts {
	var c SpotsCounts
	for y := 0; y < m.Height; y++ {
		if y >= len(m.Tiles) {
			break
		}
		for x := 0; x < m.Width; x++ {
			if x >= len(m.Tiles[y]) {
				break
			}
			switch m.Tiles[y][x].Buildable {
			case "NONE":
				c.None++
			case "MELEE":
				c.Melee++
			case "RANGED":
				c.Ranged++
			case "ALL":
				c.All++
			default:
				c.Unknown++
			}
		}
	}
	return c
}

// SortedSpots 给界面用：把格子按 (x, y) 字典序排一份。
//
// ⚠ 与 `MeleeSpots` 的顺序**不是一回事**：那一个是行主序（y 在外），
// 这一个按 x 优先。搜索要行主序，展示往往要字典序 —— 两者混用会让
// `per_op` 截断的产物悄悄换一批，所以两个名字分开。
func SortedSpots(cells [][2]int) [][2]int {
	out := append([][2]int(nil), cells...)
	sort.Slice(out, func(i, j int) bool {
		if out[i][0] != out[j][0] {
			return out[i][0] < out[j][0]
		}
		return out[i][1] < out[j][1]
	})
	return out
}
