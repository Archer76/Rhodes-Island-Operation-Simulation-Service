package main

import "math"

// 【恐惧】与【诱导】的移动（诱发移动）——几何与选择那一层。
//
// 判据出处：PRTS `诱发移动` 页（2026-09-19 抓取，原文存
// `tmp/prts/页-诱发移动.txt`）。`异常效果` 页对恐惧只写了一句
// 「激活单位的恐惧控制器，详细机制请见`诱发移动#恐惧`」——**细节全在这一页**，
// 所以光看异常效果页是写不出这条机制的。
//
// 原文（`诱发移动` 页）：
//
//	「恐惧是一个拥有着复杂机制的BUFF，激活恐惧控制器，令敌人以**远离施加者**的
//	  "方式"进行特殊的"恐惧移动"……※自惧与恐惧完全相等，且可以代替恐惧维持恐惧控制器。
//	  ===恐惧可达地块===
//	  施加恐惧效果时，恐惧控制器会建立一个列表，以特殊逻辑记录下若干个地块以供"四散逃跑"。
//	  如果存在效果源以**被命中位置**为扇形中心，**半径10格**内、**远离效果源方向**的
//	  **左右各45°**扇形区域中的地块若满足以下条件则将被记录为"恐惧可达地块"：
//	  * 该格中心点位于给定范围内；
//	  * 该格可抵达其终点；
//	  * 该格为可通行地块（**不论该格是否有障碍物**）；
//	  * 该格**不为保护目标点或地穴**。
//	  特殊地，如果效果源与目标自身的距离为0（完全重合），则最终将**不存在任何有效的
//	  恐惧可达地块**。……如果不存在效果源或是效果源为自己，则直接视为**不存在任何有效的
//	  恐惧可达地块**。
//	  ===恐惧移动===
//	  受恐惧控制器影响的单位会以恐惧可达地块中距离自身**寻路距离5格**内的**随机1格**
//	  作为新的临时检查点（具有**0.5边长正方形**的随机偏移）生成临时路径。若不存在
//	  恐惧可达地块，则代用当前地块（相同随机偏移）生成临时路径。……
//	  * 如果找不到可用地块或找到的恐惧可达地块寻路距离>5，则地块将回落至自身所在地块。
//	  : 因为距离过长的情况下回落至自身所在格时，之前选择的"5距离之外"格子会**永久**
//	    从当次恐惧的恐惧可达地块中剔除（直到恐惧可达地块范围被刷新）。
//	  * 重复获得恐惧时**立刻以当前位置刷新**恐惧可达地块范围及新的检查点。
//	  : 持有多个恐惧效果时，**任一恐惧效果结束也会立刻刷新**新的检查点。
//	  ==诱移优先级==
//	  当一个目标同时拥有多种诱发移动效果时，按 **恐惧>诱导** 的优先级取最高一个在当前
//	  时刻有效。」
//
// ⚠ 本层**只管几何与选择**：随机量由调用方按单位随机数传入，时间与生命周期
// （持续多久、结束时清除【恐惧移动】）属接线范围——这样这一层才是确定的、可自证的。
//
// ⚠ tooltip 词典说恐惧是「无法被阻挡并四散逃跑」，但 `异常效果` 页与 `诱发移动` 页
// **都没有**"不可阻挡"这一句，且 FEARED 不在三张清单（阻止攻击/能力/移动）里。
// 故"不可阻挡"按**词典独有的说法**处理，登记为待核，不在本层实现。

const (
	//: 「半径10格内」。
	fearRadius = 10.0
	//: 「远离效果源方向的左右各45°」。
	fearHalfAngle = math.Pi / 4
	//: 「距离自身寻路距离5格内」。
	fearLocalPathDist = 5
	//: 「0.5边长正方形」→ 以格中心为原点的 ±0.25 偏移。
	fearOffsetHalf = 0.25
)

// fearSectorHit 报告"格 center 是否落在以 hit 为扇形中心、朝 awayFrom 方向张开
// ±45°、半径 10 格的扇形内"。
//
// 三个前置：`source` 与 `hit` 完全重合、或 `source == self`（效果源为自己）时，
// 原文规定**不存在任何有效的恐惧可达地块**，故整条判据直接为假。
//
// ⚠ 「远离效果源方向」= 从效果源指向被命中位置的那个方向；扇形张在**命中位置**上，
// 不是张在效果源上（原文写的是"以被命中位置为扇形中心"）。这两个中心差 10 格量级，
// 写反了会得到一整套错误地块，而且不会报错。
func fearSectorHit(hit, source, center [2]float64) bool {
	dx, dy := hit[0]-source[0], hit[1]-source[1]
	if dx == 0 && dy == 0 {
		return false // 效果源与被命中位置完全重合
	}
	ox, oy := center[0]-hit[0], center[1]-hit[1]
	if ox*ox+oy*oy > fearRadius*fearRadius {
		return false // 半径 10 格之外
	}
	if ox == 0 && oy == 0 {
		return true // 扇形中心自身（角度未定义但距离为 0，按在内处理）
	}
	// 用点积比较夹角，避开 atan2 的分支与精度问题。
	// 加 1e-12 是给"恰好 45°"留余量：边界上两侧算出来的余弦不会逐位相等，
	// 不留余量会让边界格的结果取决于浮点误差（本项目栽过"边界差一个"）。
	dot := dx*ox + dy*oy
	cosAngle := dot / (math.Hypot(dx, dy) * math.Hypot(ox, oy))
	return cosAngle >= math.Cos(fearHalfAngle)-1e-12
}

