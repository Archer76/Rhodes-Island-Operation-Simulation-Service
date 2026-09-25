package main

import "testing"

// TestSluggishFactor 盯住 2026-09-25 那次**语义变更**（博士裁定：停顿＝减速 80%）。
//
// 两条断言缺一不可：
//
//  1. **没有停顿时恰好是 1.0** —— 它乘在 `advance` 速度式的末尾，而 `x * 1.0`
//     在 IEEE754 下是精确的 ⇒ 没中停顿的敌人在这次改动前后**逐位相同**。
//     这一条是「改语义还能拿既有读数当参照」的全部依据，所以必须钉死。
//  2. **有停顿时是 0.2**（＝1 − 80%）——**不是 0**。写成 0 就是退回旧的
//     「整帧不移动」读法，而 `unit.py` 里那两种写法同时存在（这正是当初的冲突）。
func TestSluggishFactor(t *testing.T) {
	e := &enemy{}
	if got := e.sluggishFactor(); got != 1.0 {
		t.Fatalf("没有停顿时必须是精确的 1.0，得 %v", got)
	}
	e.sluggishTimer = 0.5
	if got := e.sluggishFactor(); got != 1.0-sluggishSlowPct {
		t.Fatalf("停顿中应是 1−%v，得 %v", sluggishSlowPct, got)
	}
	if got := e.sluggishFactor(); got == 0.0 {
		t.Fatal("停顿**不是**不能移动（那是被博士推翻的旧读法）：系数不该是 0")
	}
}

// TestSluggishKeepsOtherFactorsBitIdentical 是那条不变量的**真形态**：
// 不是「系数看着像 1」，而是「整条速度式逐位不变」。
//
// 用一串**故意不好看**的数（末位差异会暴露提前合并）算两遍：
// 旧式（没有停顿这一项）与新式（末尾多乘一个 1.0）。
func TestSluggishKeepsOtherFactorsBitIdentical(t *testing.T) {
	cases := []struct{ move, scale, mult, haste float64 }{
		{1.1, 0.5, 0.873, 1.0},
		{0.7, 0.25, 1.0, 1.0},
		{1.3, 1.0, 0.3333333333333333, 1.4},
		{2.0, 0.5, 0.5, 0.5},
	}
	for _, c := range cases {
		e := &enemy{}
		e.spec.MoveSpeed = c.move
		old := c.move * c.scale * c.mult * c.haste
		now := c.move * c.scale * c.mult * c.haste * e.sluggishFactor()
		if old != now {
			t.Errorf("move=%v scale=%v mult=%v haste=%v：旧 %v 新 %v（必须逐位相同）",
				c.move, c.scale, c.mult, c.haste, old, now)
		}
	}
}

// TestReadTraitSlow 盯住特性「攻击附带停顿」那条判据（梓兰 凝滞师）。
//
// ★ 值是**秒数**，不是减速比例——减速比例是全局常数。把 0.8 当成「减速 80%」
// 读也不会报错（两个数恰好一样），所以这里用一个**不可能被误读成比例**的值钉住。
func TestReadTraitSlow(t *testing.T) {
	cases := []struct {
		bb   []any
		want float64
	}{
		{[]any{"sluggish", 2.5}, 2.5},  // 若被当成比例，2.5 会露馅
		{[]any{"sluggish", 0.8}, 0.8},  // 真实值（梓兰）
		{[]any{"sluggish", 0.0}, 0.0},  // 非正 = 没有这条
		{[]any{"hindrance", 1.0}, 0.0}, // 别的键不算
		{[]any{}, 0.0},                 // 空黑板
	}
	for _, c := range cases {
		raw := traitWithBlackboard(c.bb)
		if got := readTraitSlow(raw); got != c.want {
			t.Errorf("黑板 %v：得 %v，要 %v", c.bb, got, c.want)
		}
	}
}
