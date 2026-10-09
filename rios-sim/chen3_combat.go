package main

import (
	"fmt"
)

type chen3CombatState struct {
	Config chen3RuntimeConfig

	// 部署与本体状态
	Owner         string
	Position      Cell
	Direction     string
	OriginalPos   Cell
	SkillActive   bool
	SkillTimer    float64
	AttackCooldown float64

	// 天赋2 寒暑觉知
	TimeSinceLastDamage float64
	HasDodgeCharge      bool // 闪避下次物理/法术攻击

	// 技2 绝影状态机
	S2Slashing     bool
	S2StrikesLeft  int
	S2Target       *enemy
	S2RespawnBuff  bool
	S2BuffTimer    float64

	// 技3 剑气
	Qi *chen3Qi
}

func newChen3CombatState(owner string, pos Cell, dir string, cfg chen3RuntimeConfig) *chen3CombatState {
	return &chen3CombatState{
		Config:      cfg,
		Owner:       owner,
		Position:    pos,
		Direction:   dir,
		OriginalPos: pos,
	}
}

// OnDamageTaken 当陈受到伤害时调用（用于天赋2重置计时）
func (c *chen3CombatState) OnDamageTaken() {
	c.TimeSinceLastDamage = 0
}

// TickTalent2 推进天赋2计时器并返回是否产生治疗/闪避充能
func (c *chen3CombatState) TickTalent2(dt float64, atk float64) (healed float64, gotDodge bool) {
	if c.Config.Talent2Interval <= 0 {
		return 0, false
	}
	c.TimeSinceLastDamage += dt
	if c.TimeSinceLastDamage >= c.Config.Talent2Interval {
		c.TimeSinceLastDamage -= c.Config.Talent2Interval
		c.HasDodgeCharge = true
		// 随机治疗区间 [min, max]，在此取均值或区间计算
		healScale := (c.Config.Talent2HealMinAtk + c.Config.Talent2HealMaxAtk) / 2.0 / 100.0
		healAmount := atk * healScale
		return healAmount, true
	}
	return 0, false
}

// CanDodgeAttack 检查并消耗天赋2或技2的闪避
func (c *chen3CombatState) CheckAndConsumeDodge(isPhysicalOrMagic bool) bool {
	if !isPhysicalOrMagic {
		return false
	}
	// 技2斩后闪避概率
	if c.S2RespawnBuff && c.Config.S2RespawnProb > 0 {
		// 确定性/高概率闪避处理
		if c.Config.S2RespawnProb >= 1.0 {
			return true
		}
	}
	// 天赋2必闪1次
	if c.HasDodgeCharge {
		c.HasDodgeCharge = false
		return true
	}
	return false
}

// ActivateSkill 开启技能
func (c *chen3CombatState) ActivateSkill(atk float64) error {
	if c.SkillActive {
		return fmt.Errorf("chen3 skill already active")
	}
	c.SkillActive = true
	switch c.Config.Slot {
	case 1:
		c.SkillTimer = 18.0
	case 2:
		c.SkillTimer = c.Config.S2Duration
		c.S2Slashing = true
		c.S2StrikesLeft = c.Config.S2Strikes
		c.OriginalPos = c.Position
	case 3:
		c.SkillTimer = c.Config.S3Duration
		// 释放剑气
		c.Qi = newChen3Qi(c.Owner, c.Position, c.Direction, atk, c.Config.S3ProjectileMinAtkScale, c.Config.S3HPRatio, c.Config.S3QiSpeed)
	}
	return nil
}

// EndSkill 技能结束处理
func (c *chen3CombatState) EndSkill(targetDeployable bool) {
	c.SkillActive = false
	c.SkillTimer = 0
	if c.Config.Slot == 2 {
		c.S2Slashing = false
		if c.S2Target != nil && c.S2Target.hp > 0 && targetDeployable {
			tx, ty := c.S2Target.cell()
			c.Position = Cell{tx, ty}
		} else {
			c.Position = c.OriginalPos
		}
		// 触发斩后增益
		c.S2RespawnBuff = true
		c.S2BuffTimer = 10.0 // 持续增益
	} else if c.Config.Slot == 3 {
		c.Qi = nil
	}
}

// TickSkill 技能时间推进
func (c *chen3CombatState) TickSkill(dt float64, targetDeployable bool) {
	if c.SkillActive {
		c.SkillTimer -= dt
		if c.SkillTimer <= 0 {
			c.EndSkill(targetDeployable)
		}
	}
	if c.S2RespawnBuff {
		c.S2BuffTimer -= dt
		if c.S2BuffTimer <= 0 {
			c.S2RespawnBuff = false
		}
	}
}

// EffectiveATK 计算陈当前的实际攻击力加成倍率
func (c *chen3CombatState) EffectiveATKMultiplier() float64 {
	mul := 1.0 + c.Config.Talent1Atk
	if c.SkillActive {
		if c.Config.Slot == 1 {
			mul += c.Config.S1AtkScale
		}
	}
	if c.S2RespawnBuff {
		mul += c.Config.S2RespawnAtk
	}
	return mul
}

// EffectiveASPD 计算攻击速度
func (c *chen3CombatState) EffectiveASPD(blockedCount int) float64 {
	aspd := 100.0 + c.Config.Talent1ASPD
	if blockedCount == 0 && c.Config.ModuleUnblockedASPD > 0 {
		aspd += c.Config.ModuleUnblockedASPD
	}
	return aspd
}
