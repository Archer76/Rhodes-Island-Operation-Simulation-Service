package main

import (
	"math"
	"testing"
)

// 【阻止攻击/阻止能力/阻止移动】三张清单 ＋【战栗】【沉睡】【浮空】的守卫。
// 判据出处与原文都抄在 `control.go` 的文件头。
//
// 这一批的价值主要在**清单本身**：它们是所有控制类机制共同consult的判据，
// 抄错一项不会报错，只会让某一类状态静默地管不住人（或管得太多）。

// 清单必须**逐项相等**，不能用"包含"去测——多一项少一项都是错的。
func TestAbnormalFlagListsAreExact(t *testing.T) {
	cases := []struct {
		name  string
		mask  abnormalFlag
		items []abnormalFlag
	}{
		{"阻止攻击（8项）", maskBlocksAttack, []abnormalFlag{
			flagStun, flagUnableAction, flagLevitate, flagFrozen,
			flagPalsyShake, flagDisarm, flagForceDisarm, flagAsleep}},
		{"阻止能力（6项）", maskBlocksAbility, []abnormalFlag{
			flagStun, flagUnableAction, flagLevitate, flagFrozen,
			flagPalsyShake, flagAsleep}},
		{"阻止移动（4项）", maskBlocksMove, []abnormalFlag{
			flagBind, flagSelfBind, flagFrozen, flagLevitate}},
	}
	for _, c := range cases {
		var want abnormalFlag
		for _, f := range c.items {
			want |= f
		}
		if c.mask != want {
			t.Fatalf("%s 清单不符：\n  得 %016b\n  期 %016b", c.name, c.mask, want)
		}
		// 反向：清单**不得**包含未列出的位
		for _, f := range []abnormalFlag{flagStun, flagUnableAction, flagLevitate,
			flagFrozen, flagPalsyShake, flagDisarm, flagForceDisarm, flagAsleep,
			flagSleeping, flagBind, flagSelfBind} {
			listed := false
			for _, it := range c.items {
				if it == f {
					listed = true
				}
			}
			if !listed && c.mask&f != 0 {
				t.Fatalf("%s 清单里多了未列出的项 %016b", c.name, f)
			}
		}
	}
}

// 三张清单**不是**子集关系——这条要是被"优化"成层层包含，行为就变了。
func TestFlagListsAreNotNested(t *testing.T) {
	if maskBlocksMove&maskBlocksAttack == maskBlocksMove {
		t.Fatal("阻止移动不该是阻止攻击的子集：束缚/自缚只在移动那张表里")
	}
	if maskBlocksAbility&maskBlocksAttack != maskBlocksAbility {
		t.Fatal("阻止能力应是阻止攻击的子集（8 项里有 6 项重合）")
	}
	// 晕眩/无法行动/麻痹震颤让人动不了，但**不属于**阻止移动
	for _, f := range []abnormalFlag{flagStun, flagUnableAction, flagPalsyShake} {
		if maskBlocksMove&f != 0 {
			t.Fatalf("%016b 不该出现在阻止移动清单里（原文专门点过这条）", f)
		}
	}
}

func TestDisarmIgnoredWhenInvincibleButForceDisarmIsNot(t *testing.T) {
	// 「缴械（持有无敌情况下忽略）」
	if blocksAttack(flagDisarm, true) {
		t.Fatal("持有无敌时缴械应被忽略")
	}
	if !blocksAttack(flagDisarm, false) {
		t.Fatal("没有无敌时缴械应当生效")
	}
	// ⚠ 强制缴械没有那个括号
	if !blocksAttack(flagForceDisarm, true) {
		t.Fatal("强制缴械在无敌下**仍然生效**（原文的括号只挂在缴械上）")
	}
}

func TestTrembleNotInTheAttackList(t *testing.T) {
	// 原文明说战栗"不属于上述八者，因此不会影响此检查"
	if maskBlocksAttack&flagStun == 0 {
		t.Fatal("前置：晕眩应在清单里（否则本测试失去意义）")
	}
	if !blocksAttack(flagStun, false) || !blocksAttack(flagStun, true) {
		t.Fatal("晕眩应无条件阻止攻击")
	}
}

