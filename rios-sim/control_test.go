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

func TestLevitateAppliesAndWeightHalving(t *testing.T) {
	// 取消条件：**单位数据上为飞行单位** 且 **不持有缚地**
	if levitateApplies(true, false) {
		t.Fatal("飞行单位且无缚地 ⇒ 浮空 Buff 取消")
	}
	if !levitateApplies(true, true) {
		t.Fatal("飞行单位但持有缚地 ⇒ 可以浮空")
	}
	if !levitateApplies(false, false) {
		t.Fatal("地面单位 ⇒ 可以浮空")
	}

	// 重量**大于 3** 才减半；恰好 3 不减
	if got := levitateDuration(10, 3); math.Abs(got-10) > 1e-12 {
		t.Fatalf("重量恰好 3 不减半（阈值是「大于3」），得到 %v", got)
	}
	if got := levitateDuration(10, 3.0001); math.Abs(got-5) > 1e-12 {
		t.Fatalf("重量大于 3 应减半，得到 %v", got)
	}
	if got := levitateDuration(10, 4); math.Abs(got-5) > 1e-12 {
		t.Fatalf("重量大于 3 应减半，得到 %v", got)
	}
}
