package main

// 可选性（隐匿 / 迷彩 / 无法选择类效果）——**这一层原先在 Go 里不存在**。
//
// ── 取证（2026-09-19，PRTS `异常效果` 页 raw wikitext，客户端 2.7.61）──
//   · 隐匿 = `INVISIBLE(9)`：「无法被不同阵营选中（属于**无法选择**类效果）」
//     并且原文明确：「*隐匿与"阻挡时解除"没有直接关系，该机制通常由其他效果实现*」
//     ⇒ 词典 tooltip 那句「不阻挡时不成为敌方攻击目标」**不是**它的定义（本文件按原文实现）。
//   · 迷彩 = `CAMOUFLAGE(17)`：「无法被对立阵营的**部分能力和部分弹道**选中；会因隐匿免疫而失效，
//     但在因隐匿免疫而失效的情况下依旧能被检测到」
//     「※由特殊逻辑实现，**不属于**"无法选择"效果」
//     「※所有光环类能力、以及涉及中点判定/格子判定的效果均**不受**迷彩制约」
//   · 「无法选择类异常效果」= `get_targetFree` 检查的**五个**：
//     **隐匿、不可选中、无敌、塔不可选中、对地规避**（索敌者行动方式不为地面时忽略）。
//     「可选性效果」= 上面五个 + 禁疗 + 孤立；**不包括迷彩**。
//   · 反隐（隐匿免疫）：「持有隐匿免疫的单位，身上的迷彩效果会失效。不过其与迷彩免疫不同，
//     **无法真正阻止其他机制对迷彩的检测**，因此同时具有隐匿免疫与迷彩的单位
//     会被部分非索敌能力认为"具有可正常生效的迷彩"。」
//   · 「对于敌方而言，只要被阻挡，就会无视隐匿/不可选中/迷彩/无敌等影响可选性的能力进行强制攻击。」
//     （`作战机制` 页）
//
// ── 两条最容易被做错的，都在这里显式建模 ──
//   ① **迷彩与隐匿不是同一处判**：隐匿在 `get_targetFree` 的五个里，迷彩**不在**。
//      把迷彩塞进同一张掩码，会让"光环/格子/中点"这类本该无视迷彩的效果被拦掉。
//   ② **反隐让迷彩"失效"但不让迷彩"消失"**：选择看不见它，检测仍看得见它。
//      合成一个布尔就会把这两种问法答成同一个答案。
//
// ── 刻意不做的：本层只管"能不能被选中/被什么选中"，不改任何伤害数值 ──
// 伤害是否吃到无敌，仍由既有 `damageVsInvincible` 判——本层提供它的那个输入
//（`notSelectable` 的结果正是原文说的"是否仍持有无敌/隐匿/不可选中/塔不可选中之一"）。

// targetFree 是**无法选择类异常效果**的掩码（原文 `get_targetFree` 查的那五个）。
type targetFree uint8

const (
	tfHidden       targetFree = 1 << iota //: 隐匿 INVISIBLE(9)
	tfUntargetable                        //: 不可选中 TARGET_FREE(2)
	tfInvincible                          //: 无敌 INVINCIBLE(5)
	tfTowerFree                           //: 塔不可选中 TOWER_TARGET_FREE(32)
	tfGroundFree                          //: 对地规避 MOTION_TARGET_FREE(35)
)

// selectorKind 是"谁来选"——因为迷彩对不同的选取方式答案不同（原文列的例外）。
type selectorKind uint8

const (
	selAbility    selectorKind = iota //: 普通能力选取（受迷彩制约）
	selProjectile                     //: 弹道选取（受迷彩制约）
	selAura                           //: 光环类能力（原文：不受迷彩制约）
	selCell                           //: 涉及格子判定的效果（原文：不受迷彩制约）
	selMidpoint                       //: 涉及中点判定的效果（原文：不受迷彩制约；溅射属此类）
)

// selectorIsGround 报告索敌者的行动方式是不是地面。
//
// 它只影响**对地规避**这一条：原文写「对地规避（索敌者行动方式不为地面的情况下忽略）」。
// 「所有角色类单位的行动方式均为地面，无论其模型表现如何」（同页）——
// 所以浮空干员**仍然**是地面索敌者，这条不能靠"看起来在天上"判。
func camouflageApplies(k selectorKind) bool {
	switch k {
	case selAura, selCell, selMidpoint:
		return false
	}
	return true
}