func TestTrembleBlocksAttackOnlyWhileBlocking(t *testing.T) {
	if trembleBlocksAttack(false, true) {
		t.Fatal("没有战栗时，被阻挡照样能攻击")
	}
	if trembleBlocksAttack(true, false) {
		t.Fatal("战栗只在**被阻挡**时禁普攻——没被阻挡就该照常打")
	}
	if !trembleBlocksAttack(true, true) {
		t.Fatal("战栗＋被阻挡 ⇒ 无法触发普通攻击")
	}
}

func TestSleepingFlagsAndSleepIsNotNap(t *testing.T) {
	// 原文：「无法行动+无敌+不可阻挡」——注意工具页词典少了"不可阻挡"
	if maskSleeping&flagUnableAction == 0 {
		t.Fatal("沉睡应包含无法行动")
	}
	// 「因为小睡不是沉睡，无视沉睡的伤害也无法影响小睡单位」——两者必须是不同的位
	if flagAsleep == flagSleeping {
		t.Fatal("小睡与沉睡必须分开：同名不同义")
	}
	if flagAsleep&maskSleeping != 0 {
		t.Fatal("小睡不该落进沉睡的标记里")
	}
	// 沉睡本身不在"阻止攻击"清单里；它靠携带的【无法行动】进那一列
	if maskBlocksAttack&flagSleeping != 0 {
		t.Fatal("清单里列的是【无法行动】，不是【沉睡】本身")
	}
	if !blocksAttack(maskSleeping, false) {
		t.Fatal("沉睡（带着无法行动）应能被判为阻止攻击")
	}
}

func TestCanDamageSleepingTarget(t *testing.T) {
	// 两级判据：先问"拿掉沉睡还有没有别的无敌理由"，再问"这一击带不带那个标记"
	if canDamageSleepingTarget(true, true) {
		t.Fatal("还有别的无敌理由时，无视沉睡也打不动")
	}
	if !canDamageSleepingTarget(true, false) {
		t.Fatal("没有别的理由且带标记 ⇒ 可以打")
	}
	if canDamageSleepingTarget(false, false) {
		t.Fatal("不带标记就打不动")
	}
	if damageVsInvincible(true, true, false) != 1 {
		t.Fatal("倍率形式应与谓词一致")
	}
	if damageVsInvincible(true, false, false) != 0 {
		t.Fatal("倍率形式应与谓词一致（打不动⇒0）")
	}
	if damageVsInvincible(false, true, false) != 0 {
		t.Fatal("非沉睡目标不适用本条（没有放行依据）")
	}
}

// ★ 这一组是**订正**第 6 轮那版写的守卫用的。旧版三条守卫当时全绿，但相对
// `行动方式` 整页原文漏了三处：遗漏"已持有浮空也不能再施加"、遗漏缚地镜像、
// 重量减半只做一次（原文两样都有要累乘到四分之一）。
// 保留此注释是为了记住：**正例守卫全绿不等于实现对。**
func TestLevitateBuffAppliesThreeConditions(t *testing.T) {
	// 地面、既无浮空也无缚地 ⇒ 可施加
	if !levitateBuffApplies(false, false, false, false) {
		t.Fatal("地面单位、无浮空无缚地 ⇒ 浮空 Buff 可施加")
	}
	// ① 行动类型（数据）为飞行 ⇒ 不可施加
	if levitateBuffApplies(true, false, false, false) {
		t.Fatal("行动类型为飞行的单位无法被施加浮空Buff")
	}
	// ①的例外：持有缚地异常 ⇒ 可施加（允许"抵消"）
	if !levitateBuffApplies(true, false, true, false) {
		t.Fatal("飞行单位但持有缚地 ⇒ 可无视，允许施加浮空")
	}
	// ★② 已持有浮空异常 ⇒ 不可施加（旧版漏了这条）
	if levitateBuffApplies(false, true, false, false) {
		t.Fatal("已持有浮空异常的单位无法被施加浮空Buff")
	}
	// ②的例外一：持有缚地 ⇒ 可施加
	if !levitateBuffApplies(false, true, true, false) {
		t.Fatal("已持有浮空但持有缚地 ⇒ 允许「抵消」式施加")
	}
	// ②的例外二：本 Buff 携带浮空强化 ⇒ 可无视"已持有浮空"这一条
	if !levitateBuffApplies(false, true, false, true) {
		t.Fatal("携带浮空强化的 Buff 可无视「已持有浮空」这一条限制")
	}
	// ★ 但浮空强化**只**免那一条，不免"行动类型为飞行"
	if levitateBuffApplies(true, false, false, true) {
		t.Fatal("浮空强化不免「行动类型为飞行」这一条——原文那句限制只点了后一条")
	}
}

