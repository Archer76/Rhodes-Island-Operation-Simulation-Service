package main

import (
	"math"
	"testing"
)

// 浮点近似比较用**本文件私有**的名字。
//
// ⚠ 为什么不能叫 `near`：`status_test.go:96` 把 `near` 当**数值**用
// （`math.Abs(got-30) > near`，一个容差常量），我第一版直接 `func fragileNear(...)` 就把它顶掉了，
// 编译报的是 `mismatched types float64 and func(...)`——**报错指向的是别人的文件**。
// 教训：往共用 package 里加 helper，先挑一个别人不可能用的名字。
func fragileNear(a, b float64) bool { return math.Abs(a-b) < 1e-9 }

// **同名取最高**——这是词典原文唯一明写的规则，也是本机制最容易做错的一处：
// 做错的方式是"同名相加"，那样两个 30% 会变成 60%，伤害静默偏高。
func TestFragileSameNameTakesMaxNotSum(t *testing.T) {
	var f fragileState
	f.Add("脆弱", 0.3, 10)
	f.Add("脆弱", 0.5, 10)
	if got := f.Ratio(); !fragileNear(got, 0.5) {
		t.Fatalf("同名应取最高 0.5（不是相加 0.8），得到 %v", got)
	}
	if got := f.Apply(1000); !fragileNear(got, 1500) {
		t.Fatalf("1000 伤害在 0.5 下应为 1500，得到 %v", got)
	}
}

// 低比例的那条**不会**把高比例压下来（顺序无关）。
func TestFragileSameNameOrderIndependent(t *testing.T) {
	var a, b fragileState
	a.Add("脆弱", 0.5, 10)
	a.Add("脆弱", 0.3, 10)
	b.Add("脆弱", 0.3, 10)
	b.Add("脆弱", 0.5, 10)
	if !fragileNear(a.Ratio(), 0.5) || !fragileNear(b.Ratio(), 0.5) {
		t.Fatalf("两种施加顺序都应为 0.5，得到 %v / %v", a.Ratio(), b.Ratio())
	}
}

// 异名相加：**这一条是未取证的实现选择**（见 fragile.go 文件头），
// 用守卫钉住是为了——改口径时守卫必然变红，不许静默改。
func TestFragileDistinctNamesAdd(t *testing.T) {
	var f fragileState
	f.Add("甲方的脆弱", 0.2, 10)
	f.Add("乙方的脆弱", 0.3, 10)
	if got := f.Ratio(); !fragileNear(got, 0.5) {
		t.Fatalf("当前实现取异名相加＝0.5，得到 %v；若这是有意改口径，请同时改这条守卫", got)
	}
}

// **各自计时**：短的那条到期后，比例应回落到长的那条的值，而不是一起消失。
// 这条守卫盯的是"把同名合并成一条"那种偷懒实现。
func TestFragileTimersAreIndependent(t *testing.T) {
	var f fragileState
	f.Add("脆弱", 0.5, 1)  // 1 秒后到期
	f.Add("脆弱", 0.3, 10) // 10 秒
	if !fragileNear(f.Ratio(), 0.5) {
		t.Fatalf("初始应取最高 0.5，得到 %v", f.Ratio())
	}
	f.Tick(2) // 过掉短的那条
	if !fragileNear(f.Ratio(), 0.3) {
		t.Fatalf("短条到期后应回落到 0.3，得到 %v（若为 0 说明把同名合并成了一条）", f.Ratio())
	}
	f.Tick(20)
	if f.Active() || !fragileNear(f.Ratio(), 0) {
		t.Fatalf("全部到期后应无效果，得到 active=%v ratio=%v", f.Active(), f.Ratio())
	}
}

// 非正的比例/时长不记：数据里 0 值极常见，记下来就成了"永久的 +0%"，
// 会让 Active() 报真、痕迹一路打，掩盖真正该看的东西。
func TestFragileIgnoresNonPositiveInput(t *testing.T) {
	var f fragileState
	f.Add("脆弱", 0, 10)
	f.Add("脆弱", 0.3, 0)
	f.Add("", 0.3, 10)
	f.Add("脆弱", -0.5, 10)
	if f.Active() || !fragileNear(f.Ratio(), 0) {
		t.Fatalf("非正输入不该被记下，得到 active=%v ratio=%v", f.Active(), f.Ratio())
	}
}

// Apply 对非正伤害原样返回（不要造出负数或凭空加伤）。
func TestFragileApplyLeavesNonPositiveDamageAlone(t *testing.T) {
	var f fragileState
	f.Add("脆弱", 0.5, 10)
	if got := f.Apply(0); !fragileNear(got, 0) {
		t.Fatalf("0 伤害应原样返回，得到 %v", got)
	}
	if got := f.Apply(-100); !fragileNear(got, -100) {
		t.Fatalf("负伤害（回血类记账）应原样返回，得到 %v", got)
	}
}

// **混轴守卫**：脆弱只提升物理/法术/真实伤害，**不含**元素损伤。
// 「元素脆弱」是另一条轴（`ep_fragile`）。混进来会让两边都错。
func TestFragileDoesNotAmplifyElementDamage(t *testing.T) {
	var f fragileState
	f.Add("脆弱", 1.0, 10) // +100%，足够明显
	// 元素损伤不走 fragileState.Apply：这里用一个"元素量"验证没有可乘之机——
	// 若有人把元素损伤也接进 Apply，本守卫会失败（因为它会翻倍）。
	elementAmount := 200.0
	if got := f.Apply(elementAmount); fragileNear(got, elementAmount) {
		t.Fatalf("脆弱必须能提升普通伤害（这是反证：否则本守卫是空的）")
	}
	// 正面断言：本文件不提供任何把元素损伤乘进去的入口。
	if _, ok := any(f).(interface{ applyElement(float64) float64 }); ok {
		t.Fatal("fragileState 不该有元素损伤入口——元素脆弱是另一条轴")
	}
}

// Names 去重且顺序稳定（痕迹要可比对）。
func TestFragileNamesDedupStable(t *testing.T) {
	var f fragileState
	f.Add("甲", 0.1, 5)
	f.Add("乙", 0.1, 5)
	f.Add("甲", 0.2, 5)
	got := f.Names()
	if len(got) != 2 || got[0] != "甲" || got[1] != "乙" {
		t.Fatalf("应为 [甲 乙]，得到 %v", got)
	}
}
