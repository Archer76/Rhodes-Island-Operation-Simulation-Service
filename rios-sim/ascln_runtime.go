package main

// AsclnDebuffState 跟踪单个敌人身上的第一天赋 debuff 状态
type AsclnDebuffState struct {
	Stacks        int
	RemainingTime float64
	IntervalTimer float64
}

// AsclnRuntime 封装阿斯卡纶在主战斗循环中的运行态
type AsclnRuntime struct {
	Config *AsclnRuntimeConfig
	RNG    *probRNG

	// 第一天赋：map[enemyIndex]*AsclnDebuffState
	Debuffs map[int]*AsclnDebuffState

	// 第二天赋：相邻高台判定结果缓存
	AdjacentHighground bool

	// 技能 1 充能与连击状态
	S1Charges      int
	S1PendingCombo int // 连续攻击第二发判定

	// 技能 2 / 3 持续时间
	SkillActive        bool
	SkillRemainingTime float64

	// 统计留痕
	TotalDoTDamage float64
	TotalHeal      float64
	MissTriggers   int
	DodgeTriggers  int
}

func newAsclnRuntime(cfg *AsclnRuntimeConfig) *AsclnRuntime {
	return &AsclnRuntime{
		Config:  cfg,
		RNG:     newProbRNG(cfg.RNGSeed),
		Debuffs: make(map[int]*AsclnDebuffState),
	}
}

// CheckAdjacentHighground 检查阿斯卡纶周围四格是否存在高台地块
func (r *AsclnRuntime) CheckAdjacentHighground(stage *Stage, col, row int) bool {
	if stage == nil || stage.Map.Tiles == nil {
		r.AdjacentHighground = false
		return false
	}
	neighbors := [][2]int{
		{col, row - 1},
		{col, row + 1},
		{col - 1, row},
		{col + 1, row},
	}
	for _, n := range neighbors {
		nc, nr := n[0], n[1]
		if nr >= 0 && nr < len(stage.Map.Tiles) {
			if nc >= 0 && nc < len(stage.Map.Tiles[nr]) {
				tile := stage.Map.Tiles[nr][nc]
				if tile.Height == "high" || tile.Buildable == "high" || tile.Buildable == "all" {
					r.AdjacentHighground = true
					return true
				}
			}
		}
	}
	r.AdjacentHighground = false
	return false
}

// ApplyT1Debuff 攻击命中或尸爆波及敌人时施加/刷新第一天赋
func (r *AsclnRuntime) ApplyT1Debuff(enemyIdx int) {
	st, exists := r.Debuffs[enemyIdx]
	if !exists {
		st = &AsclnDebuffState{
			Stacks:        1,
			RemainingTime: r.Config.T1DebuffDuration,
			IntervalTimer: 0,
		}
		r.Debuffs[enemyIdx] = st
		return
	}
	// 已有时增加一层（不超过上限）并刷新持续时间
	if st.Stacks < r.Config.T1MaxStackCnt {
		st.Stacks++
	}
	st.RemainingTime = r.Config.T1DebuffDuration
}

// EnemyMoveSpeedModifier 计算阿斯卡纶对指定敌人造成的总移速修正比例（负数表示减速）
func (r *AsclnRuntime) EnemyMoveSpeedModifier(enemyIdx int, inSkillRange bool) float64 {
	mod := 0.0
	// 1. 第一天赋层数减速
	if st, ok := r.Debuffs[enemyIdx]; ok && st.RemainingTime > 0 {
		mod += r.Config.T1MoveSpeed * float64(st.Stacks)
	}
	// 2. 模组 X 特性减速（在攻击范围内敌人移速 -20%）
	if inSkillRange && r.Config.TraitMoveSpeed != 0 {
		mod += r.Config.TraitMoveSpeed
	}
	// 3. 技能 2 范围减速光环
	if r.SkillActive && inSkillRange && r.Config.Slot == 2 {
		mod += r.Config.S2MoveSpeed
	}
	return mod
}

// SampleHitChance 判定敌人攻击阿斯卡纶时是否命中（确定性伪随机采样，V-2 规范）
func (r *AsclnRuntime) SampleHitChance(isPhysical bool, inSkillRange bool, isGroundEnemy bool) (bool, string) {
	// 技能 3 开启期间，处于技能范围内的地面敌人受到未命中率降低影响
	if r.SkillActive && r.Config.Slot == 3 && inSkillRange && isGroundEnemy {
		var hitrateReduction float64
		if isPhysical {
			hitrateReduction = r.Config.S3DamageHitratePhys // 例如 -0.5
		} else {
			hitrateReduction = r.Config.S3DamageHitrateMag // 例如 -0.5
		}
		// 基础命中率为 1.0 + reduction（例如 1.0 - 0.5 = 0.5）
		hitChance := 1.0 + hitrateReduction
		if hitChance < 0 {
			hitChance = 0
		}
		// 确定性抽样：若未命中（chance(hitChance) 为 false）
		if !r.RNG.chance(hitChance) {
			r.MissTriggers++
			return false, "miss"
		}
	}

	// 伏击客特性闪避判定（基础 50%，模组 Y 提升至 65%）
	dodgeChance := r.Config.TraitDodgeProb
	if dodgeChance > 0 && r.RNG.chance(dodgeChance) {
		r.DodgeTriggers++
		return false, "dodge"
	}

	return true, "hit"
}

// OnEvadeOrMiss 触发闪避或未命中时的生命回复（技能 3）
func (r *AsclnRuntime) OnEvadeOrMiss(maxHP float64) float64 {
	if r.SkillActive && r.Config.Slot == 3 && r.Config.S3AttackHpRatio > 0 {
		heal := maxHP * r.Config.S3AttackHpRatio
		r.TotalHeal += heal
		return heal
	}
	return 0
}

// OnEnemyKilledByT1 带有第一天赋效果的敌人被击倒时触发回复（模组 Y Lv2/3）
func (r *AsclnRuntime) OnEnemyKilledByT1(enemyIdx int, maxHP float64) float64 {
	if st, ok := r.Debuffs[enemyIdx]; ok && st.RemainingTime > 0 {
		delete(r.Debuffs, enemyIdx)
		if r.Config.T1OnKillHpRatio > 0 {
			heal := maxHP * r.Config.T1OnKillHpRatio
			r.TotalHeal += heal
			return heal
		}
	}
	return 0
}

// TriggerS2CorpseExplosion 技能 2 期间地面敌人被击倒，尸爆施加第一天赋
func (r *AsclnRuntime) TriggerS2CorpseExplosion(enemies []*enemy, killedPos [2]float64) {
	if !r.SkillActive || r.Config.Slot != 2 || r.Config.S2RangeRadius <= 0 {
		return
	}
	radius := r.Config.S2RangeRadius
	radiusSq := radius * radius
	for _, e := range enemies {
		if e == nil || !e.alive() || e.spec.IsFlying {
			continue
		}
		ex, ey := e.position[0], e.position[1]
		dx := ex - killedPos[0]
		dy := ey - killedPos[1]
		if dx*dx+dy*dy <= radiusSq {
			r.ApplyT1Debuff(e.index)
		}
	}
}

// ClearAllDebuffs 阿斯卡纶离场或撤退时清理所有施加的 debuff
func (r *AsclnRuntime) ClearAllDebuffs() {
	r.Debuffs = make(map[int]*AsclnDebuffState)
	r.SkillActive = false
	r.SkillRemainingTime = 0
}
