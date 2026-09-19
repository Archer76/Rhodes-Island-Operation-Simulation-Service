package main

import "math"

// 【麻痹】与【麻痹震颤】——"层数换打断"的机制。
//
// 判据出自**两处，分工不同，缺一条就会写歪**：
//
// ① PRTS `异常效果` 页（PALSY 序号 39 / PALSYING 序号 40）给的是**时机与状态机**：
//
//	「敌人类单位在进行普通攻击动作期间，**即将攻击的瞬间**或**动作开始一定时间
//	  （默认2秒）后**获得 **0.5s 麻痹震颤**。状态机尝试切换至 PALSY
//	  （**无法攻击、释放技能**）。
//	  ※通常由异常效果麻痹机制添加的BUFF携带**以打断本次普通攻击**。
//	  ※此异常效果相关机制主要由Buff实现，并非异常本身的效果。」
//
// ② `敌人一览/数据` 页的 tooltip 词典给的是**层数规则**（①里没有这一段）：
//
//	「**每层**麻痹可以使敌人在普通攻击时**打断本次攻击**，**上限3层**；
//	  麻痹**未被消耗时持续时间无限**，**拥有抵抗的单位每5秒流失1层**。」
//
// ⚠ 只读 ① 会把它写成"麻痹＝另一种晕眩"（一次性、按时长）；只读 ② 会漏掉
// "动作开始 2 秒后也会触发"这个第二个时机。两条合起来才是完整的。
//
// ⚠ 还有一处**作用面**容易漏：`麻痹震颤` 不只挡"攻击"，
// 站内技能正文里明记「其他普通攻击行为（如猎手装弹、秘术师储存能量）同样无法进行」——
// 即一切**普通攻击型行为**都被挡，不是只有造成伤害的那一下。
//
// ⚠ 对象是**敌人类单位**（①的原文如此）。

const (
	//: 麻痹层数上限（tooltip 词典：「上限3层」）。
	palsyMaxStacks = 3
	//: 每次触发打断时给多少秒【麻痹震颤】（`异常效果` 页：「0.5s 麻痹震颤」）。
	palsyShakeSecs = 0.5
	//: 普攻动作开始多久之后也算一个触发时机（页里「默认2秒」——原文写了"默认"，
	//: 说明可被覆盖，所以留成常量而不是硬写进判据里）。
	palsyWindupSecs = 2.0
	//: 「拥有抵抗的单位每5秒流失1层」里的那个 5 秒。
	palsyDecayBaseSecs = 5.0
)

// palsyState 是【麻痹】层数 ＋ 【麻痹震颤】计时器。
//
// 页里那句「此异常效果相关机制主要由Buff实现，并非异常本身的效果」，正是说这一族
// 在引擎里应当做成一个**挂在单位上的状态**，而不是一次性动作——所以这里是状态。
type palsyState struct {
	//: 剩余层数。**未被消耗时不清零**（"麻痹未被消耗时持续时间无限"）。
	stacks int
	//: 【麻痹震颤】剩余秒数；> 0 时该单位无法攻击、无法释放技能。
	shake float64
	//: 【麻痹免疫】：使自身的麻痹**失效**，但**不清除相关Buff**——即层数照记、
	//: 照显示，就是不触发打断。（`元素` 页：麻痹免疫「使自身的麻痹失效，但不会
	//: 清除相关Buff，获得3层麻痹」。）所以它是"是否生效"的开关，不是"有没有层"。
	immune bool
	//: 抵抗带来的"每 5 秒流失 1 层"计时器（只在有抵抗时累加）。
	decay float64
}

// add 叠加层数，**按上限截断**。n ≤ 0 时不动（别把"没有这条"写成"减一层"）。
//
// 免疫状态**不阻止记层**：原文明说免疫只是让麻痹失效、Buff 照挂在身上。
func (p *palsyState) add(n int) {
	if n <= 0 {
		return
	}
	p.stacks += n
	if p.stacks > palsyMaxStacks {
		p.stacks = palsyMaxStacks
	}
}

// active 报告"这一刻麻痹是否**生效**"：有层、且没有被免疫。
func (p *palsyState) active() bool { return p.stacks > 0 && !p.immune }

// canAttack 报告"这一刻能不能攻击／释放技能"。
//
// 只看震颤。⚠ 调用点要覆盖**一切普通攻击型行为**（含装弹、储能量这类非伤害行为），
// 不只是造成伤害的那一下——正文里明写了这一类也被挡。
func (p *palsyState) canAttack() bool { return p.shake <= 0 }

// interrupt 是"即将攻击的瞬间"这个时机的触发：消耗 1 层、进入（或续上）震颤，
// 返回 true 表示**本次普攻被打断**（调用方据此取消这一击）。
//
// 层数为 0、或处于麻痹免疫时返回 false 且**不消耗任何东西**——
// "没层数就不打断"与"打断了但没层数"是两件事。
func (p *palsyState) interrupt() bool {
	if !p.active() {
		return false
	}
	p.stacks--
	if palsyShakeSecs > p.shake {
		p.shake = palsyShakeSecs
	}
	return true
}

// windupReached 是第二个时机：普攻动作开始 `elapsed` 秒后，越过了页里那个
// "一定时间（默认2秒）"的阈值就该触发（同样是一次中断，由调用方走 interrupt）。
//
// 之所以单独给一个判据而不是写死进 interrupt：原文写的是"默认2秒"，
// 说明这是可被覆盖的参数；写死会让日后想改的人只能改判据。
func (p *palsyState) windupReached(elapsed float64) bool {
	return elapsed >= palsyWindupSecs
}

// tick 推进一秒内的状态：震颤倒计时 ＋ 抵抗者的层数流失。
//
// `resistFactor` 是[可抵抗状态生效时间倍率]（1.0 = 没有抵抗，0.5 = 抵抗减半），
// 走 `resist.go` 的同一套口径：**加速流逝**，所以"每 5 秒"在抵抗下变成 2.5 秒。
//
// ⚠ 震颤计时器**不**乘这个倍率：被抵抗的那一条原文说的是"麻痹等状态每5秒流失1层"，
// 加速的是**层数流失**，不是震颤那 0.5 秒的时长。这条如果写反，症状是震颤被砍半、
// 看起来"更弱"，不会报错。
//
// ⚠ 层数流失只在**有抵抗时**发生：没有抵抗的单位"未被消耗时持续时间无限"，
// 一个计时器跑到底也不该掉层。
func (p *palsyState) tick(dt, resistFactor float64) {
	if p.shake > 0 {
		p.shake = math.Max(0.0, p.shake-dt)
	}
	if resistFactor >= resistNone || p.stacks <= 0 {
		p.decay = 0
		return
	}
	p.decay += dt
	need := palsyDecayInterval(palsyDecayBaseSecs, resistFactor)
	for p.decay >= need && p.stacks > 0 {
		p.decay -= need
		p.stacks--
	}
}
