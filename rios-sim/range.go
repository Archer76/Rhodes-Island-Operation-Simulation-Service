package main

// range.go：**攻击范围**（丙阶段三·第十一批）。
//
// 两段拼起来：
//
//  1. `excel/range_table.json[code].grids[]` 给的是**朝右约定**下的相对格
//     （`ak_tactic/gamedata/range.py:105-123`，那里的模块注释写明它与
//     `battle.range.rotate_cells` 是配套的）；
//  2. 按朝向旋转（`battle/range.py:57-86`）再平移到落点（`footprint`，`:89-92`）。
//
// ## 旋转公式与「数学课上那套」差一个符号
//
// 屏幕坐标系（MAA 标准）是 x 向右、**y 向下**，所以：
//
//	Right  (x, y)      Up   (y, -x)      Left (-x, -y)      Down (-y, x)
//
// 照数学习惯写成 `Up → (-y, x)` 会让整个范围上下翻，症状是「站对了格子却打不到人」。
//
// ## 本轮未接（具名）
//
// `normalize_direction` 的**别名表**（`battle/range.py:30-43`）没读全——
// 这里只认 Right/Left/Up/Down 四个正名，**其余一律大声失败**，
// 不默认朝右（`geometry.facing` 的兜底是另一条路，混用会让「认不出」变成「朝右」）。

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

// Cell 是整数格坐标。
type Cell [2]int

var rangeTableCache map[string][]Cell

// LoadRangeTable 复刻 `RangeTable._load`（`range.py:105-123`）。
//
// ⚠ 只取**同时有 col 与 row** 的项；缺一个的整项丢掉（与 Python 的
// `if "col" in g and "row" in g` 同口径）——那是数据里有残缺项时的判据。
func LoadRangeTable() (map[string][]Cell, error) {
	if rangeTableCache != nil {
		return rangeTableCache, nil
	}
	p := filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel",
		"range_table.json")
	blob, err := os.ReadFile(p)
	if err != nil {
		return nil, fmt.Errorf("读 range_table 失败（%s）：%w", p, err)
	}
	var raw map[string]struct {
		Grids []struct {
			Col *int `json:"col"`
			Row *int `json:"row"`
		} `json:"grids"`
	}
	if err := json.Unmarshal(blob, &raw); err != nil {
		return nil, fmt.Errorf("range_table 不是合法 JSON（%s）：%w", p, err)
	}
	if len(raw) == 0 {
		return nil, fmt.Errorf("range_table 是空的（%s）", p)
	}
	out := make(map[string][]Cell, len(raw))
	for code, entry := range raw {
		cells := make([]Cell, 0, len(entry.Grids))
		for _, g := range entry.Grids {
			if g.Col == nil || g.Row == nil {
				continue
			}
			cells = append(cells, Cell{*g.Col, *g.Row})
		}
		out[code] = cells
	}
	rangeTableCache = out
	return out, nil
}

// RangeCodes 返回全部范围代号（已排序，供判据遍历）。
func RangeCodes() ([]string, error) {
	tbl, err := LoadRangeTable()
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(tbl))
	for c := range tbl {
		out = append(out, c)
	}
	sort.Strings(out)
	return out, nil
}

// RotateCells 复刻 `rotate_cells`（`battle/range.py:57-86`）。
//
// ★ 只认四个正名；其余**大声失败**——`normalize_direction` 的别名表本轮未读全，
// 静默兜底成「朝右」会把「认不出」伪装成一个看起来正常的结果。
func RotateCells(cells []Cell, direction string) ([]Cell, error) {
	switch direction {
	case "Right", "Up", "Left", "Down":
	default:
		return nil, fmt.Errorf("认不出的朝向：%q（本轮只认 Right/Left/Up/Down 四个正名）",
			direction)
	}
	out := make([]Cell, 0, len(cells))
	for _, c := range cells {
		x, y := c[0], c[1]
		switch direction {
		case "Right":
			out = append(out, Cell{x, y})
		case "Up":
			out = append(out, Cell{y, -x})
		case "Left":
			out = append(out, Cell{-x, -y})
		case "Down":
			out = append(out, Cell{-y, x})
		}
	}
	return out, nil
}

// Footprint 复刻 `footprint`（`battle/range.py:89-92`）：
// 范围的**绝对格**集合——相对格旋转后平移到落点。
func Footprint(cells []Cell, direction string, ox, oy int) ([]Cell, error) {
	rot, err := RotateCells(cells, direction)
	if err != nil {
		return nil, err
	}
	out := make([]Cell, 0, len(rot))
	for _, c := range rot {
		out = append(out, Cell{ox + c[0], oy + c[1]})
	}
	return out, nil
}

// RangeQuery 是一次范围查询（判据用）。
type RangeQuery struct {
	Code      string `json:"code"`
	Direction string `json:"direction"`
	X         int    `json:"x"`
	Y         int    `json:"y"`
}

// RangeResult 是相对格 ＋ 绝对格两栏。
//
// ⚠ 两栏都要给：只比绝对格会让「旋转公式错」与「表读错」两种因
// 长得一样；只比相对格则盖不到平移。
type RangeResult struct {
	Code      string `json:"code"`
	Direction string `json:"direction"`
	Cells     []Cell `json:"cells"`
	Footprint []Cell `json:"footprint"`
	Error     string `json:"error,omitempty"`
}

// RangeFor 处理一批范围查询。
func RangeFor(queries []RangeQuery) ([]RangeResult, error) {
	tbl, err := LoadRangeTable()
	if err != nil {
		return nil, err
	}
	out := make([]RangeResult, 0, len(queries))
	for _, q := range queries {
		cells, ok := tbl[q.Code]
		if !ok {
			return nil, fmt.Errorf("range_table.json 里没有范围 %q", q.Code)
		}
		fp, err := Footprint(cells, q.Direction, q.X, q.Y)
		if err != nil {
			return nil, err
		}
		out = append(out, RangeResult{Code: q.Code, Direction: q.Direction,
			Cells: append([]Cell{}, cells...), Footprint: fp})
	}
	return out, nil
}