func TestGroundBuffAppliesIsTheMirror(t *testing.T) {
	// 「行动类型（数据）不为飞行的单位……无法被施加缚地Buff」
	if groundBuffApplies(false, false, false, false) {
		t.Fatal("地面单位无法被施加缚地Buff")
	}
	// 例外：持有浮空异常 ⇒ 可施加
	if !groundBuffApplies(false, true, false, false) {
		t.Fatal("地面单位但持有浮空 ⇒ 允许施加缚地以「抵消」")
	}
	// 飞行单位 ⇒ 可施加
	if !groundBuffApplies(true, false, false, false) {
		t.Fatal("飞行单位可被施加缚地Buff")
	}
	// 「已持有缚地异常的单位无法被施加缚地Buff」
	if groundBuffApplies(true, false, true, false) {
		t.Fatal("已持有缚地异常的单位无法被再施加缚地Buff")
	}
	// ⚠ 「缚地强化」这一项在 `行动方式` 页**未见记载**（页里只写了浮空强化），
	// 所以这里只钉"传了也要走已持有缚地那一条"以外的取证过的行为，不臆造镜像条款。
	if !groundBuffApplies(true, true, true, false) {
		t.Fatal("飞行＋持有浮空与缚地 ⇒ 允许（浮空那条例外仍在）")
	}
}

func TestHeavyDurationIsMultiplicative(t *testing.T) {
	// 重量**高于 3** 才减半：恰好 3 不减
	if got := heavyDuration(10, 3, true, false); math.Abs(got-10) > 1e-12 {
		t.Fatalf("重量恰好 3 不减半（阈值是「高于3」），得到 %v", got)
	}
	if got := heavyDuration(10, 3.0001, true, false); math.Abs(got-5) > 1e-12 {
		t.Fatalf("重量高于 3 且带浮空 ⇒ 减半，得到 %v", got)
	}
	// ★ 两个异常都有 ⇒ 累乘至**四分之一**（旧版只减半一次，正是漏在这）
	if got := heavyDuration(10, 4, true, true); math.Abs(got-2.5) > 1e-12 {
		t.Fatalf("浮空与缚地都有 ⇒ 累乘至四分之一，得到 %v", got)
	}
	// 带缚地单独也减半
	if got := heavyDuration(10, 4, false, true); math.Abs(got-5) > 1e-12 {
		t.Fatalf("只带缚地 ⇒ 减半，得到 %v", got)
	}
	// 两个都不带 ⇒ 不减（原文限于"当施加的Buff中包含浮空或缚地异常效果时"）
	if got := heavyDuration(10, 4, false, false); math.Abs(got-10) > 1e-12 {
		t.Fatalf("不带浮空也不带缚地 ⇒ 不减，得到 %v", got)
	}
	// 低重量即使两个都有也不减
	if got := heavyDuration(10, 2, true, true); math.Abs(got-10) > 1e-12 {
		t.Fatalf("重量不高于 3 ⇒ 不减，得到 %v", got)
	}
}

func TestAirStateAfterStack(t *testing.T) {
	// 比数量
	if airStateAfterStack(false, 2, 1) != airFlying {
		t.Fatal("浮空Buff数多 ⇒ 浮空状态")
	}
	if airStateAfterStack(true, 1, 2) != airGround {
		t.Fatal("缚地Buff数多 ⇒ 缚地状态")
	}
	// ★ 数量相等时看**原本**是什么单位
	if airStateAfterStack(true, 1, 1) != airFlying {
		t.Fatal("数量相等且原本是飞行单位 ⇒ 浮空")
	}
	if airStateAfterStack(false, 1, 1) != airGround {
		t.Fatal("数量相等且原本是地面单位 ⇒ 缚地")
	}
	// 一个都没有时也走"相等"那一支 ⇒ 保持原本
	if airStateAfterStack(true, 0, 0) != airFlying {
		t.Fatal("没有任何浮空/缚地Buff的飞行单位应保持飞行")
	}
	if airStateAfterStack(false, 0, 0) != airGround {
		t.Fatal("没有任何浮空/缚地Buff的地面单位应保持地面")
	}
}
