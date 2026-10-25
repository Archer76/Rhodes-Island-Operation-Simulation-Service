package main

import (
	"math"
)

// logos_runtime.go：逻各斯（char_4133_logos）在主战斗循环里的状态与机制内核。
//
// 分工：
//
//   - `logos_spec.go`   只存 gamedata 原文（证据链）；
//   - `logos_config.go` 把原文解析成强类型字段（黑板书）；
//   - **本文件**是运行期：天赋二「剜魂具辞」的减益、技能一「殁亡」的斩杀、
//     技能二「提喻」的锁定多段伤害与减速、技能三「延异视阈」的多目标与范围；
//   - `logos_sim_tick.go` 是帧内驱动（`logosTick`）。
//
// ⚠ **不做近似、不掷骰子**。本文件里没有任何 `rand`：判决要可重复，所以凡
// 「随机目标」一律落成**确定性次序**，并把该口径登记进 `Unresolved` 待证。
//
// ⚠ 概率类机制（第一天赋「语汇演化」的 `prob`）属 roadmap 第六节 **V-2**
// 「概率机制的结果语义」待裁定项，**不折成期望值**，在 `mechanism_gaps.go`
// 里作为具名 Gap 拒判——这条是博士 2026-10-24 的裁定，不是本文件的选择。

// LogosBattleState 是一名场上逻各斯的可变状态。
//
// 它只装**跨帧**的东西：技能档位的静态数值留在 `Config` 里（部署时解一次），
// 逐帧变化的锁定目标、层数与计时器在这里。
type LogosBattleState struct {
	Config *LogosRuntimeConfig

	// ---- 技能二「提喻」的锁定状态 ----
	// Locked 是当前锁定的目标。**同一帧内不重选**：正文写「锁定」，
	// 每次出手都重挑会让层数永远回到 0（等于没建模）。
	Locked *enemy
	// S2Stack 是「对相同目标的伤害逐渐提高」的层数，上限 `attack@max_stack_cnt`。
	S2Stack int
	// S2Timer 是距下一次锁定伤害的累计秒数（`attack@cooldown` 一拍）。
	S2Timer float64

	// ---- 技能一「殁亡」的斩杀计数（判决留痕用） ----
	S1Kills int
	// ---- 技能二的锁定伤害笔数 ----
	S2Ticks int
	// ---- 天赋二「剜魂具辞」的施加次数 ----
	T2Applied int
}

func newLogosBattleState(cfg *LogosRuntimeConfig) *LogosBattleState {
	return &LogosBattleState{Config: cfg}
}

// reset 把逐帧状态清零——技能结束/被打断时调用（正文：「被打断或目标倒下时
// 重新索敌且效果重置」；技能结束当然更要重置）。
func (s *LogosBattleState) reset() {
	if s.Locked != nil {
		// 解除减速：层数撤销时要把它挂在那只敌人身上的乘区一并清掉。
		s.Locked.logosMoveDown = 0
	}
	s.Locked = nil
	s.S2Stack = 0
	s.S2Timer = 0
}

// ---------------------------------------------------------------- 天赋二

// enemyCellOf 把敌人的浮点位置折成整数格。
//
// ⚠ 折法与 `pickTargets` 一致（`math.RoundToEven`）：同一次判定里两处用两种
// 取整，"范围里有没有人"会出现两种答案，而症状只是**偶尔**差一格。
func enemyCellOf(e *enemy) [2]int {
	if e == nil {
		return [2]int{}
	}
	return [2]int{
		int(math.RoundToEven(e.position[0])),
		int(math.RoundToEven(e.position[1])),
	}
}

// logosTalent2OnHit 把「剜魂具辞」施加到被打中的敌人身上。
//
// 原文：「攻击使目标在 N 秒内法术抗性 −M 且受到的法术伤害提高 K 点」。
//
// 三项都在敌人身上取 max 续期（与全仓时限状态的写法一致）：
//   - 剩余秒数取 max，不覆盖；
//   - 法抗削减与法伤加值**按这次的黑板值覆盖**（同一名逻各斯两种数值不会同时存在；
//     取 max 会让换潜能之后旧值残留）。
//
// ⚠ 时点口径：**本次这一击的伤害已经结算完**，减益作用于**之后**的伤害。
// 数据里没有第二个键能判「同一击是否享受」，已登记进 `Unresolved`。
func logosTalent2OnHit(op *operator, target *enemy, t float64, verdict *Verdict) {
	if op == nil || target == nil || op.logosState == nil {
		return
	}
	cfg := op.logosState.Config
	if !cfg.Talent2Enabled || cfg.Talent2Duration <= 0 {
		return
	}
	target.logosDebuffUntil = math.Max(target.logosDebuffUntil, t+cfg.Talent2Duration)
	target.logosMagicResDown = -cfg.Talent2MagicResDelta // 黑板里是 -10，减益是「减 10」
	target.logosMagicFlatBonusValue = cfg.Talent2AtkAddition
	op.logosState.T2Applied++
	if verdict != nil {
		verdict.Events = append(verdict.Events, Event{
			T: t, Kind: "logos_talent2",
			Who: op.spec.Name + " → " + target.spec.Name,
		})
	}
}

