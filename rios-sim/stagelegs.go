package main

import (
	"fmt"
	"math"
	"strings"
)

// stagelegs.go：路线分段计划（`Route.legs`，丙阶段四·第二十七批）。
//
// 权威 `gamedata/stage.py:415-481`。它是**路线生产侧**的另一半
// （一半是 `stagepath.go` 的地面寻路），与寻路合起来卡着 `spawns` 与
// `unsupported` 两个键。搬它之前 Go **只有消费侧**（`sim.go` 沿 `LegSpec`
// 走，而 `LegSpec` 是从规格里收来的），生产侧写在这里。
//
// ## 三种段落
//
//   - `walk`   沿 `points` 折线走，`length` 是折线总长（格）；
//   - `wait`   原地待命 `seconds` 秒（`WAIT*`）；
//   - `vanish` **离场** `seconds` 秒（`DISAPPEAR` → 等待 → `APPEAR_AT_POS`），
//     这段时间敌人不在地图上。
//
// ## 三处最容易写错的
//
//  1. **`is_wait` 是 `startswith("WAIT")`，不是 `== "WAIT_FOR_SECONDS"`**
//     （`stage.py:288`）。写成相等会漏判别的 `WAIT*`，那条 checkpoint
//     既不 flush 也不记秒数。`is_move` / `is_appear` 才是相等判定。
//  2. **`flush()` 里相邻两段之间要丢掉重复顶点**（`pts.pop()`）——
//     漏了它折线会多一个重复点：长度不变、`points` 不同。
//     另外**同一条 `flush` 内接续才丢**：两次 `flush` 之间是两个独立的 `walk` 段。
//  3. **`WALK` 沿可行走地块寻路、`FLY` 是直线**（`stage.py:426-427`）：
//     `use_map` 只在非 FLY 且 `a != b` 时才寻路；`a == b` 两个分支都给
//     `[a, b]`（一个**重复点**，这正是下一段 `pop()` 要清掉的东西）。
//
// ## ★ 长度：不许用朴素累加（1 ulp 的根因，2026-09-21 第 29 轮查清）
//
// 上一版 Go 实现 55 关里 54 关全过，只在 `act31side_05` 的 5 条路线 `length`
// 上失配：`Go=24.242640687119287` vs 原版 `24.242640687119284`。
// 公式与点列当时都已排除，其实**两条都没错**，错的是**求和算法**：
//
//   - 权威 `_polyline_length` 用的是内建 `sum(...)`（`stage.py:357-358`）；
//   - **CPython 3.12 起，`sum()` 对浮点走 Neumaier 补偿求和**
//     （`Objects/bltinmodule.c` 的 `builtin_sum`），得到的是**正确舍入**的和；
//   - Go 那边的 `total += ...` 是朴素左到右累加，比正确舍入值高 1 ulp。
//
// 实测（`act31side_05` 路线 1 第 8 段，23 步、20 直行 ＋ 3 斜行）：
// `sum()=…284`、`math.fsum=…284`、朴素累加 `=…287`。**「逐项值相同 ＋ 公式相同
// ＋ 累加顺序相同 ⇒ 和必须相同」这条推理是错的**——它默认了累加是朴素加法。
//
// ⇒ `polylineLength` 必须走 `sumLikePython`；`gridDist` 必须复刻
// `math.dist` 的**平方和开方**（不是缩放式，见 `gridDist` 自己的注释——
// 缩放式是本条路上**第二个**、与求和无关的 1 ulp）。

// RouteLeg 是路线的一段。
//
// ★ 四个字段**都**无条件序列化（不用 `omitempty`）：判据要比 `length` 的末位，
// 而 0 秒的 `wait`、空 `points` 的 `vanish` 都是**有意义的读数**，
// 省略会让「没有这一段」与「这一段是 0」在回读时长得一样。
//
// 注意这里**不做 `to_dict` 的 `round(length, 3)`**（`stage.py:345`）：
// 那是展示路径；真正送进规格的 `_legs_spec`（`simgo/spec.py:851`）
// 送的是 `float(leg.length)` 原值。
type RouteLeg struct {
	Kind    string   `json:"kind"`
	Points  [][2]int `json:"points"`
	Length  float64  `json:"length"`
	Seconds float64  `json:"seconds"`
}

// sumLikePython 复刻 CPython 3.12+ 内建 `sum()` 对浮点序列的求和：
// Neumaier 补偿求和。逐句对 `builtin_sum` 的浮点累加段。
//
// ⚠ 这不是「更准的写法」这种风格选择，而是**与权威逐位对齐**的要求：
// 换成朴素累加，`act31side_05` 就会有 1 ulp 的失配（见文件头）。
func sumLikePython(xs []float64) float64 {
	s, c := 0.0, 0.0
	for _, x := range xs {
		t := s + x
		if math.Abs(s) >= math.Abs(x) {
			c += (s - t) + x
		} else {
			c += (x - t) + s
		}
		s = t
	}
	return s + c
}