// fearCellOK 是可达地块的四个条件（原文那四条）。
//
// ⚠ 「该格为可通行地块（**不论该格是否有障碍物**）」——括号那句是重点：
// 占着障碍物也算可通行。它与"该格可抵达其终点"是**两条**，不是同一条的同义反复。
// 传进来的三个谓词各自回答一条，别把它们合并。
type fearCellOK struct {
	Reachable func(cell [2]int) bool //: 「该格可抵达其终点」
	Passable  func(cell [2]int) bool //: 「该格为可通行地块（不论是否有障碍物）」
	GoalOrPit func(cell [2]int) bool //: 「该格为保护目标点或地穴」——这一条是**排除**用
}

// fearCells 建**恐惧可达地块**列表：扇区内中心点合格、可抵达终点、可通行、
// 且不是保护目标点或地穴。
//
// `candidates` 由调用方给（通常是必经地图全格或扇区内格），本函数只做筛选——
// 这样测试不必造一整张地图。
func fearCells(hit, source [2]float64, candidates [][2]int, ok fearCellOK) [][2]int {
	if hit == source {
		return nil // 「不存在任何有效的恐惧可达地块」
	}
	out := make([][2]int, 0, len(candidates))
	for _, c := range candidates {
		center := [2]float64{float64(c[0]), float64(c[1])}
		if !fearSectorHit(hit, source, center) {
			continue
		}
		if ok.Reachable != nil && !ok.Reachable(c) {
			continue
		}
		if ok.Passable != nil && !ok.Passable(c) {
			continue
		}
		if ok.GoalOrPit != nil && ok.GoalOrPit(c) {
			continue
		}
		out = append(out, c)
	}
	return out
}

// fearTargets 是「当次恐惧」的可达地块池，负责原文那条**永久剔除**规则。
//
// 「之前选择的"5距离之外"格子会永久从当次恐惧的恐惧可达地块中剔除
//
//	（**直到恐惧可达地块范围被刷新**）」——所以池子是可变的，而刷新（重复获得恐惧）
//
// 由调用方重建一个新的 fearTargets。
type fearTargets struct {
	cells [][2]int
	gone  map[[2]int]bool
}

func newFearTargets(cells [][2]int) *fearTargets {
	return &fearTargets{cells: cells, gone: map[[2]int]bool{}}
}

// alive 是剔除后剩下还能选的格子数（0 表示"找不到可用地块"）。
func (f *fearTargets) alive() int {
	n := 0
	for _, c := range f.cells {
		if !f.gone[c] {
			n++
		}
	}
	return n
}

// pick 选一个临时检查点。
//
// 规则按原文：在**寻路距离 ≤ 5** 的格子里随机取 1 格；若没有这样的格子
// （找不到可用地块，或所有格子的寻路距离都 > 5），则**回落至自身所在格**，
// 并把那些"5 距离之外"的格子**永久剔除**。
//
// `u` ∈ [0,1) 是调用方给的随机数——本层自己不取随机，保持确定可测。
// 返回 (检查点, 是否用了回落)。
func (f *fearTargets) pick(self [2]int, pathDist func(a, b [2]int) int, u float64) ([2]int, bool) {
	local := make([][2]int, 0, len(f.cells))
	tooFar := make([][2]int, 0, len(f.cells))
	for _, c := range f.cells {
		if f.gone[c] {
			continue
		}
		if pathDist(self, c) <= fearLocalPathDist {
			local = append(local, c)
		} else {
			tooFar = append(tooFar, c)
		}
	}
	if len(local) == 0 {
		// 回落，并永久剔除这一批"5 距离之外"的格子
		for _, c := range tooFar {
			f.gone[c] = true
		}
		return self, true
	}
	if u < 0 {
		u = 0
	}
	if u >= 1 {
		u = 0.9999999999
	}
	idx := int(u * float64(len(local)))
	if idx >= len(local) {
		idx = len(local) - 1
	}
	return local[idx], false
}

// fearOffset 把两个单位随机数（各 ∈ [0,1)）变成"0.5 边长正方形"内的偏移量。
//
// ⚠ 是**正方形**不是圆：两条轴各自独立平移到 [−0.25, +0.25]，不要写成
// 极坐标的"半径 0.25 圆内"——两者在角上的分布明显不同，且都不报错。
func fearOffset(u1, u2 float64) [2]float64 {
	return [2]float64{
		(u1 - 0.5) * (fearOffsetHalf * 2),
		(u2 - 0.5) * (fearOffsetHalf * 2),
	}
}

// lureKind 是"当前时刻生效的诱发移动"。
type lureKind int

const (
	lureNone    lureKind = iota //: 都没有
	lureFear                    //: 恐惧
	lureAttract                 //: 诱导
)

// activeLure 是「诱移优先级」：同时拥有恐惧与诱导时取**恐惧**。
//
// 返回三态而不是 bool：本项目反复栽在"不可比≠相同"上——"有诱发移动"与
// "哪一种在生效"是两个问题，压成一个布尔会让调用方分不清该走哪条路径。
func activeLure(hasFear, hasAttract bool) lureKind {
	if hasFear {
		return lureFear
	}
	if hasAttract {
		return lureAttract
	}
	return lureNone
}
