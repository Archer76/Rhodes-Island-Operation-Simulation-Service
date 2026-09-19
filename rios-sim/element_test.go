package main

import (
	"math"
	"testing"
)

// 元素损伤（爆条）的守卫。判据出处与逐条原文都写在 `element.go` 的文件头。
//
// 这个文件重点钉三件最容易写错的事：
//  ① **爆条后不是"留余量"，是"进冷却 → 归满"**；
//  ② **冷却期间是对所有元素免疫**（不是只对爆掉的那一种）；
//  ③ **两列效果不能混**（同一个元素，敌人列与我方列的秒数与伤害都不同）。

const elemNear = 1e-9

func TestElementStateInitAndResist(t *testing.T) {
	s := newElementState(defaultMaxEP)
	for i := 1; i <= numElements; i++ {
		if math.Abs(s.ep[i]-1000) > elemNear {
			t.Fatalf("元素 %s 的初始元素值应为 1000，得到 %v", elementName(elementKind(i)), s.ep[i])
		}
	}
	// 领袖级敌人：最大值 2000（"与其属性上限"）
	l := newElementState(leaderMaxEP)
	if math.Abs(l.ep[elemSanity]-2000) > elemNear {
		t.Fatalf("领袖最大元素值应为 2000，得到 %v", l.ep[elemSanity])
	}

	// 损伤抵抗：损伤值 × (1 − 抵抗×0.01)
	s.resist = 20
	if got := elementDamage(500, s.resist); math.Abs(got-400) > elemNear {
		t.Fatalf("抵抗 20 时 500 损伤应折为 400，得到 %v", got)
	}
	if got := elementDamage(500, 0); math.Abs(got-500) > elemNear {
		t.Fatalf("无抵抗时不该折，得到 %v", got)
	}
	// 负损伤与非正损伤一律不产生元素损伤
	if got := elementDamage(-5, 0); got != 0 {
		t.Fatalf("负损伤应归零，得到 %v", got)
	}
}

func TestElementBurstOnZeroNotCarryOver(t *testing.T) {
	s := newElementState(defaultMaxEP)

	// ① 差一点：不爆条
	if s.damage(elemFire, 999) {
		t.Fatal("999 损伤不该爆条（元素值还剩 1）")
	}
	if math.Abs(s.ep[elemFire]-1) > elemNear {
		t.Fatalf("元素值应为 1，得到 %v", s.ep[elemFire])
	}

	// ② 补上最后 1 点：爆条。**元素值落到 0**，不是"留 0 余量"也不是负数
	if !s.damage(elemFire, 1) {
		t.Fatal("补满 1000 应当爆条")
	}
	if s.ep[elemFire] != 0 {
		t.Fatalf("爆条瞬间元素值应为 0，得到 %v", s.ep[elemFire])
	}
}

func TestElementCooldownBlocksEveryElement(t *testing.T) {
	s := newElementState(defaultMaxEP)
	s.damage(elemFire, 1000)
	s.startBurst(elemFire, burstOnEnemy[elemFire].Duration)

	// 冷却期间：**所有类型**都无法损失（原文：「单位所有类型的元素值均无法损失」）
	if !s.anyCooling() {
		t.Fatal("刚进冷却，anyCooling 应为真")
	}
	if s.damage(elemFire, 5000) {
		t.Fatal("冷却期间同种元素不该再爆条")
	}
	if s.damage(elemSanity, 5000) {
		t.Fatal("冷却期间**别的**元素也不该爆条——这是「所有类型」那条原文")
	}
	if math.Abs(s.ep[elemSanity]-1000) > elemNear {
		t.Fatalf("冷却期间别的元素值不该变，得到 %v", s.ep[elemSanity])
	}

	// 冷却结束：元素值归满
	done := s.tick(burstOnEnemy[elemFire].Duration)
	if len(done) != 1 || done[0] != elemFire {
		t.Fatalf("应恰有一个元素结束爆条，得到 %v", done)
	}
	if math.Abs(s.ep[elemFire]-1000) > elemNear {
		t.Fatalf("爆条结束后应归满 1000，得到 %v", s.ep[elemFire])
	}
	if s.anyCooling() {
		t.Fatal("冷却已结束，anyCooling 应为假")
	}
	// 归满之后可以再次爆条
	if !s.damage(elemFire, 1000) {
		t.Fatal("归满后应能再次爆条")
	}
}

func TestElementBurstDurationsDifferPerFaction(t *testing.T) {
	// 侵蚀损伤是唯一秒数不同的那条：敌人 8s，我方 10s
	if got := burstOnEnemy[elemWater].Duration; math.Abs(got-8) > elemNear {
		t.Fatalf("侵蚀损伤对敌人应为 8s，得到 %v", got)
	}
	if got := burstOnOperator[elemWater].Duration; math.Abs(got-10) > elemNear {
		t.Fatalf("侵蚀损伤对我方应为 10s，得到 %v", got)
	}
	want := map[elementKind]float64{elemSanity: 10, elemWater: 8, elemFire: 10, elemDark: 15, elemAnger: 15}
	for k, secs := range want {
		if got := burstOnEnemy[k].Duration; math.Abs(got-secs) > elemNear {
			t.Fatalf("%s 对敌爆发时长应为 %v，得到 %v", elementName(k), secs, got)
		}
	}
}

