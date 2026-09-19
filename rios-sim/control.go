package main

// 【阻止攻击 / 阻止能力 / 阻止移动】三张清单 ＋【战栗】【沉睡】【浮空】三条机制。
//
// 判据出处：PRTS `异常效果` 页（2026-09-19 抓取）。三张清单是该页原文小节，
// 逐字抄在下面——**它们不是子集关系**，别按"一个比一个宽"去猜：
//
//	「"阻止攻击类异常效果"指的是在处理单位"能否攻击或阻挡攻击？"（get_canUseAtkOrCbt）
//	  方法时检查的八个异常效果：晕眩、无法行动、浮空、冻结、麻痹震颤、缴械
//	  （持有无敌情况下忽略）、强制缴械、小睡」
//	「"阻止能力类异常效果"……六个：晕眩、无法行动、浮空、冻结、麻痹震颤、小睡」
//	「"阻止移动类异常效果"……四个：束缚、自缚、冻结、浮空」
//
// ⚠ 两个反直觉点（都配了守卫）：
//  1. **战栗不在"阻止攻击"那八项里**。页里专门点了一句：「战栗虽然能在实质上阻止
//     敌方单位在阻挡状态下发动攻击，但不属于上述八者，因此**不会影响此检查**」。
//     所以它不是"八项之一"，而是一条**条件成立才生效**的独立机制（见战栗那一段）。
//  2. **缴械在"持有无敌情况下忽略"**——而**强制缴械没有这个括号**。两者写法相邻，
//     照抄时极易一视同仁。
//
// ⚠ 「晕眩、无法行动、麻痹震颤同样因切换状态机而让单位无法移动，但不属于
//   [阻止移动] 此类效果」——所以"实际动不了"与"被判为阻止移动"是两件事。

// abnormalFlag 是一条异常效果。用位图是因为三张清单要按集合算，且清单之间不是包含关系。
type abnormalFlag uint16

const (
	flagStun         abnormalFlag = 1 << iota //: 晕眩 STUN
	flagUnableAction                          //: 无法行动 UNABLE_ACTION
	flagLevitate                              //: 浮空 LEVITATE
	flagFrozen                                //: 冻结 FROZEN
	flagPalsyShake                            //: 麻痹震颤 PALSYING
	flagDisarm                                //: 缴械 DISARMED
	flagForceDisarm                           //: 强制缴械 FORCE_DISARMED
	flagAsleep                                //: 小睡 ASLEEP
	flagSleeping                              //: 沉睡 SLEEPING
	flagBind                                  //: 束缚 BIND
	flagSelfBind                              //: 自缚
)

// 三张清单，逐字照原文列名。
const (
	//: 「能否攻击或阻挡攻击？」——八个（缴械的例外在 blocksAttack 里处理）
	maskBlocksAttack = flagStun | flagUnableAction | flagLevitate | flagFrozen |
		flagPalsyShake | flagDisarm | flagForceDisarm | flagAsleep
	//: 「能否使用能力？」——六个
	maskBlocksAbility = flagStun | flagUnableAction | flagLevitate | flagFrozen |
		flagPalsyShake | flagAsleep
	//: 「能否移动？」——四个（注意它含束缚/自缚，不含晕眩/无法行动/麻痹震颤）
	maskBlocksMove = flagBind | flagSelfBind | flagFrozen | flagLevitate
)

// blocksAttack 是"能否攻击或阻挡攻击？"这一检定的判据。
//
// `invincible` 用来兑现原文那个括号：「缴械（**持有无敌情况下忽略**）」。
// ⚠ 只忽略**缴械**，不忽略**强制缴械**——两者在原文里是并列的两项，括号只挂在前面那个。
func blocksAttack(flags abnormalFlag, invincible bool) bool {
	f := flags
	if invincible {
		f &^= flagDisarm
	}
	return f&maskBlocksAttack != 0
}

// blocksAbility 是"能否使用能力？"的判据。
func blocksAbility(flags abnormalFlag) bool { return flags&maskBlocksAbility != 0 }

// blocksMove 是"能否移动？"的判据。
func blocksMove(flags abnormalFlag) bool { return flags&maskBlocksMove != 0 }

// ---- 战栗（DISARMED_COMBAT）----
//
// 原文：「若状态机处于 COMBAT 则无法触发普通攻击
//
//	※打断当前正在进行的普通攻击的效果为相关Buff操控，非异常效果战栗本身的效果
//	※其他普通攻击行为（如替换攻击的技能）同样无法进行」
//
// 即：**"被阻挡"是条件**，不是无条件禁攻。`blocking` 就是"状态机是否处于 COMBAT"。
//
// ⚠ 上面那句"打断是 Buff 操控、不是战栗本身的效果"要落到实现上：
// `trembleBlocksAttack` 只回答"这一击能不能出手"，**不负责取消已经出手的那一击**；
// 取消是施加方的 Buff 行为，混在一起写会让"谁打断的"无从归因。
func trembleBlocksAttack(trembling, blocking bool) bool {
	return trembling && blocking
}