// notSelectable 回答"不同阵营能否选中它"——即原文的 `get_targetFree`。
//
// `selectorGround` = 索敌者的行动方式是否为地面（只影响对地规避）。
// ⚠ **迷彩不在这里**，这是原文的分工，不是漏写。
func notSelectable(f targetFree, selectorGround bool) bool {
	f &^= 0 // 保持纯函数语义（不就地改调用方的值）
	if f&tfGroundFree != 0 && !selectorGround {
		f &^= tfGroundFree // 索敌者是空中 ⇒ 对地规避被忽略
	}
	return f&(tfHidden|tfUntargetable|tfInvincible|tfTowerFree|tfGroundFree) != 0
}

// selectableFrom 是 above 的"我方视角"包装：默认索敌者是地面单位
// （「所有角色类单位的行动方式均为地面」）。
func selectableFrom(f targetFree) bool { return !notSelectable(f, true) }

// camouflageBlocks 回答"迷彩能不能挡住这一次选取"。
//
// `hasAntiStealth` = 该单位是否处在隐匿免疫（反隐）效果下。
func camouflageBlocks(k selectorKind, hasAntiStealth bool) bool {
	if hasAntiStealth {
		return false // 反隐 ⇒ 迷彩失效（但"能不能被检测到"不受影响，见 camouflageDetectable）
	}
	if !camouflageApplies(k) {
		return false // 光环 / 格子 / 中点判定本就不受迷彩制约
	}
	return true
}

// camouflageDetectable 回答的是**另一个问题**：「其他机制还能不能检测到它身上有迷彩」。
//
// ★ 这一条是原文里最容易被合成一个布尔的那句：
//
//	「…无法真正阻止其他机制对迷彩的检测，因此同时具有隐匿免疫与迷彩的单位
//	  会被部分非索敌能力认为"具有可正常生效的迷彩"」。
//	所以：**反隐不改变本函数的返回值**。它与 `camouflageBlocks` 是两个问法。
func camouflageDetectable(hasCamouflage bool) bool { return hasCamouflage }

// antiStealthSuppresses 施加反隐（隐匿免疫）后**用于选择判定**的那张掩码。
//
// 原文：「"解除隐匿"本质上是使敌方获得一个反隐 Buff，其隐匿、迷彩效果会因此失效。」
// ⇒ 选择判定层面：隐匿与对地规避之外的"看不见"效果一并失效，但**无敌仍在**
// （无敌不是"看不见"，它是免伤；反隐不解除它）。
func antiStealthSuppresses(f targetFree) targetFree {
	return f &^ (tfHidden | tfUntargetable | tfTowerFree | tfGroundFree)
}

// blockingOverridesSelection 是被阻挡时的强制攻击规则（`作战机制` 页）：
// 「对于敌方而言，只要被阻挡，就会无视隐匿/不可选中/迷彩/无敌等影响可选性的能力进行强制攻击。」
//
// ⚠ 只对**敌方**成立（原文限定"对于敌方而言"）；我方近战被阻挡时的优先索敌是另一条规则
// （「我方索敌优先级：阻挡（近战限定）…」），别拿这一条去改我方。
func blockingOverridesSelection(blocked bool) bool { return blocked }

// TraceSelection 打一行 `SEL` 痕迹。
//
// 键值形状与 `ELEM`/`FRAGILE` 一致，`tools/trace_kv.py` 是唯一解析入口。
// 为什么选取也要留痕：**没被选中**这件事在别处不会留下任何痕迹——
// 一支箭飞过去没打中任何东西，在伤害/命中痕迹里是"什么都没发生"，
// 与"本来就没有目标"无法区分（记忆 223402c9 那一类假信号）。
func TraceSelection(t float64, who, target string, f targetFree, k selectorKind,
	hasAnti bool, blocked bool, picked bool) {
	if !picked && f == 0 && !blocked {
		return // 什么都没拦、也没选上：不是本层造成的，别打噪声
	}
	trace("SEL t=%.4f who=%s target=%s flags=%d kind=%d anti=%t blocked=%t picked=%t",
		t, who, target, uint8(f), uint8(k), hasAnti, blocked, picked)
}
