package main

import (
	"math"
)

// DminonRuntime 封装国度（char_4246_dminon）在主战斗循环中的运行态
type DminonRuntime struct {
	Config *DminonRuntimeConfig
	RNG    *probRNG

	// 国度地块状态
	RealmTiles         map[[2]int]bool // 当前生效的所有国度地块
	BaseCells          map[[2]int]bool // 基础常态攻击范围覆盖的绝对格
	SkillCells         map[[2]int]bool // 技能范围覆盖的绝对格
	ExtraExpandedCells map[[2]int]bool // 三技能受击扩散出的额外绝对格

	// 技能状态机
	SkillActive    bool
	SkillCastCount int // 技能开启次数（用于技2二次使用永续判定）
	IsPermanent    bool

	// 技能一【停步】
	S1TriggeredEnemies map[int]bool // 本次技1期间已触发首次踏上停顿的敌人索引

	// 技能三【无人之国度】
	S3CounterTimer float64 // 受击扩散反击冷却计时器 (0.5s)

	// 第二天赋【此身为界】
	WasAlive         bool // 跟踪上一帧存活状态
	RetreatTriggered bool // 防止离场引爆重复触发

	// 第一天赋 DoT 计时器
	DoTTimer float64

	// 统计数据
	TotalDoTDamage     float64
	TotalExplodeDamage float64
	TotalCounterDamage float64
	StunTriggers       int
	SluggishTriggers   int
	CountersTriggered  int
}

func newDminonRuntime(cfg *DminonRuntimeConfig) *DminonRuntime {
	return &DminonRuntime{
		Config:             cfg,
		RNG:                newProbRNG(cfg.RNGSeed),
		RealmTiles:         make(map[[2]int]bool),
		BaseCells:          make(map[[2]int]bool),
		SkillCells:         make(map[[2]int]bool),
		ExtraExpandedCells: make(map[[2]int]bool),
		S1TriggeredEnemies: make(map[int]bool),
		WasAlive:           true,
	}
}

// InitRealm 初始化常态范围与技能范围
func (r *DminonRuntime) InitRealm(baseCells, skillCells [][2]int) {
	r.BaseCells = make(map[[2]int]bool, len(baseCells))
	for _, c := range baseCells {
		r.BaseCells[c] = true
	}
	r.SkillCells = make(map[[2]int]bool, len(skillCells))
	for _, c := range skillCells {
		r.SkillCells[c] = true
	}
	r.ResetRealmTiles()
}

// ResetRealmTiles 重置国度地块为当前攻击范围（常态或技能范围）
func (r *DminonRuntime) ResetRealmTiles() {
	r.RealmTiles = make(map[[2]int]bool)
	r.ExtraExpandedCells = make(map[[2]int]bool)
	if r.SkillActive && len(r.SkillCells) > 0 {
		for c := range r.SkillCells {
			r.RealmTiles[c] = true
		}
	} else {
		for c := range r.BaseCells {
			r.RealmTiles[c] = true
		}
	}
}

// IsOnRealm 检查某个绝对格坐标是否处于国度地块内
func (r *DminonRuntime) IsOnRealm(cell [2]int) bool {
	return r.RealmTiles[cell]
}

// OnSkillStart 技能开启触发
func (r *DminonRuntime) OnSkillStart() {
	r.SkillActive = true
	r.SkillCastCount++

	if r.Config.Slot == 1 {
		r.S1TriggeredEnemies = make(map[int]bool)
	} else if r.Config.Slot == 2 {
		// 第二次及以后使用：攻速 +30，持续时间无限
		if r.SkillCastCount >= 2 {
			r.IsPermanent = true
		}
	}

	// 范围可能扩大（技2 y-3, 技3 y-10），更新地块
	if len(r.SkillCells) > 0 {
		for c := range r.SkillCells {
			r.RealmTiles[c] = true
		}
	}
}

// OnSkillEnd 技能结束触发
func (r *DminonRuntime) OnSkillEnd() {
	r.SkillActive = false

	if r.Config.Slot == 1 {
		r.S1TriggeredEnemies = make(map[int]bool)
	}

	// 技能结束重置地块（恢复为常态攻击范围覆盖的基础地块）
	r.ResetRealmTiles()
}

