package main

import "strings"

// stagepath.go：地面寻路（丙阶段四·第二十六批）。
//
// 权威 `gamedata/stage.py:154-226`。它是**路线生产侧**的一半，卡着
// `spawns` 与 `unsupported` 两个键。
//
// 三处逐字对齐：`"ALL" in passable` 是**子串**判定且 `tile_hole` 不可走；
// **不许斜穿墙角**；★ **同距离时按 (x, y) 字典序决胜**——原版的堆是
// `(距离, 格)` 元组，Python 的元组比较就是这么排的。只比距离会挑到另一条
// **等长但不同**的折线：到达时刻一样、`points` 对不上。
//
// 弹出序用线性扫描复刻（不用 `container/heap`）：每次取**全局最小**的
// `(d, x, y)`，含已过期条目——过期条目弹出时按 `d > dist` 跳过，
// 与 Python 的 heapq 行为一致。

var impassableKeys = map[string]bool{"tile_hole": true}

// Walkable 复刻 `StageMap.walkable`。
func (m StageMap) Walkable(x, y int) bool {
	if x < 0 || y < 0 || y >= len(m.Tiles) || x >= len(m.Tiles[y]) {
		return false
	}
	t := m.Tiles[y][x]
	return strings.Contains(t.Passable, "ALL") && !impassableKeys[t.Key]
}

// GroundPath 复刻 `StageMap.ground_path`。
func (m StageMap) GroundPath(start, end [2]int, diagonal bool) [][2]int {
	if start == end {
		return [][2]int{start}
	}
	if !m.Walkable(start[0], start[1]) || !m.Walkable(end[0], end[1]) {
		return [][2]int{start, end} // 端点不可走 → 退回直线
	}
	steps := [][2]int{{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
	if diagonal {
		steps = append(steps, [2]int{1, 1}, [2]int{1, -1},
			[2]int{-1, 1}, [2]int{-1, -1})
	}
	const diag = 1.4142135623730951

	dist := map[[2]int]float64{start: 0.0}
	prev := map[[2]int][2]int{}
	type node struct {
		d    float64
		x, y int
	}
	pending := []node{{0.0, start[0], start[1]}}
	for len(pending) > 0 {
		//: 取全局最小的 (d, x, y)——复刻 Python 元组堆的弹出序。
		best := 0
		for i := 1; i < len(pending); i++ {
			a, b := pending[i], pending[best]
			if a.d < b.d || (a.d == b.d && (a.x < b.x ||
				(a.x == b.x && a.y < b.y))) {
				best = i
			}
		}
		cur := pending[best]
		pending = append(pending[:best], pending[best+1:]...)
		cell := [2]int{cur.x, cur.y}
		if cell == end {
			break
		}
		if cur.d > dist[cell] {
			continue
		}
		for _, s := range steps {
			nxt := [2]int{cur.x + s[0], cur.y + s[1]}
			if !m.Walkable(nxt[0], nxt[1]) {
				continue
			}
			if s[0] != 0 && s[1] != 0 &&
				!(m.Walkable(cur.x+s[0], cur.y) && m.Walkable(cur.x, cur.y+s[1])) {
				continue // 不许斜穿墙角
			}
			nd := cur.d + 1.0
			if s[0] != 0 && s[1] != 0 {
				nd = cur.d + diag
			}
			if old, ok := dist[nxt]; !ok || nd < old {
				dist[nxt] = nd
				prev[nxt] = cell
				pending = append(pending, node{nd, nxt[0], nxt[1]})
			}
		}
	}
	if _, ok := dist[end]; !ok {
		return [][2]int{start, end} // 不连通 → 退回直线
	}
	out := [][2]int{end}
	for out[len(out)-1] != start {
		out = append(out, prev[out[len(out)-1]])
	}
	for i, j := 0, len(out)-1; i < j; i, j = i+1, j-1 {
		out[i], out[j] = out[j], out[i]
	}
	return out
}

// PathQuery 是一次寻路请求。
type PathQuery struct {
	Start    [2]int `json:"start"`
	End      [2]int `json:"end"`
	Diagonal *bool  `json:"diagonal"`
}

// GroundPaths 对一关批量寻路。
func GroundPaths(level string, qs []PathQuery) ([][][2]int, error) {
	st, err := LoadStage(level)
	if err != nil {
		return nil, err
	}
	out := make([][][2]int, 0, len(qs))
	for _, q := range qs {
		d := true
		if q.Diagonal != nil {
			d = *q.Diagonal
		}
		out = append(out, st.Map.GroundPath(q.Start, q.End, d))
	}
	return out, nil
}
