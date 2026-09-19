package main

import (
	"math"
	"testing"
)

// 【恐惧/诱导】移动层的守卫。判据原文抄在 `fear.go` 文件头。
//
// 这一层最贵的一条是**扇形中心在哪**：原文写"以**被命中位置**为扇形中心"，
// 而"远离效果源方向"又来自效果源。写成"以效果源为中心"会得到一整套错误地块，
// 且完全不会报错——所以单配一条能分辨这两种读法的用例。

func TestFearSectorIsAwayFromSource(t *testing.T) {
	source := [2]float64{0, 0}
	hit := [2]float64{10, 0} // 被命中位置在效果源正右方 ⇒ 扇形朝 +x 张开

	if !fearSectorHit(hit, source, [2]float64{20, 0}) {
		t.Fatal("正前方同轴、距离 10 以内 ⇒ 在扇形内")
	}
	if fearSectorHit(hit, source, [2]float64{-5, 0}) {
		t.Fatal("效果源那一侧（反方向）⇒ 不在扇形内")
	}
	// ⚠ 角度要按**相对命中位置**的偏移算：命中位置在 (10,0)，故偏移 (3,3) 才是 45°。
	// （写成 {10,10} 的偏移是 (0,10)＝90°，那是另一回事——本用例第一版就这么错了。）
	// 恰好 45°：应在边界内（判据留了 1e-12 余量）
	if !fearSectorHit(hit, source, [2]float64{13, 3}) {
		t.Fatal("恰好 45°应算在扇形边界内")
	}
	// 超过 45° 但**半径仍在 10 以内** ⇒ 只可能因角度被筛掉
	if fearSectorHit(hit, source, [2]float64{13, 3.2}) {
		t.Fatal("超过 45° ⇒ 不在扇形内（此例半径仅 4.4，排除半径因素）")
	}
	// 角度合格但半径超 10 ⇒ 只可能因半径被筛掉
	if fearSectorHit(hit, source, [2]float64{21, 0}) {
		t.Fatal("离命中位置超过 10 格 ⇒ 不在扇形内")
	}
}

// ★ 分辨"扇形中心是命中位置"还是"扇形中心是效果源"。
func TestFearSectorCenterIsTheHitPosition(t *testing.T) {
	source := [2]float64{0, 0}
	hit := [2]float64{10, 0}
	between := [2]float64{5, 0} // 在效果源与命中位置之间

	// 以**命中位置**为中心 ⇒ 该点在命中位置的反方向 ⇒ 不在扇形内
	if fearSectorHit(hit, source, between) {
		t.Fatal("命中位置与效果源之间的那格在扇形背面，不该被算进来" +
			"（若判成在内，说明扇形中心错放在了效果源上）")
	}
	// 以**效果源**为中心的错误读法会把它判为在内（距离5、方向同为+x）。
	// 这里显式把那个错误读法的结果写出来，免得日后有人"顺手改成以源为中心"：
	if !fearSectorHit(hit, source, [2]float64{15, 0}) {
		t.Fatal("命中位置前方 5 格应在扇形内（正确读法）")
	}
}

func TestFearNoCellsWhenSourceMeetsHitOrIsSelf(t *testing.T) {
	same := [2]float64{4, 4}
	if fearSectorHit(same, same, [2]float64{6, 4}) {
		t.Fatal("效果源与目标完全重合 ⇒ 不存在任何有效的恐惧可达地块")
	}
	cand := [][2]int{{6, 4}, {7, 4}}
	if got := fearCells(same, same, cand, fearCellOK{}); got != nil {
		t.Fatalf("完全重合时应返回空列表，得到 %v", got)
	}
}