// logosTalent2Active 报告这一只敌人此刻是否处在「剜魂具辞」里。
func (e *enemy) logosTalent2Active() bool {
	if e.sim == nil || e.sim.time == nil {
		return false
	}
	return *e.sim.time < e.logosDebuffUntil
}

// 两个读数拆成方法而不是字段直读：法抗那一条要在 `enemy.res()` 的唯一入口里
// 乘进去，法伤加值要在伤害结算后加进去，两处都需要「这一刻有没有生效」的判据。
func (e *enemy) logosResDown() float64 {
	if !e.logosTalent2Active() {
		return 0
	}
	return e.logosMagicResDown
}

func (e *enemy) logosMagicFlat() float64 {
	if !e.logosTalent2Active() {
		return 0
	}
	return e.logosMagicFlatBonusValue
}

// ---------------------------------------------------------------- 技能一

// logosS1Execute 是技能一「殁亡」的逐帧判定：
//
//	攻击范围内生命值低于「逻各斯攻击力 × attack@kill_atk_scale」的敌人立刻倒下；
//	每倒下一名，就对**另一个**范围内的目标造成与其生命值相等的法术伤害。
//
// 口径与出处：
//   - 阈值取**当前**攻击力（技能期间已被 `atk` 抬到 2 倍），所以阈值随技能开关变；
//   - 「立刻倒下」用黑板里的 `attack@kill_damage`（数据上就是 9999999）走同一条
//     伤害入口——这样「击杀归谁」与「累计伤害」两个读数与普攻同源，不留第二套账；
//   - 「另一个随机目标」在 Go 里落成**按敌人列表次序的第一个合格目标**：
//     判决必须可重复，掷骰子会让同一条时间线两次跑出两个数。该口径登记待证。
func logosS1Execute(op *operator, st *LogosBattleState, enemies []*enemy, t float64, verdict *Verdict) {
	cfg := st.Config
	if cfg.S1KillAtkScale <= 0 {
		return
	}
	cells := op.targetRange()
	threshold := op.atk() * cfg.S1KillAtkScale
	if threshold <= 0 {
		return
	}

	// 先把这一帧「够得着且已经低于阈值」的人点出来，再统一倒下：
	// 边遍历边结算会让「先倒下的那个」之后的判定用上被改过的血量。
	var doomed []*enemy
	for _, e := range enemies {
		if e == nil || !e.alive() || e.leaked || e.offMap {
			continue
		}
		if !inCells(cells, enemyCellOf(e)) {
			continue
		}
		if e.hp >= threshold {
			continue
		}
		doomed = append(doomed, e)
	}
	if len(doomed) == 0 {
		return
	}

	for _, e := range doomed {
		if !e.alive() {
			continue
		}
		fallenHP := e.hp
		// 「立刻倒下」：走统一伤害入口。
		dealt := e.take(math.Max(cfg.S1KillDamage, fallenHP), op)
		if dealt <= 0 {
			continue
		}
		st.S1Kills++
		verdict.DamageDealt += dealt
		if verdict != nil {
			verdict.Events = append(verdict.Events, Event{
				T: t, Kind: "logos_s1_execute",
				Who: op.spec.Name + " → " + e.spec.Name,
			})
		}
		// 「对另一个随机目标造成与倒下单位生命值相等的法术伤害」。
		//
		// ⚠ 这里的「生命值」取**倒下那一刻**的血量（`fallenHP`），不是最大生命值：
		// 正文写的是"倒下单位生命值"，而"立刻倒下"的判据看的也是当前生命值。
		// 同一句话里两处血量同源，才不会有第二种读法。
		victim := logosAnotherTarget(op, enemies, e, cells)
		if victim == nil {
			continue
		}
		// 伤害走标准的法术结算（法抗会削它），并按天赋二加值叠加。
		dmg := resolveDamage(fallenHP, "MAGIC", 1.0, 0, victim.res(), 0)
		dmg += victim.logosMagicFlat()
		got := victim.take(dmg, op)
		verdict.DamageDealt += got
		if got > 0 && !victim.alive() && !victim.pendingReborn() {
			victim.deathTime = t
		}
	}
}

