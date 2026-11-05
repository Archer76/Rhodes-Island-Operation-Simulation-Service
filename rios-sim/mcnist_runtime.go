package main

// McnistBarrierHolder 屏障持有者状态
type McnistBarrierHolder struct {
	Barrier         float64 // 当前屏障数值
	OverkillProtect bool    // 是否具备来自机械师的超额防护机制
}

// McnistRuntime 机械师在主战斗循环中的状态管理
type McnistRuntime struct {
	Config *McnistRuntimeConfig

	// 机械师本体屏障
	OwnerBarrier McnistBarrierHolder

	// 召唤物【结构性原理】状态
	TokenOp       *operator
	TokenBarrier  McnistBarrierHolder
	TokenLifetime float64 // 剩余持续时间（秒）
	TokenCooldown float64 // 独立再部署冷却（初始 0）
	TokenDeployed bool

	// 技能弹药状态
	AmmoRemaining int

	// S1 连击与弹药计时
	S1Firing        bool
	S1ShotsFired    int     // 本次五连击打出的发数
	S1NextShotTimer float64 // 下一次小连击间隔倒计时

	// S2 屏障破裂处理标志（防反伤回环）
	S2BarrierBurstProcessing bool

	// S3 冲锋与虚弱光环状态
	S3DashTriggered  bool    // 技能期间是否已触发过冲锋
	WeakenAuraActive bool    // 虚弱光环是否激活
	WeakenAuraCenter [2]int  // 光环中心地块
	WeakenAuraRatio  float64 // 当前虚弱比例（初始 0.50，每秒 -0.025）

	// 敌方战栗与虚弱状态跟踪: map[enemyIndex]剩余时间
	TrembleDebuffs map[int]float64
	WeakenDebuffs  map[int]float64 // 敌人受到的虚弱比例

	// 统计指纹
	TotalBarrierAbsorbed float64
	TotalOverkillBlocks  int
	TotalBurstDamageHits int
	TotalDashDamageHits  int
	TotalClusterAttacks  int
}

func newMcnistRuntime(cfg *McnistRuntimeConfig) *McnistRuntime {
	return &McnistRuntime{
		Config:         cfg,
		TrembleDebuffs: make(map[int]float64),
		WeakenDebuffs:  make(map[int]float64),
	}
}

// InitOnDeploy 机械师本体部署初始化
func (r *McnistRuntime) InitOnDeploy(op *operator) {
	if r.Config.LifeEquationHPRatio > 0 {
		barrierAmount := op.maxHP() * r.Config.LifeEquationHPRatio
		r.OwnerBarrier = McnistBarrierHolder{
			Barrier:         barrierAmount,
			OverkillProtect: true,
		}
	}
	r.TokenCooldown = 0
}

// DeployToken 部署结构性原理召唤物
func (r *McnistRuntime) DeployToken(tokenOp *operator) {
	r.TokenOp = tokenOp
	r.TokenDeployed = true
	r.TokenLifetime = r.Config.TokenDuration
	if r.Config.LifeEquationHPRatio > 0 {
		barrierAmount := tokenOp.maxHP() * r.Config.LifeEquationHPRatio
		r.TokenBarrier = McnistBarrierHolder{
			Barrier:         barrierAmount,
			OverkillProtect: true,
		}
	}
}

// AbsorbDamageWithBarrier 尝试用来自机械师的屏障吸收伤害
// 返回扣除屏障后剩余伤害。如果持有超额防护且单次伤害击碎屏障，超额部分被完全抵挡（返回 0）。
func (r *McnistRuntime) AbsorbDamageWithBarrier(targetOp *operator, dmg float64) float64 {
	var holder *McnistBarrierHolder
	isOwner := (targetOp.spec.CharID == mcnistCharID)
	if isOwner {
		holder = &r.OwnerBarrier
	} else if r.TokenOp != nil && targetOp == r.TokenOp {
		holder = &r.TokenBarrier
	} else {
		return dmg
	}

	if holder.Barrier <= 0 {
		return dmg
	}

	if holder.Barrier >= dmg {
		holder.Barrier -= dmg
		r.TotalBarrierAbsorbed += dmg
		return 0.0
	}

	// 屏障不足以抵挡全部伤害：发生屏障破裂
	absorbed := holder.Barrier
	holder.Barrier = 0
	r.TotalBarrierAbsorbed += absorbed

	// 检查超额防护机制（Overkill Protection）
	if holder.OverkillProtect {
		// 单次超额伤害直接抵挡，本体不扣血
		r.TotalOverkillBlocks++
		return 0.0
	}

	return dmg - absorbed
}

// EnemyAtkModifier 虚弱效果降低敌人攻击力
func (r *McnistRuntime) EnemyAtkModifier(enemyIdx int) float64 {
	if ratio, ok := r.WeakenDebuffs[enemyIdx]; ok && ratio > 0 {
		return -ratio
	}
	return 0.0
}

// EnemyIsTrembling 敌人是否处于战栗状态
func (r *McnistRuntime) EnemyIsTrembling(enemyIdx int) bool {
	if sec, ok := r.TrembleDebuffs[enemyIdx]; ok && sec > 0 {
		return true
	}
	return false
}

// ClearAll 清除所有状态
func (r *McnistRuntime) ClearAll() {
	r.OwnerBarrier = McnistBarrierHolder{}
	r.TokenBarrier = McnistBarrierHolder{}
	r.TokenDeployed = false
	r.TokenOp = nil
	r.AmmoRemaining = 0
	r.S1Firing = false
	r.WeakenAuraActive = false
	r.TrembleDebuffs = make(map[int]float64)
	r.WeakenDebuffs = make(map[int]float64)
}
