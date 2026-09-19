package main

import "testing"

// 冻结 −15 法抗：把深水 P0 那条分岔的**算术**钉成守卫。
//
// 出处（PRTS《敌人一览/数据》tooltip / 记忆 `27c925e7`）：冻结期间**法术抗性 −15**，
// 且**只看施加方**——只有"友方冻结"才减，与目标阵营无关。
//
// 为什么值得单独钉：这条是**动态读**（`enemy.res()` 现算，不写 `spec.RES`），
// 所以它**不产生任何可观测量**；深水用例上它首次现形是因为"减伤因子变成 ×1.05"——
// 而 ×1.05 意味着 **RES 变成负数**（10 − 15 = −5）。
// 这个"抗性可以是负的、于是伤害系数大于 1"的后果，是当年对拍里最容易被读成"引擎算错"的那种现象，
// 所以本例把它连同那个反直觉的数字一起钉住。
func TestFrozenResistanceDownFifteen(t *testing.T) {
	e := &enemy{spec: SpawnSpec{Name: "去蚀", RES: 10}}

	// 未冻结：原样。
	if got := e.res(); got != 10 {
		t.Fatalf("未冻结时应为 10，得到 %v", got)
	}

	// 积雪造成的冻结：`frozenSnow` **无条件算友方**（积雪恒定是干员造成的）。
	e.frozenSnow = true
	if got := e.res(); got != -5 {
		t.Fatalf("积雪冻结时应为 10−15=−5，得到 %v", got)
	}
	if e.spec.RES != 10 {
		t.Fatalf("⚠ 动态读不许写回 spec.RES（写回会让它「冻过一次就永久变脆」），得到 %v", e.spec.RES)
	}

	// ★ 反直觉但正确：抗性为负 ⇒ 伤害系数 **大于 1**。
	// 深水实测：raw 696 在 RES 10 下是 ×0.9（626.4），在 RES −5 下是 ×1.05（730.8），差 104.38。
	factor := 1.0 - e.res()/100.0
	if factor != 1.05 {
		t.Fatalf("RES −5 的伤害系数应为 1.05（这是那条分岔的直接来源），得到 %v", factor)
	}

	// 解冻后抗性要**回来**——这正是"动态读"而不是"改写字段"的理由。
	e.frozenSnow = false
	if got := e.res(); got != 10 {
		t.Fatalf("解冻后应回到 10，得到 %v", got)
	}
}

// 「只看施加方」是这条的**适用范围**：非友方冻结（敌人造成的冻结）**不减**法抗。
//
// 这条口径是定过案的（记忆 `27c925e7`），而且极易做成"只要冻结就减 15"——
// 那种写法在"敌人冻结敌人"的场面下会静默多给伤害。
func TestFrozenResistanceOnlyForFriendlyFreeze(t *testing.T) {
	// 构造"非友方冻结"的形态：freezeTimer > 0 但 freezeFriendly 为假（零值）。
	e := &enemy{spec: SpawnSpec{Name: "去蚀", RES: 10}, freezeTimer: 5.0}
	if !e.frozen() {
		t.Fatal("freezeTimer>0 应算已冻结")
	}
	if e.friendlyFrozen() {
		t.Fatal("非友方冻结不该算 friendlyFrozen")
	}
	if got := e.res(); got != 10 {
		t.Fatalf("非友方冻结不减法抗，应仍为 10，得到 %v", got)
	}

	// 同一只改成友方来源 ⇒ 立刻减 15。
	e.freezeFriendly = true
	if !e.friendlyFrozen() {
		t.Fatal("友方冻结应算 friendlyFrozen")
	}
	if got := e.res(); got != -5 {
		t.Fatalf("友方冻结应减到 −5，得到 %v", got)
	}
}
