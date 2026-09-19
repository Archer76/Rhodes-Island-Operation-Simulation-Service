package main

import (
	"math"
	"testing"
)

// 【抵抗】的守卫。判据出处与原文都写在 `resist.go` 的文件头。
//
// 这个文件存在的理由：**"砍一半时长"和"加速流逝"在"还剩多久"这一面上等价**，
// 所以只测剩余时长的写法，用错实现也能全绿。必须用**逐帧扣减量**与**定时触发间隔**
// 这两个可观测量去钉——它们是两种实现真正分道扬镳的地方。

const resistNear = 1e-12

func TestResistFactorTakesStrongest(t *testing.T) {
	// 倍率越小抵抗越强，"同名效果取最高"在数值上就是取小
	if got := resistFactor(resistNone, resistHalf); math.Abs(got-0.5) > resistNear {
		t.Fatalf("1.0 与 0.5 合成应为 0.5，得到 %v", got)
	}
	if got := resistFactor(resistHalf, resistHalf); math.Abs(got-0.5) > resistNear {
		t.Fatalf("0.5 与 0.5 合成仍应为 0.5，得到 %v", got)
	}
	if got := resistFactor(resistNone, resistNone); math.Abs(got-1.0) > resistNear {
		t.Fatalf("两头都没抵抗应为 1.0，得到 %v", got)
	}
	// 非正值不是合法游戏值：按"没有抵抗"处理，绝不能放大成"状态立刻结束"
	if got := resistFactor(0, 0); math.Abs(got-1.0) > resistNear {
		t.Fatalf("非法倍率应退回 1.0，得到 %v", got)
	}
}

func TestResistedDuration(t *testing.T) {
	if got := resistedDuration(10, resistHalf); math.Abs(got-5) > resistNear {
		t.Fatalf("10 秒在抵抗下应为 5 秒，得到 %v", got)
	}
	if got := resistedDuration(10, resistNone); math.Abs(got-10) > resistNear {
		t.Fatalf("没抵抗不该改时长，得到 %v", got)
	}
	// 定时触发的效果间隔走**同一个式子**：页里那句"每秒受到一次法术伤害…
	// 变为每 0.5 秒受到一次法术伤害"。
	if got := resistedDuration(1.0, resistHalf); math.Abs(got-0.5) > resistNear {
		t.Fatalf("每秒一次的持续伤害在抵抗下应为每 0.5 秒一次，得到 %v", got)
	}
}

func TestAdvanceStatusAccelerates(t *testing.T) {
	const frame = 1.0 / 30.0

	// 没抵抗：每帧按原速扣
	if got := advanceStatus(1.0, frame, resistNone); math.Abs(got-(1.0-frame)) > resistNear {
		t.Fatalf("无抵抗时每帧应扣 %.10f，得到 %.10f", frame, 1.0-got)
	}
	// 抵抗减半：每帧扣 **2/30** 而不是 1/30（`可抵抗状态` 页里的原例）
	if got := advanceStatus(1.0, frame, resistHalf); math.Abs(got-(1.0-2*frame)) > resistNear {
		t.Fatalf("抵抗减半时每帧应扣 %.10f（2 倍速），得到 %.10f", 2*frame, 1.0-got)
	}
	// 夹零：不能让计时器变负
	if got := advanceStatus(0.01, frame, resistHalf); got != 0 {
		t.Fatalf("计时器应夹到 0，得到 %v", got)
	}
	// 非法倍率按无抵抗处理，不许除出 Inf
	if got := advanceStatus(1.0, frame, 0); math.Abs(got-(1.0-frame)) > resistNear {
		t.Fatalf("非法倍率不该改变扣减量，得到 %v", got)
	}
}

func TestResistHalvesTheWholeWindowNotJustTheLabel(t *testing.T) {
	// 这一条是"两种实现等价性"的对照：把 10 秒的状态按 30fps 逐帧推到 0，
	// 断言的**不是**"剩余时长"（那两种写法一样），而是**推完它花了多少帧**。
	const frame = 1.0 / 30.0
	left := resistedDuration(10, resistHalf) // 实际时长 5 秒
	frames := 0
	for left > 0 {
		left = advanceStatus(left, frame, resistHalf)
		frames++
	}
	// 5 秒 ÷ (1/30 秒/帧 × 2 倍速) = 75 帧
	if frames != 75 {
		t.Fatalf("抵抗减半的 10 秒状态应在 75 帧内走完，实得 %d 帧", frames)
	}
}

func TestPalsyDecayInterval(t *testing.T) {
	if got := palsyDecayInterval(5, resistNone); math.Abs(got-5) > resistNear {
		t.Fatalf("没抵抗时每 5 秒流失 1 层，得到 %v", got)
	}
	// ⚠ 这是**推导**（PRTS 只写"每 5 秒流失 1 层"，没写抵抗下的秒数），
	// 依据是同页"加速流逝 ⇒ 更频繁触发定时效果"。口径若改，这条一起改。
	if got := palsyDecayInterval(5, resistHalf); math.Abs(got-2.5) > resistNear {
		t.Fatalf("抵抗减半时每 2.5 秒流失 1 层，得到 %v", got)
	}
}
