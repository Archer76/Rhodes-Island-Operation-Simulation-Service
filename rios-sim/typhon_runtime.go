package main

import (
	"math"
)

// TyphonRuntime 封装提丰在主战斗循环中的运行态
type TyphonRuntime struct {
	Config *TyphonRuntimeConfig
	RNG    *probRNG

	// 第一天赋「碎石破阵」
	T1TargetIndex int     `json:"t1_target_index"` // 当前连续攻击的目标敌人 index (-1 为无)
	T1Stacks      int     `json:"t1_stacks"`       // 当前叠层数
	T1Timer       float64 `json:"t1_timer"`        // 破甲保持持续时间

	// 技能 2「冰原馈赠」状态机
	S2CastCount int `json:"s2_cast_count"` // 技能释放次数：1=首次20s，>=2=二次开启无限

	// 技能状态跟踪
	LastSkillActive bool `json:"last_skill_active"`

	// 技能 3「永恒狩猎」全图锁定与弹药生命周期
	S3LockedTargetIndex int `json:"s3_locked_target_index"` // 锁定的敌人 index (-1 为未锁定)
	S3RemainingAmmo     int `json:"s3_remaining_ammo"`      // 剩余弹药数

	// 统计指标
	TotalAttacks           int     `json:"total_attacks"`
	TotalDamageDealt       float64 `json:"total_damage_dealt"`
	TotalStunsApplied      int     `json:"total_stuns_applied"`
	TotalT2SluggishApplied int     `json:"total_t2_sluggish_applied"`
}

func newTyphonRuntime(cfg *TyphonRuntimeConfig) *TyphonRuntime {
	return &TyphonRuntime{
		Config:              cfg,
		RNG:                 newProbRNG(cfg.RNGSeed),
		T1TargetIndex:       -1,
		S3LockedTargetIndex: -1,
	}
}

// Tick 推进第一天赋等时间敏感状态
func (r *TyphonRuntime) Tick(dt float64) {
	if r.T1Timer > 0 {
		r.T1Timer -= dt
		if r.T1Timer <= 0 {
			r.T1Timer = 0
			r.T1Stacks = 0
			r.T1TargetIndex = -1
		}
	}
}

// OnSkillActivate 在技能开启瞬间由 sim / skillTick 调用，管理状态机
func (r *TyphonRuntime) OnSkillActivate(t float64, op *operator, enemies []*enemy, verdict *Verdict) {
	if r.Config.Slot == 2 {
		r.S2CastCount++
		if r.S2CastCount == 1 {
			// 首次开启：持续 first_duration (20s)
			dur := r.Config.S2FirstDuration
			if dur <= 0 {
				dur = 20.0
			}
			op.skillTimer = dur
			if verdict != nil {
				verdict.Events = append(verdict.Events, Event{
					T:    t,
					Kind: "typhon_s2_first_activate",
					Who:  op.spec.Name,
				})
			}
		} else {
			// 二次开启：持续时间无限
			op.skillTimer = math.Inf(1)
			if verdict != nil {
				verdict.Events = append(verdict.Events, Event{
					T:    t,
					Kind: "typhon_s2_infinite_activate",
					Who:  op.spec.Name,
				})
			}
		}
	} else if r.Config.Slot == 3 {
		r.S3RemainingAmmo = r.Config.S3TriggerTime
		op.ammoLeft = r.Config.S3TriggerTime
		op.skillTimer = math.Inf(1) // 弹药技能持续时间由弹药耗尽控制

		// 挑选目标并全图锁定
		r.AcquireS3Lock(op, enemies)

		if verdict != nil {
			verdict.Events = append(verdict.Events, Event{
				T:    t,
				Kind: "typhon_s3_activate",
				Who:  op.spec.Name,
			})
		}
	}
}

// AcquireS3Lock 在常规攻击范围内锁定优先级最高的目标
func (r *TyphonRuntime) AcquireS3Lock(op *operator, enemies []*enemy) *enemy {
	targets := pickTargets(op, enemies, 1, 0)
	if len(targets) > 0 {
		r.S3LockedTargetIndex = targets[0].index
		return targets[0]
	}
	r.S3LockedTargetIndex = -1
	return nil
}

// GetLockedEnemy 获取当前锁定的敌人对象（若存活且在场上）
func (r *TyphonRuntime) GetLockedEnemy(enemies []*enemy) *enemy {
	if r.S3LockedTargetIndex < 0 {
		return nil
	}
	for _, e := range enemies {
		if e != nil && e.index == r.S3LockedTargetIndex && e.alive() && !e.leaked && !e.offMap {
			return e
		}
	}
	return nil
}

// EffectiveDEF 计算第一天赋破甲后的目标有效防御力
func (r *TyphonRuntime) EffectiveDEF(target *enemy) float64 {
	if target == nil {
		return 0
	}
	baseDEF := target.spec.DEF
	if !r.Config.T1Unlocked || r.T1Stacks <= 0 || r.T1Timer <= 0 || target.index != r.T1TargetIndex {
		return baseDEF
	}
	penRatio := r.Config.T1DefPenetrate * float64(r.T1Stacks)
	if penRatio > 1.0 {
		penRatio = 1.0
	}
	if penRatio < 0 {
		penRatio = 0
	}
	return math.Max(0.0, baseDEF*(1.0-penRatio))
}

// RecordHit 命中敌人时推进第一天赋连击层数
func (r *TyphonRuntime) RecordHit(target *enemy) {
	if target == nil || !r.Config.T1Unlocked {
		return
	}
	if target.index == r.T1TargetIndex && r.T1Timer > 0 {
		if r.T1Stacks < r.Config.T1MaxStackCnt {
			r.T1Stacks++
		}
		r.T1Timer = r.Config.T1Duration
	} else {
		r.T1TargetIndex = target.index
		r.T1Stacks = 1
		r.T1Timer = r.Config.T1Duration
	}
}

// CheckT2 检查第二天赋未阻挡增伤与停顿
func (r *TyphonRuntime) CheckT2(target *enemy) (scale float64, applySluggish bool) {
	if !r.Config.T2Unlocked || target == nil {
		return 1.0, false
	}
	if target.blockedBy == nil {
		scale = r.Config.T2AtkScale
		if scale <= 0 {
			scale = 1.0
		}
		return scale, true
	}
	return 1.0, false
}

// CheckModX 检查模组 X 重量 >= min_weight 时的攻击力提升
func (r *TyphonRuntime) CheckModX(target *enemy) float64 {
	if target == nil || r.Config.ModXAtkScale <= 0 {
		return 1.0
	}
	if target.weight() >= r.Config.ModXMinWeight {
		return r.Config.ModXAtkScale
	}
	return 1.0
}

// CheckModY 检查模组 Y 远距离伤害加成
func (r *TyphonRuntime) CheckModY(opPos, targetPos [2]float64) float64 {
	if r.Config.ModYDamageScale <= 0 {
		return 1.0
	}
	dist := math.Hypot(targetPos[0]-opPos[0], targetPos[1]-opPos[1])
	if dist <= r.Config.ModYMinDist {
		return 1.0
	}
	if dist >= r.Config.ModYMaxDist {
		return 1.0 + r.Config.ModYDamageScale
	}
	ratio := (dist - r.Config.ModYMinDist) / (r.Config.ModYMaxDist - r.Config.ModYMinDist)
	return 1.0 + r.Config.ModYDamageScale*ratio
}
