package main

import (
	"fmt"
)

// LingRecycleReason 标记召唤物离场原因
type LingRecycleReason string

const (
	LingRecycleDefeated LingRecycleReason = "defeated" // 被击倒
	LingRecycleSkill2   LingRecycleReason = "skill2"   // 技2 结束半血回收
	LingRecycleFusion   LingRecycleReason = "fusion"   // 技3 合体吸收
	LingRecycleRetreat  LingRecycleReason = "retreat"  // 手动撤退
)

// LingCombatState 管理令本体及其全部召唤物的战斗循环、技能状态与第二天赋
type LingCombatState struct {
	Deployment LingDeploymentState
	OwnerAtk   float64 // 令本体的基础攻击力

	// 技能运行时状态
	SkillActive    bool
	SkillTimer     float64 // 技能剩余持续时间
	SkillCharges   int     // 充能层数 (主要用于 S2)
	SkillSP        float64 // 当前 SP
	SkillMaxSP     float64 // 技力消耗

	// 第二天赋「随付笺咏醉屠苏」叠层状态
	Talent2Stacks int // 当前叠加层数 (0 ~ 5)
}

func newLingCombatState(owner string, cfg lingRuntimeConfig, ownerAtk, spCost, initSp float64) LingCombatState {
	charges := 0
	if cfg.Slot == 2 {
		charges = 1
	}
	return LingCombatState{
		Deployment:   newLingDeploymentState(owner, cfg),
		OwnerAtk:     ownerAtk,
		SkillSP:      initSp,
		SkillMaxSP:   spCost,
		SkillCharges: charges,
	}
}

// EffectiveOwnerAtk 返回令本体计入第二天赋与技能后的有效攻击力
func (c *LingCombatState) EffectiveOwnerAtk() float64 {
	scale := 1.0 + float64(c.Talent2Stacks)*c.Deployment.Config.Talent2AtkRatio
	if c.SkillActive {
		switch c.Deployment.Config.Slot {
		case 1:
			scale += c.Deployment.Config.S1AtkBuff
		case 3:
			scale += c.Deployment.Config.S3AtkBuff
		}
	}
	return c.OwnerAtk * scale
}

// EffectiveTokenStats 计算召唤物计入技能增益后的当前攻防与攻速
func (c *LingCombatState) EffectiveTokenStats(t *LingTokenEntity) (atk, def, aspd float64, isMagic bool) {
	atk = t.Atk
	def = t.Def
	aspd = 100.0

	// 基础伤害类型：清平/弦惊基础形态为物理；逍遥与弦惊高级形态为法术
	if t.TokenKey == lingTokenSoul2 || t.Form == LingFormFused {
		isMagic = true
	} else {
		isMagic = false
	}

	if c.SkillActive {
		switch c.Deployment.Config.Slot {
		case 1:
			atk *= (1.0 + c.Deployment.Config.S1AtkBuff)
			aspd += c.Deployment.Config.S1ASPD
			isMagic = true // 技1 开启清平变为法术伤害
		case 3:
			atk *= (1.0 + c.Deployment.Config.S3AtkBuff)
			def *= (1.0 + c.Deployment.Config.S3DefBuff)
		}
	}
	return atk, def, aspd, isMagic
}

// NotifyTokenRemoval 处理召唤物离场（被击倒/吸收/回收/撤退），触发第二天赋
func (c *LingCombatState) NotifyTokenRemoval(t *LingTokenEntity, reason LingRecycleReason, availableSquadDeploySlots *int) {
	if !t.Alive {
		return
	}
	t.Alive = false

	// 返还团队部署位（普通返还1，合体高级返还2）
	if availableSquadDeploySlots != nil {
		*availableSquadDeploySlots += t.DeploySlots
	}

	// 触发第二天赋「随付笺咏醉屠苏」：获得技力 + 攻击力叠层（最多5层）
	if reason == LingRecycleDefeated || reason == LingRecycleSkill2 || reason == LingRecycleFusion || reason == LingRecycleRetreat {
		c.SkillSP += c.Deployment.Config.Talent2SP
		if c.SkillSP > c.SkillMaxSP {
			c.SkillSP = c.SkillMaxSP
		}
		if c.Talent2Stacks < c.Deployment.Config.Talent2MaxStack {
			c.Talent2Stacks++
		}
	}

	// 技2 回收还返还库存
	if reason == LingRecycleSkill2 {
		c.Deployment.AddInventory(1)
	}
}

// TriggerSkill 激活技能
func (c *LingCombatState) TriggerSkill(now float64, enemies []*enemy, verdict *Verdict) error {
	if c.SkillActive && c.Deployment.Config.Slot != 2 {
		return fmt.Errorf("ling skill already active")
	}

	switch c.Deployment.Config.Slot {
	case 1:
		c.SkillActive = true
		c.SkillTimer = c.Deployment.Config.S1Duration
		c.Deployment.AddInventory(c.Deployment.Config.S1SupplyCnt) // 开启获得 1 个库存
	case 2:
		// 技2 瞬发充能技能
		if c.SkillCharges <= 0 && c.SkillSP < c.SkillMaxSP {
			return fmt.Errorf("ling skill 2 not ready")
		}
		if c.SkillCharges > 0 {
			c.SkillCharges--
		} else {
			c.SkillSP = 0
		}
		// 执行对范围内最多2名敌人的法术打击与束缚，并在结束时回收生命值低于一半的逍遥
		if err := c.executeSkill2(now, enemies, verdict); err != nil {
			return err
		}
	case 3:
		c.SkillActive = true
		c.SkillTimer = c.Deployment.Config.S3Duration
		// 重置所有存活弦惊的周围脉冲计时器
		for _, t := range c.Deployment.ActiveTokens() {
			t.PulseTimer = 0
		}
	}
	return nil
}

