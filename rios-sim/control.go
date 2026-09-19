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

// ---- 浮空（LEVITATE）／缚地（GROUNDED）／近地悬浮／轨地滑行 ----
//
// 判据出处：PRTS **`行动方式` 页**（2026-09-19 抓取，原文存 tmp/prts/页-行动方式.txt）。
//
// ⚠ 这一节的**第一版只读了 `异常效果` 页里那一段**，结果写漏了三处——所以本轮把判据
// 的引用从"一句话"升级成整页原文，并把三处漏项都变成守卫：
//   ① 漏了「**已持有浮空异常**的单位也无法被施加浮空Buff」（只处理了"行动类型为飞行"）；
//   ② 漏了**缚地的镜像条件**；
//   ③ 重量减半只做了一次，而原文说**两样都有要累乘至四分之一**。
// 旧版那两条守卫当时全绿——**正例守卫全绿不等于实现对**，这三处正是靠读整页才暴露的。
//
// 原文要点：
//
//	「单位具有行动方式，有两种：地面 WALK 与飞行 FLY……地面单位会在遇到不可通行地块时
//	  绕道而行，而飞行单位通常不会。
//	  **注意，起飞的干员仍然是地面单位，不是飞行单位。**
//	  ===近地悬浮===
//	  近地悬浮指的是一类让地面单位行动方式变为飞行，但**寻路方式不变**的效果，与官方
//	  术语中所述的"无法阻挡或近战攻击"**没有任何关系**。处于近地悬浮状态的单位是真正的
//	  飞行单位，唯一的区别是仍会以地面单位的方式寻路……
//	  ===轨地滑行===
//	  与近地悬浮类似……让飞行单位行动方式变为地面，但寻路方式不变……
//	  ==浮空与缚地==
//	  浮空异常依靠"让单位进入浮空状态机"来控制单位；期间，单位会被**浮空与缚地以外的
//	  任何机制**视为飞行单位。缚地异常依靠"激活单位的缚地控制器"；期间，单位会被
//	  **浮空与缚地以外的任何机制**视为地面单位。
//	  行动类型（数据）为飞行的单位、以及**已持有浮空异常**的单位**无法被施加浮空Buff**。
//	  **若其持有缚地异常**，将可以无视上述条件……**若本次施加的Buff还携带浮空强化异常**，
//	  本次Buff将可以无视"已持有浮空异常"这一条限制。
//	  ===对高重量单位时间减半===
//	  当施加的Buff中包含浮空或缚地异常效果时，**不论目标是否持有相应免疫**，只要当前的
//	  重量属性**高于3**，本Buff的持续时间都将减半（**如果两个异常效果都有则会累乘至
//	  四分之一**）。由于直接对Buff的持续时间做手脚，**即使Buff期间单位的重量变化也无法
//	  影响Buff的持续时间**。
//	  ===浮空缚地叠加===
//	  当尝试将浮空单位缚地、或将缚地单位浮空时，单位的具体状态会取决于单位的浮空Buff
//	  数量与缚地Buff数量：> ⇒ 与只有浮空异常时一样变为浮空；< ⇒ 变为缚地；
//	  = ⇒ **原本是飞行单位的会变为浮空，原本是地面单位的会变为缚地**。
//	  一旦发生浮空缚地叠加，浮空与缚地的自不可叠加都会被"解除"来允许玩家进行"抵消"。」

// airKind 是"别的机制怎么看这个单位"的行动方式。
type airKind int

const (
	airGround airKind = iota //: 被当作地面单位
	airFlying                //: 被当作飞行单位
)

// levitateBuffApplies 报告"这一次**浮空**Buff 能不能挂上"。
//
// 不可施加的两种情形（原文并列，**不是一种**）：
//   - 行动类型（数据）为飞行；
//   - **已持有浮空异常**。
//
// 两种例外：
//   - 持有**缚地**异常 ⇒ 两条都可无视（允许玩家"抵消"）；
//   - 本 Buff 携带**浮空强化** ⇒ **只**无视"已持有浮空异常"那一条，
//     行动类型为飞行仍然挂不上（原文那句限制只点了后一条）。
func levitateBuffApplies(unitIsFlying, hasLevitate, hasGround bool, carriesForce bool) bool {
	if unitIsFlying && !hasGround {
		return false
	}
	if hasLevitate && !hasGround && !carriesForce {
		return false
	}
	return true
}

// groundBuffApplies 是上面那条的**镜像**（缚地 Buff）。
//
// ⚠ 上一版就是漏了这个镜像。原文：「行动类型（数据）**不为飞行**的单位、以及已持有
// 缚地异常的单位无法被施加缚地Buff；若其持有浮空异常，将可以无视上述条件」。
func groundBuffApplies(unitIsFlying, hasLevitate, hasGround bool, carriesForce bool) bool {
	if !unitIsFlying && !hasLevitate {
		return false
	}
	if hasGround && !hasLevitate && !carriesForce {
		return false
	}
	return true
}

// heavyDuration 实现「对高重量单位时间减半」。
//
// 规则：只要**当前重量高于 3**，且本次 Buff 带浮空和/或缚地，就**各减半一次**——
// 两个异常都有 ⇒ ×0.5×0.5 = **四分之一**。没带这两个异常则不减。
//
// ⚠ 两处容易写错：
//  1. 是**累乘**不是"减半一次"。上一版只减半一次，等于漏掉了四分之一那一档。
//  2. 判定用的是**施加时刻**的重量：原文「即使Buff期间单位的重量变化也无法影响Buff的
//     持续时间」——所以这个函数只在施加时调一次，之后不许按当前重量重算。
//     （这一点与"可抵抗状态生效时间倍率"相反：那个是逐帧乘进流逝速度的。）
//  3. 「不论目标是否持有相应免疫」——本函数**不看免疫**。
func heavyDuration(base, weight float64, carriesLevitate, carriesGround bool) float64 {
	if weight <= 3 {
		return base
	}
	out := base
	if carriesLevitate {
		out *= 0.5
	}
	if carriesGround {
		out *= 0.5
	}
	return out
}

// airStateAfterStack 实现「浮空缚地叠加」时单位最终是什么状态。
//
// 比数量：浮空多 ⇒ 浮空；缚地多 ⇒ 缚地；**相等** ⇒ 看单位**原本**是飞行还是地面
// （原本飞行取浮空，原本地面取缚地）。
//
// ⚠ 原文最后一句「当任意浮空Buff与缚地Buff结束时，单位的状态都会根据双方的数量发生
// 更新」被该页自己标了**（存疑）**。本函数给的是"按数量重算"这一读法，
// 调用方在实现"某个 Buff 结束"时请照这句存疑标注处理，不要当成已确证口径。
func airStateAfterStack(originallyFlying bool, levitateBuffs, groundBuffs int) airKind {
	switch {
	case levitateBuffs > groundBuffs:
		return airFlying
	case levitateBuffs < groundBuffs:
		return airGround
	default:
		if originallyFlying {
			return airFlying
		}
		return airGround
	}
}

// ⚠ 本文件**不含**近地悬浮／轨地滑行与起飞：三者口径已取证（原文存
// tmp/prts/页-行动方式.txt），但按项目经理通告 #2 三.1「停止新增内核」，
// P4 剩余条目挂起，等接线清零到一半再续。取证结论已写进
// `docs/mechanics-dictionary.md`，续做时不必重新抓页。
//
// ⚠ 那句「**注意，起飞的干员仍然是地面单位，不是飞行单位**」也一并登记在文档里：
// 起飞**不改行动方式**，它只改阻挡与被攻击关系，别把它当成浮空的一种。
