// snowspec.go：`mech_config["snow.field"]` 的**生产者**（积雪那一层）。
//
// 权威：`ak_tactic/simgo/spec.py::snow_spec` / `snow_mech_spec` ＋ `_ground_neighbours`。
//
// ★ **运行期那一层早就在 Go 里**（`mech/snow.go`：`SnowSpec` / `SnowField` /
// `SnowFieldSpec` / `SnowTick` / 冻结那一支），缺的只是这份规格的生产者 ——
// `SnowFieldSpec.Index` 的注释写着「由 Python 送」（`OWNER_INDEX_NOTE`）。
// 所以本文件只做一件事：把那份本来由 Python 造的几何与参数从**关卡 ＋ 计划**
// 自己造出来。
//
// ## 三处必须照抄、抄错都是「判决差一点」的地方
//
//  1. **天赋从「计划里那一手」读**（`d.talents`），不是从干员对象读。后者要到
//     部署那一刻才写上（`sim.py:3353`），而本规格在**跑之前**就要答案。
//     与 `_talent_dodge`、`_shield_of` 是**同一个坑**（权威在 `snow_spec` 的
//     注释里点过：闸门读运行期对象，就必须逐条问「这个对象是什么时候创建的」）。
//  2. **`ground` 必须确定性有序**：扩散上限是硬约束（`spread_cap`），
//     顺序一变雪就落在不同的格上。`operatorRange` 已经排好序，这里只做过滤。
//  3. **相邻关系是「四正 ＋ 四对角」的固定顺序**，不是字典序 ——
//     `(-1,0),(0,-1),(0,1),(1,0),(-1,-1),(-1,1),(1,-1),(1,1)`。
//     它与 Go 侧 `_spread_frontier` 的遍历顺序**必须一致**。
//
// ## 判据
//
// `check_buildspec_go.py` 逐路径比**整份**规格（这一支在其中，不另立特例）；
// 「雪有没有真的被造出来」由 `check_mechspec_go.py` 第五节现算并计数。
package main

import (
	"encoding/json"
	"fmt"
	"math"
)

// snowKeys 是「无垠的雪景」（圣聆初雪）的黑板指纹
// （`frontend/talent_finders.py:161` 的 `SNOW_KEYS` ＋ `:284 is_snow_talent`）。
//
// ⚠ `has(*keys)` 是「**全部**命中」（`talent.py:91-93` 的 `all`），不是任一命中——
// 与 `talentfinders.go` 文件头第 1 条坑同一条。`move_speed` **不在**指纹里，
// 但取数要用它（`slow_per_layer`），照抄权威那种「指纹一套、取数另一套」的分工。
var snowKeys = []string{"interval", "max_cast_cnt", "talent_magic_scale"}

// findSnow 复刻 `find_snow`（`talent_finders.py:246`）：**第一条**命中的。
func findSnow(ts []resolvedTalent) (resolvedTalent, bool) {
	for _, t := range ts {
		if bbHas(t.Blackboard, snowKeys...) {
			return t, true
		}
	}
	return resolvedTalent{}, false
}

// snowDirs 是四正 ＋ 四对角，**顺序照抄**权威的 `_ground_neighbours`
// （见文件头第 3 条）。写成常量而不是就地写字面量：改它等于改雪的落点。
var snowDirs = [8][2]int{
	{-1, 0}, {0, -1}, {0, 1}, {1, 0},
	{-1, -1}, {-1, 1}, {1, -1}, {1, 1},
}

// snowFieldOut 是 `SnowFieldSpec` 的**生产者侧**形状（键名与 `mech/snow.go` 的
// 消费者逐字相同——那是两侧的协议，改名等于改协议）。
type snowFieldOut struct {
	Owner        string   `json:"owner"`
	CharID       string   `json:"char_id"`
	Cell         [2]int   `json:"cell"`
	Direction    string   `json:"direction"`
	Interval     float64  `json:"interval"`
	MaxLayers    int      `json:"max_layers"`
	SlowPerLayer float64  `json:"slow_per_layer"`
	MagicScale   float64  `json:"magic_scale"`
	Ground       [][2]int `json:"ground"`
	//: 施放者在 `deploys` 里的下标（**同一个计数器**，见 `BuildDeployRows` 的排序）。
	Index int `json:"operator_index"`
}

