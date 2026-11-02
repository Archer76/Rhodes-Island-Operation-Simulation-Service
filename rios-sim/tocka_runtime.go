package main

// TockaTriggerKind 标识触发型效果的来源技能类型
type TockaTriggerKind int

const (
	TockaTriggerNone TockaTriggerKind = iota
	TockaTriggerS1
	TockaTriggerS2
	TockaTriggerS3
)

// TockaOpState 跟踪单个友方干员身上的协同（触发型效果）与伴生增益状态
type TockaOpState struct {
	TriggerKind TockaTriggerKind

	// S1 衰减屏障
	Barrier          float64
	BarrierDecayRate float64

	// S2 攻速与自动开启
	S2AspdBuffTime float64
	S2AspdBonus    float64
	S2AutoTrigger  bool

	// S3 衰减攻击力加成
	DecayAtkBuff      float64
	DecayAtkDecayRate float64
	DecayAtkTime      float64
}

// TockaWeakenState 跟踪敌方单位身上的第二天赋「雪的印痕」虚弱与法术 DoT
type TockaWeakenState struct {
	RemainingTime float64
	IntervalTimer float64
	AtkReduction  float64
	DotRatio      float64
}

// TockaRuntime 封装冻河在主战斗循环中的运行态
type TockaRuntime struct {
	Config *TockaRuntimeConfig
	RNG    *probRNG

	// 友方干员协同状态：map[*operator]*TockaOpState
	OpStates map[*operator]*TockaOpState

	// 敌方虚弱与法术 DoT：map[enemyIndex]*TockaWeakenState
	WeakenDebuffs map[int]*TockaWeakenState

	// 第二天赋「雪的印痕」强化普通攻击就绪标志
	EmpoweredAttackReady bool

	// 技能三开技初动施加完成标志
	S3InitialCastDone bool

	// 冻河自身的 S3 衰减攻击力加成
	SelfDecayAtkBuff      float64
	SelfDecayAtkDecayRate float64
	SelfDecayAtkTime      float64

	// 统计指标
	TotalHeal          float64
	TotalSpRestored    float64
	TotalStunsApplied  int
	TotalEmpoweredHits int
	TotalDoTDamage     float64
}

func newTockaRuntime(cfg *TockaRuntimeConfig) *TockaRuntime {
	return &TockaRuntime{
		Config:        cfg,
		RNG:           newProbRNG(cfg.RNGSeed),
		OpStates:      make(map[*operator]*TockaOpState),
		WeakenDebuffs: make(map[int]*TockaWeakenState),
	}
}

// ClearAll 清除所有协同标记与负面状态（如倒下/撤退时）
func (r *TockaRuntime) ClearAll() {
	r.OpStates = make(map[*operator]*TockaOpState)
	r.WeakenDebuffs = make(map[int]*TockaWeakenState)
	r.EmpoweredAttackReady = false
	r.S3InitialCastDone = false
	r.SelfDecayAtkBuff = 0
	r.SelfDecayAtkTime = 0
}

// getOrCreateOpState 获取或创建指定干员的状态
func (r *TockaRuntime) getOrCreateOpState(op *operator) *TockaOpState {
	st, exists := r.OpStates[op]
	if !exists {
		st = &TockaOpState{}
		r.OpStates[op] = st
	}
	return st
}

// ApplyS1Trigger 向未持有协同效果的干员施加 S1 触发型效果
func (r *TockaRuntime) ApplyS1Trigger(target *operator) {
	if target == nil {
		return
	}
	st := r.getOrCreateOpState(target)
	st.TriggerKind = TockaTriggerS1
	if r.Config.T2Unlocked {
		r.EmpoweredAttackReady = true
	}
}

// ApplyS2Trigger 向未持有协同效果的干员施加 S2 触发型效果
func (r *TockaRuntime) ApplyS2Trigger(target *operator) {
	if target == nil {
		return
	}
	st := r.getOrCreateOpState(target)
	st.TriggerKind = TockaTriggerS2
	if r.Config.T2Unlocked {
		r.EmpoweredAttackReady = true
	}
}

// ApplyS3Trigger 向干员施加 S3 触发型效果
func (r *TockaRuntime) ApplyS3Trigger(target *operator) {
	if target == nil {
		return
	}
	st := r.getOrCreateOpState(target)
	st.TriggerKind = TockaTriggerS3
	if r.Config.T2Unlocked {
		r.EmpoweredAttackReady = true
	}
}

