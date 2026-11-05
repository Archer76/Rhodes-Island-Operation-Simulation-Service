package main

import (
	"math"
)

// Sbell2Runtime 封装圣聆初雪在主战斗循环中的运行态
type Sbell2Runtime struct {
	Config *Sbell2RuntimeConfig

	// 部署初始化标记
	DeployedInitDone bool

	// 第一天赋积雪生成计时器
	SnowTimer float64

	// S1 瞬发与充能控制
	S1Charges int

	// S2 永续状态
	S2Active bool

	// S3 聚怪吸引计时器
	S3AttractRemaining float64

	// 统计数据
	TotalMagicDamage float64
	ColdApplications int
	FreezeTriggers   int
	BlessingTriggered bool
}

func newSbell2Runtime(cfg *Sbell2RuntimeConfig) *Sbell2Runtime {
	rt := &Sbell2Runtime{
		Config: cfg,
	}
	if cfg != nil {
		rt.SnowTimer = cfg.T1Interval
	}
	return rt
}

// TraitBonusDEF 返回未开启技能时的特性防御力加成
func (r *Sbell2Runtime) TraitBonusDEF(skillActive bool, baseDEF float64) float64 {
	if r == nil || r.Config == nil || skillActive {
		return 0
	}
	return baseDEF * r.Config.TraitDef
}

// TraitBonusRES 返回未开启技能时的特性法术抗性加成
func (r *Sbell2Runtime) TraitBonusRES(skillActive bool) float64 {
	if r == nil || r.Config == nil || skillActive {
		return 0
	}
	return r.Config.TraitMagicResistance
}

// CanNormalAttack 判定阵法术师通常不攻击，仅在技能开启期间可攻击
func (r *Sbell2Runtime) CanNormalAttack(skillActive bool) bool {
	if r == nil {
		return true
	}
	// 阵法术师特性：未开技能时不攻击
	return skillActive
}

// OnDamageDealt 模组 Y 特性：范围内敌人越多造成的伤害越高 (最多 5 层，每层 3%)
func (r *Sbell2Runtime) DamageMultiplier(enemiesInRangeCount int) float64 {
	if r == nil || r.Config == nil || r.Config.TraitDamageScale <= 0 {
		return 1.0
	}
	stacks := enemiesInRangeCount
	if stacks > r.Config.TraitMaxValidStackCnt {
		stacks = r.Config.TraitMaxValidStackCnt
	}
	if stacks <= 0 {
		return 1.0
	}
	return 1.0 + float64(stacks)*r.Config.TraitDamageScale
}

// OnTakeDamage 第二天赋受击反击寒冷
func (r *Sbell2Runtime) OnTakeDamage(attacker *enemy, friendly bool) {
	if r == nil || r.Config == nil || !r.Config.T2Unlocked || attacker == nil || !attacker.alive() {
		return
	}
	if r.Config.T2Cold > 0 {
		attacker.applyCold(r.Config.T2Cold, friendly)
		r.ColdApplications++
	}
}

// TriggerBlessingSave 第二天赋致命伤免死满血复活
func (r *Sbell2Runtime) TriggerBlessingSave(op *operator, enemies []*enemy, t float64, verdict *Verdict) bool {
	if r == nil || r.Config == nil || !r.Config.T2Unlocked || r.BlessingTriggered || op == nil {
		return false
	}
	r.BlessingTriggered = true
	op.blessingUsed = true
	op.hp = op.maxHP() * r.Config.T2HpRatio

	// 自身冻结
	if r.Config.T2Freeze > 0 {
		op.freezeTimer = math.Max(op.freezeTimer, r.Config.T2Freeze)
		op.freezeClock.Reset()
	}

	// 范围内的所有敌人施加冻结
	freezeSecs := r.Config.T2C2eFreeze
	if freezeSecs <= 0 {
		freezeSecs = 8.0
	}

	cells := make(map[[2]int]bool, len(op.spec.Range))
	for _, c := range op.spec.Range {
		cells[[2]int{c[0], c[1]}] = true
	}

	for _, e := range enemies {
		if e == nil || !e.alive() || e.leaked || e.offMap {
			continue
		}
		cx, cy := e.cell()
		if cells[[2]int{cx, cy}] {
			// 直接冻结
			e.freezeTimer = math.Max(e.freezeTimer, freezeSecs)
			e.freezeFriendly = true
			e.freezeClock.Reset()
			r.FreezeTriggers++
		}
	}

	if verdict != nil {
		verdict.Events = append(verdict.Events, Event{
			T:    t,
			Kind: "sbell2_blessing_save",
			Who:  op.spec.Name,
		})
	}
	return true
}
