package main

import "testing"

// 折射状态层：守卫全部对着**取证来的原文**，不靠直觉。
//
// 取证出处见 `refraction.go` 头部：深池术师「法术抗性增加70（可被沉默）」；
// 假想敌·镜膜「最大生命值+100%（受沉默影响后失效，无法恢复）」。

// 第一条：**未生效时一分数都不动**。这条防的是"有折射就加"的写法。
func TestRefractionInactiveAddsNothing(t *testing.T) {
	var r refractionState
	if r.Effective() {
		t.Fatal("零值不该生效")
	}
	if got := r.ApplyResistance(10, 70); got != 10 {
		t.Fatalf("未生效应原样返回 10，得到 %v", got)
	}
}

// 第二条：生效时按**调用方给的量**加——这条钉的是"术师那一个实例"。
func TestRefractionActiveAddsCallerDelta(t *testing.T) {
	r := refractionState{Active: true}
	if !r.Effective() {
		t.Fatal("置位后应生效")
	}
	if got := r.ApplyResistance(10, 70); got != 80 {
		t.Fatalf("10+70 应为 80，得到 %v", got)
	}
}

// ★ 第三条（本文件最重要的一条）：**这层里不许有"+70"**。
//
// 折射的定义是"一个状态"，`+70` 只是深池术师那一个载体的实例（镜膜给的是最大生命值+100%）。
// 所以同一个状态、换一个量就必须换一个结果——若哪天有人把 70 写死进内核，
// 这条守卫的第三段会立刻红。
func TestRefractionDeltaIsNotHardcoded(t *testing.T) {
	r := refractionState{Active: true}
	if got := r.ApplyResistance(10, 70); got != 80 {
		t.Fatalf("传 70 应为 80，得到 %v", got)
	}
	// 同一个状态、量换成 0 与 200：结果必须跟着走。
	if got := r.ApplyResistance(10, 0); got != 10 {
		t.Fatalf("传 0 应为 10（说明 70 不是写死的），得到 %v", got)
	}
	if got := r.ApplyResistance(10, 200); got != 210 {
		t.Fatalf("传 200 应为 210，得到 %v", got)
	}
	// 负数也要照做（折射若被做成减抗，本层不该拦）。
	if got := r.ApplyResistance(10, -15); got != -5 {
		t.Fatalf("传 -15 应为 -5，得到 %v", got)
	}
}

// 第四条：**可被沉默**——沉默期间折射失效（术师与镜膜两条原文都写了这一层）。
func TestRefractionSilencedStopsWorking(t *testing.T) {
	r := refractionState{Active: true}
	r.Silence(true)
	if r.Effective() {
		t.Fatal("被沉默时折射不该生效")
	}
	if got := r.ApplyResistance(10, 70); got != 10 {
		t.Fatalf("被沉默时应原样返回 10，得到 %v", got)
	}
}

// 第五条：非锁定模式——解除沉默后**恢复**。
//
// ⚠ 这一档是**未取证**的默认（术师那条只写了"可被沉默"，没写沉默后恢不恢复），
// 所以它在这里被明确标成"一种模式"，而不是被默认成真理。
func TestRefractionRecoversWhenModeSaysSo(t *testing.T) {
	r := refractionState{Active: true, Mode: refractionSilenceRecovers}
	r.Silence(true)
	if r.Effective() {
		t.Fatal("沉默期间不该生效")
	}
	r.Silence(false)
	if !r.Effective() {
		t.Fatal("非锁定模式下解除沉默应恢复")
	}
	if got := r.ApplyResistance(10, 70); got != 80 {
		t.Fatalf("恢复后应回到 80，得到 %v", got)
	}
}

// ★ 第六条：镜膜式——「受沉默影响后失效，**无法恢复**」。
//
// 三段都要成立，缺一段就说明"无法恢复"没被真正实现：
// ① 沉默期间失效；② 解除沉默**仍**失效；③ 再置位一次**也**救不回来。
func TestRefractionLatchesWhenModeSaysSo(t *testing.T) {
	r := refractionState{Active: true, Mode: refractionSilenceLatches}
	r.Silence(true)
	if r.Effective() || !r.Latched {
		t.Fatal("锁模下被沉默应同时置上 latched")
	}
	r.Silence(false)
	if r.Effective() {
		t.Fatal("解除沉默后仍应失效（原文：无法恢复）")
	}
	r.Set(true) // 再给一次
	if r.Effective() {
		t.Fatal("重新置位也不该生效（原文：无法恢复）")
	}
	if got := r.ApplyResistance(10, 70); got != 10 {
		t.Fatalf("锁定后应原样返回 10，得到 %v", got)
	}
}

// 第七条：`Active` 与 `Effective` 必须**可分**。
//
// 「被沉默吃掉」与「本来就没给折射」在观测量上都是"没加成"，
// 但它们是两件事——本层把它们拆成两列，这条守卫防止将来有人把它合成一个布尔。
func TestRefractionActiveAndEffectiveAreDistinguishable(t *testing.T) {
	r := refractionState{Active: true}
	r.Silence(true)
	if !r.Active {
		t.Fatal("Active 应仍为真：它身上**有**折射，只是被沉默吃掉了")
	}
	if r.Effective() {
		t.Fatal("Effective 应为假")
	}
}