// OnTriggered 当持有触发型效果的干员触发机制时调用第一天赋
func (r *TockaRuntime) OnTriggered(tockaOp *operator, allOps []*operator) {
	if tockaOp == nil || !tockaOp.alive() {
		return
	}
	if !r.Config.T1Unlocked {
		return
	}

	// 1. 冻河自身回复技力
	if r.Config.T1SP > 0 {
		maxSP := 0.0
		if tockaOp.spec.Skill != nil {
			maxSP = float64(tockaOp.spec.Skill.SPCost)
		}
		tockaOp.sp += r.Config.T1SP
		if maxSP > 0 && tockaOp.sp > maxSP {
			tockaOp.sp = maxSP
		}
		r.TotalSpRestored += r.Config.T1SP
	}

	// 2. 为攻击范围内一名友方干员治疗生命
	if r.Config.T1HealScale > 0 {
		healAmount := tockaOp.atk() * r.Config.T1HealScale
		var bestTarget *operator
		lowestRatio := 2.0 // 正常生命比例 <= 1.0

		for _, ally := range allOps {
			if ally == nil || !ally.alive() {
				continue
			}
			// 必须在冻河攻击范围内
			if !inCells(tockaOp.targetRange(), [2]int{int(ally.cell[0]), int(ally.cell[1])}) {
				continue
			}
			ratio := ally.hp / ally.maxHP()
			if ratio < lowestRatio {
				lowestRatio = ratio
				bestTarget = ally
			}
		}

		if bestTarget != nil {
			oldHP := bestTarget.hp
			bestTarget.hp += healAmount
			if bestTarget.hp > bestTarget.maxHP() {
				bestTarget.hp = bestTarget.maxHP()
			}
			actualHeal := bestTarget.hp - oldHP
			r.TotalHeal += actualHeal
		}
	}
}

// HandleAllyDamaged 处理友方干员受到攻击：若持有 S1 触发型效果，获得衰减屏障并击晕攻击者
func (r *TockaRuntime) HandleAllyDamaged(ally *operator, attacker *enemy, tockaOp *operator, allOps []*operator) {
	if ally == nil || !ally.alive() || attacker == nil || !attacker.alive() {
		return
	}
	st, exists := r.OpStates[ally]
	if !exists || st.TriggerKind != TockaTriggerS1 {
		return
	}

	// 触发 S1 效果
	st.TriggerKind = TockaTriggerNone

	// 1. 获得衰减屏障
	tockaAtk := 100.0
	if tockaOp != nil && tockaOp.alive() {
		tockaAtk = tockaOp.atk()
	}
	barrierInit := tockaAtk * r.Config.S1ShieldAtkScale
	st.Barrier = barrierInit
	if r.Config.S1ShieldTime > 0 {
		st.BarrierDecayRate = barrierInit / r.Config.S1ShieldTime
	} else {
		st.BarrierDecayRate = 0
	}

	// 2. 攻击者眩晕
	if r.Config.S1Stun > 0 {
		attacker.applyStun(r.Config.S1Stun)
		r.TotalStunsApplied++
	}

	// 3. 联动第一天赋
	r.OnTriggered(tockaOp, allOps)
}

// HandleAllySkillReady 检查持有 S2 标记的干员技能是否就绪，就绪则触发攻速并自动开启
func (r *TockaRuntime) HandleAllySkillReady(ally *operator, tockaOp *operator, allOps []*operator) {
	if ally == nil || !ally.alive() || ally.spec.Skill == nil {
		return
	}
	st, exists := r.OpStates[ally]
	if !exists || st.TriggerKind != TockaTriggerS2 {
		return
	}

	maxSP := float64(ally.spec.Skill.SPCost)
	// 检查技能是否可开启（SP 满且未在激活中）
	if maxSP > 0 && ally.sp >= maxSP && !ally.skillActive {
		st.TriggerKind = TockaTriggerNone
		st.S2AspdBuffTime = r.Config.S2BuffDuration
		st.S2AspdBonus = r.Config.S2AttackSpeed
		st.S2AutoTrigger = true

		// 联动第一天赋
		r.OnTriggered(tockaOp, allOps)
	}
}