// SnowOf 造 `mech_config["snow.field"]` 那一份；这一局没有雪就返回 `(nil, 0, nil)`。
//
// `rows` 必须是 `BuildDeployRows` 的产物（**已按落地时刻排序**）：下标 `${i}`
// 就是 `deploys[].index` 那个计数器，`mech/snow.go` 的 `Start` 会拿 `char_id`
// 与 `cell` 去核对它（错位就拒跑，不是静默算错）。
func SnowOf(st *Stage, rows []DeployRow, freeze bool) (json.RawMessage, int, error) {
	fields := make([]snowFieldOut, 0, len(rows))
	allCells := map[[2]int]bool{}
	for i, r := range rows {
		ts, err := charTalents(r.Entry.CharID, r.Entry.Elite, r.Entry.Level,
			r.Entry.Potential)
		if err != nil {
			return nil, 0, err
		}
		snow, ok := findSnow(ts)
		if !ok {
			continue
		}
		code, err := operatorRangeCode(r.Entry.CharID, r.Entry.Elite)
		if err != nil {
			return nil, 0, err
		}
		//: `current_range_id()` 在**跑之前**恒 None（技能未开），所以代号就是
		//: 干员自己那一档——与 `operators.go` 取规格时同一条口径。
		cells, _, _, err := operatorRange(code, r.Direction, r.Position)
		if err != nil {
			return nil, 0, err
		}
		ground := make([][2]int, 0, len(cells))
		for _, c := range cells { //: `operatorRange` 已排序 ⇒ 过滤后仍有序
			if st.Map.Walkable(c[0], c[1]) {
				ground = append(ground, c)
				allCells[c] = true
			}
		}
		bb := snow.Blackboard
		owner := r.Operator
		if owner == "" { //: 权威 `op.name or op.char_id`
			owner = r.Entry.CharID
		}
		fields = append(fields, snowFieldOut{
			Owner: owner, CharID: r.Entry.CharID,
			Cell: r.Position, Direction: r.Direction,
			//: 四个数逐字从黑板取，**默认值也照抄**（`interval` 10.0、
			//: `max_cast_cnt` 5、其余 0.0）——一个都不许自己发明。
			Interval:     bbValue(bb, "interval", 10.0),
			MaxLayers:    int(bbValue(bb, "max_cast_cnt", 5)),
			SlowPerLayer: math.Abs(bbValue(bb, "move_speed", 0.0)),
			MagicScale:   bbValue(bb, "talent_magic_scale", 0.0),
			Ground:       ground,
			Index:        i,
		})
	}
	if len(fields) == 0 {
		return nil, 0, nil
	}

	// ---- neighbours：键 `"x,y"`，值＝该格八邻里**可行走且还没有雪**的格 ----
	//: `seen` 先播全部雪格（权威同一个写法）：所以「已有的格」不进邻居表，
	//: 而**跨格去重**——同一格只会出现在**先遇到**它的那一格的邻居里。
	seen := make(map[[2]int]bool, len(allCells))
	for c := range allCells {
		seen[c] = true
	}
	ordered := make([][2]int, 0, len(allCells))
	for c := range allCells {
		ordered = append(ordered, c)
	}
	sortCells(ordered)
	nbrs := make(map[string][][2]int, len(ordered))
	for _, c := range ordered {
		list := [][2]int{}
		for _, d := range snowDirs {
			n := [2]int{c[0] + d[0], c[1] + d[1]}
			if seen[n] {
				continue
			}
			if !st.Map.Walkable(n[0], n[1]) {
				continue
			}
			seen[n] = true
			list = append(list, n)
		}
		nbrs[fmt.Sprintf("%d,%d", c[0], c[1])] = list
	}

	goals := st.Map.GoalCells()
	sortCells(goals) //: 权威是 `sorted({...})`；这一份要与它逐位相同
	out := struct {
		Freeze     bool                `json:"freeze"`
		Fields     []snowFieldOut      `json:"fields"`
		Neighbours map[string][][2]int `json:"neighbours"`
		GoalCells  [][2]int            `json:"goal_cells"`
	}{Freeze: freeze, Fields: fields, Neighbours: nbrs, GoalCells: goals}
	blob, err := json.Marshal(out)
	if err != nil {
		return nil, 0, err
	}
	return blob, len(fields), nil
}
