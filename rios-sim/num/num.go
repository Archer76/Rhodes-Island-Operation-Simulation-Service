// Package num 收「与数值精度有关的、必须自己写的」那几个函数。
//
// 目前只有 `Hypot` 一个。它存在的理由不是风格，是**证据**：Go 标准库的
// `math.Hypot` 不满足正确舍入（2026-09-27 实测 2.88% 的随机输入给出非正确舍入
// 值），而它在本仓被用来算腿长、算距离、算夹角 —— 那 1 ulp 会一路传成
// 到达表时刻、`dwell`、候选排序上的差。详见 `Hypot` 的注释。
package num

import "math"

// Hypot 是**正确舍入**的 `sqrt(x*x + y*y)`。
//
// # 为什么要自己写一个
//
// 2026-09-27 实测（博士口径：**判准是「正确舍入」，不是「与 CPython 一致」**）：
// 用 `decimal` 80 位算 `sqrt(x²+y²)` 的真值、再正确舍入到 double 当唯一正确答案，
// 比 25008 例随机输入 ——
//
//   - **CPython 的 `math.hypot`：0 例不对**（正确舍入）；
//   - **Go 的 `math.Hypot`：721 例不对（2.88%）**。
//
// 代价不止那一格：`arrivals.go` 的 visit 时刻表由它算腿长，于是 `visit.enter` /
// `visit.exit` 各差 1 ulp（实测 `main_15-13` 的 `寒灾回响 (9,0)`；603 关的到达表里
// enter 170 处 / exit 168 处），再往上传成 `dwell` / `value` 的差，最后落在候选
// 排序上 —— 而 `per_op` 的截断就切在那个序上。⇒ 这是**源头**那 1 ulp。
//
// Go 的 `math.Hypot` 是「缩放 + `Sqrt(p*p + q*q)`」，**没有修正步**；这里补上。
//
// # 算法（与 CPython `math.hypot` 同一条路：double-double + 一次 Newton 修正）
//
//  1. 特殊值：任一参数是 ±Inf ⇒ +Inf；否则任一 NaN ⇒ NaN；最大者为 0 ⇒ 0。
//     与 `math.Hypot` 的既有口径一致（改这个函数**不许**改变特殊值行为）。
//  2. 取绝对值、排序（`ax >= ay`）。
//  3. 用 `Frexp`/`Ldexp` 把 `ax` 归一到 `[0.5, 1)` —— **2 的幂缩放是精确的**，
//     不引入任何误差；归一之后 `sx*sx + sy*sy ∈ [0.25, 2)` ⇒ 既不上溢也不下溢。
//  4. 用 `FMA` 把两个平方各自算成 double-double（`p+pe == sx*sx` 精确），
//     用 two-sum 求出 `p+q` 的精确残差 `err`，再并上两个平方的残差 ⇒ `s + lo`
//     就是 `sx*sx + sy*sy` 的高精度值。
//  5. `r = Sqrt(s)`，然后**一次 Newton 修正** `r += (s + lo - r*r) / (2r)`；
//     分子里的 `r*r` 也走 `FMA` 取精确残差 ⇒ 结果正确舍入。
//
// # 判据（两把，都不许省）
//
//   - **外面那把是权威**：`out/acceptance/_hypot_rounding_check.py`
//     （真值来自 `decimal`，不依赖本函数、也不依赖 CPython 的实现；它同时
//     生成 `testdata/hypot_rounding.txt`）。改这里之后必须重跑它，要求
//     「Go 不正确 = 0 例」。
//   - **里面那把是棘轮**：`num_test.go` 吃上面那份夹具，逐例要求逐位相等，
//     并且要求**样本里确实含有标准库答错的例**（否则就是样本没行使 ⇒ 判红）。
func Hypot(x, y float64) float64 {
	if math.IsInf(x, 0) || math.IsInf(y, 0) {
		return math.Inf(1)
	}
	if math.IsNaN(x) || math.IsNaN(y) {
		return math.NaN()
	}
	ax, ay := math.Abs(x), math.Abs(y)
	if ax < ay {
		ax, ay = ay, ax
	}
	if ax == 0 {
		return 0
	}
	//: 归一到 [0.5, 1)：2 的幂缩放精确，且让平方和落在 [0.25, 2)。
	_, e := math.Frexp(ax)
	sx := math.Ldexp(ax, -e)
	sy := math.Ldexp(ay, -e)

	//: 平方和的 double-double：(s + lo) ≈ sx*sx + sy*sy。
	p := sx * sx
	pe := math.FMA(sx, sx, -p) //: p + pe == sx*sx，精确
	q := sy * sy
	qe := math.FMA(sy, sy, -q) //: q + qe == sy*sy，精确
	s := p + q
	bb := s - p
	err := (p - (s - bb)) + (q - bb) //: two-sum 的精确残差
	lo := err + pe + qe

	r := math.Sqrt(s)
	//: 一次 Newton 修正。分子 = (s + lo) - r*r，两块都用精确残差补齐。
	rr := r * r
	re := math.FMA(r, r, -rr)
	r += ((s - rr) + (lo - re)) / (2 * r)
	return math.Ldexp(r, e)
}