// gridDist 复刻 CPython 的 `math.dist(a, b)`（两元素序列）。
//
// ⚠ 它是**平方和开方**，不是缩放式。本项目两处注释都曾把 `math.dist`
// 写成「先把差分除以最大值、平方求和、再乘回去」的缩放式——**那是错的**，
// 而错法很隐蔽：单位步（`dx, dy ∈ {0,1}`）下两者逐位相同，看不出来。
// 实测（dx, dy ∈ [0,80)，6400 个格点）：
//
//	sqrt(dx² + dy²)                          → 与 math.dist **0 处不符**
//	max·sqrt((dx/max)² + (dy/max)²)          → **2062 处不符**（各差 1 ulp）
//
// 缩放那条路 CPython 只在平方会溢出时（`max` 到 1e200 那种）才走；
// 网格坐标离它无穷远。第一版 Go 照缩放式写，于是 `act31side_09` 的
// 5 条路线又差 1 ulp——**同一条判据上第二个 1 ulp，来源与第一个无关**。
func gridDist(a, b [2]int) float64 {
	dx := float64(b[0] - a[0])
	dy := float64(b[1] - a[1])
	return math.Sqrt(dx*dx + dy*dy)
}

// polylineLength 复刻 `_polyline_length`：相邻点距离之和（走 `sum()` 的语义）。
func polylineLength(pts [][2]int) float64 {
	ds := make([]float64, 0, len(pts))
	for i := 1; i < len(pts); i++ {
		ds = append(ds, gridDist(pts[i-1], pts[i]))
	}
	return sumLikePython(ds)
}

// LegsOf 复刻 `Route.legs`。`st` 提供寻路用的地图（权威那边是 `walk_map`）。
//
// 只有 `MOVE` 与 `APPEAR_AT_POS` 带真坐标；`WAIT*` 与 `DISAPPEAR` 的 position
// 是 `(0,0)` 占位，当坐标读会画出穿过地图原点的假路径。
//
// ⚠ `APPEAR_AT_POS` **只在 `DISAPPEAR` 那一段里被消费**：单独出现时权威
// 既不 append 也不 flush（`stage.py:448-477` 的三个分支都不认它），这里照抄。
func (st *Stage) LegsOf(r Route) []RouteLeg {
	fly := strings.ToUpper(r.Mode) == "FLY" //: `(self.mode or "WALK").upper() == "FLY"`
	useMap := !fly
	out := []RouteLeg{}
	walk := [][2]int{r.Start}

	flush := func() {
		if len(walk) < 2 {
			return
		}
		pts := [][2]int{}
		for i := 0; i+1 < len(walk); i++ {
			a, b := walk[i], walk[i+1]
			if len(pts) > 0 {
				pts = pts[:len(pts)-1] //: 与上一段接续，别重复顶点
			}
			if useMap && a != b {
				pts = append(pts, st.Map.GroundPath(a, b, true)...)
			} else {
				pts = append(pts, a, b)
			}
		}
		if len(pts) >= 2 {
			out = append(out, RouteLeg{
				Kind: "walk", Points: pts, Length: polylineLength(pts),
			})
		}
	}

	cps := r.Checkpoints
	for i := 0; i < len(cps); {
		c := cps[i]
		switch {
		case c.Type == "MOVE":
			walk = append(walk, *c.Position)
		case c.Type == "DISAPPEAR":
			flush()
			//: 消失之后、出现之前的等待都算离场时长。
			gone := 0.0
			var appear *[2]int
			j := i + 1
			for j < len(cps) {
				cj := cps[j]
				if cj.Type == "APPEAR_AT_POS" {
					appear = cj.Position
					j++
					break
				}
				if strings.HasPrefix(cj.Type, "WAIT") {
					gone += cj.Wait
				}
				j++
			}
			if gone > 0 {
				out = append(out, RouteLeg{
					Kind: "vanish", Points: [][2]int{}, Seconds: gone,
				})
			}
			if appear != nil {
				walk = [][2]int{*appear}
			} else {
				//: 找不到落点就留在原地（权威：`walk[-1]`）。
				walk = [][2]int{walk[len(walk)-1]}
			}
			i = j
			continue
		case strings.HasPrefix(c.Type, "WAIT"):
			flush()
			walk = [][2]int{walk[len(walk)-1]}
			if c.Wait != 0 {
				out = append(out, RouteLeg{
					Kind: "wait", Points: [][2]int{}, Seconds: c.Wait,
				})
			}
		}
		i++
	}
	walk = append(walk, r.End)
	flush()
	return out
}

// RouteLegsOf 对一关批量求分段计划（`legs` 命令的入口）。
//
// `idx` 是路线号（`Route.Index`，即 `routes` 数组下标）。越界**具名报错**，
// 不静默跳过——跳过的症状是「少了那一条」，而少了的那条不会有任何判据报警。
func RouteLegsOf(level string, idx []int) ([][]RouteLeg, error) {
	st, err := LoadStage(level)
	if err != nil {
		return nil, err
	}
	out := make([][]RouteLeg, 0, len(idx))
	for _, k := range idx {
		if k < 0 || k >= len(st.Routes) {
			return nil, fmt.Errorf("路线号 %d 越界（%s 共 %d 条路线）",
				k, st.LevelID, len(st.Routes))
		}
		out = append(out, st.LegsOf(st.Routes[k]))
	}
	return out, nil
}