// logosAnotherTarget 在范围内挑一个**除 fallen 之外**的存活敌人。
//
// 「随机」在数据里没有种子也没有权重，本实现取**敌人列表次序的第一个合格目标**
// ——确定性、可复核，并登记进 `Unresolved` 待证。
func logosAnotherTarget(op *operator, enemies []*enemy, fallen *enemy, cells [][2]int) *enemy {
	for _, e := range enemies {
		if e == nil || e == fallen {
			continue
		}
		if !e.alive() || e.leaked || e.offMap {
			continue
		}
		if !inCells(cells, enemyCellOf(e)) {
			continue
		}
		return e
	}
	return nil
}

// ---------------------------------------------------------------- 技能二

// logosS2Tick 是技能二「提喻」的逐帧驱动：
//
//	停攻 → 锁定一个目标 → 每 `attack@cooldown` 秒结算一次法术伤害；
//	同一目标每结算一次，伤害倍率 +(attack@atk_scale_delta)、移速 −(|attack@move_speed|)，
//	两者都以 `attack@max_stack_cnt` 封顶（10 层 ⇒ 倍率 3 倍、移速 40%，正合
//	「锁定 5 秒后达到上限」：10 层 × 0.5 秒 = 5 秒）。
func logosS2Tick(op *operator, st *LogosBattleState, enemies []*enemy, dt, t float64, verdict *Verdict) {
	cfg := st.Config
	if cfg.S2Cooldown <= 0 {
		return
	}
	cells := op.targetRange()

	// 目标倒下 / 跑出范围 / 不存在 ⇒ 重新索敌并**重置**效果。
	if st.Locked != nil {
		ok := st.Locked.alive() && !st.Locked.leaked && !st.Locked.offMap &&
			inCells(cells, enemyCellOf(st.Locked))
		if !ok {
			st.reset()
		}
	}
	if st.Locked == nil {
		picked := pickTargets(op, enemies, 1, t)
		if len(picked) == 0 {
			return
		}
		st.Locked = picked[0]
		st.S2Stack = 0
		st.S2Timer = 0
	}

	st.S2Timer += dt
	// while 而不是 if：低帧率夹具里 dt 可能跨过一拍以上，漏掉的拍数会让
	// 层数与伤害同时偏少，而症状只是"伤害偏低"。
	for st.S2Timer >= cfg.S2Cooldown {
		st.S2Timer -= cfg.S2Cooldown
		target := st.Locked
		if target == nil || !target.alive() {
			st.reset()
			return
		}
		if st.S2Stack < cfg.S2MaxStackCnt {
			st.S2Stack++
		}
		// 倍率：`base + delta × 层数`（10 层 ⇒ 0.75 + 1.5 = 2.25 = 3 × base）。
		scale := cfg.S2AtkScaleBase + cfg.S2AtkScaleDelta*float64(st.S2Stack)
		dmg := resolveDamage(op.atk(), "MAGIC", scale, target.spec.DEF, target.res(), 0)
		dmg += target.logosMagicFlat()
		got := target.take(dmg, op)
		st.S2Ticks++
		if got > 0 {
			verdict.DamageDealt += got
		}
		// 移速：`attack@move_speed` 数据里就是**每层的负比例**（-0.06），
		// 直接相加即可（10 层 ⇒ -0.6 ⇒ 移速 40%）。乘上负号会变成加速——
		// 症状是"被她盯上的敌人跑得更快"，且只在技能二的局里出现。
		target.logosMoveDown = cfg.S2MoveSpeedDelta * float64(st.S2Stack)
		if got > 0 && !target.alive() && !target.pendingReborn() {
			target.deathTime = t
		}
		if verdict != nil {
			verdict.Events = append(verdict.Events, Event{
				T: t, Kind: "logos_s2_tick",
				Who: op.spec.Name + " → " + target.spec.Name,
			})
		}
		if !target.alive() {
			// 目标倒下：重新索敌、效果重置（正文原话）。
			st.reset()
			return
		}
	}
}

// logosMoveScale 是逻各斯技能二叠出来的**移速乘区**（没叠过就是 1.0）。
//
// ⚠ 与【停顿】不是一回事：停顿是全局常数 80%，这一条是**按层爬坡**的
// （每层 -6%，10 层到 40%），所以不能复用 `sluggishTimer`。
func (e *enemy) logosMoveScale() float64 {
	if e.logosMoveDown == 0 {
		return 1
	}
	s := 1 + e.logosMoveDown
	if s < 0 {
		return 0
	}
	return s
}