// executeSkill2 执行技2法伤、束缚与半血回收
func (c *LingCombatState) executeSkill2(now float64, enemies []*enemy, verdict *Verdict) error {
	atkScale := c.Deployment.Config.S2AtkScale
	duration := c.Deployment.Config.S2Duration

	// 令本体与所有在场的逍遥分别索敌
	unitsToStrike := []*LingTokenEntity(nil)
	for _, t := range c.Deployment.ActiveTokens() {
		if t.TokenKey == lingTokenSoul2 {
			unitsToStrike = append(unitsToStrike, t)
		}
	}

	// 令本体攻击（最多2名）
	ownerDamage := c.EffectiveOwnerAtk() * atkScale
	c.strikeTargetsInCellRange(ownerDamage, duration, 2, enemies, now, verdict)

	// 各逍遥发动攻击
	for _, tok := range unitsToStrike {
		tokDamage := tok.Atk * atkScale
		c.strikeTargetsInCellRange(tokDamage, duration, 2, enemies, now, verdict)
	}

	// 技能结算时回收生命值低于一半的逍遥
	for _, tok := range unitsToStrike {
		if tok.CurrentHp < tok.MaxHp*c.Deployment.Config.S2RecycleHPRatio {
			c.NotifyTokenRemoval(tok, LingRecycleSkill2, nil)
		}
	}

	return nil
}

func (c *LingCombatState) strikeTargetsInCellRange(damage, rootDuration float64, maxTargets int, enemies []*enemy, now float64, verdict *Verdict) {
	hitCount := 0
	for _, e := range enemies {
		if e == nil || e.hp <= 0 {
			continue
		}
		// 施加法术伤害
		actualDmg := damage * (1.0 - e.res()/100.0)
		if actualDmg < damage*0.05 {
			actualDmg = damage * 0.05
		}
		e.hp -= actualDmg
		if e.hp < 0 {
			e.hp = 0
		}

		hitCount++
		if hitCount >= maxTargets {
			break
		}
	}
}

// TickCombatFrame 每帧推进状态机（SP 回复、技能持续、技3弦惊十字脉冲）
func (c *LingCombatState) TickCombatFrame(dt, now float64, enemies []*enemy, availableSquadDeploySlots *int, verdict *Verdict) {
	if dt <= 0 {
		return
	}

	// 1. SP 自然充能
	if !c.SkillActive {
		c.SkillSP += dt
		if c.Deployment.Config.Slot == 2 {
			// 充能型技能
			if c.SkillSP >= c.SkillMaxSP {
				if c.SkillCharges < c.Deployment.Config.S2MaxCharges {
					c.SkillCharges++
					c.SkillSP -= c.SkillMaxSP
				} else {
					c.SkillSP = c.SkillMaxSP
				}
			}
		} else {
			if c.SkillSP >= c.SkillMaxSP {
				c.SkillSP = c.SkillMaxSP
			}
		}
	} else {
		// 技能持续时间递减
		c.SkillTimer -= dt
		if c.SkillTimer <= 0 {
			c.SkillActive = false
			c.SkillTimer = 0
			// 技3 结束时令获得 1 个召唤物
			if c.Deployment.Config.Slot == 3 {
				c.Deployment.AddInventory(c.Deployment.Config.S3SupplyCnt)
			}
		}
	}

	// 2. 技3 激活态下弦惊的周期性四格法术脉冲
	if c.SkillActive && c.Deployment.Config.Slot == 3 {
		pulseInterval := c.Deployment.Config.S3PulseInterval // 0.5s
		pulseDmg := c.EffectiveOwnerAtk() * c.Deployment.Config.S3PulseScale // 20% 令攻击力

		for _, t := range c.Deployment.ActiveTokens() {
			if t.TokenKey != lingTokenSoul3 {
				continue
			}
			t.PulseTimer += dt
			if t.PulseTimer >= pulseInterval {
				t.PulseTimer -= pulseInterval
				// 对周围十字四格敌人造成伤害
				c.pulseAOE(t.Cell, pulseDmg, enemies, now, verdict)
			}
		}
	}
}

// pulseAOE 对指定坐标周围四格进行法术伤害判定
func (c *LingCombatState) pulseAOE(center Cell, dmg float64, enemies []*enemy, now float64, verdict *Verdict) {
	crossOffsets := [][2]int{{0, 1}, {0, -1}, {1, 0}, {-1, 0}}
	for _, e := range enemies {
		if e == nil || e.hp <= 0 {
			continue
		}
		// 检查是否在周围四格
		dx, dy := e.cell()
		dx -= center[0]
		dy -= center[1]
		for _, off := range crossOffsets {
			if dx == off[0] && dy == off[1] {
				actualDmg := dmg * (1.0 - e.res()/100.0)
				if actualDmg < dmg*0.05 {
					actualDmg = dmg * 0.05
				}
				e.hp -= actualDmg
				if e.hp < 0 {
					e.hp = 0
				}
				break
			}
		}
	}
}
