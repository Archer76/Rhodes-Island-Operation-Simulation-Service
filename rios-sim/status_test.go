package main

import (
	"math"
	"testing"
)

// 【寒冷】与【冻结】的数值效果守卫。
//
// 判据出处：**PRTS《敌人一览/数据》** 的 tooltip 词典（2026-09-19 博士提供该页）——
//
//	寒冷：攻击速度下降 30，如果在持续时间内再次受到寒冷效果则会变为冻结
//	冻结：无法移动、攻击及使用技能（通过寒冷触发）；敌方被冻结时，法术抗性-15
//
// 这两条数是项目此前**明确记为"拿不到"**的（`异常效果`页不给数、
// `excel/buff_table.json` 两个公开镜像都 404），见 `docs/mechanics-dictionary.md`。
//
// ⚠ 本文件只钉**机制本身**。有一条纪律必须留在这里：敌人作为受击方的结算要
// 走 `enemy.res()`（不是直接读 `spec.RES`），否则冻结那 −15 会静默漏掉——
// 现在读它的有主循环的普攻/技能结算与机制伤害两处。改结算路径时先回来看这里。

const near = 1e-9

func TestColdSlowsEnemyAttack(t *testing.T) {
	e := &enemy{spec: SpawnSpec{Interval: 1.7, RES: 30, DEF: 100}}

	// ① 没中招：**逐位等于**基础间隔（`× 100/100`）。这条是刻意的——
	// 补数值不该动既有对拍基线，谁把公式改成"总是折一下"这里会红。
	if got := e.interval(); math.Abs(got-1.7) > near {
		t.Fatalf("无寒冷时出手间隔应等于基础间隔 1.7，得到 %v", got)
	}

	// ② 中招：攻速 −30 ⇒ 间隔 × 100/70
	e.coldTimer = 5
	want := 1.7 * 100.0 / 70.0
	if got := e.interval(); math.Abs(got-want) > 1e-12 {
		t.Fatalf("寒冷中出手间隔应为 1.7×100/70 = %v，得到 %v", want, got)
	}

	// ③ 到期复位：冷却是**现读**计时器的（与 `sluggishTimer` 同一类），
	// 计时器归零那一刻间隔就该回来，不需要额外清状态。
	e.coldTimer = 0
	if got := e.interval(); math.Abs(got-1.7) > near {
		t.Fatalf("寒冷到期后应回到 1.7，得到 %v", got)
	}
}

func TestFrozenLowersEnemyRes(t *testing.T) {
	e := &enemy{spec: SpawnSpec{Interval: 1.0, RES: 30}}

	if got := e.res(); math.Abs(got-30) > near {
		t.Fatalf("未冻结时法抗应为 30，得到 %v", got)
	}
	// 限时冻结（计时器那一半）
	e.freezeTimer = 4
	if got := e.res(); math.Abs(got-15) > near {
		t.Fatalf("冻结期间法抗应为 30−15 = 15，得到 %v", got)
	}
	e.freezeTimer = 0
	// 积雪满层那一半（`frozenSnow` 是复合判据的另一半，漏了它这一路就静默）
	e.frozenSnow = true
	if got := e.res(); math.Abs(got-15) > near {
		t.Fatalf("站满层积雪上法抗也应为 15，得到 %v", got)
	}
	e.frozenSnow = false
	if got := e.res(); math.Abs(got-30) > near {
		t.Fatalf("解冻后法抗应回到 30，得到 %v", got)
	}
}

func TestApplyColdConvertsToFreeze(t *testing.T) {
	e := &enemy{spec: SpawnSpec{Interval: 1.0, RES: 0}}

	// 第一次：只上寒冷
	e.applyCold(5)
	if math.Abs(e.coldTimer-5) > near {
		t.Fatalf("首次寒冷应为 5 秒，得到 %v", e.coldTimer)
	}
	if e.freezeTimer != 0 {
		t.Fatalf("首次寒冷不该顺带冻结，得到 freeze=%v", e.freezeTimer)
	}

	// 第二次（仍在寒冷中）：转为冻结，**时长按触发那一次**（假设，见下）
	e.applyCold(3)
	if math.Abs(e.freezeTimer-3) > near {
		t.Fatalf("再次寒冷应转为 3 秒冻结，得到 %v", e.freezeTimer)
	}
	if e.coldTimer <= 0 {
		t.Fatalf("转冻结后寒冷计时不该被清掉，得到 %v", e.coldTimer)
	}

	// ⚠ 转冻结后的**时长**tooltip 没给数，实现按"触发那一次的秒数"取，
	// 这是**假设**不是定论（已登记进 docs/uncertainties.md）。口径若改，改这里。
}

func TestApplyColdRejectsNonPositive(t *testing.T) {
	e := &enemy{spec: SpawnSpec{Interval: 1.0, RES: 0}}
	e.applyCold(0)
	e.applyCold(-3)
	if e.coldTimer != 0 || e.freezeTimer != 0 {
		t.Fatalf("非正秒数不该写进任何计时器，得到 cold=%v freeze=%v",
			e.coldTimer, e.freezeTimer)
	}
}

func TestApplyFreezeTakesMax(t *testing.T) {
	e := &enemy{spec: SpawnSpec{Interval: 1.0, RES: 0}}
	e.applyFreeze(5)
	e.applyFreeze(2)
	if math.Abs(e.freezeTimer-5) > near {
		t.Fatalf("短冻结不该顶掉长冻结：期望 5，得到 %v", e.freezeTimer)
	}
	e.applyFreeze(8)
	if math.Abs(e.freezeTimer-8) > near {
		t.Fatalf("更长的冻结应当续上：期望 8，得到 %v", e.freezeTimer)
	}
}
