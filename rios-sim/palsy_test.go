package main

import (
	"math"
	"testing"
)

// 【麻痹】的守卫。判据出处与两条来源的分工都写在 `palsy.go` 的文件头。
//
// 重点钉四件容易写歪的事：
//  ① 层数**上限 3**、且"没有这条"不等于"减一层"；
//  ② 麻痹免疫是"**失效但不清 Buff**"——层数照在，只是不触发；
//  ③ "未被消耗时持续时间无限"：没有抵抗时**一个计时器跑到底也不掉层**；
//  ④ 抵抗加速的是**层数流失**（5 秒→2.5 秒），**不是**那 0.5 秒震颤——写反不报错，
//    只表现为"震颤更弱"。

const palsyNear = 1e-12

func TestPalsyStacksCapAtThree(t *testing.T) {
	var p palsyState
	p.add(1)
	if p.stacks != 1 {
		t.Fatalf("加 1 层后应为 1，得到 %d", p.stacks)
	}
	// 神经损伤爆发一次给 3 层，再给一次不该变成 6 层
	p.add(3)
	if p.stacks != palsyMaxStacks {
		t.Fatalf("层数应被截到上限 %d，得到 %d", palsyMaxStacks, p.stacks)
	}
	p.add(0)
	p.add(-2)
	if p.stacks != palsyMaxStacks {
		t.Fatalf("非正层数不该改变层数（「没有这条」不是「减一层」），得到 %d", p.stacks)
	}
}

func TestPalsyImmuneKeepsStacksButInert(t *testing.T) {
	p := palsyState{immune: true}
	p.add(3)
	// 「使自身的麻痹失效，但**不会清除相关Buff**」——层数照记
	if p.stacks != 3 {
		t.Fatalf("免疫不阻止记层，应为 3，得到 %d", p.stacks)
	}
	if p.active() {
		t.Fatal("免疫时麻痹不该生效")
	}
	if p.interrupt() {
		t.Fatal("免疫时不该打断，也不该消耗层数")
	}
	if p.stacks != 3 {
		t.Fatalf("免疫时 interrupt 不该动层数，得到 %d", p.stacks)
	}
	// 免疫一撤，层数还在 ⇒ 立刻重新生效（Buff 从未被清除）
	p.immune = false
	if !p.active() {
		t.Fatal("免疫撤销后，身上还留着的层数应立即生效")
	}
}

func TestPalsyInterruptConsumesOneStackAndShakes(t *testing.T) {
	var p palsyState
	p.add(3)

	if !p.interrupt() {
		t.Fatal("有层数时应能打断")
	}
	if p.stacks != 2 {
		t.Fatalf("打断应消耗 1 层，得到 %d", p.stacks)
	}
	if math.Abs(p.shake-palsyShakeSecs) > palsyNear {
		t.Fatalf("打断应给 %.1fs 震颤，得到 %v", palsyShakeSecs, p.shake)
	}
	if p.canAttack() {
		t.Fatal("震颤期间不能攻击（也不能释放技能）")
	}

	// 第二次：层数继续掉，震颤取"更大值"（不叠加、不缩短）
	p.shake = 0.2
	if !p.interrupt() {
		t.Fatal("还有 1 层，应能再打断")
	}
	if math.Abs(p.shake-palsyShakeSecs) > palsyNear {
		t.Fatalf("震颤应取更大值 %.1f，得到 %v", palsyShakeSecs, p.shake)
	}

	// 第三次用光
	p.interrupt()
	if p.stacks != 0 {
		t.Fatalf("三次打断后层数应为 0，得到 %d", p.stacks)
	}
	if p.interrupt() {
		t.Fatal("没有层数时不该打断（更不该把层数压成负数）")
	}
	if p.stacks != 0 {
		t.Fatalf("没有层数时不该改变层数，得到 %d", p.stacks)
	}
}

func TestPalsyShakeDecaysAndClampsAtZero(t *testing.T) {
	var p palsyState
	p.shake = palsyShakeSecs

	p.tick(0.2, resistNone)
	if math.Abs(p.shake-0.3) > 1e-9 {
		t.Fatalf("震颤应扣到 0.3，得到 %v", p.shake)
	}
	p.tick(0.5, resistNone)
	if p.shake != 0 {
		t.Fatalf("震颤应夹到 0（不许为负），得到 %v", p.shake)
	}
	if !p.canAttack() {
		t.Fatal("震颤结束后应能攻击")
	}
}

func TestPalsyUnconsumedLastsForever(t *testing.T) {
	// 「麻痹未被消耗时持续时间无限」
	var p palsyState
	p.add(1)
	for i := 0; i < 100; i++ {
		p.tick(10.0, resistNone) // 累计 1000 秒
	}
	if p.stacks != 1 {
		t.Fatalf("没有抵抗时层数不该随时间掉（应恒为 1），得到 %d", p.stacks)
	}
}

func TestPalsyDecaysOnlyWithResistAndShakeIsNotAccelerated(t *testing.T) {
	var p palsyState

	// 有抵抗才流失：倍率 1.0 时跑 6 秒不掉层
	p.add(2)
	p.tick(6.0, resistNone)
	if p.stacks != 2 {
		t.Fatalf("没有抵抗不该流失层数，得到 %d", p.stacks)
	}

	// 抵抗减半：5 秒变 2.5 秒
	p.tick(palsyDecayInterval(palsyDecayBaseSecs, resistHalf), resistHalf)
	if p.stacks != 1 {
		t.Fatalf("抵抗下每 %.1fs 应流失 1 层，得到 %d",
			palsyDecayInterval(palsyDecayBaseSecs, resistHalf), p.stacks)
	}
	p.tick(palsyDecayInterval(palsyDecayBaseSecs, resistHalf), resistHalf)
	if p.stacks != 0 {
		t.Fatalf("再过一个周期应流光，得到 %d", p.stacks)
	}

	// ★ 反向：**震颤本身不乘倍率**。
	// 若把抵抗错误地也乘到震颤上，0.3 秒会扣成 0.6 秒 → shake 归零，
	// 症状只是"震颤变弱"，不会报错——所以这条必须单独钉。
	var q palsyState
	q.shake = palsyShakeSecs
	q.tick(0.3, resistHalf)
	if math.Abs(q.shake-0.2) > 1e-9 {
		t.Fatalf("震颤应按真实时间流逝（0.3s 后剩 0.2），得到 %v", q.shake)
	}
}

func TestPalsyWindupSecondTiming(t *testing.T) {
	// 「即将攻击的瞬间**或**动作开始一定时间（默认2秒）后」——第二个时机
	var p palsyState
	if p.windupReached(palsyWindupSecs - 0.01) {
		t.Fatal("不到 2 秒不该按第二个时机触发")
	}
	if !p.windupReached(palsyWindupSecs) {
		t.Fatalf("到 %.1f 秒应按第二个时机触发", palsyWindupSecs)
	}
}