func TestFearCellsApplyAllFourConditions(t *testing.T) {
	source := [2]float64{0, 0}
	hit := [2]float64{10, 0}
	cand := [][2]int{
		{14, 0},  // 合格
		{15, 3},  // 不可抵达终点
		{16, -3}, // 不可通行
		{17, 0},  // 是保护目标点/地穴
		{30, 0},  // 扇区外（半径超 10 且角度也偏）
	}
	ok := fearCellOK{
		Reachable: func(c [2]int) bool { return c != [2]int{15, 3} },
		Passable:  func(c [2]int) bool { return c != [2]int{16, -3} },
		GoalOrPit: func(c [2]int) bool { return c == [2]int{17, 0} },
	}
	got := fearCells(hit, source, cand, ok)
	if len(got) != 1 || got[0] != [2]int{14, 0} {
		t.Fatalf("四条条件应各自筛掉一格，只剩 {14,0}，得到 %v", got)
	}

	// 「该格为可通行地块（**不论该格是否有障碍物**）」与"可抵达终点"是两条：
	// 把 Passable 单独设为假，必须仍然被筛掉（证明两个谓词都在被读）
	ok2 := fearCellOK{Reachable: func([2]int) bool { return true }}
	ok2.Passable = func(c [2]int) bool { return c != [2]int{14, 0} }
	if got := fearCells(hit, source, [][2]int{{14, 0}}, ok2); len(got) != 0 {
		t.Fatalf("可通行那一条必须独立生效，得到 %v", got)
	}
	// 只给 Reachable 时，其余两条不设谓词 ⇒ 不应被误筛
	if got := fearCells(hit, source, [][2]int{{14, 0}}, fearCellOK{
		Reachable: func([2]int) bool { return true },
	}); len(got) != 1 {
		t.Fatalf("未提供的条件不该被当成假，得到 %v", got)
	}
}

func TestFearTargetsPickLocalThenFallbackAndPermanentRemoval(t *testing.T) {
	near := [2]int{1, 0}
	far := [2]int{9, 9}
	ft := newFearTargets([][2]int{near, far})
	dist := func(a, b [2]int) int {
		if b == far {
			return 20 // 「寻路距离>5」
		}
		return 3
	}

	// 有 5 格内的格子 ⇒ 取它，且不算回落
	got, fell := ft.pick([2]int{0, 0}, dist, 0.0)
	if fell || got != near {
		t.Fatalf("应取 5 格内的 %v，得到 %v（回落=%v）", near, got, fell)
	}
	// 把近的剔除后 ⇒ 只剩 >5 的 ⇒ 回落至自身，并把那格**永久剔除**
	ft.gone[near] = true
	got, fell = ft.pick([2]int{0, 0}, dist, 0.0)
	if !fell || got != [2]int{0, 0} {
		t.Fatalf("找不到可用地块应回落至自身，得到 %v（回落=%v）", got, fell)
	}
	if ft.alive() != 0 {
		t.Fatalf("5 距离之外的格子应被永久剔除，存活数=%d", ft.alive())
	}
	// 第二次仍然回落（剔除是永久的，不是一次性的）
	if _, fell = ft.pick([2]int{0, 0}, dist, 0.0); !fell {
		t.Fatal("剔除应持续生效")
	}
	// 「直到恐惧可达地块范围被刷新」——重建一个池子应当把格子找回来
	if newFearTargets([][2]int{near, far}).alive() != 2 {
		t.Fatal("刷新（重建池子）后可达地块应恢复")
	}
}

func TestFearOffsetIsASquareNotACircle(t *testing.T) {
	if o := fearOffset(0.5, 0.5); math.Abs(o[0]) > 1e-12 || math.Abs(o[1]) > 1e-12 {
		t.Fatalf("两个随机数都取中点 ⇒ 偏移为 0，得到 %v", o)
	}
	lo := fearOffset(0, 0)
	hi := fearOffset(1, 1)
	if math.Abs(lo[0]+fearOffsetHalf) > 1e-12 || math.Abs(lo[1]+fearOffsetHalf) > 1e-12 {
		t.Fatalf("下界应为 -%.2f，得到 %v", fearOffsetHalf, lo)
	}
	if math.Abs(hi[0]-fearOffsetHalf) > 1e-12 || math.Abs(hi[1]-fearOffsetHalf) > 1e-12 {
		t.Fatalf("上界应为 +%.2f，得到 %v", fearOffsetHalf, hi)
	}
	// ★ 正方形 vs 圆：角点到中心距离 = 0.25*sqrt2 > 0.25。若是"圆内均匀"就不会到角上。
	corner := math.Hypot(lo[0], lo[1])
	if corner <= fearOffsetHalf {
		t.Fatalf("角点距离 %.4f 应大于 %.2f（证明是正方形不是圆）", corner, fearOffsetHalf)
	}
}

func TestLurePriority(t *testing.T) {
	if activeLure(true, true) != lureFear {
		t.Fatal("恐惧与诱导同时存在 ⇒ 取恐惧")
	}
	if activeLure(false, true) != lureAttract {
		t.Fatal("只有诱导 ⇒ 取诱导")
	}
	if activeLure(true, false) != lureFear {
		t.Fatal("只有恐惧 ⇒ 取恐惧")
	}
	if activeLure(false, false) != lureNone {
		t.Fatal("都没有 ⇒ 三态里的「都没有」，不是「诱导」")
	}
}
