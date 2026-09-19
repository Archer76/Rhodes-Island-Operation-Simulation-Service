package main

import "testing"

// **核心区分**：隐匿在 `get_targetFree` 的五个里，迷彩**不在**。
// 把迷彩塞进同一张掩码，会让"光环/格子/中点"这类本该无视迷彩的效果被拦掉。
func TestStealthCamouflageIsNotInTargetFree(t *testing.T) {
	// 只有迷彩、没有任何无法选择类效果 ⇒ 通用选取仍然选得中。
	if !selectableFrom(0) {
		t.Fatal("没有任何无法选择类效果时应可选")
	}
	// 隐匿则相反。
	if selectableFrom(tfHidden) {
		t.Fatal("隐匿应不可被不同阵营选中")
	}
}

// 五个标志逐一验证——少一个就是漏了原文里的一项。
func TestStealthAllFiveFlagsBlockSelection(t *testing.T) {
	each := map[string]targetFree{
		"隐匿":    tfHidden,
		"不可选中":  tfUntargetable,
		"无敌":    tfInvincible,
		"塔不可选中": tfTowerFree,
		"对地规避":  tfGroundFree,
	}
	for name, f := range each {
		if selectableFrom(f) {
			t.Fatalf("%s 应使单位不可被选中（原文 get_targetFree 查这五个）", name)
		}
	}
}

// 对地规避只在**索敌者是地面**时生效（原文括号）。
func TestStealthGroundFreeIgnoredByFlyingSelector(t *testing.T) {
	if !notSelectable(tfGroundFree, true) {
		t.Fatal("地面索敌者应被对地规避挡住")
	}
	if notSelectable(tfGroundFree, false) {
		t.Fatal("非地面索敌者应忽略对地规避（原文明确写了这个例外）")
	}
}

// 迷彩对不同的选取方式答案不同：挡住能力/弹道，放行光环/格子/中点。
func TestStealthCamouflageKindDependent(t *testing.T) {
	for _, k := range []selectorKind{selAbility, selProjectile} {
		if !camouflageBlocks(k, false) {
			t.Fatalf("kind=%d 应被迷彩挡住", k)
		}
	}
	for _, k := range []selectorKind{selAura, selCell, selMidpoint} {
		if camouflageBlocks(k, false) {
			t.Fatalf("kind=%d 原文写明不受迷彩制约（光环/格子/中点判定）", k)
		}
	}
}

// ★ 反隐让迷彩"失效"但**不让迷彩消失**：选择看不见它，检测仍看得见它。
// 合成一个布尔就会把这两种问法答成同一个答案——这条守卫盯的就是那个合成。
func TestStealthAntiStealthHidesButDoesNotEraseCamouflage(t *testing.T) {
	if camouflageBlocks(selAbility, true) {
		t.Fatal("反隐后迷彩不应再挡住选取")
	}
	if !camouflageDetectable(true) {
		t.Fatal("反隐**不**改变「能不能检测到迷彩」——原文：无法真正阻止其他机制对迷彩的检测")
	}
}

// 反隐作用于选择判定时：拿走"看不见"的效果，但**无敌仍在**（无敌是免伤，不是看不见）。
func TestStealthAntiStealthKeepsInvincible(t *testing.T) {
	got := antiStealthSuppresses(tfHidden | tfUntargetable | tfInvincible | tfTowerFree)
	if got&tfInvincible == 0 {
		t.Fatal("反隐不该解除无敌——它不解除免伤")
	}
	if got&(tfHidden|tfUntargetable|tfTowerFree) != 0 {
		t.Fatalf("反隐应拿走隐匿/不可选中/塔不可选中，得到 %d", got)
	}
}

// 被阻挡 ⇒ 敌方强制攻击，无视一切可选性（原文限定"对于敌方而言"）。
func TestStealthBlockingOverridesEverything(t *testing.T) {
	if !blockingOverridesSelection(true) {
		t.Fatal("被阻挡时敌方应强制攻击")
	}
	all := tfHidden | tfUntargetable | tfInvincible | tfTowerFree | tfGroundFree
	// 语义断言：无论掩码多大，被阻挡这一条都独立成立——它不查掩码。
	if !blockingOverridesSelection(true) || notSelectable(all, true) == false {
		t.Fatal("被阻挡的强制攻击与掩码是两条独立规则")
	}
}

// 组合：隐匿 + 反隐 + 地面索敌 ⇒ 可选；再叠对地规避 ⇒ 又不可选。
func TestStealthComposition(t *testing.T) {
	f := antiStealthSuppresses(tfHidden)
	if !selectableFrom(f) {
		t.Fatal("隐匿被反隐抵消后应可选")
	}
	if selectableFrom(f | tfGroundFree) {
		t.Fatal("再叠加对地规避（地面索敌者）应不可选")
	}
}

// 无敌既在掩码里，也单独与既有 damageVsInvincible 对接：
// 本层的结果就是原文说的"是否仍持有无敌/隐匿/不可选中/塔不可选中之一"。
//
// ⚠ 这条守卫我第一版写错过：`damageVsInvincible` 是**两级**判据——
// 先问"拿掉沉睡还剩不剩别的无敌理由"（`otherInvincibility`），再问"这一击带不带那个标记"
// （`sourceIgnoresSleep`）。我原来那版拿 `sleeping=true, ignores=false` 去要 1，等于
// 断言"没有标记也能打沉睡单位"，与 `control.go:111-131` 的原文实现相反——
// **是断言错了不是代码错了**。守卫把一个误会当场逮住，这正是它该有的样子。
func TestStealthFeedsDamageVsInvincible(t *testing.T) {
	other := notSelectable(tfHidden, true)
	if !other {
		t.Fatal("隐匿应算作 otherInvincibility")
	}
	// 有别的无敌理由 ⇒ 无论带不带标记都打不动。
	if got := damageVsInvincible(true, true, other); got != 0 {
		t.Fatalf("有 otherInvincibility 时应打不中，得到倍率 %v", got)
	}
	// 没有别的无敌理由 + 带"无视沉睡"标记 ⇒ 打得动。
	if got := damageVsInvincible(true, true, notSelectable(0, true)); got != 1 {
		t.Fatalf("无 otherInvincibility 且带标记时应打中，得到倍率 %v", got)
	}
	// 没有别的无敌理由 + **不带**标记 ⇒ 打不动（沉睡单位的保护）。
	if got := damageVsInvincible(true, false, notSelectable(0, true)); got != 0 {
		t.Fatalf("不带标记时不应打中沉睡单位，得到倍率 %v", got)
	}
}