func TestElementBurstTableEnemyColumn(t *testing.T) {
	// 逐条对 PRTS《元素》页"其他单位受到的效果"列
	if b := burstOnEnemy[elemSanity]; b.Direct != 6000 || b.DirectType != "ELEMENT" ||
		b.PalsyStack != 3 || !b.PalsyImmune {
		t.Fatalf("神经损伤对敌应为 3 层麻痹＋麻痹免疫＋6000 元素，得到 %+v", b)
	}
	if b := burstOnEnemy[elemWater]; b.DefDown != 120 || b.Direct != 5000 || b.DirectType != "ELEMENT" {
		t.Fatalf("侵蚀损伤对敌应为 −120 防御＋5000 元素，得到 %+v", b)
	}
	if b := burstOnEnemy[elemFire]; b.ResDown != 20 || b.Direct != 7000 || b.DirectType != "ELEMENT" {
		t.Fatalf("灼燃损伤对敌应为 −20 法抗＋7000 元素，得到 %+v", b)
	}
	if b := burstOnEnemy[elemDark]; b.WeakPct != 50 || b.Dot != 800 || b.DotType != "ELEMENT" {
		t.Fatalf("凋亡损伤对敌应为 50%% 虚弱＋每秒 800 元素，得到 %+v", b)
	}
	// 狂躁对敌人一格是**空的**——这是原文「无效果」，不是漏抄
	if b := burstOnEnemy[elemAnger]; b.Direct != 0 || b.Dot != 0 || b.AspdUp != 0 || b.DefDown != 0 || b.ResDown != 0 {
		t.Fatalf("狂躁损伤对敌人类单位应为无效果，得到 %+v", b)
	}

	// 我方列也钉一遍（防止两列被后来的人合并）
	if b := burstOnOperator[elemSanity]; b.Direct != 1000 || b.DirectType != "TRUE" {
		t.Fatalf("神经损伤对我方应为 1000 真实伤害，得到 %+v", b)
	}
	if b := burstOnOperator[elemFire]; b.Direct != 1200 || b.DirectType != "MAGIC" || b.ResDown != 20 {
		t.Fatalf("灼燃损伤对我方应为 −20 法抗＋1200 法术，得到 %+v", b)
	}
	if b := burstOnOperator[elemAnger]; b.AspdUp != 50 || b.Dot != 100 ||
		b.DotGrowth != 50 || b.DotCap != 600 || !b.DotIsTrue {
		t.Fatalf("狂躁损伤对我方应为攻速+50、每秒 100 起每次+50 上限 600 真伤，得到 %+v", b)
	}
}

func TestResolveElementDamage(t *testing.T) {
	// DMG_e = max[0.05A, 0.01A·max(0, 100−D)]
	if got := resolveElementDamage(1000, 0); math.Abs(got-1000) > elemNear {
		t.Fatalf("元素抗性 0 时 1000 应打满，得到 %v", got)
	}
	if got := resolveElementDamage(1000, 30); math.Abs(got-700) > elemNear {
		t.Fatalf("元素抗性 30 时应为 700，得到 %v", got)
	}
	// 保底 5%：抗性 100 时 0.01×1000×0 = 0，被 0.05×1000 = 50 顶上去
	if got := resolveElementDamage(1000, 100); math.Abs(got-50) > elemNear {
		t.Fatalf("元素抗性 100 应落到 5%% 保底 50，得到 %v", got)
	}
	if got := resolveElementDamage(1000, 150); math.Abs(got-50) > elemNear {
		t.Fatalf("元素抗性超 100 仍取保底 50，得到 %v", got)
	}
}

func TestElementCurrentPicksLowest(t *testing.T) {
	s := newElementState(defaultMaxEP)
	if got := s.current(); got != elemNone {
		t.Fatalf("全满时应无当前损伤元素，得到 %s", elementName(got))
	}
	s.damage(elemDark, 300) // DARK 剩 700
	s.damage(elemFire, 500) // FIRE 剩 500 ← 最低
	if got := s.current(); got != elemFire {
		t.Fatalf("当前损伤元素应为最低的 FIRE，得到 %s", elementName(got))
	}
	// 平手时按 ID 升序：DARK 也降到 500，FIRE(3) < DARK(4)，仍取 FIRE
	s.damage(elemDark, 200)
	if got := s.current(); got != elemFire {
		t.Fatalf("平手 500 时应取 ID 更小的 FIRE，得到 %s", elementName(got))
	}
	// 出现更低者时立刻改判
	s.damage(elemWater, 600) // WATER 剩 400
	if got := s.current(); got != elemWater {
		t.Fatalf("WATER 最低时应改判 WATER，得到 %s", elementName(got))
	}
}
