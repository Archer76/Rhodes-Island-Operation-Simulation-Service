package main

import (
	"fmt"
	"math"
)

// RadianSimTickResult 记录一个 sim tick 内电弧体系产生的动作与事件
type RadianSimTickResult struct {
	DamageEvents []RadianDamageEvent
	TokensKilled []uint64
	SkillEnded   bool
}

type RadianDamageEvent struct {
	SourceID        string  // "radian" 或 token key
	TargetID        string  // 敌人 ID
	Damage          float64 // 伤害量
	IsMagic         bool    // 是否法术伤害
	ApplySluggish   float64 // 施加停顿持续时间 (0.0 表示无)
	ApplyFragile    float64 // 施加法术脆弱持续时间 (0.0 表示无)
	FragileScale    float64 // 脆弱倍率加成 (1.1 ~ 1.35)
}

// TickRadian 执行电弧及其召唤物的一个逻辑帧更新 (dt 通常为 1.0/30.0 秒)
func (c *RadianCombatState) TickRadian(dt float64, now float64, availableSquadDeploySlots *int) RadianSimTickResult {
	res := RadianSimTickResult{}

	// 1. 技能持续与 SP 回复推进
	if c.SkillActive {
		c.SkillTimer -= dt
		if c.SkillTimer <= 1e-6 {
			c.FinishSkill(now)
			res.SkillEnded = true
		}
	} else {
		// 常态自动自然回复 SP (1.0 SP/s)
		if c.SkillSP < c.SkillMaxSP {
			c.SkillSP = math.Min(c.SkillMaxSP, c.SkillSP+dt*1.0)
		}
	}

	// 2. 召唤物攻击与计时推进
	for _, t := range c.Deployment.ActiveTokens() {
		if !t.Alive {
			continue
		}
		if t.AttackTimer > 0 {
			t.AttackTimer -= dt
		}
	}

	return res
}

// RadianHitTarget 统一计算对目标的攻击伤害与弱化效果
func (c *RadianCombatState) RadianHitTarget(t *RadianTokenEntity, targetID string, enemyRes float64) RadianDamageEvent {
	var atk, def, aspd float64
	var isMagic bool
	sourceID := "radian"

	if t != nil {
		atk, def, aspd, isMagic = c.EffectiveTokenStats(t)
		sourceID = fmt.Sprintf("radian_token_%d", t.ID)
		_ = def
		_ = aspd
	} else {
		effAtk, _ := c.EffectiveOwnerStats()
		atk = effAtk
		isMagic = true // 电弧特性：攻击造成法术伤害
	}

	// 计算基础伤害
	dmg := atk
	if isMagic {
		// 法术减伤公式: dmg * (100 - res) / 100，最低 5% 伤害保底
		resRatio := math.Max(0.0, (100.0-enemyRes)/100.0)
		dmg = math.Max(atk*0.05, atk*resRatio)
	}

	evt := RadianDamageEvent{
		SourceID: sourceID,
		TargetID: targetID,
		Damage:   dmg,
		IsMagic:  isMagic,
	}

	// 技能三【手牵手】效果：对敌人造成法术伤害时，施加停顿与法术脆弱
	if c.SkillActive && c.Deployment.Config.Slot == 3 && isMagic {
		evt.ApplySluggish = c.Deployment.Config.S3SluggishDuration
		evt.ApplyFragile = c.Deployment.Config.S3MagicFragileDuration
		evt.FragileScale = c.Deployment.Config.S3DamageScale
		// 受到法术脆弱倍率加成
		evt.Damage *= evt.FragileScale
	}

	return evt
}