// HandleAllySkillActivated 处理持有 S3 标记的干员开启技能：攻击力加成与标记转移
func (r *TockaRuntime) HandleAllySkillActivated(ally *operator, tockaOp *operator, allOps []*operator) {
	if ally == nil || !ally.alive() {
		return
	}
	st, exists := r.OpStates[ally]
	if !exists || st.TriggerKind != TockaTriggerS3 {
		return
	}

	// 触发 S3 效果
	st.TriggerKind = TockaTriggerNone

	// 1. 持有者与冻河自身获得攻击力加成（在 bonus_duration 内衰减）
	dur := r.Config.S3BonusDuration
	if dur <= 0 {
		dur = 15.0
	}
	initAtk := r.Config.S3BonusInitAtk
	decayRate := r.Config.S3BonusAtkDecPerSec
	if decayRate <= 0 {
		decayRate = initAtk / dur
	}

	// 持有者
	st.DecayAtkBuff = initAtk
	st.DecayAtkDecayRate = decayRate
	st.DecayAtkTime = dur

	// 冻河自身
	r.SelfDecayAtkBuff = initAtk
	r.SelfDecayAtkDecayRate = decayRate
	r.SelfDecayAtkTime = dur

	// 2. 将标记转移给冻河攻击范围内技力比例最高的另一名干员
	var bestTarget *operator
	highestSpRatio := -1.0

	for _, cand := range allOps {
		if cand == nil || !cand.alive() || cand == ally {
			continue
		}
		if tockaOp != nil && !inCells(tockaOp.targetRange(), [2]int{int(cand.cell[0]), int(cand.cell[1])}) {
			continue
		}
		spRatio := 0.0
		if cand.spec.Skill != nil && cand.spec.Skill.SPCost > 0 {
			spRatio = cand.sp / float64(cand.spec.Skill.SPCost)
		}
		if spRatio > highestSpRatio {
			highestSpRatio = spRatio
			bestTarget = cand
		}
	}

	if bestTarget != nil {
		r.ApplyS3Trigger(bestTarget)
	}

	// 3. 联动第一天赋
	r.OnTriggered(tockaOp, allOps)
}

// ApplyT2Weaken 对命中的敌人施加第二天赋「雪的印痕」虚弱与法术 DoT
func (r *TockaRuntime) ApplyT2Weaken(e *enemy) {
	if e == nil || !e.alive() {
		return
	}
	st, exists := r.WeakenDebuffs[e.index]
	if !exists {
		st = &TockaWeakenState{}
		r.WeakenDebuffs[e.index] = st
	}
	st.RemainingTime = r.Config.T2BuffDuration
	st.IntervalTimer = 0
	st.AtkReduction = r.Config.T2Atk
	st.DotRatio = r.Config.T2MagicAtkScale
}

// EnemyAtkModifier 计算指定敌人因虚弱受到的攻击力修正比例（负数表示攻击力降低）
func (r *TockaRuntime) EnemyAtkModifier(enemyIdx int) float64 {
	if st, ok := r.WeakenDebuffs[enemyIdx]; ok && st.RemainingTime > 0 {
		return st.AtkReduction
	}
	return 0.0
}

// OpAtkModifier 计算指定干员的攻击力加成比例（S3 衰减攻击力加成）
func (r *TockaRuntime) OpAtkModifier(op *operator) float64 {
	if op == nil {
		return 0.0
	}
	if st, ok := r.OpStates[op]; ok && st.DecayAtkTime > 0 {
		return st.DecayAtkBuff
	}
	return 0.0
}

// OpAspdModifier 计算指定干员的攻速加成（S2 攻速加成）
func (r *TockaRuntime) OpAspdModifier(op *operator) float64 {
	if op == nil {
		return 0.0
	}
	if st, ok := r.OpStates[op]; ok && st.S2AspdBuffTime > 0 {
		return st.S2AspdBonus
	}
	return 0.0
}

// SelfAtkModifier 计算冻河自身的衰减攻击力加成比例
func (r *TockaRuntime) SelfAtkModifier() float64 {
	if r.SelfDecayAtkTime > 0 {
		return r.SelfDecayAtkBuff
	}
	return 0.0
}

// AbsorbDamageWithBarrier 尝试用 S1 屏障吸收伤害，返回扣除屏障后剩余伤害
func (r *TockaRuntime) AbsorbDamageWithBarrier(op *operator, dmg float64) float64 {
	if op == nil {
		return dmg
	}
	st, ok := r.OpStates[op]
	if !ok || st.Barrier <= 0 {
		return dmg
	}
	if st.Barrier >= dmg {
		st.Barrier -= dmg
		return 0.0
	}
	remaining := dmg - st.Barrier
	st.Barrier = 0
	return remaining
}