// CheckS1Sluggish 检查敌人是否首次踏上国度地块，若是则施加停顿
func (r *DminonRuntime) CheckS1Sluggish(enemyIdx int, cell [2]int) (float64, bool) {
	if !r.SkillActive || r.Config.Slot != 1 {
		return 0, false
	}
	if !r.IsOnRealm(cell) {
		return 0, false
	}
	if r.S1TriggeredEnemies[enemyIdx] {
		return 0, false
	}
	r.S1TriggeredEnemies[enemyIdx] = true
	r.SluggishTriggers++
	return r.Config.S1Sluggish, true
}

// TryS3Counter 技能三受击扩散与反击判定
func (r *DminonRuntime) TryS3Counter(attackerCell [2]int) ([][2]int, bool) {
	if !r.SkillActive || r.Config.Slot != 3 {
		return nil, false
	}
	if r.S3CounterTimer > 0 {
		return nil, false
	}

	// 触发扩散：在伤害来源周围四格扩散国度
	r.S3CounterTimer = r.Config.S3CounterCD
	if r.S3CounterTimer <= 0 {
		r.S3CounterTimer = 0.5
	}
	r.CountersTriggered++

	neighbors := [][2]int{
		{attackerCell[0] + 1, attackerCell[1]},
		{attackerCell[0] - 1, attackerCell[1]},
		{attackerCell[0], attackerCell[1] + 1},
		{attackerCell[0], attackerCell[1] - 1},
	}
	for _, n := range neighbors {
		r.ExtraExpandedCells[n] = true
		r.RealmTiles[n] = true
	}
	return neighbors, true
}

// TriggerRetreatExplosion 第二天赋【此身为界】：撤退/离场引爆与清空国度
func (r *DminonRuntime) TriggerRetreatExplosion(enemies []*enemy, op *operator, t float64, verdict *Verdict) float64 {
	if r.RetreatTriggered || !r.Config.T2Unlocked {
		r.ClearAllRealm()
		return 0
	}
	r.RetreatTriggered = true

	totalDmg := 0.0
	atkScale := r.Config.T2AtkScale
	stunDur := r.Config.T2Stun
	if stunDur <= 0 {
		stunDur = 5.0
	}
	currentAtk := op.atk()

	for _, e := range enemies {
		if e == nil || !e.alive() || e.spec.IsFlying || e.offMap || e.leaked {
			continue
		}
		ecell := [2]int{int(math.RoundToEven(e.position[0])), int(math.RoundToEven(e.position[1]))}
		if !r.IsOnRealm(ecell) {
			continue
		}

		rawDmg := currentAtk * atkScale
		res := e.res()
		if res < 0 {
			res = 0
		}
		if res > 100 {
			res = 100
		}
		actualDmg := rawDmg * (1.0 - res/100.0)
		if actualDmg < 0.05*rawDmg {
			actualDmg = 0.05 * rawDmg
		}
		dealt := e.take(actualDmg, op)
		totalDmg += dealt
		r.TotalExplodeDamage += dealt
		r.StunTriggers++

		// 施加晕眩 5 秒
		e.applyStun(stunDur)

		if !e.alive() && verdict != nil {
			verdict.Kills++
			verdict.Events = append(verdict.Events, Event{
				T: t, Kind: "kill", Who: e.spec.Name + " (此身为界)",
			})
		}
	}

	if verdict != nil {
		verdict.Events = append(verdict.Events, Event{
			T: t, Kind: "dminon_retreat_explosion", Who: op.spec.Name,
		})
	}

	// 随后场上所有“国度”消失
	r.ClearAllRealm()
	return totalDmg
}

// ClearAllRealm 清空场上所有的国度地块
func (r *DminonRuntime) ClearAllRealm() {
	r.RealmTiles = make(map[[2]int]bool)
	r.ExtraExpandedCells = make(map[[2]int]bool)
}

// EnemyMoveSpeedModifier 模组 AMB-X 特性减速：攻击范围内敌人移速 -20%
func (r *DminonRuntime) EnemyMoveSpeedModifier(inRange bool) float64 {
	if inRange && r.Config.TraitMoveSpeed < 0 {
		return r.Config.TraitMoveSpeed
	}
	return 0
}

// IsEnemyUndodgeable 技能二【受戮】：使“国度”上的敌人无法闪避物法攻击
func (r *DminonRuntime) IsEnemyUndodgeable(cell [2]int) bool {
	if r.SkillActive && r.Config.Slot == 2 {
		return r.IsOnRealm(cell)
	}
	return false
}