// ---- 沉睡（SLEEPING）----
//
// 原文：「无法行动+无敌+不可阻挡」。
//
// ⚠ 工具页的 tooltip 词典只写了「无敌且无法行动」——**漏了"不可阻挡"**。
// 以本页为准（同族差异在本项目里已出现过多次：沉睡、冻结、元素损伤都是）。
const maskSleeping = flagUnableAction | flagSleeping // 语义标记：沉睡带来的"无法行动"

// canDamageSleepingTarget 报告"这一次伤害能不能落在一个处于【无敌】的目标身上"。
//
// 原文（`异常效果` 页 §7「可影响沉睡单位的伤害」）：
//
//	「部分干员的伤害可以"无视沉睡"，其逻辑本质上是让自己的伤害具有 8 号 SharedFlag
//	  （即 DAMAGE_CAN_HURT_SLEEPING_ENTITY）。
//	  单位在处理目标无敌异常效果所带来的"无法受到伤害与元素损伤效果"时，会**先判定**
//	  "假定目标具有沉睡免疫的情况下，是否仍具有无敌/隐匿/不可选中/塔不可选中之一"。
//	  若通过，视为"即使无视沉睡也无法造成伤害"，因而不论是否具有该 SharedFlag 伤害都会被归零；
//	  若未通过，则可因上述 SharedFlag 而"无视无敌"造成伤害。」
//
// 所以判据是**两级**的：先问"拿掉沉睡还剩不剩别的无敌理由"，再问"这一击带不带那个标记"。
//
// `otherInvincibility` = "假定目标有沉睡免疫时，是否仍持有无敌/隐匿/不可选中/塔不可选中
// 之一"。原文另记：「目标处于出场/部署/消失状态机中会**自动通过**这一判定」——
// 即那三种状态要算进 `otherInvincibility`（通过 ⇒ 打不动）。
func canDamageSleepingTarget(sourceIgnoresSleep, otherInvincibility bool) bool {
	if otherInvincibility {
		return false
	}
	return sourceIgnoresSleep
}

// damageVsInvincible 是上面那条判据的"倍率"形式：能打中返回 1，打不中返回 0。
//
// `sleeping` 为假时**不适用本判据**：这里的上下文是"目标已经被判为无敌"，
// 沉睡只是"有没有那个可以无视它的标记"的来源。非沉睡的无敌同样走这一支，
// 区别只在 `sourceIgnoresSleep` 的取值来源（沉睡是干员的 8 号标记）。
func damageVsInvincible(sleeping, sourceIgnoresSleep, otherInvincibility bool) float64 {
	if !sleeping {
		return 0 // 非沉睡的无敌：本条不给出放行
	}
	if canDamageSleepingTarget(sourceIgnoresSleep, otherInvincibility) {
		return 1
	}
	return 0
}

// ---- 浮空（LEVITATE）----
//
// 原文：「敌人类单位状态机尝试切换至 LEVITATE（该状态机下持有
// **不可阻挡＋失衡免疫＋缴械**异常效果，且**无法移动**），尝试让其他机制将单位视为
// **飞行单位**。
// 施加的Buff包含浮空异常将被视为浮空Buff：若单位数据上为**飞行单位**且**不持有缚地**
// 异常则 Buff **取消**，而若其**重量大于3** 则 Buff **时间将减半**。」
//
// ⚠ 所以"浮空"不是"飘起来"这么简单：它一次改三件事——阻挡关系（不可阻挡＋被视作飞行
// 单位）、失衡免疫、以及缴械（禁普攻）。而作用面还要看**单位自身**是地面还是飞行。

// : 浮空状态下单位持有的异常效果组合（原文那句括号）。
const maskLevitateState = flagLevitate

// levitateApplies 报告"这一次浮空 Buff 能不能挂上"。
//
// 原文的取消条件是连着的两个：**单位数据上为飞行单位** 且 **不持有缚地异常**。
// 缚地（GROUNDED）会"尝试让其他机制将单位视为地面单位"，正好与浮空相反，故能救回来。
func levitateApplies(unitIsFlying, hasBindGround bool) bool {
	return !(unitIsFlying && !hasBindGround)
}

// levitateDuration 给浮空 Buff 的时长：**重量大于 3 的减半**。
//
// ⚠ 阈值是**严格大于 3**（"重量大于3"），重量恰好为 3 的单位**不减半**——
// 这种"边界差一个"的写法在本项目里已经栽过（攻速下限 10 对 20），故单列守卫。
func levitateDuration(base float64, weight float64) float64 {
	if weight > 3 {
		return base * 0.5
	}
	return base
}
